"""Automated tests for conversational session state machine (Task BE-14, User Story #1).

Covers:
- Full happy-path progression (INITIAL -> ASK_MODULE -> ASK_PRIORITY -> CONFIRMATION -> 'Confirmar').
- Cancellation at CONFIRMATION ('Cancelar') verifying zero tickets are created and session state is cleared.
- Invalid inputs at ASK_MODULE, ASK_PRIORITY, and CONFIRMATION (verifying state does not advance prematurely).
- Session persistence across turns using the cache layer.
- Multi-tenant isolation (RNF2) ensuring companies cannot see or select other companies' modules or sessions.
- Case-insensitivity and accent handling for priorities and confirmation commands.

Run:
    pytest apps/tickets/tests/test_chatbot_dialogue.py -v
"""

import pytest
from django.core.cache import cache

from apps.companies.models import Empresa, ModuloContratado, RolChoices, Usuario
from apps.tickets.chatbot import (
    ChatbotResponse,
    ChatbotResponseType,
    ChatbotState,
    ChatbotStateMachine,
    IncidentReportStateMachine,
)
from apps.tickets.models import (
    CanalOrigenChoices,
    EstadoChoices,
    PrioridadChoices,
    Ticket,
    TicketItem,
)


@pytest.fixture(autouse=True)
def clear_test_cache():
    """Ensure a clean cache state before and after each test."""
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
        correo="carlos@acme.com",
        password="password123",
        nombre="Carlos Gómez",
        rol=RolChoices.CLIENTE,
        empresa=empresa_acme,
    )


@pytest.fixture
def cliente_global(empresa_global):
    return Usuario.objects.create_user(
        correo="lucia@global.com",
        password="password123",
        nombre="Lucía Morales",
        rol=RolChoices.CLIENTE,
        empresa=empresa_global,
    )


@pytest.fixture
def modulos_acme(empresa_acme):
    mod1 = ModuloContratado.objects.create(
        empresa=empresa_acme,
        codigo="FACTURACION",
        nombre="Facturación Electrónica",
        activo=True,
    )
    mod2 = ModuloContratado.objects.create(
        empresa=empresa_acme,
        codigo="INVENTARIO",
        nombre="Control de Inventarios",
        activo=True,
    )
    mod3_inactivo = ModuloContratado.objects.create(
        empresa=empresa_acme,
        codigo="NOMINA",
        nombre="Nómina y RRHH",
        activo=False,
    )
    return [mod1, mod2, mod3_inactivo]


@pytest.fixture
def modulos_global(empresa_global):
    return ModuloContratado.objects.create(
        empresa=empresa_global,
        codigo="LOGISTICA",
        nombre="Gestión Logística",
        activo=True,
    )


# -----------------------------------------------------------------------------
# 1. Full Happy-Path Progression
# -----------------------------------------------------------------------------


@pytest.mark.django_db
def test_full_happy_path_progression_creates_ticket(cliente_acme, modulos_acme):
    """Test full sequential happy-path flow: INITIAL -> ASK_MODULE -> ASK_PRIORITY -> CONFIRMATION -> 'Confirmar'."""
    session_id = "session-test-happy-path"
    sm = IncidentReportStateMachine(user=cliente_acme, session_id=session_id)

    # Initial state verification
    assert sm.current_state == ChatbotState.INITIAL
    assert sm.context == {}

    # Turn 1: INITIAL -> Problem statement input
    resp1: ChatbotResponse = sm.process_message(
        "Tengo un problema crítico al emitir la factura electrónica con retención en la pantalla de cobros."
    )
    assert resp1.estado_actual == ChatbotState.ASK_MODULE
    assert resp1.tipo_respuesta == ChatbotResponseType.PREGUNTA
    assert "factura" in resp1.campos_recolectados["keywords"]
    assert (
        "retención" in resp1.campos_recolectados["keywords"]
        or "retencion" in resp1.campos_recolectados["keywords"]
    )
    assert resp1.campos_recolectados["raw_description"].startswith("Tengo un problema crítico")
    assert "Facturación Electrónica" in resp1.mensaje
    assert "Control de Inventarios" in resp1.mensaje
    # Inactive module should NOT be listed
    assert "Nómina y RRHH" not in resp1.mensaje

    # Turn 2: ASK_MODULE -> Select module by name (or code/index)
    resp2: ChatbotResponse = sm.process_message("Facturación Electrónica")
    assert resp2.estado_actual == ChatbotState.ASK_PRIORITY
    assert resp2.tipo_respuesta == ChatbotResponseType.PREGUNTA
    assert resp2.campos_recolectados["modulo_id"] == modulos_acme[0].id
    assert resp2.campos_recolectados["modulo_codigo"] == "FACTURACION"
    assert "Baja" in resp2.opciones
    assert "Media" in resp2.opciones
    assert "Alta" in resp2.opciones
    assert "Crítica" in resp2.opciones

    # Turn 3: ASK_PRIORITY -> Select urgency level (Alta)
    resp3: ChatbotResponse = sm.process_message("Alta")
    assert resp3.estado_actual == ChatbotState.CONFIRMATION
    assert resp3.tipo_respuesta == ChatbotResponseType.RESUMEN
    assert resp3.campos_recolectados["prioridad"] == PrioridadChoices.ALTA
    assert "Facturación Electrónica" in resp3.mensaje
    assert "Confirmar" in resp3.mensaje
    assert "Cancelar" in resp3.mensaje

    # Turn 4: CONFIRMATION -> Confirm ticket creation
    resp4: ChatbotResponse = sm.process_message("Confirmar")
    assert resp4.tipo_respuesta == ChatbotResponseType.TICKET_CREADO
    assert resp4.radicado is not None
    assert resp4.radicado.startswith("TK-")
    assert resp4.estado_actual == ChatbotState.INITIAL
    assert resp4.campos_recolectados == {}

    # Verify ticket was persisted in database with exact domain fields
    ticket = Ticket.objects.get(radicado=resp4.radicado)
    assert ticket.empresa == cliente_acme.empresa
    assert ticket.creado_por == cliente_acme
    assert ticket.modulo == modulos_acme[0]
    assert ticket.prioridad == PrioridadChoices.ALTA
    assert ticket.estado == EstadoChoices.ABIERTO
    assert ticket.canal_origen == CanalOrigenChoices.CHATBOT
    assert "factura electrónica" in ticket.descripcion

    # Verify initial immutable TicketItem was created
    audit_item = TicketItem.objects.filter(ticket=ticket).first()
    assert audit_item is not None
    assert audit_item.actor == cliente_acme
    assert audit_item.tipo_accion == "CREACION"
    assert audit_item.estado_nuevo == EstadoChoices.ABIERTO

    # Verify session is cleared from cache
    assert sm.current_state == ChatbotState.INITIAL
    assert sm.context == {}


# -----------------------------------------------------------------------------
# 2. Cancellation at Confirmation
# -----------------------------------------------------------------------------


@pytest.mark.django_db
def test_cancellation_at_confirmation_creates_zero_tickets(cliente_acme, modulos_acme):
    """Test user cancelling at CONFIRMATION step ('Cancelar') aborts flow without creating tickets."""
    session_id = "session-test-cancellation"
    sm = IncidentReportStateMachine(user=cliente_acme, session_id=session_id)

    # 1. INITIAL
    sm.process_message("Error al actualizar inventario físico de bodega")
    assert sm.current_state == ChatbotState.ASK_MODULE

    # 2. ASK_MODULE
    sm.process_message("INVENTARIO")
    assert sm.current_state == ChatbotState.ASK_PRIORITY

    # 3. ASK_PRIORITY
    sm.process_message("Media")
    assert sm.current_state == ChatbotState.CONFIRMATION

    # 4. CONFIRMATION -> Cancel
    resp = sm.process_message("Cancelar")
    assert resp.tipo_respuesta == ChatbotResponseType.INFO
    assert "cancelada" in resp.mensaje.lower()
    assert resp.radicado is None
    assert resp.ticket_id is None

    # Assert ZERO tickets were created in database
    assert Ticket.objects.count() == 0
    assert TicketItem.objects.count() == 0

    # Assert session is fully reset
    assert sm.current_state == ChatbotState.INITIAL
    assert sm.context == {}


# -----------------------------------------------------------------------------
# 3. Invalid Inputs & Re-prompting
# -----------------------------------------------------------------------------


@pytest.mark.django_db
def test_invalid_module_reprompts_and_keeps_state(cliente_acme, modulos_acme):
    """Test invalid or inactive module input stays in ASK_MODULE without advancing."""
    session_id = "session-test-invalid-module"
    sm = IncidentReportStateMachine(user=cliente_acme, session_id=session_id)

    sm.process_message("Fallo general en la aplicación")
    assert sm.current_state == ChatbotState.ASK_MODULE

    # Try an invalid nonexistent module
    resp_invalid = sm.process_message("ModuloInexistenteXYZ")
    assert resp_invalid.estado_actual == ChatbotState.ASK_MODULE
    assert resp_invalid.tipo_respuesta == ChatbotResponseType.ERROR
    assert "no corresponde a un módulo activo" in resp_invalid.mensaje
    assert sm.current_state == ChatbotState.ASK_MODULE

    # Try an inactive module
    resp_inactive = sm.process_message("NOMINA")
    assert resp_inactive.estado_actual == ChatbotState.ASK_MODULE
    assert sm.current_state == ChatbotState.ASK_MODULE

    # Finally provide a valid module by numeric index ('1', first active module in alphabetical order)
    resp_valid = sm.process_message("1")
    assert resp_valid.estado_actual == ChatbotState.ASK_PRIORITY
    assert sm.current_state == ChatbotState.ASK_PRIORITY
    # First active module ordered by name is "Control de Inventarios" (modulos_acme[1])
    assert sm.context["modulo_id"] == modulos_acme[1].id
    assert sm.context["modulo_codigo"] == "INVENTARIO"


@pytest.mark.django_db
def test_invalid_priority_reprompts_and_keeps_state(cliente_acme, modulos_acme):
    """Test invalid priority input stays in ASK_PRIORITY without advancing."""
    session_id = "session-test-invalid-priority"
    sm = IncidentReportStateMachine(user=cliente_acme, session_id=session_id)

    sm.process_message("Problema con el saldo de inventario")
    sm.process_message("INVENTARIO")
    assert sm.current_state == ChatbotState.ASK_PRIORITY

    # Invalid priority input
    resp_invalid = sm.process_message("SuperUrgente")
    assert resp_invalid.estado_actual == ChatbotState.ASK_PRIORITY
    assert resp_invalid.tipo_respuesta == ChatbotResponseType.ERROR
    assert "no es un nivel de prioridad válido" in resp_invalid.mensaje
    assert sm.current_state == ChatbotState.ASK_PRIORITY

    # Another invalid input
    resp_invalid_2 = sm.process_message("123")
    assert resp_invalid_2.estado_actual == ChatbotState.ASK_PRIORITY
    assert sm.current_state == ChatbotState.ASK_PRIORITY

    # Provide valid priority with lowercase
    resp_valid = sm.process_message("baja")
    assert resp_valid.estado_actual == ChatbotState.CONFIRMATION
    assert sm.current_state == ChatbotState.CONFIRMATION
    assert sm.context["prioridad"] == PrioridadChoices.BAJA


@pytest.mark.django_db
def test_invalid_confirmation_reprompts_and_keeps_state(cliente_acme, modulos_acme):
    """Test unrecognized input at CONFIRMATION step re-prompts and does not create tickets."""
    session_id = "session-test-invalid-confirmation"
    sm = IncidentReportStateMachine(user=cliente_acme, session_id=session_id)

    sm.process_message("Error 500 al timbrar factura")
    sm.process_message("FACTURACION")
    sm.process_message("Media")
    assert sm.current_state == ChatbotState.CONFIRMATION

    # Send random response
    resp_unrecognized = sm.process_message("Tal vez más tarde")
    assert resp_unrecognized.estado_actual == ChatbotState.CONFIRMATION
    assert resp_unrecognized.tipo_respuesta == ChatbotResponseType.ERROR
    assert "Opción no reconocida" in resp_unrecognized.mensaje
    assert sm.current_state == ChatbotState.CONFIRMATION
    assert Ticket.objects.count() == 0

    # Finally confirm
    resp_confirm = sm.process_message("confirmar")
    assert resp_confirm.tipo_respuesta == ChatbotResponseType.TICKET_CREADO
    assert Ticket.objects.count() == 1


# -----------------------------------------------------------------------------
# 4. Session Persistence Across Turns
# -----------------------------------------------------------------------------


@pytest.mark.django_db
def test_session_persistence_across_multiple_instances(cliente_acme, modulos_acme):
    """Test session state and collected fields persist in cache across independent object turns."""
    session_id = "session-persistent-12345"

    # Turn 1: Instance 1 starts dialogue
    sm1 = IncidentReportStateMachine(user=cliente_acme, session_id=session_id)
    sm1.process_message("El reporte de compras mensuales no carga")

    # Turn 2: Instance 2 (new object instance simulating fresh HTTP request)
    sm2 = IncidentReportStateMachine(user=cliente_acme, session_id=session_id)
    assert sm2.current_state == ChatbotState.ASK_MODULE
    assert "compras" in sm2.context["keywords"]
    assert sm2.context["raw_description"] == "El reporte de compras mensuales no carga"

    sm2.process_message("Facturación Electrónica")

    # Turn 3: Instance 3
    sm3 = IncidentReportStateMachine(user=cliente_acme, session_id=session_id)
    assert sm3.current_state == ChatbotState.ASK_PRIORITY
    assert sm3.context["modulo_codigo"] == "FACTURACION"

    sm3.process_message("Crítica")

    # Turn 4: Instance 4
    sm4 = IncidentReportStateMachine(user=cliente_acme, session_id=session_id)
    assert sm4.current_state == ChatbotState.CONFIRMATION
    assert sm4.context["prioridad"] == PrioridadChoices.CRITICA

    resp4 = sm4.process_message("Confirmar")
    assert resp4.tipo_respuesta == ChatbotResponseType.TICKET_CREADO

    # Turn 5: Instance 5 after confirmation should find clean session
    sm5 = IncidentReportStateMachine(user=cliente_acme, session_id=session_id)
    assert sm5.current_state == ChatbotState.INITIAL
    assert sm5.context == {}


# -----------------------------------------------------------------------------
# 5. Multi-Tenant Isolation (RNF2)
# -----------------------------------------------------------------------------


@pytest.mark.django_db
def test_multitenant_module_isolation(cliente_acme, cliente_global, modulos_acme, modulos_global):
    """Test client from Company A cannot select modules belonging to Company B (RNF2)."""
    sm_acme = IncidentReportStateMachine(user=cliente_acme, session_id="session-acme-tenant")
    sm_acme.process_message("Inconveniente con las entregas de pedidos")
    assert sm_acme.current_state == ChatbotState.ASK_MODULE

    # Acme user attempts to select Global's module ('LOGISTICA')
    resp_rejected = sm_acme.process_message("LOGISTICA")
    assert resp_rejected.estado_actual == ChatbotState.ASK_MODULE
    assert resp_rejected.tipo_respuesta == ChatbotResponseType.ERROR
    assert "no corresponde a un módulo activo" in resp_rejected.mensaje

    # Global user can select 'LOGISTICA'
    sm_global = IncidentReportStateMachine(user=cliente_global, session_id="session-global-tenant")
    sm_global.process_message("Retraso en rutas de distribución")
    resp_global = sm_global.process_message("LOGISTICA")
    assert resp_global.estado_actual == ChatbotState.ASK_PRIORITY


@pytest.mark.django_db
def test_multitenant_session_isolation(cliente_acme, cliente_global, modulos_acme):
    """Test same session_id used by users of different companies does not leak session data."""
    shared_session_id = "shared-session-token"

    # Acme client enters description
    sm_acme = IncidentReportStateMachine(user=cliente_acme, session_id=shared_session_id)
    sm_acme.process_message("Fallo confidencial de nómina Acme")
    assert sm_acme.current_state == ChatbotState.ASK_MODULE

    # Global client with same session_id should see a clean session, NOT Acme's data
    sm_global = IncidentReportStateMachine(user=cliente_global, session_id=shared_session_id)
    assert sm_global.current_state == ChatbotState.INITIAL
    assert sm_global.context == {}


# -----------------------------------------------------------------------------
# 6. Priority & Confirmation Case-Insensitive / Accent Flexibility
# -----------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "priority_input,expected_choice",
    [
        ("baja", PrioridadChoices.BAJA),
        ("BAJA", PrioridadChoices.BAJA),
        ("media", PrioridadChoices.MEDIA),
        ("Media", PrioridadChoices.MEDIA),
        ("ALTA", PrioridadChoices.ALTA),
        ("alta", PrioridadChoices.ALTA),
        ("critica", PrioridadChoices.CRITICA),
        ("crítica", PrioridadChoices.CRITICA),
        ("CRITICA", PrioridadChoices.CRITICA),
        ("CRÍTICA", PrioridadChoices.CRITICA),
    ],
)
def test_priority_case_and_accent_insensitivity(
    cliente_acme, modulos_acme, priority_input, expected_choice
):
    """Verify priority parsing handles case-insensitivity and accents properly."""
    sm = IncidentReportStateMachine(user=cliente_acme, session_id=f"session-pri-{priority_input}")
    sm.process_message("Error en pantalla de facturas")
    sm.process_message("FACTURACION")
    resp = sm.process_message(priority_input)
    assert resp.estado_actual == ChatbotState.CONFIRMATION
    assert sm.context["prioridad"] == expected_choice


@pytest.mark.django_db
@pytest.mark.parametrize(
    "confirm_input",
    ["confirmar", "CONFIRMAR", "Confirmar", "sí, confirmar", "si, confirmar", "confirmo"],
)
def test_confirm_keyword_flexibility(cliente_acme, modulos_acme, confirm_input):
    """Verify confirmation keywords match flexibly."""
    sm = IncidentReportStateMachine(user=cliente_acme, session_id=f"session-conf-{confirm_input}")
    sm.process_message("Problema con facturación")
    sm.process_message("FACTURACION")
    sm.process_message("Media")
    resp = sm.process_message(confirm_input)
    assert resp.tipo_respuesta == ChatbotResponseType.TICKET_CREADO
    assert resp.radicado is not None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "cancel_input",
    ["cancelar", "CANCELAR", "Cancelar", "no, cancelar", "abortar"],
)
def test_cancel_keyword_flexibility(cliente_acme, modulos_acme, cancel_input):
    """Verify cancellation keywords match flexibly."""
    sm = IncidentReportStateMachine(user=cliente_acme, session_id=f"session-canc-{cancel_input}")
    sm.process_message("Problema con facturación")
    sm.process_message("FACTURACION")
    sm.process_message("Media")
    resp = sm.process_message(cancel_input)
    assert resp.tipo_respuesta == ChatbotResponseType.INFO
    assert Ticket.objects.count() == 0


@pytest.mark.django_db
def test_empty_initial_message_reprompts_user(cliente_acme, modulos_acme):
    """Test empty or whitespace-only initial message re-prompts without transitioning state."""
    sm = IncidentReportStateMachine(user=cliente_acme, session_id="session-empty-input")
    resp = sm.process_message("   ")
    assert resp.estado_actual == ChatbotState.INITIAL
    assert sm.current_state == ChatbotState.INITIAL
    assert "describe" in resp.mensaje.lower()


@pytest.mark.django_db
def test_company_without_active_modules_gracefully_halts(cliente_global):
    """Test company with zero active modules produces a clear Spanish error and resets."""
    # Global has no modules created yet in this test
    sm = IncidentReportStateMachine(user=cliente_global, session_id="session-no-modules")
    resp = sm.process_message("Tengo un problema con el sistema")
    assert resp.tipo_respuesta == ChatbotResponseType.ERROR
    assert "no cuenta actualmente con módulos contratados activos" in resp.mensaje
    assert sm.current_state == ChatbotState.INITIAL


def test_alias_chatbot_state_machine_is_identical():
    """Verify ChatbotStateMachine alias points to IncidentReportStateMachine."""
    assert ChatbotStateMachine is IncidentReportStateMachine
