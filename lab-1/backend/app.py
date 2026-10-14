import os
import time

import psycopg
from flask import Flask, jsonify, request


app = Flask(__name__)
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://labuser:labpassword@localhost:5432/labdb"
)
INSTANCE = os.environ.get("BACKEND_INSTANCE", "backend-1")


def get_connection():
    return psycopg.connect(DATABASE_URL)


def create_table():
    for attempt in range(20):
        try:
            with get_connection() as connection:
                with connection.cursor() as cursor:
                    # All Gunicorn workers and both backend containers start at
                    # nearly the same time. Serialize the one-time schema setup
                    # so concurrent CREATE TABLE statements cannot race inside
                    # PostgreSQL's system catalog.
                    cursor.execute("SELECT pg_advisory_xact_lock(104729)")
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS tasks (
                            id SERIAL PRIMARY KEY,
                            text VARCHAR(200) NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
            return
        except psycopg.OperationalError:
            if attempt == 19:
                raise
            time.sleep(2)


def read_tasks():
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, text, created_at FROM tasks ORDER BY id DESC")
            return cursor.fetchall()


@app.after_request
def add_instance_header(response):
    response.headers["X-Backend-Instance"] = INSTANCE
    return response


@app.get("/api/healthz")
def healthz():
    try:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
    except psycopg.Error:
        return jsonify(status="degraded", database="error", instance=INSTANCE), 503
    return jsonify(status="ok", database="ok", instance=INSTANCE)


@app.get("/api/tasks")
def tasks_api():
    try:
        rows = read_tasks()
    except psycopg.Error:
        return jsonify(error="База временно недоступна."), 503

    return jsonify(
        {
            "instance": INSTANCE,
            "tasks": [
                {"id": row[0], "text": row[1], "created_at": row[2].isoformat()}
                for row in rows
            ],
        }
    )


@app.post("/api/tasks")
def add_task():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify(error="Текст задачи не может быть пустым."), 400
    if len(text) > 200:
        return jsonify(error="Текст задачи не должен превышать 200 символов."), 400

    try:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO tasks (text) VALUES (%s) RETURNING id", (text,)
                )
                task_id = cursor.fetchone()[0]
    except psycopg.Error:
        return jsonify(error="База временно недоступна."), 503

    return jsonify(id=task_id, text=text, instance=INSTANCE), 201


create_table()

