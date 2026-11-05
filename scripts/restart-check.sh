#!/usr/bin/env bash
set -euo pipefail
P="$(cd "$(dirname "$0")/.." && pwd)"
D="${RESTART_CHECK_DIR:?}"
PY="$P/backend/.venv/bin/python"
export BIBOO_DATA_DIR="$D" BIBOO_FAKE_MODELS=1 BIBOO_SECURE_COOKIE=0
export DEEPSEEK_API_KEY="" AIHUBMIX_API_KEY="" TENCENTCLOUD_SECRET_ID="" TENCENTCLOUD_SECRET_KEY=""
api() { curl --fail --silent --show-error --max-time 5 "$@"; }
json() { "$PY" -c "import json,sys; print($1)"; }
case "${1:-}" in
  start)
    cd "$P/backend"
    nohup "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 0 > "$D/server.log" 2>&1 &
    pid=$!
    for _ in {1..50}; do
      kill -0 "$pid" 2>/dev/null || break
      port="$(sed -nE 's|^.*Uvicorn running on http://127\.0\.0\.1:([0-9]+) .*|\1|p' "$D/server.log" | tail -1)"
      base="http://127.0.0.1:$port/api/v1"
      if [ -n "$port" ] && api "$base/health" > /dev/null 2>&1; then
        printf '%s\n' "$base" > "$D/base-url"
        echo "$pid"
        exit 0
      fi
      sleep 0.1
    done
    kill "$pid" 2>/dev/null || true
    cat "$D/server.log" >&2
    exit 1
    ;;
  write)
    BASE="$(cat "$D/base-url")"
    code="$("$PY" "$P/scripts/create_teacher.py" '重启检查老师')"
    "$PY" -c 'import json,sys; print(json.dumps({"invite_code":sys.stdin.read().strip()}))' <<< "$code" |
      api -c "$D/cookies" -H 'Content-Type: application/json' --data-binary @- "$BASE/auth/login" >/dev/null
    "$PY" -c 'import json,sys; print(json.dumps({"name":sys.argv[1]}))' "$2" |
      api -b "$D/cookies" -H 'Content-Type: application/json' --data-binary @- "$BASE/classes" |
      json 'json.load(sys.stdin)["id"]'
    ;;
  read)
    BASE="$(cat "$D/base-url")"
    api -b "$D/cookies" "$BASE/classes" |
      "$PY" -c 'import json,sys; print(next(row["name"] for row in json.load(sys.stdin) if row["id"] == int(sys.argv[1])))' "$2"
    ;;
  stop) ;;
  *) echo '用法：restart-check.sh start|write|read|stop' >&2; exit 2 ;;
esac
