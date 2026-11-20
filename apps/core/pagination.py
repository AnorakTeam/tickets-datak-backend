"""Paginación estándar de las listas del API (RNF3).

"Paginar" es devolver una lista larga por partes (páginas) en vez de todo de una
vez, para que la respuesta sea rápida. El cliente pide la página con `?page=2`.
"""

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardResultsPagination(PageNumberPagination):
    """10 resultados por página y, además del formato normal de DRF, `total_pages`.

    Respuesta:
        {
          "count": 24,          # total de resultados
          "total_pages": 3,     # total de páginas (lo pide el issue #25)
          "next": "...?page=2", # link a la siguiente página o null
          "previous": null,     # link a la anterior o null
          "results": [...]      # los resultados de esta página
        }
    `count`, `next`, `previous` y `results` son los que ya usa el frontend.
    """

    page_size = 10

    def get_paginated_response(self, data):
        return Response(
            {
                "count": self.page.paginator.count,
                "total_pages": self.page.paginator.num_pages,
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "results": data,
            }
        )


class SupportInboxPagination(StandardResultsPagination):
    """Paginación explícita de 20 resultados por página para la bandeja unificada de soporte (BE-19, RF7)."""

    page_size = 20
