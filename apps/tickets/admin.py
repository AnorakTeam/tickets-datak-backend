"""Registro de los modelos de `tickets` en el panel de administración de Django (/admin/).

Sirve para revisar y crear tickets de prueba durante el desarrollo, y para
consultar (solo leer) el historial de cada ticket.
"""

from django.contrib import admin

from apps.tickets.models import Ticket, TicketItem


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


@admin.register(TicketItem)
class TicketItemAdmin(admin.ModelAdmin):
    """Admin del historial: se puede consultar, pero no editar ni borrar (RNF5).

    Desde aquí sí se puede agregar un registro nuevo para pruebas; lo que está
    bloqueado es cambiar o eliminar los que ya existen.
    """

    list_display = (
        "ticket",
        "tipo_accion",
        "estado_anterior",
        "estado_nuevo",
        "actor",
        "es_interna",
        "fecha_creacion",
    )
    list_filter = ("tipo_accion", "es_interna")
    search_fields = ("ticket__radicado", "observaciones", "actor__correo")
    list_select_related = ("ticket", "actor")

    def has_change_permission(self, request, obj=None):
        # Oculta el botón "Guardar" en registros existentes.
        return False

    def has_delete_permission(self, request, obj=None):
        # Oculta la opción de borrar (individual y masiva).
        return False
