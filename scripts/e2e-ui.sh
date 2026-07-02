#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/e2e-ui.sh [command] [options]

Commands:
  start      Build and start the Docker Compose app, then wait for the UI.
  restart    Recreate the app container, then wait for the UI.
  stop       Stop the Docker Compose app.
  logs       Follow app logs.
  status     Show container status and health check result.

Options:
  --no-build    Start without rebuilding the image.
  --rebuild     Force a rebuild before starting.
  --timeout N   Seconds to wait for /api/health. Default: 180.
  -h, --help    Show this help.

Environment:
  E2E_UI_URL       Browser URL to print/check. Default: http://localhost:8080
  E2E_HEALTH_URL   Health URL to wait on. Default: ${E2E_UI_URL}/api/health
  E2E_PROJECT      Compose project name. Default: slideforge-e2e
  E2E_TIMEOUT_SECONDS
                   Seconds to wait for /api/health. Default: 180

Examples:
  scripts/e2e-ui.sh
  scripts/e2e-ui.sh start --no-build
  scripts/e2e-ui.sh logs
  scripts/e2e-ui.sh stop
USAGE
}

repo_root() {
  local script_dir
  script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
  cd -- "${script_dir}/.." && pwd
}

detect_compose() {
  if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
    return 0
  fi

  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
    return 0
  fi

  echo "Docker Compose is required. Install Docker Desktop or docker-compose." >&2
  return 1
}

wait_for_health() {
  local health_url="$1"
  local timeout_seconds="$2"
  local started_at now elapsed

  if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required to wait for ${health_url}." >&2
    return 1
  fi

  started_at="$(date +%s)"
  printf "Waiting for %s" "${health_url}"
  while true; do
    if curl -fsS "${health_url}" >/dev/null 2>&1; then
      printf "\n"
      return 0
    fi

    now="$(date +%s)"
    elapsed=$((now - started_at))
    if [ "${elapsed}" -ge "${timeout_seconds}" ]; then
      printf "\n"
      echo "Timed out after ${timeout_seconds}s waiting for ${health_url}." >&2
      return 1
    fi

    printf "."
    sleep 2
  done
}

show_ready_message() {
  local ui_url="$1"
  local health_url="$2"

  cat <<EOF

SlideForge E2E UI is ready:
  UI:     ${ui_url}
  Health: ${health_url}

Useful next commands:
  scripts/e2e-ui.sh logs
  scripts/e2e-ui.sh status
  scripts/e2e-ui.sh stop
EOF
}

ROOT_DIR="$(repo_root)"
cd "${ROOT_DIR}"

COMMAND="start"
BUILD_ARGS=(--build)
TIMEOUT_SECONDS="${E2E_TIMEOUT_SECONDS:-180}"

if [ "${1:-}" != "" ] && [[ "${1:-}" != --* ]]; then
  COMMAND="$1"
  shift
fi

while [ "$#" -gt 0 ]; do
  case "$1" in
    --no-build)
      BUILD_ARGS=()
      ;;
    --rebuild)
      BUILD_ARGS=(--build)
      ;;
    --timeout)
      shift
      if [ "${1:-}" = "" ]; then
        echo "--timeout requires a number of seconds." >&2
        exit 2
      fi
      TIMEOUT_SECONDS="$1"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if ! [[ "${TIMEOUT_SECONDS}" =~ ^[0-9]+$ ]] || [ "${TIMEOUT_SECONDS}" -le 0 ]; then
  echo "--timeout must be a positive integer greater than zero." >&2
  exit 2
fi

UI_URL="${E2E_UI_URL:-http://localhost:8080}"
HEALTH_URL="${E2E_HEALTH_URL:-${UI_URL%/}/api/health}"
export COMPOSE_PROJECT_NAME="${E2E_PROJECT:-slideforge-e2e}"

COMPOSE=()
detect_compose

case "${COMMAND}" in
  start)
    if [ "${#BUILD_ARGS[@]}" -gt 0 ]; then
      "${COMPOSE[@]}" up -d "${BUILD_ARGS[@]}" slideforge
    else
      "${COMPOSE[@]}" up -d slideforge
    fi
    wait_for_health "${HEALTH_URL}" "${TIMEOUT_SECONDS}"
    show_ready_message "${UI_URL}" "${HEALTH_URL}"
    ;;
  restart)
    if [ "${#BUILD_ARGS[@]}" -gt 0 ]; then
      "${COMPOSE[@]}" up -d --force-recreate "${BUILD_ARGS[@]}" slideforge
    else
      "${COMPOSE[@]}" up -d --force-recreate slideforge
    fi
    wait_for_health "${HEALTH_URL}" "${TIMEOUT_SECONDS}"
    show_ready_message "${UI_URL}" "${HEALTH_URL}"
    ;;
  stop)
    "${COMPOSE[@]}" down
    ;;
  logs)
    "${COMPOSE[@]}" logs -f slideforge
    ;;
  status)
    "${COMPOSE[@]}" ps
    if wait_for_health "${HEALTH_URL}" 2; then
      echo "Health check passed: ${HEALTH_URL}"
    else
      echo "Health check failed: ${HEALTH_URL}" >&2
      exit 1
    fi
    ;;
  -h|--help)
    usage
    ;;
  *)
    echo "Unknown command: ${COMMAND}" >&2
    usage >&2
    exit 2
    ;;
esac
