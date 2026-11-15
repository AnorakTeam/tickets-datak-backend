"""Pruebas del modelo Ticket (tarea BE-05, issue #18).

Cubren los criterios de aceptación de la tarea:
- El modelo tiene exactamente los 20 campos acordados (FP8).
- Restricciones de los campos (radicado único y con formato, catálogos) y
  valores por defecto.
Además prueban las reglas de negocio de clean() (módulo y cliente de la misma
empresa) y las protecciones al borrar datos relacionados.

Ejecutar solo estas pruebas:
    pytest apps/tickets/tests/test_ticket_model.py -v
"""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError

from apps.companies.models import Empresa, ModuloContratado, RolChoices, Usuario
from apps.tickets.models import (
    CanalOrigenChoices,
    ClasificacionChoices,
    EstadoChoices,
    PrioridadChoices,
    Ticket,
)

# Los 20 campos acordados en el FP8 y en la sección 3.4 del documento de arquitectura.
CAMPOS_ESPERADOS = [
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
]


# --------------------------------------------------------------------------
# Fixtures: datos de prueba reutilizables
# --------------------------------------------------------------------------


@pytest.fixture
def empresa():
    return Empresa.objects.create(nombre="Acme Industrial S.A.S.", identificacion="900123456-7")


@pytest.fixture
def otra_empresa():
    return Empresa.objects.create(nombre="Beta Comercial S.A.S.", identificacion="800987654-3")


@pytest.fixture
def modulo(empresa):
    return ModuloContratado.objects.create(
        empresa=empresa, codigo="FACTURACION", nombre="Facturación Electrónica"
    )


@pytest.fixture
def cliente(empresa):
    return Usuario.objects.create_user(
        correo="carlos@acme.com", password="Clave#2026", nombre="Carlos Gómez", empresa=empresa
    )


@pytest.fixture
def ticket_data(empresa, cliente, modulo):
    """Datos mínimos obligatorios para crear un ticket válido."""
    return {
        "radicado": "TK-2026-000001",
        "empresa": empresa,
        "creado_por": cliente,
        "modulo": modulo,
        "pestana_o_documento": "Facturación > Nueva factura",
        "asunto": "No carga la factura",
        "descripcion": "Al guardar la factura aparece una pantalla en blanco.",
    }


# --------------------------------------------------------------------------
# Estructura del modelo
# --------------------------------------------------------------------------


def test_ticket_has_exactly_the_20_agreed_fields():
    """El modelo tiene exactamente los 20 campos del FP8, en ese orden.

    concrete_fields son las columnas reales de la tabla (las FK cuentan una vez).
    """
    nombres = [campo.name for campo in Ticket._meta.concrete_fields]

    assert nombres == CAMPOS_ESPERADOS
    assert len(nombres) == 20


def test_choices_store_documented_values():
    """Los valores guardados de los catálogos son los del documento de arquitectura."""
    assert PrioridadChoices.values == ["Baja", "Media", "Alta", "Critica"]
    assert EstadoChoices.values == ["Abierto", "En gestion", "Resuelto", "No procedente"]
    assert ClasificacionChoices.values == ["Error de uso", "Bug", "Solicitud de mejora"]
    assert CanalOrigenChoices.values == ["Portal", "Chatbot", "WhatsApp", "Slack", "Otro"]


def test_composite_index_on_empresa_estado_fecha_exists():
    """Existe el índice compuesto (empresa, estado, fecha_creacion DESC) pedido en el issue."""
    indices = {indice.name: indice.fields for indice in Ticket._meta.indexes}

    assert indices["ticket_emp_estado_fecha_idx"] == ["empresa", "estado", "-fecha_creacion"]


# --------------------------------------------------------------------------
# Creación y valores por defecto
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_ticket_with_defaults(ticket_data):
    """Un ticket nuevo toma los valores por defecto documentados."""
    ticket = Ticket.objects.create(**ticket_data)

    assert ticket.pk is not None
    assert ticket.estado == EstadoChoices.ABIERTO
    assert ticket.prioridad == PrioridadChoices.MEDIA
    assert ticket.canal_origen == CanalOrigenChoices.PORTAL
    assert ticket.clasificacion is None
    assert ticket.mensaje_error == ""
    assert ticket.comentario_solucion == ""
    assert ticket.motivo_no_procedente == ""
    assert ticket.registrado_por_agente is None
    assert ticket.responsable is None
    assert ticket.fecha_resolucion is None
    assert ticket.fecha_creacion is not None
    assert ticket.fecha_actualizacion is not None


@pytest.mark.django_db
def test_valid_ticket_passes_full_clean(ticket_data):
    """Con datos correctos, full_clean() no lanza errores."""
    Ticket(**ticket_data).full_clean()


@pytest.mark.django_db
def test_reverse_relations_are_available(ticket_data, empresa, cliente, modulo):
    """Los related_name permiten navegar desde empresa, usuario y módulo a sus tickets."""
    ticket = Ticket.objects.create(**ticket_data)

    assert list(empresa.tickets.all()) == [ticket]
    assert list(cliente.tickets_creados.all()) == [ticket]
    assert list(modulo.tickets.all()) == [ticket]


@pytest.mark.django_db
def test_default_ordering_is_newest_first(ticket_data):
    """Por defecto los tickets se listan del más reciente al más antiguo."""
    primero = Ticket.objects.create(**ticket_data)
    segundo = Ticket.objects.create(**{**ticket_data, "radicado": "TK-2026-000002"})

    assert list(Ticket.objects.all()) == [segundo, primero]


def test_string_representation():
    """__str__ devuelve "radicado - asunto". No usa base de datos."""
    ticket = Ticket(radicado="TK-2026-000001", asunto="No carga la factura")

    assert str(ticket) == "TK-2026-000001 - No carga la factura"


# --------------------------------------------------------------------------
# Restricciones de los campos
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_radicado_must_be_unique_at_database_level(ticket_data):
    """La base de datos rechaza dos tickets con el mismo radicado."""
    Ticket.objects.create(**ticket_data)

    with pytest.raises(IntegrityError):
        Ticket.objects.create(**ticket_data)


@pytest.mark.django_db
@pytest.mark.parametrize("radicado", ["TK-26-000001", "tk-2026-000001", "TK-2026-1", "ABC"])
def test_radicado_with_invalid_format_fails_validation(ticket_data, radicado):
    """Un radicado que no cumple TK-AAAA-NNNNNN es rechazado con mensaje en español.

    @pytest.mark.parametrize ejecuta esta misma prueba una vez por cada valor.
    """
    ticket = Ticket(**{**ticket_data, "radicado": radicado})

    with pytest.raises(ValidationError) as exc_info:
        ticket.full_clean()

    assert "TK-AAAA-NNNNNN" in exc_info.value.message_dict["radicado"][0]


@pytest.mark.django_db
def test_invalid_choice_value_fails_validation(ticket_data):
    """Un estado o prioridad fuera del catálogo es rechazado."""
    ticket = Ticket(**{**ticket_data, "estado": "Cerrado", "prioridad": "Urgente"})

    with pytest.raises(ValidationError) as exc_info:
        ticket.full_clean()

    assert "estado" in exc_info.value.message_dict
    assert "prioridad" in exc_info.value.message_dict


@pytest.mark.django_db
def test_required_text_fields_cannot_be_blank(ticket_data):
    """Asunto, descripción y pestaña/documento son obligatorios."""
    ticket = Ticket(**{**ticket_data, "asunto": "", "descripcion": "", "pestana_o_documento": ""})

    with pytest.raises(ValidationError) as exc_info:
        ticket.full_clean()

    assert {"asunto", "descripcion", "pestana_o_documento"} <= set(exc_info.value.message_dict)


# --------------------------------------------------------------------------
# Reglas de negocio (clean) y multi-tenant
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_modulo_from_another_empresa_fails_validation(ticket_data, otra_empresa):
    """No se puede usar un módulo que pertenece a otra empresa (RNF2)."""
    modulo_ajeno = ModuloContratado.objects.create(
        empresa=otra_empresa, codigo="NOMINA", nombre="Nómina"
    )
    ticket = Ticket(**{**ticket_data, "modulo": modulo_ajeno})

    with pytest.raises(ValidationError) as exc_info:
        ticket.full_clean()

    assert exc_info.value.message_dict["modulo"] == [
        "El módulo seleccionado no pertenece a la empresa del ticket."
    ]


@pytest.mark.django_db
def test_cliente_from_another_empresa_fails_validation(ticket_data, otra_empresa):
    """Un cliente de otra empresa no puede figurar como quien reporta el ticket."""
    cliente_ajeno = Usuario.objects.create_user(
        correo="ana@beta.com", password="Clave#2026", nombre="Ana", empresa=otra_empresa
    )
    ticket = Ticket(**{**ticket_data, "creado_por": cliente_ajeno})

    with pytest.raises(ValidationError) as exc_info:
        ticket.full_clean()

    assert exc_info.value.message_dict["creado_por"] == [
        "El cliente que reporta debe pertenecer a la empresa del ticket."
    ]


@pytest.mark.django_db
def test_agent_registered_ticket_is_valid(ticket_data):
    """Un agente puede registrar un ticket en nombre del cliente (canal WhatsApp)."""
    agente = Usuario.objects.create_user(
        correo="agente@datak.co",
        password="Clave#2026",
        nombre="Agente Soporte",
        rol=RolChoices.AGENTE_SOPORTE,
    )
    ticket = Ticket(
        **ticket_data,
        registrado_por_agente=agente,
        canal_origen=CanalOrigenChoices.WHATSAPP,
    )

    ticket.full_clean()
    ticket.save()

    assert list(agente.tickets_registrados_agente.all()) == [ticket]


# --------------------------------------------------------------------------
# Protecciones al borrar datos relacionados
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_cannot_delete_empresa_or_modulo_with_tickets(ticket_data, empresa, modulo):
    """PROTECT impide borrar una empresa o un módulo que tenga tickets."""
    Ticket.objects.create(**ticket_data)

    with pytest.raises(ProtectedError):
        modulo.delete()
    with pytest.raises(ProtectedError):
        empresa.delete()


@pytest.mark.django_db
def test_deleting_responsable_keeps_ticket(ticket_data):
    """Si se borra el responsable asignado, el ticket se conserva sin responsable (SET_NULL)."""
    responsable = Usuario.objects.create_user(
        correo="dev@datak.co",
        password="Clave#2026",
        nombre="Dev Datak",
        rol=RolChoices.RESPONSABLE_ATENCION,
    )
    ticket = Ticket.objects.create(**ticket_data, responsable=responsable)

    responsable.delete()
    ticket.refresh_from_db()

    assert ticket.responsable is None
