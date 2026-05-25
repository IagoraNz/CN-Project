.PHONY: help setup build up down logs test clean analyze restart fix-perms clean-data-dirs ui

COMPOSE = bash scripts/compose.sh
HOST_UID := $(shell id -u)
HOST_GID := $(shell id -g)

help:
	@echo "CN-Project Phase 1 - Commands"
	@echo "=============================="
	@echo ""
	@echo "Setup and Run:"
	@echo "  make setup          - Initial setup (build and start)"
	@echo "  make build          - Build Docker image"
	@echo "  make up             - Start containers"
	@echo "  make down           - Stop containers and clear csv, logs, pcap"
	@echo ""
	@echo "Testing:"
	@echo "  make test-tcp       - Test TCP transfer"
	@echo "  make test-rudp      - Test R-UDP transfer"
	@echo "  make test-all       - Run full test suite"
	@echo "  make test-scenario-a - Test scenario A (0% loss, 10ms)"
	@echo "  make test-scenario-b - Test scenario B (10% loss, 50ms)"
	@echo "  make test-scenario-c - Test scenario C (20% loss, 100ms)"
	@echo ""
	@echo "Analysis:"
	@echo "  make analyze        - Run data analysis and generate graphs"
	@echo "  make ui             - Open web control panel (setup, test, analyze, down)"
	@echo ""
	@echo "Maintenance:"
	@echo "  make logs           - Show container logs"
	@echo "  make clean          - Remove data and results"
	@echo "  make fix-perms      - Fix root-owned files from Docker (needs containers up)"
	@echo "  make restart        - Restart containers"
	@echo "  make shell-server   - Access server shell"
	@echo "  make shell-client   - Access client shell"

setup:
	bash scripts/quickstart.sh

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up -d

down:
	-docker exec cn-server chown -R $(HOST_UID):$(HOST_GID) /app/data 2>/dev/null
	$(COMPOSE) down
	$(MAKE) clean-data-dirs

clean-data-dirs:
	rm -f data/pcap/*.pcap
	rm -f data/csv/*.csv data/csv/*.json
	rm -f data/logs/*.log data/logs/*.json

logs:
	$(COMPOSE) logs -f

logs-server:
	docker exec cn-server tail -f /app/data/logs/*.log

logs-client:
	docker exec cn-client tail -f /app/data/logs/*.log

test-tcp:
	bash scripts/with_capture.sh tcp

test-rudp:
	bash scripts/with_capture.sh rudp

test-scenario-a:
	docker exec cn-server bash scripts/setup_network.sh eth0 A
	bash scripts/with_capture.sh tcp eth0 A

test-scenario-b:
	docker exec cn-server bash scripts/setup_network.sh eth0 B
	bash scripts/with_capture.sh tcp eth0 B

test-scenario-c:
	docker exec cn-server bash scripts/setup_network.sh eth0 C
	bash scripts/with_capture.sh tcp eth0 C

test-all:
	bash scripts/run_tests.sh

analyze: fix-perms
	docker exec -u $(HOST_UID):$(HOST_GID) \
		-e MPLCONFIGDIR=/tmp/mplconfig \
		-e HOME=/tmp \
		cn-server python3 analysis/analyze.py

fix-perms:
	docker exec cn-server chown -R $(HOST_UID):$(HOST_GID) /app/results /app/data

shell-server:
	docker exec -it cn-server bash

shell-client:
	docker exec -it cn-client bash

clean:
	-docker exec cn-server chown -R $(HOST_UID):$(HOST_GID) /app/results /app/data 2>/dev/null
	$(MAKE) clean-data-dirs
	rm -rf results/*
	mkdir -p data/{pcap,csv,logs,send,received}

restart: down up

ui:
	@command -v python3 >/dev/null || (echo "python3 required" && exit 1)
	@echo "Painel: http://127.0.0.1:5050"
	@python3 ui/app.py

docs:
	@echo "Opening documentation..."
	@cat docs/README_FASE1.md
