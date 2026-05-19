.PHONY: help setup build up down logs test clean analyze restart

help:
	@echo "CN-Project Phase 1 - Commands"
	@echo "=============================="
	@echo ""
	@echo "Setup and Run:"
	@echo "  make setup          - Initial setup (build and start)"
	@echo "  make build          - Build Docker image"
	@echo "  make up             - Start containers"
	@echo "  make down           - Stop containers"
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
	@echo ""
	@echo "Maintenance:"
	@echo "  make logs           - Show container logs"
	@echo "  make clean          - Remove data and results"
	@echo "  make restart        - Restart containers"
	@echo "  make shell-server   - Access server shell"
	@echo "  make shell-client   - Access client shell"

setup:
	bash scripts/quickstart.sh

build:
	docker-compose build

up:
	docker-compose up -d

down:
	docker-compose down

logs:
	docker-compose logs -f

logs-server:
	docker exec cn-server tail -f /app/data/logs/*.log

logs-client:
	docker exec cn-client tail -f /app/data/logs/*.log

test-tcp:
	docker exec cn-client python3 src/client.py /app/data/send/test_file.bin --protocol tcp

test-rudp:
	docker exec cn-client python3 src/client.py /app/data/send/test_file.bin --protocol rudp

test-scenario-a:
	docker exec cn-server bash scripts/setup_network.sh eth0 A
	docker exec cn-client python3 src/client.py /app/data/send/test_file.bin --protocol tcp

test-scenario-b:
	docker exec cn-server bash scripts/setup_network.sh eth0 B
	docker exec cn-client python3 src/client.py /app/data/send/test_file.bin --protocol tcp

test-scenario-c:
	docker exec cn-server bash scripts/setup_network.sh eth0 C
	docker exec cn-client python3 src/client.py /app/data/send/test_file.bin --protocol tcp

test-all:
	docker exec cn-client bash scripts/run_tests.sh

analyze:
	docker exec cn-server python3 analysis/analyze.py

shell-server:
	docker exec -it cn-server bash

shell-client:
	docker exec -it cn-client bash

clean:
	rm -rf data/pcap/*.pcap
	rm -rf data/csv/*.csv
	rm -rf data/logs/*.log
	rm -rf data/logs/*.json
	rm -rf results/*
	mkdir -p data/{pcap,csv,logs,send,received}

restart: down up

docs:
	@echo "Opening documentation..."
	@cat docs/README_FASE1.md
