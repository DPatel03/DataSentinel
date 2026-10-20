"""Dashboard API tests."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from dashboard.api.main import app
from dashboard.api.routes import latest_eval_file

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "datasentinel-dashboard"
    assert body["status"] in ("ok", "degraded")
    assert "database" in body


def test_api_root() -> None:
    response = client.get("/api/")
    assert response.status_code == 200


def test_auth_token_protects_api(monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "secret-token")
    denied = client.get("/api/")
    assert denied.status_code == 401
    allowed = client.get("/api/", headers={"Authorization": "Bearer secret-token"})
    assert allowed.status_code == 200
    health = client.get("/api/health")
    assert health.status_code == 200


def test_sla_endpoint_shape() -> None:
    response = client.get("/api/stats/sla")
    assert response.status_code == 200
    body = response.json()
    assert "failure_rate_pct" in body
    assert "p95_latency_ms" in body
    assert "breached" in body
    assert "max_failure_rate_pct" in body


def test_missing_record_detail_is_404() -> None:
    response = client.get("/api/records/does-not-exist")
    assert response.status_code == 404


def test_latest_eval_reads_newest_snapshot(tmp_path: Path, monkeypatch) -> None:
    from dashboard.api import routes

    mlruns = tmp_path / "mlruns"
    mlruns.mkdir()
    old = mlruns / "eval_20260101_000000.json"
    new = mlruns / "eval_results.json"
    old.write_text(json.dumps({"classification_accuracy": 0.1}))
    new.write_text(json.dumps({"classification_accuracy": 0.97}))
    old.touch()
    new.touch()
    monkeypatch.setattr(routes, "MLRUNS", mlruns)

    chosen = latest_eval_file(mlruns)
    assert chosen is not None
    assert json.loads(chosen.read_text())["classification_accuracy"] == 0.97

    response = client.get("/api/eval/latest")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["results"]["classification_accuracy"] == 0.97
