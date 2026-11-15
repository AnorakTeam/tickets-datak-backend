"""Vistas (endpoints) del API de tickets.

Una vista recibe la petición HTTP, consulta la base de datos y devuelve la
respuesta usando un serializer.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Case, IntegerField, Prefetch, Value, When
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.companies.permissions import IsClientUser
from apps.core.pagination import StandardResultsPagination
from apps.tickets.models import CanalOrigenChoices, EstadoChoices, Ticket, TicketItem
from apps.tickets.serializers import (
    ClientTicketCreatedResponseSerializer,
    ClientTicketCreateSerializer,
    ClientTicketDetailSerializer,
    ClientTicketListSerializer,
)
from apps.tickets.services import TicketCreationService


class ClientTicketListView(generics.ListCreateAPIView):
    """`GET` y `POST /api/v1/client/tickets/` — Listado y creación de tickets del cliente (BE-11 RF1, BE-12 RF4).

    - Solo clientes autenticados (`IsAuthenticated` + `IsClientUser`).
    - `GET`: lista paginada de los tickets de `request.user.empresa`, ordenando
      primero los `Abierto` y luego por `fecha_creacion` descendente.
    - `POST`: crea un nuevo ticket inyectando `empresa=request.user.empresa`,
      `creado_por=request.user` y `canal_origen='Portal'`, delegando en
      `TicketCreationService` (BE-08) y despachando el comprobante por correo (BE-09).
    """

    serializer_class = ClientTicketListSerializer
    permission_classes = [IsAuthenticated, IsClientUser]
    pagination_class = StandardResultsPagination

    def get_serializer_class(self):
        if self.request.method == "POST":
            return ClientTicketCreateSerializer
        return ClientTicketListSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        datos = serializer.validated_data

        try:
            ticket = TicketCreationService.create_ticket(
                creado_por=request.user,
                empresa=request.user.empresa,
                modulo_id=datos["modulo_id"],
                pestana_o_documento=datos["pestana_o_documento"],
                asunto=datos["asunto"],
                descripcion=datos["descripcion"],
                mensaje_error=datos.get("mensaje_error", ""),
                prioridad=datos["prioridad"],
                canal_origen=CanalOrigenChoices.PORTAL,
            )
        except DjangoValidationError as exc:
            errores = (
                exc.message_dict
                if hasattr(exc, "message_dict")
                else {"non_field_errors": exc.messages}
            )
            primer_mensaje = (
                next(iter(errores.values()))[0] if errores else "Los datos enviados no son válidos."
            )
            return Response(
                {
                    "detail": primer_mensaje,
                    "errors": errores,
                    **errores,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        salida = ClientTicketCreatedResponseSerializer(ticket)
        return Response(salida.data, status=status.HTTP_201_CREATED)

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
