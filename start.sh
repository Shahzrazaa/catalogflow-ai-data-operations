#!/usr/bin/env sh
# CatalogFlow AI launcher for macOS and Linux (Windows users: START CATALOGFLOW.bat)
set -e
cd "$(dirname "$0")"

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.9+ was not found. Install Python 3 and run again."
  exit 1
fi

if ! "$PY" -c "import pandas, openpyxl" >/dev/null 2>&1; then
  echo "Installing pandas and openpyxl..."
  "$PY" -m pip install --quiet -r requirements.txt
fi

rm -f .port
echo "Starting CatalogFlow AI..."
"$PY" server.pyw &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null' INT TERM

i=0
while [ ! -f .port ] && [ $i -lt 30 ]; do sleep 1; i=$((i + 1)); done
if [ ! -f .port ]; then
  echo "CatalogFlow did not start correctly."
  kill $SERVER_PID 2>/dev/null
  exit 1
fi

URL="http://127.0.0.1:$(cat .port)"
echo "CatalogFlow is running at $URL (Ctrl+C to stop)"
if command -v open >/dev/null 2>&1; then open "$URL"
elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 || true
fi
wait $SERVER_PID
