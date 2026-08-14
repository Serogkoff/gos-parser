#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "Запустите установку через sudo."
    exit 1
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_NAME="${1:-_}"
SERVICE_USER="gosparser"

if [[ ! -f "${PROJECT_DIR}/main.py" || ! -f "${PROJECT_DIR}/web_app.py" ]]; then
    echo "Скрипт должен находиться внутри проекта gos-parser."
    exit 1
fi

apt-get update
apt-get install -y python3 python3-venv python3-pip nginx curl

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
    useradd --system --home-dir "${PROJECT_DIR}" --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

python3 -m venv "${PROJECT_DIR}/.venv"
"${PROJECT_DIR}/.venv/bin/python" -m pip install --upgrade pip
"${PROJECT_DIR}/.venv/bin/pip" install -r "${PROJECT_DIR}/requirements.txt"

mkdir -p "${PROJECT_DIR}/backups" "${PROJECT_DIR}/.playwright"
PLAYWRIGHT_BROWSERS_PATH="${PROJECT_DIR}/.playwright" \
    "${PROJECT_DIR}/.venv/bin/playwright" install --with-deps chromium

install_template() {
    local source="$1"
    local destination="$2"
    sed \
        -e "s|__PROJECT_DIR__|${PROJECT_DIR}|g" \
        -e "s|__SERVER_NAME__|${SERVER_NAME}|g" \
        "${source}" > "${destination}"
}

install_template "${PROJECT_DIR}/deploy/gos-parser-worker.service" \
    "/etc/systemd/system/gos-parser-worker.service"
install_template "${PROJECT_DIR}/deploy/gos-parser-web.service" \
    "/etc/systemd/system/gos-parser-web.service"
install_template "${PROJECT_DIR}/deploy/nginx-gos-parser.conf" \
    "/etc/nginx/sites-available/gos-parser"

ln -sfn /etc/nginx/sites-available/gos-parser /etc/nginx/sites-enabled/gos-parser
rm -f /etc/nginx/sites-enabled/default

if [[ ! -f /etc/gos-parser.env ]]; then
    install_template "${PROJECT_DIR}/deploy/gos-parser.env.example" \
        "/etc/gos-parser.env"
    secret="$("${PROJECT_DIR}/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(48))')"
    sed -i "s|replace-with-a-long-random-value|${secret}|" /etc/gos-parser.env
fi

chmod 600 /etc/gos-parser.env
chown -R "${SERVICE_USER}:www-data" "${PROJECT_DIR}"
chmod 750 "${PROJECT_DIR}"

nginx -t
systemctl daemon-reload
systemctl enable gos-parser-worker gos-parser-web nginx

echo
echo "Файлы установлены, но службы пока не запущены."
echo "1. Заполните настройки Киодо: sudo nano /etc/gos-parser.env"
echo "2. Запустите: sudo systemctl start gos-parser-worker gos-parser-web nginx"
echo "3. Проверьте: curl http://127.0.0.1/healthz"
