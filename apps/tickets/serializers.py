"""Serializers de la app `tickets`.

Un serializer convierte un Ticket (objeto de Python) en el JSON que recibe el
frontend, y define exactamente qué campos se exponen.
"""

from rest_framework import serializers

from apps.tickets.models import Ticket, TicketItem


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
