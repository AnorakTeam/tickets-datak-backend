"""Pruebas unitarias de `RadicadoSequenceService` y `TicketCreationService` (tarea BE-08, issue #21).

Cubren los criterios de aceptación de la tarea:
- Generación secuencial en el mismo año (`TK-2026-000001`, `TK-2026-000002`, etc.).
- Reinicio de la secuencia en `000001` al cambiar de año (`TK-2027-000001`).
- Creación transaccional exitosa de `Ticket` en estado `Abierto` y creación
  automática del primer `TicketItem` con `tipo_accion='CREACION'`.
- Rollback atómico y excepción de validación cuando `empresa_id` no corresponde
  al usuario o cuando el módulo está inactivo / no contratado por la empresa,
  garantizando que no se quemen radicados ni queden registros huérfanos.

Ejecutar solo estas pruebas:
    pytest apps/tickets/tests/test_radicado_service.py -v
"""

import pytest
from django.core.exceptions import ValidationError

from apps.companies.models import Empresa, ModuloContratado, RolChoices, Usuario
from apps.tickets.models import (
    CanalOrigenChoices,
    EstadoChoices,
    PrioridadChoices,
    Ticket,
    TicketItem,
    TipoAccionChoices,
)
from apps.tickets.services import RadicadoSequenceService, TicketCreationService


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


@pytest.fixture
def modulo_inactivo(empresa_acme):
    return ModuloContratado.objects.create(
        empresa=empresa_acme,
        codigo="NOMINA",
        nombre="Nómina Electrónica",
        activo=False,
    )


@pytest.fixture
def modulo_otra_empresa(empresa_global):
    return ModuloContratado.objects.create(
        empresa=empresa_global,
        codigo="VENTAS",
        nombre="Gestión de Ventas",
        activo=True,
    )


# --------------------------------------------------------------------------
# 1. Generación secuencial y reinicio anual (RadicadoSequenceService)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_sequential_radicado_generation_in_same_year(
    empresa_acme, cliente_acme, modulo_facturacion
):
    """Genera radicados consecutivos en el mismo año: TK-2026-000001, TK-2026-000002, TK-2026-000003."""
    t1 = TicketCreationService.create_ticket(
        creado_por=cliente_acme,
        empresa_id=empresa_acme.id,
        modulo_id=modulo_facturacion.id,
        pestana_o_documento="Facturación > Emisión",
        asunto="Incidencia 1",
        descripcion="Descripción 1",
        year=2026,
    )
    t2 = TicketCreationService.create_ticket(
        creado_por=cliente_acme,
        empresa_id=empresa_acme.id,
        modulo_id=modulo_facturacion.id,
        pestana_o_documento="Facturación > Emisión",
        asunto="Incidencia 2",
        descripcion="Descripción 2",
        year=2026,
    )
    t3 = TicketCreationService.create_ticket(
        creado_por=cliente_acme,
        empresa_id=empresa_acme.id,
        modulo_id=modulo_facturacion.id,
        pestana_o_documento="Facturación > Emisión",
        asunto="Incidencia 3",
        descripcion="Descripción 3",
        year=2026,
    )

    assert t1.radicado == "TK-2026-000001"
    assert t2.radicado == "TK-2026-000002"
    assert t3.radicado == "TK-2026-000003"


@pytest.mark.django_db
def test_radicado_sequence_resets_when_year_changes(empresa_acme, cliente_acme, modulo_facturacion):
    """Cuando cambia el año (p. ej. de 2026 a 2027), el contador vuelve a empezar en 000001."""
    t_2026_1 = TicketCreationService.create_ticket(
        creado_por=cliente_acme,
        empresa=empresa_acme,
        modulo=modulo_facturacion,
        pestana_o_documento="Facturación",
        asunto="Ticket 2026 #1",
        descripcion="Detalle",
        year=2026,
    )
    t_2026_2 = TicketCreationService.create_ticket(
        creado_por=cliente_acme,
        empresa=empresa_acme,
        modulo=modulo_facturacion,
        pestana_o_documento="Facturación",
        asunto="Ticket 2026 #2",
        descripcion="Detalle",
        year=2026,
    )
    t_2027_1 = TicketCreationService.create_ticket(
        creado_por=cliente_acme,
        empresa=empresa_acme,
        modulo=modulo_facturacion,
        pestana_o_documento="Facturación",
        asunto="Ticket 2027 #1",
        descripcion="Detalle del nuevo año",
        year=2027,
    )

    assert t_2026_1.radicado == "TK-2026-000001"
    assert t_2026_2.radicado == "TK-2026-000002"
    assert t_2027_1.radicado == "TK-2027-000001"
    assert RadicadoSequenceService.generate_next_radicado(year=2027) == "TK-2027-000002"


# --------------------------------------------------------------------------
# 2. Creación exitosa de Ticket y trazabilidad inicial TicketItem
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_ticket_sets_abierto_status_and_creates_initial_ticket_item(
    empresa_acme, cliente_acme, modulo_facturacion
):
    """Crea el Ticket en estado 'Abierto' e inserta automáticamente el TicketItem de 'CREACION'."""
    ticket = TicketCreationService.create_ticket(
        creado_por=cliente_acme,
        empresa_id=empresa_acme.id,
        modulo_id=modulo_facturacion.id,
        pestana_o_documento="Emisión de Facturas / F-203",
        asunto="Error 500 al emitir factura",
        descripcion="Al confirmar la factura el sistema no completa el proceso.",
        mensaje_error="Server Error: RetencionCalculatorException",
        prioridad=PrioridadChoices.ALTA,
        canal_origen=CanalOrigenChoices.PORTAL,
        year=2026,
    )

    assert ticket.pk is not None
    assert ticket.radicado == "TK-2026-000001"
    assert ticket.estado == EstadoChoices.ABIERTO
    assert ticket.prioridad == PrioridadChoices.ALTA
    assert ticket.canal_origen == CanalOrigenChoices.PORTAL
    assert ticket.empresa == empresa_acme
    assert ticket.creado_por == cliente_acme
    assert ticket.modulo == modulo_facturacion

    historial = list(ticket.historial.all())
    assert len(historial) == 1
    item = historial[0]
    assert item.tipo_accion == TipoAccionChoices.CREACION
    assert item.actor == cliente_acme
    assert item.estado_anterior == ""
    assert item.estado_nuevo == EstadoChoices.ABIERTO
    assert item.es_interna is False
    assert item.observaciones == "Ticket creado desde el portal."


# --------------------------------------------------------------------------
# 3. Rollback atómico y validaciones multi-tenant / módulo (sin quemar radicados)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_mismatched_empresa_id_raises_error_and_rolls_back_without_burning_radicado(
    empresa_acme, empresa_global, cliente_acme, modulo_facturacion
):
    """Si `empresa_id` no corresponde al usuario, falla con ValidationError y no quema radicado."""
    with pytest.raises(ValidationError) as exc_info:
        TicketCreationService.create_ticket(
            creado_por=cliente_acme,
            empresa_id=empresa_global.id,
            modulo_id=modulo_facturacion.id,
            pestana_o_documento="Facturación",
            asunto="Intento cruzado",
            descripcion="No debe crearse.",
            year=2026,
        )

    assert "empresa" in exc_info.value.message_dict
    assert Ticket.objects.count() == 0
    assert TicketItem.objects.count() == 0

    # El siguiente ticket válido sigue recibiendo el primer radicado TK-2026-000001.
    ticket_valido = TicketCreationService.create_ticket(
        creado_por=cliente_acme,
        empresa_id=empresa_acme.id,
        modulo_id=modulo_facturacion.id,
        pestana_o_documento="Facturación",
        asunto="Ticket válido tras fallo",
        descripcion="Sí debe crearse con el primer consecutivo.",
        year=2026,
    )
    assert ticket_valido.radicado == "TK-2026-000001"


@pytest.mark.django_db
def test_inactive_or_foreign_module_raises_error_and_does_not_burn_radicado(
    empresa_acme,
    cliente_acme,
    modulo_facturacion,
    modulo_inactivo,
    modulo_otra_empresa,
):
    """Un módulo inactivo, de otra empresa o inexistente lanza ValidationError y no deja huérfanos."""
    # Caso 1: módulo inactivo de la misma empresa
    with pytest.raises(ValidationError) as exc_inactivo:
        TicketCreationService.create_ticket(
            creado_por=cliente_acme,
            empresa_id=empresa_acme.id,
            modulo_id=modulo_inactivo.id,
            pestana_o_documento="Nómina",
            asunto="Módulo inactivo",
            descripcion="No debe permitirse.",
            year=2026,
        )
    assert "modulo_id" in exc_inactivo.value.message_dict

    # Caso 2: módulo activo pero perteneciente a otra empresa
    with pytest.raises(ValidationError) as exc_ajeno:
        TicketCreationService.create_ticket(
            creado_por=cliente_acme,
            empresa_id=empresa_acme.id,
            modulo_id=modulo_otra_empresa.id,
            pestana_o_documento="Ventas",
            asunto="Módulo ajeno",
            descripcion="No debe permitirse.",
            year=2026,
        )
    assert "modulo_id" in exc_ajeno.value.message_dict

    # Caso 3: módulo inexistente
    with pytest.raises(ValidationError) as exc_inexistente:
        TicketCreationService.create_ticket(
            creado_por=cliente_acme,
            empresa_id=empresa_acme.id,
            modulo_id=999999,
            pestana_o_documento="Inexistente",
            asunto="Módulo inexistente",
            descripcion="No debe permitirse.",
            year=2026,
        )
    assert "modulo_id" in exc_inexistente.value.message_dict

    assert Ticket.objects.count() == 0
    assert TicketItem.objects.count() == 0

    # Ningún intento fallido quemó radicados: el primer ticket válido recibe TK-2026-000001.
    ticket = TicketCreationService.create_ticket(
        creado_por=cliente_acme,
        empresa_id=empresa_acme.id,
        modulo_id=modulo_facturacion.id,
        pestana_o_documento="Facturación",
        asunto="Ticket válido",
        descripcion="Se crea con el primer radicado.",
        year=2026,
    )
    assert ticket.radicado == "TK-2026-000001"
