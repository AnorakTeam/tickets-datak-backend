"""Pruebas unitarias del despachador de correos transaccionales `TicketEmailService` (tarea BE-09, issue #22).

Cubren los criterios de aceptación de la tarea:
- Envío automático del comprobante al crear un ticket desde `TicketCreationService`:
  verifica destinatario en `django.core.mail.outbox`, asunto, versión `text/plain`
  y alternativa `text/html` en español, y presencia obligatoria del `radicado`,
  `módulo`, `asunto` y `fecha` de registro en ambas versiones.
- Tolerancia a fallos (RF1 Flujo 5.1): cuando el servidor de correo falla
  (`smtplib.SMTPException` o `ConnectionError`), el error se captura y registra
  en logs (`logger.exception`), NO se propaga excepción al cliente y tanto el
  `Ticket` como su `TicketItem` inicial quedan guardados en la base de datos.

Ejecutar solo estas pruebas:
    pytest apps/tickets/tests/test_email_service.py -v
"""

import smtplib
from unittest.mock import patch

import pytest
from django.core import mail
from django.utils import timezone

from apps.companies.models import Empresa, ModuloContratado, RolChoices, Usuario
from apps.tickets.models import PrioridadChoices, Ticket, TicketItem, TipoAccionChoices
from apps.tickets.services import (
    EmailDispatcherService,
    TicketCreationService,
    TicketEmailService,
)


@pytest.fixture
def empresa_acme():
    return Empresa.objects.create(nombre="Acme Industrial S.A.S.", identificacion="900123456-7")


@pytest.fixture
def cliente_acme(empresa_acme):
    return Usuario.objects.create_user(
        correo="cliente@acme.com",
        password="test123456",
        nombre="Carlos Gómez",
        rol=RolChoices.CLIENTE,
        empresa=empresa_acme,
    )


@pytest.fixture
def modulo_facturacion(empresa_acme):
    return ModuloContratado.objects.create(
        empresa=empresa_acme,
        codigo="FACTURACION",
        nombre="Facturación Electrónica",
        activo=True,
    )


@pytest.mark.django_db
def test_ticket_creation_dispatches_multipart_spanish_receipt_email(
    empresa_acme, cliente_acme, modulo_facturacion
):
    """Al crear un ticket se envía el comprobante con `text/plain` y `text/html` en español."""
    ticket = TicketCreationService.create_ticket(
        creado_por=cliente_acme,
        empresa_id=empresa_acme.id,
        modulo_id=modulo_facturacion.id,
        pestana_o_documento="Emisión de Facturas / F-203",
        asunto="Error 500 al emitir factura electrónica",
        descripcion="Al confirmar la factura el sistema no completa el proceso.",
        mensaje_error="Server Error: RetencionCalculatorException",
        prioridad=PrioridadChoices.ALTA,
        year=2026,
    )

    assert len(mail.outbox) == 1
    mensaje = mail.outbox[0]

    # Destinatario y asunto
    assert mensaje.to == ["cliente@acme.com"]
    assert ticket.radicado in mensaje.subject
    assert ticket.asunto in mensaje.subject

    # Debe tener cuerpo en texto plano y alternativa en HTML
    cuerpo_texto = mensaje.body
    assert len(mensaje.alternatives) == 1
    cuerpo_html, mimetype = mensaje.alternatives[0]
    assert mimetype == "text/html"

    # Fecha esperada (formato YYYY-MM-DD)
    fecha_str = timezone.localtime(ticket.fecha_creacion).strftime("%Y-%m-%d")

    # Tanto texto plano como HTML deben estar en español y contener radicado, módulo, asunto y fecha
    for contenido in (cuerpo_texto, cuerpo_html):
        assert "Comprobante" in contenido or "comprobante" in contenido
        assert ticket.radicado in contenido
        assert "Facturación Electrónica" in contenido
        assert "Error 500 al emitir factura electrónica" in contenido
        assert fecha_str in contenido


@pytest.mark.django_db
@pytest.mark.parametrize(
    "excepcion_correo",
    [
        smtplib.SMTPException("SMTP server unavailable"),
        ConnectionError("Connection refused by mail server"),
    ],
)
def test_email_failure_is_logged_and_never_rolls_back_ticket_or_ticket_item(
    empresa_acme, cliente_acme, modulo_facturacion, excepcion_correo, caplog
):
    """Si falla el envío del correo (RF1 Flujo 5.1), se loguea el error y el ticket persiste."""
    with patch.object(
        mail.EmailMultiAlternatives,
        "send",
        side_effect=excepcion_correo,
    ):
        ticket = TicketCreationService.create_ticket(
            creado_por=cliente_acme,
            empresa_id=empresa_acme.id,
            modulo_id=modulo_facturacion.id,
            pestana_o_documento="Emisión de Facturas / F-203",
            asunto="Incidencia pese a fallo SMTP",
            descripcion="El ticket debe guardarse aunque falle el servidor de correo.",
            prioridad=PrioridadChoices.MEDIA,
            year=2026,
        )

    # El ticket y su TicketItem inicial quedaron persistidos en la base de datos
    assert ticket.pk is not None
    assert Ticket.objects.filter(pk=ticket.pk, radicado="TK-2026-000001").exists()
    assert TicketItem.objects.filter(
        ticket=ticket,
        tipo_accion=TipoAccionChoices.CREACION,
    ).exists()

    # El error quedó registrado en el log sin propagarse al cliente
    assert "Error al enviar el comprobante de correo para el ticket TK-2026-000001" in caplog.text


@pytest.mark.django_db
def test_direct_service_call_and_alias_return_boolean_status(
    empresa_acme, cliente_acme, modulo_facturacion
):
    """`TicketEmailService` y su alias `EmailDispatcherService` devuelven True/False según resultado."""
    assert EmailDispatcherService is TicketEmailService

    ticket = TicketCreationService.create_ticket(
        creado_por=cliente_acme,
        empresa_id=empresa_acme.id,
        modulo_id=modulo_facturacion.id,
        pestana_o_documento="Facturación",
        asunto="Prueba directa de servicio de correo",
        descripcion="Detalle",
        year=2026,
    )
    mail.outbox.clear()

    assert TicketEmailService.send_ticket_receipt(ticket) is True
    assert len(mail.outbox) == 1

    with patch.object(
        mail.EmailMultiAlternatives,
        "send",
        side_effect=smtplib.SMTPException("Timeout"),
    ):
        assert TicketEmailService.send_ticket_receipt(ticket) is False
