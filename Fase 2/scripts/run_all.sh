#!/bin/bash
# Executa validação completa da Fase 2
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== Instalando dependências ==="
python3 -m pip install -q -r requirements.txt

echo ""
echo "=== Simulação de teste ==="
python3 -c "
import sys; sys.path.insert(0,'src')
from config import SimConfig
from rudp_simulator import run_simulation
r = run_simulation(SimConfig.from_scenario('A', file_size_bytes=65536, seed=42))
print(f'OK: {r.elapsed_s:.3f}s, {r.throughput_mbps:.2f} Mbps')
"

echo ""
echo "=== 10 Tarefas de Validação ==="
python3 analysis/run_validation.py "$@"

echo ""
echo "=== Comparação Real vs Simulado ==="
python3 analysis/compare_real_sim.py

echo ""
echo "=== Concluído. Resultados em results/ ==="
