"""Pruebas del triaje de soporte (tarea BE-21, RF10 y RF12).

Endpoints probados:
- `PATCH /api/v1/support/tickets/{id}/clasificar/`
- `POST  /api/v1/support/tickets/{id}/no-procedente/`

Criterios de aceptación cubiertos:
- Clasificar actualiza `clasificacion` (y `prioridad` si se envía) y crea un
  `TicketItem(tipo_accion='CLASIFICACION')` con el agente como actor.
- No procedente rechaza un motivo vacío con 400 y bloquea los cambios de estado
  inválidos (desde "Resuelto" o "No procedente").
- Transiciones válidas e inválidas, permisos por rol y búsqueda por id o radicado.

Ejecutar solo estas pruebas:
    pytest apps/tickets/tests/test_support_triage.py -v
"""

import pytest
from rest_framework.test import APIClient

from apps.companies.models import Empresa, ModuloContratado, RolChoices, Usuario
from apps.tickets.models import (
    ClasificacionChoices,
    EstadoChoices,
    PrioridadChoices,
    Ticket,
    TicketItem,
    TipoAccionChoices,
)

pytestmark = pytest.mark.django_db


def url_clasificar(lookup):
    return f"/api/v1/support/tickets/{lookup}/clasificar/"


def url_no_procedente(lookup):
    return f"/api/v1/support/tickets/{lookup}/no-procedente/"


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
        nombre="Agente Soporte",
        rol=RolChoices.AGENTE_SOPORTE,
    )


@pytest.fixture
def responsable():
    return Usuario.objects.create_user(
        correo="dev@datak.co",
        password="Clave#2026",
        nombre="Dev Datak",
        rol=RolChoices.RESPONSABLE_ATENCION,
    )


@pytest.fixture
def ticket(empresa, cliente):
    """Ticket recién creado: estado Abierto, prioridad Media, sin clasificar."""
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
# PATCH /clasificar/  (RF10)
# --------------------------------------------------------------------------


def test_agente_clasifica_y_cambia_prioridad(agente, ticket):
    respuesta = cliente_api(agente).patch(
        url_clasificar(ticket.id),
        {"clasificacion": ClasificacionChoices.BUG, "prioridad": PrioridadChoices.ALTA},
        format="json",
    )

    assert respuesta.status_code == 200
    ticket.refresh_from_db()
    assert ticket.clasificacion == "Bug"
    assert ticket.prioridad == "Alta"
    # Clasificar no cambia el estado.
    assert ticket.estado == EstadoChoices.ABIERTO

    # Se creó el registro del historial con el agente como actor.
    item = TicketItem.objects.get(ticket=ticket)
    assert item.tipo_accion == TipoAccionChoices.CLASIFICACION
    assert item.actor == agente
    assert item.es_interna is True
    assert "Bug" in item.observaciones
    assert "Media -> Alta" in item.observaciones

    # La respuesta es el detalle completo, con el nuevo evento en el historial.
    assert respuesta.data["clasificacion"] == "Bug"
    assert respuesta.data["prioridad"] == "Alta"
    assert respuesta.data["historial"][-1]["tipo_accion"] == "CLASIFICACION"


def test_clasificar_sin_prioridad_conserva_la_actual(agente, ticket):
    respuesta = cliente_api(agente).patch(
        url_clasificar(ticket.id),
        {"clasificacion": ClasificacionChoices.ERROR_DE_USO},
        format="json",
    )

    assert respuesta.status_code == 200
    ticket.refresh_from_db()
    assert ticket.clasificacion == "Error de uso"
    assert ticket.prioridad == PrioridadChoices.MEDIA
    assert TicketItem.objects.filter(ticket=ticket).count() == 1


def test_clasificar_buscando_por_radicado(agente, ticket):
    respuesta = cliente_api(agente).patch(
        url_clasificar(ticket.radicado),
        {"clasificacion": ClasificacionChoices.SOLICITUD_DE_MEJORA},
        format="json",
    )

    assert respuesta.status_code == 200
    ticket.refresh_from_db()
    assert ticket.clasificacion == "Solicitud de mejora"


@pytest.mark.parametrize(
    "cuerpo, campo_con_error",
    [
        ({}, "clasificacion"),
        ({"clasificacion": "Otra cosa"}, "clasificacion"),
        ({"clasificacion": "Bug", "prioridad": "Urgentísima"}, "prioridad"),
    ],
)
def test_clasificar_datos_invalidos_responde_400(agente, ticket, cuerpo, campo_con_error):
    respuesta = cliente_api(agente).patch(url_clasificar(ticket.id), cuerpo, format="json")

    assert respuesta.status_code == 400
    assert campo_con_error in respuesta.data
    # No se guardó nada.
    ticket.refresh_from_db()
    assert ticket.clasificacion is None
    assert not TicketItem.objects.filter(ticket=ticket).exists()


def test_clasificar_ticket_inexistente_responde_404(agente):
    respuesta = cliente_api(agente).patch(
        url_clasificar(999999), {"clasificacion": "Bug"}, format="json"
    )
    assert respuesta.status_code == 404


# --------------------------------------------------------------------------
# POST /no-procedente/  (RF12)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("estado_inicial", [EstadoChoices.ABIERTO, EstadoChoices.EN_GESTION])
def test_agente_marca_no_procedente_desde_estado_valido(agente, ticket, estado_inicial):
    Ticket.objects.filter(pk=ticket.pk).update(estado=estado_inicial)
    motivo = "La solicitud no corresponde a soporte del ERP."

    respuesta = cliente_api(agente).post(
        url_no_procedente(ticket.id), {"motivo_no_procedente": motivo}, format="json"
    )

    assert respuesta.status_code == 200
    ticket.refresh_from_db()
    assert ticket.estado == EstadoChoices.NO_PROCEDENTE
    assert ticket.motivo_no_procedente == motivo
    assert ticket.fecha_resolucion is not None

    item = TicketItem.objects.get(ticket=ticket)
    assert item.tipo_accion == TipoAccionChoices.NO_PROCEDENTE
    assert item.actor == agente
    assert item.estado_anterior == estado_inicial
    assert item.estado_nuevo == EstadoChoices.NO_PROCEDENTE
    assert item.es_interna is False
    assert item.observaciones == motivo

    assert respuesta.data["estado"] == "No procedente"


def test_no_procedente_quita_espacios_del_motivo(agente, ticket):
    respuesta = cliente_api(agente).post(
        url_no_procedente(ticket.radicado),
        {"motivo_no_procedente": "   Duplicado del TK-2026-000002.   "},
        format="json",
    )

    assert respuesta.status_code == 200
    ticket.refresh_from_db()
    assert ticket.motivo_no_procedente == "Duplicado del TK-2026-000002."


@pytest.mark.parametrize(
    "cuerpo",
    [{}, {"motivo_no_procedente": ""}, {"motivo_no_procedente": "     "}],
    ids=["sin-motivo", "motivo-vacio", "solo-espacios"],
)
def test_no_procedente_sin_motivo_responde_400(agente, ticket, cuerpo):
    respuesta = cliente_api(agente).post(url_no_procedente(ticket.id), cuerpo, format="json")

    assert respuesta.status_code == 400
    assert "motivo_no_procedente" in respuesta.data
    ticket.refresh_from_db()
    assert ticket.estado == EstadoChoices.ABIERTO
    assert ticket.fecha_resolucion is None
    assert not TicketItem.objects.filter(ticket=ticket).exists()


@pytest.mark.parametrize("estado_cerrado", [EstadoChoices.RESUELTO, EstadoChoices.NO_PROCEDENTE])
def test_no_procedente_bloquea_tickets_cerrados(agente, ticket, estado_cerrado):
    Ticket.objects.filter(pk=ticket.pk).update(
        estado=estado_cerrado, motivo_no_procedente="", comentario_solucion=""
    )

    respuesta = cliente_api(agente).post(
        url_no_procedente(ticket.id), {"motivo_no_procedente": "Otro motivo"}, format="json"
    )

    assert respuesta.status_code == 400
    assert "estado" in respuesta.data
    ticket.refresh_from_db()
    assert ticket.estado == estado_cerrado
    assert ticket.motivo_no_procedente == ""
    assert not TicketItem.objects.filter(ticket=ticket).exists()


def test_no_procedente_ticket_inexistente_responde_404(agente):
    respuesta = cliente_api(agente).post(
        url_no_procedente("TK-2026-999999"), {"motivo_no_procedente": "x"}, format="json"
    )
    assert respuesta.status_code == 404


# --------------------------------------------------------------------------
# Permisos (sección 5.4: estas acciones son del Agente)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("quien", ["responsable", "cliente"])
@pytest.mark.parametrize("accion", ["clasificar", "no-procedente"])
def test_solo_el_agente_puede_hacer_triaje(request, ticket, quien, accion):
    usuario = request.getfixturevalue(quien)
    api = cliente_api(usuario)

    if accion == "clasificar":
        respuesta = api.patch(url_clasificar(ticket.id), {"clasificacion": "Bug"}, format="json")
    else:
        respuesta = api.post(
            url_no_procedente(ticket.id), {"motivo_no_procedente": "x"}, format="json"
        )

    assert respuesta.status_code == 403
    ticket.refresh_from_db()
    assert ticket.clasificacion is None
    assert ticket.estado == EstadoChoices.ABIERTO


def test_sin_token_responde_401(ticket):
    api = cliente_api()
    assert api.patch(url_clasificar(ticket.id), {"clasificacion": "Bug"}).status_code == 401
    assert api.post(url_no_procedente(ticket.id), {"motivo_no_procedente": "x"}).status_code == 401


# --------------------------------------------------------------------------
# Lo que ve el cliente después del triaje (RNF2)
# --------------------------------------------------------------------------


def test_cliente_ve_el_no_procedente_pero_no_la_clasificacion(agente, cliente, ticket):
    api_agente = cliente_api(agente)
    api_agente.patch(url_clasificar(ticket.id), {"clasificacion": "Error de uso"}, format="json")
    api_agente.post(
        url_no_procedente(ticket.id),
        {"motivo_no_procedente": "Se orientó al usuario por correo."},
        format="json",
    )

    respuesta = cliente_api(cliente).get(f"/api/v1/client/tickets/{ticket.radicado}/")

    assert respuesta.status_code == 200
    assert respuesta.data["estado"] == "No procedente"
    assert respuesta.data["motivo_no_procedente"] == "Se orientó al usuario por correo."
    tipos = [evento["tipo_accion"] for evento in respuesta.data["historial"]]
    assert tipos == ["NO_PROCEDENTE"]
