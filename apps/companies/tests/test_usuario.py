"""Unit and integration tests for custom Usuario model and JWT auth (BE-03)."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.companies.models import Empresa, RolChoices, Usuario


@pytest.mark.django_db
class TestUsuarioModel:
    """Test suite for custom Usuario model and manager."""

    def test_custom_user_model_is_registered(self):
        """Verify get_user_model returns Usuario."""
        User = get_user_model()
        assert User == Usuario

    def test_create_user_success(self):
        """Verify normal user creation with email, name, role and company."""
        empresa = Empresa.objects.create(nombre="Test Corp", identificacion="900111222-3")
        user = Usuario.objects.create_user(
            email="cliente@testcorp.com",
            password="StrongPassword123!",
            nombre="Carlos Gomez",
            rol=RolChoices.CLIENTE,
            empresa=empresa,
        )

        assert user.id is not None
        assert user.email == "cliente@testcorp.com"
        assert user.correo == "cliente@testcorp.com"
        assert user.nombre == "Carlos Gomez"
        assert user.rol == RolChoices.CLIENTE
        assert user.empresa == empresa
        assert user.activo is True
        assert user.is_active is True
        assert user.is_staff is False
        assert user.check_password("StrongPassword123!") is True
        assert str(user) == "Carlos Gomez <cliente@testcorp.com> (Cliente)"

    def test_create_user_without_email_raises_error(self):
        """Verify creating a user without email raises ValueError."""
        with pytest.raises(ValueError, match="El correo electrónico es obligatorio."):
            Usuario.objects.create_user(email="", password="somepassword")

    def test_create_superuser_success(self):
        """Verify superuser creation sets is_staff=True, is_superuser=True."""
        admin_user = Usuario.objects.create_superuser(
            email="admin@datak.co",
            password="AdminSecretPassword123!",
            nombre="Admin SuperDatak",
        )

        assert admin_user.is_staff is True
        assert admin_user.is_superuser is True
        assert admin_user.activo is True
        assert admin_user.check_password("AdminSecretPassword123!") is True


@pytest.mark.django_db
class TestJWTAuthentication:
    """Test suite for SimpleJWT authentication and custom claims."""

    @pytest.fixture
    def client(self):
        return APIClient()

    @pytest.fixture
    def client_user(self):
        empresa = Empresa.objects.create(
            nombre="Acme Logistics",
            identificacion="900999888-1",
        )
        return Usuario.objects.create_user(
            email="jorge@acme.com",
            password="SecurePassword2026!",
            nombre="Jorge Martinez",
            rol=RolChoices.CLIENTE,
            empresa=empresa,
        )

    def test_jwt_login_success_and_claims(self, client, client_user):
        """Verify /api/v1/auth/token/ returns tokens and custom payload claims."""
        response = client.post(
            "/api/v1/auth/token/",
            {"email": "jorge@acme.com", "password": "SecurePassword2026!"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert "access" in data
        assert "refresh" in data
        assert "user" in data
        assert data["user"]["email"] == "jorge@acme.com"
        assert data["user"]["nombre"] == "Jorge Martinez"
        assert data["user"]["rol"] == "cliente"
        assert data["user"]["empresa"]["id"] == client_user.empresa.id
        assert data["user"]["empresa"]["nombre"] == "Acme Logistics"

        # Decode token to verify embedded custom claims
        token = AccessToken(data["access"])
        assert token["email"] == "jorge@acme.com"
        assert token["nombre"] == "Jorge Martinez"
        assert token["rol"] == "cliente"
        assert token["empresa_id"] == client_user.empresa.id
        assert token["empresa_nombre"] == "Acme Logistics"

    def test_jwt_login_invalid_credentials(self, client, client_user):
        """Verify login fails with wrong password."""
        response = client.post(
            "/api/v1/auth/token/",
            {"email": "jorge@acme.com", "password": "WrongPassword!"},
            format="json",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_jwt_token_refresh(self, client, client_user):
        """Verify /api/v1/auth/token/refresh/ returns a new access token."""
        login_res = client.post(
            "/api/v1/auth/token/",
            {"email": "jorge@acme.com", "password": "SecurePassword2026!"},
            format="json",
        )
        refresh_token = login_res.data["refresh"]

        refresh_res = client.post(
            "/api/v1/auth/token/refresh/",
            {"refresh": refresh_token},
            format="json",
        )

        assert refresh_res.status_code == status.HTTP_200_OK
        assert "access" in refresh_res.data
