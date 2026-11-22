"""Pruebas del comando `python manage.py seed_data` (tarea BE-07, issue #20).

Cubren los criterios de aceptación de la tarea:
- Creación de las 2 empresas de prueba ("Acme Industrial S.A.S." y "Global Logistics Ltda.")
  con sus módulos contratados activos.
- Creación de los 4 usuarios de prueba con contraseña hasheada `test123456` y sus
  roles y vínculos de empresa correspondientes.
- Creación de tickets iniciales para ambas empresas con radicados válidos
  (`TK-AAAA-NNNNNN`), aislamiento multi-tenant e historial `TicketItem`.
- Idempotencia al ejecutar `seed_data` múltiples veces sin duplicar registros ni
  violar la inmutabilidad de `TicketItem`.

Ejecutar solo estas pruebas:
    pytest apps/core/tests/test_seed_data.py -v
"""

import re
from io import StringIO

import pytest
from django.core.management import call_command

from apps.companies.models import Empresa, ModuloContratado, RolChoices, Usuario
from apps.tickets.models import Ticket, TicketItem, TicketNotificacion


@pytest.mark.django_db
def test_seed_data_creates_expected_companies_and_active_modules():
    """`seed_data` crea las 2 empresas y sus módulos activos exactos."""
    out = StringIO()
    call_command("seed_data", stdout=out)

    acme = Empresa.objects.get(nombre="Acme Industrial S.A.S.")
    global_log = Empresa.objects.get(nombre="Global Logistics Ltda.")

    assert acme.activa is True
    assert global_log.activa is True

    modulos_acme = set(
        acme.modulos_contratados.filter(activo=True).values_list("nombre", flat=True)
    )
    modulos_global = set(
        global_log.modulos_contratados.filter(activo=True).values_list("nombre", flat=True)
    )

    assert modulos_acme == {"Inventario", "Facturacion", "Nomina"}
    assert modulos_global == {"Ventas", "Tesoreria"}
    assert "Proceso seed_data finalizado exitosamente" in out.getvalue()


@pytest.mark.django_db
def test_seed_data_creates_users_with_hashed_password_and_roles():
    """Los usuarios de prueba tienen `test123456` hasheada y los roles/empresas esperados."""
    call_command("seed_data", stdout=StringIO())

    cliente_acme = Usuario.objects.get(correo="cliente@acme.com")
    cliente_global = Usuario.objects.get(correo="cliente@global.com")
    agente = Usuario.objects.get(correo="agente@datak.co")
    soporte = Usuario.objects.get(correo="soporte@datak.co")
    dev = Usuario.objects.get(correo="dev@datak.co")
    responsable = Usuario.objects.get(correo="responsable@datak.co")

    for usuario in (cliente_acme, cliente_global, agente, soporte, dev, responsable):
        assert usuario.activo is True
        assert usuario.password != "test123456"
        assert usuario.check_password("test123456") is True

    assert cliente_acme.rol == RolChoices.CLIENTE
    assert cliente_acme.empresa.nombre == "Acme Industrial S.A.S."

    assert cliente_global.rol == RolChoices.CLIENTE
    assert cliente_global.empresa.nombre == "Global Logistics Ltda."

    assert agente.rol == RolChoices.AGENTE_SOPORTE
    assert agente.empresa is None

    assert soporte.rol == RolChoices.AGENTE_SOPORTE
    assert soporte.empresa is None

    assert dev.rol == RolChoices.RESPONSABLE_ATENCION
    assert dev.empresa is None
    assert dev.is_staff is True

    assert responsable.rol == RolChoices.RESPONSABLE_ATENCION
    assert responsable.empresa is None
    assert responsable.is_staff is True


@pytest.mark.django_db
def test_seed_data_creates_multi_tenant_tickets_and_audit_items():
    """Se crean tickets iniciales para ambas empresas con radicados válidos e historial."""
    call_command("seed_data", stdout=StringIO())

    acme = Empresa.objects.get(nombre="Acme Industrial S.A.S.")
    global_log = Empresa.objects.get(nombre="Global Logistics Ltda.")

    assert Ticket.objects.filter(empresa=acme).exists()
    assert Ticket.objects.filter(empresa=global_log).exists()

    patron_radicado = re.compile(r"^TK-\d{4}-\d{6}$")
    for ticket in Ticket.objects.select_related("empresa", "creado_por", "modulo"):
        assert patron_radicado.match(ticket.radicado)
        assert ticket.modulo.empresa_id == ticket.empresa_id
        assert ticket.creado_por.empresa_id == ticket.empresa_id
        assert ticket.historial.exists()


@pytest.mark.django_db
def test_seed_data_creates_notifications_for_resolved_and_dismissed_tickets():
    """`seed_data` crea notificaciones para tickets resueltos y desestimados (BE-27, RF16)."""
    call_command("seed_data", stdout=StringIO())

    cliente_acme = Usuario.objects.get(correo="cliente@acme.com")
    cliente_global = Usuario.objects.get(correo="cliente@global.com")

    notif_acme = TicketNotificacion.objects.filter(destinatario=cliente_acme).first()
    assert notif_acme is not None
    assert notif_acme.ticket.radicado == "TK-2026-000003"
    assert "Resuelto" in notif_acme.titulo
    assert notif_acme.leida is False

    notif_global = TicketNotificacion.objects.filter(destinatario=cliente_global).first()
    assert notif_global is not None
    assert notif_global.ticket.radicado == "TK-2026-000006"
    assert "Desestimado" in notif_global.titulo
    assert notif_global.leida is False


@pytest.mark.django_db
def test_seed_data_is_idempotent_on_repeated_runs():
    """Ejecutar `seed_data` dos veces seguidas no duplica registros ni falla por inmutabilidad."""
    call_command("seed_data", stdout=StringIO())

    conteo_inicial = (
        Empresa.objects.count(),
        ModuloContratado.objects.count(),
        Usuario.objects.count(),
        Ticket.objects.count(),
        TicketItem.objects.count(),
        TicketNotificacion.objects.count(),
    )

    # Segunda ejecución: debe actualizar/conservar sin duplicar ni modificar TicketItem existentes.
    call_command("seed_data", stdout=StringIO())

    conteo_final = (
        Empresa.objects.count(),
        ModuloContratado.objects.count(),
        Usuario.objects.count(),
        Ticket.objects.count(),
        TicketItem.objects.count(),
        TicketNotificacion.objects.count(),
    )

    assert conteo_final == conteo_inicial
