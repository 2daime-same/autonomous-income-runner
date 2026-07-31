from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_service_and_health_endpoints():
    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["domain_count"] == 8
    assert root.json()["directed_pair_count"] >= 50

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"


def test_domains_and_units_catalog():
    response = client.get("/domains")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 8
    assert {domain["code"] for domain in data["domains"]} == {
        "length",
        "force_torque",
        "pressure",
        "temperature",
        "electrical",
        "flow",
        "thermal",
        "mass_density",
    }

    units = client.get("/units", params={"domain": "mass-density"})
    assert units.status_code == 200
    assert units.json()["domain"] == "mass_density"
    assert any(unit["code"] == "kg_m3" for unit in units.json()["units"])


@pytest.mark.parametrize(
    ("domain", "source", "target", "value", "expected"),
    [
        ("length", "in", "mm", "2", 50.8),
        ("force_torque", "lbf", "N", "1", 4.4482216152605),
        ("pressure", "bar", "kPa", "1", 100.0),
        ("temperature", "C", "F", "100", 212.0),
        ("electrical", "kWh", "J", "1", 3_600_000.0),
        ("flow", "L_min", "m3_h", "60", 3.6),
        ("thermal", "kcal", "kJ", "1", 4.184),
        ("mass_density", "lb", "kg", "1", 0.45359237),
    ],
)
def test_get_conversion_for_every_domain(domain, source, target, value, expected):
    response = client.get(
        "/convert",
        params={"domain": domain, "from_unit": source, "to_unit": target, "value": value},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["domain"] == domain
    assert payload["result"] == pytest.approx(expected, rel=1e-12, abs=1e-12)
    assert payload["result_text"]


def test_post_conversion():
    response = client.post(
        "/convert",
        json={"domain": "temperature", "from_unit": "F", "to_unit": "C", "value": "32"},
    )
    assert response.status_code == 200
    assert response.json()["result"] == pytest.approx(0.0, abs=1e-12)


def test_unknown_domain_and_unit_are_404():
    response = client.get(
        "/convert",
        params={"domain": "alchemy", "from_unit": "lead", "to_unit": "gold", "value": 1},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "unknown_domain"

    response = client.get(
        "/convert",
        params={"domain": "length", "from_unit": "furlong", "to_unit": "m", "value": 1},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "unknown_unit"


def test_incompatible_units_are_422():
    response = client.post(
        "/convert",
        json={"domain": "electrical", "from_unit": "V", "to_unit": "ohm", "value": 1},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "incompatible_units"


def test_validation_rejects_non_finite_and_extra_fields():
    response = client.post(
        "/convert",
        json={"domain": "length", "from_unit": "m", "to_unit": "km", "value": "NaN"},
    )
    assert response.status_code == 422

    response = client.post(
        "/convert",
        json={"domain": "length", "from_unit": "m", "to_unit": "km", "value": 1, "surprise": True},
    )
    assert response.status_code == 422


def test_openapi_exposes_required_routes():
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert {"/health", "/domains", "/units", "/convert"}.issubset(paths)
