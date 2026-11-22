"""Automated test suite for Engineer Queue, Internal Notes, and Ticket Resolution.

Task BE-24 (RF13, RF14, RF15, issue #56, MS Project activity MP-63, User Story #50).

Endpoints covered:
- GET  /api/v1/support/mis-tickets/
- POST /api/v1/support/tickets/{id}/notas-internas/
- POST /api/v1/support/tickets/{id}/resolver/
"""

import pytest
from django.core import mail
from rest_framework import status
from rest_framework.test import APIClient

from apps.companies.models import Empresa, ModuloContratado, RolChoices, Usuario
from apps.tickets.models import (
    CanalOrigenChoices,
    EstadoChoices,
    PrioridadChoices,
    Ticket,
    TicketItem,
    TicketNotificacion,
    TipoAccionChoices,
)


@pytest.fixture
def empresa(db):
    return Empresa.objects.create(
        nombre="Acme Corp",
        identificacion="NIT-900111222-3",
        activa=True,
    )


@pytest.fixture
def modulo(empresa):
    return ModuloContratado.objects.create(
        empresa=empresa,
        nombre="Contabilidad",
        codigo="CONT",
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
def dev1(db):
    return Usuario.objects.create_user(
        correo="dev1@datak.co",
        password="ClaveSegura#2026",
        nombre="David Dev Uno",
        rol=RolChoices.RESPONSABLE_ATENCION,
        activo=True,
    )


@pytest.fixture
def dev2(db):
    return Usuario.objects.create_user(
        correo="dev2@datak.co",
        password="ClaveSegura#2026",
        nombre="Diana Dev Dos",
        rol=RolChoices.RESPONSABLE_ATENCION,
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
def ticket_dev1(empresa, modulo, cliente, dev1):
    return Ticket.objects.create(
        radicado="TK-2026-000201",
        empresa=empresa,
        creado_por=cliente,
        responsable=dev1,
        modulo=modulo,
        pestana_o_documento="Libro Diario",
        asunto="Error de cuadre en balance",
        descripcion="Diferencia de 100 pesos en cuadre contable.",
        prioridad=PrioridadChoices.MEDIA,
        estado=EstadoChoices.EN_GESTION,
        canal_origen=CanalOrigenChoices.PORTAL,
    )


@pytest.fixture
def ticket_dev2(empresa, modulo, cliente, dev2):
    return Ticket.objects.create(
        radicado="TK-2026-000202",
        empresa=empresa,
        creado_por=cliente,
        responsable=dev2,
        modulo=modulo,
        pestana_o_documento="Cuentas por Cobrar",
        asunto="Filtro no responde",
        descripcion="Al seleccionar fecha no filtra registros.",
        prioridad=PrioridadChoices.BAJA,
        estado=EstadoChoices.EN_GESTION,
        canal_origen=CanalOrigenChoices.PORTAL,
    )


# ==============================================================================
# 1. GET /api/v1/support/mis-tickets/ (RF13)
# ==============================================================================

@pytest.mark.django_db
def test_mis_tickets_only_returns_tickets_assigned_to_authenticated_user(dev1, dev2, ticket_dev1, ticket_dev2):
    client = APIClient()
    client.force_authenticate(user=dev1)

    response = client.get("/api/v1/support/mis-tickets/")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    results = data.get("results", [])
    radicados = [item["radicado"] for item in results]

    assert ticket_dev1.radicado in radicados
    assert ticket_dev2.radicado not in radicados


@pytest.mark.django_db
def test_mis_tickets_filter_by_estado(dev1, empresa, modulo, cliente):
    t_gestion = Ticket.objects.create(
        radicado="TK-2026-000203",
        empresa=empresa,
        creado_por=cliente,
        responsable=dev1,
        modulo=modulo,
        pestana_o_documento="Doc A",
        asunto="Ticket en gestion",
        descripcion="Desc",
        prioridad=PrioridadChoices.BAJA,
        estado=EstadoChoices.EN_GESTION,
        canal_origen=CanalOrigenChoices.PORTAL,
    )
    t_resuelto = Ticket.objects.create(
        radicado="TK-2026-000204",
        empresa=empresa,
        creado_por=cliente,
        responsable=dev1,
        modulo=modulo,
        pestana_o_documento="Doc B",
        asunto="Ticket resuelto",
        descripcion="Desc",
        prioridad=PrioridadChoices.BAJA,
        estado=EstadoChoices.RESUELTO,
        canal_origen=CanalOrigenChoices.PORTAL,
    )

    client = APIClient()
    client.force_authenticate(user=dev1)

    # Filter: En gestion
    res_gestion = client.get("/api/v1/support/mis-tickets/?estado=En gestion")
    assert res_gestion.status_code == status.HTTP_200_OK
    rads_gestion = [t["radicado"] for t in res_gestion.json()["results"]]
    assert t_gestion.radicado in rads_gestion
    assert t_resuelto.radicado not in rads_gestion

    # Filter: Resuelto
    res_resuelto = client.get("/api/v1/support/mis-tickets/?estado=Resuelto")
    assert res_resuelto.status_code == status.HTTP_200_OK
    rads_resuelto = [t["radicado"] for t in res_resuelto.json()["results"]]
    assert t_resuelto.radicado in rads_resuelto
    assert t_gestion.radicado not in rads_resuelto


@pytest.mark.django_db
def test_mis_tickets_invalid_estado_returns_400(dev1):
    client = APIClient()
    client.force_authenticate(user=dev1)

    response = client.get("/api/v1/support/mis-tickets/?estado=Invalido")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "estado" in response.json()


@pytest.mark.django_db
def test_mis_tickets_permissions(cliente):
    # Anonymous -> 401
    anon_client = APIClient()
    assert anon_client.get("/api/v1/support/mis-tickets/").status_code == status.HTTP_401_UNAUTHORIZED

    # Cliente -> 403
    client_user = APIClient()
    client_user.force_authenticate(user=cliente)
    assert client_user.get("/api/v1/support/mis-tickets/").status_code == status.HTTP_403_FORBIDDEN


# ==============================================================================
# 2. POST /api/v1/support/tickets/{id}/notas-internas/ (RF14)
# ==============================================================================

@pytest.mark.django_db
def test_add_internal_note_success(dev1, ticket_dev1):
    client = APIClient()
    client.force_authenticate(user=dev1)

    url = f"/api/v1/support/tickets/{ticket_dev1.pk}/notas-internas/"
    payload = {"observaciones": "Se revisaron los logs del servicio y se halló bloqueo de base de datos."}
    response = client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_201_CREATED

    item = TicketItem.objects.filter(ticket=ticket_dev1, tipo_accion=TipoAccionChoices.NOTA_INTERNA).first()
    assert item is not None
    assert item.actor == dev1
    assert item.es_interna is True
    assert "Se revisaron los logs" in item.observaciones
    assert item.estado_anterior == EstadoChoices.EN_GESTION
    assert item.estado_nuevo == EstadoChoices.EN_GESTION


@pytest.mark.django_db
def test_add_internal_note_by_radicado_lookup(dev1, ticket_dev1):
    client = APIClient()
    client.force_authenticate(user=dev1)

    url = f"/api/v1/support/tickets/{ticket_dev1.radicado}/notas-internas/"
    payload = {"observaciones": "Nota agregada por radicado."}
    response = client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    assert TicketItem.objects.filter(ticket=ticket_dev1, observaciones="Nota agregada por radicado.").exists()


@pytest.mark.django_db
def test_add_internal_note_empty_text_returns_400(dev1, ticket_dev1):
    client = APIClient()
    client.force_authenticate(user=dev1)

    url = f"/api/v1/support/tickets/{ticket_dev1.pk}/notas-internas/"
    res_empty = client.post(url, {"observaciones": "   "}, format="json")
    assert res_empty.status_code == status.HTTP_400_BAD_REQUEST

    res_missing = client.post(url, {}, format="json")
    assert res_missing.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_cannot_add_internal_note_to_closed_ticket(dev1, ticket_dev1):
    ticket_dev1.estado = EstadoChoices.RESUELTO
    ticket_dev1.save()

    client = APIClient()
    client.force_authenticate(user=dev1)

    url = f"/api/v1/support/tickets/{ticket_dev1.pk}/notas-internas/"
    response = client.post(url, {"observaciones": "Nota en ticket cerrado"}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "detail" in response.json()


@pytest.mark.django_db
def test_internal_note_never_leaks_to_client_portal(dev1, cliente, ticket_dev1):
    # Add internal note as dev
    client_dev = APIClient()
    client_dev.force_authenticate(user=dev1)
    client_dev.post(
        f"/api/v1/support/tickets/{ticket_dev1.pk}/notas-internas/",
        {"observaciones": "NOTA_SECRETA_INTERNA"},
        format="json",
    )

    # Query as client via GET /api/v1/client/tickets/{radicado}/
    client_cli = APIClient()
    client_cli.force_authenticate(user=cliente)
    res_client = client_cli.get(f"/api/v1/client/tickets/{ticket_dev1.radicado}/")

    assert res_client.status_code == status.HTTP_200_OK
    response_text = str(res_client.content)
    assert "NOTA_SECRETA_INTERNA" not in response_text


# ==============================================================================
# 3. POST /api/v1/support/tickets/{id}/resolver/ (RF15)
# ==============================================================================

@pytest.mark.django_db
def test_resolve_ticket_success(dev1, cliente, ticket_dev1):
    mail.outbox.clear()
    client = APIClient()
    client.force_authenticate(user=dev1)

    url = f"/api/v1/support/tickets/{ticket_dev1.pk}/resolver/"
    payload = {"comentario_solucion": "Se liberó el bloqueo de concurrencia y se cuadró el saldo."}
    response = client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_200_OK

    ticket_dev1.refresh_from_db()
    assert ticket_dev1.estado == EstadoChoices.RESUELTO
    assert ticket_dev1.comentario_solucion == payload["comentario_solucion"]
    assert ticket_dev1.fecha_resolucion is not None

    # Check TicketItem audit record
    item = TicketItem.objects.filter(ticket=ticket_dev1, tipo_accion=TipoAccionChoices.RESOLUCION).first()
    assert item is not None
    assert item.actor == dev1
    assert item.es_interna is False
    assert item.estado_nuevo == EstadoChoices.RESUELTO
    assert item.observaciones == payload["comentario_solucion"]

    # Check TicketNotificacion created in DB for client (BE-23, RF16)
    notif = TicketNotificacion.objects.filter(ticket=ticket_dev1).first()
    assert notif is not None
    assert notif.destinatario == cliente
    assert notif.estado_nuevo == EstadoChoices.RESUELTO
    assert "Ticket Resuelto" in notif.titulo
    assert "Se liberó el bloqueo" in notif.mensaje

    # Check notification email dispatched
    assert len(mail.outbox) == 1
    assert cliente.correo in mail.outbox[0].to
    assert "Ticket Resuelto" in mail.outbox[0].subject


@pytest.mark.django_db
def test_resolve_ticket_by_radicado_lookup(dev1, ticket_dev1):
    client = APIClient()
    client.force_authenticate(user=dev1)

    url = f"/api/v1/support/tickets/{ticket_dev1.radicado}/resolver/"
    payload = {"comentario_solucion": "Resuelto buscando por código radicado."}
    response = client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_200_OK
    ticket_dev1.refresh_from_db()
    assert ticket_dev1.estado == EstadoChoices.RESUELTO


@pytest.mark.django_db
def test_resolve_ticket_empty_solution_returns_400(dev1, ticket_dev1):
    client = APIClient()
    client.force_authenticate(user=dev1)

    url = f"/api/v1/support/tickets/{ticket_dev1.pk}/resolver/"
    res_empty = client.post(url, {"comentario_solucion": "   "}, format="json")
    assert res_empty.status_code == status.HTTP_400_BAD_REQUEST

    res_missing = client.post(url, {}, format="json")
    assert res_missing.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_cannot_resolve_already_closed_ticket(dev1, ticket_dev1):
    ticket_dev1.estado = EstadoChoices.RESUELTO
    ticket_dev1.save()

    client = APIClient()
    client.force_authenticate(user=dev1)

    url = f"/api/v1/support/tickets/{ticket_dev1.pk}/resolver/"
    response = client.post(url, {"comentario_solucion": "Intentar resolver otra vez"}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "detail" in response.json()


@pytest.mark.django_db
def test_resolve_ticket_permissions(cliente, ticket_dev1):
    anon_client = APIClient()
    assert anon_client.post(f"/api/v1/support/tickets/{ticket_dev1.pk}/resolver/", {}).status_code == status.HTTP_401_UNAUTHORIZED

    client_user = APIClient()
    client_user.force_authenticate(user=cliente)
    assert client_user.post(f"/api/v1/support/tickets/{ticket_dev1.pk}/resolver/", {"comentario_solucion": "Solucion"}).status_code == status.HTTP_403_FORBIDDEN
