#!/usr/bin/env bash
# Deploy smart_calendar to the server: rsync the code and rebuild the container there.
#   ./deploy.sh            code only
#   ./deploy.sh --secrets  also push .env and data/google_token.json
set -euo pipefail

HOST="${SMART_CALENDAR_HOST:-ubuntu@130.162.197.224}"
DEST=/home/ubuntu/smart_calendar

cd "$(dirname "$0")"

rsync -az --delete \
  --exclude .git \
  --exclude .venv \
  --exclude .env \
  --exclude data \
  --exclude credentials.json \
  --exclude __pycache__ \
  ./ "$HOST:$DEST/"

if [[ "${1:-}" == "--secrets" ]]; then
  ssh "$HOST" "mkdir -p $DEST/data"
  scp .env "$HOST:$DEST/.env"
  scp data/google_token.json "$HOST:$DEST/data/google_token.json"
fi

ssh "$HOST" "cd $DEST && docker compose up -d --build && docker compose ps"

echo "Deployed. Logs: ssh $HOST 'cd $DEST && docker compose logs -f'"
