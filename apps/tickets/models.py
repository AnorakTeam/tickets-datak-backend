"""Modelos de la app `tickets`.

Contiene el modelo `Ticket` (tarea BE-05): la entidad central del sistema, que
representa una incidencia de soporte reportada por un cliente de Datak.co.

Los campos siguen la sección 3.4 de ARCHITECTURE_AND_DATA_MODEL_REFERENCE.md y
el issue #18. El modelo tiene EXACTAMENTE 20 campos (los acordados en el FP8,
archivo lógico interno de complejidad MEDIA). No se deben agregar, quitar ni
renombrar campos sin actualizar esa documentación.
"""

from django.core.exceptions import ValidationError
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
