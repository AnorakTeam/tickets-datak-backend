"""Conversational session state machine for incident reporting (Task BE-14, User Story #1).

This module implements the multi-turn conversational dialogue state machine guiding
client users through reporting a technical incident in four sequential steps:
1. INITIAL: Captures problem description, extracts entity keywords, transitions to ASK_MODULE.
2. ASK_MODULE: Queries active modules for the client's company, validates selection,
   transitions to ASK_PRIORITY.
3. ASK_PRIORITY: Validates priority (Baja, Media, Alta, Crítica), transitions to CONFIRMATION.
4. CONFIRMATION: Displays collected summary, asks for 'Confirmar' or 'Cancelar'.
   - 'Confirmar': Creates the ticket via TicketCreationService, resets session.
   - 'Cancelar': Abort flow without creating ticket, resets session.

Implements multi-tenant isolation (RNF2) and session persistence across turns
backed by Django's cache layer.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from django.core.cache import cache as default_django_cache

from apps.companies.models import ModuloContratado, Usuario
from apps.tickets.models import CanalOrigenChoices, PrioridadChoices, Ticket
from apps.tickets.services import TicketCreationService

logger = logging.getLogger(__name__)

# Spanish stopwords for incident keyword extraction
SPANISH_STOPWORDS: set[str] = {
    "a",
    "al",
    "algo",
    "algun",
    "alguna",
    "algunas",
    "algunos",
    "ante",
    "antes",
    "aquel",
    "aquella",
    "aquellas",
    "aquello",
    "aquellos",
    "aqui",
    "aquí",
    "asi",
    "así",
    "aun",
    "aún",
    "aunque",
    "bien",
    "buen",
    "buena",
    "buenas",
    "bueno",
    "buenos",
    "cada",
    "caso",
    "como",
    "cómo",
    "con",
    "contra",
    "cual",
    "cuál",
    "cuales",
    "cuáles",
    "cuando",
    "cuándo",
    "de",
    "del",
    "desde",
    "donde",
    "dónde",
    "durante",
    "e",
    "el",
    "ella",
    "ellas",
    "ello",
    "ellos",
    "en",
    "entre",
    "era",
    "erais",
    "eran",
    "eras",
    "eres",
    "es",
    "esa",
    "esas",
    "ese",
    "eso",
    "esos",
    "esta",
    "estaba",
    "estabais",
    "estaban",
    "estabas",
    "estad",
    "estada",
    "estadas",
    "estado",
    "estados",
    "estais",
    "estamos",
    "estan",
    "están",
    "estar",
    "estará",
    "estas",
    "este",
    "esto",
    "estos",
    "estoy",
    "estuve",
    "estuviera",
    "estuviese",
    "estuvo",
    "favor",
    "fue",
    "fuera",
    "fueron",
    "fuese",
    "fui",
    "fuimos",
    "ha",
    "habeis",
    "habéis",
    "haber",
    "habia",
    "había",
    "habiais",
    "habíais",
    "habian",
    "habían",
    "habias",
    "habías",
    "habida",
    "habidas",
    "habido",
    "habidos",
    "habiendo",
    "habla",
    "hablan",
    "hacer",
    "hacia",
    "hago",
    "han",
    "has",
    "hasta",
    "hay",
    "haya",
    "hayamos",
    "hayan",
    "hayas",
    "he",
    "hecho",
    "hemos",
    "hola",
    "hube",
    "hubiera",
    "hubiese",
    "hubo",
    "la",
    "las",
    "le",
    "les",
    "lo",
    "los",
    "mas",
    "más",
    "me",
    "mi",
    "mía",
    "mías",
    "mientras",
    "mio",
    "mío",
    "míos",
    "mis",
    "mismo",
    "mismos",
    "momento",
    "mucha",
    "muchas",
    "mucho",
    "muchos",
    "muy",
    "nada",
    "ni",
    "no",
    "nos",
    "nosotras",
    "nosotros",
    "nuestra",
    "nuestras",
    "nuestro",
    "nuestros",
    "o",
    "os",
    "otra",
    "otras",
    "otro",
    "otros",
    "para",
    "parece",
    "pero",
    "poco",
    "por",
    "porque",
    "porqué",
    "porfavor",
    "que",
    "qué",
    "quien",
    "quién",
    "quienes",
    "quiénes",
    "se",
    "sea",
    "seamos",
    "sean",
    "seas",
    "ser",
    "será",
    "serán",
    "serás",
    "seré",
    "seréis",
    "seremos",
    "sería",
    "si",
    "sí",
    "sido",
    "siempre",
    "siendo",
    "sin",
    "sobre",
    "sois",
    "solamente",
    "solo",
    "sólo",
    "somos",
    "son",
    "soy",
    "su",
    "sus",
    "suya",
    "suyas",
    "suyo",
    "suyos",
    "tal",
    "tambien",
    "también",
    "tanto",
    "te",
    "tendrá",
    "tendrán",
    "tendrás",
    "tendré",
    "tendréis",
    "tendremos",
    "tendría",
    "tenga",
    "tengamos",
    "tengan",
    "tengas",
    "tengo",
    "tenia",
    "tenía",
    "teniais",
    "teníais",
    "tenian",
    "tenían",
    "tenias",
    "tenías",
    "tenida",
    "tenidas",
    "tenido",
    "tenidos",
    "teniendo",
    "tenéis",
    "tenemos",
    "tener",
    "ti",
    "tiene",
    "tienen",
    "tienes",
    "toda",
    "todas",
    "todo",
    "todos",
    "tras",
    "tu",
    "tú",
    "tus",
    "tuve",
    "tuviera",
    "tuviese",
    "tuvo",
    "tuya",
    "tuyas",
    "tuyo",
    "tuyos",
    "un",
    "una",
    "unas",
    "uno",
    "unos",
    "va",
    "vais",
    "vamos",
    "van",
    "varias",
    "varios",
    "vaya",
    "vayan",
    "ve",
    "ver",
    "vez",
    "vosotras",
    "vosotros",
    "vuestra",
    "vuestras",
    "vuestro",
    "vuestros",
    "y",
    "ya",
    "yo",
}


def normalize_text(text: str) -> str:
    """Normalize unicode characters removing diacritics/accents and trimming whitespace."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).strip()


def extract_keywords(text: str) -> list[str]:
    """Extract significant keywords from user input removing stop words and punctuation."""
    words = re.findall(r"[a-zA-ZáéíóúÁÉÍÓÚñÑ0-9]+", text)
    keywords: list[str] = []
    seen: set[str] = set()

    for word in words:
        lower_word = word.lower()
        norm_word = normalize_text(lower_word)
        if len(norm_word) >= 3 and norm_word not in SPANISH_STOPWORDS:
            if lower_word not in seen:
                seen.add(lower_word)
                keywords.append(lower_word)

    return keywords


def extract_asunto(text: str, max_length: int = 100) -> str:
    """Derive a concise subject from the problem description."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "Incidencia reportada por Chatbot"

    first_line = lines[0]
    sentence = first_line.split(".")[0].strip()
    candidate = sentence if sentence else first_line

    if len(candidate) > max_length:
        return candidate[:max_length].rstrip() + "..."
    return candidate


class ChatbotState(str, Enum):
    """Conversational dialogue states for incident reporting."""

    INITIAL = "INITIAL"
    ASK_MODULE = "ASK_MODULE"
    ASK_PRIORITY = "ASK_PRIORITY"
    CONFIRMATION = "CONFIRMATION"


class ChatbotResponseType(str, Enum):
    """Allowed chatbot response types matching the frontend API contract."""

    PREGUNTA = "PREGUNTA"
    RESUMEN = "RESUMEN"
    TICKET_CREADO = "TICKET_CREADO"
    ESTADO_TICKET = "ESTADO_TICKET"
    INFO = "INFO"
    ERROR = "ERROR"


@dataclass
class ChatbotResponse:
    """Data transfer object representing a turn response from the chatbot."""

    session_id: str
    tipo_respuesta: str
    mensaje: str
    estado_actual: str
    campos_recolectados: dict[str, Any] = field(default_factory=dict)
    radicado: str | None = None
    ticket_id: int | None = None
    opciones: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert the response object to a standard serializable dictionary."""
        payload: dict[str, Any] = {
            "session_id": self.session_id,
            "tipo_respuesta": self.tipo_respuesta,
            "mensaje": self.mensaje,
            "estado_actual": self.estado_actual,
            "campos_recolectados": self.campos_recolectados,
        }
        if self.radicado is not None:
            payload["radicado"] = self.radicado
        if self.ticket_id is not None:
            payload["ticket_id"] = self.ticket_id
        if self.opciones:
            payload["opciones"] = self.opciones
        return payload


class IncidentReportStateMachine:
    """Conversational state machine orchestrating the incident reporting flow (User Story #1).

    Maintains sequential step progression:
    - INITIAL -> ASK_MODULE -> ASK_PRIORITY -> CONFIRMATION -> (Ticket Created / Cancelled).
    Persists session data and handles re-prompting on invalid inputs.
    """

    CACHE_KEY_PREFIX = "chatbot_session"
    DEFAULT_TIMEOUT_SECONDS = 3600  # 1 hour

    ALLOWED_PRIORITIES: dict[str, str] = {
        "baja": PrioridadChoices.BAJA,
        "media": PrioridadChoices.MEDIA,
        "alta": PrioridadChoices.ALTA,
        "critica": PrioridadChoices.CRITICA,
    }

    CONFIRM_KEYWORDS: set[str] = {
        "confirmar",
        "confirmo",
        "confirm",
        "si, confirmar",
        "sí, confirmar",
    }
    CANCEL_KEYWORDS: set[str] = {"cancelar", "cancelo", "cancel", "no, cancelar", "abortar"}

    def __init__(
        self,
        user: Usuario,
        session_id: str,
        cache_backend: Any = None,
        timeout: int | None = None,
    ) -> None:
        if not user or not getattr(user, "is_authenticated", False):
            raise ValueError("A valid authenticated Usuario instance is required.")
        if not getattr(user, "empresa_id", None):
            raise ValueError("The authenticated user must belong to an Empresa (RNF2).")
        if not session_id or not str(session_id).strip():
            raise ValueError("A non-empty session_id string is required.")

        self.user = user
        self.session_id = str(session_id).strip()
        self.cache = cache_backend if cache_backend is not None else default_django_cache
        self.timeout = timeout or self.DEFAULT_TIMEOUT_SECONDS

        self.state: str = ChatbotState.INITIAL
        self.session_data: dict[str, Any] = {}
        self._load_session()

    @property
    def current_state(self) -> str:
        """Return the current active conversational state."""
        return self.state

    @property
    def context(self) -> dict[str, Any]:
        """Return the collected fields dictionary."""
        return self.session_data

    def _get_cache_key(self) -> str:
        """Generate a tenant-isolated cache key for this user session (RNF2)."""
        safe_session = re.sub(r"[^a-zA-Z0-9_\-]", "_", self.session_id)
        return f"{self.CACHE_KEY_PREFIX}:{self.user.empresa_id}:{self.user.id}:{safe_session}"

    def _load_session(self) -> None:
        """Load session state and data from cache if present."""
        cached_payload = self.cache.get(self._get_cache_key())
        if isinstance(cached_payload, dict):
            # Verify tenant isolation and owner consistency
            if (
                cached_payload.get("empresa_id") == self.user.empresa_id
                and cached_payload.get("user_id") == self.user.id
            ):
                self.state = cached_payload.get("state", ChatbotState.INITIAL)
                self.session_data = cached_payload.get("data", {})
                return

        self.state = ChatbotState.INITIAL
        self.session_data = {}

    def _save_session(self) -> None:
        """Persist current state and data into the cache backend."""
        payload = {
            "session_id": self.session_id,
            "empresa_id": self.user.empresa_id,
            "user_id": self.user.id,
            "state": self.state,
            "data": self.session_data,
        }
        self.cache.set(self._get_cache_key(), payload, timeout=self.timeout)

    def clear_session(self) -> None:
        """Clear the session from cache and reset instance memory."""
        self.cache.delete(self._get_cache_key())
        self.state = ChatbotState.INITIAL
        self.session_data = {}

    def reset(self) -> None:
        """Alias for clear_session."""
        self.clear_session()

    def process_message(self, message: str) -> ChatbotResponse:
        """Process an incoming conversational message according to the current state."""
        cleaned_text = (message or "").strip()

        if self.state == ChatbotState.INITIAL:
            return self._handle_initial(cleaned_text)
        elif self.state == ChatbotState.ASK_MODULE:
            return self._handle_ask_module(cleaned_text)
        elif self.state == ChatbotState.ASK_PRIORITY:
            return self._handle_ask_priority(cleaned_text)
        elif self.state == ChatbotState.CONFIRMATION:
            return self._handle_confirmation(cleaned_text)
        else:
            # Fallback if state got corrupted
            self.clear_session()
            return self._handle_initial(cleaned_text)

    # -------------------------------------------------------------------------
    # State Handlers
    # -------------------------------------------------------------------------

    def _handle_initial(self, text: str) -> ChatbotResponse:
        """State 1 (INITIAL): Capture problem description, extract keywords, ask for module."""
        if not text:
            return ChatbotResponse(
                session_id=self.session_id,
                tipo_respuesta=ChatbotResponseType.PREGUNTA,
                mensaje="Por favor describe detalladamente el inconveniente que estás experimentando.",
                estado_actual=ChatbotState.INITIAL,
                campos_recolectados={},
            )

        # Store raw description and extract entity keywords & subject
        raw_description = text
        keywords = extract_keywords(raw_description)
        asunto = extract_asunto(raw_description)

        self.session_data = {
            "raw_description": raw_description,
            "descripcion": raw_description,
            "asunto": asunto,
            "keywords": keywords,
        }

        # Query active modules for the user's company (RNF2 & BE-10)
        active_modules = list(
            ModuloContratado.objects.filter(
                empresa_id=self.user.empresa_id,
                activo=True,
            ).order_by("nombre", "id")
        )

        if not active_modules:
            # Company has no contracted or active modules
            self.clear_session()
            return ChatbotResponse(
                session_id=self.session_id,
                tipo_respuesta=ChatbotResponseType.ERROR,
                mensaje="Su empresa no cuenta actualmente con módulos contratados activos para radicar incidencias. Por favor contacte al administrador.",
                estado_actual=ChatbotState.INITIAL,
                campos_recolectados={},
            )

        # Transition to ASK_MODULE
        self.state = ChatbotState.ASK_MODULE
        self._save_session()

        module_options = [f"{m.nombre} ({m.codigo})" for m in active_modules]
        prompt = self._format_ask_module_prompt(active_modules)

        return ChatbotResponse(
            session_id=self.session_id,
            tipo_respuesta=ChatbotResponseType.PREGUNTA,
            mensaje=prompt,
            estado_actual=ChatbotState.ASK_MODULE,
            campos_recolectados=dict(self.session_data),
            opciones=module_options,
        )

    def _handle_ask_module(self, text: str) -> ChatbotResponse:
        """State 2 (ASK_MODULE): Validate module selection against active company modules."""
        active_modules = list(
            ModuloContratado.objects.filter(
                empresa_id=self.user.empresa_id,
                activo=True,
            ).order_by("nombre", "id")
        )

        selected_module = self._match_module(text, active_modules)

        if selected_module is None:
            # Re-prompt in same state on invalid input
            prompt = self._format_invalid_module_prompt(text, active_modules)
            module_options = [f"{m.nombre} ({m.codigo})" for m in active_modules]
            return ChatbotResponse(
                session_id=self.session_id,
                tipo_respuesta=ChatbotResponseType.ERROR,
                mensaje=prompt,
                estado_actual=ChatbotState.ASK_MODULE,
                campos_recolectados=dict(self.session_data),
                opciones=module_options,
            )

        # Store validated module
        self.session_data["modulo_id"] = selected_module.id
        self.session_data["modulo_nombre"] = selected_module.nombre
        self.session_data["modulo_codigo"] = selected_module.codigo

        # Transition to ASK_PRIORITY
        self.state = ChatbotState.ASK_PRIORITY
        self._save_session()

        priority_options = ["Baja", "Media", "Alta", "Crítica"]
        prompt = (
            f"Módulo seleccionado: **{selected_module.nombre}**.\n\n"
            "¿Cuál es el nivel de urgencia o prioridad de esta incidencia?\n"
            "Opciones permitidas:\n"
            "• **Baja**\n"
            "• **Media**\n"
            "• **Alta**\n"
            "• **Crítica**"
        )

        return ChatbotResponse(
            session_id=self.session_id,
            tipo_respuesta=ChatbotResponseType.PREGUNTA,
            mensaje=prompt,
            estado_actual=ChatbotState.ASK_PRIORITY,
            campos_recolectados=dict(self.session_data),
            opciones=priority_options,
        )

    def _handle_ask_priority(self, text: str) -> ChatbotResponse:
        """State 3 (ASK_PRIORITY): Validate urgency level (case-insensitive) and transition to CONFIRMATION."""
        normalized_input = normalize_text(text).lower()
        matched_priority = self.ALLOWED_PRIORITIES.get(normalized_input)

        if matched_priority is None:
            # Invalid input: stay in ASK_PRIORITY and re-prompt
            prompt = (
                f"'{text}' no es un nivel de prioridad válido.\n"
                "Por favor selecciona una de las siguientes opciones exactas:\n"
                "• **Baja**\n"
                "• **Media**\n"
                "• **Alta**\n"
                "• **Crítica**"
            )
            return ChatbotResponse(
                session_id=self.session_id,
                tipo_respuesta=ChatbotResponseType.ERROR,
                mensaje=prompt,
                estado_actual=ChatbotState.ASK_PRIORITY,
                campos_recolectados=dict(self.session_data),
                opciones=["Baja", "Media", "Alta", "Crítica"],
            )

        # Store validated priority
        self.session_data["prioridad"] = matched_priority

        # Transition to CONFIRMATION
        self.state = ChatbotState.CONFIRMATION
        self._save_session()

        summary_prompt = self._format_confirmation_prompt(self.session_data)

        return ChatbotResponse(
            session_id=self.session_id,
            tipo_respuesta=ChatbotResponseType.RESUMEN,
            mensaje=summary_prompt,
            estado_actual=ChatbotState.CONFIRMATION,
            campos_recolectados=dict(self.session_data),
            opciones=["Confirmar", "Cancelar"],
        )

    def _handle_confirmation(self, text: str) -> ChatbotResponse:
        """State 4 (CONFIRMATION): Handle final confirmation or cancellation."""
        normalized_input = normalize_text(text).lower()

        # Check for 'Confirmar'
        if normalized_input in self.CONFIRM_KEYWORDS or normalized_input.startswith("confirm"):
            return self._proceed_ticket_creation()

        # Check for 'Cancelar'
        if normalized_input in self.CANCEL_KEYWORDS or normalized_input.startswith("cancel"):
            return self._abort_ticket_creation()

        # Invalid option: keep state in CONFIRMATION and re-prompt
        prompt = (
            "Opción no reconocida. Por favor responde únicamente:\n"
            "• '**Confirmar**' para registrar la incidencia.\n"
            "• '**Cancelar**' para descartar el reporte sin crear el ticket."
        )
        return ChatbotResponse(
            session_id=self.session_id,
            tipo_respuesta=ChatbotResponseType.ERROR,
            mensaje=prompt,
            estado_actual=ChatbotState.CONFIRMATION,
            campos_recolectados=dict(self.session_data),
            opciones=["Confirmar", "Cancelar"],
        )

    # -------------------------------------------------------------------------
    # Confirmation Actions
    # -------------------------------------------------------------------------

    def _proceed_ticket_creation(self) -> ChatbotResponse:
        """Invoke TicketCreationService, reset the session, and return success response."""
        modulo_id = self.session_data.get("modulo_id")
        raw_description = self.session_data.get("raw_description", "")
        asunto = self.session_data.get("asunto", "Incidencia reportada por Chatbot")
        prioridad = self.session_data.get("prioridad", PrioridadChoices.MEDIA)

        ticket: Ticket = TicketCreationService.create_ticket(
            creado_por=self.user,
            empresa=self.user.empresa,
            modulo_id=modulo_id,
            pestana_o_documento="Chatbot / Asistente Virtual",
            asunto=asunto,
            descripcion=raw_description,
            prioridad=prioridad,
            canal_origen=CanalOrigenChoices.CHATBOT,
        )

        radicado = ticket.radicado
        ticket_id = ticket.id

        # Clear session completely
        self.clear_session()

        success_message = (
            f"He creado tu ticket exitosamente con el radicado **{radicado}**.\n"
            "Nuestro equipo de soporte ya fue notificado y se ha enviado un comprobante a tu correo."
        )

        return ChatbotResponse(
            session_id=self.session_id,
            tipo_respuesta=ChatbotResponseType.TICKET_CREADO,
            mensaje=success_message,
            estado_actual=ChatbotState.INITIAL,
            radicado=radicado,
            ticket_id=ticket_id,
            campos_recolectados={},
        )

    def _abort_ticket_creation(self) -> ChatbotResponse:
        """Abort conversational flow without creating any ticket and reset session."""
        self.clear_session()

        cancellation_message = (
            "La creación del ticket ha sido cancelada exitosamente.\n"
            "No se ha generado ningún radicado y tu sesión ha sido reiniciada. ¿En qué más puedo ayudarte?"
        )

        return ChatbotResponse(
            session_id=self.session_id,
            tipo_respuesta=ChatbotResponseType.INFO,
            mensaje=cancellation_message,
            estado_actual=ChatbotState.INITIAL,
            campos_recolectados={},
        )

    # -------------------------------------------------------------------------
    # Helper Formatters & Matchers
    # -------------------------------------------------------------------------

    def _match_module(self, text: str, modules: list[ModuloContratado]) -> ModuloContratado | None:
        """Match user text against active company modules by index, code, ID, or name."""
        if not text or not modules:
            return None

        clean_text = text.strip()
        norm_text = normalize_text(clean_text).lower()

        # 1. Match by numeric index in presented list (e.g. '1', '2')
        if clean_text.isdigit():
            idx = int(clean_text)
            if 1 <= idx <= len(modules):
                return modules[idx - 1]
            # Match by direct module ID
            for mod in modules:
                if mod.id == idx:
                    return mod

        # 2. Exact match on code (e.g. 'FACTURACION', 'INVENTARIO')
        for mod in modules:
            if normalize_text(mod.codigo).lower() == norm_text:
                return mod

        # 3. Exact match on module name (e.g. 'Facturación Electrónica')
        for mod in modules:
            if normalize_text(mod.nombre).lower() == norm_text:
                return mod

        # 4. Substring / contains match on module name or code
        matches = [
            mod
            for mod in modules
            if norm_text in normalize_text(mod.nombre).lower()
            or norm_text in normalize_text(mod.codigo).lower()
        ]
        if len(matches) == 1:
            return matches[0]

        return None

    def _format_ask_module_prompt(self, modules: list[ModuloContratado]) -> str:
        """Build the module selection prompt in Spanish."""
        lines = [
            "He detectado tu reporte de incidencia. Por favor selecciona el módulo en el que se presentó el inconveniente:\n"
        ]
        for idx, mod in enumerate(modules, start=1):
            lines.append(f"{idx}. **{mod.nombre}** (`{mod.codigo}`)")
        lines.append("\nPuedes responder con el número de la opción o el nombre del módulo.")
        return "\n".join(lines)

    def _format_invalid_module_prompt(self, text: str, modules: list[ModuloContratado]) -> str:
        """Build the re-prompt on invalid module selection in Spanish."""
        lines = [
            f"'{text}' no corresponde a un módulo activo contratado por su empresa.",
            "Por favor selecciona una de las siguientes opciones válidas:\n",
        ]
        for idx, mod in enumerate(modules, start=1):
            lines.append(f"{idx}. **{mod.nombre}** (`{mod.codigo}`)")
        lines.append("\nResponde con el número de la opción o el nombre del módulo.")
        return "\n".join(lines)

    def _format_confirmation_prompt(self, data: dict[str, Any]) -> str:
        """Build the structured summary prompt for final confirmation."""
        raw_description = data.get("raw_description", "")
        keywords = data.get("keywords", [])
        keywords_str = ", ".join(keywords) if keywords else "Ninguna identificada"
        modulo_nombre = data.get("modulo_nombre", "")
        modulo_codigo = data.get("modulo_codigo", "")
        prioridad_val = data.get("prioridad", "Media")
        prioridad_label = "Crítica" if prioridad_val == PrioridadChoices.CRITICA else prioridad_val

        return (
            "Verifica la información antes de radicar el ticket:\n\n"
            f"• **Descripción:** {raw_description}\n"
            f"• **Palabras clave:** {keywords_str}\n"
            f"• **Módulo:** {modulo_nombre} (`{modulo_codigo}`)\n"
            f"• **Prioridad:** {prioridad_label}\n\n"
            "¿Deseas radicar este ticket? Por favor responde con '**Confirmar**' o '**Cancelar**'."
        )


# Alias for backward and forward compatibility with team conventions
ChatbotStateMachine = IncidentReportStateMachine
