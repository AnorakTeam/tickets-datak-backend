"""Rutas del API de tickets. Se incluyen bajo `/api/v1/` en config/urls.py."""

from django.urls import path

from apps.tickets.views import ClientTicketListView

urlpatterns = [
    # GET /api/v1/client/tickets/ — "Mis tickets" del cliente (BE-12).
    # BE-11 agregará el POST (crear ticket) en esta misma ruta.
    path("client/tickets/", ClientTicketListView.as_view(), name="client-ticket-list"),
]
