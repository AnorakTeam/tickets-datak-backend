"""Pruebas de detalle de ticket de soporte y creación externa por agente (tarea BE-20, RF8 y RF9).

Endpoints probados:
- `GET /api/v1/support/tickets/{id}/` (acepta `id` numérico o `radicado`)
- `POST /api/v1/support/tickets/`

Cubren los criterios de aceptación de la tarea:
- Detalle por `id` y por `radicado` (`GET`): ambos formatos resuelven el ticket,
  exponen los 20 campos del modelo y devuelven el `historial` en orden cronológico
  ascendente incluyendo ítems con `es_interna=True`.
- Permisos en `GET` y `POST`: `agente_soporte` y `responsable_atencion` acceden al
  detalle (`200 OK`); solo `agente_soporte` puede registrar tickets externos
  (`POST -> 201 Created`); `cliente` recibe `403 Forbidden`.
- Creación externa exitosa (`POST -> 201 Created`): tanto enviando `creado_por_id`
  explícito como omitiéndolo (resolviendo el cliente activo principal de la empresa),
  confirmando `registrado_por_agente == agente`, `canal_origen` externo (`WhatsApp`),
  radicado generado, `TicketItem(tipo_accion='CREACION')` y envío de correo comprobante.
- Validaciones de negocio (`400 Bad Request`): módulo no contratado o inactivo
  para la `empresa_id` seleccionada, o `creado_por_id` perteneciente a otra empresa.

Ejecutar solo estas pruebas:
    pytest apps/tickets/tests/test_support_detail_create.py -v
"""

import re

import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.companies.models import Empresa, ModuloContratado, RolChoices, Usuario
from apps.tickets.models import (
    CanalOrigenChoices,
    ClasificacionChoices,
    EstadoChoices,
    PrioridadChoices,
    Ticket,
    TicketItem,
    TipoAccionChoices,
)

SUPPORT_TICKETS_URL = "/api/v1/support/tickets/"
PASSWORD = "test123456"

CAMPOS_20_TICKET = {
    "id",
    "radicado",
    "empresa",
    "creado_por",
    "registrado_por_agente",
    "modulo",
    "pestana_o_documento",
    "asunto",
    "descripcion",
    "mensaje_error",
    "prioridad",
    "estado",
    "clasificacion",
    "canal_origen",
    "responsable",
    "comentario_solucion",
    "motivo_no_procedente",
    "fecha_creacion",
    "fecha_actualizacion",
    "fecha_resolucion",
}


def detail_url(lookup):
    return f"/api/v1/support/tickets/{lookup}/"


@pytest.fixture
def empresa_acme():
    return Empresa.objects.create(
        nombre="Acme Industrial S.A.S.",
        identificacion="900123456-7",
        activa=True,
    )


@pytest.fixture
def empresa_global():
    return Empresa.objects.create(
        nombre="Global Logistics Ltda.",
        identificacion="800987654-3",
        activa=True,
    )


@pytest.fixture
def modulos(empresa_acme, empresa_global):
    facturacion = ModuloContratado.objects.create(
        empresa=empresa_acme,
        codigo="FACTURACION",
        nombre="Facturación Electrónica",
        activo=True,
    )
    nomina_inactiva = ModuloContratado.objects.create(
        empresa=empresa_acme,
        codigo="NOMINA",
        nombre="Nómina Electrónica",
        activo=False,
    )
    ventas_global = ModuloContratado.objects.create(
        empresa=empresa_global,
        codigo="VENTAS",
        nombre="Gestión de Ventas",
        activo=True,
    )
    return {
        "facturacion": facturacion,
        "nomina_inactiva": nomina_inactiva,
        "ventas_global": ventas_global,
    }


@pytest.fixture
def usuarios(empresa_acme, empresa_global):
    cliente_acme = Usuario.objects.create_user(
        correo="cliente@acme.com",
        password=PASSWORD,
        nombre="Carlos Gómez",
        rol=RolChoices.CLIENTE,
        empresa=empresa_acme,
    )
    cliente_global = Usuario.objects.create_user(
        correo="cliente@global.com",
        password=PASSWORD,
        nombre="Laura Martínez",
        rol=RolChoices.CLIENTE,
        empresa=empresa_global,
    )
    agente = Usuario.objects.create_user(
        correo="agente@datak.co",
        password=PASSWORD,
        nombre="Andrés Soporte",
        rol=RolChoices.AGENTE_SOPORTE,
    )
    responsable = Usuario.objects.create_user(
        correo="dev@datak.co",
        password=PASSWORD,
        nombre="Camila Dev",
        rol=RolChoices.RESPONSABLE_ATENCION,
    )
    return {
        "cliente_acme": cliente_acme,
        "cliente_global": cliente_global,
        "agente": agente,
        "responsable": responsable,
    }


@pytest.fixture
def ticket_con_historial(empresa_acme, modulos, usuarios):
    """Ticket con 3 eventos en el historial (incluyendo una nota interna)."""
    ticket = Ticket.objects.create(
        radicado="TK-2026-000001",
        empresa=empresa_acme,
        creado_por=usuarios["cliente_acme"],
        registrado_por_agente=usuarios["agente"],
        modulo=modulos["facturacion"],
        pestana_o_documento="Emisión de Facturas / F-203",
        asunto="Error al timbrar factura con retención",
        descripcion="Falla la firma digital.",
        mensaje_error="SignatureError: Invalid certificate",
        prioridad=PrioridadChoices.ALTA,
        estado=EstadoChoices.EN_GESTION,
        clasificacion=ClasificacionChoices.BUG,
        canal_origen=CanalOrigenChoices.WHATSAPP,
        responsable=usuarios["responsable"],
    )
    TicketItem.objects.create(
        ticket=ticket,
        actor=usuarios["agente"],
        tipo_accion=TipoAccionChoices.CREACION,
        estado_nuevo=EstadoChoices.ABIERTO,
        es_interna=False,
        observaciones="Registrado desde WhatsApp.",
    )
    TicketItem.objects.create(
        ticket=ticket,
        actor=usuarios["agente"],
        tipo_accion=TipoAccionChoices.ASIGNACION,
        estado_anterior=EstadoChoices.ABIERTO,
        estado_nuevo=EstadoChoices.EN_GESTION,
        responsable_asignado=usuarios["responsable"],
        es_interna=False,
        observaciones="Asignado a desarrollo.",
    )
    TicketItem.objects.create(
        ticket=ticket,
        actor=usuarios["responsable"],
        tipo_accion=TipoAccionChoices.NOTA_INTERNA,
        es_interna=True,
        observaciones="NOTA INTERNA: revisar certificado en bóveda.",
    )
    return ticket


# --------------------------------------------------------------------------
# 1. Detalle completo por `id` y por `radicado` (RF8)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_detail_resolves_by_numeric_id_and_by_radicado_with_full_history(
    usuarios, ticket_con_historial
):
    """`GET /api/v1/support/tickets/{id}/` funciona tanto con `id` numérico como con `radicado`."""
    client = APIClient()
    client.force_authenticate(user=usuarios["agente"])

    resp_by_id = client.get(detail_url(ticket_con_historial.id))
    resp_by_radicado = client.get(detail_url("TK-2026-000001"))

    assert resp_by_id.status_code == 200
    assert resp_by_radicado.status_code == 200
    assert resp_by_id.data == resp_by_radicado.data

    data = resp_by_id.data
    assert CAMPOS_20_TICKET <= set(data.keys())
    assert "historial" in data

    assert data["id"] == ticket_con_historial.id
    assert data["radicado"] == "TK-2026-000001"
    assert data["empresa"]["nombre"] == "Acme Industrial S.A.S."
    assert data["registrado_por_agente"]["correo"] == "agente@datak.co"
    assert data["responsable"]["correo"] == "dev@datak.co"

    # El historial está en orden cronológico ascendente e incluye notas internas (es_interna=True)
    historial = data["historial"]
    assert len(historial) == 3
    assert [item["tipo_accion"] for item in historial] == [
        "CREACION",
        "ASIGNACION",
        "NOTA_INTERNA",
    ]
    assert historial[2]["es_interna"] is True
    assert "NOTA INTERNA" in historial[2]["observaciones"]


@pytest.mark.django_db
@pytest.mark.parametrize("lookup_inexistente", ["999999", "TK-2026-999999"])
def test_detail_nonexistent_id_or_radicado_returns_404(usuarios, lookup_inexistente):
    """Si el `id` o `radicado` no existe, devuelve 404 Not Found."""
    client = APIClient()
    client.force_authenticate(user=usuarios["agente"])

    response = client.get(detail_url(lookup_inexistente))
    assert response.status_code == 404


# --------------------------------------------------------------------------
# 2. Permisos en GET (detalle) y POST (creación externa)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_detail_accessible_by_responsable_atencion_and_forbidden_for_cliente(
    usuarios, ticket_con_historial
):
    """`responsable_atencion` puede ver el detalle (200); `cliente` recibe 403 Forbidden."""
    client = APIClient()

    client.force_authenticate(user=usuarios["responsable"])
    assert client.get(detail_url(ticket_con_historial.id)).status_code == 200

    client.force_authenticate(user=usuarios["cliente_acme"])
    assert client.get(detail_url(ticket_con_historial.id)).status_code == 403


@pytest.mark.django_db
def test_external_post_permissions_only_allow_agente_soporte(empresa_acme, modulos, usuarios):
    """En `POST /api/v1/support/tickets/`, `cliente` y `responsable_atencion` reciben 403."""
    payload = {
        "empresa_id": empresa_acme.id,
        "modulo_id": modulos["facturacion"].id,
        "pestana_o_documento": "Facturación",
        "asunto": "Reporte por WhatsApp",
        "descripcion": "Detalle reportado al agente.",
        "prioridad": "Media",
        "canal_origen": "WhatsApp",
    }

    # Anónimo -> 401
    assert APIClient().post(SUPPORT_TICKETS_URL, payload, format="json").status_code == 401

    # Cliente -> 403
    client = APIClient()
    client.force_authenticate(user=usuarios["cliente_acme"])
    assert client.post(SUPPORT_TICKETS_URL, payload, format="json").status_code == 403

    # Responsable de atención -> 403 en creación externa
    client.force_authenticate(user=usuarios["responsable"])
    assert client.post(SUPPORT_TICKETS_URL, payload, format="json").status_code == 403


# --------------------------------------------------------------------------
# 3. Creación externa exitosa (POST /api/v1/support/tickets/ -> 201 Created, RF9)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_external_ticket_creation_with_explicit_creado_por_id(empresa_acme, modulos, usuarios):
    """Un agente crea un ticket externo indicando `creado_por_id`; asigna `registrado_por_agente`, `TicketItem` y envía correo."""
    client = APIClient()
    client.force_authenticate(user=usuarios["agente"])

    payload = {
        "empresa_id": empresa_acme.id,
        "creado_por_id": usuarios["cliente_acme"].id,
        "modulo_id": modulos["facturacion"].id,
        "pestana_o_documento": "Emisión de Facturas / F-203",
        "asunto": "Incidencia reportada por WhatsApp",
        "descripcion": "El cliente envió captura del error por WhatsApp.",
        "mensaje_error": "Error 502 Bad Gateway",
        "prioridad": "Alta",
        "canal_origen": "WhatsApp",
    }

    response = client.post(SUPPORT_TICKETS_URL, payload, format="json")

    assert response.status_code == 201
    data = response.data
    assert re.match(r"^TK-\d{4}-000001$", data["radicado"])
    assert data["estado"] == EstadoChoices.ABIERTO
    assert data["canal_origen"] == CanalOrigenChoices.WHATSAPP
    assert data["registrado_por_agente"]["id"] == usuarios["agente"].id
    assert data["creado_por"]["id"] == usuarios["cliente_acme"].id

    ticket = Ticket.objects.get(pk=data["id"])
    assert ticket.registrado_por_agente == usuarios["agente"]
    assert ticket.creado_por == usuarios["cliente_acme"]
    assert ticket.canal_origen == CanalOrigenChoices.WHATSAPP

    # Historial inicial CREACION
    items = list(TicketItem.objects.filter(ticket=ticket))
    assert len(items) == 1
    assert items[0].tipo_accion == TipoAccionChoices.CREACION
    assert items[0].actor == usuarios["agente"]

    # Correo enviado al cliente de la empresa
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["cliente@acme.com"]
    assert ticket.radicado in mail.outbox[0].subject


@pytest.mark.django_db
def test_external_ticket_creation_without_creado_por_id_resolves_company_client(
    empresa_acme, modulos, usuarios
):
    """Si se omite `creado_por_id`, selecciona automáticamente el cliente activo principal de la empresa."""
    client = APIClient()
    client.force_authenticate(user=usuarios["agente"])

    payload = {
        "empresa_id": empresa_acme.id,
        "modulo_id": modulos["facturacion"].id,
        "pestana_o_documento": "Facturación",
        "asunto": "Incidencia reportada por Slack sin indicar usuario",
        "descripcion": "Reportado en el canal compartido de Slack.",
        "prioridad": "Media",
        "canal_origen": "Slack",
    }

    response = client.post(SUPPORT_TICKETS_URL, payload, format="json")

    assert response.status_code == 201
    assert response.data["creado_por"]["id"] == usuarios["cliente_acme"].id
    assert response.data["registrado_por_agente"]["id"] == usuarios["agente"].id
    assert response.data["canal_origen"] == CanalOrigenChoices.SLACK


# --------------------------------------------------------------------------
# 4. Validaciones de negocio (400 Bad Request)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_external_creation_rejects_uncontracted_or_inactive_module_and_mismatched_client(
    empresa_acme, modulos, usuarios
):
    """Rechaza con 400 módulo de otra empresa, módulo inactivo o `creado_por_id` de otra empresa."""
    client = APIClient()
    client.force_authenticate(user=usuarios["agente"])

    base_payload = {
        "empresa_id": empresa_acme.id,
        "creado_por_id": usuarios["cliente_acme"].id,
        "modulo_id": modulos["facturacion"].id,
        "pestana_o_documento": "Facturación",
        "asunto": "Prueba de validación",
        "descripcion": "Descripción",
        "prioridad": "Alta",
        "canal_origen": "WhatsApp",
    }

    # 1. Módulo perteneciente a otra empresa (Global Logistics)
    r_mod_ajeno = client.post(
        SUPPORT_TICKETS_URL,
        {**base_payload, "modulo_id": modulos["ventas_global"].id},
        format="json",
    )
    assert r_mod_ajeno.status_code == 400
    assert "modulo_id" in r_mod_ajeno.data

    # 2. Módulo inactivo de la misma empresa
    r_mod_inactivo = client.post(
        SUPPORT_TICKETS_URL,
        {**base_payload, "modulo_id": modulos["nomina_inactiva"].id},
        format="json",
    )
    assert r_mod_inactivo.status_code == 400
    assert "modulo_id" in r_mod_inactivo.data

    # 3. `creado_por_id` perteneciente a otra empresa
    r_cliente_ajeno = client.post(
        SUPPORT_TICKETS_URL,
        {**base_payload, "creado_por_id": usuarios["cliente_global"].id},
        format="json",
    )
    assert r_cliente_ajeno.status_code == 400
    assert "creado_por_id" in r_cliente_ajeno.data

    assert Ticket.objects.count() == 0
