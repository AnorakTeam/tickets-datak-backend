"""Models for the companies application (multi-tenant boundary)."""

from django.db import models


class Empresa(models.Model):
    """Tenant model representing client companies."""

    id = models.BigAutoField(primary_key=True)
    nombre = models.CharField(max_length=200, help_text="Nombre legal o comercial de la empresa")
    identificacion = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="NIT o número de identificación tributaria único",
    )
    activa = models.BooleanField(
        default=True,
        help_text="Indica si la empresa tiene acceso activo al sistema de soporte",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "empresas"
        verbose_name = "Empresa"
        verbose_name_plural = "Empresas"
        ordering = ["nombre"]

    def __str__(self) -> str:
        return f"{self.nombre} ({self.identificacion})"

    @property
    def nit(self) -> str:
        """Alias for identificacion."""
        return self.identificacion

    @property
    def created_at(self):
        """English alias for fecha_creacion."""
        return self.fecha_creacion

    @property
    def updated_at(self):
        """English alias for fecha_actualizacion."""
        return self.fecha_actualizacion
