"""Integration tests for `POST /api/v1/chatbot/mensajes/` (Task BE-15, RF3, RF6, User Story #1).

Covers:
- Permission enforcement: 401 for anonymous, 403 for non-client staff.
- 400 Bad Request on missing / blank 'mensaje'.
- Full 4-turn reporting dialogue ending in 'Confirmar':
    * Ticket created in DB with canal_origen='Chatbot', linked to client's empresa.
    * Response contains the generated radicado.
- Cancellation flow ('Cancelar'): no ticket created.
- RF6 — specific radicado lookup: returns estado + comentario_solucion.
- RF6 — general active tickets listing for the client's company.
- Multi-tenant isolation: radicado belonging to a different company returns safe "not found".

Run:
    pytest apps/tickets/tests/test_chatbot_api.py -v
"""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.companies.models import Empresa, ModuloContratado, RolChoices, Usuario
from apps.tickets.models import (
    CanalOrigenChoices,
    EstadoChoices,
    Ticket,
    TicketItem,
    TipoAccionChoices,
)
from apps.tickets.services import TicketCreationService

ENDPOINT = "/api/v1/chatbot/mensajes/"
PASSWORD = "testpass123"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_cache():
    """Flush cache before and after every test to prevent session bleed-over."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def empresa_acme(db):
    return Empresa.objects.create(nombre="Acme Industrial S.A.S.", identificacion="900123456-7")


@pytest.fixture
def empresa_global(db):
    return Empresa.objects.create(nombre="Global Logistics Ltda.", identificacion="800987654-3")


@pytest.fixture
def cliente_acme(empresa_acme):
    return Usuario.objects.create_user(
        correo="cliente@acme.com",
        password=PASSWORD,
        nombre="Carlos Gómez",
        rol=RolChoices.CLIENTE,
        empresa=empresa_acme,
    )


@pytest.fixture
def cliente_global(empresa_global):
    return Usuario.objects.create_user(
        correo="cliente@global.com",
        password=PASSWORD,
        nombre="Lucía Morales",
        rol=RolChoices.CLIENTE,
        empresa=empresa_global,
    )


@pytest.fixture
def agente(db):
    return Usuario.objects.create_user(
        correo="agente@datak.co",
        password=PASSWORD,
        nombre="Agente Soporte",
        rol=RolChoices.AGENTE_SOPORTE,
        empresa=None,
    )


@pytest.fixture
def modulo_facturacion(empresa_acme):
    return ModuloContratado.objects.create(
        empresa=empresa_acme,
        codigo="FACTURACION",
        nombre="Facturación Electrónica",
        activo=True,
    )


@pytest.fixture
def modulo_inventario(empresa_acme):
    return ModuloContratado.objects.create(
        empresa=empresa_acme,
        codigo="INVENTARIO",
        nombre="Control de Inventarios",
        activo=True,
    )


@pytest.fixture
def modulo_global(empresa_global):
    return ModuloContratado.objects.create(
        empresa=empresa_global,
        codigo="LOGISTICA",
        nombre="Gestión Logística",
        activo=True,
    )


@pytest.fixture
def api_client():
    return APIClient()


def auth_client(user) -> APIClient:
    """Return an APIClient authenticated as *user* via force_authenticate."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ---------------------------------------------------------------------------
# Helper: run a full 4-step reporting dialogue
# ---------------------------------------------------------------------------


def run_full_dialogue(
    api_client, session_id: str, modulo_nombre: str = "Facturación Electrónica"
) -> dict:
    """Drive the chatbot through the 4-turn happy path and return the final response JSON."""

    def post(msg):
        resp = api_client.post(ENDPOINT, {"mensaje": msg, "session_id": session_id}, format="json")
        assert resp.status_code == 200, f"Unexpected {resp.status_code}: {resp.data}"
        return resp.data

    # Turn 1 — describe the problem
    r1 = post("Tengo un problema al emitir facturas electrónicas en el módulo de cobros.")
    assert r1["estado_actual"] == "ASK_MODULE"

    # Turn 2 — select module
    r2 = post(modulo_nombre)
    assert r2["estado_actual"] == "ASK_PRIORITY"

    # Turn 3 — set priority
    r3 = post("Alta")
    assert r3["estado_actual"] == "CONFIRMATION"

    # Turn 4 — confirm
    r4 = post("Confirmar")
    assert r4["tipo_respuesta"] == "TICKET_CREADO"
    return r4


# ===========================================================================
# 1. Permission enforcement
# ===========================================================================


@pytest.mark.django_db
def test_anonymous_request_returns_401(api_client):
    """Unauthenticated request must receive 401."""
    resp = api_client.post(ENDPOINT, {"mensaje": "Hola"}, format="json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_staff_agente_request_returns_403(agente):
    """Non-client (agente) must receive 403."""
    client = auth_client(agente)
    resp = client.post(ENDPOINT, {"mensaje": "Hola"}, format="json")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_missing_mensaje_returns_400(cliente_acme):
    """Missing or blank 'mensaje' field must return 400."""
    client = auth_client(cliente_acme)

    # Missing key entirely
    resp = client.post(ENDPOINT, {}, format="json")
    assert resp.status_code == 400

    # Blank string
    resp2 = client.post(ENDPOINT, {"mensaje": "   "}, format="json")
    assert resp2.status_code == 400

    # No ticket created
    assert Ticket.objects.count() == 0


# ===========================================================================
# 2. Full 4-step reporting dialogue (RF3)
# ===========================================================================


@pytest.mark.django_db
def test_full_4step_dialogue_creates_ticket_with_chatbot_canal(
    cliente_acme, modulo_facturacion, modulo_inventario
):
    """Full 4-turn happy path creates a Ticket with canal_origen='Chatbot',
    linked to the client's empresa, and the response contains the radicado."""
    client = auth_client(cliente_acme)
    session_id = "api-happy-path-test"
    r4 = run_full_dialogue(client, session_id)

    # Response must contain the radicado
    assert "radicado" in r4
    radicado = r4["radicado"]
    assert radicado.startswith("TK-")

    # Ticket must be in DB with correct domain values
    ticket = Ticket.objects.get(radicado=radicado)
    assert ticket.canal_origen == CanalOrigenChoices.CHATBOT
    assert ticket.empresa == cliente_acme.empresa
    assert ticket.creado_por == cliente_acme
    assert ticket.estado == EstadoChoices.ABIERTO
    assert ticket.prioridad == "Alta"

    # Initial immutable TicketItem must exist
    items = TicketItem.objects.filter(ticket=ticket)
    assert items.count() >= 1
    creation_item = items.filter(tipo_accion=TipoAccionChoices.CREACION).first()
    assert creation_item is not None
    assert creation_item.actor == cliente_acme


@pytest.mark.django_db
def test_response_includes_radicado_on_ticket_creation(cliente_acme, modulo_facturacion):
    """The TICKET_CREADO response must include 'radicado' in the JSON payload."""
    client = auth_client(cliente_acme)
    r4 = run_full_dialogue(client, "session-radicado-check")

    assert r4.get("tipo_respuesta") == "TICKET_CREADO"
    assert "radicado" in r4
    assert r4["radicado"] is not None
    assert r4["radicado"].startswith("TK-")


@pytest.mark.django_db
def test_session_scoped_to_user_not_shared_across_users(
    cliente_acme, cliente_global, modulo_facturacion, modulo_global
):
    """Two different users sharing the same session_id string must have independent sessions."""
    session_id = "shared-session-id"

    client_acme = auth_client(cliente_acme)
    client_global = auth_client(cliente_global)

    # Advance Acme client to ASK_MODULE
    r_acme = client_acme.post(
        ENDPOINT, {"mensaje": "Falla en facturación.", "session_id": session_id}, format="json"
    )
    assert r_acme.status_code == 200
    assert r_acme.data["estado_actual"] == "ASK_MODULE"

    # Global client sends first message — must start from INITIAL, not inherit Acme's session
    r_global = client_global.post(
        ENDPOINT, {"mensaje": "Consultar estado", "session_id": session_id}, format="json"
    )
    assert r_global.status_code == 200
    # Global client hit status inquiry (no active tickets yet), not continuation of Acme's flow
    # Either INFO or ESTADO_TICKET is acceptable; key point: not in ASK_MODULE
    assert r_global.data["estado_actual"] == "INITIAL"


# ===========================================================================
# 3. Cancellation flow
# ===========================================================================


@pytest.mark.django_db
def test_cancellation_flow_creates_no_ticket(cliente_acme, modulo_facturacion):
    """Cancelling at CONFIRMATION must NOT create any ticket."""
    client = auth_client(cliente_acme)
    session_id = "cancel-flow-test"

    def post(msg):
        resp = client.post(ENDPOINT, {"mensaje": msg, "session_id": session_id}, format="json")
        assert resp.status_code == 200
        return resp.data

    # Walk through 3 turns to reach CONFIRMATION
    post("Tengo un problema con la facturación.")
    post("Facturación Electrónica")
    r3 = post("Media")
    assert r3["estado_actual"] == "CONFIRMATION"

    ticket_count_before = Ticket.objects.count()

    # Cancel
    r4 = post("Cancelar")
    assert r4["tipo_respuesta"] == "INFO"
    assert r4["estado_actual"] == "INITIAL"

    # No new ticket should have been created
    assert Ticket.objects.count() == ticket_count_before


# ===========================================================================
# 4. RF6 — Status inquiry: specific radicado
# ===========================================================================


@pytest.fixture
def ticket_acme(cliente_acme, modulo_facturacion):
    """Create a resolved ticket belonging to Acme with a solution comment."""
    ticket = TicketCreationService.create_ticket(
        creado_por=cliente_acme,
        empresa=cliente_acme.empresa,
        modulo_id=modulo_facturacion.id,
        pestana_o_documento="Portal",
        asunto="Error en factura",
        descripcion="No se puede emitir la factura electrónica.",
        prioridad="Media",
        canal_origen=CanalOrigenChoices.PORTAL,
    )
    # Manually set to Resuelto with a comment to test RF6 field exposure
    ticket.estado = EstadoChoices.RESUELTO
    ticket.comentario_solucion = "Se actualizó la plantilla de factura."
    ticket.save()
    return ticket


@pytest.fixture
def ticket_global(cliente_global, modulo_global):
    """Create a ticket belonging to Global Logistics (a different company)."""
    return TicketCreationService.create_ticket(
        creado_por=cliente_global,
        empresa=cliente_global.empresa,
        modulo_id=modulo_global.id,
        pestana_o_documento="Portal",
        asunto="Falla logística",
        descripcion="Error en rutas de distribución.",
        prioridad="Alta",
        canal_origen=CanalOrigenChoices.PORTAL,
    )


@pytest.mark.django_db
def test_rf6_specific_radicado_returns_status_and_solution_comment(cliente_acme, ticket_acme):
    """Querying a known radicado returns estado and comentario_solucion."""
    client = auth_client(cliente_acme)
    radicado = ticket_acme.radicado

    resp = client.post(
        ENDPOINT, {"mensaje": f"¿Cuál es el estado del radicado {radicado}?"}, format="json"
    )
    assert resp.status_code == 200
    data = resp.data

    assert data["tipo_respuesta"] == "ESTADO_TICKET"
    assert radicado in data["mensaje"]
    # Estado must appear in message
    assert EstadoChoices.RESUELTO in data["mensaje"]
    # Solution comment must appear
    assert "Se actualizó la plantilla" in data["mensaje"]
    # Radicado echoed in campos_recolectados
    assert data["campos_recolectados"]["radicado"] == radicado
    assert data["campos_recolectados"]["estado"] == EstadoChoices.RESUELTO
    assert "Se actualizó la plantilla" in data["campos_recolectados"]["comentario_solucion"]


@pytest.mark.django_db
def test_rf6_bare_radicado_in_message_works(cliente_acme, ticket_acme):
    """Sending just the radicado (no extra text) must still trigger the lookup."""
    client = auth_client(cliente_acme)
    resp = client.post(ENDPOINT, {"mensaje": ticket_acme.radicado}, format="json")
    assert resp.status_code == 200
    assert resp.data["tipo_respuesta"] == "ESTADO_TICKET"
    assert ticket_acme.radicado in resp.data["mensaje"]


# ===========================================================================
# 5. RF6 — Status inquiry: general active tickets listing
# ===========================================================================


@pytest.mark.django_db
def test_rf6_general_inquiry_lists_active_tickets_for_company(
    cliente_acme, modulo_facturacion, modulo_inventario
):
    """A general status inquiry lists all active tickets for the user's company."""
    # Create two active tickets for Acme
    t1 = TicketCreationService.create_ticket(
        creado_por=cliente_acme,
        empresa=cliente_acme.empresa,
        modulo_id=modulo_facturacion.id,
        pestana_o_documento="Portal",
        asunto="Falla facturación",
        descripcion="No funciona.",
        prioridad="Media",
        canal_origen=CanalOrigenChoices.PORTAL,
    )
    t2 = TicketCreationService.create_ticket(
        creado_por=cliente_acme,
        empresa=cliente_acme.empresa,
        modulo_id=modulo_inventario.id,
        pestana_o_documento="Portal",
        asunto="Falla inventario",
        descripcion="Stock incorrecto.",
        prioridad="Baja",
        canal_origen=CanalOrigenChoices.PORTAL,
    )

    client = auth_client(cliente_acme)
    resp = client.post(ENDPOINT, {"mensaje": "¿Cuál es el estado de mis tickets?"}, format="json")
    assert resp.status_code == 200
    data = resp.data

    assert data["tipo_respuesta"] == "ESTADO_TICKET"
    # Both radicados must appear in the response
    assert t1.radicado in data["mensaje"]
    assert t2.radicado in data["mensaje"]
    # Summary in campos_recolectados
    radicados_in_summary = [
        item["radicado"] for item in data["campos_recolectados"].get("tickets_activos", [])
    ]
    assert t1.radicado in radicados_in_summary
    assert t2.radicado in radicados_in_summary


@pytest.mark.django_db
def test_rf6_general_inquiry_no_active_tickets_returns_info(cliente_acme, modulo_facturacion):
    """When company has no active tickets, response is INFO with a helpful message."""
    # Create a resolved ticket (not active)
    ticket = TicketCreationService.create_ticket(
        creado_por=cliente_acme,
        empresa=cliente_acme.empresa,
        modulo_id=modulo_facturacion.id,
        pestana_o_documento="Portal",
        asunto="Ticket resuelto",
        descripcion="Fue resuelto.",
        prioridad="Baja",
        canal_origen=CanalOrigenChoices.PORTAL,
    )
    ticket.estado = EstadoChoices.RESUELTO
    ticket.save()

    client = auth_client(cliente_acme)
    resp = client.post(ENDPOINT, {"mensaje": "estado de mis tickets"}, format="json")
    assert resp.status_code == 200
    assert resp.data["tipo_respuesta"] == "INFO"
    # Should mention there are no active tickets
    assert "activos" in resp.data["mensaje"].lower() or "no tienes" in resp.data["mensaje"].lower()


# ===========================================================================
# 6. Multi-tenant isolation (RNF2)
# ===========================================================================


@pytest.mark.django_db
def test_rf6_cannot_query_radicado_from_another_company(cliente_acme, ticket_global):
    """Querying a radicado belonging to another company must return 'not found' (safe response)."""
    client = auth_client(cliente_acme)
    foreign_radicado = ticket_global.radicado

    resp = client.post(
        ENDPOINT,
        {"mensaje": f"Estado del ticket {foreign_radicado}"},
        format="json",
    )
    assert resp.status_code == 200
    data = resp.data

    # Must be ESTADO_TICKET type (consistent interface) but NOT expose the actual ticket data
    assert data["tipo_respuesta"] == "ESTADO_TICKET"
    # The 'mensaje' must NOT contain data from the other company's ticket
    assert "Falla logística" not in data["mensaje"]
    assert "Global Logistics" not in data["mensaje"]
    # The response must indicate not found
    assert "no se encontró" in data["mensaje"].lower() or "no encontró" in data["mensaje"].lower()
    # campos_recolectados must not contain the foreign ticket's radicado as a resolved match
    assert data["campos_recolectados"].get("estado") is None
    assert data["campos_recolectados"].get("radicado") is None


@pytest.mark.django_db
def test_rf6_general_listing_only_shows_own_company_tickets(
    cliente_acme, cliente_global, modulo_facturacion, modulo_global
):
    """General active ticket listing for Acme must NOT include Global's tickets."""
    # Create a ticket for Acme
    t_acme = TicketCreationService.create_ticket(
        creado_por=cliente_acme,
        empresa=cliente_acme.empresa,
        modulo_id=modulo_facturacion.id,
        pestana_o_documento="Portal",
        asunto="Ticket Acme",
        descripcion="Descripción Acme.",
        prioridad="Media",
        canal_origen=CanalOrigenChoices.PORTAL,
    )
    # Create a ticket for Global
    t_global = TicketCreationService.create_ticket(
        creado_por=cliente_global,
        empresa=cliente_global.empresa,
        modulo_id=modulo_global.id,
        pestana_o_documento="Portal",
        asunto="Ticket Global",
        descripcion="Descripción Global.",
        prioridad="Alta",
        canal_origen=CanalOrigenChoices.PORTAL,
    )

    client = auth_client(cliente_acme)
    resp = client.post(ENDPOINT, {"mensaje": "mis tickets"}, format="json")
    assert resp.status_code == 200
    data = resp.data

    # Acme's radicado must be present
    assert t_acme.radicado in data["mensaje"]
    # Global's radicado must NOT appear
    assert t_global.radicado not in data["mensaje"]


@pytest.mark.django_db
def test_rf3_reporting_session_scoped_to_company(
    cliente_acme, cliente_global, modulo_facturacion, modulo_global
):
    """Reporting sessions are strictly isolated: Global client cannot see Acme's modules."""
    client_acme = auth_client(cliente_acme)
    client_global = auth_client(cliente_global)

    # Advance Acme through INITIAL
    r_acme = client_acme.post(
        ENDPOINT,
        {"mensaje": "Falla en facturación.", "session_id": "shared-session"},
        format="json",
    )
    assert r_acme.status_code == 200
    assert r_acme.data["estado_actual"] == "ASK_MODULE"
    # Acme's modules should be listed (not Global's)
    assert "Facturación Electrónica" in r_acme.data["mensaje"]
    assert "Gestión Logística" not in r_acme.data["mensaje"]

    # Advance Global through INITIAL with the same session_id string
    r_global = client_global.post(
        ENDPOINT,
        {"mensaje": "Falla en logística.", "session_id": "shared-session"},
        format="json",
    )
    assert r_global.status_code == 200
    assert r_global.data["estado_actual"] == "ASK_MODULE"
    # Global's modules should be listed (not Acme's)
    assert "Gestión Logística" in r_global.data["mensaje"]
    assert "Facturación Electrónica" not in r_global.data["mensaje"]
