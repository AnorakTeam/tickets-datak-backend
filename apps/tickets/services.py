"""Servicios de dominio de la app `tickets` (tarea BE-08, issue #21).

Contiene:
- `RadicadoSequenceService`: generador atómico y seguro ante concurrencia
  (`select_for_update`) de números de radicado con formato `TK-AAAA-NNNNNN`,
  reiniciando el contador anual en `000001` cuando cambia el año.
- `TicketCreationService`: servicio transaccional (`@transaction.atomic`) que
  valida aislamiento multi-tenant (`empresa_id`), vigencia y pertenencia del
  módulo (`ModuloContratado`), asigna el radicado, crea el `Ticket` en estado
  `Abierto` y registra el primer evento inmutable `TicketItem` (`CREACION`).
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.companies.models import Empresa, ModuloContratado, RolChoices, Usuario
from apps.tickets.models import (
    CanalOrigenChoices,
    EstadoChoices,
    PrioridadChoices,
    Ticket,
    TicketItem,
    TipoAccionChoices,
)


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


class TicketCreationService:
    """Servicio de dominio para la creación atómica de tickets y su trazabilidad inicial."""

    @classmethod
    @transaction.atomic
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
        """Crea un `Ticket` en estado `Abierto` y su `TicketItem` de `CREACION` de forma atómica.

        Reglas validadas antes de generar el radicado o insertar registros:
        1. Multi-tenancy (RNF2): la empresa indicada debe coincidir exactamente
           con `creado_por.empresa_id`.
        2. Módulo contratado (RF2): el módulo debe existir, pertenecer a esa
           misma empresa y tener `activo=True`.
        """
        actor_creador = creado_por or usuario
        if actor_creador is None:
            raise ValidationError(
                {"creado_por": ["El usuario que reporta el ticket es obligatorio."]}
            )

        # 1. Resolver y validar el aislamiento multi-tenant (empresa_id vs usuario).
        if isinstance(empresa, Empresa):
            target_empresa_id = empresa.pk
        elif isinstance(empresa, int):
            target_empresa_id = empresa
        elif empresa_id is not None:
            target_empresa_id = empresa_id
        else:
            target_empresa_id = actor_creador.empresa_id

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
            empresa_id=target_empresa_id,
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

        return ticket
