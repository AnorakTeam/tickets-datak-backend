"""Pruebas del historial inmutable TicketItem (tarea BE-06, issue #19).

Cubren los criterios de aceptación de la tarea:
- El modelo existe con sus 10 campos y su migración.
- Actualizar o borrar un TicketItem lanza una excepción (RNF5).
Además prueban que también se bloquean los cambios y borrados masivos, el orden
cronológico del historial y las relaciones con Ticket y Usuario.

Ejecutar solo estas pruebas:
    pytest apps/tickets/tests/test_ticket_item_immutability.py -v
"""

import pytest
from django.core.exceptions import PermissionDenied
from django.db.models import ProtectedError

from apps.companies.models import Empresa, ModuloContratado, RolChoices, Usuario
from apps.tickets.models import EstadoChoices, Ticket, TicketItem, TipoAccionChoices

# Los 10 campos de la sección 3.5 del documento de arquitectura.
CAMPOS_ESPERADOS = [
    "id",
    "ticket",
    "actor",
    "tipo_accion",
    "estado_anterior",
    "estado_nuevo",
    "responsable_asignado",
    "es_interna",
    "observaciones",
    "fecha_creacion",
]


# --------------------------------------------------------------------------
# Fixtures: datos de prueba reutilizables
# --------------------------------------------------------------------------


@pytest.fixture
def cliente():
    empresa = Empresa.objects.create(nombre="Acme Industrial S.A.S.", identificacion="900123456-7")
    return Usuario.objects.create_user(
        correo="carlos@acme.com", password="Clave#2026", nombre="Carlos Gómez", empresa=empresa
    )


@pytest.fixture
def ticket(cliente):
    modulo = ModuloContratado.objects.create(
        empresa=cliente.empresa, codigo="FACTURACION", nombre="Facturación Electrónica"
    )
    return Ticket.objects.create(
        radicado="TK-2026-000001",
        empresa=cliente.empresa,
        creado_por=cliente,
        modulo=modulo,
        pestana_o_documento="Facturación > Nueva factura",
        asunto="No carga la factura",
        descripcion="Al guardar la factura aparece una pantalla en blanco.",
    )


@pytest.fixture
def item(ticket, cliente):
    """Primer evento del historial: la creación del ticket."""
    return TicketItem.objects.create(
        ticket=ticket,
        actor=cliente,
        tipo_accion=TipoAccionChoices.CREACION,
        estado_nuevo=EstadoChoices.ABIERTO,
        observaciones="Ticket creado desde el portal.",
    )


# --------------------------------------------------------------------------
# Estructura y creación
# --------------------------------------------------------------------------


def test_ticket_item_has_exactly_the_10_documented_fields():
    """El modelo tiene exactamente los 10 campos de la sección 3.5, en ese orden."""
    nombres = [campo.name for campo in TicketItem._meta.concrete_fields]

    assert nombres == CAMPOS_ESPERADOS


def test_tipo_accion_choices_match_documentation():
    """Los tipos de acción son los del documento de arquitectura."""
    assert TipoAccionChoices.values == [
        "CREACION",
        "ASIGNACION",
        "CAMBIO_ESTADO",
        "CLASIFICACION",
        "NOTA_INTERNA",
        "RESOLUCION",
        "NO_PROCEDENTE",
    ]


@pytest.mark.django_db
def test_create_item_with_defaults(item, ticket, cliente):
    """Crear un registro funciona y toma los valores por defecto."""
    assert item.pk is not None
    assert item.ticket == ticket
    assert item.actor == cliente
    assert item.estado_anterior == ""
    assert item.es_interna is False
    assert item.responsable_asignado is None
    assert item.fecha_creacion is not None


@pytest.mark.django_db
def test_history_is_available_from_ticket_in_chronological_order(item, ticket, cliente):
    """`ticket.historial` devuelve los eventos del más antiguo al más reciente."""
    nota = TicketItem.objects.create(
        ticket=ticket,
        actor=cliente,
        tipo_accion=TipoAccionChoices.NOTA_INTERNA,
        es_interna=True,
        observaciones="Revisar con el equipo de facturación.",
    )

    assert list(ticket.historial.all()) == [item, nota]


@pytest.mark.django_db
def test_assignment_event_stores_responsable(ticket):
    """Un evento de asignación guarda el responsable y el cambio de estado."""
    agente = Usuario.objects.create_user(
        correo="agente@datak.co",
        password="Clave#2026",
        nombre="Agente Soporte",
        rol=RolChoices.AGENTE_SOPORTE,
    )
    responsable = Usuario.objects.create_user(
        correo="dev@datak.co",
        password="Clave#2026",
        nombre="Dev Datak",
        rol=RolChoices.RESPONSABLE_ATENCION,
    )

    evento = TicketItem.objects.create(
        ticket=ticket,
        actor=agente,
        tipo_accion=TipoAccionChoices.ASIGNACION,
        estado_anterior=EstadoChoices.ABIERTO,
        estado_nuevo=EstadoChoices.EN_GESTION,
        responsable_asignado=responsable,
        es_interna=True,
    )

    assert list(responsable.asignaciones_historial.all()) == [evento]
    assert list(agente.acciones_historial.all()) == [evento]


# --------------------------------------------------------------------------
# Inmutabilidad (criterio de aceptación principal)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_updating_an_existing_item_raises_permission_denied(item):
    """Volver a guardar un registro existente está prohibido y no cambia nada."""
    item.observaciones = "Texto alterado"

    with pytest.raises(PermissionDenied, match="no se pueden modificar"):
        item.save()

    item.refresh_from_db()
    assert item.observaciones == "Ticket creado desde el portal."


@pytest.mark.django_db
def test_deleting_an_item_raises_permission_denied(item):
    """Borrar un registro está prohibido y el registro sigue existiendo."""
    with pytest.raises(PermissionDenied, match="no se pueden eliminar"):
        item.delete()

    assert TicketItem.objects.filter(pk=item.pk).exists()


@pytest.mark.django_db
def test_bulk_update_is_blocked(item):
    """Tampoco se puede modificar en masa con .update() (no pasa por save())."""
    with pytest.raises(PermissionDenied):
        TicketItem.objects.filter(pk=item.pk).update(observaciones="Texto alterado")

    item.refresh_from_db()
    assert item.observaciones == "Ticket creado desde el portal."


@pytest.mark.django_db
def test_bulk_delete_is_blocked(item):
    """Tampoco se puede borrar en masa con .delete() sobre una consulta."""
    with pytest.raises(PermissionDenied):
        TicketItem.objects.all().delete()

    assert TicketItem.objects.count() == 1


# --------------------------------------------------------------------------
# Protecciones de las relaciones
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_actor_with_history_cannot_be_deleted(item, cliente):
    """PROTECT: no se puede borrar un usuario que aparece como actor en el historial."""
    with pytest.raises(ProtectedError):
        cliente.delete()


@pytest.mark.django_db
def test_string_representation(item):
    """__str__ muestra el radicado y el tipo de acción."""
    assert str(item) == "TK-2026-000001 · CREACION"
