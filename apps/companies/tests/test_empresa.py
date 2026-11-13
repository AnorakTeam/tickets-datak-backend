"""Pruebas unitarias del modelo Empresa (tarea BE-02, issue #15).

Cubren los criterios de aceptación de la tarea:
- Se puede crear una empresa y toma sus valores por defecto.
- La identificación (NIT) es única, tanto en la base de datos como en la validación.
- La representación en texto (__str__) es la esperada.

Ejecutar solo estas pruebas:
    pytest apps/companies/tests/test_empresa.py -v
"""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.companies.models import Empresa


# @pytest.mark.django_db le da a la prueba acceso a una base de datos de prueba
# temporal. pytest-django la crea al inicio y deshace los cambios de cada prueba,
# así que una prueba nunca afecta a otra ni a la base de datos real.
@pytest.mark.django_db
def test_create_empresa_with_defaults():
    """Al crear una empresa se guarda y se llenan los valores automáticos."""
    empresa = Empresa.objects.create(nombre="Acme Industrial S.A.S.", identificacion="900123456-7")

    assert empresa.pk is not None  # Se guardó y tiene id asignado.
    assert empresa.activa is True  # Valor por defecto del campo `activa`.
    assert empresa.created_at is not None  # Lo llena auto_now_add.
    assert empresa.updated_at is not None  # Lo llena auto_now.


@pytest.mark.django_db
def test_identificacion_must_be_unique_at_database_level():
    """PostgreSQL rechaza una segunda empresa con el mismo NIT.

    `objects.create()` no ejecuta validaciones de Django, va directo a la base de
    datos; por eso el error que aparece es IntegrityError (lo lanza el índice
    único). Esto prueba que la restricción existe en la base de datos y no solo
    en el código.
    """
    Empresa.objects.create(nombre="Acme Industrial S.A.S.", identificacion="900123456-7")

    with pytest.raises(IntegrityError):
        Empresa.objects.create(nombre="Otra Empresa S.A.S.", identificacion="900123456-7")


@pytest.mark.django_db
def test_identificacion_unique_validation_message_is_in_spanish():
    """La validación de Django muestra el mensaje en español.

    `full_clean()` ejecuta las validaciones del modelo (las mismas que usan los
    formularios y serializers) sin guardar. Como el NIT ya existe, falla con
    ValidationError y el mensaje debe ser el definido en `error_messages`.
    """
    Empresa.objects.create(nombre="Acme Industrial S.A.S.", identificacion="900123456-7")
    duplicate = Empresa(nombre="Otra Empresa S.A.S.", identificacion="900123456-7")

    with pytest.raises(ValidationError) as exc_info:
        duplicate.full_clean()

    # message_dict agrupa los errores por campo: {"identificacion": ["..."]}.
    assert exc_info.value.message_dict["identificacion"] == [
        "Ya existe una empresa registrada con esta identificación."
    ]


@pytest.mark.django_db
def test_updated_at_changes_on_save():
    """Al modificar y guardar una empresa, `updated_at` se actualiza solo."""
    empresa = Empresa.objects.create(nombre="Acme Industrial S.A.S.", identificacion="900123456-7")
    original_updated_at = empresa.updated_at

    empresa.activa = False
    empresa.save()
    # refresh_from_db() vuelve a leer el registro desde la base de datos para
    # comprobar lo que realmente quedó guardado, no lo que hay en memoria.
    empresa.refresh_from_db()

    assert empresa.activa is False
    assert empresa.updated_at > original_updated_at


def test_string_representation():
    """__str__ devuelve "nombre (NIT)".

    No lleva @pytest.mark.django_db porque no guarda nada: solo crea el objeto
    en memoria y lee su texto.
    """
    empresa = Empresa(nombre="Acme Industrial S.A.S.", identificacion="900123456-7")

    assert str(empresa) == "Acme Industrial S.A.S. (900123456-7)"
