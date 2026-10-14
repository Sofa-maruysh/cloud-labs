#!/usr/bin/env bash
set -uo pipefail

# Git Bash rewrites POSIX-looking arguments such as /api/tasks before passing
# them to Windows executables. Docker must receive the container path unchanged.
export MSYS_NO_PATHCONV=1

ROOT_MSYS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if command -v cygpath >/dev/null 2>&1; then
    COMPOSE_FILE="$(cygpath -m "$ROOT_MSYS/compose.yaml")"
else
    COMPOSE_FILE="$ROOT_MSYS/compose.yaml"
fi

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

BASE_HTTP="http://127.0.0.1"
BASE_HTTPS="https://127.0.0.1"
PASS=0
FAIL=0
BACKEND_2_STOPPED=0

ok() { echo "  [OK]   $*"; PASS=$((PASS + 1)); }
bad() { echo "  [FAIL] $*"; FAIL=$((FAIL + 1)); }

restore_backend() {
    if [ "$BACKEND_2_STOPPED" -eq 1 ]; then
        compose start backend-2 >/dev/null 2>&1 || true
    fi
}
trap restore_backend EXIT

echo "== 0. Все сервисы запущены =="
running="$(compose ps --services --status running 2>/dev/null | sort | tr '\n' ' ')"
echo "  сервисы: $running"
required="backend-1 backend-2 db nginx"
missing=""
for service in $required; do
    [[ " $running " == *" $service "* ]] || missing="$missing $service"
done
[ -z "$missing" ] && ok "db, backend-1, backend-2 и nginx работают" || bad "не запущены:$missing"

echo "== 1. HTTP перенаправляется на HTTPS =="
redirect="$(curl --noproxy '*' -sS --max-time 10 -o /dev/null -w '%{http_code}|%{redirect_url}' "$BASE_HTTP/")"
echo "  $redirect"
[[ "$redirect" == 301\|https://* ]] && ok "получен 301 на HTTPS" || bad "ожидался 301 на HTTPS"

echo "== 2. nginx самостоятельно отдаёт фронтенд =="
body="$(curl --noproxy '*' -skS --max-time 10 "$BASE_HTTPS/")"
[[ "$body" == *"Список задач"* ]] && ok "главная страница доступна по HTTPS" || bad "главная страница не найдена"

echo "== 3. Балансировка между двумя бэкендами =="
instances=""
for _ in $(seq 1 8); do
    instance="$(curl --noproxy '*' -skS --max-time 10 -D - -o /dev/null "$BASE_HTTPS/api/tasks" | awk 'tolower($1)=="x-backend-instance:" {gsub("\r", "", $2); print $2}')"
    instances="$instances $instance"
    sleep 0.2
done
echo "  инстансы:$instances"
[[ "$instances" == *backend-1* && "$instances" == *backend-2* ]] && ok "ответили оба инстанса" || bad "не видно обоих инстансов"
sleep 2

echo "== 4. alias /docs =="
docs="$(curl --noproxy '*' -skS --max-time 10 "$BASE_HTTPS/docs/")"
[[ "$docs" == *"Docs (alias)"* ]] && ok "/docs отдаётся из отдельного каталога" || bad "/docs не работает"

echo "== 5. Собственная страница 404 =="
not_found="$(curl --noproxy '*' -skS --max-time 10 -w '|%{http_code}' "$BASE_HTTPS/not-found-for-check")"
[[ "$not_found" == *"Такой страницы нет"*"|404" ]] && ok "возвращается собственная 404" || bad "собственная 404 не найдена"

echo "== 6. Basic Auth для /admin =="
code="$(curl --noproxy '*' -skS --max-time 10 -o /dev/null -w '%{http_code}' "$BASE_HTTPS/admin/")"
[ "$code" = 401 ] && ok "без пароля получен 401" || bad "без пароля ожидался 401, получен $code"
code="$(curl --noproxy '*' -skS --max-time 10 -u admin:lab1admin -o /dev/null -w '%{http_code}' "$BASE_HTTPS/admin/")"
[ "$code" = 200 ] && ok "с верным паролем получен 200" || bad "с паролем ожидался 200, получен $code"

echo "== 7. Ограничение частоты запросов =="
codes="$(compose --profile tools run --rm --no-deps checker nginx 443 40 /api/tasks 2>/dev/null)"
n200=0
n429=0
for code in $codes; do
    [ "$code" = 200 ] && n200=$((n200 + 1))
    [ "$code" = 429 ] && n429=$((n429 + 1))
done
echo "  статусы: $codes"
echo "  200=$n200, 429=$n429"
[ "$n429" -gt 0 ] && ok "лимит срабатывает со статусом 429" || bad "статус 429 не получен"
sleep 2

echo "== 8. Виртуальные хосты =="
other="$(curl --noproxy '*' -skS --max-time 10 -H 'Host: other.local' "$BASE_HTTPS/")"
[[ "$other" == *"Второй проект"* && "$other" != *"Список задач"* ]] && ok "other.local отдаёт второй проект" || bad "виртуальные хосты смешаны"
code="$(curl --noproxy '*' -skS --max-time 10 -H 'Host: other.local' -o /dev/null -w '%{http_code}' "$BASE_HTTPS/api/tasks")"
[ "$code" = 404 ] && ok "/api отсутствует на втором хосте" || bad "/api доступен на втором хосте: $code"
main="$(curl --noproxy '*' -skS --max-time 10 -H 'Host: lab1.local' "$BASE_HTTPS/")"
[[ "$main" == *"Список задач"* ]] && ok "lab1.local отдаёт основной проект" || bad "основной хост не работает"
code="$(curl --noproxy '*' -skS --max-time 10 -H 'Host: unknown.local' -o /dev/null -w '%{http_code}' "$BASE_HTTPS/")"
[ "$code" = 404 ] && ok "неизвестный Host не раскрывает проекты" || bad "неизвестный Host получил $code"

echo "== 9. Отказоустойчивость при остановке backend-2 =="
compose stop backend-2 >/dev/null
BACKEND_2_STOPPED=1
sleep 2
all_ok=1
seen=""
for _ in $(seq 1 6); do
    headers="$(curl --noproxy '*' -skS --max-time 8 -D - -o /dev/null -w 'HTTP_CODE:%{http_code}' "$BASE_HTTPS/api/tasks")"
    code="$(printf '%s' "$headers" | sed -n 's/.*HTTP_CODE://p')"
    instance="$(printf '%s' "$headers" | awk 'tolower($1)=="x-backend-instance:" {gsub("\r", "", $2); print $2}')"
    [ "$code" = 200 ] || all_ok=0
    seen="$seen $instance"
done
echo "  после остановки: коды 200=$all_ok, инстансы:$seen"
[ "$all_ok" -eq 1 ] && ok "API продолжает отвечать 200" || bad "часть запросов завершилась ошибкой"
[[ "$seen" == *backend-1* && "$seen" != *backend-2* ]] && ok "трафик идёт только на backend-1" || bad "получен неожиданный инстанс:$seen"

echo "  запускаю backend-2 обратно"
compose start backend-2 >/dev/null
restored=0
for _ in $(seq 1 30); do
    instance="$(curl --noproxy '*' -skS --max-time 8 -D - -o /dev/null "$BASE_HTTPS/api/tasks" | awk 'tolower($1)=="x-backend-instance:" {gsub("\r", "", $2); print $2}')"
    if [ "$instance" = backend-2 ]; then
        restored=1
        break
    fi
    sleep 1
done
if [ "$restored" -eq 1 ]; then
    BACKEND_2_STOPPED=0
    ok "backend-2 вернулся в балансировку"
else
    bad "backend-2 не вернулся"
fi

trap - EXIT
echo
echo "Итог: OK=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]

