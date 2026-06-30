#!/usr/bin/env bash
# Wrapper for Docker Compose (v2 plugin or legacy docker-compose).
# Always runs from the project root so build context and volumes resolve correctly.

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_OPTS=(--project-directory "$PROJECT_ROOT" -f "$PROJECT_ROOT/docker/docker-compose.yml")

if ! docker info >/dev/null 2>&1; then
    echo "Error: Docker daemon is not running." >&2
    echo "  On WSL2: enable WSL integration in Docker Desktop (Settings → Resources → WSL Integration)." >&2
    exit 1
fi

if docker compose version >/dev/null 2>&1; then
    exec docker compose "${COMPOSE_OPTS[@]}" "$@"
elif command -v docker-compose >/dev/null 2>&1; then
    exec docker-compose "${COMPOSE_OPTS[@]}" "$@"
else
    echo "Error: Docker Compose not found." >&2
    echo "  Install Docker Desktop and enable WSL integration, or install the compose plugin." >&2
    exit 1
fi
