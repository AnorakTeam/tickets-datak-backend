"""Permisos de Django REST Framework basados en el rol del usuario.

Un "permiso" de DRF decide si una petición puede usar un endpoint. Se aplica en
una vista con `permission_classes = [...]`; si devuelve False, DRF responde 403
(o 401 si el usuario no envió token).
"""

from rest_framework.permissions import BasePermission

from apps.companies.models import RolChoices


class IsClientUser(BasePermission):
    """Solo deja pasar a usuarios con rol `cliente` que pertenecen a una empresa.

    Se usa en los endpoints del portal del cliente (por ejemplo "Mis tickets").
    El personal interno (agentes y responsables) usa otros endpoints.
    """

    # Mensaje en español que DRF devuelve en la respuesta 403.
    message = "Solo los usuarios con rol cliente pueden acceder a este recurso."

    def has_permission(self, request, view):
        usuario = request.user
        return bool(
            usuario
            and usuario.is_authenticated
            and usuario.rol == RolChoices.CLIENTE
            # Por la restricción del modelo un cliente siempre tiene empresa,
            # pero se revisa igual para no filtrar con empresa vacía nunca.
            and usuario.empresa_id is not None
        )


class IsInternalSupportUser(BasePermission):
    """Permite el acceso únicamente al personal interno (`agente_soporte` o `responsable_atencion`).

    Se utiliza en los endpoints de la consola interna de soporte (`/api/v1/support/...`,
    tarea BE-19, RF7). Cualquier usuario con rol `cliente` recibe `403 Forbidden`.
    """

    message = "Solo el personal interno de soporte puede acceder a este recurso."

    def has_permission(self, request, view):
        usuario = request.user
        return bool(
            usuario
            and usuario.is_authenticated
            and usuario.rol in (RolChoices.AGENTE_SOPORTE, RolChoices.RESPONSABLE_ATENCION)
        )


class IsSupportAgentUser(BasePermission):
    """Permite el acceso exclusivamente a usuarios autenticados con rol `agente_soporte`.

    Se utiliza para acciones exclusivas de agentes de soporte como registrar
    tickets en nombre del cliente por canales externos (`POST /api/v1/support/tickets/`,
    tarea BE-20, RF9).
    """

    message = "Solo los agentes de soporte pueden realizar esta acción."

    def has_permission(self, request, view):
        usuario = request.user
        return bool(
            usuario and usuario.is_authenticated and usuario.rol == RolChoices.AGENTE_SOPORTE
        )
