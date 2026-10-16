"""Простые тесты для API списка задач."""
import os
import pytest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://fake:fake@localhost:5432/fake")

import app as app_module


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


def test_health_endpoint(client):
    """ /api/healthz должен отвечать 200 и правильным JSON. """
    with patch.object(app_module, "get_connection") as mock_conn:
        mock_conn.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = (1,)
        response = client.get("/api/healthz")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "ok"
        assert data["database"] == "СЛОМАНО"


def test_add_task_rejects_empty_text(client):
    """ Пустой текст должен приводить к 400. """
    response = client.post("/api/tasks", json={"text": ""})
    assert response.status_code == 400


def test_add_task_rejects_too_long_text(client):
    """ Текст длиннее 200 символов должен приводить к 400. """
    response = client.post("/api/tasks", json={"text": "x" * 201})
    assert response.status_code == 400