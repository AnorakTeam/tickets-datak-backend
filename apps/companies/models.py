"""Modelos de la app `companies`.

Esta app contiene:
- `Empresa`: el "tenant" del sistema (multi-tenant). Cada cliente de Datak.co es
  una empresa y todos sus datos (usuarios, módulos contratados, tickets) cuelgan
  de ella. Así se garantiza que una empresa nunca vea la información de otra (RNF2).
- `Usuario`: el modelo de usuario personalizado del proyecto (tarea BE-03). Se
  inicia sesión con el correo y cada usuario tiene un rol y, si es cliente, una
  empresa.
- `ModuloContratado`: el catálogo de módulos funcionales habilitados para cada
  empresa cliente (tarea BE-04, p. ej. INVENTARIO, NOMINA, VENTAS, FACTURACION,
  CONTABILIDAD).
"""

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class Empresa(models.Model):
    """Empresa cliente de Datak.co; es el límite de aislamiento entre clientes.

    Regla clave del proyecto (RNF2): la empresa de un usuario NUNCA se recibe
    desde el frontend (payload de la petición). Siempre se obtiene en el servidor
    a partir del usuario autenticado (`request.user.empresa`). Este modelo es la
    base de esa regla: Usuario, ModuloContratado y Ticket tendrán una llave
    foránea (FK) hacia aquí.

    Los campos siguen la sección 3.1 de ARCHITECTURE_AND_DATA_MODEL_REFERENCE.md.
    No se declara `id`: Django crea automáticamente un `BigAutoField`
    (entero autoincremental) porque así está configurado DEFAULT_AUTO_FIELD.
    """

    # Razón social de la empresa, por ejemplo "Acme Industrial S.A.S.".
    # El primer argumento ("nombre") es el nombre legible que muestra el admin.
    nombre = models.CharField("nombre", max_length=255)

    # NIT o identificación tributaria. `unique=True` crea un índice único en
    # PostgreSQL, así que la base de datos rechaza dos empresas con el mismo NIT
    # aunque el código tenga un error. `error_messages` reemplaza el mensaje por
    # defecto de Django por uno en español, que es lo que verá el usuario cuando
    # se valide un formulario o serializer.
    identificacion = models.CharField(
        "identificación (NIT)",
        max_length=50,
        unique=True,
        error_messages={"unique": "Ya existe una empresa registrada con esta identificación."},
    )

    # Permite "desactivar" una empresa (por ejemplo, si termina el contrato)
    # sin borrarla, para no perder sus tickets ni su historial.
    activa = models.BooleanField("activa", default=True)

    # Fechas de auditoría que Django llena solo:
    # - auto_now_add=True: se guarda una única vez, al crear el registro.
    # - auto_now=True: se actualiza cada vez que se llama a save().
    created_at = models.DateTimeField("fecha de creación", auto_now_add=True)
    updated_at = models.DateTimeField("fecha de actualización", auto_now=True)

    class Meta:
        # Nombres en español que aparecen en el panel de administración.
        verbose_name = "empresa"
        verbose_name_plural = "empresas"
        # Orden por defecto de las consultas: alfabético por nombre.
        ordering = ["nombre"]

    def __str__(self) -> str:
        """Texto con el que se muestra la empresa (admin, shell, logs).

        Ejemplo: "Acme Industrial S.A.S. (900123456-7)".
        """
        return f"{self.nombre} ({self.identificacion})"


class RolChoices(models.TextChoices):
    """Roles posibles de un usuario (actores del Charter y del documento de arquitectura).

    Cada opción tiene dos partes: el valor que se guarda en la base de datos
    (por ejemplo "cliente") y la etiqueta legible que se muestra (por ejemplo
    "Cliente"). El frontend recibe y compara el valor guardado.
    """

    # Representante de la empresa cliente que reporta y consulta incidencias.
    CLIENTE = "cliente", "Cliente"
    # Personal interno de Datak.co que recibe, clasifica y registra tickets.
    AGENTE_SOPORTE = "agente_soporte", "Agente de soporte"
    # Desarrollador o equipo de producto al que se le asigna resolver el ticket.
    RESPONSABLE_ATENCION = "responsable_atencion", "Responsable de atención"


class UsuarioManager(BaseUserManager):
    """Administrador (manager) del modelo Usuario: crea usuarios y superusuarios.

    Django necesita un manager propio cuando el usuario no tiene el campo
    `username`. Este manager se usa con `Usuario.objects.create_user(...)` y lo
    llama el comando `python manage.py createsuperuser`.
    """

    # Permite que las migraciones serialicen este manager (requisito de Django).
    use_in_migrations = True

    def _create_user(self, correo, password, **extra_fields):
        """Lógica común de creación: valida el correo, cifra la contraseña y guarda."""
        if not correo:
            raise ValueError("El correo es obligatorio para crear un usuario.")
        # normalize_email pasa a minúsculas la parte del dominio
        # ("Ana@ACME.com" -> "Ana@acme.com") para evitar duplicados por mayúsculas.
        correo = self.normalize_email(correo)
        usuario = self.model(correo=correo, **extra_fields)
        # set_password guarda la contraseña cifrada (hash), nunca en texto plano.
        # Si password es None, el usuario queda sin contraseña utilizable.
        usuario.set_password(password)
        # full_clean ejecuta las validaciones del modelo (por ejemplo, que un
        # cliente tenga empresa) antes de guardar, para dar un error claro.
        usuario.full_clean(exclude=["password"])
        usuario.save(using=self._db)
        return usuario

    def create_user(self, correo, password=None, **extra_fields):
        """Crea un usuario normal (sin acceso al panel de administración)."""
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(correo, password, **extra_fields)

    def create_superuser(self, correo, password=None, **extra_fields):
        """Crea un superusuario con acceso total al panel /admin/.

        Un superusuario es personal interno de Datak.co, por eso por defecto se
        crea con rol `agente_soporte` y sin empresa (no pertenece a un cliente).
        """
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("rol", RolChoices.AGENTE_SOPORTE)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("El superusuario debe tener is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("El superusuario debe tener is_superuser=True.")

        return self._create_user(correo, password, **extra_fields)


class Usuario(AbstractBaseUser, PermissionsMixin):
    """Usuario del sistema (configurado como AUTH_USER_MODEL en config/settings.py).

    Hereda de:
    - AbstractBaseUser: aporta la contraseña cifrada (`password`), `last_login`
      y los métodos `set_password()` / `check_password()`.
    - PermissionsMixin: aporta `is_superuser`, grupos y permisos de Django.

    Los campos siguen la sección 3.2 de ARCHITECTURE_AND_DATA_MODEL_REFERENCE.md.
    El inicio de sesión se hace con `correo` + contraseña (no hay `username`).
    """

    # Correo con el que el usuario inicia sesión. Es único: no puede haber dos
    # usuarios con el mismo correo (lo garantiza un índice único en la base de datos).
    correo = models.EmailField(
        "correo electrónico",
        unique=True,
        error_messages={"unique": "Ya existe un usuario registrado con este correo."},
    )

    # Nombre completo de la persona, por ejemplo "Carlos Gómez".
    nombre = models.CharField("nombre completo", max_length=255)

    # Rol del usuario; solo acepta los valores definidos en RolChoices.
    # Por defecto un usuario nuevo es "cliente".
    rol = models.CharField(
        "rol",
        max_length=30,
        choices=RolChoices.choices,
        default=RolChoices.CLIENTE,
    )

    # Empresa a la que pertenece el usuario (el tenant).
    # - null=True / blank=True: el personal interno de Datak.co (agentes y
    #   responsables) no pertenece a una empresa cliente, así que puede quedar vacío.
    # - Para un `cliente` es OBLIGATORIA; eso se valida en clean() y con una
    #   restricción en la base de datos (ver Meta.constraints).
    # - on_delete=CASCADE: si se borra la empresa, se borran sus usuarios.
    # - related_name="usuarios": permite consultar `empresa.usuarios.all()`.
    empresa = models.ForeignKey(
        Empresa,
        verbose_name="empresa",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="usuarios",
    )

    # Indica si la cuenta está habilitada. Un usuario inactivo no puede iniciar
    # sesión. Equivale al `is_active` de Django (ver la propiedad is_active abajo).
    activo = models.BooleanField("activo", default=True)

    # Permite entrar al panel de administración de Django (/admin/).
    is_staff = models.BooleanField("acceso al admin", default=False)

    # Fecha en que se creó el usuario; Django la llena automáticamente.
    created_at = models.DateTimeField("fecha de creación", auto_now_add=True)

    # Conecta el modelo con su manager: Usuario.objects.create_user(...).
    objects = UsuarioManager()

    # Campo que Django usa como "nombre de usuario" para autenticar.
    # Por esto el login (JWT) recibe {"correo": ..., "password": ...}.
    USERNAME_FIELD = "correo"
    # Campo usado como correo en funciones de Django (p. ej. recuperar contraseña).
    EMAIL_FIELD = "correo"
    # Campos extra que pide `createsuperuser` además del correo y la contraseña.
    REQUIRED_FIELDS = ["nombre"]

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        ordering = ["correo"]
        constraints = [
            # Regla de negocio protegida también en la base de datos:
            # "si el rol es cliente, la empresa no puede estar vacía".
            # Se escribe como: (rol distinto de cliente) O (empresa no es nula).
            models.CheckConstraint(
                condition=~Q(rol="cliente") | Q(empresa__isnull=False),
                name="usuario_cliente_requiere_empresa",
                violation_error_message="Un usuario con rol cliente debe pertenecer a una empresa.",
            ),
        ]

    @property
    def is_active(self):
        """Traduce `activo` al nombre que esperan Django y SimpleJWT.

        Django y SimpleJWT revisan `user.is_active` para dejar o no iniciar
        sesión. Como en el modelo el campo se llama `activo` (en español, según el
        documento de arquitectura), esta propiedad devuelve ese mismo valor.
        """
        return self.activo

    @is_active.setter
    def is_active(self, value):
        # Permite escribir `usuario.is_active = False` y que se guarde en `activo`.
        self.activo = value

    def clean(self):
        """Validaciones de negocio que se ejecutan con full_clean() (formularios, admin)."""
        super().clean()
        # Normaliza el correo también cuando el usuario se edita desde el admin.
        self.correo = self.__class__.objects.normalize_email(self.correo)
        if self.rol == RolChoices.CLIENTE and self.empresa_id is None:
            raise ValidationError(
                {"empresa": "Un usuario con rol cliente debe pertenecer a una empresa."}
            )

    def __str__(self) -> str:
        """Texto con el que se muestra el usuario. Ejemplo: "Carlos Gómez <carlos@acme.com>"."""
        return f"{self.nombre} <{self.correo}>"


class ModuloContratado(models.Model):
    """Módulo funcional contratado y habilitado para una empresa cliente (tarea BE-04).

    Representa cada módulo del producto Datak.co que una empresa tiene activo
    (por ejemplo: INVENTARIO, NOMINA, VENTAS, FACTURACION, CONTABILIDAD).
    Al reportar un ticket (RF1, RF2, RF3), el cliente solo puede elegir entre
    los módulos contratados y activos de su propia empresa.

    Los campos siguen la sección 3.3 de ARCHITECTURE_AND_DATA_MODEL_REFERENCE.md.
    No se declara `id`: Django crea automáticamente un `BigAutoField` porque
    así está configurado `DEFAULT_AUTO_FIELD` en `config/settings.py`.
    """

    # Empresa propietaria del módulo contratado.
    # - on_delete=CASCADE: si se elimina la empresa, se eliminan sus módulos.
    # - related_name="modulos_contratados": permite consultar `empresa.modulos_contratados.all()`.
    empresa = models.ForeignKey(
        Empresa,
        verbose_name="empresa",
        on_delete=models.CASCADE,
        related_name="modulos_contratados",
    )

    # Identificador corto del módulo (p. ej. "FACTURACION", "INVENTARIO", "NOMINA").
    codigo = models.CharField("código", max_length=50)

    # Nombre legible para mostrar en el selector del portal y chatbot
    # (p. ej. "Facturación Electrónica", "Control de Inventarios").
    nombre = models.CharField("nombre", max_length=100)

    # Permite deshabilitar un módulo contratado sin perder el historial de tickets
    # asociados a él.
    activo = models.BooleanField("activo", default=True)

    class Meta:
        verbose_name = "módulo contratado"
        verbose_name_plural = "módulos contratados"
        ordering = ["nombre"]
        # Una misma empresa no puede tener dos veces el mismo código de módulo,
        # pero dos empresas distintas sí pueden contratar el mismo código.
        unique_together = ("empresa", "codigo")

    def __str__(self) -> str:
        """Texto con el que se muestra el módulo. Ejemplo: "Facturación Electrónica (FACTURACION)"."""
        return f"{self.nombre} ({self.codigo})"
