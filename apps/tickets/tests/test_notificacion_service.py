"""Tests for TicketNotificacion model and NotificationService (Task BE-23, RF16, issue #55).

Verifies:
1. Exact 9 logical fields on `TicketNotificacion` model (section 3.6 of ARCHITECTURE_AND_DATA_MODEL_REFERENCE.md).
2. Creation of in-portal notification and email dispatch on ticket resolution ('Resuelto').
3. Creation of in-portal notification and email dispatch on ticket dismissal ('No procedente').
4. Email failure resilience: notification and ticket state remain persisted if SMTP fails.
5. Dismissal endpoint (BE-21) triggers notification service correctly.
"""

from unittest.mock import patch

import pytest
from django.core import mail
from django.utils import timezone
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
from apps.tickets.services import NotificationService


@pytest.fixture
def empresa(db):
    return Empresa.objects.create(
        nombre="Acme Corp",
        identificacion="NIT-900123456-1",
        activa=True,
    )


@pytest.fixture
def modulo(empresa):
    return ModuloContratado.objects.create(
        empresa=empresa,
        nombre="Facturación Electrónica",
        codigo="FACT",
        activo=True,
    )


@pytest.fixture
def cliente(empresa):
    return Usuario.objects.create_user(
        correo="cliente@acme.com",
        password="ClaveSegura#2026",
        nombre="Carlos Cliente",
        rol=RolChoices.CLIENTE,
        empresa=empresa,
        activo=True,
    )


@pytest.fixture
def agente(db):
    return Usuario.objects.create_user(
        correo="agente@datak.co",
        password="ClaveSegura#2026",
        nombre="Ana Agente",
        rol=RolChoices.AGENTE_SOPORTE,
        activo=True,
    )


@pytest.fixture
def ticket(empresa, modulo, cliente):
    return Ticket.objects.create(
        radicado="TK-2026-000100",
        empresa=empresa,
        creado_por=cliente,
        modulo=modulo,
        pestana_o_documento="Factura #123",
        asunto="Error al emitir factura",
        descripcion="Falla con código 500 al guardar factura de venta.",
        prioridad=PrioridadChoices.ALTA,
        estado=EstadoChoices.ABIERTO,
        canal_origen=CanalOrigenChoices.PORTAL,
    )


@pytest.mark.django_db
def test_ticket_notificacion_model_has_exact_9_fields():
    """Validates that TicketNotificacion has exactly 9 database fields (FP8 architecture invariant)."""
    field_names = [f.name for f in TicketNotificacion._meta.fields]
    expected_fields = [
        "id",
        "destinatario",
        "empresa",
        "ticket",
        "titulo",
        "mensaje",
        "estado_nuevo",
        "leida",
        "fecha_creacion",
    ]
    assert sorted(field_names) == sorted(expected_fields)
    assert len(field_names) == 9


@pytest.mark.django_db
def test_notify_ticket_closed_resuelto(ticket, cliente):
    """Verifies notification creation and email dispatch when ticket is resolved."""
    ticket.estado = EstadoChoices.RESUELTO
    ticket.comentario_solucion = "Se reinició el servicio de emisión y se reintentó con éxito."
    ticket.fecha_resolucion = timezone.now()
    ticket.save()

    mail.outbox.clear()

    notificacion = NotificationService.notify_ticket_closed(ticket)

    assert notificacion is not None
    assert notificacion.destinatario == cliente
    assert notificacion.empresa == ticket.empresa
    assert notificacion.ticket == ticket
    assert notificacion.estado_nuevo == EstadoChoices.RESUELTO
    assert notificacion.leida is False
    assert "Ticket Resuelto: TK-2026-000100" in notificacion.titulo
    assert "Se reinició el servicio de emisión" in notificacion.mensaje

    # Verifies email was sent
    assert len(mail.outbox) == 1
    sent_email = mail.outbox[0]
    assert cliente.correo in sent_email.to
    assert "Ticket Resuelto: TK-2026-000100" in sent_email.subject
    assert "Se reinició el servicio de emisión" in sent_email.body


@pytest.mark.django_db
def test_notify_ticket_closed_no_procedente(ticket, cliente):
    """Verifies notification creation and email dispatch when ticket is dismissed."""
    ticket.estado = EstadoChoices.NO_PROCEDENTE
    ticket.motivo_no_procedente = "Solicitud fuera de alcance del contrato estándar."
    ticket.fecha_resolucion = timezone.now()
    ticket.save()

    mail.outbox.clear()

    notificacion = NotificationService.notify_ticket_closed(ticket)

    assert notificacion is not None
    assert notificacion.destinatario == cliente
    assert notificacion.estado_nuevo == EstadoChoices.NO_PROCEDENTE
    assert "Ticket No Procedente: TK-2026-000100" in notificacion.titulo
    assert "fuera de alcance del contrato estándar" in notificacion.mensaje

    # Verifies email was sent
    assert len(mail.outbox) == 1
    sent_email = mail.outbox[0]
    assert cliente.correo in sent_email.to
    assert "Ticket No Procedente: TK-2026-000100" in sent_email.subject
    assert "fuera de alcance del contrato estándar" in sent_email.body


@pytest.mark.django_db
def test_notify_ticket_closed_resilient_to_email_failure(ticket, cliente):
    """Notification record must still be created even if SMTP raises an exception."""
    ticket.estado = EstadoChoices.RESUELTO
    ticket.comentario_solucion = "Solución aplicada correctamente."
    ticket.fecha_resolucion = timezone.now()
    ticket.save()

    with patch("apps.tickets.services.EmailMultiAlternatives.send", side_effect=Exception("SMTP connection failed")):
        notificacion = NotificationService.notify_ticket_closed(ticket)

    assert notificacion is not None
    assert TicketNotificacion.objects.filter(pk=notificacion.pk).exists()
    assert notificacion.destinatario == cliente


@pytest.mark.django_db
def test_notify_ticket_without_creado_por_returns_none(ticket):
    """If ticket.creado_por is None, logs warning and creates no notification."""
    ticket.creado_por = None
    notificacion = NotificationService.notify_ticket_closed(ticket)
    assert notificacion is None
    assert TicketNotificacion.objects.count() == 0


@pytest.mark.django_db
def test_dismiss_view_triggers_notification(ticket, agente, cliente):
    """Dismiss endpoint (/no-procedente/) automatically creates a TicketNotificacion."""
    client = APIClient()
    client.force_authenticate(user=agente)

    mail.outbox.clear()

    payload = {"motivo_no_procedente": "La función solicitada no existe en esta versión."}
    url = f"/api/v1/support/tickets/{ticket.pk}/no-procedente/"
    response = client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_200_OK

    notif = TicketNotificacion.objects.filter(ticket=ticket).first()
    assert notif is not None
    assert notif.destinatario == cliente
    assert notif.estado_nuevo == EstadoChoices.NO_PROCEDENTE
    assert "no existe en esta versión" in notif.mensaje
    assert len(mail.outbox) == 1
