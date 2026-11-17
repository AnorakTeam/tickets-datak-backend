"""Rutas del API de tickets. Se incluyen bajo `/api/v1/` en config/urls.py."""

from django.urls import path

from apps.tickets.views import (
    ClientTicketDetailView,
    ClientTicketListView,
    SupportTicketInboxView,
)

urlpatterns = [
    # GET y POST /api/v1/client/tickets/ — "Mis tickets" (BE-12) y creación (BE-11).
    path("client/tickets/", ClientTicketListView.as_view(), name="client-ticket-list"),
    # GET /api/v1/client/tickets/TK-2026-000001/ — detalle de un ticket para el cliente (BE-13).
    path(
        "client/tickets/<str:radicado>/",
        ClientTicketDetailView.as_view(),
        name="client-ticket-detail",
    ),
    # GET /api/v1/support/tickets/ — bandeja unificada de soporte con filtros multi-tenant (BE-19, RF7).
    path("support/tickets/", SupportTicketInboxView.as_view(), name="support-ticket-inbox"),
]
