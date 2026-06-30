.PHONY: help install validate validate-quick compare sim test clean

PYTHON ?= python3
VENV ?= .venv

help:
	@echo "Fase 2 — Modelagem Estocástica (SimPy)"
	@echo "======================================="
	@echo ""
	@echo "  make install          Instalar dependências (simpy, scipy, ...)"
	@echo "  make validate         Executar 10 tarefas de validação (30 runs)"
	@echo "  make validate-quick   Validação rápida (5 runs, menos tamanhos)"
	@echo "  make compare          Gráficos Real (Fase 1) vs Simulado"
	@echo "  make sim              Simulação única (cenário B, 1 MB)"
	@echo "  make test             Testes unitários do simulador"
	@echo "  make clean            Limpar resultados gerados"

install:
	$(PYTHON) -m pip install -r requirements.txt

validate:
	$(PYTHON) analysis/run_validation.py

validate-quick:
	$(PYTHON) analysis/run_validation.py --quick

compare:
	$(PYTHON) analysis/compare_real_sim.py

sim:
	$(PYTHON) -c "import sys; sys.path.insert(0,'src'); from config import SimConfig; from rudp_simulator import run_simulation; r=run_simulation(SimConfig.from_scenario('B')); print(f'Elapsed: {r.elapsed_s:.2f}s | Throughput: {r.throughput_mbps:.2f} Mbps | Retrans: {r.retransmissions}')"

test:
	$(PYTHON) -m pytest tests/ -v

clean:
	rm -rf results/graphs/*.png results/*.json data/task*.csv data/real_vs_simulated.csv
