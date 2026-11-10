import pytest
from django.urls import reverse
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_health_check_endpoint():
    client = APIClient()
    url = reverse("health-check")
    response = client.get(url)
    assert response.status_code == 200
    assert response.data == {"status": "ok", "service": "tickets-datak-backend", "version": "1.0.0"}
