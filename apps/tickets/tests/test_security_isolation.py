"""Security test suite: multi-tenant isolation (RNF2) and audit immutability (RNF5).

Task BE-16 (issue #29, User Story #1). This module is the automated security
gate for the client-facing API and complements the per-endpoint unit tests.

Covered areas:
- Multi-tenant isolation (RNF2): a client only sees the tickets of their own
  company in the list endpoint; requesting a ticket owned by another company
  through the detail endpoint returns 404 (never 403 or 200), so tenant IDs can
  not be enumerated; the chatbot never discloses another company's ticket.
- Audit log immutability (RNF5): existing ``TicketItem`` rows can not be
  updated or deleted, either through the model or through bulk querysets.
- Client serializers (RNF2): internal-only fields (assigned staff, internal
  notes, internal actors) are absent from the response at every nesting level.

Run only this suite:
    pytest apps/tickets/tests/test_security_isolation.py -v
"""

import json

import pytest
from django.core.exceptions import PermissionDenied
from django.urls import NoReverseMatch, reverse
from rest_framework.test import APIClient

from apps.companies.models import Empresa, ModuloContratado, RolChoices, Usuario
from apps.tickets.models import EstadoChoices, Ticket, TicketItem, TipoAccionChoices

PASSWORD = "Clave#2026"

LIST_URL = "/api/v1/client/tickets/"

INTERNAL_NOTE = "NOTA INTERNA CONFIDENCIAL: escalar con el equipo de facturación."

# Keys that must never reach a client serializer, at any nesting level.
FORBIDDEN_CLIENT_KEYS = {
    "actor",
    "actor_id",
    "clasificacion",
    "creado_por",
    "creado_por_id",
    "empresa",
    "empresa_id",
    "es_interna",
    "id",
    "registrado_por_agente",
    "registrado_por_agente_id",
    "responsable",
    "responsable_asignado",
    "responsable_asignado_id",
    "responsable_id",
}

HISTORY_PUBLIC_FIELDS = {
    "tipo_accion",
    "estado_anterior",
    "estado_nuevo",
    "observaciones",
    "fecha_creacion",
}


def detail_url(radicado: str) -> str:
    """Return the client ticket detail URL for a radicado."""
    return f"/api/v1/client/tickets/{radicado}/"


def chatbot_url() -> str:
    """Return the chatbot endpoint URL or skip when BE-15 is not merged yet."""
    try:
        return reverse("chatbot-mensajes")
    except NoReverseMatch:
        pytest.skip("POST /api/v1/chatbot/mensajes/ (BE-15) is not registered in this branch yet.")


def iter_keys(payload):
    """Yield every key of a (possibly deeply nested) JSON-like structure."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            yield key
            yield from iter_keys(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from iter_keys(value)


def collect_history(payload):
    """Return all history objects found in a detail payload."""
    history = payload.get("historial", [])
    assert isinstance(history, list)
    return history


# ---------------------------------------------------------------------------
# Fixtures: two fully independent tenants
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def use_fast_password_hasher(settings):
    """Use a cheap hasher: authentication is forced, so strong hashing adds no value."""
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture
def company_a():
    return Empresa.objects.create(nombre="Acme Industrial S.A.S.", identificacion="900123456-7")


@pytest.fixture
def company_b():
    return Empresa.objects.create(nombre="Beta Comercial S.A.S.", identificacion="800987654-3")


@pytest.fixture
def client_a(company_a):
    return Usuario.objects.create_user(
        correo="carlos@acme.com",
        password=PASSWORD,
        nombre="Carlos Gómez",
        empresa=company_a,
    )


@pytest.fixture
def client_b(company_b):
    return Usuario.objects.create_user(
        correo="ana@beta.com",
        password=PASSWORD,
        nombre="Ana Torres",
        empresa=company_b,
    )


@pytest.fixture
def module_a(company_a):
    return ModuloContratado.objects.create(
        empresa=company_a, codigo="FACTURACION", nombre="Facturación Electrónica"
    )


@pytest.fixture
def module_b(company_b):
    return ModuloContratado.objects.create(
        empresa=company_b, codigo="INVENTARIO", nombre="Control de Inventarios"
    )


@pytest.fixture
def agent():
    """Internal Datak staff member; never belongs to a client company."""
    return Usuario.objects.create_user(
        correo="agente@datak.co",
        password=PASSWORD,
        nombre="Agente Soporte",
        rol=RolChoices.AGENTE_SOPORTE,
    )


@pytest.fixture
def responsible():
    """Internal developer assigned to tickets; must stay hidden from clients."""
    return Usuario.objects.create_user(
        correo="dev@datak.co",
        password=PASSWORD,
        nombre="Dev Datak",
        rol=RolChoices.RESPONSABLE_ATENCION,
    )


@pytest.fixture
def ticket_a(company_a, client_a, module_a, agent, responsible):
    """Company A ticket with public and internal history."""
    ticket = Ticket.objects.create(
        radicado="TK-2026-000001",
        empresa=company_a,
        creado_por=client_a,
        modulo=module_a,
        pestana_o_documento="Facturación / Nueva factura",
        asunto="ALPHA-PUBLIC-ISSUE: no carga la factura",
        descripcion="ALPHA-PUBLIC-DESCRIPTION: la pantalla queda en blanco.",
        estado=EstadoChoices.ABIERTO,
        prioridad="Alta",
        responsable=responsible,
        registrado_por_agente=agent,
    )
    TicketItem.objects.create(
        ticket=ticket,
        actor=client_a,
        tipo_accion=TipoAccionChoices.CREACION,
        estado_nuevo=EstadoChoices.ABIERTO,
        observaciones="Ticket creado desde el portal.",
    )
    TicketItem.objects.create(
        ticket=ticket,
        actor=agent,
        tipo_accion=TipoAccionChoices.NOTA_INTERNA,
        es_interna=True,
        responsable_asignado=responsible,
        observaciones=INTERNAL_NOTE,
    )
    return ticket


@pytest.fixture
def ticket_b(company_b, client_b, module_b):
    """Company B ticket. None of its data may ever reach a Company A client."""
    ticket = Ticket.objects.create(
        radicado="TK-2026-000002",
        empresa=company_b,
        creado_por=client_b,
        modulo=module_b,
        pestana_o_documento="Inventario / Ajustes",
        asunto="BETA-SECRET-ISSUE: descuadre de inventario",
        descripcion="BETA-SECRET-DESCRIPTION: datos financieros de Beta.",
        estado=EstadoChoices.EN_GESTION,
        prioridad="Critica",
        comentario_solucion="BETA-SECRET-SOLUTION: no debe filtrarse.",
    )
    TicketItem.objects.create(
        ticket=ticket,
        actor=client_b,
        tipo_accion=TipoAccionChoices.CREACION,
        estado_nuevo=EstadoChoices.ABIERTO,
        observaciones="BETA-SECRET-HISTORY: evento privado de Beta.",
    )
    return ticket


@pytest.fixture
def api_client_a(client_a):
    client = APIClient()
    client.force_authenticate(user=client_a)
    return client


@pytest.fixture
def api_client_b(client_b):
    client = APIClient()
    client.force_authenticate(user=client_b)
    return client


# ---------------------------------------------------------------------------
# RNF2: list isolation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_only_returns_tickets_of_authenticated_user_company(api_client_a, ticket_a, ticket_b):
    """Company A sees exactly its own ticket and zero Company B tickets."""
    response = api_client_a.get(LIST_URL)

    assert response.status_code == 200
    radicados = [row["radicado"] for row in response.data["results"]]
    assert radicados == [ticket_a.radicado]
    assert response.data["count"] == 1

    body = response.content.decode("utf-8")
    assert ticket_b.radicado not in body
    assert ticket_b.asunto not in body
    assert ticket_b.descripcion not in body


@pytest.mark.django_db
def test_list_ignores_company_identifiers_supplied_by_the_client(
    api_client_a, ticket_a, ticket_b, company_b
):
    """Tenant filters sent in the query string can not switch the tenant (RNF2).

    The company is resolved exclusively from ``request.user.empresa``, so
    ``?empresa=`` / ``?empresa_id=`` pointing to Company B must have no effect.
    """
    response = api_client_a.get(
        LIST_URL,
        {"empresa": company_b.pk, "empresa_id": company_b.pk},
    )

    assert response.status_code == 200
    radicados = [row["radicado"] for row in response.data["results"]]
    assert radicados == [ticket_a.radicado]
    assert ticket_b.radicado not in response.content.decode("utf-8")


@pytest.mark.django_db
def test_company_b_client_only_sees_company_b_tickets(api_client_b, ticket_a, ticket_b):
    """The isolation is symmetric: Company B only sees its own ticket."""
    response = api_client_b.get(LIST_URL)

    assert response.status_code == 200
    radicados = [row["radicado"] for row in response.data["results"]]
    assert radicados == [ticket_b.radicado]
    assert ticket_a.radicado not in response.content.decode("utf-8")


# ---------------------------------------------------------------------------
# RNF2: detail isolation (404 enforcement)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_detail_of_another_company_ticket_returns_404(api_client_a, ticket_b):
    """A valid radicado owned by Company B is strictly 404 for Company A."""
    response = api_client_a.get(detail_url(ticket_b.radicado))

    assert response.status_code == 404
    body = response.content.decode("utf-8")
    assert ticket_b.asunto not in body
    assert ticket_b.descripcion not in body
    assert ticket_b.comentario_solucion not in body
    assert "BETA-SECRET" not in body


@pytest.mark.django_db
def test_cross_tenant_404_is_indistinguishable_from_unknown_radicado(api_client_a, ticket_b):
    """Existing-but-foreign and nonexistent radicados produce the same 404 body.

    Identical responses prevent attackers from enumerating which radicados
    exist in other companies.
    """
    foreign = api_client_a.get(detail_url(ticket_b.radicado))
    missing = api_client_a.get(detail_url("TK-2026-999999"))

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


@pytest.mark.django_db
def test_detail_of_own_company_ticket_returns_200(api_client_a, ticket_a):
    """Sanity check: the same endpoint does return Company A's own ticket."""
    response = api_client_a.get(detail_url(ticket_a.radicado))

    assert response.status_code == 200
    assert response.data["radicado"] == ticket_a.radicado


# ---------------------------------------------------------------------------
# RNF2: chatbot isolation
# ---------------------------------------------------------------------------


def assert_no_company_b_leak(payload, ticket_b):
    """Assert a chatbot payload exposes no Company B ticket data."""
    body = json.dumps(payload, ensure_ascii=False, default=str)

    assert ticket_b.asunto not in body
    assert ticket_b.descripcion not in body
    assert ticket_b.comentario_solucion not in body
    assert "BETA-SECRET" not in body

    # A not-found answer must not return the foreign radicado or its state.
    assert payload.get("radicado") != ticket_b.radicado
    ideas = payload.get("datos") or {}
    collected = payload.get("campos_recolectados") or {}
    assert ideas.get("estado") != ticket_b.estado
    assert collected.get("estado") != ticket_b.estado
    assert collected.get("tickets_activos") is None


@pytest.mark.django_db
def test_chatbot_does_not_disclose_another_company_ticket(api_client_a, ticket_b):
    """Querying a foreign radicado through the chatbot must not leak it (RNF2)."""
    url = chatbot_url()
    response = api_client_a.post(
        url,
        {"mensaje": f"¿Cuál es el estado del radicado {ticket_b.radicado}?"},
        format="json",
    )

    # 200 with a safe "not found" answer or a strict 404 are both acceptable.
    # A 403 is not: it would reveal that the radicado exists in another tenant.
    assert response.status_code in (200, 404)
    assert_no_company_b_leak(response.json(), ticket_b)


@pytest.mark.django_db
def test_chatbot_general_inquiry_only_lists_own_company_tickets(api_client_a, ticket_a, ticket_b):
    """A general "mis tickets" inquiry is scoped to the authenticated company."""
    url = chatbot_url()
    response = api_client_a.post(url, {"mensaje": "Muéstrame mis tickets"}, format="json")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert ticket_a.radicado in body
    assert ticket_b.radicado not in body
    assert ticket_b.asunto not in body
    assert "BETA-SECRET" not in body


# ---------------------------------------------------------------------------
# RNF5: history immutability
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_existing_history_item_can_not_be_updated(ticket_a):
    """Updating an existing TicketItem raises PermissionDenied and persists nothing."""
    item = ticket_a.historial.get(tipo_accion=TipoAccionChoices.CREACION)
    original_observaciones = item.observaciones
    original_estado = item.estado_nuevo

    item.observaciones = "Texto alterado"
    item.estado_nuevo = EstadoChoices.RESUELTO

    with pytest.raises(PermissionDenied, match="no se pueden modificar"):
        item.save()

    item.refresh_from_db()
    assert item.observaciones == original_observaciones
    assert item.estado_nuevo == original_estado


@pytest.mark.django_db
def test_existing_history_item_can_not_be_deleted(ticket_a):
    """Deleting a TicketItem raises PermissionDenied and the row still exists."""
    item = ticket_a.historial.get(tipo_accion=TipoAccionChoices.CREACION)

    with pytest.raises(PermissionDenied, match="no se pueden eliminar"):
        item.delete()

    assert TicketItem.objects.filter(pk=item.pk).exists()


@pytest.mark.django_db
def test_bulk_history_update_is_blocked(ticket_a):
    """Queryset.update() (which bypasses save()) is also blocked."""
    item = ticket_a.historial.get(tipo_accion=TipoAccionChoices.CREACION)

    with pytest.raises(PermissionDenied, match="no se pueden modificar"):
        TicketItem.objects.filter(pk=item.pk).update(observaciones="Texto alterado")

    item.refresh_from_db()
    assert item.observaciones == "Ticket creado desde el portal."


@pytest.mark.django_db
def test_bulk_history_delete_is_blocked(ticket_a):
    """Queryset.delete() (which bypasses model.delete()) is also blocked."""
    count_before = TicketItem.objects.count()

    with pytest.raises(PermissionDenied, match="no se pueden eliminar"):
        TicketItem.objects.all().delete()

    assert TicketItem.objects.count() == count_before


@pytest.mark.django_db
def test_history_is_append_only(ticket_a, client_a):
    """New events can still be appended; only existing rows are immutable."""
    item = TicketItem.objects.create(
        ticket=ticket_a,
        actor=client_a,
        tipo_accion=TipoAccionChoices.CAMBIO_ESTADO,
        estado_anterior=EstadoChoices.ABIERTO,
        estado_nuevo=EstadoChoices.EN_GESTION,
        observaciones="Evento nuevo permitido.",
    )

    assert item.pk is not None
    assert TicketItem.objects.filter(pk=item.pk).exists()


# ---------------------------------------------------------------------------
# RNF2: client serializer security
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_detail_payload_never_exposes_internal_fields(api_client_a, ticket_a):
    """No internal key appears anywhere in the detail payload (root or history)."""
    response = api_client_a.get(detail_url(ticket_a.radicado))

    assert response.status_code == 200
    payload = response.json()

    leaked_keys = FORBIDDEN_CLIENT_KEYS & set(iter_keys(payload))
    assert leaked_keys == set()

    history = collect_history(payload)
    assert history
    for event in history:
        assert set(event) == HISTORY_PUBLIC_FIELDS


@pytest.mark.django_db
def test_detail_payload_never_exposes_internal_values(api_client_a, ticket_a, responsible, agent):
    """Internal note text and staff identities are absent from the payload."""
    response = api_client_a.get(detail_url(ticket_a.radicado))

    assert response.status_code == 200
    body = response.content.decode("utf-8")

    assert INTERNAL_NOTE not in body
    assert "NOTA INTERNA" not in body
    assert responsible.nombre not in body
    assert responsible.correo not in body
    assert agent.nombre not in body
    assert agent.correo not in body


@pytest.mark.django_db
def test_detail_history_only_contains_public_events(api_client_a, ticket_a):
    """Internal notes (es_interna=True) are filtered out of the client timeline."""
    response = api_client_a.get(detail_url(ticket_a.radicado))

    history = collect_history(response.json())
    assert [event["tipo_accion"] for event in history] == ["CREACION"]
    assert all("es_interna" not in event for event in history)


@pytest.mark.django_db
def test_list_payload_never_exposes_internal_fields(api_client_a, ticket_a, responsible):
    """The list rows also omit internal keys and staff identities."""
    response = api_client_a.get(LIST_URL)

    assert response.status_code == 200
    payload = response.json()

    leaked_keys = FORBIDDEN_CLIENT_KEYS & set(iter_keys(payload))
    assert leaked_keys == set()

    body = response.content.decode("utf-8")
    assert responsible.nombre not in body
    assert responsible.correo not in body
    assert set(payload["results"][0]) == {
        "radicado",
        "asunto",
        "modulo_nombre",
        "prioridad",
        "estado",
        "fecha_creacion",
    }
