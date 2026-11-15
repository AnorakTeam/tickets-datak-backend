"""Rutas del API de `companies` (incluidas bajo `/api/v1/` en `config/urls.py`)."""

from django.urls import path

from apps.companies.views import ModuloContratadoListView

urlpatterns = [
    # GET /api/v1/modulos/ — módulos contratados activos de la empresa autenticada (BE-10, RF2).
    path("modulos/", ModuloContratadoListView.as_view(), name="modulos-contratados-list"),
]
