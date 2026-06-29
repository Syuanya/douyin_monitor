#!/usr/bin/env bash
set -euo pipefail
systemctl disable --now douyin-monitor-web 2>/dev/null || true
rm -f /etc/systemd/system/douyin-monitor-web.service
systemctl daemon-reload
printf 'Service removed. Data under /opt/douyin-monitor is left untouched.\n'
