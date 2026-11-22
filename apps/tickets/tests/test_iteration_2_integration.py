"""Comprehensive End-to-End Integration Suite for Iteration 2 (BE-26, RF7-RF16, Issue #58).

Authored by @tohond (Omar Palencia).
Parent User Story: #50 (HU-03). MS Project Activity: MP-68 / MP-70.

Exercises the full Iteration 2 support lifecycle:
1. External ticket intake (RF9: WhatsApp, Slack, etc.)
2. Unified inbox triage and filtering (RF7)
3. Support ticket inspection & full audit timeline (RF8)
4. Ticket classification & priority setting (RF10)
5. Staff assignment from active catalog (RF11)
6. Engineer assigned queue (RF13)
7. Private internal notes (RF14)
8. Security & privacy boundary (RNF2: client never sees internal notes or staff names)
9. Ticket resolution & closure notification (RF15, RF16)
10. In-portal client notification & mark-as-read (RF16)
11. Ticket dismissal as 'No procedente' and lifecycle restrictions (RF12)
"""

import pytest
from django.core import mail
from rest_framework import status
from rest_framework.test import APIClient

from apps.companies.models import Empresa, ModuloContratado, RolChoices, Usuario
from apps.tickets.models import (
    CanalOrigenChoices,
    ClasificacionChoices,
    EstadoChoices,
    PrioridadChoices,
    Ticket,
    TicketItem,
    TicketNotificacion,
    TipoAccionChoices,
)


@pytest.fixture
def empresa_acme(db):
    return Empresa.objects.create(
        nombre="Acme Logistics",
        identificacion="NIT-900333444-1",
        activa=True,
    )


@pytest.fixture
def empresa_beta(db):
    return Empresa.objects.create(
        nombre="Beta Supplies",
        identificacion="NIT-900555666-2",
        activa=True,
    )


@pytest.fixture
def modulo_facturacion(empresa_acme):
    return ModuloContratado.objects.create(
        empresa=empresa_acme,
        nombre="Facturación Electrónica",
        codigo="FACT",
        activo=True,
    )


@pytest.fixture
def cliente_acme(empresa_acme):
    return Usuario.objects.create_user(
        correo="contacto@acmelogistics.com",
        password="SecurePassword2026#",
        nombre="Laura Cliente",
        rol=RolChoices.CLIENTE,
        empresa=empresa_acme,
        activo=True,
    )


@pytest.fixture
def agente_soporte(empresa_acme):
    return Usuario.objects.create_user(
        correo="agente1@datak.co",
        password="SecurePassword2026#",
        nombre="Andrés Agente",
        rol=RolChoices.AGENTE_SOPORTE,
        empresa=empresa_acme,
        activo=True,
    )


@pytest.fixture
def ingeniero_soporte(empresa_acme):
    return Usuario.objects.create_user(
        correo="ingeniero1@datak.co",
        password="SecurePassword2026#",
        nombre="Iván Ingeniero",
        rol=RolChoices.RESPONSABLE_ATENCION,
        empresa=empresa_acme,
        activo=True,
    )


def test_full_support_lifecycle_external_creation_to_resolution(
    empresa_acme, modulo_facturacion, cliente_acme, agente_soporte, ingeniero_soporte
):
    """E2E Test: External WhatsApp report -> Inbox -> Classify -> Assign -> Notes -> Resolve -> Notify."""
    agent_client = APIClient()
    agent_client.force_authenticate(user=agente_soporte)

    # 1. External ticket registration via WhatsApp (RF9)
    create_payload = {
        "empresa_id": empresa_acme.id,
        "modulo_id": modulo_facturacion.id,
        "canal_origen": CanalOrigenChoices.WHATSAPP,
        "asunto": "Error en sincronización DIAN",
        "descripcion": "El cliente reporta por WhatsApp que las facturas no sincronizan con DIAN desde las 9am.",
        "prioridad": PrioridadChoices.MEDIA,
        "pestana_o_documento": "Módulo Facturación -> Generar",
        "mensaje_error_tecnico": "HTTP 502 Bad Gateway DIAN Gateway Timeout",
    }
    create_res = agent_client.post("/api/v1/support/tickets/", create_payload, format="json")
    assert create_res.status_code == status.HTTP_201_CREATED, create_res.data
    radicado = create_res.data["radicado"]
    ticket_id = create_res.data["id"]
    assert radicado.startswith("TK-")
    assert create_res.data["estado"] == EstadoChoices.ABIERTO
    assert create_res.data["canal_origen"] == CanalOrigenChoices.WHATSAPP

    # 2. Unified Inbox listing with filters (RF7)
    inbox_res = agent_client.get(f"/api/v1/support/tickets/?empresa={empresa_acme.id}&estado=Abierto")
    assert inbox_res.status_code == status.HTTP_200_OK
    results = inbox_res.data["results"]
    assert any(t["radicado"] == radicado for t in results)

    # 3. Support Ticket Detail inspection (RF8)
    detail_res = agent_client.get(f"/api/v1/support/tickets/{radicado}/")
    assert detail_res.status_code == status.HTTP_200_OK
    assert detail_res.data["radicado"] == radicado
    assert len(detail_res.data["historial"]) >= 1
    assert detail_res.data["historial"][0]["tipo_accion"] == TipoAccionChoices.CREACION

    # 4. Classify and prioritize ticket (RF10)
    classify_payload = {
        "clasificacion": ClasificacionChoices.BUG,
        "prioridad": PrioridadChoices.CRITICA,
    }
    classify_res = agent_client.patch(
        f"/api/v1/support/tickets/{ticket_id}/clasificar/",
        classify_payload,
        format="json",
    )
    assert classify_res.status_code == status.HTTP_200_OK
    assert classify_res.data["clasificacion"] == ClasificacionChoices.BUG
    assert classify_res.data["prioridad"] == PrioridadChoices.CRITICA

    # 5. List available staff and assign ticket (RF11)
    staff_res = agent_client.get("/api/v1/support/responsables/")
    assert staff_res.status_code == status.HTTP_200_OK
    assert any(s["id"] == ingeniero_soporte.id for s in staff_res.data)

    assign_payload = {"responsable_id": ingeniero_soporte.id}
    assign_res = agent_client.patch(
        f"/api/v1/support/tickets/{ticket_id}/asignar/",
        assign_payload,
        format="json",
    )
    assert assign_res.status_code == status.HTTP_200_OK
    assert assign_res.data["estado"] == EstadoChoices.EN_GESTION
    assert assign_res.data["responsable"]["id"] == ingeniero_soporte.id

    # 6. Engineer logs in and checks their assigned queue (RF13)
    engineer_client = APIClient()
    engineer_client.force_authenticate(user=ingeniero_soporte)

    queue_res = engineer_client.get("/api/v1/support/mis-tickets/?estado=En gestion")
    assert queue_res.status_code == status.HTTP_200_OK
    assert any(t["radicado"] == radicado for t in queue_res.data["results"])

    # 7. Engineer registers a private internal note (RF14)
    note_payload = {
        "observaciones": "Se reinició el worker de conexión SSL con el web service de la DIAN. Pruebas preliminares OK."
    }
    note_res = engineer_client.post(
        f"/api/v1/support/tickets/{ticket_id}/notas-internas/",
        note_payload,
        format="json",
    )
    assert note_res.status_code == status.HTTP_201_CREATED
    # Verify the note is present in internal audit history
    assert any(
        item["tipo_accion"] == TipoAccionChoices.NOTA_INTERNA and item["es_interna"] is True
        for item in note_res.data["historial"]
    )

    # 8. PRIVACY BOUNDARY CHECK (RNF2): Client viewing ticket NEVER sees internal note or engineer name
    client_api = APIClient()
    client_api.force_authenticate(user=cliente_acme)

    client_view = client_api.get(f"/api/v1/client/tickets/{radicado}/")
    assert client_view.status_code == status.HTTP_200_OK
    assert "responsable" not in client_view.data
    # Client history only contains public events
    for public_event in client_view.data.get("historial", []):
        assert public_event.get("tipo_accion") != TipoAccionChoices.NOTA_INTERNA
        assert "es_interna" not in public_event
        assert "actor" not in public_event

    # 9. Engineer resolves ticket (RF15)
    resolve_payload = {
        "comentario_solucion": "El servicio de sincronización con la DIAN fue restablecido. Las facturas pendientes ya fueron procesadas y confirmadas."
    }
    resolve_res = engineer_client.post(
        f"/api/v1/support/tickets/{ticket_id}/resolver/",
        resolve_payload,
        format="json",
    )
    assert resolve_res.status_code == status.HTTP_200_OK
    assert resolve_res.data["estado"] == EstadoChoices.RESUELTO
    assert resolve_res.data["comentario_solucion"] == resolve_payload["comentario_solucion"]

    # 10. Verify notification created and client consumes it (RF16)
    notif_res = client_api.get("/api/v1/client/notificaciones/")
    assert notif_res.status_code == status.HTTP_200_OK
    assert notif_res.data["unread_count"] >= 1
    client_notifs = notif_res.data["notificaciones"]
    target_notif = next((n for n in client_notifs if n["ticket_radicado"] == radicado), None)
    assert target_notif is not None
    assert target_notif["leida"] is False
    assert target_notif["tipo"] == "resolucion"

    # Mark as read
    mark_res = client_api.patch(f"/api/v1/client/notificaciones/{target_notif['id']}/leida/")
    assert mark_res.status_code == status.HTTP_200_OK
    assert mark_res.data["leida"] is True

    # Check unread count updated
    updated_notif_res = client_api.get("/api/v1/client/notificaciones/")
    assert updated_notif_res.data["unread_count"] == 0


def test_support_dismissal_flow_and_restrictions(
    empresa_acme, modulo_facturacion, cliente_acme, agente_soporte, ingeniero_soporte
):
    """E2E Test: Ticket dismissed as 'No procedente' (RF12) -> triggers client notification."""
    ticket = Ticket.objects.create(
        radicado="TK-2026-000777",
        empresa=empresa_acme,
        modulo=modulo_facturacion,
        creado_por=cliente_acme,
        asunto="Solicitud de reporte personalizado",
        descripcion="Requerimos un reporte no contemplado en el contrato de servicio.",
        prioridad=PrioridadChoices.BAJA,
        estado=EstadoChoices.ABIERTO,
        canal_origen=CanalOrigenChoices.PORTAL,
    )

    agent_client = APIClient()
    agent_client.force_authenticate(user=agente_soporte)

    # 1. Dismiss ticket (RF12)
    dismiss_payload = {
        "motivo_no_procedente": "La funcionalidad solicitada no forma parte del alcance contratado. Se remite al área comercial."
    }
    dismiss_res = agent_client.post(
        f"/api/v1/support/tickets/{ticket.id}/no-procedente/",
        dismiss_payload,
        format="json",
    )
    assert dismiss_res.status_code == status.HTTP_200_OK
    assert dismiss_res.data["estado"] == EstadoChoices.NO_PROCEDENTE

    # 2. Assert closed ticket rejects internal notes and resolution (HTTP 400)
    engineer_client = APIClient()
    engineer_client.force_authenticate(user=ingeniero_soporte)

    note_attempt = engineer_client.post(
        f"/api/v1/support/tickets/{ticket.id}/notas-internas/",
        {"observaciones": "Nota tardía"},
        format="json",
    )
    assert note_attempt.status_code == status.HTTP_400_BAD_REQUEST

    resolve_attempt = engineer_client.post(
        f"/api/v1/support/tickets/{ticket.id}/resolver/",
        {"comentario_solucion": "Solución tardía"},
        format="json",
    )
    assert resolve_attempt.status_code == status.HTTP_400_BAD_REQUEST

    # 3. Client checks notifications (RF16)
    client_api = APIClient()
    client_api.force_authenticate(user=cliente_acme)

    notif_res = client_api.get("/api/v1/client/notificaciones/")
    assert notif_res.status_code == status.HTTP_200_OK
    notif = next((n for n in notif_res.data["notificaciones"] if n["ticket_radicado"] == ticket.radicado), None)
    assert notif is not None
    assert notif["tipo"] == "no_procedente"
    assert notif["leida"] is False


def test_strict_role_enforcement_on_support_endpoints(cliente_acme, agente_soporte):
    """Security Test: Cliente cannot reach /api/v1/support/** endpoints (403)."""
    client_api = APIClient()
    client_api.force_authenticate(user=cliente_acme)

    assert client_api.get("/api/v1/support/tickets/").status_code == status.HTTP_403_FORBIDDEN
    assert client_api.get("/api/v1/support/mis-tickets/").status_code == status.HTTP_403_FORBIDDEN
    assert client_api.get("/api/v1/support/responsables/").status_code == status.HTTP_403_FORBIDDEN
    assert client_api.get("/api/v1/support/empresas/").status_code == status.HTTP_403_FORBIDDEN
    assert (
        client_api.post(
            "/api/v1/support/tickets/",
            {"empresa_id": 1, "modulo_id": 1, "asunto": "X", "descripcion": "Y"},
            format="json",
        ).status_code
        == status.HTTP_403_FORBIDDEN
    )
