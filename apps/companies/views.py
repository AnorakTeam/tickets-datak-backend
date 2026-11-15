"""Vistas (endpoints) de la app `companies` (tarea BE-10, issue #23)."""

from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from apps.companies.models import ModuloContratado
from apps.companies.serializers import ModuloContratadoSerializer


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
