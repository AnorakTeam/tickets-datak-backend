"""Vistas (endpoints) del API de tickets.

Una vista recibe la petición HTTP, consulta la base de datos y devuelve la
respuesta usando un serializer.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Case, IntegerField, Prefetch, Q, Value, When
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

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
    TicketNotificacion,
    TipoAccionChoices,
)
from apps.tickets.serializers import (
    ROLES_ASIGNABLES,
    ClientTicketCreatedResponseSerializer,
    ClientTicketCreateSerializer,
    ClientTicketDetailSerializer,
    ClientTicketListSerializer,
    SupportExternalTicketCreateSerializer,
    SupportStaffSerializer,
    SupportTicketAssignSerializer,
    SupportTicketClassifySerializer,
    SupportTicketDetailSerializer,
    SupportTicketDismissSerializer,
    SupportTicketInboxSerializer,
    SupportInternalNoteSerializer,
    SupportTicketResolveSerializer,
    ClientNotificationSerializer,
)
from apps.tickets.services import NotificationService, TicketCreationService


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


class ClientNotificationListView(APIView):
    """`GET /api/v1/client/notificaciones/` — Bandeja de notificaciones del cliente (BE-25, RF16).

    - Solo clientes autenticados (`IsAuthenticated` + `IsClientUser`).
    - Filtra estrictamente por `destinatario=request.user` y `empresa_id=request.user.empresa_id`.
    - Ordenado cronológicamente descendente por `fecha_creacion`.
    - Devuelve `unread_count` con el total de notificaciones no leídas y la lista de notificaciones.
    """

    permission_classes = [IsAuthenticated, IsClientUser]

    def get(self, request):
        qs = (
            TicketNotificacion.objects.filter(
                destinatario=request.user,
                empresa_id=request.user.empresa_id,
            )
            .select_related("ticket")
            .order_by("-fecha_creacion", "-id")
        )

        unread_count = qs.filter(leida=False).count()
        serializer = ClientNotificationSerializer(qs, many=True)

        return Response(
            {
                "unread_count": unread_count,
                "count": qs.count(),
                "notificaciones": serializer.data,
                "results": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class ClientNotificationMarkReadView(APIView):
    """`PATCH /api/v1/client/notificaciones/{id}/leida/` — Marcar notificación como leída (BE-25, RF16).

    - Solo clientes autenticados (`IsAuthenticated` + `IsClientUser`).
    - Aislamiento multi-tenant estricto: la notificación debe pertenecer a `request.user` y `request.user.empresa`.
    - Si el ID pertenece a otra empresa o a otro usuario, responde 404 (para evitar enumeración).
    - Actualiza `leida=True` de manera idempotente y devuelve el estado actualizado.
    """

    permission_classes = [IsAuthenticated, IsClientUser]

    def patch(self, request, pk):
        notificacion = get_object_or_404(
            TicketNotificacion,
            pk=pk,
            destinatario=request.user,
            empresa_id=request.user.empresa_id,
        )

        if not notificacion.leida:
            notificacion.leida = True
            notificacion.save(update_fields=["leida"])

        serializer = ClientNotificationSerializer(notificacion)
        return Response(
            {
                "success": True,
                "id": notificacion.id,
                "leida": True,
                "notificacion": serializer.data,
            },
            status=status.HTTP_200_OK,
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


# --------------------------------------------------------------------------
# Acciones de soporte sobre un ticket (BE-21 y siguientes).
#
# Las URL usan `{id}`, que (igual que el detalle de BE-20) puede ser el id
# numérico o el radicado (TK-AAAA-NNNNNN). Las dos funciones de abajo las
# comparten todas las acciones para no repetir código.
# --------------------------------------------------------------------------


def obtener_ticket_para_actualizar(lookup):
    """Busca el ticket por id o radicado y lo BLOQUEA mientras dura la transacción.

    `select_for_update()` evita que dos agentes cambien el mismo ticket al mismo
    tiempo (el segundo espera a que termine el primero). Solo funciona dentro de
    `transaction.atomic()`. Si el ticket no existe, responde 404.
    """
    valor = str(lookup).strip()
    queryset = Ticket.objects.select_for_update()
    if valor.isdigit():
        return get_object_or_404(queryset, pk=int(valor))
    return get_object_or_404(queryset, radicado=valor)


def respuesta_detalle_soporte(ticket_id, codigo_estado=status.HTTP_200_OK):
    """Devuelve el detalle completo del ticket (mismo formato que BE-20) ya actualizado.

    Se vuelve a consultar el ticket con sus relaciones y el historial para que
    la respuesta incluya el nuevo registro de `TicketItem`.
    """
    ticket = (
        Ticket.objects.select_related(
            "empresa", "modulo", "creado_por", "responsable", "registrado_por_agente"
        )
        .prefetch_related(
            Prefetch(
                "historial",
                queryset=TicketItem.objects.select_related(
                    "actor", "responsable_asignado"
                ).order_by("fecha_creacion", "id"),
            )
        )
        .get(pk=ticket_id)
    )
    return Response(SupportTicketDetailSerializer(ticket).data, status=codigo_estado)


class SupportTicketClassifyView(APIView):
    """`PATCH /api/v1/support/tickets/{id}/clasificar/` — clasificar el ticket (BE-21, RF10).

    - Solo `agente_soporte` (sección 5.4 del documento de arquitectura).
    - Guarda la `clasificacion` y, si se envía, la nueva `prioridad`.
    - No cambia el estado del ticket.
    - Deja un registro en el historial: `TicketItem(tipo_accion='CLASIFICACION')`
      con `es_interna=True`, porque la clasificación es información interna
      que el cliente no ve (RNF2).
    """

    permission_classes = [IsAuthenticated, IsSupportAgentUser]

    def patch(self, request, lookup):
        # 1. Validar el cuerpo (si algo está mal, DRF responde 400 aquí mismo).
        serializer = SupportTicketClassifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        clasificacion = serializer.validated_data["clasificacion"]
        prioridad_nueva = serializer.validated_data.get("prioridad")

        # 2. Todo dentro de una transacción: o se guarda el ticket Y el
        #    historial, o no se guarda nada.
        with transaction.atomic():
            ticket = obtener_ticket_para_actualizar(lookup)
            prioridad_anterior = ticket.prioridad

            ticket.clasificacion = clasificacion
            if prioridad_nueva:
                ticket.prioridad = prioridad_nueva
            # `fecha_actualizacion` se incluye para que `auto_now` la actualice.
            ticket.save(update_fields=["clasificacion", "prioridad", "fecha_actualizacion"])

            # 3. Texto del historial, por ejemplo:
            #    "Clasificado como Bug. Prioridad: Media -> Alta."
            observaciones = f"Clasificado como {clasificacion}."
            if prioridad_nueva and prioridad_nueva != prioridad_anterior:
                observaciones += f" Prioridad: {prioridad_anterior} -> {prioridad_nueva}."

            TicketItem.objects.create(
                ticket=ticket,
                actor=request.user,
                tipo_accion=TipoAccionChoices.CLASIFICACION,
                es_interna=True,
                observaciones=observaciones,
            )

        return respuesta_detalle_soporte(ticket.pk)


class SupportTicketDismissView(APIView):
    """`POST /api/v1/support/tickets/{id}/no-procedente/` — desestimar el ticket (BE-21, RF12).

    - Solo `agente_soporte` (sección 5.4 del documento de arquitectura).
    - `motivo_no_procedente` es obligatorio (400 si falta o está vacío).
    - Solo se puede desde "Abierto" o "En gestion" (máquina de estados, sección 4).
      Si el ticket ya está "Resuelto" o "No procedente" responde 400 y no cambia nada.
    - Cambia el estado a "No procedente", guarda el motivo y la `fecha_resolucion`.
    - Deja un registro `TicketItem(tipo_accion='NO_PROCEDENTE')` visible para el
      cliente (`es_interna=False`), con el motivo como observación.
    """

    permission_classes = [IsAuthenticated, IsSupportAgentUser]

    # Estados finales: desde aquí ya no se puede pasar a "No procedente".
    ESTADOS_CERRADOS = (EstadoChoices.RESUELTO, EstadoChoices.NO_PROCEDENTE)

    def post(self, request, lookup):
        serializer = SupportTicketDismissSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        motivo = serializer.validated_data["motivo_no_procedente"]

        with transaction.atomic():
            ticket = obtener_ticket_para_actualizar(lookup)

            # Regla de la máquina de estados: un ticket cerrado no se desestima.
            if ticket.estado in self.ESTADOS_CERRADOS:
                mensaje = (
                    f"No se puede marcar como No procedente un ticket en estado "
                    f"{ticket.get_estado_display()}."
                )
                raise ValidationError({"detail": mensaje, "estado": [mensaje]})

            estado_anterior = ticket.estado
            ticket.estado = EstadoChoices.NO_PROCEDENTE
            ticket.motivo_no_procedente = motivo
            ticket.fecha_resolucion = timezone.now()
            ticket.save(
                update_fields=[
                    "estado",
                    "motivo_no_procedente",
                    "fecha_resolucion",
                    "fecha_actualizacion",
                ]
            )

            TicketItem.objects.create(
                ticket=ticket,
                actor=request.user,
                tipo_accion=TipoAccionChoices.NO_PROCEDENTE,
                estado_anterior=estado_anterior,
                estado_nuevo=EstadoChoices.NO_PROCEDENTE,
                es_interna=False,
                observaciones=motivo,
            )

            # Notificar al cliente en portal y por correo (BE-23, RF16)
            NotificationService.notify_ticket_closed(ticket)

        return respuesta_detalle_soporte(ticket.pk)


class SupportResponsablesView(generics.ListAPIView):
    """`GET /api/v1/support/responsables/` — personal al que se puede asignar un ticket (BE-22, RF11).

    - Accesible para el personal interno (`agente_soporte` y `responsable_atencion`),
      porque la lista también sirve para el filtro por responsable de la bandeja.
    - Devuelve los usuarios ACTIVOS con rol `responsable_atencion` o `agente_soporte`,
      ordenados por nombre.
    - Sin paginación: es la lista completa para un desplegable.
    """

    serializer_class = SupportStaffSerializer
    permission_classes = [IsAuthenticated, IsInternalSupportUser]
    pagination_class = None

    def get_queryset(self):
        return Usuario.objects.filter(rol__in=ROLES_ASIGNABLES, activo=True).order_by(
            "nombre", "id"
        )


class SupportTicketAssignView(APIView):
    """`PATCH /api/v1/support/tickets/{id}/asignar/` — asignar o reasignar responsable (BE-22, RF11).

    - Solo `agente_soporte` (sección 5.4 del documento de arquitectura).
    - `responsable_id` debe ser personal interno activo; un cliente da 400.
    - Estado (máquina de estados, sección 4):
        * "Abierto"    -> pasa a "En gestion" (asignación inicial).
        * "En gestion" -> se queda en "En gestion" (reasignación).
        * "Resuelto" o "No procedente" -> 400, un ticket cerrado no se asigna.
    - Deja un registro `TicketItem(tipo_accion='ASIGNACION')` con el
      `responsable_asignado` y el estado anterior/nuevo. Es visible para el
      cliente (así ve que su ticket pasó a "En gestión"), pero la observación
      NO dice el nombre del responsable, y el portal del cliente no muestra
      `actor` ni `responsable_asignado` (RNF2).
    """

    permission_classes = [IsAuthenticated, IsSupportAgentUser]

    ESTADOS_CERRADOS = (EstadoChoices.RESUELTO, EstadoChoices.NO_PROCEDENTE)

    def patch(self, request, lookup):
        serializer = SupportTicketAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # validate_responsable_id ya devolvió el objeto Usuario.
        responsable = serializer.validated_data["responsable_id"]

        with transaction.atomic():
            ticket = obtener_ticket_para_actualizar(lookup)

            if ticket.estado in self.ESTADOS_CERRADOS:
                mensaje = (
                    f"No se puede asignar un responsable a un ticket en estado "
                    f"{ticket.get_estado_display()}."
                )
                raise ValidationError({"detail": mensaje, "estado": [mensaje]})

            estado_anterior = ticket.estado
            # Si ya tenía responsable, es una reasignación.
            es_reasignacion = ticket.responsable_id is not None

            ticket.responsable = responsable
            # Solo cambia de estado si estaba "Abierto"; si ya estaba
            # "En gestion" se queda igual.
            ticket.estado = EstadoChoices.EN_GESTION
            ticket.save(update_fields=["responsable", "estado", "fecha_actualizacion"])

            TicketItem.objects.create(
                ticket=ticket,
                actor=request.user,
                tipo_accion=TipoAccionChoices.ASIGNACION,
                estado_anterior=estado_anterior,
                estado_nuevo=ticket.estado,
                responsable_asignado=responsable,
                es_interna=False,
                observaciones=(
                    "Ticket reasignado a otro responsable."
                    if es_reasignacion
                    else "Ticket asignado a un responsable para su atención."
                ),
            )

        return respuesta_detalle_soporte(ticket.pk)


class SupportEngineerQueueView(generics.ListAPIView):
    """`GET /api/v1/support/mis-tickets/` — Cola de tickets asignados al ingeniero autenticado (BE-24, RF13).

    - Solo personal interno (`IsAuthenticated` + `IsInternalSupportUser`).
    - Filtra estrictamente por `responsable=request.user`.
    - Soporta filtro opcional `?estado=` ('En gestion', 'Resuelto', etc.).
    - Ordena por estado activo primero ('En gestion', 'Abierto') y luego por `-fecha_creacion`.
    - Utiliza paginación `SupportInboxPagination` (20 por página) y `SupportTicketInboxSerializer`.
    """

    serializer_class = SupportTicketInboxSerializer
    permission_classes = [IsAuthenticated, IsInternalSupportUser]
    pagination_class = SupportInboxPagination

    def get_queryset(self):
        queryset = Ticket.objects.filter(responsable=self.request.user).select_related(
            "empresa",
            "modulo",
            "creado_por",
            "responsable",
        )
        estado = self.request.query_params.get("estado")
        if estado:
            if estado not in EstadoChoices.values:
                opciones = ", ".join(EstadoChoices.values)
                raise ValidationError({"estado": [f"Estado no válido. Opciones: {opciones}."]})
            queryset = queryset.filter(estado=estado)

        return queryset.annotate(
            is_cerrado=Case(
                When(
                    estado__in=[EstadoChoices.RESUELTO, EstadoChoices.NO_PROCEDENTE],
                    then=Value(1),
                ),
                default=Value(0),
                output_field=IntegerField(),
            )
        ).order_by("is_cerrado", "-fecha_creacion", "-id")


class SupportTicketInternalNoteView(APIView):
    """`POST /api/v1/support/tickets/{id}/notas-internas/` — Registrar nota interna en el historial (BE-24, RF14).

    - Accesible para personal interno (`IsAuthenticated` + `IsInternalSupportUser`).
    - Requiere `observaciones` no vacío (400 si falta o son espacios en blanco).
    - Un ticket cerrado ('Resuelto' o 'No procedente') no admite notas internas (responde 400).
    - Registra un nuevo evento `TicketItem(tipo_accion='NOTA_INTERNA', es_interna=True, actor=request.user)`.
    - `es_interna=True` garantiza que la nota nunca llegue al portal del cliente (RNF2).
    - Devuelve el detalle actualizado del ticket (201 Created).
    """

    permission_classes = [IsAuthenticated, IsInternalSupportUser]
    ESTADOS_CERRADOS = (EstadoChoices.RESUELTO, EstadoChoices.NO_PROCEDENTE)

    def post(self, request, lookup):
        serializer = SupportInternalNoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        observaciones = serializer.validated_data["observaciones"]

        with transaction.atomic():
            ticket = obtener_ticket_para_actualizar(lookup)

            if ticket.estado in self.ESTADOS_CERRADOS:
                mensaje = (
                    f"No se pueden agregar notas internas a un ticket en estado "
                    f"{ticket.get_estado_display()}."
                )
                raise ValidationError({"detail": mensaje, "estado": [mensaje]})

            ticket.save(update_fields=["fecha_actualizacion"])

            TicketItem.objects.create(
                ticket=ticket,
                actor=request.user,
                tipo_accion=TipoAccionChoices.NOTA_INTERNA,
                estado_anterior=ticket.estado,
                estado_nuevo=ticket.estado,
                es_interna=True,
                observaciones=observaciones,
            )

        return respuesta_detalle_soporte(ticket.pk, codigo_estado=status.HTTP_201_CREATED)


class SupportTicketResolveView(APIView):
    """`POST /api/v1/support/tickets/{id}/resolver/` — Resolver y cerrar una incidencia (BE-24, RF15).

    - Accesible para personal interno (`IsAuthenticated` + `IsInternalSupportUser`).
    - Requiere `comentario_solucion` obligatorio (400 si falta o son solo espacios en blanco).
    - Solo aplicable desde 'Abierto' o 'En gestion'. Si ya está cerrado responde 400.
    - Cambia estado a 'Resuelto', fija `fecha_resolucion=timezone.now()` y `comentario_solucion`.
    - Registra un evento `TicketItem(tipo_accion='RESOLUCION', es_interna=False)` visible para el cliente.
    - Notifica al cliente en el portal y por correo transaccional vía `NotificationService` (BE-23, RF16).
    - Devuelve el detalle actualizado del ticket (200 OK).
    """

    permission_classes = [IsAuthenticated, IsInternalSupportUser]
    ESTADOS_CERRADOS = (EstadoChoices.RESUELTO, EstadoChoices.NO_PROCEDENTE)

    def post(self, request, lookup):
        serializer = SupportTicketResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comentario_solucion = serializer.validated_data["comentario_solucion"]

        with transaction.atomic():
            ticket = obtener_ticket_para_actualizar(lookup)

            if ticket.estado in self.ESTADOS_CERRADOS:
                mensaje = (
                    f"No se puede resolver un ticket en estado "
                    f"{ticket.get_estado_display()}."
                )
                raise ValidationError({"detail": mensaje, "estado": [mensaje]})

            estado_anterior = ticket.estado
            ticket.estado = EstadoChoices.RESUELTO
            ticket.comentario_solucion = comentario_solucion
            ticket.fecha_resolucion = timezone.now()
            ticket.save(
                update_fields=[
                    "estado",
                    "comentario_solucion",
                    "fecha_resolucion",
                    "fecha_actualizacion",
                ]
            )

            TicketItem.objects.create(
                ticket=ticket,
                actor=request.user,
                tipo_accion=TipoAccionChoices.RESOLUCION,
                estado_anterior=estado_anterior,
                estado_nuevo=EstadoChoices.RESUELTO,
                es_interna=False,
                observaciones=comentario_solucion,
            )

            # Notificar al cliente creador en portal y correo (BE-23, RF16)
            NotificationService.notify_ticket_closed(ticket)

        return respuesta_detalle_soporte(ticket.pk, codigo_estado=status.HTTP_200_OK)

