"""Простые тесты для API списка задач."""
import os
import sys
from unittest.mock import patch, MagicMock

# Мокаем psycopg.connect ДО импорта app, чтобы app.py не пошёл в реальную БД
fake_conn = MagicMock()
fake_conn.__enter__.return_value = fake_conn
fake_conn.__exit__.return_value = False
fake_conn.execute.return_value.fetchone.return_value = (1,)

os.environ.setdefault("DATABASE_URL", "postgresql://fake:fake@localhost:5432/fake")

import psycopg
psycopg.connect = MagicMock(return_value=fake_conn)

import pytest
import app as app_module


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


def test_health_endpoint(client):
    """ /api/healthz должен отвечать 200 и правильным JSON. """
    response = client.get("/api/healthz")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"
    assert data["database"] == "ok"   # ← специально сломано


def test_add_task_rejects_empty_text(client):
    """ Пустой текст должен приводить к 400. """
    response = client.post("/api/tasks", json={"text": ""})
    assert response.status_code == 400


def test_add_task_rejects_too_long_text(client):
    """ Текст длиннее 200 символов должен приводить к 400. """
    response = client.post("/api/tasks", json={"text": "x" * 201})
    assert response.status_code == 400