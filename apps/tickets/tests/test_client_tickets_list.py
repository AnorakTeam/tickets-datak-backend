"""Pruebas del endpoint "Mis tickets": GET /api/v1/client/tickets/ (tarea BE-12, issue #25).

Cubren los criterios de aceptación de la tarea:
- El cliente solo ve los tickets de su propia empresa (RNF2).
- Los tickets "Abierto" aparecen antes que los de otros estados.
- El filtro por estado funciona.
Además prueban la paginación, los permisos y que no se expongan datos internos.

Ejecutar solo estas pruebas:
    pytest apps/tickets/tests/test_client_tickets_list.py -v
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.companies.models import Empresa, ModuloContratado, RolChoices, Usuario
from apps.tickets.models import EstadoChoices, Ticket

URL = "/api/v1/client/tickets/"


# --------------------------------------------------------------------------
# Fixtures y utilidades
# --------------------------------------------------------------------------


@pytest.fixture
def empresa():
    return Empresa.objects.create(nombre="Acme Industrial S.A.S.", identificacion="900123456-7")


@pytest.fixture
def otra_empresa():
    return Empresa.objects.create(nombre="Beta Comercial S.A.S.", identificacion="800987654-3")


@pytest.fixture
def cliente(empresa):
    return Usuario.objects.create_user(
        correo="carlos@acme.com", password="Clave#2026", nombre="Carlos Gómez", empresa=empresa
    )


@pytest.fixture
def api_client(cliente):
    """Cliente HTTP ya autenticado como `cliente`.

    force_authenticate evita pedir un token en cada prueba; el login con JWT ya
    está probado en BE-03.
    """
    client = APIClient()
    client.force_authenticate(user=cliente)
    return client


def crear_ticket(empresa, numero, estado=EstadoChoices.ABIERTO, horas_atras=0):
    """Crea un ticket de la empresa dada con el radicado TK-2026-<numero>.

    `horas_atras` permite simular tickets creados en distintos momentos:
    `fecha_creacion` se llena sola al crear (auto_now_add), así que después se
    ajusta con update() para controlar el orden en las pruebas.
    """
    usuario = empresa.usuarios.filter(rol=RolChoices.CLIENTE).first() or (
        Usuario.objects.create_user(
            correo=f"cliente{empresa.pk}@{empresa.identificacion}.com",
            password="Clave#2026",
            nombre="Cliente",
            empresa=empresa,
        )
    )
    modulo, _ = ModuloContratado.objects.get_or_create(
        empresa=empresa, codigo="FACTURACION", defaults={"nombre": "Facturación Electrónica"}
    )
    ticket = Ticket.objects.create(
        radicado=f"TK-2026-{numero:06d}",
        empresa=empresa,
        creado_por=usuario,
        modulo=modulo,
        pestana_o_documento="Facturación > Nueva factura",
        asunto=f"Incidencia {numero}",
        descripcion="Descripción de prueba.",
        estado=estado,
    )
    Ticket.objects.filter(pk=ticket.pk).update(
        fecha_creacion=timezone.now() - timedelta(hours=horas_atras)
    )
    return ticket


def radicados(response):
    """Lista de radicados en el orden en que los devolvió el endpoint."""
    return [fila["radicado"] for fila in response.data["results"]]


# --------------------------------------------------------------------------
# Criterios de aceptación
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_client_only_sees_tickets_of_own_company(api_client, cliente, empresa, otra_empresa):
    """Aislamiento multi-tenant: los tickets de otra empresa nunca aparecen."""
    crear_ticket(empresa, 1)
    crear_ticket(otra_empresa, 2)

    response = api_client.get(URL)

    assert response.status_code == 200
    assert radicados(response) == ["TK-2026-000001"]
    assert response.data["count"] == 1


@pytest.mark.django_db
def test_open_tickets_come_first_then_newest(api_client, cliente, empresa):
    """Primero los "Abierto" (del más nuevo al más viejo), luego los demás estados."""
    crear_ticket(empresa, 1, estado=EstadoChoices.RESUELTO, horas_atras=0)  # el más nuevo
    crear_ticket(empresa, 2, estado=EstadoChoices.ABIERTO, horas_atras=5)
    crear_ticket(empresa, 3, estado=EstadoChoices.EN_GESTION, horas_atras=1)
    crear_ticket(empresa, 4, estado=EstadoChoices.ABIERTO, horas_atras=2)

    response = api_client.get(URL)

    assert radicados(response) == [
        "TK-2026-000004",  # Abierto, hace 2 h
        "TK-2026-000002",  # Abierto, hace 5 h
        "TK-2026-000001",  # Resuelto, ahora
        "TK-2026-000003",  # En gestión, hace 1 h
    ]


@pytest.mark.django_db
def test_filter_by_estado(api_client, cliente, empresa):
    """?estado= devuelve solo los tickets en ese estado."""
    crear_ticket(empresa, 1, estado=EstadoChoices.ABIERTO)
    crear_ticket(empresa, 2, estado=EstadoChoices.RESUELTO)
    crear_ticket(empresa, 3, estado=EstadoChoices.EN_GESTION)

    response = api_client.get(URL, {"estado": "En gestion"})

    assert response.status_code == 200
    assert radicados(response) == ["TK-2026-000003"]


@pytest.mark.django_db
def test_invalid_estado_returns_400_in_spanish(api_client, cliente):
    """Un estado que no existe en el catálogo responde 400 con mensaje en español."""
    response = api_client.get(URL, {"estado": "Cerrado"})

    assert response.status_code == 400
    assert "Estado no válido" in response.data["estado"][0]


# --------------------------------------------------------------------------
# Formato de la respuesta y paginación
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_response_rows_only_expose_client_safe_fields(api_client, cliente, empresa):
    """Cada fila trae exactamente los campos de la sección 5.2; nada interno (RNF2)."""
    crear_ticket(empresa, 1)

    fila = api_client.get(URL).data["results"][0]

    assert set(fila) == {
        "radicado",
        "asunto",
        "modulo_nombre",
        "prioridad",
        "estado",
        "fecha_creacion",
    }
    assert fila["modulo_nombre"] == "Facturación Electrónica"
    assert "responsable" not in fila


@pytest.mark.django_db
def test_pagination_returns_10_per_page_with_total_pages(api_client, cliente, empresa):
    """12 tickets → página 1 con 10, página 2 con 2, y total_pages = 2."""
    for numero in range(1, 13):
        crear_ticket(empresa, numero, horas_atras=numero)

    pagina_1 = api_client.get(URL)
    pagina_2 = api_client.get(URL, {"page": 2})

    assert pagina_1.data["count"] == 12
    assert pagina_1.data["total_pages"] == 2
    assert len(pagina_1.data["results"]) == 10
    assert pagina_1.data["next"] is not None
    assert pagina_1.data["previous"] is None
    assert len(pagina_2.data["results"]) == 2
    assert pagina_2.data["next"] is None


@pytest.mark.django_db
def test_empty_list_when_company_has_no_tickets(api_client, cliente):
    """Sin tickets, la respuesta es 200 con una lista vacía."""
    response = api_client.get(URL)

    assert response.status_code == 200
    assert response.data["count"] == 0
    assert response.data["results"] == []


# --------------------------------------------------------------------------
# Permisos
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_anonymous_request_returns_401():
    """Sin token, el endpoint responde 401 (no autenticado)."""
    response = APIClient().get(URL)

    assert response.status_code == 401


@pytest.mark.django_db
def test_internal_staff_gets_403():
    """Un agente de soporte no puede usar el endpoint del portal del cliente."""
    agente = Usuario.objects.create_user(
        correo="agente@datak.co",
        password="Clave#2026",
        nombre="Agente Soporte",
        rol=RolChoices.AGENTE_SOPORTE,
    )
    client = APIClient()
    client.force_authenticate(user=agente)

    response = client.get(URL)

    assert response.status_code == 403
    assert response.data["detail"] == (
        "Solo los usuarios con rol cliente pueden acceder a este recurso."
    )


@pytest.mark.django_db
def test_works_with_real_jwt_token(cliente, empresa):
    """Prueba de punta a punta: login con JWT y luego "Mis tickets" con ese token."""
    crear_ticket(empresa, 1)
    client = APIClient()
    login = client.post(
        "/api/v1/auth/token/",
        {"correo": "carlos@acme.com", "password": "Clave#2026"},
        format="json",
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    response = client.get(URL)

    assert response.status_code == 200
    assert radicados(response) == ["TK-2026-000001"]
