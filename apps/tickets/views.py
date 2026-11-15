"""Vistas (endpoints) del API de tickets.

Una vista recibe la petición HTTP, consulta la base de datos y devuelve la
respuesta usando un serializer.
"""

from django.db.models import Case, IntegerField, Value, When
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from apps.companies.permissions import IsClientUser
from apps.core.pagination import StandardResultsPagination
from apps.tickets.models import EstadoChoices, Ticket
from apps.tickets.serializers import ClientTicketListSerializer


class ClientTicketListView(generics.ListAPIView):
    """`GET /api/v1/client/tickets/?estado=&page=` — "Mis tickets" del cliente (BE-12, RF4).

    - Solo clientes autenticados (IsAuthenticated + IsClientUser).
    - Multi-tenant (RNF2): solo devuelve tickets de la empresa del usuario que
      hace la petición (`request.user.empresa`). La empresa NUNCA se lee de la URL
      ni del cuerpo de la petición.
    - Orden: primero los tickets en estado "Abierto"; dentro de cada grupo, del
      más reciente al más antiguo.
    - Filtro opcional `?estado=` con los valores del catálogo
      (Abierto, En gestion, Resuelto, No procedente).
    - Paginado de 10 en 10 (`?page=`).

    Nota para BE-11 (POST en esta misma URL): se puede convertir esta vista en
    `ListCreateAPIView` y agregar el serializer de creación, en vez de crear
    otra vista para la misma ruta.
    """

    serializer_class = ClientTicketListSerializer
    permission_classes = [IsAuthenticated, IsClientUser]
    pagination_class = StandardResultsPagination

    def get_queryset(self):
        """Arma la consulta de tickets que puede ver este cliente."""
        # 1. Aislamiento por empresa: SIEMPRE filtrar por la empresa del usuario.
        queryset = Ticket.objects.filter(empresa_id=self.request.user.empresa_id)

        # 2. Filtro opcional por estado (?estado=Resuelto).
        estado = self.request.query_params.get("estado")
        if estado:
            if estado not in EstadoChoices.values:
                opciones = ", ".join(EstadoChoices.values)
                raise ValidationError({"estado": [f"Estado no válido. Opciones: {opciones}."]})
            queryset = queryset.filter(estado=estado)

        # 3. Orden: "Abierto" primero. Case/When crea una columna temporal que
        #    vale 0 para los abiertos y 1 para los demás; se ordena por ella y
        #    luego por fecha descendente. `-id` desempata tickets con la misma fecha.
        queryset = queryset.annotate(
            prioridad_orden_abierto=Case(
                When(estado=EstadoChoices.ABIERTO, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        ).order_by("prioridad_orden_abierto", "-fecha_creacion", "-id")

        # 4. select_related trae el módulo en la misma consulta (para
        #    `modulo_nombre`), evitando una consulta extra por cada fila (RNF3).
        return queryset.select_related("modulo")
