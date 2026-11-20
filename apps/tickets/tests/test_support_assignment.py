"""Pruebas de asignación de responsables (tarea BE-22, RF11).

Endpoints probados:
- `PATCH /api/v1/support/tickets/{id}/asignar/`
- `GET   /api/v1/support/responsables/`

Criterios de aceptación cubiertos:
- Asignar a un usuario `cliente` responde 400.
- "Abierto" pasa a "En gestion" y se registra un `TicketItem(ASIGNACION)` tanto
  en la asignación inicial como en la reasignación.
- Listado del personal asignable (solo activos y solo roles internos).

Ejecutar solo estas pruebas:
    pytest apps/tickets/tests/test_support_assignment.py -v
"""

import pytest
from rest_framework.test import APIClient

from apps.companies.models import Empresa, ModuloContratado, RolChoices, Usuario
from apps.tickets.models import EstadoChoices, Ticket, TicketItem, TipoAccionChoices

pytestmark = pytest.mark.django_db

RESPONSABLES_URL = "/api/v1/support/responsables/"


def url_asignar(lookup):
    return f"/api/v1/support/tickets/{lookup}/asignar/"


# --------------------------------------------------------------------------
# Fixtures (datos de prueba)
# --------------------------------------------------------------------------


@pytest.fixture
def empresa():
    return Empresa.objects.create(nombre="Acme Industrial S.A.S.", identificacion="900123456-7")


@pytest.fixture
def cliente(empresa):
    return Usuario.objects.create_user(
        correo="carlos@acme.com", password="Clave#2026", nombre="Carlos Gómez", empresa=empresa
    )


@pytest.fixture
def agente():
    return Usuario.objects.create_user(
        correo="agente@datak.co",
        password="Clave#2026",
        nombre="Andrea Agente",
        rol=RolChoices.AGENTE_SOPORTE,
    )


@pytest.fixture
def responsable():
    return Usuario.objects.create_user(
        correo="dev1@datak.co",
        password="Clave#2026",
        nombre="Beatriz Dev",
        rol=RolChoices.RESPONSABLE_ATENCION,
    )


@pytest.fixture
def otro_responsable():
    return Usuario.objects.create_user(
        correo="dev2@datak.co",
        password="Clave#2026",
        nombre="Camilo Dev",
        rol=RolChoices.RESPONSABLE_ATENCION,
    )


@pytest.fixture
def responsable_inactivo():
    return Usuario.objects.create_user(
        correo="exdev@datak.co",
        password="Clave#2026",
        nombre="Diego Retirado",
        rol=RolChoices.RESPONSABLE_ATENCION,
        activo=False,
    )


@pytest.fixture
def ticket(empresa, cliente):
    """Ticket recién creado: estado Abierto y sin responsable."""
    modulo = ModuloContratado.objects.create(empresa=empresa, codigo="FACT", nombre="Facturación")
    return Ticket.objects.create(
        radicado="TK-2026-000001",
        empresa=empresa,
        creado_por=cliente,
        modulo=modulo,
        pestana_o_documento="Factura electrónica",
        asunto="Error 500 al emitir factura",
        descripcion="Al guardar la factura sale error 500.",
    )


def cliente_api(usuario=None):
    """APIClient autenticado como `usuario` (o sin autenticar si es None)."""
    api = APIClient()
    if usuario is not None:
        api.force_authenticate(user=usuario)
    return api


# --------------------------------------------------------------------------
# PATCH /asignar/
# --------------------------------------------------------------------------


def test_asignacion_inicial_pasa_de_abierto_a_en_gestion(agente, responsable, ticket):
    respuesta = cliente_api(agente).patch(
        url_asignar(ticket.id), {"responsable_id": responsable.id}, format="json"
    )

    assert respuesta.status_code == 200
    ticket.refresh_from_db()
    assert ticket.responsable == responsable
    assert ticket.estado == EstadoChoices.EN_GESTION

    item = TicketItem.objects.get(ticket=ticket)
    assert item.tipo_accion == TipoAccionChoices.ASIGNACION
    assert item.actor == agente
    assert item.responsable_asignado == responsable
    assert item.estado_anterior == EstadoChoices.ABIERTO
    assert item.estado_nuevo == EstadoChoices.EN_GESTION
    assert item.es_interna is False

    # La respuesta es el detalle completo de soporte.
    assert respuesta.data["estado"] == "En gestion"
    assert respuesta.data["responsable"]["id"] == responsable.id
    assert respuesta.data["historial"][-1]["tipo_accion"] == "ASIGNACION"


def test_reasignacion_se_queda_en_gestion_y_registra_historial(
    agente, responsable, otro_responsable, ticket
):
    api = cliente_api(agente)
    api.patch(url_asignar(ticket.id), {"responsable_id": responsable.id}, format="json")

    respuesta = api.patch(
        url_asignar(ticket.radicado), {"responsable_id": otro_responsable.id}, format="json"
    )

    assert respuesta.status_code == 200
    ticket.refresh_from_db()
    assert ticket.responsable == otro_responsable
    assert ticket.estado == EstadoChoices.EN_GESTION

    # Un registro por cada asignación (inicial + reasignación).
    items = list(TicketItem.objects.filter(ticket=ticket).order_by("fecha_creacion", "id"))
    assert [i.tipo_accion for i in items] == ["ASIGNACION", "ASIGNACION"]
    assert items[1].responsable_asignado == otro_responsable
    assert items[1].estado_anterior == EstadoChoices.EN_GESTION
    assert items[1].estado_nuevo == EstadoChoices.EN_GESTION
    assert "reasignado" in items[1].observaciones


def test_se_puede_asignar_a_un_agente_de_soporte(agente, ticket):
    respuesta = cliente_api(agente).patch(
        url_asignar(ticket.id), {"responsable_id": agente.id}, format="json"
    )

    assert respuesta.status_code == 200
    ticket.refresh_from_db()
    assert ticket.responsable == agente


def test_asignar_a_un_cliente_responde_400(agente, cliente, ticket):
    respuesta = cliente_api(agente).patch(
        url_asignar(ticket.id), {"responsable_id": cliente.id}, format="json"
    )

    assert respuesta.status_code == 400
    assert "responsable_id" in respuesta.data
    ticket.refresh_from_db()
    assert ticket.responsable is None
    assert ticket.estado == EstadoChoices.ABIERTO
    assert not TicketItem.objects.filter(ticket=ticket).exists()


@pytest.mark.parametrize(
    "cuerpo",
    [{}, {"responsable_id": "abc"}, {"responsable_id": 999999}],
    ids=["sin-responsable", "id-no-numerico", "id-inexistente"],
)
def test_asignar_datos_invalidos_responde_400(agente, ticket, cuerpo):
    respuesta = cliente_api(agente).patch(url_asignar(ticket.id), cuerpo, format="json")

    assert respuesta.status_code == 400
    assert "responsable_id" in respuesta.data
    assert not TicketItem.objects.filter(ticket=ticket).exists()


def test_asignar_a_responsable_inactivo_responde_400(agente, responsable_inactivo, ticket):
    respuesta = cliente_api(agente).patch(
        url_asignar(ticket.id), {"responsable_id": responsable_inactivo.id}, format="json"
    )

    assert respuesta.status_code == 400
    assert "responsable_id" in respuesta.data


@pytest.mark.parametrize("estado_cerrado", [EstadoChoices.RESUELTO, EstadoChoices.NO_PROCEDENTE])
def test_no_se_asigna_un_ticket_cerrado(agente, responsable, ticket, estado_cerrado):
    Ticket.objects.filter(pk=ticket.pk).update(estado=estado_cerrado)

    respuesta = cliente_api(agente).patch(
        url_asignar(ticket.id), {"responsable_id": responsable.id}, format="json"
    )

    assert respuesta.status_code == 400
    assert "estado" in respuesta.data
    ticket.refresh_from_db()
    assert ticket.estado == estado_cerrado
    assert ticket.responsable is None
    assert not TicketItem.objects.filter(ticket=ticket).exists()


def test_asignar_ticket_inexistente_responde_404(agente, responsable):
    respuesta = cliente_api(agente).patch(
        url_asignar(999999), {"responsable_id": responsable.id}, format="json"
    )
    assert respuesta.status_code == 404


@pytest.mark.parametrize("quien", ["responsable", "cliente"])
def test_solo_el_agente_puede_asignar(request, responsable, ticket, quien):
    usuario = request.getfixturevalue(quien)
    respuesta = cliente_api(usuario).patch(
        url_asignar(ticket.id), {"responsable_id": responsable.id}, format="json"
    )

    assert respuesta.status_code == 403
    ticket.refresh_from_db()
    assert ticket.responsable is None


def test_asignar_sin_token_responde_401(responsable, ticket):
    respuesta = cliente_api().patch(url_asignar(ticket.id), {"responsable_id": responsable.id})
    assert respuesta.status_code == 401


def test_cliente_ve_en_gestion_pero_no_quien_es_el_responsable(
    agente, cliente, responsable, ticket
):
    cliente_api(agente).patch(
        url_asignar(ticket.id), {"responsable_id": responsable.id}, format="json"
    )

    respuesta = cliente_api(cliente).get(f"/api/v1/client/tickets/{ticket.radicado}/")

    assert respuesta.status_code == 200
    assert respuesta.data["estado"] == "En gestion"
    assert "responsable" not in respuesta.data
    evento = respuesta.data["historial"][0]
    assert evento["tipo_accion"] == "ASIGNACION"
    assert "responsable_asignado" not in evento
    assert "actor" not in evento
    # La observación no menciona el nombre ni el correo del responsable (RNF2).
    assert responsable.nombre not in evento["observaciones"]
    assert responsable.correo not in evento["observaciones"]


# --------------------------------------------------------------------------
# GET /responsables/
# --------------------------------------------------------------------------


def test_lista_solo_personal_interno_activo_ordenado_por_nombre(
    agente, responsable, otro_responsable, responsable_inactivo, cliente
):
    respuesta = cliente_api(agente).get(RESPONSABLES_URL)

    assert respuesta.status_code == 200
    # Sin paginación: la respuesta es directamente la lista.
    assert [u["correo"] for u in respuesta.data] == [
        "agente@datak.co",  # Andrea Agente
        "dev1@datak.co",  # Beatriz Dev
        "dev2@datak.co",  # Camilo Dev
    ]
    # No aparecen el cliente ni el usuario inactivo.
    correos = {u["correo"] for u in respuesta.data}
    assert cliente.correo not in correos
    assert responsable_inactivo.correo not in correos
    # Solo los campos necesarios para el desplegable.
    assert set(respuesta.data[0].keys()) == {"id", "nombre", "correo", "rol"}


def test_responsable_de_atencion_tambien_puede_ver_la_lista(responsable):
    respuesta = cliente_api(responsable).get(RESPONSABLES_URL)
    assert respuesta.status_code == 200


def test_cliente_no_puede_ver_la_lista(cliente):
    assert cliente_api(cliente).get(RESPONSABLES_URL).status_code == 403


def test_lista_sin_token_responde_401():
    assert cliente_api().get(RESPONSABLES_URL).status_code == 401
