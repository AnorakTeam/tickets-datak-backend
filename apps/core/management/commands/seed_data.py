"""Comando de gestión `seed_data` para poblar datos iniciales de prueba (tarea BE-07, issue #20).

Crea de forma atómica e idempotente:
- 2 empresas clientes:
  1. "Acme Industrial S.A.S." con módulos activos: Inventario, Facturación, Nómina.
  2. "Global Logistics Ltda." con módulos activos: Ventas, Tesorería.
- 4 usuarios de prueba (contraseña `test123456`):
  - `cliente@acme.com` (rol `cliente`, vinculado a Acme Industrial S.A.S.)
  - `cliente@global.com` (rol `cliente`, vinculado a Global Logistics Ltda.)
  - `agente@datak.co` (rol `agente_soporte`, personal interno)
  - `dev@datak.co` (rol `responsable_atencion`, personal interno / staff)
- Tickets iniciales para ambas empresas con sus respectivos eventos `TicketItem`
  respetando el aislamiento multi-tenant (RNF2) y la inmutabilidad del historial (RNF5).

Uso:
    python manage.py seed_data
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.companies.models import Empresa, ModuloContratado, RolChoices, Usuario
from apps.tickets.models import (
    CanalOrigenChoices,
    ClasificacionChoices,
    EstadoChoices,
    PrioridadChoices,
    Ticket,
    TicketItem,
    TicketNotificacion,
    TipoAccionChoices,
)

SEED_PASSWORD = "test123456"

EMPRESAS_SEED = [
    {
        "identificacion": "900123456-7",
        "nombre": "Acme Industrial S.A.S.",
        "modulos": [
            {"codigo": "INVENTARIO", "nombre": "Inventario"},
            {"codigo": "FACTURACION", "nombre": "Facturacion"},
            {"codigo": "NOMINA", "nombre": "Nomina"},
        ],
    },
    {
        "identificacion": "800987654-3",
        "nombre": "Global Logistics Ltda.",
        "modulos": [
            {"codigo": "VENTAS", "nombre": "Ventas"},
            {"codigo": "TESORERIA", "nombre": "Tesoreria"},
        ],
    },
]


class Command(BaseCommand):
    """Puebla la base de datos con empresas, módulos, usuarios y tickets de prueba."""

    help = (
        "Seed initial test companies, contracted modules, users, and sample tickets (idempotent)."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Iniciando carga de datos de prueba (seed_data)...")

        empresas_map, modulos_map = self._seed_empresas_and_modulos()
        usuarios_map = self._seed_usuarios(empresas_map)
        self._seed_tickets(empresas_map, modulos_map, usuarios_map)

        self.stdout.write(
            self.style.SUCCESS("Proceso seed_data finalizado exitosamente de forma idempotente.")
        )

    def _seed_empresas_and_modulos(self):
        """Crea o actualiza las empresas de prueba y sus módulos contratados activos."""
        empresas_map = {}
        modulos_map = {}

        for emp_data in EMPRESAS_SEED:
            empresa, created = Empresa.objects.update_or_create(
                identificacion=emp_data["identificacion"],
                defaults={
                    "nombre": emp_data["nombre"],
                    "activa": True,
                },
            )
            empresas_map[empresa.nombre] = empresa
            accion_emp = "Creada" if created else "Actualizada"
            self.stdout.write(
                self.style.SUCCESS(
                    f"[Empresa] {accion_emp}: {empresa.nombre} ({empresa.identificacion})"
                )
            )

            modulos_map[empresa.nombre] = {}
            for mod_data in emp_data["modulos"]:
                modulo, mod_created = ModuloContratado.objects.update_or_create(
                    empresa=empresa,
                    codigo=mod_data["codigo"],
                    defaults={
                        "nombre": mod_data["nombre"],
                        "activo": True,
                    },
                )
                modulos_map[empresa.nombre][modulo.codigo] = modulo
                accion_mod = "Creado" if mod_created else "Actualizado"
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  [ModuloContratado] {accion_mod}: {modulo.nombre} ({modulo.codigo}) -> {empresa.nombre}"
                    )
                )

        return empresas_map, modulos_map

    def _seed_usuarios(self, empresas_map):
        """Crea o actualiza los 4 usuarios de prueba con contraseña hasheada `test123456`."""
        acme = empresas_map["Acme Industrial S.A.S."]
        global_log = empresas_map["Global Logistics Ltda."]

        usuarios_seed = [
            {
                "correo": "cliente@acme.com",
                "nombre": "Carlos Gómez (Cliente Acme)",
                "rol": RolChoices.CLIENTE,
                "empresa": acme,
                "is_staff": False,
            },
            {
                "correo": "cliente@global.com",
                "nombre": "Laura Martínez (Cliente Global)",
                "rol": RolChoices.CLIENTE,
                "empresa": global_log,
                "is_staff": False,
            },
            {
                "correo": "agente@datak.co",
                "nombre": "Andrés Pérez (Agente Soporte)",
                "rol": RolChoices.AGENTE_SOPORTE,
                "empresa": None,
                "is_staff": True,
            },
            {
                "correo": "soporte@datak.co",
                "nombre": "Ana Soporte (Agente Soporte)",
                "rol": RolChoices.AGENTE_SOPORTE,
                "empresa": None,
                "is_staff": True,
            },
            {
                "correo": "dev@datak.co",
                "nombre": "Camila Ríos (Desarrolladora)",
                "rol": RolChoices.RESPONSABLE_ATENCION,
                "empresa": None,
                "is_staff": True,
            },
            {
                "correo": "responsable@datak.co",
                "nombre": "Mariana Silva (Responsable Atención)",
                "rol": RolChoices.RESPONSABLE_ATENCION,
                "empresa": None,
                "is_staff": True,
            },
        ]

        usuarios_map = {}
        for u_data in usuarios_seed:
            usuario = Usuario.objects.filter(correo=u_data["correo"]).first()
            created = usuario is None

            if created:
                usuario = Usuario.objects.create_user(
                    correo=u_data["correo"],
                    password=SEED_PASSWORD,
                    nombre=u_data["nombre"],
                    rol=u_data["rol"],
                    empresa=u_data["empresa"],
                    activo=True,
                    is_staff=u_data["is_staff"],
                )
            else:
                usuario.nombre = u_data["nombre"]
                usuario.rol = u_data["rol"]
                usuario.empresa = u_data["empresa"]
                usuario.activo = True
                usuario.is_staff = u_data["is_staff"]
                if not usuario.check_password(SEED_PASSWORD):
                    usuario.set_password(SEED_PASSWORD)
                usuario.full_clean(exclude=["password"])
                usuario.save()

            usuarios_map[usuario.correo] = usuario
            accion_usr = "Creado" if created else "Actualizado"
            self.stdout.write(
                self.style.SUCCESS(
                    f"[Usuario] {accion_usr}: {usuario.correo} (rol={usuario.rol}, empresa={usuario.empresa_id})"
                )
            )

        return usuarios_map

    def _seed_tickets(self, empresas_map, modulos_map, usuarios_map):
        """Crea o actualiza tickets iniciales de muestra y su historial inmutable TicketItem."""
        acme = empresas_map["Acme Industrial S.A.S."]
        global_log = empresas_map["Global Logistics Ltda."]

        cliente_acme = usuarios_map["cliente@acme.com"]
        cliente_global = usuarios_map["cliente@global.com"]
        agente = usuarios_map["agente@datak.co"]
        dev = usuarios_map["dev@datak.co"]

        tickets_seed = [
            {
                "radicado": "TK-2026-000001",
                "empresa": acme,
                "creado_por": cliente_acme,
                "modulo": modulos_map[acme.nombre]["FACTURACION"],
                "pestana_o_documento": "Emisión de Facturas / F-203",
                "asunto": "Error 500 al emitir factura electrónica con retención",
                "descripcion": (
                    "Al confirmar la factura con retención en la fuente el sistema "
                    "no completa el proceso y arroja error de servidor."
                ),
                "mensaje_error": "Server Error: RetencionCalculatorException line 42",
                "prioridad": PrioridadChoices.ALTA,
                "estado": EstadoChoices.ABIERTO,
                "clasificacion": None,
                "canal_origen": CanalOrigenChoices.PORTAL,
                "responsable": None,
                "comentario_solucion": "",
                "motivo_no_procedente": "",
                "fecha_resolucion": None,
                "items": [
                    {
                        "actor": cliente_acme,
                        "tipo_accion": TipoAccionChoices.CREACION,
                        "estado_anterior": "",
                        "estado_nuevo": EstadoChoices.ABIERTO,
                        "responsable_asignado": None,
                        "es_interna": False,
                        "observaciones": "Ticket creado desde el portal del cliente.",
                    },
                ],
            },
            {
                "radicado": "TK-2026-000002",
                "empresa": acme,
                "creado_por": cliente_acme,
                "modulo": modulos_map[acme.nombre]["INVENTARIO"],
                "pestana_o_documento": "Kardex de Productos / Bodega Central",
                "asunto": "Diferencia en saldo de inventario tras traslado entre bodegas",
                "descripcion": (
                    "El saldo disponible del producto SKU-402 no se descuenta en la "
                    "bodega origen al confirmar el traslado."
                ),
                "mensaje_error": "",
                "prioridad": PrioridadChoices.MEDIA,
                "estado": EstadoChoices.EN_GESTION,
                "clasificacion": ClasificacionChoices.BUG,
                "canal_origen": CanalOrigenChoices.CHATBOT,
                "responsable": dev,
                "comentario_solucion": "",
                "motivo_no_procedente": "",
                "fecha_resolucion": None,
                "items": [
                    {
                        "actor": cliente_acme,
                        "tipo_accion": TipoAccionChoices.CREACION,
                        "estado_anterior": "",
                        "estado_nuevo": EstadoChoices.ABIERTO,
                        "responsable_asignado": None,
                        "es_interna": False,
                        "observaciones": "Ticket reportado mediante el chatbot.",
                    },
                    {
                        "actor": agente,
                        "tipo_accion": TipoAccionChoices.ASIGNACION,
                        "estado_anterior": EstadoChoices.ABIERTO,
                        "estado_nuevo": EstadoChoices.EN_GESTION,
                        "responsable_asignado": dev,
                        "es_interna": False,
                        "observaciones": "Incidencia asignada al equipo de desarrollo.",
                    },
                    {
                        "actor": dev,
                        "tipo_accion": TipoAccionChoices.NOTA_INTERNA,
                        "estado_anterior": "",
                        "estado_nuevo": "",
                        "responsable_asignado": None,
                        "es_interna": True,
                        "observaciones": "Nota interna: revisar trigger de descuento en traslado de bodega.",
                    },
                ],
            },
            {
                "radicado": "TK-2026-000003",
                "empresa": acme,
                "creado_por": cliente_acme,
                "modulo": modulos_map[acme.nombre]["NOMINA"],
                "pestana_o_documento": "Liquidación Mensual / Planilla PILA",
                "asunto": "Diferencia de pesos en autoliquidación de aportes",
                "descripcion": (
                    "Al generar el archivo plano PILA se presenta una diferencia "
                    "de ajuste por redondeo frente al operador."
                ),
                "mensaje_error": "",
                "prioridad": PrioridadChoices.BAJA,
                "estado": EstadoChoices.RESUELTO,
                "clasificacion": ClasificacionChoices.ERROR_DE_USO,
                "canal_origen": CanalOrigenChoices.PORTAL,
                "responsable": dev,
                "comentario_solucion": (
                    "Se habilitó el parámetro de redondeo de seguridad social en la "
                    "configuración de nómina."
                ),
                "motivo_no_procedente": "",
                "fecha_resolucion": timezone.now(),
                "items": [
                    {
                        "actor": cliente_acme,
                        "tipo_accion": TipoAccionChoices.CREACION,
                        "estado_anterior": "",
                        "estado_nuevo": EstadoChoices.ABIERTO,
                        "responsable_asignado": None,
                        "es_interna": False,
                        "observaciones": "Ticket creado desde el portal del cliente.",
                    },
                    {
                        "actor": dev,
                        "tipo_accion": TipoAccionChoices.RESOLUCION,
                        "estado_anterior": EstadoChoices.ABIERTO,
                        "estado_nuevo": EstadoChoices.RESUELTO,
                        "responsable_asignado": None,
                        "es_interna": False,
                        "observaciones": (
                            "Se habilitó el parámetro de redondeo de seguridad social en la "
                            "configuración de nómina."
                        ),
                    },
                ],
            },
            {
                "radicado": "TK-2026-000004",
                "empresa": global_log,
                "creado_por": cliente_global,
                "modulo": modulos_map[global_log.nombre]["VENTAS"],
                "pestana_o_documento": "Pedidos de Clientes / Despachos",
                "asunto": "No permite aprobar pedidos de venta con cupo de crédito",
                "descripcion": (
                    "Los pedidos de clientes con cupo aprobado quedan bloqueados "
                    "en validación comercial."
                ),
                "mensaje_error": "CreditLimitValidationError: Timeout connecting to scoring",
                "prioridad": PrioridadChoices.CRITICA,
                "estado": EstadoChoices.ABIERTO,
                "clasificacion": None,
                "canal_origen": CanalOrigenChoices.PORTAL,
                "responsable": None,
                "comentario_solucion": "",
                "motivo_no_procedente": "",
                "fecha_resolucion": None,
                "items": [
                    {
                        "actor": cliente_global,
                        "tipo_accion": TipoAccionChoices.CREACION,
                        "estado_anterior": "",
                        "estado_nuevo": EstadoChoices.ABIERTO,
                        "responsable_asignado": None,
                        "es_interna": False,
                        "observaciones": "Ticket creado desde el portal del cliente.",
                    },
                ],
            },
            {
                "radicado": "TK-2026-000005",
                "empresa": global_log,
                "creado_por": cliente_global,
                "modulo": modulos_map[global_log.nombre]["TESORERIA"],
                "pestana_o_documento": "Conciliación Bancaria / Extractos",
                "asunto": "Error al importar archivo de extracto bancario en formato CSV",
                "descripcion": (
                    "Al subir el extracto del mes actual el cargador rechaza las "
                    "fechas con formato DD/MM/AAAA."
                ),
                "mensaje_error": "",
                "prioridad": PrioridadChoices.ALTA,
                "estado": EstadoChoices.EN_GESTION,
                "clasificacion": ClasificacionChoices.BUG,
                "canal_origen": CanalOrigenChoices.CHATBOT,
                "responsable": dev,
                "comentario_solucion": "",
                "motivo_no_procedente": "",
                "fecha_resolucion": None,
                "items": [
                    {
                        "actor": cliente_global,
                        "tipo_accion": TipoAccionChoices.CREACION,
                        "estado_anterior": "",
                        "estado_nuevo": EstadoChoices.ABIERTO,
                        "responsable_asignado": None,
                        "es_interna": False,
                        "observaciones": "Ticket reportado mediante el chatbot.",
                    },
                    {
                        "actor": agente,
                        "tipo_accion": TipoAccionChoices.ASIGNACION,
                        "estado_anterior": EstadoChoices.ABIERTO,
                        "estado_nuevo": EstadoChoices.EN_GESTION,
                        "responsable_asignado": dev,
                        "es_interna": False,
                        "observaciones": "Asignado para revisión del parser de extractos.",
                    },
                ],
            },
            {
                "radicado": "TK-2026-000006",
                "empresa": global_log,
                "creado_por": cliente_global,
                "modulo": modulos_map[global_log.nombre]["VENTAS"],
                "pestana_o_documento": "Configuración / Parámetros Generales",
                "asunto": "Solicitud de modificación de campos fijos en formato de factura",
                "descripcion": (
                    "Se solicita eliminar campos de control fiscal predeterminados "
                    "en el formato de impresión estándar."
                ),
                "mensaje_error": "",
                "prioridad": PrioridadChoices.BAJA,
                "estado": EstadoChoices.NO_PROCEDENTE,
                "clasificacion": ClasificacionChoices.SOLICITUD_DE_MEJORA,
                "canal_origen": CanalOrigenChoices.PORTAL,
                "responsable": None,
                "comentario_solucion": "",
                "motivo_no_procedente": (
                    "Los campos de control fiscal son obligatorios por regulación "
                    "y no pueden ser retirados de la plantilla estándar."
                ),
                "fecha_resolucion": timezone.now(),
                "items": [
                    {
                        "actor": cliente_global,
                        "tipo_accion": TipoAccionChoices.CREACION,
                        "estado_anterior": "",
                        "estado_nuevo": EstadoChoices.ABIERTO,
                        "responsable_asignado": None,
                        "es_interna": False,
                        "observaciones": "Ticket reportado a través del portal de clientes.",
                    },
                    {
                        "actor": agente,
                        "tipo_accion": TipoAccionChoices.NO_PROCEDENTE,
                        "estado_anterior": EstadoChoices.ABIERTO,
                        "estado_nuevo": EstadoChoices.NO_PROCEDENTE,
                        "responsable_asignado": None,
                        "es_interna": False,
                        "observaciones": (
                            "Los campos de control fiscal son obligatorios por regulación "
                            "y no pueden ser retirados de la plantilla estándar."
                        ),
                    },
                ],
            },
        ]

        for t_data in tickets_seed:
            items_data = t_data.pop("items")
            radicado = t_data.pop("radicado")

            ticket = Ticket.objects.filter(radicado=radicado).first()
            created = ticket is None

            if created:
                ticket = Ticket(radicado=radicado, **t_data)
            else:
                for campo, valor in t_data.items():
                    setattr(ticket, campo, valor)

            ticket.full_clean()
            ticket.save()

            accion_tk = "Creado" if created else "Actualizado"
            self.stdout.write(
                self.style.SUCCESS(
                    f"[Ticket] {accion_tk}: {ticket.radicado} ({ticket.estado}) -> {ticket.empresa.nombre}"
                )
            )

            # TicketItem es estrictamente inmutable (RNF5): nunca se modifica un
            # registro existente; solo se insertan los eventos faltantes.
            for item_data in items_data:
                existe_item = TicketItem.objects.filter(
                    ticket=ticket,
                    tipo_accion=item_data["tipo_accion"],
                    observaciones=item_data["observaciones"],
                ).exists()
                if not existe_item:
                    TicketItem.objects.create(ticket=ticket, **item_data)
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  [TicketItem] Creado: {ticket.radicado} · {item_data['tipo_accion']}"
                        )
                    )

        # Seed TicketNotificacion para tickets cerrados (Resuelto / No procedente) (BE-27, RF16)
        notificaciones_seed = [
            {
                "radicado": "TK-2026-000003",
                "destinatario": cliente_acme,
                "empresa": acme,
                "titulo": "Ticket Resuelto: TK-2026-000003",
                "mensaje": (
                    "Se habilitó el parámetro de redondeo de seguridad social en la "
                    "configuración de nómina."
                ),
                "estado_nuevo": EstadoChoices.RESUELTO,
                "leida": False,
            },
            {
                "radicado": "TK-2026-000006",
                "destinatario": cliente_global,
                "empresa": global_log,
                "titulo": "Ticket Desestimado: TK-2026-000006",
                "mensaje": (
                    "Los campos de control fiscal son obligatorios por regulación "
                    "y no pueden ser retirados de la plantilla estándar."
                ),
                "estado_nuevo": EstadoChoices.NO_PROCEDENTE,
                "leida": False,
            },
        ]

        for n_data in notificaciones_seed:
            radicado_target = n_data.pop("radicado")
            ticket_target = Ticket.objects.filter(radicado=radicado_target).first()
            if ticket_target:
                notif, created_notif = TicketNotificacion.objects.get_or_create(
                    ticket=ticket_target,
                    destinatario=n_data["destinatario"],
                    empresa=n_data["empresa"],
                    defaults={
                        "titulo": n_data["titulo"],
                        "mensaje": n_data["mensaje"],
                        "estado_nuevo": n_data["estado_nuevo"],
                        "leida": n_data["leida"],
                    },
                )
                accion_notif = "Creada" if created_notif else "Existente"
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  [TicketNotificacion] {accion_notif}: {notif.titulo} -> {notif.destinatario.correo}"
                    )
                )
