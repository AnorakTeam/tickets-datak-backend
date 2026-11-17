"""Serializers de la app `tickets`.

Un serializer convierte un Ticket (objeto de Python) en el JSON que recibe el
frontend, y define exactamente qué campos se exponen.
"""

from rest_framework import serializers

from apps.tickets.models import CanalOrigenChoices, PrioridadChoices, Ticket, TicketItem


class ClientTicketListSerializer(serializers.ModelSerializer):
    """Fila de la tabla "Mis tickets" del portal del cliente (BE-12, RF4).

    Regla de seguridad (RNF2): este serializer es para CLIENTES, así que NO
    incluye `responsable` (el desarrollador asignado), ni notas internas, ni
    quién lo registró. Solo los campos de la sección 5.2 del documento de
    arquitectura, que son los que ya usa la pantalla de Juan Diego.
    """

    # Nombre del módulo afectado. `source="modulo.nombre"` lo toma del módulo
    # relacionado, así el frontend no tiene que pedirlo aparte.
    modulo_nombre = serializers.CharField(source="modulo.nombre", read_only=True)

    class Meta:
        model = Ticket
        fields = ["radicado", "asunto", "modulo_nombre", "prioridad", "estado", "fecha_creacion"]
        read_only_fields = fields


class ClientTicketHistoryItemSerializer(serializers.ModelSerializer):
    """Un evento de la línea de tiempo del ticket, en versión segura para el cliente.

    Solo se envían eventos con `es_interna=False` (eso lo filtra la vista), y de
    cada evento NO se envían `actor` (quién lo hizo, que puede ser alguien del
    equipo interno), ni `responsable_asignado`, ni el campo `es_interna`.
    """

    class Meta:
        model = TicketItem
        fields = [
            "tipo_accion",
            "estado_anterior",
            "estado_nuevo",
            "observaciones",
            "fecha_creacion",
        ]
        read_only_fields = fields


class ClientTicketDetailSerializer(serializers.ModelSerializer):
    """Detalle de un ticket para el portal del cliente (BE-13, RF5).

    Incluye los campos de la sección 5.2 del documento de arquitectura más:
    - `modulo_nombre`: nombre del módulo afectado (igual que en "Mis tickets").
    - `historial`: línea de tiempo pública del ticket, para la vista de detalle
      del frontend (FE-09).

    Regla de seguridad (RNF2): NUNCA incluye `responsable` (desarrollador
    asignado), `registrado_por_agente` (agente que lo registró), `creado_por`,
    `clasificacion` ni notas internas del historial.
    """

    modulo_nombre = serializers.CharField(source="modulo.nombre", read_only=True)
    # `source="historial_publico"` es una lista que arma la vista con solo los
    # eventos no internos (ver ClientTicketDetailView.get_queryset).
    historial = ClientTicketHistoryItemSerializer(
        source="historial_publico", many=True, read_only=True
    )

    class Meta:
        model = Ticket
        fields = [
            "radicado",
            "estado",
            "prioridad",
            "asunto",
            "descripcion",
            "modulo_nombre",
            "pestana_o_documento",
            "mensaje_error",
            "canal_origen",
            "fecha_creacion",
            "fecha_actualizacion",
            "fecha_resolucion",
            "comentario_solucion",
            "motivo_no_procedente",
            "historial",
        ]
        read_only_fields = fields


class ClientTicketCreateSerializer(serializers.Serializer):
    """Serializer de entrada para reportar un ticket desde el portal (`POST /api/v1/client/tickets/`, BE-11, RF1).

    Valida los campos enviados por el formulario del cliente. La `empresa`,
    `creado_por` y `canal_origen='Portal'` nunca se aceptan del payload: los
    inyecta la vista a partir del usuario autenticado (RNF2).
    """

    modulo_id = serializers.IntegerField(required=True)
    pestana_o_documento = serializers.CharField(
        required=True,
        allow_blank=False,
        max_length=255,
    )
    asunto = serializers.CharField(
        required=True,
        allow_blank=False,
        max_length=255,
    )
    descripcion = serializers.CharField(
        required=True,
        allow_blank=False,
    )
    mensaje_error = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
    )
    prioridad = serializers.ChoiceField(
        choices=PrioridadChoices.choices,
        required=True,
    )

    def validate_mensaje_error(self, value):
        return value or ""


class ClientTicketCreatedResponseSerializer(serializers.ModelSerializer):
    """Serializer de salida (`201 Created`) tras radicar un ticket en el portal (BE-11, RF1).

    Incluye `id`, `radicado`, resumen básico (`estado`, `asunto`, `prioridad`,
    `canal_origen`, `fecha_creacion`), el objeto `modulo` (`id`, `nombre`) y el
    `mensaje` de confirmación que consume `RadicadoModal.vue` (FE-07).
    """

    modulo = serializers.SerializerMethodField()
    mensaje = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = [
            "id",
            "radicado",
            "estado",
            "prioridad",
            "canal_origen",
            "fecha_creacion",
            "asunto",
            "modulo",
            "mensaje",
        ]
        read_only_fields = fields

    def get_modulo(self, obj: Ticket) -> dict:
        return {
            "id": obj.modulo_id,
            "nombre": obj.modulo.nombre,
        }

    def get_mensaje(self, obj: Ticket) -> str:
        return "Incidencia radicada exitosamente. Se envió un comprobante al correo registrado."


class SupportTicketInboxSerializer(serializers.ModelSerializer):
    """Fila de la bandeja unificada de soporte (`GET /api/v1/support/tickets/`, BE-19, RF7).

    Expone la información completa de triaje para el personal interno (`agente_soporte`
    y `responsable_atencion`), incluyendo empresa, módulo, cliente reportante y
    responsable asignado.
    """

    empresa = serializers.SerializerMethodField()
    modulo = serializers.SerializerMethodField()
    creado_por = serializers.SerializerMethodField()
    responsable = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = [
            "id",
            "radicado",
            "asunto",
            "estado",
            "prioridad",
            "canal_origen",
            "clasificacion",
            "fecha_creacion",
            "empresa",
            "modulo",
            "creado_por",
            "responsable",
        ]
        read_only_fields = fields

    def get_empresa(self, obj: Ticket) -> dict:
        return {
            "id": obj.empresa_id,
            "nombre": obj.empresa.nombre,
            "identificacion": obj.empresa.identificacion,
        }

    def get_modulo(self, obj: Ticket) -> dict:
        return {
            "id": obj.modulo_id,
            "codigo": obj.modulo.codigo,
            "nombre": obj.modulo.nombre,
        }

    def get_creado_por(self, obj: Ticket) -> dict:
        return {
            "id": obj.creado_por_id,
            "nombre": obj.creado_por.nombre,
            "correo": obj.creado_por.correo,
        }

    def get_responsable(self, obj: Ticket) -> dict | None:
        if obj.responsable_id is None or obj.responsable is None:
            return None
        return {
            "id": obj.responsable_id,
            "nombre": obj.responsable.nombre,
            "correo": obj.responsable.correo,
        }


class SupportTicketHistoryItemSerializer(serializers.ModelSerializer):
    """Evento completo del historial (`TicketItem`) para la vista interna de soporte (BE-20, RF8).

    A diferencia del historial del portal del cliente, aquí SÍ se incluyen las
    notas internas (`es_interna=True`), el `actor` y el `responsable_asignado`.
    """

    actor = serializers.SerializerMethodField()
    responsable_asignado = serializers.SerializerMethodField()

    class Meta:
        model = TicketItem
        fields = [
            "id",
            "ticket",
            "actor",
            "tipo_accion",
            "estado_anterior",
            "estado_nuevo",
            "responsable_asignado",
            "es_interna",
            "observaciones",
            "fecha_creacion",
        ]
        read_only_fields = fields

    def get_actor(self, obj: TicketItem) -> dict:
        return {
            "id": obj.actor_id,
            "nombre": obj.actor.nombre,
            "correo": obj.actor.correo,
            "rol": obj.actor.rol,
        }

    def get_responsable_asignado(self, obj: TicketItem) -> dict | None:
        if obj.responsable_asignado_id is None or obj.responsable_asignado is None:
            return None
        return {
            "id": obj.responsable_asignado_id,
            "nombre": obj.responsable_asignado.nombre,
            "correo": obj.responsable_asignado.correo,
            "rol": obj.responsable_asignado.rol,
        }


class SupportTicketDetailSerializer(serializers.ModelSerializer):
    """Detalle completo de un `Ticket` para la consola interna de soporte (BE-20, RF8).

    Expone los 20 campos de dominio del modelo `Ticket` junto con el `historial`
    completo ordenado cronológicamente de forma ascendente (incluyendo `es_interna=True`).
    """

    empresa = serializers.SerializerMethodField()
    modulo = serializers.SerializerMethodField()
    creado_por = serializers.SerializerMethodField()
    registrado_por_agente = serializers.SerializerMethodField()
    responsable = serializers.SerializerMethodField()
    historial = SupportTicketHistoryItemSerializer(many=True, read_only=True)

    class Meta:
        model = Ticket
        fields = [
            "id",
            "radicado",
            "empresa",
            "creado_por",
            "registrado_por_agente",
            "modulo",
            "pestana_o_documento",
            "asunto",
            "descripcion",
            "mensaje_error",
            "prioridad",
            "estado",
            "clasificacion",
            "canal_origen",
            "responsable",
            "comentario_solucion",
            "motivo_no_procedente",
            "fecha_creacion",
            "fecha_actualizacion",
            "fecha_resolucion",
            "historial",
        ]
        read_only_fields = fields

    def get_empresa(self, obj: Ticket) -> dict:
        return {
            "id": obj.empresa_id,
            "nombre": obj.empresa.nombre,
            "identificacion": obj.empresa.identificacion,
        }

    def get_modulo(self, obj: Ticket) -> dict:
        return {
            "id": obj.modulo_id,
            "codigo": obj.modulo.codigo,
            "nombre": obj.modulo.nombre,
        }

    def get_creado_por(self, obj: Ticket) -> dict:
        return {
            "id": obj.creado_por_id,
            "nombre": obj.creado_por.nombre,
            "correo": obj.creado_por.correo,
        }

    def get_registrado_por_agente(self, obj: Ticket) -> dict | None:
        if obj.registrado_por_agente_id is None or obj.registrado_por_agente is None:
            return None
        return {
            "id": obj.registrado_por_agente_id,
            "nombre": obj.registrado_por_agente.nombre,
            "correo": obj.registrado_por_agente.correo,
        }

    def get_responsable(self, obj: Ticket) -> dict | None:
        if obj.responsable_id is None or obj.responsable is None:
            return None
        return {
            "id": obj.responsable_id,
            "nombre": obj.responsable.nombre,
            "correo": obj.responsable.correo,
        }


class SupportExternalTicketCreateSerializer(serializers.Serializer):
    """Serializer de entrada para registrar tickets recibidos por canales externos (`POST /api/v1/support/tickets/`, BE-20, RF9)."""

    empresa_id = serializers.IntegerField(required=True)
    creado_por_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
    )
    modulo_id = serializers.IntegerField(required=True)
    pestana_o_documento = serializers.CharField(
        required=True,
        allow_blank=False,
        max_length=255,
    )
    asunto = serializers.CharField(
        required=True,
        allow_blank=False,
        max_length=255,
    )
    descripcion = serializers.CharField(
        required=True,
        allow_blank=False,
    )
    mensaje_error = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
    )
    prioridad = serializers.ChoiceField(
        choices=PrioridadChoices.choices,
        required=True,
    )
    canal_origen = serializers.ChoiceField(
        choices=CanalOrigenChoices.choices,
        required=True,
    )

    def validate_mensaje_error(self, value):
        return value or ""
