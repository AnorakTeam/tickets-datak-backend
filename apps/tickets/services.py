"""Servicios de dominio de la app `tickets` (tareas BE-08 y BE-09, issues #21 y #22).

Contiene:
- `RadicadoSequenceService`: generador atómico y seguro ante concurrencia
  (`select_for_update`) de números de radicado con formato `TK-AAAA-NNNNNN`,
  reiniciando el contador anual en `000001` cuando cambia el año.
- `TicketEmailService` (`EmailDispatcherService`): servicio de envío de
  comprobante transaccional de recepción de ticket en formato multipart
  (`text/plain` + `text/html`) en español mediante `EmailMultiAlternatives`.
- `TicketCreationService`: servicio transaccional (`transaction.atomic`) que
  valida aislamiento multi-tenant (`empresa_id`), vigencia y pertenencia del
  módulo (`ModuloContratado`), asigna el radicado, crea el `Ticket` en estado
  `Abierto`, registra el primer evento inmutable `TicketItem` (`CREACION`) y
  despacha de forma segura el comprobante por correo electrónico (RF1 Flujo 5.1).
"""

import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from apps.companies.models import Empresa, ModuloContratado, RolChoices, Usuario
from apps.tickets.models import (
    CanalOrigenChoices,
    EstadoChoices,
    PrioridadChoices,
    Ticket,
    TicketItem,
    TicketNotificacion,
    TipoAccionChoices,
)

logger = logging.getLogger(__name__)


class RadicadoSequenceService:
    """Genera radicados únicos consecutivos por año con formato `TK-AAAA-NNNNNN`.

    Utiliza `select_for_update()` dentro de una transacción atómica para bloquear
    a nivel de fila y evitar condiciones de carrera (race conditions) cuando dos
    usuarios reportan tickets al mismo tiempo.
    """

    @classmethod
    @transaction.atomic
    def generate_next_radicado(cls, year: int | None = None) -> str:
        """Calcula y devuelve el siguiente radicado disponible para el año dado.

        Si no se indica `year`, usa el año actual (`timezone.now().year`).
        Cuando comienza un nuevo año sin tickets previos, arranca en `000001`.
        """
        anio = year if year is not None else timezone.now().year
        prefijo = f"TK-{anio}-"

        # Bloqueo a nivel de fila (select_for_update):
        # 1. Bloquea las filas de Empresa en orden determinístico para serializar
        #    incluso el caso en que aún no exista ningún ticket para ese año.
        # 2. Bloquea el último Ticket registrado de ese año para leer su consecutivo.
        list(Empresa.objects.select_for_update().order_by("id").values_list("id", flat=True))

        ultimo_ticket = (
            Ticket.objects.select_for_update()
            .filter(radicado__startswith=prefijo)
            .order_by("-radicado")
            .first()
        )

        if ultimo_ticket is None:
            siguiente_numero = 1
        else:
            consecutivo_actual = int(ultimo_ticket.radicado.split("-")[-1])
            siguiente_numero = consecutivo_actual + 1

        return f"{prefijo}{siguiente_numero:06d}"

    @classmethod
    def get_next_radicado(cls, year: int | None = None) -> str:
        """Alias de `generate_next_radicado` por conveniencia."""
        return cls.generate_next_radicado(year=year)


class TicketEmailService:
    """Despachador de correos transaccionales para comprobantes de tickets (BE-09, RF1).

    Envía un correo multipart (`text/plain` y `text/html`) en español al cliente
    que reportó la incidencia con el radicado, módulo, asunto y fecha/hora de registro.
    Cualquier fallo de renderizado o conexión SMTP se captura y registra en logs
    sin propagar la excepción ni afectar la persistencia del ticket (RF1 Flujo 5.1).
    """

    SUBJECT_TEMPLATE = "[Datak Soporte] Comprobante de radicación {radicado} - {asunto}"
    TXT_TEMPLATE = "tickets/emails/ticket_receipt.txt"
    HTML_TEMPLATE = "tickets/emails/ticket_receipt.html"

    @classmethod
    def send_ticket_receipt(cls, ticket: Ticket) -> bool:
        """Renderiza y envía el comprobante de recepción del ticket al correo del creador.

        Devuelve `True` si el correo fue enviado con éxito, o `False` si ocurrió
        alguna excepción (la cual queda registrada mediante `logger.exception`).
        """
        try:
            fecha_local = (
                timezone.localtime(ticket.fecha_creacion)
                if ticket.fecha_creacion and timezone.is_aware(ticket.fecha_creacion)
                else (ticket.fecha_creacion or timezone.now())
            )
            fecha_formateada = fecha_local.strftime("%Y-%m-%d %H:%M:%S")

            contexto = {
                "ticket": ticket,
                "radicado": ticket.radicado,
                "modulo": ticket.modulo.nombre,
                "asunto": ticket.asunto,
                "pestana_o_documento": ticket.pestana_o_documento,
                "prioridad": ticket.prioridad,
                "estado": ticket.estado,
                "fecha_registro": fecha_formateada,
                "destinatario_nombre": ticket.creado_por.nombre,
                "empresa_nombre": ticket.empresa.nombre,
            }

            cuerpo_texto = render_to_string(cls.TXT_TEMPLATE, contexto)
            cuerpo_html = render_to_string(cls.HTML_TEMPLATE, contexto)
            asunto_correo = cls.SUBJECT_TEMPLATE.format(
                radicado=ticket.radicado,
                asunto=ticket.asunto,
            )

            mensaje = EmailMultiAlternatives(
                subject=asunto_correo,
                body=cuerpo_texto,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[ticket.creado_por.correo],
            )
            mensaje.attach_alternative(cuerpo_html, "text/html")
            mensaje.send(fail_silently=False)
            return True
        except Exception:
            logger.exception(
                "Error al enviar el comprobante de correo para el ticket %s",
                getattr(ticket, "radicado", "desconocido"),
            )
            return False

    CLOSED_SUBJECT_TEMPLATE = "[Datak Soporte] {titulo}"
    CLOSED_TXT_TEMPLATE = "tickets/emails/ticket_closed.txt"
    CLOSED_HTML_TEMPLATE = "tickets/emails/ticket_closed.html"

    @classmethod
    def send_ticket_closed_notification(
        cls, ticket: Ticket, notificacion: TicketNotificacion | None = None
    ) -> bool:
        """Envía correo informativo de resolución o no procedencia al creador del ticket.

        Captura cualquier fallo para no interrumpir el flujo transaccional.
        """
        try:
            destinatario = ticket.creado_por
            if not destinatario or not destinatario.correo:
                return False

            fecha_resolucion = (
                timezone.localtime(ticket.fecha_resolucion)
                if ticket.fecha_resolucion and timezone.is_aware(ticket.fecha_resolucion)
                else (ticket.fecha_resolucion or timezone.now())
            )
            fecha_formateada = fecha_resolucion.strftime("%Y-%m-%d %H:%M:%S")

            es_resuelto = ticket.estado == EstadoChoices.RESUELTO
            titulo = (
                notificacion.titulo
                if notificacion
                else f"Ticket {ticket.get_estado_display()}: {ticket.radicado}"
            )

            contexto = {
                "ticket": ticket,
                "notificacion": notificacion,
                "radicado": ticket.radicado,
                "modulo": ticket.modulo.nombre if ticket.modulo else "N/A",
                "asunto": ticket.asunto,
                "estado": ticket.get_estado_display(),
                "es_resuelto": es_resuelto,
                "comentario_solucion": ticket.comentario_solucion or "",
                "motivo_no_procedente": ticket.motivo_no_procedente or "",
                "fecha_resolucion": fecha_formateada,
                "destinatario_nombre": destinatario.nombre,
                "empresa_nombre": ticket.empresa.nombre,
                "titulo": titulo,
            }

            cuerpo_texto = render_to_string(cls.CLOSED_TXT_TEMPLATE, contexto)
            cuerpo_html = render_to_string(cls.CLOSED_HTML_TEMPLATE, contexto)
            asunto_correo = cls.CLOSED_SUBJECT_TEMPLATE.format(titulo=titulo)

            mensaje = EmailMultiAlternatives(
                subject=asunto_correo,
                body=cuerpo_texto,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[destinatario.correo],
            )
            mensaje.attach_alternative(cuerpo_html, "text/html")
            mensaje.send(fail_silently=False)
            return True
        except Exception:
            logger.exception(
                "Error al enviar notificación de cierre de ticket por correo para %s",
                getattr(ticket, "radicado", "desconocido"),
            )
            return False


# Alias para compatibilidad con distintos nombres de importación.
EmailDispatcherService = TicketEmailService


class NotificationService:
    """Servicio de dominio para generación de notificaciones internas y por correo (BE-23, RF16).

    Crea registros en el modelo `TicketNotificacion` para el creador del ticket cuando este
    pasa a un estado de cierre ('Resuelto' o 'No procedente'), y dispara el correo transaccional
    informativo de forma desacoplada y segura.
    """

    @classmethod
    def notify_ticket_closed(cls, ticket: Ticket) -> TicketNotificacion | None:
        """Crea la notificación para el usuario creador y despacha el correo transaccional.

        Si el ticket no tiene usuario creador (creado_por es None), registra advertencia y omite.
        Cualquier error de correo no afecta la persistencia de la notificación.
        """
        try:
            destinatario = getattr(ticket, "creado_por", None)
        except Exception:
            destinatario = None

        if destinatario is None:
            logger.warning(
                "No se puede notificar el cierre del ticket %s: creado_por es None.",
                getattr(ticket, "radicado", "desconocido"),
            )
            return None

        es_resuelto = ticket.estado == EstadoChoices.RESUELTO
        if es_resuelto:
            titulo = f"Ticket Resuelto: {ticket.radicado}"
            mensaje = (
                f"Su ticket '{ticket.asunto}' ha sido resuelto. "
                f"Solución: {ticket.comentario_solucion or 'No especificada.'}"
            )
        else:
            titulo = f"Ticket No Procedente: {ticket.radicado}"
            mensaje = (
                f"Su ticket '{ticket.asunto}' fue marcado como no procedente. "
                f"Motivo: {ticket.motivo_no_procedente or 'No especificado.'}"
            )

        notificacion = TicketNotificacion.objects.create(
            destinatario=destinatario,
            empresa=ticket.empresa,
            ticket=ticket,
            titulo=titulo,
            mensaje=mensaje,
            estado_nuevo=ticket.estado,
            leida=False,
        )

        # Despachar correo transaccional de forma segura
        TicketEmailService.send_ticket_closed_notification(ticket, notificacion)

        return notificacion


class TicketCreationService:
    """Servicio de dominio para la creación atómica de tickets y su trazabilidad inicial."""

    @classmethod
    def create_ticket(
        cls,
        *,
        creado_por: Usuario | None = None,
        usuario: Usuario | None = None,
        empresa: Empresa | int | None = None,
        empresa_id: int | None = None,
        modulo: ModuloContratado | int | None = None,
        modulo_id: int | None = None,
        pestana_o_documento: str,
        asunto: str,
        descripcion: str,
        mensaje_error: str = "",
        prioridad: str = PrioridadChoices.MEDIA,
        canal_origen: str = CanalOrigenChoices.PORTAL,
        registrado_por_agente: Usuario | None = None,
        observaciones_iniciales: str | None = None,
        year: int | None = None,
    ) -> Ticket:
        """Crea un `Ticket` en estado `Abierto`, su `TicketItem` de `CREACION` y envía el comprobante.

        Reglas validadas dentro del bloque `@transaction.atomic` antes de generar el radicado:
        1. Multi-tenancy (RNF2): la empresa indicada debe coincidir exactamente
           con `creado_por.empresa_id`.
        2. Módulo contratado (RF2): el módulo debe existir, pertenecer a esa
           misma empresa y tener `activo=True`.

        El envío del correo de comprobante (BE-09, RF1 Flujo 5.1) se ejecuta fuera
        del bloque atómico tras confirmar el guardado y captura cualquier excepción,
        garantizando que un fallo de correo nunca revierta el ticket creado.
        """
        with transaction.atomic():
            actor_creador = creado_por or usuario
            if actor_creador is None:
                raise ValidationError(
                    {"creado_por": ["El usuario que reporta el ticket es obligatorio."]}
                )

            # 1. Resolver y validar el aislamiento multi-tenant (empresa_id vs usuario).
            if isinstance(empresa, Empresa):
                target_empresa_id = empresa.pk
                empresa_obj = empresa
            elif isinstance(empresa, int):
                target_empresa_id = empresa
                empresa_obj = None
            elif empresa_id is not None:
                target_empresa_id = empresa_id
                empresa_obj = None
            else:
                target_empresa_id = actor_creador.empresa_id
                empresa_obj = actor_creador.empresa

            if target_empresa_id is None or actor_creador.empresa_id is None:
                raise ValidationError(
                    {"empresa": ["El usuario que reporta el ticket debe pertenecer a una empresa."]}
                )

            if (
                actor_creador.rol == RolChoices.CLIENTE
                and target_empresa_id != actor_creador.empresa_id
            ):
                raise ValidationError(
                    {
                        "empresa": [
                            "La empresa indicada no coincide con la empresa del usuario autenticado."
                        ]
                    }
                )

            if target_empresa_id != actor_creador.empresa_id:
                raise ValidationError(
                    {"empresa": ["El cliente que reporta debe pertenecer a la empresa del ticket."]}
                )

            if empresa_obj is None:
                empresa_obj = actor_creador.empresa or Empresa.objects.get(pk=target_empresa_id)

            # 2. Resolver y validar que el módulo exista, pertenezca a la empresa y esté activo.
            if isinstance(modulo, ModuloContratado):
                modulo_obj = modulo
            else:
                target_modulo_id = modulo if isinstance(modulo, int) else modulo_id
                if target_modulo_id is None:
                    raise ValidationError({"modulo_id": ["El módulo afectado es obligatorio."]})
                modulo_obj = ModuloContratado.objects.filter(pk=target_modulo_id).first()

            if modulo_obj is None or modulo_obj.empresa_id != target_empresa_id:
                raise ValidationError(
                    {"modulo_id": ["El módulo seleccionado no está contratado por la empresa."]}
                )

            if not modulo_obj.activo:
                raise ValidationError(
                    {"modulo_id": ["El módulo seleccionado no está activo para la empresa."]}
                )

            # 3. Generar el radicado único de forma atómica con bloqueo de fila.
            radicado = RadicadoSequenceService.generate_next_radicado(year=year)

            # 4. Crear el Ticket con estado inicial 'Abierto'.
            ticket = Ticket(
                radicado=radicado,
                empresa=empresa_obj,
                creado_por=actor_creador,
                registrado_por_agente=registrado_por_agente,
                modulo=modulo_obj,
                pestana_o_documento=pestana_o_documento,
                asunto=asunto,
                descripcion=descripcion,
                mensaje_error=mensaje_error or "",
                prioridad=prioridad,
                estado=EstadoChoices.ABIERTO,
                canal_origen=canal_origen,
            )
            ticket.full_clean()
            ticket.save()

            # 5. Crear el primer evento inmutable en TicketItem con tipo_accion='CREACION'.
            actor_item = registrado_por_agente or actor_creador
            if observaciones_iniciales is not None:
                observaciones = observaciones_iniciales
            elif canal_origen == CanalOrigenChoices.CHATBOT:
                observaciones = "Ticket reportado mediante el chatbot."
            else:
                observaciones = "Ticket creado desde el portal."

            TicketItem.objects.create(
                ticket=ticket,
                actor=actor_item,
                tipo_accion=TipoAccionChoices.CREACION,
                estado_anterior="",
                estado_nuevo=EstadoChoices.ABIERTO,
                es_interna=False,
                observaciones=observaciones,
            )

        # 6. Envío del comprobante fuera del bloque atómico (BE-09, RF1 Flujo 5.1).
        TicketEmailService.send_ticket_receipt(ticket)

        return ticket
