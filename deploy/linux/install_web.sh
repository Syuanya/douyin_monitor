#!/usr/bin/env bash
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/douyin-monitor/app}
ROOT_DIR=${ROOT_DIR:-/opt/douyin-monitor}
DATA_DIR=${DATA_DIR:-/opt/douyin-monitor/data}
SERVICE_USER=${SERVICE_USER:-douyin-monitor}
PORT=${PORT:-8080}
TOKEN=${DOUYIN_MONITOR_WEB_TOKEN:-}

if [[ -z "$TOKEN" ]]; then
  TOKEN=$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "$ROOT_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

mkdir -p "$ROOT_DIR" "$DATA_DIR"
rsync -a --delete --exclude '.git' ./ "$APP_DIR"/
chown -R "$SERVICE_USER:$SERVICE_USER" "$ROOT_DIR"

python3 -m venv "$ROOT_DIR/venv"
"$ROOT_DIR/venv/bin/pip" install --upgrade pip
"$ROOT_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" -r "$APP_DIR/requirements-web.txt"

cat > "$ROOT_DIR/.env.web" <<ENV
DOUYIN_MONITOR_WEB_HOST=127.0.0.1
DOUYIN_MONITOR_WEB_PORT=$PORT
DOUYIN_MONITOR_RUN_PATH=$DATA_DIR
DOUYIN_MONITOR_WEB_TOKEN=$TOKEN
ENV
chown "$SERVICE_USER:$SERVICE_USER" "$ROOT_DIR/.env.web"
chmod 600 "$ROOT_DIR/.env.web"

cp "$APP_DIR/deploy/linux/douyin-monitor-web.service" /etc/systemd/system/douyin-monitor-web.service
systemctl daemon-reload
systemctl enable --now douyin-monitor-web

echo "Installed Douyin Monitor Web."
echo "Local URL: http://127.0.0.1:$PORT"
echo "Token: $TOKEN"
echo "For remote access, configure Nginx HTTPS using deploy/linux/nginx.conf."
