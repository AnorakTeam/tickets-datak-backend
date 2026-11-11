"""Registro de los modelos de `companies` en el panel de administración de Django.

Esto permite crear, buscar y editar empresas desde /admin/ durante el desarrollo
y las pruebas, sin tener que escribir código ni usar la base de datos directamente.
"""

from django.contrib import admin

from apps.companies.models import Empresa


# El decorador registra el modelo Empresa en el admin usando esta configuración.
@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    # Columnas que se muestran en la lista de empresas.
    list_display = ("nombre", "identificacion", "activa", "created_at")
    # Filtro lateral para ver solo empresas activas o inactivas.
    list_filter = ("activa",)
    # Campos por los que busca la caja de búsqueda del admin.
    search_fields = ("nombre", "identificacion")
