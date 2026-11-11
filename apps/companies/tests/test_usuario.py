"""Pruebas del modelo Usuario y del login con JWT (tarea BE-03, issue #16).

Cubren los criterios de aceptación de la tarea:
- El modelo personalizado está registrado como AUTH_USER_MODEL.
- El manager permite create_user y create_superuser.
- Los tokens JWT incluyen el rol y el id de la empresa (claims).
Además prueban la regla "un cliente debe tener empresa" y el formato de la
respuesta del login que espera el frontend.

Ejecutar solo estas pruebas:
    pytest apps/companies/tests/test_usuario.py -v
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.companies.models import Empresa, RolChoices, Usuario

# URLs de autenticación definidas en config/urls.py.
LOGIN_URL = "/api/v1/auth/token/"
REFRESH_URL = "/api/v1/auth/token/refresh/"
PASSWORD = "ClaveSegura#2026"


# Los "fixtures" de pytest preparan datos que varias pruebas reutilizan. Una
# prueba los pide escribiendo su nombre como parámetro (por ejemplo `empresa`).
@pytest.fixture
def empresa():
    """Empresa cliente de prueba."""
    return Empresa.objects.create(nombre="Acme Industrial S.A.S.", identificacion="900123456-7")


@pytest.fixture
def cliente(empresa):
    """Usuario con rol cliente que pertenece a la empresa de prueba."""
    return Usuario.objects.create_user(
        correo="carlos@acme.com",
        password=PASSWORD,
        nombre="Carlos Gómez",
        rol=RolChoices.CLIENTE,
        empresa=empresa,
    )


@pytest.fixture
def api_client():
    """Cliente HTTP de Django REST Framework para llamar a los endpoints en las pruebas."""
    return APIClient()


# --------------------------------------------------------------------------
# Modelo y manager
# --------------------------------------------------------------------------


def test_usuario_is_the_auth_user_model():
    """get_user_model() devuelve nuestro Usuario: AUTH_USER_MODEL está bien configurado."""
    assert get_user_model() is Usuario


@pytest.mark.django_db
def test_create_user_hashes_password_and_sets_defaults(cliente):
    """create_user guarda la contraseña cifrada y pone los valores por defecto."""
    assert cliente.pk is not None
    assert cliente.password != PASSWORD  # No se guarda en texto plano.
    assert cliente.check_password(PASSWORD)  # Pero se puede verificar.
    assert cliente.activo is True
    assert cliente.is_active is True  # La propiedad refleja el campo `activo`.
    assert cliente.is_staff is False
    assert cliente.is_superuser is False
    assert cliente.created_at is not None


@pytest.mark.django_db
def test_create_user_normalizes_email_domain(empresa):
    """El dominio del correo se guarda en minúsculas para evitar duplicados."""
    usuario = Usuario.objects.create_user(
        correo="Ana@ACME.COM", password=PASSWORD, nombre="Ana", empresa=empresa
    )

    assert usuario.correo == "Ana@acme.com"


@pytest.mark.django_db
def test_create_user_without_correo_raises_error():
    """No se puede crear un usuario sin correo; el mensaje está en español."""
    with pytest.raises(ValueError, match="El correo es obligatorio"):
        Usuario.objects.create_user(correo="", password=PASSWORD, nombre="Sin correo")


@pytest.mark.django_db
def test_create_superuser_sets_admin_flags_and_internal_role():
    """create_superuser da acceso total al admin y crea personal interno (sin empresa)."""
    admin = Usuario.objects.create_superuser(
        correo="admin@datak.co", password=PASSWORD, nombre="Admin Datak"
    )

    assert admin.is_staff is True
    assert admin.is_superuser is True
    assert admin.rol == RolChoices.AGENTE_SOPORTE
    assert admin.empresa is None


@pytest.mark.django_db
def test_create_superuser_rejects_is_superuser_false():
    """create_superuser no permite crear un superusuario sin is_superuser."""
    with pytest.raises(ValueError, match="is_superuser=True"):
        Usuario.objects.create_superuser(
            correo="admin@datak.co", password=PASSWORD, nombre="Admin", is_superuser=False
        )


@pytest.mark.django_db
def test_correo_must_be_unique_at_database_level(cliente, empresa):
    """PostgreSQL rechaza dos usuarios con el mismo correo (índice único).

    Se usa objects.create() (que no valida en Django) para comprobar que la
    restricción existe en la base de datos y no solo en el código.
    """
    with pytest.raises(IntegrityError):
        Usuario.objects.create(correo="carlos@acme.com", nombre="Otro Carlos", empresa=empresa)


@pytest.mark.django_db
def test_cliente_without_empresa_fails_validation():
    """La validación de Django exige empresa para un cliente, con mensaje en español."""
    with pytest.raises(ValidationError) as exc_info:
        Usuario.objects.create_user(
            correo="sin.empresa@acme.com",
            password=PASSWORD,
            nombre="Sin Empresa",
            rol=RolChoices.CLIENTE,
        )

    assert exc_info.value.message_dict["empresa"] == [
        "Un usuario con rol cliente debe pertenecer a una empresa."
    ]


@pytest.mark.django_db
def test_cliente_without_empresa_is_rejected_by_database():
    """Aunque se salte la validación de Django, la base de datos lo impide (CheckConstraint)."""
    with pytest.raises(IntegrityError):
        Usuario.objects.create(
            correo="sin.empresa@acme.com", nombre="Sin Empresa", rol=RolChoices.CLIENTE
        )


@pytest.mark.django_db
def test_internal_staff_can_exist_without_empresa():
    """Agentes de soporte y responsables de atención no necesitan empresa."""
    agente = Usuario.objects.create_user(
        correo="agente@datak.co",
        password=PASSWORD,
        nombre="Agente Soporte",
        rol=RolChoices.AGENTE_SOPORTE,
    )
    responsable = Usuario.objects.create_user(
        correo="dev@datak.co",
        password=PASSWORD,
        nombre="Dev Datak",
        rol=RolChoices.RESPONSABLE_ATENCION,
    )

    assert agente.empresa is None
    assert responsable.empresa is None


def test_string_representation():
    """__str__ devuelve "nombre <correo>". No usa base de datos."""
    usuario = Usuario(correo="carlos@acme.com", nombre="Carlos Gómez")

    assert str(usuario) == "Carlos Gómez <carlos@acme.com>"


# --------------------------------------------------------------------------
# Login con JWT: POST /api/v1/auth/token/ y /api/v1/auth/token/refresh/
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_login_returns_tokens_and_user_data(api_client, cliente, empresa):
    """Con credenciales correctas el login responde 200, los tokens y los datos del usuario.

    El formato de `user` es el que espera el store de Pinia del frontend.
    """
    response = api_client.post(
        LOGIN_URL, {"correo": "carlos@acme.com", "password": PASSWORD}, format="json"
    )

    assert response.status_code == 200
    assert "access" in response.data
    assert "refresh" in response.data
    assert response.data["user"] == {
        "id": cliente.id,
        "correo": "carlos@acme.com",
        "nombre": "Carlos Gómez",
        "rol": "cliente",
        "empresa": {
            "id": empresa.id,
            "nombre": "Acme Industrial S.A.S.",
            "identificacion": "900123456-7",
        },
    }


@pytest.mark.django_db
def test_access_token_contains_rol_and_empresa_claims(api_client, cliente, empresa):
    """El token de acceso lleva dentro el rol y el id de la empresa (criterio de aceptación)."""
    response = api_client.post(
        LOGIN_URL, {"correo": "carlos@acme.com", "password": PASSWORD}, format="json"
    )
    # AccessToken() decodifica el token y verifica su firma.
    claims = AccessToken(response.data["access"])

    assert claims["user_id"] == str(cliente.id)
    assert claims["rol"] == "cliente"
    assert claims["empresa_id"] == empresa.id


@pytest.mark.django_db
def test_login_of_internal_staff_returns_null_empresa(api_client):
    """Para personal interno, empresa es null en la respuesta y en el token."""
    Usuario.objects.create_user(
        correo="agente@datak.co",
        password=PASSWORD,
        nombre="Agente Soporte",
        rol=RolChoices.AGENTE_SOPORTE,
    )

    response = api_client.post(
        LOGIN_URL, {"correo": "agente@datak.co", "password": PASSWORD}, format="json"
    )

    assert response.status_code == 200
    assert response.data["user"]["empresa"] is None
    assert AccessToken(response.data["access"])["empresa_id"] is None


@pytest.mark.django_db
def test_login_with_wrong_password_returns_401_in_spanish(api_client, cliente):
    """Con contraseña incorrecta responde 401 y un mensaje en español."""
    response = api_client.post(
        LOGIN_URL, {"correo": "carlos@acme.com", "password": "incorrecta"}, format="json"
    )

    assert response.status_code == 401
    assert response.data["detail"] == "Correo o contraseña incorrectos, o la cuenta está inactiva."


@pytest.mark.django_db
def test_inactive_user_cannot_login(api_client, cliente):
    """Un usuario desactivado (activo=False) no puede iniciar sesión."""
    cliente.activo = False
    cliente.save()

    response = api_client.post(
        LOGIN_URL, {"correo": "carlos@acme.com", "password": PASSWORD}, format="json"
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_refresh_returns_new_access_token_with_claims(api_client, cliente, empresa):
    """Renovar el acceso con el token de refresh conserva los claims rol y empresa_id."""
    login = api_client.post(
        LOGIN_URL, {"correo": "carlos@acme.com", "password": PASSWORD}, format="json"
    )

    response = api_client.post(REFRESH_URL, {"refresh": login.data["refresh"]}, format="json")

    assert response.status_code == 200
    claims = AccessToken(response.data["access"])
    assert claims["rol"] == "cliente"
    assert claims["empresa_id"] == empresa.id
