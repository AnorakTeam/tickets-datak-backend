"""Pruebas del detalle de ticket: GET /api/v1/client/tickets/{radicado}/ (BE-13, issue #26).

Cubren los criterios de aceptación de la tarea:
- Se devuelve el detalle correcto de un ticket de la propia empresa.
- Pedir el radicado de un ticket de otra empresa responde 404.
- Ningún dato de gestión interna aparece en el JSON.
Además prueban el historial público (sin notas internas) y los permisos.

Ejecutar solo estas pruebas:
    pytest apps/tickets/tests/test_client_ticket_detail.py -v
"""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.companies.models import Empresa, ModuloContratado, RolChoices, Usuario
from apps.tickets.models import EstadoChoices, Ticket, TicketItem, TipoAccionChoices

# Campos exactos que puede ver el cliente en el detalle.
CAMPOS_PERMITIDOS = {
    "radicado",
    "estado",
    "prioridad",
    "asunto",
    "descripcion",
    "modulo_nombre",
    "pestana_o_documento",
    "mensaje_error",
    "canal_origen",
    "fecha_creacion",
    "fecha_actualizacion",
    "fecha_resolucion",
    "comentario_solucion",
    "motivo_no_procedente",
    "historial",
}

# Campos internos que NUNCA deben aparecer (RNF2).
CAMPOS_INTERNOS = {
    "id",
    "empresa",
    "responsable",
    "registrado_por_agente",
    "creado_por",
    "clasificacion",
}


def url(radicado):
    return f"/api/v1/client/tickets/{radicado}/"


# --------------------------------------------------------------------------
# Fixtures
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
def ticket_resuelto(empresa, cliente, agente, responsable):
    """Ticket ya resuelto, con responsable asignado y un historial que mezcla
    eventos públicos y una nota interna."""
    modulo = ModuloContratado.objects.create(
        empresa=empresa, codigo="FACTURACION", nombre="Facturación Electrónica"
    )
    ticket = Ticket.objects.create(
        radicado="TK-2026-000001",
        empresa=empresa,
        creado_por=cliente,
        modulo=modulo,
        pestana_o_documento="Emisión de Facturas / F-203",
        asunto="Error 500 al emitir factura",
        descripcion="Al timbrar la factura el sistema arroja error de servidor.",
        mensaje_error="Server Error: RetencionCalculatorException",
        prioridad="Alta",
        estado=EstadoChoices.RESUELTO,
        clasificacion="Bug",
        responsable=responsable,
        registrado_por_agente=agente,
        comentario_solucion="Se corrigió la regla de validación de retención.",
        fecha_resolucion=timezone.now(),
    )
    TicketItem.objects.create(
        ticket=ticket,
        actor=cliente,
        tipo_accion=TipoAccionChoices.CREACION,
        estado_nuevo=EstadoChoices.ABIERTO,
        observaciones="Ticket creado desde el portal.",
    )
    TicketItem.objects.create(
        ticket=ticket,
        actor=agente,
        tipo_accion=TipoAccionChoices.NOTA_INTERNA,
        es_interna=True,
        observaciones="NOTA SECRETA: revisar con el equipo de facturación.",
    )
    TicketItem.objects.create(
        ticket=ticket,
        actor=responsable,
        tipo_accion=TipoAccionChoices.RESOLUCION,
        estado_anterior=EstadoChoices.EN_GESTION,
        estado_nuevo=EstadoChoices.RESUELTO,
        observaciones="Se corrigió la regla de validación de retención.",
    )
    return ticket


@pytest.fixture
def api_client(cliente):
    client = APIClient()
    client.force_authenticate(user=cliente)
    return client


# --------------------------------------------------------------------------
# Criterios de aceptación
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_returns_detail_of_own_company_ticket(api_client, ticket_resuelto):
    """El cliente recibe el detalle correcto de un ticket de su empresa."""
    response = api_client.get(url("TK-2026-000001"))

    assert response.status_code == 200
    assert response.data["radicado"] == "TK-2026-000001"
    assert response.data["estado"] == "Resuelto"
    assert response.data["prioridad"] == "Alta"
    assert response.data["asunto"] == "Error 500 al emitir factura"
    assert response.data["modulo_nombre"] == "Facturación Electrónica"
    assert response.data["pestana_o_documento"] == "Emisión de Facturas / F-203"
    assert response.data["mensaje_error"] == "Server Error: RetencionCalculatorException"
    assert response.data["comentario_solucion"] == (
        "Se corrigió la regla de validación de retención."
    )
    assert response.data["fecha_resolucion"] is not None


@pytest.mark.django_db
def test_ticket_of_another_company_returns_404(ticket_resuelto):
    """Un cliente de otra empresa recibe 404 aunque el radicado exista (no 403)."""
    otra = Empresa.objects.create(nombre="Beta Comercial S.A.S.", identificacion="800987654-3")
    intruso = Usuario.objects.create_user(
        correo="ana@beta.com", password="Clave#2026", nombre="Ana", empresa=otra
    )
    client = APIClient()
    client.force_authenticate(user=intruso)

    response = client.get(url("TK-2026-000001"))

    assert response.status_code == 404


@pytest.mark.django_db
def test_nonexistent_radicado_returns_404(api_client):
    """Un radicado que no existe responde 404 igual que uno ajeno (no se distinguen)."""
    response = api_client.get(url("TK-2026-999999"))

    assert response.status_code == 404


@pytest.mark.django_db
def test_no_internal_fields_are_exposed(api_client, ticket_resuelto):
    """El JSON trae exactamente los campos permitidos y ninguno interno (RNF2)."""
    data = api_client.get(url("TK-2026-000001")).data

    assert set(data) == CAMPOS_PERMITIDOS
    assert not CAMPOS_INTERNOS & set(data)
    # Tampoco aparecen los nombres o correos del personal interno en ningún lado.
    texto = str(data)
    assert "Dev Datak" not in texto
    assert "dev@datak.co" not in texto
    assert "agente@datak.co" not in texto


# --------------------------------------------------------------------------
# Historial (línea de tiempo)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_history_excludes_internal_notes(api_client, ticket_resuelto):
    """El historial trae los eventos públicos en orden y omite las notas internas."""
    historial = api_client.get(url("TK-2026-000001")).data["historial"]

    assert [evento["tipo_accion"] for evento in historial] == ["CREACION", "RESOLUCION"]
    assert "NOTA SECRETA" not in str(historial)


@pytest.mark.django_db
def test_history_items_do_not_expose_actor(api_client, ticket_resuelto):
    """Cada evento solo trae campos seguros: ni actor, ni responsable, ni es_interna."""
    evento = api_client.get(url("TK-2026-000001")).data["historial"][1]

    assert set(evento) == {
        "tipo_accion",
        "estado_anterior",
        "estado_nuevo",
        "observaciones",
        "fecha_creacion",
    }
    assert evento["estado_anterior"] == "En gestion"
    assert evento["estado_nuevo"] == "Resuelto"


# --------------------------------------------------------------------------
# Permisos
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_anonymous_request_returns_401(ticket_resuelto):
    response = APIClient().get(url("TK-2026-000001"))

    assert response.status_code == 401


@pytest.mark.django_db
def test_internal_staff_gets_403(ticket_resuelto, agente):
    """El personal interno no usa el portal del cliente."""
    client = APIClient()
    client.force_authenticate(user=agente)

    response = client.get(url("TK-2026-000001"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_detail_query_count_is_constant(api_client, ticket_resuelto, django_assert_max_num_queries):
    """El detalle usa pocas consultas, sin importar cuántos eventos tenga (RNF3).

    django_assert_max_num_queries (de pytest-django) falla si se hacen más
    consultas de las indicadas: 1 ticket + módulo, 1 historial.
    """
    with django_assert_max_num_queries(2):
        api_client.get(url("TK-2026-000001"))
