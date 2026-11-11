"""Models for the companies application (multi-tenant boundary and user accounts)."""

from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models


class Empresa(models.Model):
    """Tenant model representing client companies."""

    id = models.BigAutoField(primary_key=True)
    nombre = models.CharField(max_length=200, help_text="Nombre legal o comercial de la empresa")
    identificacion = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="NIT o número de identificación tributaria único",
    )
    activa = models.BooleanField(
        default=True,
        help_text="Indica si la empresa tiene acceso activo al sistema de soporte",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "empresas"
        verbose_name = "Empresa"
        verbose_name_plural = "Empresas"
        ordering = ["nombre"]

    def __str__(self) -> str:
        return f"{self.nombre} ({self.identificacion})"

    @property
    def nit(self) -> str:
        """Alias for identificacion."""
        return self.identificacion

    @property
    def created_at(self):
        """English alias for fecha_creacion."""
        return self.fecha_creacion

    @property
    def updated_at(self):
        """English alias for fecha_actualizacion."""
        return self.fecha_actualizacion


class RolChoices(models.TextChoices):
    """Available system roles."""

    CLIENTE = "cliente", "Cliente"
    AGENTE_SOPORTE = "agente_soporte", "Agente de Soporte"
    RESPONSABLE_ATENCION = "responsable_atencion", "Responsable de Atención"


class UsuarioManager(BaseUserManager):
    """Custom manager for the Usuario model using email as identifier."""

    def create_user(self, email: str, password: str | None = None, **extra_fields):
        """Create and return a regular user."""
        if not email:
            raise ValueError("El correo electrónico es obligatorio.")

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str | None = None, **extra_fields):
        """Create and return a superuser with full permissions."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("activo", True)
        extra_fields.setdefault("rol", RolChoices.RESPONSABLE_ATENCION)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, password, **extra_fields)


class Usuario(AbstractBaseUser, PermissionsMixin):
    """Custom user model for the ticketing platform."""

    id = models.BigAutoField(primary_key=True)
    email = models.EmailField(
        unique=True,
        db_index=True,
        help_text="Correo electrónico corporativo y nombre de usuario único",
    )
    nombre = models.CharField(max_length=150, help_text="Nombre completo del usuario")
    rol = models.CharField(
        max_length=30,
        choices=RolChoices.choices,
        default=RolChoices.CLIENTE,
        help_text="Rol operativo en el sistema",
    )
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="usuarios",
        help_text="Empresa cliente a la que pertenece el usuario (obligatoria para clientes)",
    )
    activo = models.BooleanField(
        default=True,
        help_text="Designa si la cuenta de usuario se encuentra habilitada",
    )
    is_staff = models.BooleanField(
        default=False,
        help_text="Designa si el usuario puede acceder al sitio de administración",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    objects = UsuarioManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["nombre"]

    class Meta:
        db_table = "usuarios"
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"
        ordering = ["nombre"]

    def __str__(self) -> str:
        return f"{self.nombre} <{self.email}> ({self.get_rol_display()})"

    @property
    def is_active(self) -> bool:
        """Django auth compatibility: maps to self.activo."""
        return self.activo

    @is_active.setter
    def is_active(self, value: bool) -> None:
        self.activo = value

    @property
    def correo(self) -> str:
        """Spanish alias for email."""
        return self.email

    @correo.setter
    def correo(self, value: str) -> None:
        self.email = value

    @property
    def created_at(self):
        """English alias for fecha_creacion."""
        return self.fecha_creacion

    @property
    def updated_at(self):
        """English alias for fecha_actualizacion."""
        return self.fecha_actualizacion
