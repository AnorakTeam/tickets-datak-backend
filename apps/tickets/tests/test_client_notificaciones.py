"""Tests for client notification endpoints (Task BE-25, RF16, issue #57).

Covers:
1. `GET /api/v1/client/notificaciones/`:
   - Scoped strictly to `destinatario=request.user` and `empresa=request.user.empresa`.
   - Chronological ordering (newest first).
   - Accurately counts unread notifications (`unread_count`).
   - Rejects unauthenticated requests with 401.
   - Rejects internal staff requests with 403.
2. `PATCH /api/v1/client/notificaciones/{id}/leida/`:
   - Successfully marks notification as read (`leida=True`).
   - Cross-user and cross-company accesses respond with 404 Not Found (RNF2 anti-enumeration).
   - Idempotency when already marked as read.
"""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.companies.models import Empresa, ModuloContratado, RolChoices, Usuario
from apps.tickets.models import (
    CanalOrigenChoices,
    EstadoChoices,
    PrioridadChoices,
    Ticket,
    TicketNotificacion,
)


@pytest.fixture
def empresa_a(db):
    return Empresa.objects.create(
        nombre="Alpha Corp",
        identificacion="NIT-900111111-1",
        activa=True,
    )


@pytest.fixture
def empresa_b(db):
    return Empresa.objects.create(
        nombre="Beta Inc",
        identificacion="NIT-900222222-2",
        activa=True,
    )


@pytest.fixture
def modulo_a(empresa_a):
    return ModuloContratado.objects.create(
        empresa=empresa_a,
        nombre="Módulo Ventas",
        codigo="VENT",
        activo=True,
    )


@pytest.fixture
def modulo_b(empresa_b):
    return ModuloContratado.objects.create(
        empresa=empresa_b,
        nombre="Módulo Nómina",
        codigo="NOM",
        activo=True,
    )


@pytest.fixture
def cliente_a1(empresa_a):
    return Usuario.objects.create_user(
        correo="cliente1@alpha.com",
        password="Password123#",
        nombre="Carlos Alpha 1",
        rol=RolChoices.CLIENTE,
        empresa=empresa_a,
        activo=True,
    )


@pytest.fixture
def cliente_a2(empresa_a):
    return Usuario.objects.create_user(
        correo="cliente2@alpha.com",
        password="Password123#",
        nombre="María Alpha 2",
        rol=RolChoices.CLIENTE,
        empresa=empresa_a,
        activo=True,
    )


@pytest.fixture
def cliente_b(empresa_b):
    return Usuario.objects.create_user(
        correo="cliente@beta.com",
        password="Password123#",
        nombre="Bernardo Beta",
        rol=RolChoices.CLIENTE,
        empresa=empresa_b,
        activo=True,
    )


@pytest.fixture
def agente_soporte(empresa_a):
    return Usuario.objects.create_user(
        correo="agente@datak.co",
        password="Password123#",
        nombre="Agente Soporte",
        rol=RolChoices.AGENTE_SOPORTE,
        empresa=empresa_a,
        activo=True,
    )


@pytest.fixture
def ticket_a(empresa_a, modulo_a, cliente_a1):
    return Ticket.objects.create(
        radicado="TK-2026-000888",
        empresa=empresa_a,
        modulo=modulo_a,
        creado_por=cliente_a1,
        asunto="Fallo al emitir factura",
        descripcion="No se puede generar la factura electrónica en PDF.",
        prioridad=PrioridadChoices.MEDIA,
        estado=EstadoChoices.RESUELTO,
        canal_origen=CanalOrigenChoices.PORTAL,
        comentario_solucion="Se actualizó la plantilla de PDF correctamente.",
    )


@pytest.fixture
def ticket_b(empresa_b, modulo_b, cliente_b):
    return Ticket.objects.create(
        radicado="TK-2026-000999",
        empresa=empresa_b,
        modulo=modulo_b,
        creado_por=cliente_b,
        asunto="Error en nómina",
        descripcion="Cálculo erróneo de horas extras.",
        prioridad=PrioridadChoices.ALTA,
        estado=EstadoChoices.NO_PROCEDENTE,
        canal_origen=CanalOrigenChoices.PORTAL,
        comentario_solucion="No procedente por desfase de fechas.",
    )


@pytest.fixture
def notificacion_a1(empresa_a, cliente_a1, ticket_a):
    return TicketNotificacion.objects.create(
        destinatario=cliente_a1,
        empresa=empresa_a,
        ticket=ticket_a,
        titulo=f"Incidencia {ticket_a.radicado} resuelta",
        mensaje="Tu incidencia ha sido resuelta satisfactoriamente.",
        estado_nuevo="Resuelto",
        leida=False,
    )


def test_anonymous_cannot_access_notifications(client):
    res_get = client.get("/api/v1/client/notificaciones/")
    assert res_get.status_code == status.HTTP_401_UNAUTHORIZED

    res_patch = client.patch("/api/v1/client/notificaciones/1/leida/")
    assert res_patch.status_code == status.HTTP_401_UNAUTHORIZED


def test_staff_user_cannot_access_client_notifications(agente_soporte):
    client = APIClient()
    client.force_authenticate(user=agente_soporte)

    res_get = client.get("/api/v1/client/notificaciones/")
    assert res_get.status_code == status.HTTP_403_FORBIDDEN

    res_patch = client.patch("/api/v1/client/notificaciones/1/leida/")
    assert res_patch.status_code == status.HTTP_403_FORBIDDEN


def test_client_receives_only_own_notifications(
    empresa_a, empresa_b, cliente_a1, cliente_a2, cliente_b, ticket_a, ticket_b
):
    # 2 notifications for cliente_a1 (one unread, one read)
    n1 = TicketNotificacion.objects.create(
        destinatario=cliente_a1,
        empresa=empresa_a,
        ticket=ticket_a,
        titulo="Notificación 1",
        mensaje="Mensaje 1",
        estado_nuevo="Resuelto",
        leida=False,
    )
    n2 = TicketNotificacion.objects.create(
        destinatario=cliente_a1,
        empresa=empresa_a,
        ticket=ticket_a,
        titulo="Notificación 2",
        mensaje="Mensaje 2",
        estado_nuevo="Resuelto",
        leida=True,
    )

    # 1 notification for another user in same company (cliente_a2)
    TicketNotificacion.objects.create(
        destinatario=cliente_a2,
        empresa=empresa_a,
        ticket=ticket_a,
        titulo="Notificación A2",
        mensaje="Mensaje A2",
        estado_nuevo="Resuelto",
        leida=False,
    )

    # 1 notification for another company (cliente_b)
    TicketNotificacion.objects.create(
        destinatario=cliente_b,
        empresa=empresa_b,
        ticket=ticket_b,
        titulo="Notificación B",
        mensaje="Mensaje B",
        estado_nuevo="No procedente",
        leida=False,
    )

    api_client = APIClient()
    api_client.force_authenticate(user=cliente_a1)

    response = api_client.get("/api/v1/client/notificaciones/")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "unread_count" in data
    assert data["unread_count"] == 1
    assert data["count"] == 2

    # Exactly the 2 notifications belonging to cliente_a1
    ids = [item["id"] for item in data["notificaciones"]]
    assert ids == [n2.id, n1.id]  # Ordered -fecha_creacion, -id


def test_notification_payload_structure(cliente_a1, notificacion_a1, ticket_a):
    api_client = APIClient()
    api_client.force_authenticate(user=cliente_a1)

    response = api_client.get("/api/v1/client/notificaciones/")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert len(data["notificaciones"]) == 1
    item = data["notificaciones"][0]

    assert item["id"] == notificacion_a1.id
    assert item["titulo"] == notificacion_a1.titulo
    assert item["mensaje"] == notificacion_a1.mensaje
    assert item["estado_nuevo"] == "Resuelto"
    assert item["leida"] is False
    assert item["ticket_radicado"] == ticket_a.radicado
    assert item["radicado"] == ticket_a.radicado
    assert item["ticket"]["id"] == ticket_a.id
    assert item["ticket"]["radicado"] == ticket_a.radicado
    assert item["ticket"]["asunto"] == ticket_a.asunto
    assert item["tipo"] == "resolucion"


def test_mark_notification_as_read_success(cliente_a1, notificacion_a1):
    assert notificacion_a1.leida is False

    api_client = APIClient()
    api_client.force_authenticate(user=cliente_a1)

    url = f"/api/v1/client/notificaciones/{notificacion_a1.id}/leida/"
    response = api_client.patch(url)
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["success"] is True
    assert data["id"] == notificacion_a1.id
    assert data["leida"] is True

    notificacion_a1.refresh_from_db()
    assert notificacion_a1.leida is True

    # Subsequent GET shows unread_count = 0
    get_res = api_client.get("/api/v1/client/notificaciones/")
    assert get_res.json()["unread_count"] == 0


def test_mark_notification_as_read_is_idempotent(cliente_a1, notificacion_a1):
    notificacion_a1.leida = True
    notificacion_a1.save(update_fields=["leida"])

    api_client = APIClient()
    api_client.force_authenticate(user=cliente_a1)

    url = f"/api/v1/client/notificaciones/{notificacion_a1.id}/leida/"
    response = api_client.patch(url)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["leida"] is True


def test_cannot_mark_other_user_notification_returns_404(
    empresa_a, cliente_a1, cliente_a2, ticket_a
):
    notif_a2 = TicketNotificacion.objects.create(
        destinatario=cliente_a2,
        empresa=empresa_a,
        ticket=ticket_a,
        titulo="Para A2",
        mensaje="Solo para A2",
        estado_nuevo="Resuelto",
        leida=False,
    )

    api_client = APIClient()
    api_client.force_authenticate(user=cliente_a1)

    url = f"/api/v1/client/notificaciones/{notif_a2.id}/leida/"
    response = api_client.patch(url)
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_cannot_mark_other_company_notification_returns_404(
    empresa_b, cliente_a1, cliente_b, ticket_b
):
    notif_b = TicketNotificacion.objects.create(
        destinatario=cliente_b,
        empresa=empresa_b,
        ticket=ticket_b,
        titulo="Para B",
        mensaje="Solo para B",
        estado_nuevo="No procedente",
        leida=False,
    )

    api_client = APIClient()
    api_client.force_authenticate(user=cliente_a1)

    url = f"/api/v1/client/notificaciones/{notif_b.id}/leida/"
    response = api_client.patch(url)
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_mark_nonexistent_notification_returns_404(cliente_a1):
    api_client = APIClient()
    api_client.force_authenticate(user=cliente_a1)

    url = "/api/v1/client/notificaciones/999999/leida/"
    response = api_client.patch(url)
    assert response.status_code == status.HTTP_404_NOT_FOUND
