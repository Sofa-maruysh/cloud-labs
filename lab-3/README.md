# Лабораторная работа 2 - Docker и устойчивый стек

Список задач из [лабы 0](../lab-0), разделённый на три контейнера: nginx с фронтендом, Flask с API и PostgreSQL.

Полный ход работы, неудачные попытки, вывод команд и результаты замеров - в [report.md](report.md).

## Запуск

Нужен запущенный Docker Desktop с Linux-контейнерами и Docker Compose v2 или новее. Для скрипта опытов дополнительно нужны Python 3.10+ и `curl`. Python-пакеты на компьютере устанавливать не нужно.

Из корня репозитория:

```bash
cd lab-2
docker compose up --build -d --wait
```

Открыть <http://localhost:5052>, добавить задачу и обновить страницу. API доступно через фронтенд: `GET /api/tasks`, `POST /api/tasks` с JSON `{"text":"Новая задача"}`, `GET /api/healthz`.

```bash
docker compose ps
curl http://localhost:5052/api/healthz
docker compose logs --tail 30
```

В нормальном состоянии все три контейнера `healthy`. Наружу опубликован только `127.0.0.1:5052`. У БД и бэкенда внешних портов нет.

В Compose задан учебный локальный пароль. При желании можно скопировать `.env.example` в `.env` и заменить его до первого запуска. Для этого примера используйте буквы и цифры, чтобы пароль не требовал экранирования в URL. Изменение переменной не меняет пароль уже созданной БД.

## Файлы

| Файл / папка | Зачем нужен |
| --- | --- |
| [backend/Dockerfile.bad](backend/Dockerfile.bad) | Работающий учебный антипример с шестью плохими практиками |
| [backend/Dockerfile](backend/Dockerfile) | Хороший образ: slim, digest, две стадии, кеш, отдельный пользователь, healthcheck |
| [backend/.dockerignore](backend/.dockerignore) | В сборку хорошего образа идут только нужные файлы |
| [frontend](frontend) | Та же страница списка задач, теперь статика и запросы к API |
| [compose.yaml](compose.yaml) | Три сервиса, две сети, том, healthchecks, restart и финальные лимиты |
| [compose.bad.yaml](compose.bad.yaml) | Временный запуск плохого образа для проверки API |
| [compose.cpu-tight.yaml](compose.cpu-tight.yaml) | Пример тесного CPU-лимита для ручного эксперимента |
| [compose.oom.yaml](compose.oom.yaml) | Пример заведомо тесной памяти 32 MiB |
| [scripts/lab.py](scripts/lab.py) | Повторение всех опытов с сохранением вывода |
| [evidence](evidence) | Реальные логи и JSON с результатами |
| [screenshots](screenshots) | Скриншот работающего приложения |

## Как повторить проверки

Команды ниже выполняются из `lab-2`. На Windows `python` можно заменить на `py -3`, на Linux/macOS - на `python3`.

```bash
python scripts/lab.py images
python scripts/lab.py start
python scripts/lab.py bad
python scripts/lab.py check
python scripts/lab.py recovery
python scripts/lab.py seed
python scripts/lab.py tight
python scripts/lab.py oom
python scripts/lab.py stable
python scripts/lab.py clean
python scripts/lab.py metadata
```

`images` меняет ровно одну строку `APP_LABEL` для каждого из трёх замеров, а затем возвращает файл к исходному содержимому. Сначала прогревается кеш обоих образов. Измеряется вся команда `docker build` через монотонный таймер Python. Полный BuildKit-вывод сохраняется.

`check` создаёт проверочную задачу, удаляет **только контейнер БД этого проекта**, пересоздаёт его и сравнивает запись и имя тома. Заодно проверяет пользователя, `.dockerignore`, доступ бэкенда к БД и отсутствие доступа у фронтенда.

`recovery` отправляет PostgreSQL аварийный `SIGQUIT` изнутри контейнера. Проверяет рост `RestartCount`, прежний ID бэкенда и успешный `curl`. `docker stop` и `docker kill` для этого опыта не подходят: Docker воспринимает их как ручную остановку.

`seed` добавляет 2000 строк с префиксом `[load]`. `tight` и `stable` отправляют по 120 запросов к **настоящему API** из восьми параллельных клиентов. Каждый ответ содержит весь список, то есть бэкенд читает PostgreSQL и собирает JSON. Скрипт снимает `docker stats` и разницу `cpu.stat` до/после.

`oom` снижает память уже работающего бэкенда до 32 MiB во время запросов, сохраняет Docker OOM-события и возвращает лимит 256 MiB. `stable` возвращает CPU 0.5, пересоздаёт бэкенд и проверяет, что все запросы прошли с HTTP 200, перезапусков и OOM не было. `clean` удаляет только строки с префиксом `[load]` и оставляет обычные задачи.

Повторный запуск перезаписывает соответствующие логи в `evidence/`, поэтому для новых опытов стоит сохранить старые результаты отдельно. Лимиты CPU и памяти действуют только внутри контейнеров `cloud-lab2`.

## Остановка и возврат к обычному запуску

```bash
docker compose down
```

Именованный том `cloud-lab2_postgres_data` остаётся, поэтому при новом запуске задачи вернутся.

Если вручную меняли лимиты через `docker update` или запускали дополнительные Compose-файлы, вернуть параметры основного файла можно так:

```bash
docker compose up -d --force-recreate --wait
```

Удалять том для обычной остановки не нужно. Команда `docker compose down -v` удалит и данные лабораторной.
