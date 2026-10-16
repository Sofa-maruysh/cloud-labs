"""Воспроизводимые опыты lab-2. Нужны Python 3.10+, Docker и curl."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
BASE = "http://127.0.0.1:5052"
LOCK = threading.Lock()
CURRENT = None
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def emit(message):
    with LOCK:
        print(message, flush=True)
        if CURRENT:
            with CURRENT.open("a", encoding="utf-8") as f:
                f.write(str(message) + "\n")


def begin(name):
    global CURRENT
    EVIDENCE.mkdir(exist_ok=True)
    CURRENT = EVIDENCE / (name + ".txt")
    CURRENT.write_text("", encoding="utf-8")
    emit("Опыт: " + name)
    emit(datetime.now(timezone(timedelta(hours=3))).isoformat())


def run(*args, ok=True, quiet=False):
    emit("$ " + subprocess.list2cmdline(args))
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    output = result.stdout + result.stderr
    if output.strip() and not quiet:
        emit(output.rstrip())
    emit("exit_code=" + str(result.returncode))
    if ok and result.returncode:
        raise RuntimeError("Команда не прошла: " + subprocess.list2cmdline(args))
    return output


def compose(*args, overlay=None, **kwargs):
    files = ["-f", "compose.yaml"]
    if overlay:
        files += ["-f", overlay]
    return run("docker", "compose", *files, *args, **kwargs)


def cid(service):
    return compose("ps", "-a", "-q", service, quiet=True).strip()


def inspect(container):
    return json.loads(run("docker", "inspect", container, quiet=True))[0]


def request(path, payload=None):
    data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as response:
        return response.status, json.load(response)


def wait_ready(timeout=90):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if request("/api/healthz")[0] == 200:
                return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(1)
    raise RuntimeError("API не стало готовым")


def curl(path):
    return run("curl", "-sS", "--max-time", "12", "-w", "\\nHTTP %{http_code}\\n", BASE + path, ok=False)


def images():
    begin("01-images-cache")
    run("docker", "version")
    run("docker", "compose", "version")
    code = ROOT / "backend/app.py"
    original = code.read_bytes()
    measurements = []
    try:
        for kind, file in [("bad", "Dockerfile.bad"), ("good", "Dockerfile")]:
            t = time.perf_counter()
            run("docker", "build", "--progress=plain", "-f", "backend/" + file,
                "-t", "cloud-lab2-backend:" + kind, "backend")
            emit(f"Первичная сборка {kind}: {time.perf_counter() - t:.3f} s")
        for trial in range(1, 4):
            # Ровно одна строка кода меняется в одинаковом контексте обоих образов.
            changed = original.decode().replace('APP_LABEL = "Список задач"',
                                                 f'APP_LABEL = "Список задач, замер {trial}"')
            code.write_text(changed, encoding="utf-8", newline="\n")
            for kind, file in [("bad", "Dockerfile.bad"), ("good", "Dockerfile")]:
                t = time.perf_counter()
                run("docker", "build", "--progress=plain", "-f", "backend/" + file,
                    "-t", "cloud-lab2-backend:" + kind, "backend")
                seconds = time.perf_counter() - t
                measurements.append({"trial": trial, "image": kind, "seconds": round(seconds, 3)})
                emit(f"Пересборка {kind}, замер {trial}: {seconds:.3f} s")
    finally:
        code.write_bytes(original)
    for kind, file in [("bad", "Dockerfile.bad"), ("good", "Dockerfile")]:
        run("docker", "build", "--progress=plain", "-f", "backend/" + file,
            "-t", "cloud-lab2-backend:" + kind, "backend")
    sizes = {}
    for kind in ("bad", "good"):
        sizes[kind] = json.loads(run("docker", "image", "inspect", "cloud-lab2-backend:" + kind, quiet=True))[0]["Size"]
        emit(f"Размер {kind}: {sizes[kind]} bytes = {sizes[kind]/1024/1024:.2f} MiB")
    result = {"builds": measurements, "size_bytes": sizes,
              "median_seconds": {kind: statistics.median(m["seconds"] for m in measurements if m["image"] == kind) for kind in ("bad", "good")}}
    (EVIDENCE / "images.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    emit(json.dumps(result, indent=2))
    assert sizes["good"] < sizes["bad"]


def start():
    begin("02-start")
    compose("config", "--quiet")
    compose("up", "-d", "--build", "--wait", "--wait-timeout", "120")
    wait_ready()
    compose("ps")
    curl("/api/healthz")


def check():
    begin("03-checks")
    for service in ("backend", "frontend"):
        compose("exec", "-T", service, "whoami")
    compose("exec", "-T", "backend", "sh", "-c", "test ! -e /app/notes-demo.txt && echo 'notes-demo.txt excluded'")
    run("docker", "run", "--rm", "--entrypoint", "sh", "cloud-lab2-backend:bad", "-c", "whoami; ls /app/notes-demo.txt")
    db = cid("db")
    before = inspect(db)
    emit("db networks=" + str(list(before["NetworkSettings"]["Networks"])))
    emit("frontend networks=" + str(list(inspect(cid("frontend"))["NetworkSettings"]["Networks"])))
    compose("exec", "-T", "backend", "python", "-c",
            "import socket; s=socket.create_connection(('db',5432),2); print('backend -> db: connected'); s.close()")
    compose("exec", "-T", "frontend", "sh", "-c", "nc -w 2 db 5432 < /dev/null", ok=False)
    ip = next(iter(before["NetworkSettings"]["Networks"].values()))["IPAddress"]
    compose("exec", "-T", "frontend", "sh", "-c", "nc -w 2 " + ip + " 5432 < /dev/null", ok=False)
    status, task = request("/api/tasks", {"text": "Проверить, что задача переживёт удаление контейнера БД"})
    emit(f"POST /api/tasks HTTP {status}: {json.dumps(task, ensure_ascii=False)}")
    assert status == 201
    emit("GET before=" + json.dumps(request("/api/tasks")[1], ensure_ascii=False))
    emit("Удаляем только контейнер lab-2. Именованный том остаётся.")
    compose("stop", "db")
    compose("rm", "-f", "db")
    compose("up", "-d", "db", "--wait", "--wait-timeout", "90")
    wait_ready()
    after = inspect(cid("db"))
    emit("db container before=" + before["Id"])
    emit("db container after =" + after["Id"])
    emit("volume before=" + before["Mounts"][0]["Name"])
    emit("volume after =" + after["Mounts"][0]["Name"])
    tasks = request("/api/tasks")[1]
    emit("GET after=" + json.dumps(tasks, ensure_ascii=False))
    assert before["Id"] != after["Id"]
    assert before["Mounts"][0]["Name"] == after["Mounts"][0]["Name"]
    assert any(t["id"] == task["id"] and t["text"] == task["text"] for t in tasks)
    # Ошибка данных не превращается в 500 или запись пустой задачи.
    try:
        request("/api/tasks", {"text": ""})
        raise AssertionError("Пустую задачу приняли")
    except urllib.error.HTTPError as e:
        emit("POST empty task: HTTP " + str(e.code))
        assert e.code == 400
    compose("ps")
    curl("/api/tasks")
    emit("PASS: пользователь, ignore, сеть, том, чтение/запись, валидация")


def recovery():
    begin("04-recovery")
    compose("up", "-d", "db", "--wait", "--wait-timeout", "90")
    wait_ready()
    # Даём Docker включить наблюдение restart policy после успешного старта.
    time.sleep(11)
    db, backend = cid("db"), cid("backend")
    before = inspect(db)
    emit("db RestartCount before=" + str(before["RestartCount"]))
    # SIGQUIT у PostgreSQL запускает immediate shutdown (аварийная остановка).
    # SIGKILL из того же PID namespace не убивает init/PID 1.
    t = time.perf_counter()
    run("docker", "exec", "--user", "postgres", db, "sh", "-c", "kill -QUIT 1", ok=False)
    curl("/healthz")
    curl("/api/healthz")
    deadline = time.monotonic() + 30
    while inspect(db)["RestartCount"] == before["RestartCount"]:
        if time.monotonic() > deadline:
            raise RuntimeError("Docker не перезапустил БД")
        time.sleep(1)
    wait_ready()
    seconds = time.perf_counter() - t
    after = inspect(db)
    emit("db same container=" + str(before["Id"] == after["Id"]))
    emit("db RestartCount after=" + str(after["RestartCount"]))
    emit("backend same container=" + str(backend == cid("backend")))
    assert after["RestartCount"] > before["RestartCount"]
    assert backend == cid("backend")
    emit(f"API восстановилось за {seconds:.3f} s (с шагом опроса 1 s)")
    curl("/api/healthz")
    curl("/api/tasks")
    compose("ps")
    compose("logs", "--tail", "35", "db", "backend")
    (EVIDENCE / "recovery.json").write_text(json.dumps({"seconds":round(seconds,3), "db_restarts_before":before["RestartCount"], "db_restarts_after":after["RestartCount"]}, indent=2), encoding="utf-8")


def sql(query):
    return compose("exec", "-T", "db", "psql", "-U", "labuser", "-d", "labdb", "-c", query)


def seed():
    begin("05-load-data")
    sql("DELETE FROM tasks WHERE text LIKE '[load] %'; INSERT INTO tasks(text) SELECT '[load] ' || i || ' ' || repeat('x',170) FROM generate_series(1,2000) i;")
    sql("SELECT count(*) AS tasks_for_load FROM tasks;")


def cpu_stat(container):
    text = run("docker", "exec", container, "cat", "/sys/fs/cgroup/cpu.stat")
    return {k: int(v) for k, v in (line.split() for line in text.splitlines())}


def load(label, count=120, concurrency=8):
    begin("06-load-" + label)
    container = cid("backend")
    cfg = inspect(container)["HostConfig"]
    emit("limits=" + json.dumps({k: cfg[k] for k in ("NanoCpus","Memory","MemorySwap")}))
    before = cpu_stat(container)
    initial = inspect(container)["RestartCount"]
    stop = threading.Event()
    samples = []
    def monitor():
        while not stop.is_set():
            result = run("docker", "stats", "--no-stream", "--format", "{{json .}}", cid_for_monitor,
                         "cloud-lab2-db-1", "cloud-lab2-frontend-1", ok=False)
            samples.extend(json.loads(line) for line in result.splitlines() if line.startswith("{"))
            stop.wait(1)
    cid_for_monitor = container
    watcher = threading.Thread(target=monitor, daemon=True)
    watcher.start()
    def one(_):
        started = time.perf_counter()
        try:
            status, data = request("/api/tasks")
            return status, time.perf_counter()-started, len(data)
        except urllib.error.HTTPError as e:
            return e.code, time.perf_counter()-started, 0
        except OSError:
            return 0, time.perf_counter()-started, 0
    t = time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            results = list(pool.map(one, range(count)))
        finished = time.perf_counter()
    finally:
        stop.set()
        watcher.join(timeout=8)
    seconds = finished-t
    after = cpu_stat(container)
    latencies = sorted(r[1] for r in results)
    statuses = {str(s): sum(1 for r in results if r[0] == s) for s in set(r[0] for r in results)}
    output = {"label":label, "requests":count, "concurrency":concurrency, "seconds":round(seconds,3),
              "rps":round(count/seconds,2), "http_statuses":statuses,
              "p50_seconds":round(statistics.median(latencies),3), "p95_seconds":round(latencies[int(.95*(len(latencies)-1))],3),
              "rows_per_response":max(r[2] for r in results),
              "cpu_stat_delta":{k:after[k]-before[k] for k in before},
              "restarts_before":initial, "restarts_after":inspect(container)["RestartCount"], "stats":samples}
    emit(json.dumps(output, indent=2, ensure_ascii=False))
    (EVIDENCE / ("load-" + label + ".json")).write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    memory_text = run("docker", "exec", container, "cat", "/sys/fs/cgroup/memory.events")
    memory_events = {k: int(v) for k, v in (line.split() for line in memory_text.splitlines())}
    if label == "stable":
        assert statuses == {"200": count} and initial == output["restarts_after"]
        assert memory_events["oom_kill"] == 0


def tight():
    begin("07-cpu-limits")
    compose("up", "-d", "--force-recreate", "backend", "--wait", "--wait-timeout", "120")
    wait_ready()
    # Сначала стартуем при обычном лимите: 0.05 CPU затягивает даже импорт Python.
    run("docker", "update", "--cpus", "0.5", cid("backend"))
    wait_ready()
    run("docker", "update", "--cpus", "0.1", cid("backend"))
    load("tight-cpu")


def oom():
    begin("08-oom")
    run("docker", "update", "--cpus", "0.5", "--memory", "256m", "--memory-swap", "256m", cid("backend"))
    compose("up", "-d", "--wait", "--wait-timeout", "120")
    wait_ready()
    container = cid("backend")
    initial = inspect(container)["RestartCount"]
    since = int(time.time())
    # Меняем лимит уже работающего сервиса: запросы идут во время опыта.
    emit("Запускаем запросы к реальному API, затем снижаем память до 32 MiB.")
    stop = threading.Event()
    statuses = []
    def pressure():
        while not stop.is_set():
            try:
                statuses.append(request("/api/tasks")[0])
            except urllib.error.HTTPError as e:
                statuses.append(e.code)
            except OSError:
                statuses.append(0)
    workers = [threading.Thread(target=pressure, daemon=True) for _ in range(8)]
    for worker in workers:
        worker.start()
    try:
        run("docker", "update", "--memory", "32m", "--memory-swap", "32m", container)
        for _ in range(5):
            run("docker", "stats", "--no-stream", container, ok=False)
            state = inspect(container)
            emit("state=" + json.dumps(state["State"]) + ", RestartCount=" + str(state["RestartCount"]))
            run("docker", "exec", container, "cat", "/sys/fs/cgroup/memory.events", ok=False)
            time.sleep(1)
    finally:
        stop.set()
        for worker in workers:
            worker.join(timeout=16)
        until = int(time.time()) + 1
        events = run("docker", "events", "--since", str(since), "--until", str(until),
                     "--filter", "container=" + container, "--format", "{{json .}}")
        emit("HTTP statuses=" + json.dumps({str(s):statuses.count(s) for s in set(statuses)}))
        compose("logs", "--tail", "60", "backend")
        state = inspect(container)
        summary = {"initial_restarts":initial, "final_restarts":state["RestartCount"],
                   "oom_events":sum(1 for line in events.splitlines() if '"Action":"oom"' in line),
                   "statuses":{str(s):statuses.count(s) for s in set(statuses)}}
        emit("OOM summary=" + json.dumps(summary))
        (EVIDENCE / "oom.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        run("docker", "update", "--memory", "256m", "--memory-swap", "256m", container)
        compose("up", "-d", "--wait", "--wait-timeout", "120")
        wait_ready()
        curl("/api/healthz")
    assert summary["oom_events"] > 0, "Нужен настоящий OOM event, а не только ошибка HTTP"


def stable():
    begin("09-final-limits")
    run("docker", "update", "--cpus", "0.5", "--memory", "256m", "--memory-swap", "256m", cid("backend"))
    compose("up", "-d", "--force-recreate", "backend", "--wait", "--wait-timeout", "120")
    compose("up", "-d", "--wait", "--wait-timeout", "120")
    wait_ready()
    load("stable")


def clean():
    begin("10-final")
    sql("DELETE FROM tasks WHERE text LIKE '[load] %';")
    compose("ps")
    for service in ("db", "backend", "frontend"):
        state = inspect(cid(service))
        cfg = state["HostConfig"]
        emit(service + " " + json.dumps({"health":state["State"]["Health"]["Status"], "restart":cfg["RestartPolicy"], "cpu":cfg["NanoCpus"]/1e9, "memory_mib":cfg["Memory"]/1024/1024, "networks":list(state["NetworkSettings"]["Networks"])}))
    curl("/api/healthz")
    curl("/api/tasks")


def bad():
    begin("11-bad-image-run")
    compose("run", "-d", "--rm", "--no-deps", "--name", "cloud-lab2-bad-demo", "backend", overlay="compose.bad.yaml")
    try:
        time.sleep(8)
        compose("exec", "-T", "backend", "python", "-c", "import urllib.request; r=urllib.request.urlopen('http://cloud-lab2-bad-demo:5000/api/healthz',timeout=10); print('bad API HTTP',r.status); print(r.read().decode())")
        run("docker", "exec", "cloud-lab2-bad-demo", "whoami")
        run("docker", "inspect", "cloud-lab2-bad-demo", "--format", "health={{json .Config.Healthcheck}} user={{json .Config.User}}")
    finally:
        run("docker", "stop", "cloud-lab2-bad-demo")


def metadata():
    begin("12-environment-images")
    run("docker", "info", "--format", "CPUs={{.NCPU}} Memory={{.MemTotal}} Architecture={{.Architecture}}")
    run("docker", "image", "ls", "cloud-lab2-backend")
    for kind in ("bad", "good"):
        run("docker", "image", "inspect", "cloud-lab2-backend:" + kind, "--format", "content_bytes={{.Size}} user={{json .Config.User}} health={{json .Config.Healthcheck}}")
    compose("exec", "-T", "backend", "python", "--version")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=["images","start","check","recovery","seed","tight","oom","stable","clean","bad","metadata"])
    args = parser.parse_args()
    os.chdir(ROOT)
    globals()[args.step]()
