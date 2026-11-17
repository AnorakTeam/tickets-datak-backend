"""Vistas (endpoints) del API de tickets.

Una vista recibe la petición HTTP, consulta la base de datos y devuelve la
respuesta usando un serializer.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Case, IntegerField, Prefetch, Q, Value, When
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.companies.models import Empresa, RolChoices, Usuario
from apps.companies.permissions import (
    IsClientUser,
    IsInternalSupportUser,
    IsSupportAgentUser,
)
from apps.core.pagination import StandardResultsPagination, SupportInboxPagination
from apps.tickets.models import (
    CanalOrigenChoices,
    EstadoChoices,
    PrioridadChoices,
    Ticket,
    TicketItem,
)
from apps.tickets.serializers import (
    ClientTicketCreatedResponseSerializer,
    ClientTicketCreateSerializer,
    ClientTicketDetailSerializer,
    ClientTicketListSerializer,
    SupportExternalTicketCreateSerializer,
    SupportTicketDetailSerializer,
    SupportTicketInboxSerializer,
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


class SupportTicketInboxView(generics.ListCreateAPIView):
    """`GET` y `POST /api/v1/support/tickets/` — Bandeja unificada (BE-19 RF7) y registro externo por agente (BE-20 RF9).

    - `GET`: accesible para `agente_soporte` y `responsable_atencion` (`IsInternalSupportUser`).
      Consulta tickets de todas las empresas con filtros multi-tenant y paginación a 20 elementos.
    - `POST`: restringido exclusivamente a `agente_soporte` (`IsSupportAgentUser`).
      Registra un ticket reportado por canal externo (`WhatsApp`, `Slack`, `Otro`, etc.)
      en nombre de un cliente de la empresa indicada, asignando `registrado_por_agente=request.user`,
      generando radicado atómico, creando el `TicketItem` de `CREACION` y enviando el comprobante por correo.
    """

    serializer_class = SupportTicketInboxSerializer
    permission_classes = [IsAuthenticated, IsInternalSupportUser]
    pagination_class = SupportInboxPagination

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsSupportAgentUser()]
        return [IsAuthenticated(), IsInternalSupportUser()]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return SupportExternalTicketCreateSerializer
        return SupportTicketInboxSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        datos = serializer.validated_data

        empresa_obj = Empresa.objects.filter(pk=datos["empresa_id"], activa=True).first()
        if empresa_obj is None:
            return Response(
                {
                    "detail": "La empresa seleccionada no existe o no está activa.",
                    "empresa_id": ["La empresa seleccionada no existe o no está activa."],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        creado_por_id = datos.get("creado_por_id")
        if creado_por_id is not None:
            cliente_creador = Usuario.objects.filter(pk=creado_por_id).first()
            if (
                cliente_creador is None
                or cliente_creador.rol != RolChoices.CLIENTE
                or cliente_creador.empresa_id != empresa_obj.id
                or not cliente_creador.activo
            ):
                return Response(
                    {
                        "detail": "El usuario cliente indicado no pertenece a la empresa seleccionada o no está activo.",
                        "creado_por_id": [
                            "El usuario cliente indicado no pertenece a la empresa seleccionada o no está activo."
                        ],
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            cliente_creador = (
                Usuario.objects.filter(
                    empresa_id=empresa_obj.id,
                    rol=RolChoices.CLIENTE,
                    activo=True,
                )
                .order_by("id")
                .first()
            )
            if cliente_creador is None:
                return Response(
                    {
                        "detail": "La empresa seleccionada no tiene usuarios clientes activos registrados.",
                        "creado_por_id": [
                            "La empresa seleccionada no tiene usuarios clientes activos registrados."
                        ],
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            ticket = TicketCreationService.create_ticket(
                creado_por=cliente_creador,
                empresa=empresa_obj,
                modulo_id=datos["modulo_id"],
                pestana_o_documento=datos["pestana_o_documento"],
                asunto=datos["asunto"],
                descripcion=datos["descripcion"],
                mensaje_error=datos.get("mensaje_error", ""),
                prioridad=datos["prioridad"],
                canal_origen=datos["canal_origen"],
                registrado_por_agente=request.user,
                observaciones_iniciales=(
                    f"Ticket registrado por agente de soporte desde el canal {datos['canal_origen']}."
                ),
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

        salida = SupportTicketDetailSerializer(ticket)
        return Response(salida.data, status=status.HTTP_201_CREATED)

    def get_queryset(self):
        queryset = Ticket.objects.select_related(
            "empresa",
            "modulo",
            "creado_por",
            "responsable",
        )
        params = self.request.query_params

        empresa = params.get("empresa") or params.get("empresa_id")
        if empresa:
            try:
                queryset = queryset.filter(empresa_id=int(empresa))
            except (TypeError, ValueError) as exc:
                raise ValidationError({"empresa": ["ID de empresa no válido."]}) from exc

        estado = params.get("estado")
        if estado:
            if estado not in EstadoChoices.values:
                opciones = ", ".join(EstadoChoices.values)
                raise ValidationError({"estado": [f"Estado no válido. Opciones: {opciones}."]})
            queryset = queryset.filter(estado=estado)

        prioridad = params.get("prioridad")
        if prioridad:
            if prioridad not in PrioridadChoices.values:
                opciones = ", ".join(PrioridadChoices.values)
                raise ValidationError(
                    {"prioridad": [f"Prioridad no válida. Opciones: {opciones}."]}
                )
            queryset = queryset.filter(prioridad=prioridad)

        canal_origen = params.get("canal_origen") or params.get("canal")
        if canal_origen:
            if canal_origen not in CanalOrigenChoices.values:
                opciones = ", ".join(CanalOrigenChoices.values)
                raise ValidationError(
                    {"canal_origen": [f"Canal de origen no válido. Opciones: {opciones}."]}
                )
            queryset = queryset.filter(canal_origen=canal_origen)

        responsable = params.get("responsable") or params.get("responsable_id")
        if responsable:
            try:
                queryset = queryset.filter(responsable_id=int(responsable))
            except (TypeError, ValueError) as exc:
                raise ValidationError({"responsable": ["ID de responsable no válido."]}) from exc

        search = (params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(Q(radicado__icontains=search) | Q(asunto__icontains=search))

        return queryset.annotate(
            is_abierto=Case(
                When(estado=EstadoChoices.ABIERTO, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        ).order_by("is_abierto", "-fecha_creacion", "-id")


class SupportTicketDetailView(generics.RetrieveAPIView):
    """`GET /api/v1/support/tickets/{id}/` — Detalle completo del ticket para soporte (BE-20, RF8).

    - Accesible para `agente_soporte` y `responsable_atencion` (`IsInternalSupportUser`).
    - Soporta lookup dual: resuelve el ticket tanto si `{id}` es numérico (`pk`)
      como si es el código de radicado (`TK-AAAA-NNNNNN`), devolviendo `404` si no existe.
    - Expone todos los 20 campos del `Ticket` y el `historial` completo ordenado
      cronológicamente de forma ascendente, incluyendo notas internas (`es_interna=True`).
    """

    serializer_class = SupportTicketDetailSerializer
    permission_classes = [IsAuthenticated, IsInternalSupportUser]
    lookup_url_kwarg = "lookup"

    def get_queryset(self):
        return Ticket.objects.select_related(
            "empresa",
            "modulo",
            "creado_por",
            "responsable",
            "registrado_por_agente",
        ).prefetch_related(
            Prefetch(
                "historial",
                queryset=TicketItem.objects.select_related(
                    "actor",
                    "responsable_asignado",
                ).order_by("fecha_creacion", "id"),
            )
        )

    def get_object(self):
        queryset = self.filter_queryset(self.get_queryset())
        valor = str(self.kwargs.get(self.lookup_url_kwarg, "")).strip()

        if valor.isdigit():
            obj = get_object_or_404(queryset, pk=int(valor))
        else:
            obj = get_object_or_404(queryset, radicado=valor)

        self.check_object_permissions(self.request, obj)
        return obj
