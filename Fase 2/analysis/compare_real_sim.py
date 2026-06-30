#!/usr/bin/env python3
"""Gráficos comparativos Real (Fase 1) vs Simulado (Fase 2)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'analysis'))

from config import SimConfig, CONVERGENCE_RUNS
from load_phase1_data import SCENARIO_ORDER, load_app_metrics, metrics_to_dataframe
from rudp_simulator import run_simulation

GRAPHS_DIR = ROOT / 'results' / 'graphs'
GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
sns.set_theme(style='whitegrid')


def run_comparison(n_runs: int = 10):
    print('Gerando comparação Real vs Simulado...')
    phase1 = metrics_to_dataframe(load_app_metrics())
    rows = []

    has_phase1 = not phase1.empty and 'scenario' in phase1.columns
    for scen in SCENARIO_ORDER:
        if has_phase1:
            scen_df = phase1[phase1['scenario'].str.upper() == scen]
            real_tp = scen_df['throughput_mbps']
            real_mean = float(real_tp.mean()) if len(real_tp) else None
            real_el = scen_df['elapsed_s']
            real_el_mean = float(real_el.mean()) if len(real_el) else None
        else:
            real_mean = None
            real_el_mean = None

        sim_tp, sim_el = [], []
        for i in range(n_runs):
            cfg = SimConfig.from_scenario(scen, file_size_bytes=1024 * 1024, seed=20000 + i)
            res = run_simulation(cfg)
            sim_tp.append(res.throughput_mbps)
            sim_el.append(res.elapsed_s)

        rows.append({
            'scenario': scen,
            'real_throughput_mbps': real_mean,
            'sim_throughput_mbps': float(np.mean(sim_tp)),
            'sim_throughput_std': float(np.std(sim_tp, ddof=1)) if len(sim_tp) > 1 else 0,
            'real_elapsed_s': real_el_mean,
            'sim_elapsed_s': float(np.mean(sim_el)),
            'sim_elapsed_std': float(np.std(sim_el, ddof=1)) if len(sim_el) > 1 else 0,
        })

    df = pd.DataFrame(rows)
    df.to_csv(ROOT / 'data' / 'real_vs_simulated.csv', index=False)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    x = np.arange(len(SCENARIO_ORDER))
    w = 0.35

    real_tp = [r if r is not None else 0 for r in df['real_throughput_mbps']]
    has_real = [r is not None for r in df['real_throughput_mbps']]

    axes[0].bar(x - w / 2, real_tp, w, label='Real (Fase 1)', color='#2171b5')
    axes[0].bar(x + w / 2, df['sim_throughput_mbps'], w,
                yerr=df['sim_throughput_std'], capsize=4,
                label='SimPy (Fase 2)', color='#cb181d', alpha=0.85)
    for i, ok in enumerate(has_real):
        if not ok:
            axes[0].text(i - w / 2, 0.05, 'N/D', ha='center', fontsize=8, color='gray')
    axes[0].set_xticks(x)
    axes[0].set_xticklabels([f'Cenário {s}' for s in SCENARIO_ORDER])
    axes[0].set_ylabel('Mbps')
    axes[0].set_title('Vazão')
    axes[0].legend()

    real_el = [r if r is not None else 0 for r in df['real_elapsed_s']]
    axes[1].bar(x - w / 2, real_el, w, label='Real (Fase 1)', color='#2171b5')
    axes[1].bar(x + w / 2, df['sim_elapsed_s'], w,
                yerr=df['sim_elapsed_std'], capsize=4,
                label='SimPy (Fase 2)', color='#cb181d', alpha=0.85)
    axes[1].set_xticks(x)
    axes[1].set_xticklabels([f'Cenário {s}' for s in SCENARIO_ORDER])
    axes[1].set_ylabel('Segundos')
    axes[1].set_title('Tempo de transferência')
    axes[1].legend()

    fig.suptitle('Análise Comparativa — Real vs Simulado (R-UDP, 1 MB)', fontweight='bold')
    fig.tight_layout()
    out = GRAPHS_DIR / 'real_vs_simulated.png'
    fig.savefig(out, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f'✓ {out}')

    report = ROOT / 'results' / 'comparison_report.json'
    with open(report, 'w') as f:
        json.dump(rows, f, indent=2)
    print(f'✓ {report}')


if __name__ == '__main__':
    n = int(sys.argv[1]) if len(sys.argv) > 1 else min(CONVERGENCE_RUNS, 10)
    run_comparison(n)
