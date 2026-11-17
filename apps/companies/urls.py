"""Rutas del API de `companies` (incluidas bajo `/api/v1/` en `config/urls.py`)."""

from django.urls import path

from apps.companies.views import ModuloContratadoListView, SupportEmpresaCatalogListView

urlpatterns = [
    # GET /api/v1/modulos/ — módulos contratados activos de la empresa autenticada (BE-10, RF2).
    path("modulos/", ModuloContratadoListView.as_view(), name="modulos-contratados-list"),
    # GET /api/v1/support/empresas/ — catálogo de empresas activas y módulos activos para soporte (BE-19, RF7).
    path(
        "support/empresas/",
        SupportEmpresaCatalogListView.as_view(),
        name="support-empresas-catalog",
    ),
]
