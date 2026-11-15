"""Rutas del API de tickets. Se incluyen bajo `/api/v1/` en config/urls.py."""

from django.urls import path

from apps.tickets.views import ClientTicketDetailView, ClientTicketListView

urlpatterns = [
    # GET /api/v1/client/tickets/ — "Mis tickets" del cliente (BE-12).
    # BE-11 agregará el POST (crear ticket) en esta misma ruta.
    path("client/tickets/", ClientTicketListView.as_view(), name="client-ticket-list"),
    # GET /api/v1/client/tickets/TK-2026-000001/ — detalle de un ticket (BE-13).
    # <str:radicado> toma ese pedazo de la URL y lo pasa a la vista como `radicado`.
    path(
        "client/tickets/<str:radicado>/",
        ClientTicketDetailView.as_view(),
        name="client-ticket-detail",
    ),
]
