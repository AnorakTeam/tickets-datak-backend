"""Chatbot messaging endpoint: `POST /api/v1/chatbot/mensajes/` (Task BE-15, RF3, RF6, User Story #1).

Exposes a single POST endpoint protected by `IsAuthenticated` + `IsClientUser`.

Two dialogue modes are handled transparently:

1. **Incident-reporting flow (RF3):** Routes turns through the BE-14
   `IncidentReportStateMachine`.  When the client confirms at the
   CONFIRMATION state the ticket is created via `TicketCreationService`
   with `canal_origen='Chatbot'`, linked to the authenticated user and
   their company.  The generated `radicado` is returned and the session
   is cleared.

2. **Status-inquiry flow (RF6):** Detected when the user is *not* in an
   active reporting session and their message either contains a radicado
   pattern (`TK-YYYY-NNNNNN`) or matches status-inquiry keywords.
   - Specific radicado → returns `estado` + `comentario_solucion` for that
     ticket, filtered strictly by the user's company (returns a safe "not
     found" response if the radicado belongs to another company).
   - General inquiry (no radicado) → lists active tickets for the user's
     company with their current status and solution comment.

Multi-tenancy (RNF2): the client's company is **always** taken from
`request.user.empresa`, never from the request payload.
"""

from __future__ import annotations

import logging
import re

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.companies.permissions import IsClientUser
from apps.tickets.chatbot import (
    ChatbotResponseType,
    ChatbotState,
    IncidentReportStateMachine,
)
from apps.tickets.models import EstadoChoices, Ticket

logger = logging.getLogger(__name__)

# Radicado pattern: TK-YYYY-NNNNNN
_RADICADO_RE = re.compile(r"\bTK-\d{4}-\d{6}\b", re.IGNORECASE)

# Keywords that signal a general status inquiry (Spanish)
_STATUS_KEYWORDS: frozenset[str] = frozenset(
    {
        "estado",
        "estados",
        "status",
        "consultar",
        "consulta",
        "mis tickets",
        "mis incidencias",
        "ver tickets",
        "ver incidencias",
        "listar tickets",
        "listar incidencias",
        "tickets activos",
        "incidencias activas",
        "seguimiento",
        "how is",
        "como va",
        "como esta",
        "cómo va",
        "cómo está",
        "ticket",
        "incidencia",
        "radicado",
        "radicados",
    }
)

# "Active" statuses for general listing (Resuelto/No procedente are closed)
_ACTIVE_STATUSES: tuple[str, ...] = (
    EstadoChoices.ABIERTO,
    EstadoChoices.EN_GESTION,
)


def _extract_radicado(text: str) -> str | None:
    """Return the first radicado found in *text*, or None."""
    match = _RADICADO_RE.search(text)
    return match.group(0).upper() if match else None


def _looks_like_status_inquiry(text: str, normalized: str) -> bool:
    """Return True when the message appears to be a status/inquiry question."""
    # Direct radicado present
    if _extract_radicado(text):
        return True
    # Keyword match
    for kw in _STATUS_KEYWORDS:
        if kw in normalized:
            return True
    return False


def _build_ticket_status_response(ticket: Ticket) -> str:
    """Format a human-readable status paragraph for a single ticket."""
    solucion = ticket.comentario_solucion.strip() if ticket.comentario_solucion else ""
    lines = [
        f"**Radicado:** {ticket.radicado}",
        f"**Asunto:** {ticket.asunto}",
        f"**Estado:** {ticket.estado}",
        f"**Prioridad:** {ticket.prioridad}",
        f"**Canal:** {ticket.canal_origen}",
        f"**Fecha de creación:** {ticket.fecha_creacion.strftime('%Y-%m-%d %H:%M') if ticket.fecha_creacion else 'N/A'}",
    ]
    if solucion:
        lines.append(f"**Comentario de solución:** {solucion}")
    if ticket.motivo_no_procedente and ticket.motivo_no_procedente.strip():
        lines.append(f"**Motivo no procedente:** {ticket.motivo_no_procedente.strip()}")
    return "\n".join(lines)


class ChatbotMensajesView(APIView):
    """`POST /api/v1/chatbot/mensajes/` — chatbot messaging endpoint (BE-15, RF3, RF6).

    Request body:
        {
            "mensaje": "<non-empty string>",
            "session_id": "<optional string; defaults to user-scoped default>"
        }

    Response (200 OK):
        {
            "session_id": str,
            "tipo_respuesta": str,   // PREGUNTA | RESUMEN | TICKET_CREADO | ESTADO_TICKET | INFO | ERROR
            "mensaje": str,
            "estado_actual": str,
            "campos_recolectados": dict,
            "radicado": str | null,  // present on TICKET_CREADO
            "ticket_id": int | null, // present on TICKET_CREADO
            "opciones": list[str]    // present when options are available
        }

    Authentication: JWT Bearer token (IsAuthenticated + IsClientUser).
    Multi-tenancy: empresa is always resolved from request.user.empresa (RNF2).
    """

    permission_classes = [IsAuthenticated, IsClientUser]

    def post(self, request: Request, *args, **kwargs) -> Response:
        # 1. Validate the incoming payload
        raw_mensaje = request.data.get("mensaje", "")
        if not raw_mensaje or not str(raw_mensaje).strip():
            return Response(
                {
                    "detail": "El campo 'mensaje' es obligatorio y no puede estar vacío.",
                    "tipo_respuesta": ChatbotResponseType.ERROR,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        mensaje_text: str = str(raw_mensaje).strip()

        # Resolve session_id: prefer provided value, fall back to a user-scoped default.
        raw_session = request.data.get("session_id", "")
        session_id: str = (
            str(raw_session).strip()
            if raw_session and str(raw_session).strip()
            else f"default-{request.user.id}"
        )

        # 2. Load the state machine (restores existing session from cache if present)
        try:
            sm = IncidentReportStateMachine(user=request.user, session_id=session_id)
        except (ValueError, AttributeError):
            logger.exception(
                "Error initialising chatbot state machine for user %s", request.user.id
            )
            return Response(
                {
                    "detail": "No se pudo inicializar la sesión de chatbot.",
                    "tipo_respuesta": ChatbotResponseType.ERROR,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 3. Decide routing: status-inquiry vs reporting dialogue
        in_active_reporting = sm.current_state != ChatbotState.INITIAL

        normalized_msg = mensaje_text.lower()

        if not in_active_reporting and _looks_like_status_inquiry(mensaje_text, normalized_msg):
            # ----------------------------------------------------------------
            # RF6: Status inquiry branch
            # ----------------------------------------------------------------
            chatbot_resp = self._handle_status_inquiry(request, mensaje_text)
        else:
            # ----------------------------------------------------------------
            # RF3: Incident-reporting dialogue (delegated to BE-14 state machine)
            # ----------------------------------------------------------------
            try:
                chatbot_resp = sm.process_message(mensaje_text)
            except DjangoValidationError as exc:
                errores = (
                    exc.message_dict
                    if hasattr(exc, "message_dict")
                    else {"non_field_errors": exc.messages}
                )
                logger.exception(
                    "Validation error during chatbot ticket creation for user %s",
                    request.user.id,
                )
                return Response(
                    {
                        "detail": str(exc),
                        "tipo_respuesta": ChatbotResponseType.ERROR,
                        "errors": errores,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            except Exception:
                logger.exception(
                    "Unexpected error in chatbot state machine for user %s",
                    request.user.id,
                )
                return Response(
                    {
                        "detail": "Ocurrió un error inesperado en el chatbot. Por favor intenta de nuevo.",
                        "tipo_respuesta": ChatbotResponseType.ERROR,
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        return Response(chatbot_resp.to_dict(), status=status.HTTP_200_OK)

    # -------------------------------------------------------------------------
    # RF6: Status inquiry helpers
    # -------------------------------------------------------------------------

    def _handle_status_inquiry(self, request: Request, text: str):
        """Handle RF6 status inquiry: specific radicado lookup or general active listing."""

        user = request.user
        empresa_id = user.empresa_id

        # Determine a stable session_id for the response (no active session needed here)
        session_id = f"default-{user.id}"

        radicado = _extract_radicado(text)
        if radicado:
            return self._lookup_specific_radicado(radicado, empresa_id, session_id)
        else:
            return self._list_active_tickets(empresa_id, session_id)

    def _lookup_specific_radicado(self, radicado: str, empresa_id: int, session_id: str):
        """Return status for a specific radicado, filtered by the user's company (RNF2)."""
        from apps.tickets.chatbot import ChatbotResponse

        ticket = (
            Ticket.objects.filter(empresa_id=empresa_id, radicado__iexact=radicado)
            .select_related("modulo")
            .first()
        )

        if ticket is None:
            # Safe 'not found' — never leak cross-company data
            mensaje = (
                f"No se encontró el ticket con radicado **{radicado}** asociado a tu empresa. "
                "Verifica el número e inténtalo de nuevo."
            )
            return ChatbotResponse(
                session_id=session_id,
                tipo_respuesta=ChatbotResponseType.ESTADO_TICKET,
                mensaje=mensaje,
                estado_actual=ChatbotState.INITIAL,
                campos_recolectados={},
                radicado=None,
            )

        body = _build_ticket_status_response(ticket)
        mensaje = f"Aquí está el estado actual de tu ticket:\n\n{body}"
        return ChatbotResponse(
            session_id=session_id,
            tipo_respuesta=ChatbotResponseType.ESTADO_TICKET,
            mensaje=mensaje,
            estado_actual=ChatbotState.INITIAL,
            campos_recolectados={
                "radicado": ticket.radicado,
                "estado": ticket.estado,
                "comentario_solucion": ticket.comentario_solucion or "",
            },
            radicado=ticket.radicado,
        )

    def _list_active_tickets(self, empresa_id: int, session_id: str):
        """Return a summary of all active (Abierto/En gestión) tickets for the company."""
        from apps.tickets.chatbot import ChatbotResponse

        tickets = (
            Ticket.objects.filter(empresa_id=empresa_id, estado__in=_ACTIVE_STATUSES)
            .select_related("modulo")
            .order_by("-fecha_creacion")
        )

        if not tickets.exists():
            mensaje = (
                "No tienes tickets activos en este momento. "
                "Si deseas reportar una nueva incidencia, descríbeme el problema."
            )
            return ChatbotResponse(
                session_id=session_id,
                tipo_respuesta=ChatbotResponseType.INFO,
                mensaje=mensaje,
                estado_actual=ChatbotState.INITIAL,
                campos_recolectados={},
            )

        lines = ["Estos son tus tickets activos:\n"]
        tickets_summary = []
        for t in tickets:
            block = _build_ticket_status_response(t)
            lines.append(block)
            lines.append("")  # blank separator
            tickets_summary.append(
                {
                    "radicado": t.radicado,
                    "asunto": t.asunto,
                    "modulo": t.modulo.nombre if t.modulo else "",
                    "estado": t.estado,
                    "prioridad": t.prioridad,
                    "comentario_solucion": t.comentario_solucion or "",
                }
            )

        mensaje = "\n".join(lines).strip()
        return ChatbotResponse(
            session_id=session_id,
            tipo_respuesta=ChatbotResponseType.ESTADO_TICKET,
            mensaje=mensaje,
            estado_actual=ChatbotState.INITIAL,
            campos_recolectados={"tickets_activos": tickets_summary},
            opciones=[t.radicado for t in tickets],
        )
