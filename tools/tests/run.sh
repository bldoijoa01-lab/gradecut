#!/usr/bin/env bash
# 사이트 기능 점검: 저장소 루트를 임시 서버로 띄우고 smoke.js 실행
# 실행: bash tools/tests/run.sh
set -u
cd "$(dirname "$0")/../.."
PORT="${PORT:-8765}"
python3 -m http.server "$PORT" >/dev/null 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT
for _ in $(seq 1 20); do curl -s -o /dev/null "http://localhost:$PORT/" && break; sleep 0.25; done
BASE="http://localhost:$PORT/" node tools/tests/smoke.js
