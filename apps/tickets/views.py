"""Vistas (endpoints) del API de tickets.

Una vista recibe la petición HTTP, consulta la base de datos y devuelve la
respuesta usando un serializer.
"""

from django.db.models import Case, IntegerField, Prefetch, Value, When
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from apps.companies.permissions import IsClientUser
from apps.core.pagination import StandardResultsPagination
from apps.tickets.models import EstadoChoices, Ticket, TicketItem
from apps.tickets.serializers import ClientTicketDetailSerializer, ClientTicketListSerializer


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


class ClientTicketDetailView(generics.RetrieveAPIView):
    """`GET /api/v1/client/tickets/{radicado}/` — detalle de un ticket (BE-13, RF5).

    - Solo clientes autenticados (IsAuthenticated + IsClientUser).
    - Se busca por `radicado` (por ejemplo TK-2026-000001), no por id.
    - Multi-tenant (RNF2): la búsqueda se hace SOLO dentro de los tickets de la
      empresa del usuario. Si el radicado existe pero es de otra empresa, la
      respuesta es 404 "No encontrado" (no 403), para no revelar que ese
      radicado existe en otra empresa (evita "enumerar" tickets ajenos).
    - Nunca devuelve el responsable, el agente ni las notas internas.
    """

    serializer_class = ClientTicketDetailSerializer
    permission_classes = [IsAuthenticated, IsClientUser]
    # Campo del modelo con el que se busca el ticket y nombre del parámetro en la URL.
    lookup_field = "radicado"

    def get_queryset(self):
        """Tickets de la empresa del usuario, con su historial público ya cargado."""
        return (
            Ticket.objects.filter(empresa_id=self.request.user.empresa_id)
            .select_related("modulo")
            .prefetch_related(
                # Prefetch carga el historial en una sola consulta extra y, con
                # el filtro, deja por fuera las notas internas (es_interna=True).
                # El resultado queda en `ticket.historial_publico`, que es lo que
                # usa el serializer. order_by asegura el orden cronológico.
                Prefetch(
                    "historial",
                    queryset=TicketItem.objects.filter(es_interna=False).order_by(
                        "fecha_creacion", "id"
                    ),
                    to_attr="historial_publico",
                )
            )
        )
