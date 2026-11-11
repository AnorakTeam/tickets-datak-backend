"""Modelos de la app `companies`.

Esta app contiene la entidad `Empresa`, que es el "tenant" del sistema
(multi-tenant): cada cliente de Datak.co es una empresa y todos sus datos
(usuarios, módulos contratados, tickets) cuelgan de ella. Así se garantiza
que una empresa nunca vea la información de otra (requisito RNF2).
"""

from django.db import models


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
