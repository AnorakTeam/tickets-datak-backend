"""Unit tests for Empresa (tenant) model (BE-02)."""

import pytest
from django.db import IntegrityError

from apps.companies.models import Empresa


@pytest.mark.django_db
class TestEmpresaModel:
    """Test suite for the Empresa tenant model."""

    def test_create_empresa_success(self):
        """Verify Empresa can be created with required and default fields."""
        empresa = Empresa.objects.create(
            nombre="Acme Corp",
            identificacion="900123456-1",
        )
        assert empresa.id is not None
        assert empresa.nombre == "Acme Corp"
        assert empresa.identificacion == "900123456-1"
        assert empresa.nit == "900123456-1"
        assert empresa.activa is True
        assert empresa.fecha_creacion is not None
        assert empresa.fecha_actualizacion is not None
        assert empresa.created_at == empresa.fecha_creacion

    def test_empresa_string_representation(self):
        """Verify __str__ returns formatted name and identification."""
        empresa = Empresa.objects.create(
            nombre="Datak Technologies",
            identificacion="800987654-2",
        )
        assert str(empresa) == "Datak Technologies (800987654-2)"

    def test_empresa_unique_identificacion(self):
        """Verify duplicate identificacion (NIT) raises IntegrityError."""
        Empresa.objects.create(
            nombre="First Corp",
            identificacion="900000001-1",
        )
        with pytest.raises(IntegrityError):
            Empresa.objects.create(
                nombre="Second Corp",
                identificacion="900000001-1",
            )

    def test_empresa_ordering(self):
        """Verify default ordering is alphabetical by nombre."""
        Empresa.objects.create(nombre="Zeta Logistics", identificacion="900000003-3")
        Empresa.objects.create(nombre="Alpha Solutions", identificacion="900000002-2")

        nombres = list(Empresa.objects.values_list("nombre", flat=True))
        assert nombres == sorted(nombres)
