"""Registro de los modelos de `companies` en el panel de administración de Django.

Esto permite crear, buscar y editar empresas y usuarios desde /admin/ durante el
desarrollo y las pruebas, sin tener que escribir código ni usar la base de datos
directamente.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import BaseUserCreationForm, UserChangeForm

from apps.companies.models import Empresa, Usuario


# El decorador registra el modelo Empresa en el admin usando esta configuración.
@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    # Columnas que se muestran en la lista de empresas.
    list_display = ("nombre", "identificacion", "activa", "created_at")
    # Filtro lateral para ver solo empresas activas o inactivas.
    list_filter = ("activa",)
    # Campos por los que busca la caja de búsqueda del admin.
    search_fields = ("nombre", "identificacion")


class UsuarioCreationForm(BaseUserCreationForm):
    """Formulario para crear un usuario desde el admin.

    Hereda de BaseUserCreationForm, que ya trae los campos "contraseña" y
    "confirmar contraseña" y guarda la contraseña cifrada. Solo se le indica qué
    modelo y qué campos usar, porque nuestro usuario no tiene `username`.
    """

    class Meta:
        model = Usuario
        fields = ("correo", "nombre", "rol", "empresa")


class UsuarioChangeForm(UserChangeForm):
    """Formulario para editar un usuario existente desde el admin.

    La contraseña no se edita aquí directamente: Django muestra un enlace para
    cambiarla de forma segura.
    """

    class Meta:
        model = Usuario
        fields = "__all__"


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    """Admin de usuarios basado en el UserAdmin de Django, adaptado a nuestros campos."""

    form = UsuarioChangeForm
    add_form = UsuarioCreationForm

    # Columnas de la lista de usuarios, filtros laterales, búsqueda y orden.
    list_display = ("correo", "nombre", "rol", "empresa", "activo", "is_staff")
    list_filter = ("rol", "activo", "is_staff", "empresa")
    search_fields = ("correo", "nombre")
    ordering = ("correo",)

    # Secciones del formulario al EDITAR un usuario.
    fieldsets = (
        (None, {"fields": ("correo", "password")}),
        ("Información personal", {"fields": ("nombre", "rol", "empresa")}),
        (
            "Permisos",
            {"fields": ("activo", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Fechas", {"fields": ("last_login", "created_at")}),
    )
    # `created_at` se llena solo, así que en el formulario es de solo lectura.
    readonly_fields = ("last_login", "created_at")

    # Secciones del formulario al CREAR un usuario (pide contraseña dos veces).
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("correo", "nombre", "rol", "empresa", "password1", "password2"),
            },
        ),
    )

    # Lista de grupos y permisos con buscador en dos columnas.
    filter_horizontal = ("groups", "user_permissions")
