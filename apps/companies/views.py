"""Vistas (endpoints) de la app `companies` (tareas BE-10 y BE-19)."""

from django.db.models import Prefetch
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from apps.companies.models import Empresa, ModuloContratado
from apps.companies.permissions import IsInternalSupportUser
from apps.companies.serializers import (
    ModuloContratadoSerializer,
    SupportEmpresaCatalogSerializer,
)


class ModuloContratadoListView(generics.ListAPIView):
    """`GET /api/v1/modulos/` — Lista los módulos activos contratados por la empresa (BE-10, RF2).

    Reglas del contrato (sección 4.3 de CONTRATO_API y RNF2):
    - Requiere autenticación (`IsAuthenticated`).
    - Devuelve un arreglo JSON plano `[...]` (`pagination_class = None`).
    - Filtra estrictamente por `request.user.empresa` y `activo=True`.
    - Ignora cualquier parámetro `?empresa_id=` enviado en la URL.
    - Si el usuario autenticado no tiene empresa asignada (p. ej. personal interno)
      o su empresa no tiene módulos activos, devuelve `[]` (`200 OK`).
    """

    serializer_class = ModuloContratadoSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        empresa = getattr(self.request.user, "empresa", None)
        if not empresa:
            return ModuloContratado.objects.none()

        return ModuloContratado.objects.filter(
            empresa=empresa,
            activo=True,
        ).order_by("nombre", "id")


class SupportEmpresaCatalogListView(generics.ListAPIView):
    """`GET /api/v1/support/empresas/` — Catálogo de empresas activas y sus módulos activos (BE-19, RF7).

    Restringido al personal interno (`agente_soporte` y `responsable_atencion`).
    Devuelve una lista directa sin paginar (`pagination_class = None`) optimizada
    con `prefetch_related` para poblar los selectores de filtros en la consola de soporte.
    """

    serializer_class = SupportEmpresaCatalogSerializer
    permission_classes = [IsAuthenticated, IsInternalSupportUser]
    pagination_class = None

    def get_queryset(self):
        return (
            Empresa.objects.filter(activa=True)
            .prefetch_related(
                Prefetch(
                    "modulos_contratados",
                    queryset=ModuloContratado.objects.filter(activo=True).order_by("nombre", "id"),
                    to_attr="modulos_activos",
                )
            )
            .order_by("nombre", "id")
        )
