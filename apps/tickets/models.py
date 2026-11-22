"""Modelos de la app `tickets`.

Contiene:
- `Ticket` (tarea BE-05): la entidad central del sistema, que representa una
  incidencia de soporte reportada por un cliente de Datak.co. Tiene EXACTAMENTE
  20 campos (sección 3.4 de ARCHITECTURE_AND_DATA_MODEL_REFERENCE.md, FP8,
  archivo lógico interno de complejidad MEDIA). No se deben agregar, quitar ni
  renombrar campos sin actualizar esa documentación.
- `TicketItem` (tarea BE-06): el historial de cada ticket. Cada acción (crear,
  asignar, cambiar estado, nota interna, resolver...) queda como un registro
  que NO se puede modificar ni borrar (RNF5, sección 3.5 del mismo documento).
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import RegexValidator
from django.db import models

from apps.companies.models import Empresa, ModuloContratado, RolChoices, Usuario

# --------------------------------------------------------------------------
# Catálogos (choices)
# --------------------------------------------------------------------------
# Cada opción tiene el valor que se guarda en la base de datos y una etiqueta
# legible. Los valores guardados son los del documento de arquitectura (sin
# tildes, por ejemplo "En gestion") porque el frontend y las demás tareas los
# comparan tal cual; las etiquetas sí llevan tildes porque son lo que se muestra.


class PrioridadChoices(models.TextChoices):
    """Urgencia de la incidencia, elegida por el cliente al reportarla."""

    BAJA = "Baja", "Baja"
    MEDIA = "Media", "Media"
    ALTA = "Alta", "Alta"
    CRITICA = "Critica", "Crítica"


class EstadoChoices(models.TextChoices):
    """Ciclo de vida del ticket.

    Abierto -> En gestión -> Resuelto, o bien -> No procedente.
    """

    ABIERTO = "Abierto", "Abierto"
    EN_GESTION = "En gestion", "En gestión"
    RESUELTO = "Resuelto", "Resuelto"
    NO_PROCEDENTE = "No procedente", "No procedente"


class ClasificacionChoices(models.TextChoices):
    """Tipo de incidencia que asigna el agente de soporte al hacer el triaje."""

    ERROR_DE_USO = "Error de uso", "Error de uso"
    BUG = "Bug", "Bug"
    SOLICITUD_DE_MEJORA = "Solicitud de mejora", "Solicitud de mejora"


class CanalOrigenChoices(models.TextChoices):
    """Por dónde llegó la incidencia.

    Portal y Chatbot los crea el propio cliente; WhatsApp, Slack y Otro los
    registra un agente de soporte en nombre del cliente.
    """

    PORTAL = "Portal", "Portal"
    CHATBOT = "Chatbot", "Chatbot"
    WHATSAPP = "WhatsApp", "WhatsApp"
    SLACK = "Slack", "Slack"
    OTRO = "Otro", "Otro"


# Validador del formato del radicado: "TK-" + año de 4 dígitos + "-" + 6 dígitos.
# Ejemplo válido: TK-2026-000001. El número lo genera RadicadoSequenceService (BE-08).
radicado_validator = RegexValidator(
    regex=r"^TK-\d{4}-\d{6}$",
    message="El radicado debe tener el formato TK-AAAA-NNNNNN (por ejemplo TK-2026-000001).",
)


class Ticket(models.Model):
    """Incidencia de soporte reportada por un cliente (20 campos exactos).

    Reglas importantes:
    - Multi-tenant (RNF2): cada ticket pertenece a una `empresa`, y en las
      consultas de los clientes siempre se filtra por la empresa del usuario
      autenticado (`request.user.empresa`), nunca por un dato que mande el frontend.
    - Los campos `responsable` y las notas internas NUNCA se muestran al cliente;
      eso lo controlan los serializers de los endpoints (BE-12 y BE-13).
    - Las llaves foráneas usan PROTECT o SET_NULL para no perder tickets si se
      intenta borrar una empresa, un módulo o un usuario relacionado.
    """

    # 1. id: no se declara; Django crea un BigAutoField (DEFAULT_AUTO_FIELD).

    # 2. Número de radicado que ve el cliente, por ejemplo "TK-2026-000001".
    #    unique=True impide dos tickets con el mismo radicado (índice único).
    radicado = models.CharField(
        "radicado",
        max_length=20,
        unique=True,
        db_index=True,
        validators=[radicado_validator],
        error_messages={"unique": "Ya existe un ticket con este radicado."},
    )

    # 3. Empresa dueña del ticket (el tenant). PROTECT: no se puede borrar una
    #    empresa que tenga tickets, para no perder el historial de soporte.
    empresa = models.ForeignKey(
        Empresa,
        verbose_name="empresa",
        on_delete=models.PROTECT,
        db_index=True,
        related_name="tickets",
    )

    # 4. Usuario que reportó el ticket (el cliente). PROTECT por la misma razón.
    creado_por = models.ForeignKey(
        Usuario,
        verbose_name="creado por",
        on_delete=models.PROTECT,
        related_name="tickets_creados",
    )

    # 5. Agente de soporte que registró el ticket en nombre del cliente (cuando
    #    llega por WhatsApp, Slack u otro canal). Vacío si lo creó el cliente.
    #    SET_NULL: si se borra el agente, el ticket queda pero sin ese dato.
    registrado_por_agente = models.ForeignKey(
        Usuario,
        verbose_name="registrado por agente",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets_registrados_agente",
    )

    # 6. Módulo contratado afectado (de la misma empresa del ticket; se valida en clean()).
    modulo = models.ForeignKey(
        ModuloContratado,
        verbose_name="módulo",
        on_delete=models.PROTECT,
        related_name="tickets",
    )

    # 7. Pantalla, pestaña o documento donde ocurrió el problema.
    pestana_o_documento = models.CharField("pestaña o documento", max_length=255)

    # 8. Resumen corto de la incidencia.
    asunto = models.CharField("asunto", max_length=255)

    # 9. Explicación completa del problema.
    descripcion = models.TextField("descripción")

    # 10. Mensaje de error del sistema, si lo hay (opcional).
    mensaje_error = models.TextField("mensaje de error", blank=True, default="")

    # 11. Prioridad; por defecto "Media".
    prioridad = models.CharField(
        "prioridad",
        max_length=20,
        choices=PrioridadChoices.choices,
        default=PrioridadChoices.MEDIA,
    )

    # 12. Estado del ciclo de vida; todo ticket nuevo empieza "Abierto".
    estado = models.CharField(
        "estado",
        max_length=30,
        choices=EstadoChoices.choices,
        default=EstadoChoices.ABIERTO,
    )

    # 13. Clasificación que pone el agente de soporte; vacía al crear el ticket.
    clasificacion = models.CharField(
        "clasificación",
        max_length=30,
        choices=ClasificacionChoices.choices,
        null=True,
        blank=True,
    )

    # 14. Canal por el que llegó; por defecto "Portal".
    canal_origen = models.CharField(
        "canal de origen",
        max_length=20,
        choices=CanalOrigenChoices.choices,
        default=CanalOrigenChoices.PORTAL,
    )

    # 15. Desarrollador o responsable asignado a resolverlo. Es información
    #     interna: no se muestra al cliente (RNF2).
    responsable = models.ForeignKey(
        Usuario,
        verbose_name="responsable",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets_asignados",
    )

    # 16. Explicación de la solución; SÍ es visible para el cliente.
    comentario_solucion = models.TextField("comentario de solución", blank=True, default="")

    # 17. Motivo por el que se marcó "No procedente"; visible para el cliente.
    motivo_no_procedente = models.TextField("motivo de no procedente", blank=True, default="")

    # 18-20. Fechas: creación (se llena sola, con índice para ordenar rápido),
    #        última actualización (se actualiza en cada save) y resolución
    #        (se llena cuando el ticket se resuelve o se cierra).
    fecha_creacion = models.DateTimeField("fecha de creación", auto_now_add=True, db_index=True)
    fecha_actualizacion = models.DateTimeField("fecha de actualización", auto_now=True)
    fecha_resolucion = models.DateTimeField("fecha de resolución", null=True, blank=True)

    class Meta:
        verbose_name = "ticket"
        verbose_name_plural = "tickets"
        # Por defecto, los tickets más recientes primero.
        ordering = ["-fecha_creacion"]
        indexes = [
            # Índice compuesto pedido en el issue #18: acelera la consulta más
            # común ("tickets de mi empresa, filtrados por estado, del más nuevo
            # al más viejo") que usan "Mis tickets" (BE-12) y la consola de soporte.
            models.Index(
                fields=["empresa", "estado", "-fecha_creacion"],
                name="ticket_emp_estado_fecha_idx",
            ),
        ]

    def clean(self):
        """Validaciones de negocio que se ejecutan con full_clean() (serializers, admin).

        1. El módulo elegido debe pertenecer a la misma empresa del ticket: un
           cliente no puede reportar sobre un módulo de otra empresa (RNF2).
        2. Si quien crea el ticket es un cliente, debe ser de la misma empresa.
        """
        super().clean()
        errores = {}

        # `*_id` evita consultar la base de datos solo para comparar ids.
        if self.modulo_id and self.empresa_id and self.modulo.empresa_id != self.empresa_id:
            errores["modulo"] = "El módulo seleccionado no pertenece a la empresa del ticket."

        if (
            self.creado_por_id
            and self.empresa_id
            and self.creado_por.rol == RolChoices.CLIENTE
            and self.creado_por.empresa_id != self.empresa_id
        ):
            errores["creado_por"] = (
                "El cliente que reporta debe pertenecer a la empresa del ticket."
            )

        if errores:
            raise ValidationError(errores)

    def __str__(self) -> str:
        """Texto con el que se muestra el ticket. Ejemplo: "TK-2026-000001 - No carga la factura"."""
        return f"{self.radicado} - {self.asunto}"


# --------------------------------------------------------------------------
# Historial inmutable del ticket (BE-06)
# --------------------------------------------------------------------------

# Mensajes que se muestran cuando alguien intenta modificar o borrar el historial.
MENSAJE_NO_MODIFICABLE = "Los registros del historial del ticket no se pueden modificar."
MENSAJE_NO_ELIMINABLE = "Los registros del historial del ticket no se pueden eliminar."


class TipoAccionChoices(models.TextChoices):
    """Tipo de evento que se registra en el historial del ticket."""

    CREACION = "CREACION", "Creación"
    ASIGNACION = "ASIGNACION", "Asignación"
    CAMBIO_ESTADO = "CAMBIO_ESTADO", "Cambio de estado"
    CLASIFICACION = "CLASIFICACION", "Clasificación"
    NOTA_INTERNA = "NOTA_INTERNA", "Nota interna"
    RESOLUCION = "RESOLUCION", "Resolución"
    NO_PROCEDENTE = "NO_PROCEDENTE", "No procedente"


class TicketItemQuerySet(models.QuerySet):
    """Consultas del historial que bloquean los cambios masivos.

    `save()` y `delete()` del modelo solo protegen un registro a la vez. Pero
    Django también permite cambiar o borrar muchos de una sola vez con
    `TicketItem.objects.filter(...).update(...)` o `.delete()`, que NO pasan por
    esos métodos. Este QuerySet bloquea también esos caminos, para que el
    historial sea realmente de solo inserción (RNF5).
    """

    def update(self, **kwargs):
        raise PermissionDenied(MENSAJE_NO_MODIFICABLE)

    def delete(self):
        raise PermissionDenied(MENSAJE_NO_ELIMINABLE)


class TicketItem(models.Model):
    """Registro del historial de un ticket (10 campos). Solo se puede crear.

    Funciona como una bitácora ("event sourcing"): en lugar de editar un evento
    anterior, cada cambio se agrega como un registro nuevo. Así queda la
    trazabilidad completa de quién hizo qué y cuándo.

    Regla de visibilidad (RNF2): los registros con `es_interna=True` son notas
    del equipo de soporte y NUNCA se muestran al cliente; eso lo aplican los
    serializers de los endpoints del cliente (BE-13).
    """

    # 1. id: no se declara; Django crea un BigAutoField (DEFAULT_AUTO_FIELD).

    # 2. Ticket al que pertenece el evento. CASCADE: el historial vive y muere
    #    con su ticket. related_name="historial" permite `ticket.historial.all()`.
    ticket = models.ForeignKey(
        Ticket,
        verbose_name="ticket",
        on_delete=models.CASCADE,
        related_name="historial",
    )

    # 3. Usuario que hizo la acción (cliente, agente o responsable).
    #    PROTECT: no se puede borrar un usuario que aparece en el historial.
    actor = models.ForeignKey(
        Usuario,
        verbose_name="actor",
        on_delete=models.PROTECT,
        related_name="acciones_historial",
    )

    # 4. Qué tipo de acción fue (ver TipoAccionChoices).
    tipo_accion = models.CharField(
        "tipo de acción",
        max_length=30,
        choices=TipoAccionChoices.choices,
    )

    # 5-6. Estado del ticket antes y después de la acción. Quedan vacíos cuando
    #      la acción no cambia el estado (por ejemplo, una nota interna).
    estado_anterior = models.CharField(
        "estado anterior",
        max_length=30,
        choices=EstadoChoices.choices,
        blank=True,
        default="",
    )
    estado_nuevo = models.CharField(
        "estado nuevo",
        max_length=30,
        choices=EstadoChoices.choices,
        blank=True,
        default="",
    )

    # 7. Responsable asignado en esta acción (solo para ASIGNACION).
    #    SET_NULL: si se borra ese usuario, el evento se conserva sin ese dato.
    responsable_asignado = models.ForeignKey(
        Usuario,
        verbose_name="responsable asignado",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asignaciones_historial",
    )

    # 8. True = nota interna del equipo de soporte, oculta para el cliente.
    es_interna = models.BooleanField("es interna", default=False)

    # 9. Comentario u observación del evento (opcional).
    observaciones = models.TextField("observaciones", blank=True, default="")

    # 10. Momento en que ocurrió el evento; Django lo llena al crear.
    fecha_creacion = models.DateTimeField("fecha de creación", auto_now_add=True)

    # Usa el QuerySet que bloquea update() y delete() masivos.
    objects = TicketItemQuerySet.as_manager()

    class Meta:
        verbose_name = "registro de historial"
        verbose_name_plural = "historial de tickets"
        # Orden cronológico: del evento más antiguo al más reciente.
        # `id` desempata eventos creados en el mismo instante.
        ordering = ["fecha_creacion", "id"]

    def save(self, *args, **kwargs):
        """Guarda el registro SOLO si es nuevo; si ya existe, lo impide.

        Un registro nuevo todavía no tiene `pk` (id), así que se guarda normal.
        Si ya tiene `pk`, ya está en la base de datos y cambiarlo alteraría el
        historial, por eso se lanza PermissionDenied.
        """
        if self.pk is not None:
            raise PermissionDenied(MENSAJE_NO_MODIFICABLE)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Nunca permite borrar un registro del historial."""
        raise PermissionDenied(MENSAJE_NO_ELIMINABLE)

    def __str__(self) -> str:
        """Ejemplo: "TK-2026-000001 · CREACION"."""
        return f"{self.ticket.radicado} · {self.tipo_accion}"


class TicketNotificacion(models.Model):
    """Notificación en el portal para el cliente ante cierre o resolución de tickets (BE-23, RF16).

    Tiene EXACTAMENTE 9 campos lógicos (sección 3.6 de ARCHITECTURE_AND_DATA_MODEL_REFERENCE.md).
    Registra avisos dirigidos al usuario creador del ticket cuando este cambia de estado
    a 'Resuelto' o 'No procedente'.
    """

    # 1. id: BigAutoField implícito (DEFAULT_AUTO_FIELD)

    # 2. Usuario cliente destinatario de la notificación.
    destinatario = models.ForeignKey(
        Usuario,
        verbose_name="destinatario",
        on_delete=models.CASCADE,
        related_name="notificaciones",
    )

    # 3. Empresa dueña del ticket y del cliente (aislamiento multi-inquilino RNF2).
    empresa = models.ForeignKey(
        Empresa,
        verbose_name="empresa",
        on_delete=models.CASCADE,
        related_name="notificaciones",
    )

    # 4. Ticket al que hace referencia la notificación.
    ticket = models.ForeignKey(
        Ticket,
        verbose_name="ticket",
        on_delete=models.CASCADE,
        related_name="notificaciones",
    )

    # 5. Título corto del aviso (ej: "Ticket Resuelto: TK-2026-000012").
    titulo = models.CharField("título", max_length=255)

    # 6. Contenido descriptivo del aviso (solución o motivo de desestimación).
    mensaje = models.TextField("mensaje")

    # 7. Nuevo estado que motivó la notificación ('Resuelto' o 'No procedente').
    estado_nuevo = models.CharField(
        "estado nuevo",
        max_length=30,
        choices=EstadoChoices.choices,
    )

    # 8. Bandera que indica si el cliente ya visualizó/marcó como leída la notificación.
    leida = models.BooleanField("leída", default=False)

    # 9. Momento en el que se generó la notificación en el sistema.
    fecha_creacion = models.DateTimeField("fecha de creación", auto_now_add=True)

    class Meta:
        verbose_name = "notificación de ticket"
        verbose_name_plural = "notificaciones de tickets"
        ordering = ["-fecha_creacion", "-id"]

    def __str__(self) -> str:
        return f"{self.ticket.radicado} · {self.titulo} · {'Leída' if self.leida else 'No leída'}"

