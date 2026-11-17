"""Rutas del API de tickets. Se incluyen bajo `/api/v1/` en config/urls.py."""

from django.urls import path

from apps.tickets.views import (
    ClientTicketDetailView,
    ClientTicketListView,
    SupportTicketDetailView,
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
    # GET y POST /api/v1/support/tickets/ — bandeja unificada (BE-19 RF7) y creación externa (BE-20 RF9).
    path("support/tickets/", SupportTicketInboxView.as_view(), name="support-ticket-inbox"),
    # GET /api/v1/support/tickets/{id}/ — detalle completo por id o radicado (BE-20 RF8).
    path(
        "support/tickets/<str:lookup>/",
        SupportTicketDetailView.as_view(),
        name="support-ticket-detail",
    ),
]
