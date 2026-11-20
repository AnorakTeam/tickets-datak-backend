"""Pruebas de la bandeja unificada de soporte y catálogo de empresas (tarea BE-19, RF7).

Endpoints probados:
- `GET /api/v1/support/tickets/`
- `GET /api/v1/support/empresas/`

Cubren los criterios de aceptación de la tarea:
- Permisos por rol (`IsInternalSupportUser`): `agente_soporte` y `responsable_atencion`
  reciben `200 OK`; `cliente` recibe `403 Forbidden`; anónimo recibe `401 Unauthorized`.
- Bandeja unificada multi-tenant: devuelve tickets de múltiples empresas simultáneamente.
- Filtros individuales y combinados: `empresa`, `estado`, `prioridad`,
  `canal_origen`, `responsable` y `search` (coincidencia parcial insensible a
  mayúsculas por `radicado` y por `asunto`).
- Ordenamiento y paginación: primero tickets `'Abierto'` y luego los demás estados
  ordenados por `-fecha_creacion`, con límite de `20` resultados por página.
- Catálogo `/api/v1/support/empresas/`: retorna únicamente empresas activas
  (`activa=True`) junto con sus módulos contratados activos (`activo=True`).

Ejecutar solo estas pruebas:
    pytest apps/tickets/tests/test_support_inbox.py -v
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.companies.models import Empresa, ModuloContratado, RolChoices, Usuario
from apps.tickets.models import (
    CanalOrigenChoices,
    EstadoChoices,
    PrioridadChoices,
    Ticket,
)

INBOX_URL = "/api/v1/support/tickets/"
EMPRESAS_URL = "/api/v1/support/empresas/"
PASSWORD = "test123456"


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
def empresa_inactiva():
    return Empresa.objects.create(
        nombre="Inactiva Corp S.A.S.",
        identificacion="700111222-9",
        activa=False,
    )


@pytest.fixture
def modulos(empresa_acme, empresa_global, empresa_inactiva):
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
    ventas = ModuloContratado.objects.create(
        empresa=empresa_global,
        codigo="VENTAS",
        nombre="Gestión de Ventas",
        activo=True,
    )
    mod_emp_inactiva = ModuloContratado.objects.create(
        empresa=empresa_inactiva,
        codigo="INVENTARIO",
        nombre="Inventario",
        activo=True,
    )
    return {
        "facturacion": facturacion,
        "nomina_inactiva": nomina_inactiva,
        "ventas": ventas,
        "mod_emp_inactiva": mod_emp_inactiva,
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
    responsable_1 = Usuario.objects.create_user(
        correo="dev@datak.co",
        password=PASSWORD,
        nombre="Camila Dev",
        rol=RolChoices.RESPONSABLE_ATENCION,
    )
    responsable_2 = Usuario.objects.create_user(
        correo="dev2@datak.co",
        password=PASSWORD,
        nombre="Diego Dev",
        rol=RolChoices.RESPONSABLE_ATENCION,
    )
    return {
        "cliente_acme": cliente_acme,
        "cliente_global": cliente_global,
        "agente": agente,
        "responsable_1": responsable_1,
        "responsable_2": responsable_2,
    }


@pytest.fixture
def tickets_sample(empresa_acme, empresa_global, modulos, usuarios):
    """Crea 4 tickets variados entre Acme y Global con distintas fechas, estados, prioridades y canales."""
    ahora = timezone.now()

    t1 = Ticket.objects.create(
        radicado="TK-2026-000001",
        empresa=empresa_acme,
        creado_por=usuarios["cliente_acme"],
        modulo=modulos["facturacion"],
        pestana_o_documento="Facturación > F-203",
        asunto="Error 500 al emitir factura electrónica",
        descripcion="Falla la emisión.",
        prioridad=PrioridadChoices.ALTA,
        estado=EstadoChoices.ABIERTO,
        canal_origen=CanalOrigenChoices.PORTAL,
        responsable=None,
    )
    Ticket.objects.filter(pk=t1.pk).update(fecha_creacion=ahora - timedelta(hours=5))

    t2 = Ticket.objects.create(
        radicado="TK-2026-000002",
        empresa=empresa_acme,
        creado_por=usuarios["cliente_acme"],
        modulo=modulos["facturacion"],
        pestana_o_documento="Facturación > Notas crédito",
        asunto="Rechazo de DIAN en nota crédito",
        descripcion="Error de validación XML.",
        prioridad=PrioridadChoices.MEDIA,
        estado=EstadoChoices.EN_GESTION,
        canal_origen=CanalOrigenChoices.CHATBOT,
        responsable=usuarios["responsable_1"],
    )
    Ticket.objects.filter(pk=t2.pk).update(fecha_creacion=ahora - timedelta(hours=1))

    t3 = Ticket.objects.create(
        radicado="TK-2026-000003",
        empresa=empresa_global,
        creado_por=usuarios["cliente_global"],
        modulo=modulos["ventas"],
        pestana_o_documento="Pedidos > Cupo de crédito",
        asunto="Bloqueo de pedido urgente en despachos",
        descripcion="No deja aprobar el pedido.",
        prioridad=PrioridadChoices.CRITICA,
        estado=EstadoChoices.ABIERTO,
        canal_origen=CanalOrigenChoices.WHATSAPP,
        responsable=usuarios["responsable_2"],
    )
    Ticket.objects.filter(pk=t3.pk).update(fecha_creacion=ahora - timedelta(hours=2))

    t4 = Ticket.objects.create(
        radicado="TK-2026-000004",
        empresa=empresa_global,
        creado_por=usuarios["cliente_global"],
        modulo=modulos["ventas"],
        pestana_o_documento="Cotizaciones",
        asunto="Ajuste de plantilla PDF de cotización",
        descripcion="Logo corrido.",
        prioridad=PrioridadChoices.BAJA,
        estado=EstadoChoices.RESUELTO,
        canal_origen=CanalOrigenChoices.SLACK,
        responsable=usuarios["responsable_1"],
    )
    Ticket.objects.filter(pk=t4.pk).update(fecha_creacion=ahora)

    return [t1, t2, t3, t4]


# --------------------------------------------------------------------------
# 1. Permisos por rol (IsInternalSupportUser)
# --------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("url", [INBOX_URL, EMPRESAS_URL])
def test_anonymous_user_receives_401(url):
    """Un usuario no autenticado recibe 401 en ambos endpoints de soporte."""
    response = APIClient().get(url)
    assert response.status_code == 401


@pytest.mark.django_db
@pytest.mark.parametrize("url", [INBOX_URL, EMPRESAS_URL])
def test_client_user_receives_403_forbidden(usuarios, url):
    """Un usuario con rol `cliente` recibe 403 Forbidden en los endpoints de soporte."""
    client = APIClient()
    client.force_authenticate(user=usuarios["cliente_acme"])

    response = client.get(url)
    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("rol_key", ["agente", "responsable_1"])
def test_internal_support_roles_receive_200_ok(usuarios, tickets_sample, rol_key):
    """Tanto `agente_soporte` como `responsable_atencion` reciben 200 OK en ambos endpoints."""
    client = APIClient()
    client.force_authenticate(user=usuarios[rol_key])

    resp_inbox = client.get(INBOX_URL)
    resp_empresas = client.get(EMPRESAS_URL)

    assert resp_inbox.status_code == 200
    assert resp_empresas.status_code == 200


# --------------------------------------------------------------------------
# 2. Bandeja unificada multi-tenant y ordenamiento ('Abierto' primero)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_unified_inbox_returns_all_companies_ordered_open_first_then_newest(
    usuarios, tickets_sample
):
    """Devuelve tickets de múltiples empresas simultáneamente, con 'Abierto' primero y luego -fecha_creacion."""
    client = APIClient()
    client.force_authenticate(user=usuarios["agente"])

    response = client.get(INBOX_URL)

    assert response.status_code == 200
    assert response.data["count"] == 4

    radicados = [item["radicado"] for item in response.data["results"]]
    # Abiertos primero (TK-2026-000003 hace 2h, luego TK-2026-000001 hace 5h),
    # seguidos de los demás estados por fecha más reciente (TK-2026-000004 ahora, TK-2026-000002 hace 1h).
    assert radicados == [
        "TK-2026-000003",
        "TK-2026-000001",
        "TK-2026-000004",
        "TK-2026-000002",
    ]

    primer_item = response.data["results"][0]
    assert {
        "id",
        "radicado",
        "asunto",
        "estado",
        "prioridad",
        "canal_origen",
        "fecha_creacion",
        "empresa",
        "modulo",
        "responsable",
    } <= set(primer_item.keys())
    assert primer_item["empresa"]["nombre"] == "Global Logistics Ltda."
    assert primer_item["modulo"]["codigo"] == "VENTAS"
    assert primer_item["responsable"]["correo"] == "dev2@datak.co"


# --------------------------------------------------------------------------
# 3. Filtros individuales y combinados
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_inbox_filters_individually_and_combined(
    empresa_acme, empresa_global, usuarios, tickets_sample
):
    """Verifica el funcionamiento de `empresa`, `estado`, `prioridad`, `canal_origen`, `responsable` y `search`."""
    client = APIClient()
    client.force_authenticate(user=usuarios["agente"])

    # Filtro por empresa
    r_emp = client.get(INBOX_URL, {"empresa": empresa_acme.id})
    assert {t["radicado"] for t in r_emp.data["results"]} == {
        "TK-2026-000001",
        "TK-2026-000002",
    }

    # Filtro por estado
    r_est = client.get(INBOX_URL, {"estado": EstadoChoices.EN_GESTION})
    assert [t["radicado"] for t in r_est.data["results"]] == ["TK-2026-000002"]

    # Filtro por prioridad
    r_prio = client.get(INBOX_URL, {"prioridad": PrioridadChoices.CRITICA})
    assert [t["radicado"] for t in r_prio.data["results"]] == ["TK-2026-000003"]

    # Filtro por canal_origen
    r_canal = client.get(INBOX_URL, {"canal_origen": CanalOrigenChoices.SLACK})
    assert [t["radicado"] for t in r_canal.data["results"]] == ["TK-2026-000004"]

    # Filtro por responsable
    r_resp = client.get(INBOX_URL, {"responsable": usuarios["responsable_1"].id})
    assert {t["radicado"] for t in r_resp.data["results"]} == {
        "TK-2026-000002",
        "TK-2026-000004",
    }

    # Filtro search por radicado (insensible a mayúsculas y parcial)
    r_search_rad = client.get(INBOX_URL, {"search": "tk-2026-000003"})
    assert [t["radicado"] for t in r_search_rad.data["results"]] == ["TK-2026-000003"]

    # Filtro search por asunto (insensible a mayúsculas y parcial)
    r_search_asunto = client.get(INBOX_URL, {"search": "RECHAZO DE DIAN"})
    assert [t["radicado"] for t in r_search_asunto.data["results"]] == ["TK-2026-000002"]

    # Filtros combinados: empresa_global + estado Abierto + prioridad Critica
    r_comb = client.get(
        INBOX_URL,
        {
            "empresa": empresa_global.id,
            "estado": EstadoChoices.ABIERTO,
            "prioridad": PrioridadChoices.CRITICA,
            "search": "urgente",
        },
    )
    assert [t["radicado"] for t in r_comb.data["results"]] == ["TK-2026-000003"]


# --------------------------------------------------------------------------
# 4. Paginación explícita a 20 resultados por página
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_inbox_pagination_limits_to_20_per_page(empresa_acme, modulos, usuarios):
    """Con 25 tickets, la primera página devuelve exactamente 20 y la segunda 5."""
    for i in range(1, 26):
        Ticket.objects.create(
            radicado=f"TK-2026-{i:06d}",
            empresa=empresa_acme,
            creado_por=usuarios["cliente_acme"],
            modulo=modulos["facturacion"],
            pestana_o_documento="Facturación",
            asunto=f"Ticket masivo {i}",
            descripcion="Prueba de paginación a 20 elementos.",
            estado=EstadoChoices.ABIERTO,
        )

    client = APIClient()
    client.force_authenticate(user=usuarios["agente"])

    page_1 = client.get(INBOX_URL)
    page_2 = client.get(INBOX_URL, {"page": 2})

    assert page_1.status_code == 200
    assert page_1.data["count"] == 25
    assert page_1.data["total_pages"] == 2
    assert len(page_1.data["results"]) == 20
    assert page_1.data["next"] is not None

    assert page_2.status_code == 200
    assert len(page_2.data["results"]) == 5
    assert page_2.data["next"] is None


# --------------------------------------------------------------------------
# 5. Catálogo /api/v1/support/empresas/
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_support_empresas_catalog_returns_only_active_companies_and_active_modules(
    empresa_acme, empresa_global, empresa_inactiva, modulos, usuarios
):
    """Retorna únicamente empresas con `activa=True` y dentro de cada una solo módulos con `activo=True`."""
    client = APIClient()
    client.force_authenticate(user=usuarios["agente"])

    response = client.get(EMPRESAS_URL)

    assert response.status_code == 200
    assert isinstance(response.data, list)

    nombres_empresas = [emp["nombre"] for emp in response.data]
    assert nombres_empresas == ["Acme Industrial S.A.S.", "Global Logistics Ltda."]
    assert "Inactiva Corp S.A.S." not in nombres_empresas

    acme_data = response.data[0]
    assert acme_data["id"] == empresa_acme.id
    codigos_acme = [m["codigo"] for m in acme_data["modulos_contratados"]]
    assert codigos_acme == ["FACTURACION"]
    assert "NOMINA" not in codigos_acme
    for m in acme_data["modulos_contratados"]:
        assert set(m.keys()) == {"id", "codigo", "nombre"}
