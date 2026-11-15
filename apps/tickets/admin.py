"""Registro del modelo Ticket en el panel de administración de Django (/admin/).

Sirve para revisar y crear tickets de prueba durante el desarrollo.
"""

from django.contrib import admin

from apps.tickets.models import Ticket


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    # Columnas de la lista de tickets.
    list_display = (
        "radicado",
        "asunto",
        "empresa",
        "estado",
        "prioridad",
        "canal_origen",
        "fecha_creacion",
    )
    # Filtros laterales para ubicar tickets rápido.
    list_filter = ("estado", "prioridad", "canal_origen", "clasificacion", "empresa")
    # Búsqueda por radicado, asunto o correo de quien lo reportó.
    search_fields = ("radicado", "asunto", "creado_por__correo")
    # Las fechas automáticas no se editan a mano.
    readonly_fields = ("fecha_creacion", "fecha_actualizacion")
    # Carga empresa, módulo y usuarios en la misma consulta (más rápido).
    list_select_related = ("empresa", "modulo", "creado_por")
