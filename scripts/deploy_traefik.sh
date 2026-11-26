#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
ENV_FILE="${1:-$ROOT/.env}"
[[ -f "$ENV_FILE" ]] || { echo "ERRO: arquivo de ambiente ausente: $ENV_FILE" >&2; exit 1; }
command -v docker >/dev/null || { echo "ERRO: Docker nao instalado" >&2; exit 1; }
docker compose version >/dev/null || { echo "ERRO: Compose v2 necessario" >&2; exit 1; }
command -v python3 >/dev/null || { echo "ERRO: Python 3 necessario para preflight" >&2; exit 1; }

COMPOSE=(docker compose --env-file "$ENV_FILE" -f compose.yaml -f compose.production.yaml --profile web)
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
"${COMPOSE[@]}" config --format json > "$TMP"
python3 scripts/check_production_compose.py "$TMP"
# Nunca cria ou reinicia a borda compartilhada. Exige redes preexistentes.
PROXY="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["networks"]["proxy"]["name"])' "$TMP")"
docker network inspect "$PROXY" >/dev/null || { echo "ERRO: rede Traefik $PROXY nao existe" >&2; exit 1; }
docker network inspect whatsapp_internal >/dev/null || { echo "ERRO: rede Evolution whatsapp_internal nao existe" >&2; exit 1; }

"${COMPOSE[@]}" up -d --build --wait
"${COMPOSE[@]}" ps
echo "Deploy concluido. Configure o Public Hostname do Cloudflare Tunnel para http://traefik:80, mantendo o Host original."
echo "Valide HTTPS, OIDC, /api/session, /app, uploads e SSE no dominio publicado."
