#!/bin/sh
# 以 root 启动只为修正挂载目录的属主（宿主机上 docker 自动创建的 ./data 属于 root），随后降权运行
set -e
if [ "$(id -u)" = "0" ]; then
  if [ "$(stat -c %u /app/data)" != "1000" ]; then
    chown -R app:app /app/data
  fi
  exec setpriv --reuid=app --regid=app --init-groups python -m tgrank "$@"
fi
exec python -m tgrank "$@"
