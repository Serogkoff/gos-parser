#!/usr/bin/env bash
set -u

failed=0
check() {
    local title="$1"
    shift
    if "$@" >/dev/null 2>&1; then
        printf '✅ %s\n' "$title"
    else
        printf '❌ %s\n' "$title"
        failed=1
    fi
}

check "Служба парсера работает" systemctl is-active gos-parser-worker
check "Служба сайта работает" systemctl is-active gos-parser-web
check "Nginx работает" systemctl is-active nginx
check "Веб-интерфейс отвечает" curl --fail --silent --max-time 5 http://127.0.0.1/healthz
check "Конфигурация Nginx корректна" nginx -t

exit "${failed}"
