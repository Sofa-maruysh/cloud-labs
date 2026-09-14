import os
import time

import psycopg
from flask import Flask, jsonify, redirect, render_template, request, url_for

app = Flask(__name__)
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://labuser:labpassword@localhost:5432/labdb"
)


def get_connection():
    return psycopg.connect(DATABASE_URL)


def create_table():
    for attempt in range(10):
        try:
            with get_connection() as connection:
                with connection.cursor() as cursor:
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
            if attempt == 9:
                raise
            time.sleep(2)


def get_tasks():
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, text, created_at FROM tasks ORDER BY id DESC")
            return cursor.fetchall()


@app.get("/")
def index():
    return render_template("index.html", tasks=get_tasks())


@app.post("/tasks")
def add_task():
    text = request.form.get("text", "").strip()
    if text:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO tasks (text) VALUES (%s)", (text,))
    return redirect(url_for("index"))


@app.get("/api/tasks")
def tasks_api():
    tasks = get_tasks()
    return jsonify(
        [
            {"id": task[0], "text": task[1], "created_at": task[2].isoformat()}
            for task in tasks
        ]
    )


if __name__ == "__main__":
    create_table()
    app.run(host="0.0.0.0", port=5000)

