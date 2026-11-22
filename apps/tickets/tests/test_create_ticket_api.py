"""Pruebas del endpoint de creación de tickets: `POST /api/v1/client/tickets/` (tarea BE-11, issue #24, RF1).

Cubren los criterios de aceptación de la tarea:
- Creación exitosa (`201 Created`): cliente autenticado envía payload válido;
  responde con `id`, `radicado`, `estado`, `asunto`, `prioridad`, `canal_origen`,
  `fecha_creacion`, `modulo` y `mensaje`; guarda en BD con `empresa`, `creado_por`
  y `canal_origen='Portal'`; crea el `TicketItem` inicial (`CREACION`) y envía el
  comprobante por correo (`mail.outbox`).
- Campos requeridos faltantes o prioridad inválida (`400 Bad Request`).
- Módulo no contratado (de otra empresa), inactivo (`activo=False`) o inexistente
  retorna `400 Bad Request` con mensaje claro en español y no crea ningún ticket.
- Aislamiento multi-tenant (RNF2): cualquier `empresa_id` o `creado_por` enviado
  en el payload es ignorado; siempre se toma del usuario autenticado.
- Permisos (`401` / `403`): solicitud anónima recibe `401` y personal interno
  (`agente@datak.co` / `dev@datak.co`) recibe `403 Forbidden`.

Ejecutar solo estas pruebas:
    pytest apps/tickets/tests/test_create_ticket_api.py -v
"""

import re

import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.companies.models import Empresa, ModuloContratado, RolChoices, Usuario
from apps.tickets.models import (
    CanalOrigenChoices,
    EstadoChoices,
    Ticket,
    TicketItem,
    TipoAccionChoices,
)

URL = "/api/v1/client/tickets/"
PASSWORD = "test123456"


@pytest.fixture
def empresa_acme():
    return Empresa.objects.create(nombre="Acme Industrial S.A.S.", identificacion="900123456-7")


@pytest.fixture
def empresa_global():
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
def modulo_facturacion(empresa_acme):
    return ModuloContratado.objects.create(
        empresa=empresa_acme,
        codigo="FACTURACION",
        nombre="Facturación Electrónica",
        activo=True,
    )


@pytest.fixture
def modulo_inactivo(empresa_acme):
    return ModuloContratado.objects.create(
        empresa=empresa_acme,
        codigo="NOMINA",
        nombre="Nómina Electrónica",
        activo=False,
    )


@pytest.fixture
def modulo_global(empresa_global):
    return ModuloContratado.objects.create(
        empresa=empresa_global,
        codigo="VENTAS",
        nombre="Gestión de Ventas",
        activo=True,
    )


@pytest.fixture
def payload_valido(modulo_facturacion):
    return {
        "modulo_id": modulo_facturacion.id,
        "pestana_o_documento": "Emisión de Facturas / F-203",
        "asunto": "Error 500 al emitir factura electrónica con retención",
        "descripcion": "Al confirmar la factura el sistema no completa el proceso.",
        "mensaje_error": "Server Error: RetencionCalculatorException",
        "prioridad": "Alta",
    }


# --------------------------------------------------------------------------
# 1. Creación exitosa (201 Created)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_ticket_successfully_returns_201_creates_item_and_sends_email(
    empresa_acme, cliente_acme, modulo_facturacion, payload_valido
):
    """Un cliente autenticado radica un ticket válido y recibe 201, TicketItem y comprobante."""
    client = APIClient()
    client.force_authenticate(user=cliente_acme)

    response = client.post(URL, payload_valido, format="json")

    assert response.status_code == 201
    data = response.data

    assert "id" in data
    assert re.match(r"^TK-\d{4}-000001$", data["radicado"])
    assert data["estado"] == EstadoChoices.ABIERTO
    assert data["prioridad"] == "Alta"
    assert data["canal_origen"] == CanalOrigenChoices.PORTAL
    assert data["asunto"] == payload_valido["asunto"]
    assert data["fecha_creacion"] is not None
    assert data["modulo"] == {
        "id": modulo_facturacion.id,
        "nombre": "Facturación Electrónica",
    }
    assert "Incidencia radicada exitosamente" in data["mensaje"]

    # Verificar persistencia en base de datos con empresa, creado_por y canal_origen='Portal'
    ticket = Ticket.objects.get(pk=data["id"])
    assert ticket.radicado == data["radicado"]
    assert ticket.empresa == empresa_acme
    assert ticket.creado_por == cliente_acme
    assert ticket.modulo == modulo_facturacion
    assert ticket.canal_origen == CanalOrigenChoices.PORTAL
    assert ticket.estado == EstadoChoices.ABIERTO

    # Verificar creación del TicketItem inicial (CREACION)
    items = list(TicketItem.objects.filter(ticket=ticket))
    assert len(items) == 1
    assert items[0].tipo_accion == TipoAccionChoices.CREACION
    assert items[0].actor == cliente_acme
    assert items[0].estado_nuevo == EstadoChoices.ABIERTO
    assert items[0].es_interna is False

    # Verificar despacho del correo comprobante
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["cliente@acme.com"]
    assert ticket.radicado in mail.outbox[0].subject


@pytest.mark.django_db
def test_ignores_spoofed_empresa_or_canal_in_request_payload(
    empresa_acme, empresa_global, cliente_acme, payload_valido
):
    """RNF2: aunque el payload envíe `empresa_id` ajena o `canal_origen` distinto, usa los del servidor."""
    client = APIClient()
    client.force_authenticate(user=cliente_acme)

    payload_manipulado = {
        **payload_valido,
        "empresa": empresa_global.id,
        "empresa_id": empresa_global.id,
        "canal_origen": "WhatsApp",
    }

    response = client.post(URL, payload_manipulado, format="json")

    assert response.status_code == 201
    ticket = Ticket.objects.get(pk=response.data["id"])
    assert ticket.empresa == empresa_acme
    assert ticket.canal_origen == CanalOrigenChoices.PORTAL


# --------------------------------------------------------------------------
# 2. Validación de campos requeridos (400 Bad Request)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_missing_required_fields_returns_400(cliente_acme):
    """Enviar un payload sin los campos obligatorios devuelve 400 con errores por campo."""
    client = APIClient()
    client.force_authenticate(user=cliente_acme)

    response = client.post(URL, {}, format="json")

    assert response.status_code == 400
    assert {
        "modulo_id",
        "pestana_o_documento",
        "asunto",
        "descripcion",
        "prioridad",
    } <= set(response.data.keys())
    assert Ticket.objects.count() == 0


@pytest.mark.django_db
def test_invalid_prioridad_returns_400(cliente_acme, payload_valido):
    """Una prioridad fuera de PrioridadChoices devuelve 400."""
    client = APIClient()
    client.force_authenticate(user=cliente_acme)

    response = client.post(URL, {**payload_valido, "prioridad": "Urgente"}, format="json")

    assert response.status_code == 400
    assert "prioridad" in response.data
    assert Ticket.objects.count() == 0


# --------------------------------------------------------------------------
# 3. Módulo no contratado, de otra empresa o inactivo (400 Bad Request)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_module_from_another_company_returns_400_and_creates_no_ticket(
    cliente_acme, modulo_global, payload_valido
):
    """Intentar usar el `modulo_id` de otra empresa responde 400 y no crea ningún ticket."""
    client = APIClient()
    client.force_authenticate(user=cliente_acme)

    response = client.post(
        URL,
        {**payload_valido, "modulo_id": modulo_global.id},
        format="json",
    )

    assert response.status_code == 400
    assert "modulo_id" in response.data
    assert "no está contratado" in response.data["modulo_id"][0]
    assert Ticket.objects.count() == 0
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_inactive_module_returns_400_and_creates_no_ticket(
    cliente_acme, modulo_inactivo, payload_valido
):
    """Intentar usar un módulo con `activo=False` responde 400 y no crea ningún ticket."""
    client = APIClient()
    client.force_authenticate(user=cliente_acme)

    response = client.post(
        URL,
        {**payload_valido, "modulo_id": modulo_inactivo.id},
        format="json",
    )

    assert response.status_code == 400
    assert "modulo_id" in response.data
    assert "no está activo" in response.data["modulo_id"][0]
    assert Ticket.objects.count() == 0


# --------------------------------------------------------------------------
# 4. Permisos (401 Unauthorized / 403 Forbidden)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_unauthenticated_post_returns_401(payload_valido):
    """Sin token de autenticación retorna 401."""
    response = APIClient().post(URL, payload_valido, format="json")

    assert response.status_code == 401
    assert Ticket.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    "correo,rol",
    [
        ("agente@datak.co", RolChoices.AGENTE_SOPORTE),
        ("dev@datak.co", RolChoices.RESPONSABLE_ATENCION),
    ],
)
def test_internal_staff_post_returns_403_forbidden(payload_valido, correo, rol):
    """Agentes y desarrolladores internos sin rol cliente reciben 403 Forbidden."""
    interno = Usuario.objects.create_user(
        correo=correo,
        password=PASSWORD,
        nombre="Personal Interno",
        rol=rol,
    )
    client = APIClient()
    client.force_authenticate(user=interno)

    response = client.post(URL, payload_valido, format="json")

    assert response.status_code == 403
    assert Ticket.objects.count() == 0
