"""Serializers de la app `tickets`.

Un serializer convierte un Ticket (objeto de Python) en el JSON que recibe el
frontend, y define exactamente qué campos se exponen.
"""

from rest_framework import serializers

from apps.tickets.models import Ticket


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
