"""API списка задач из lab-0, теперь отдельно от фронтенда."""
import os
import time

import psycopg
from flask import Flask, jsonify, request

app = Flask(__name__)
DATABASE_URL = os.environ["DATABASE_URL"]
APP_LABEL = "Список задач"


def get_connection():
    # Новое соединение на запрос: после перезапуска БД нет старого сокета.
    for attempt in range(3):
        try:
            return psycopg.connect(DATABASE_URL, connect_timeout=2)
        except psycopg.OperationalError:
            if attempt == 2:
                raise
            time.sleep(0.3)


def create_table():
    for attempt in range(15):
        try:
            with get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS tasks (
                        id SERIAL PRIMARY KEY,
                        text VARCHAR(200) NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            return
        except psycopg.OperationalError:
            if attempt == 14:
                raise
            time.sleep(1)


@app.errorhandler(psycopg.OperationalError)
def database_unavailable(error):
    app.logger.warning("База временно недоступна: %s", type(error).__name__)
    return jsonify(error="База временно недоступна. Попробуйте ещё раз."), 503


@app.get("/healthz")
@app.get("/api/healthz")
def health():
    with get_connection() as conn:
        conn.execute("SELECT 1").fetchone()
    return jsonify(status="ok", database="ok")


@app.get("/api/tasks")
def get_tasks():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, text, created_at FROM tasks ORDER BY id DESC"
        ).fetchall()
    return jsonify([
        {"id": row[0], "text": row[1], "created_at": row[2].isoformat()}
        for row in rows
    ])


@app.post("/api/tasks")
def add_task():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
        return jsonify(error="Передайте текст задачи."), 400
    text = payload["text"].strip()
    if not 1 <= len(text) <= 200:
        return jsonify(error="Длина задачи должна быть от 1 до 200 символов."), 400
    with get_connection() as conn:
        row = conn.execute(
            "INSERT INTO tasks (text) VALUES (%s) RETURNING id, text, created_at",
            (text,),
        ).fetchone()
    return jsonify(id=row[0], text=row[1], created_at=row[2].isoformat()), 201


# При импорте gunicorn тоже создаёт таблицу, как запуск app.py в lab-0.
try:
    create_table()
except Exception as e:
    print(f"create_table warning: {e}")