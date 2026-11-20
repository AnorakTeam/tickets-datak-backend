"""Pruebas del endpoint `GET /api/v1/modulos/` (tarea BE-10, issue #23, RF2).

Cubren los criterios de aceptación y la matriz del contrato de API:
- Devuelve exclusivamente los módulos activos (`activo=True`) contratados por la
  empresa del usuario autenticado (`request.user.empresa`).
- Cada elemento expone exactamente `id`, `codigo` y `nombre` en un arreglo plano.
- Módulos inactivos o de otra empresa nunca se exponen (aislamiento RNF2).
- Si la empresa no tiene módulos activos o el usuario es personal interno sin
  empresa asignada, devuelve `[]` con `200 OK`.
- Ignora cualquier query param `?empresa_id=` enviado por el cliente.
- Solicitudes sin autenticar reciben `401 Unauthorized`.

Ejecutar solo estas pruebas:
    pytest apps/companies/tests/test_modulos_endpoint.py -v
"""

import pytest
from rest_framework.test import APIClient

from apps.companies.models import Empresa, ModuloContratado, RolChoices, Usuario

URL = "/api/v1/modulos/"
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
def modulos_setup(empresa_acme, empresa_global):
    """Crea módulos activos e inactivos en Acme y módulos activos en Global."""
    facturacion = ModuloContratado.objects.create(
        empresa=empresa_acme,
        codigo="FACTURACION",
        nombre="Facturación Electrónica",
        activo=True,
    )
    inventario = ModuloContratado.objects.create(
        empresa=empresa_acme,
        codigo="INVENTARIO",
        nombre="Control de Inventarios",
        activo=True,
    )
    nomina_inactiva = ModuloContratado.objects.create(
        empresa=empresa_acme,
        codigo="NOMINA",
        nombre="Nómina Electrónica",
        activo=False,
    )
    ventas_otra_empresa = ModuloContratado.objects.create(
        empresa=empresa_global,
        codigo="VENTAS",
        nombre="Gestión de Ventas",
        activo=True,
    )
    return {
        "facturacion": facturacion,
        "inventario": inventario,
        "nomina_inactiva": nomina_inactiva,
        "ventas_otra_empresa": ventas_otra_empresa,
    }


@pytest.mark.django_db
def test_returns_only_active_modules_of_authenticated_user_company(cliente_acme, modulos_setup):
    """Devuelve solo los módulos activos de la empresa autenticada con `id`, `codigo` y `nombre`."""
    client = APIClient()
    client.force_authenticate(user=cliente_acme)

    response = client.get(URL)

    assert response.status_code == 200
    assert isinstance(response.data, list)
    assert len(response.data) == 2

    codigos = [item["codigo"] for item in response.data]
    assert set(codigos) == {"FACTURACION", "INVENTARIO"}
    assert "NOMINA" not in codigos
    assert "VENTAS" not in codigos

    for item in response.data:
        assert set(item.keys()) == {"id", "codigo", "nombre"}


@pytest.mark.django_db
def test_company_without_active_modules_returns_empty_list(empresa_acme, cliente_acme):
    """Si la empresa solo tiene módulos inactivos o ninguno, responde 200 con `[]`."""
    ModuloContratado.objects.create(
        empresa=empresa_acme,
        codigo="CONTABILIDAD",
        nombre="Contabilidad",
        activo=False,
    )
    client = APIClient()
    client.force_authenticate(user=cliente_acme)

    response = client.get(URL)

    assert response.status_code == 200
    assert response.data == []


@pytest.mark.django_db
def test_internal_user_without_empresa_gets_empty_list(modulos_setup):
    """Un usuario interno sin empresa asignada recibe `[]` (`ModuloContratado.objects.none()`)."""
    agente = Usuario.objects.create_user(
        correo="agente@datak.co",
        password=PASSWORD,
        nombre="Agente Soporte",
        rol=RolChoices.AGENTE_SOPORTE,
    )
    client = APIClient()
    client.force_authenticate(user=agente)

    response = client.get(URL)

    assert response.status_code == 200
    assert response.data == []


@pytest.mark.django_db
def test_ignores_empresa_id_query_parameter(cliente_acme, empresa_global, modulos_setup):
    """Enviar `?empresa_id=` en la URL nunca permite consultar módulos de otra empresa."""
    client = APIClient()
    client.force_authenticate(user=cliente_acme)

    response = client.get(URL, {"empresa_id": empresa_global.id})

    assert response.status_code == 200
    codigos = {item["codigo"] for item in response.data}
    assert codigos == {"FACTURACION", "INVENTARIO"}
    assert "VENTAS" not in codigos


@pytest.mark.django_db
def test_unauthenticated_request_returns_401():
    """Sin token de autenticación responde 401."""
    response = APIClient().get(URL)

    assert response.status_code == 401


@pytest.mark.django_db
def test_works_with_real_jwt_bearer_token(cliente_acme, modulos_setup):
    """Flujo completo: login en `/api/v1/auth/token/` y consulta con `Bearer <access>`."""
    client = APIClient()
    login = client.post(
        "/api/v1/auth/token/",
        {"correo": "cliente@acme.com", "password": PASSWORD},
        format="json",
    )
    assert login.status_code == 200

    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    response = client.get(URL)

    assert response.status_code == 200
    assert {item["codigo"] for item in response.data} == {"FACTURACION", "INVENTARIO"}
