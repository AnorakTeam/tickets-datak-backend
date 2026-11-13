"""Pruebas unitarias del modelo ModuloContratado (tarea BE-04, issue #17).

Cubren los criterios de aceptación de la tarea:
- Creación de módulos contratados asociados a una empresa y valores por defecto.
- Relación inversa `empresa.modulos_contratados` y borrado en cascada (`CASCADE`).
- Restricción de unicidad por empresa (`unique_together = ('empresa', 'codigo')`):
  una misma empresa no puede repetir `codigo`, pero dos empresas distintas sí
  pueden contratar el mismo `codigo`.
- Representación en texto (`__str__`).

Ejecutar solo estas pruebas:
    pytest apps/companies/tests/test_modulo_contratado.py -v
"""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.companies.models import Empresa, ModuloContratado


@pytest.fixture
def empresa_acme():
    """Primera empresa cliente de prueba."""
    return Empresa.objects.create(nombre="Acme Industrial S.A.S.", identificacion="900123456-7")


@pytest.fixture
def empresa_globex():
    """Segunda empresa cliente de prueba para verificar aislamiento de unicidad."""
    return Empresa.objects.create(nombre="Globex Corp S.A.S.", identificacion="900987654-3")


@pytest.mark.django_db
def test_create_modulo_contratado_with_defaults(empresa_acme):
    """Al crear un módulo contratado se guarda con `activo=True` por defecto y queda ligado a su empresa."""
    modulo = ModuloContratado.objects.create(
        empresa=empresa_acme,
        codigo="FACTURACION",
        nombre="Facturación Electrónica",
    )

    assert modulo.pk is not None
    assert modulo.empresa == empresa_acme
    assert modulo.codigo == "FACTURACION"
    assert modulo.nombre == "Facturación Electrónica"
    assert modulo.activo is True
    assert list(empresa_acme.modulos_contratados.all()) == [modulo]


@pytest.mark.django_db
def test_empresa_and_codigo_must_be_unique_together_at_database_level(empresa_acme):
    """La base de datos rechaza dos módulos con el mismo código dentro de la misma empresa."""
    ModuloContratado.objects.create(
        empresa=empresa_acme,
        codigo="INVENTARIO",
        nombre="Control de Inventarios",
    )

    with pytest.raises(IntegrityError):
        ModuloContratado.objects.create(
            empresa=empresa_acme,
            codigo="INVENTARIO",
            nombre="Inventario Duplicado",
        )


@pytest.mark.django_db
def test_empresa_and_codigo_unique_together_validation_on_full_clean(empresa_acme):
    """`full_clean()` lanza ValidationError cuando se repite (empresa, codigo)."""
    ModuloContratado.objects.create(
        empresa=empresa_acme,
        codigo="NOMINA",
        nombre="Nómina Electrónica",
    )
    duplicado = ModuloContratado(
        empresa=empresa_acme,
        codigo="NOMINA",
        nombre="Otra Nómina",
    )

    with pytest.raises(ValidationError):
        duplicado.full_clean()


@pytest.mark.django_db
def test_different_companies_can_contract_same_modulo_codigo(empresa_acme, empresa_globex):
    """Dos empresas distintas pueden tener contratado el mismo código de módulo."""
    modulo_acme = ModuloContratado.objects.create(
        empresa=empresa_acme,
        codigo="FACTURACION",
        nombre="Facturación Electrónica",
    )
    modulo_globex = ModuloContratado.objects.create(
        empresa=empresa_globex,
        codigo="FACTURACION",
        nombre="Facturación Electrónica",
    )

    assert modulo_acme.pk != modulo_globex.pk
    assert empresa_acme.modulos_contratados.count() == 1
    assert empresa_globex.modulos_contratados.count() == 1


@pytest.mark.django_db
def test_same_company_can_contract_multiple_different_modulos(empresa_acme):
    """Una misma empresa puede contratar varios módulos con códigos distintos."""
    ModuloContratado.objects.create(
        empresa=empresa_acme, codigo="INVENTARIO", nombre="Control de Inventarios"
    )
    ModuloContratado.objects.create(
        empresa=empresa_acme, codigo="NOMINA", nombre="Nómina Electrónica"
    )
    ModuloContratado.objects.create(
        empresa=empresa_acme, codigo="CONTABILIDAD", nombre="Contabilidad General"
    )

    codigos = set(empresa_acme.modulos_contratados.values_list("codigo", flat=True))
    assert codigos == {"INVENTARIO", "NOMINA", "CONTABILIDAD"}


@pytest.mark.django_db
def test_deleting_empresa_cascades_to_modulos_contratados(empresa_acme):
    """Si se elimina una empresa, sus módulos contratados se eliminan en cascada."""
    ModuloContratado.objects.create(
        empresa=empresa_acme,
        codigo="VENTAS",
        nombre="Gestión de Ventas",
    )
    assert ModuloContratado.objects.filter(empresa=empresa_acme).count() == 1

    empresa_acme.delete()

    assert ModuloContratado.objects.count() == 0


def test_string_representation():
    """`__str__` devuelve 'nombre (codigo)' sin necesidad de tocar la base de datos."""
    modulo = ModuloContratado(codigo="FACTURACION", nombre="Facturación Electrónica")

    assert str(modulo) == "Facturación Electrónica (FACTURACION)"
