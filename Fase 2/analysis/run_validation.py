#!/usr/bin/env python3
"""Executa as 10 tarefas de validação do simulador SimPy (Fase 2)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'analysis'))

from config import (
    CONVERGENCE_RUNS,
    SCENARIOS,
    THROUGHPUT_FILE_SIZES_MB,
    WINDOW_SIZES,
    SimConfig,
)
from load_phase1_data import (
    SCENARIO_ORDER,
    aggregate_by_scenario,
    get_delay_params_from_phase1,
    load_app_metrics,
    load_pcap_rtt_samples,
    metrics_to_dataframe,
)
from rudp_simulator import run_simulation

RESULTS_DIR = ROOT / 'results'
GRAPHS_DIR = RESULTS_DIR / 'graphs'
DATA_DIR = ROOT / 'data'
GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

sns.set_theme(style='whitegrid')

# Paleta unificada: Cenário A=azul, B=roxo, C=laranja
COLORS = {'A': '#1f77b4', 'B': '#756bb1', 'C': '#e6550d'}
# Versão clara (Real/configurado); versão cheia (SimPy/simulado)
COLORS_LIGHT = {'A': '#aec7e8', 'B': '#c6b9e0', 'C': '#f5a97a'}


def _save_fig(fig, name: str) -> Path:
    out = GRAPHS_DIR / f'{name}.png'
    fig.savefig(out, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f'  ✓ Gráfico: {out.name}')
    return out


def _ci95(values: list[float]) -> tuple[float, float, float]:
    """Média e IC 95% (t de Student)."""
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    if n == 0:
        return 0.0, 0.0, 0.0
    mean = float(np.mean(arr))
    if n < 2:
        return mean, mean, mean
    sem = stats.sem(arr)
    h = sem * stats.t.ppf(0.975, n - 1)
    return mean, mean - h, mean + h


class ValidationRunner:
    """Orquestra as 10 tarefas de validação (Seção 3.1 do edital)."""

    def __init__(self, quick: bool = False):
        self.quick = quick
        self.runs = 5 if quick else CONVERGENCE_RUNS
        self.phase1_metrics = load_app_metrics()
        self.phase1_df = metrics_to_dataframe(self.phase1_metrics)
        self.delay_params = get_delay_params_from_phase1()
        self.task_results: dict = {}

    def run_all(self) -> dict:
        print('=' * 60)
        print('Fase 2 — 10 Tarefas de Validação SimPy')
        print('=' * 60)

        self.task_01_delay_model()
        self.task_02_bernoulli_loss()
        self.task_03_timeout_retransmissions()
        self.task_04_throughput_curve()
        self.task_05_window_sensitivity()
        self.task_06_rtt_validation()
        self.task_07_jitter_impact()
        self.task_08_stress_scenario()
        self.task_09_efficiency_analysis()
        self.task_10_statistical_convergence()

        report_path = RESULTS_DIR / 'validation_report.json'
        with open(report_path, 'w') as f:
            json.dump(self.task_results, f, indent=2, default=str)
        print(f'\n✓ Relatório completo: {report_path}')
        self._print_checklist()
        return self.task_results

    def _print_checklist(self):
        print('\n' + '=' * 60)
        print('CHECKLIST — 10 Tarefas de Validação')
        print('=' * 60)
        tasks = [
            ('01', 'Modelagem de Atraso (distribuição normal)'),
            ('02', 'Modelo de Perda de Bernoulli vs tc'),
            ('03', 'Simulação de Timeout / Retransmissões'),
            ('04', 'Curva de Vazão (1–100 MB)'),
            ('05', 'Sensibilidade da Janela (N)'),
            ('06', 'Validação de RTT (sim vs tcpdump)'),
            ('07', 'Impacto do Jitter'),
            ('08', 'Cenário de Estresse (25% perda)'),
            ('09', 'Análise de Eficiência (dados vs ACKs)'),
            ('10', 'Convergência Estatística (IC 95%)'),
        ]
        for tid, desc in tasks:
            status = self.task_results.get(f'task_{tid}', {}).get('status', '?')
            mark = '✓' if status == 'ok' else '○'
            print(f'  [{mark}] Tarefa {tid}: {desc}')

    # ------------------------------------------------------------------ Tarefa 1
    def task_01_delay_model(self):
        """Ajusta N(μ,σ) aos dados reais de latência e plota histograma + PDF."""
        print('\n[Tarefa 1] Modelagem de Atraso — ajuste N(μ,σ) a dados reais')

        rtt_by_scenario = load_pcap_rtt_samples()

        rows = []
        fig, axes = plt.subplots(1, len(SCENARIO_ORDER), figsize=(5 * len(SCENARIO_ORDER), 4))
        if len(SCENARIO_ORDER) == 1:
            axes = [axes]

        for ax, scen in zip(axes, SCENARIO_ORDER):
            params = self.delay_params[scen]

            real_rtts = rtt_by_scenario.get(scen, [])
            if real_rtts:
                # Converte RTT em atraso one-way (RTT / 2)
                delay_samples = [r / 2 for r in real_rtts]
                fit_mu = float(np.mean(delay_samples))
                fit_sigma = float(np.std(delay_samples, ddof=1)) if len(delay_samples) > 1 else params['delay_std_ms']
                ks_stat, ks_p = stats.kstest(delay_samples, stats.norm(loc=fit_mu, scale=fit_sigma).cdf)
                source = 'pcap'
            else:
                # Sem dados reais: usa parâmetros padrão do cenário tc
                fit_mu = params['delay_mean_ms']
                fit_sigma = params['delay_std_ms']
                delay_samples = []
                ks_stat, ks_p = float('nan'), float('nan')
                source = params['source']

            rows.append({
                'scenario': scen,
                'mu_ms': fit_mu,
                'sigma_ms': fit_sigma,
                'n_samples': len(delay_samples),
                'source': source,
                'ks_stat': ks_stat,
                'ks_p': ks_p,
            })

            x_range = np.linspace(max(0.0, fit_mu - 4 * fit_sigma), fit_mu + 4 * fit_sigma, 300)
            pdf_vals = stats.norm.pdf(x_range, fit_mu, fit_sigma)

            if delay_samples:
                ax.hist(delay_samples, bins=max(5, len(delay_samples) // 3),
                        density=True, alpha=0.55, color=COLORS_LIGHT[scen], label='Dados reais (Fase 1)')
            ax.plot(x_range, pdf_vals, color=COLORS[scen], lw=2,
                    label=f'N({fit_mu:.1f}, {fit_sigma:.1f}²)')
            ax.set_title(f'Cenário {scen}', fontweight='bold')
            ax.set_xlabel('Atraso one-way (ms)')
            ax.set_ylabel('Densidade')
            ax.legend(fontsize=8)

        fig.suptitle('Tarefa 1 — Modelagem de Atraso: N(μ, σ) calibrada com dados reais',
                     fontweight='bold')
        fig.tight_layout()
        _save_fig(fig, 'task01_delay_model')

        df = pd.DataFrame(rows)
        df.to_csv(DATA_DIR / 'task01_delay_model.csv', index=False)

        self.task_results['task_01'] = {
            'status': 'ok',
            'description': 'Latência representada por N(μ,σ) ajustada a dados reais de Fase 1',
            'data': rows,
        }

    # ------------------------------------------------------------------ Tarefa 2
    def task_02_bernoulli_loss(self):
        print('\n[Tarefa 2] Modelo de Perda de Bernoulli vs tc')
        rows = []
        for scen in SCENARIO_ORDER:
            tc_loss = SCENARIOS[scen]['loss_prob']
            observed_losses = []
            total_attempts = []

            for i in range(self.runs):
                cfg = SimConfig.from_scenario(scen, file_size_bytes=512 * 1024, seed=2000 + i)
                res = run_simulation(cfg)
                attempts = res.packets_sent + res.ack_packets
                observed_losses.append(res.packets_lost)
                total_attempts.append(attempts)

            total_lost = sum(observed_losses)
            total_pkts = sum(total_attempts)
            sim_rate = total_lost / total_pkts if total_pkts else 0.0

            rows.append({
                'scenario': scen,
                'tc_loss_prob': tc_loss,
                'sim_observed_loss_rate': sim_rate,
                'error_abs': abs(sim_rate - tc_loss),
                'total_packets': total_pkts,
            })

        df = pd.DataFrame(rows)
        df.to_csv(DATA_DIR / 'task02_bernoulli_loss.csv', index=False)

        fig, ax = plt.subplots(figsize=(8, 5))
        x = np.arange(len(SCENARIO_ORDER))
        for idx, scen in enumerate(SCENARIO_ORDER):
            ax.bar(x[idx] - 0.2, df.loc[idx, 'tc_loss_prob'] * 100, 0.4, color=COLORS_LIGHT[scen])
            ax.bar(x[idx] + 0.2, df.loc[idx, 'sim_observed_loss_rate'] * 100, 0.4, color=COLORS[scen])
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor='#cccccc', label='tc (configurado)'),
            Patch(facecolor='#555555', label='SimPy (observado)'),
        ] + [Patch(facecolor=COLORS[s], label=f'Cenário {s}') for s in SCENARIO_ORDER]
        ax.legend(handles=legend_elements, fontsize=8)
        ax.set_xticks(x)
        ax.set_xticklabels([f'Cenário {s}' for s in SCENARIO_ORDER])
        ax.set_ylabel('Taxa de perda (%)')
        ax.set_title('Tarefa 2 — Perda de Bernoulli vs tc', fontweight='bold')
        _save_fig(fig, 'task02_bernoulli_loss')

        self.task_results['task_02'] = {'status': 'ok', 'data': rows}

    # ------------------------------------------------------------------ Tarefa 3
    def task_03_timeout_retransmissions(self):
        print('\n[Tarefa 3] Timeout e Retransmissões vs logs Fase 1')
        rows = []
        real_by_scen = {}
        if not self.phase1_df.empty:
            agg = self.phase1_df.groupby('scenario')['retransmissions'].mean()
            real_by_scen = agg.to_dict()

        for scen in SCENARIO_ORDER:
            sim_retrans = []
            for i in range(self.runs):
                cfg = SimConfig.from_scenario(
                    scen, file_size_bytes=1024 * 1024, seed=3000 + i,
                )
                res = run_simulation(cfg)
                sim_retrans.append(res.retransmissions)

            real_val = real_by_scen.get(scen, real_by_scen.get(scen.upper(), None))
            sim_mean = float(np.mean(sim_retrans))

            rows.append({
                'scenario': scen,
                'real_retrans_mean': real_val,
                'sim_retrans_mean': sim_mean,
                'sim_retrans_std': float(np.std(sim_retrans, ddof=1)) if len(sim_retrans) > 1 else 0,
            })

        df = pd.DataFrame(rows)
        df.to_csv(DATA_DIR / 'task03_retransmissions.csv', index=False)

        fig, ax = plt.subplots(figsize=(8, 5))
        x = np.arange(len(SCENARIO_ORDER))
        real_vals = [r['real_retrans_mean'] or 0 for r in rows]
        sim_vals = [r['sim_retrans_mean'] for r in rows]
        for idx, scen in enumerate(SCENARIO_ORDER):
            ax.bar(x[idx] - 0.2, real_vals[idx], 0.4, color=COLORS_LIGHT[scen])
            ax.bar(x[idx] + 0.2, sim_vals[idx], 0.4, color=COLORS[scen])
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor='#cccccc', label='Real (Fase 1 / tcpdump)'),
            Patch(facecolor='#555555', label='SimPy'),
        ] + [Patch(facecolor=COLORS[s], label=f'Cenário {s}') for s in SCENARIO_ORDER]
        ax.legend(handles=legend_elements, fontsize=8)
        ax.set_xticks(x)
        ax.set_xticklabels([f'Cenário {s}' for s in SCENARIO_ORDER])
        ax.set_ylabel('Retransmissões (média)')
        ax.set_title('Tarefa 3 — Retransmissões: SimPy vs Real', fontweight='bold')
        _save_fig(fig, 'task03_retransmissions')

        self.task_results['task_03'] = {'status': 'ok', 'data': rows}

    # ------------------------------------------------------------------ Tarefa 4
    def task_04_throughput_curve(self):
        print('\n[Tarefa 4] Curva de Vazão — 1 MB a 10 MB (3 cenários)')
        sizes = THROUGHPUT_FILE_SIZES_MB if not self.quick else [1, 3, 7, 10]
        rows = []

        for scen in SCENARIO_ORDER:
            for size_mb in sizes:
                size_bytes = size_mb * 1024 * 1024
                throughputs = []
                for i in range(min(self.runs, 10)):
                    cfg = SimConfig.from_scenario(scen, file_size_bytes=size_bytes, seed=4000 + ord(scen) + size_mb + i)
                    res = run_simulation(cfg)
                    throughputs.append(res.throughput_mbps)

                mean, lo, hi = _ci95(throughputs)
                rows.append({
                    'scenario': scen,
                    'file_size_mb': size_mb,
                    'throughput_mean_mbps': mean,
                    'ci_low': lo,
                    'ci_high': hi,
                })

        df = pd.DataFrame(rows)
        df.to_csv(DATA_DIR / 'task04_throughput_curve.csv', index=False)

        scen_labels = {s: SCENARIOS[s]['label'] for s in SCENARIO_ORDER}

        fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=False)
        for ax, scen in zip(axes, SCENARIO_ORDER):
            sub = df[df['scenario'] == scen]
            color = COLORS[scen]
            ax.plot(sub['file_size_mb'], sub['throughput_mean_mbps'], 'o-', color=color, linewidth=2)
            ax.fill_between(sub['file_size_mb'], sub['ci_low'], sub['ci_high'], alpha=0.25, color=color)
            ax.set_xlabel('Tamanho do arquivo (MB)')
            ax.set_ylabel('Vazão (Mbps)')
            ax.set_title(f'Cenário {scen}\n{scen_labels[scen]}', fontsize=9)

        fig.suptitle('Tarefa 4 — Curva de Vazão 1–10 MB (3 Cenários, IC 95%)', fontweight='bold')
        fig.tight_layout()
        _save_fig(fig, 'task04_throughput_curve')

        self.task_results['task_04'] = {'status': 'ok', 'data': rows}

    # ------------------------------------------------------------------ Tarefa 5
    def task_05_window_sensitivity(self):
        print('\n[Tarefa 5] Sensibilidade da Janela (N) — 3 cenários')
        rows = []
        windows = WINDOW_SIZES if not self.quick else [1, 4, 16, 64]

        for scen in SCENARIO_ORDER:
            for ws in windows:
                throughputs = []
                for i in range(min(self.runs, 10)):
                    cfg = SimConfig.from_scenario(
                        scen, file_size_bytes=2 * 1024 * 1024, window_size=ws, seed=5000 + ord(scen) + ws + i,
                    )
                    res = run_simulation(cfg)
                    throughputs.append(res.throughput_mbps)

                mean_tp = float(np.mean(throughputs))
                rows.append({'scenario': scen, 'window_size': ws, 'throughput_mean_mbps': mean_tp})

        df = pd.DataFrame(rows)
        df.to_csv(DATA_DIR / 'task05_window_sensitivity.csv', index=False)

        fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=False)
        for ax, scen in zip(axes, SCENARIO_ORDER):
            sub = df[df['scenario'] == scen].copy()
            saturation_n = int(sub.loc[sub['throughput_mean_mbps'].idxmax(), 'window_size'])
            color = COLORS[scen]
            ax.plot(sub['window_size'], sub['throughput_mean_mbps'], 's-', color=color, linewidth=2)
            ax.axvline(saturation_n, color='red', linestyle='--', alpha=0.7, label=f'Sat. ≈ N={saturation_n}')
            ax.set_xlabel('Tamanho da janela (N)')
            ax.set_ylabel('Vazão (Mbps)')
            ax.set_title(f'Cenário {scen}')
            ax.legend(fontsize=8)

        fig.suptitle('Tarefa 5 — Sensibilidade da Janela Go-Back-N (3 Cenários)', fontweight='bold')
        fig.tight_layout()
        _save_fig(fig, 'task05_window_sensitivity')

        self.task_results['task_05'] = {
            'status': 'ok',
            'data': rows,
        }

    # ------------------------------------------------------------------ Tarefa 6
    def task_06_rtt_validation(self):
        print('\n[Tarefa 6] Validação de RTT — SimPy vs tcpdump')
        rows = []
        for scen in SCENARIO_ORDER:
            params = self.delay_params[scen]
            real_rtt = params['rtt_mean_ms']

            sim_rtts = []
            for i in range(self.runs):
                cfg = SimConfig.from_scenario(
                    scen,
                    file_size_bytes=512 * 1024,
                    delay_mean_ms=params['delay_mean_ms'],
                    delay_std_ms=params['delay_std_ms'],
                    seed=6000 + i,
                )
                res = run_simulation(cfg)
                if res.mean_rtt_ms > 0:
                    sim_rtts.append(res.mean_rtt_ms)

            sim_mean = float(np.mean(sim_rtts)) if sim_rtts else 0.0
            rows.append({
                'scenario': scen,
                'real_rtt_ms': real_rtt,
                'sim_rtt_ms': sim_mean,
                'diff_ms': sim_mean - real_rtt,
                'diff_pct': (sim_mean - real_rtt) / real_rtt * 100 if real_rtt else 0,
            })

        df = pd.DataFrame(rows)
        df.to_csv(DATA_DIR / 'task06_rtt_validation.csv', index=False)

        fig, ax = plt.subplots(figsize=(8, 5))
        x = np.arange(len(SCENARIO_ORDER))
        for idx, scen in enumerate(SCENARIO_ORDER):
            ax.bar(x[idx] - 0.2, df.loc[idx, 'real_rtt_ms'], 0.4, color=COLORS_LIGHT[scen])
            ax.bar(x[idx] + 0.2, df.loc[idx, 'sim_rtt_ms'], 0.4, color=COLORS[scen])
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor='#cccccc', label='Real (tcpdump/Fase 1)'),
            Patch(facecolor='#555555', label='SimPy'),
        ] + [Patch(facecolor=COLORS[s], label=f'Cenário {s}') for s in SCENARIO_ORDER]
        ax.legend(handles=legend_elements, fontsize=8)
        ax.set_xticks(x)
        ax.set_xticklabels([f'Cenário {s}' for s in SCENARIO_ORDER])
        ax.set_ylabel('RTT médio (ms)')
        ax.set_title('Tarefa 6 — RTT Médio: Simulado vs Real', fontweight='bold')
        _save_fig(fig, 'task06_rtt_validation')

        self.task_results['task_06'] = {'status': 'ok', 'data': rows}

    # ------------------------------------------------------------------ Tarefa 7
    def task_07_jitter_impact(self):
        print('\n[Tarefa 7] Impacto do Jitter na estabilidade do fluxo — 3 cenários × 2 métricas')
        jitter_levels = [0, 5, 10, 20, 40] if not self.quick else [0, 10, 40]
        rows = []

        for scen in SCENARIO_ORDER:
            for jitter in jitter_levels:
                throughputs = []
                for i in range(min(self.runs, 15)):
                    cfg = SimConfig.from_scenario(
                        scen, file_size_bytes=1024 * 1024,
                        jitter_std_ms=float(jitter), seed=7000 + ord(scen) + jitter + i,
                    )
                    res = run_simulation(cfg)
                    throughputs.append(res.throughput_mbps)

                mean, lo, hi = _ci95(throughputs)
                cv = float(np.std(throughputs, ddof=1) / np.mean(throughputs)) if np.mean(throughputs) else 0
                rows.append({
                    'scenario': scen,
                    'jitter_std_ms': jitter,
                    'throughput_mean_mbps': mean,
                    'throughput_cv': cv,
                    'ci_low': lo,
                    'ci_high': hi,
                })

        df = pd.DataFrame(rows)
        df.to_csv(DATA_DIR / 'task07_jitter_impact.csv', index=False)

        fig, axes = plt.subplots(2, 3, figsize=(15, 9))
        for col, scen in enumerate(SCENARIO_ORDER):
            sub = df[df['scenario'] == scen]
            color = COLORS[scen]

            ax1 = axes[0, col]
            ax1.errorbar(sub['jitter_std_ms'], sub['throughput_mean_mbps'],
                         yerr=[sub['throughput_mean_mbps'] - sub['ci_low'],
                               sub['ci_high'] - sub['throughput_mean_mbps']],
                         fmt='o-', capsize=4, color=color)
            ax1.set_xlabel('Jitter σ (ms)')
            ax1.set_ylabel('Vazão (Mbps)')
            ax1.set_title(f'Cenário {scen} — Vazão vs Jitter')

            ax2 = axes[1, col]
            ax2.plot(sub['jitter_std_ms'], sub['throughput_cv'], 's-', color=color)
            ax2.set_xlabel('Jitter σ (ms)')
            ax2.set_ylabel('Coef. de variação (CV)')
            ax2.set_title(f'Cenário {scen} — Estabilidade vs Jitter')

        fig.suptitle('Tarefa 7 — Impacto do Jitter (3 Cenários × 2 Métricas)', fontweight='bold')
        fig.tight_layout()
        _save_fig(fig, 'task07_jitter_impact')

        self.task_results['task_07'] = {'status': 'ok', 'data': rows}

    # ------------------------------------------------------------------ Tarefa 8
    def task_08_stress_scenario(self):
        print('\n[Tarefa 8] Cenário de Estresse — 25% de perda')
        rows = []
        stress = SCENARIOS['STRESS']
        elapsed_samples = []

        for i in range(self.runs):
            cfg = SimConfig(
                file_size_bytes=1024 * 1024,
                loss_prob=stress['loss_prob'],
                delay_mean_ms=stress['delay_mean_ms'],
                delay_std_ms=stress['delay_std_ms'],
                scenario='STRESS',
                seed=8000 + i,
            )
            res = run_simulation(cfg)
            elapsed_samples.append(res.elapsed_s)
            rows.append({
                'run': i + 1,
                'elapsed_s': res.elapsed_s,
                'throughput_mbps': res.throughput_mbps,
                'retransmissions': res.retransmissions,
            })

        mean_t, lo_t, hi_t = _ci95(elapsed_samples)

        # Extrapolação linear a partir do cenário C (20% perda)
        c_samples = []
        for i in range(min(self.runs, 10)):
            cfg = SimConfig.from_scenario('C', file_size_bytes=1024 * 1024, seed=8100 + i)
            c_samples.append(run_simulation(cfg).elapsed_s)
        c_mean = float(np.mean(c_samples))
        predicted_25 = c_mean * (1 + (0.25 - 0.20) / 0.20 * 0.5)

        summary = {
            'loss_prob': 0.25,
            'predicted_elapsed_s': predicted_25,
            'simulated_elapsed_mean_s': mean_t,
            'ci_low_s': lo_t,
            'ci_high_s': hi_t,
            'runs': self.runs,
        }

        pd.DataFrame(rows).to_csv(DATA_DIR / 'task08_stress_scenario.csv', index=False)

        fig, ax = plt.subplots(figsize=(7, 5))
        err_low = [0, mean_t - lo_t]
        err_high = [0, hi_t - mean_t]
        ax.bar(['Predito (extrap.)', 'SimPy (25% perda)'], [predicted_25, mean_t],
               color=[COLORS_LIGHT['C'], COLORS['C']],
               yerr=[err_low, err_high], capsize=6)
        ax.set_ylabel('Tempo de transferência (s)')
        ax.set_title('Tarefa 8 — Estresse: 25% Perda (1 MB)', fontweight='bold')
        _save_fig(fig, 'task08_stress_scenario')

        self.task_results['task_08'] = {'status': 'ok', 'summary': summary, 'runs': rows}

    # ------------------------------------------------------------------ Tarefa 9
    def task_09_efficiency_analysis(self):
        print('\n[Tarefa 9] Eficiência — pacotes de dados vs ACKs')
        rows = []
        for scen in SCENARIO_ORDER:
            ratios = []
            for i in range(min(self.runs, 10)):
                cfg = SimConfig.from_scenario(scen, file_size_bytes=1024 * 1024, seed=9000 + i)
                res = run_simulation(cfg)
                ratios.append(res.efficiency_ratio)

            mean_ratio = float(np.mean(ratios))
            rows.append({
                'scenario': scen,
                'efficiency_ratio': mean_ratio,
                'overhead_pct': (1 - mean_ratio) * 100,
                'data_share_pct': mean_ratio * 100,
            })

        df = pd.DataFrame(rows)
        df.to_csv(DATA_DIR / 'task09_efficiency.csv', index=False)

        fig, ax = plt.subplots(figsize=(8, 5))
        labels = [f'Cenário {s}' for s in df['scenario']]
        for idx, (scen, row) in enumerate(zip(df['scenario'], df.itertuples())):
            ax.bar(labels[idx], row.data_share_pct, color=COLORS[scen],
                   label='Dados' if idx == 0 else '')
            ax.bar(labels[idx], row.overhead_pct, bottom=row.data_share_pct,
                   color=COLORS_LIGHT[scen], label='ACKs (controle)' if idx == 0 else '')
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor='#555555', label='Dados'),
            Patch(facecolor='#cccccc', label='ACKs (controle)'),
        ] + [Patch(facecolor=COLORS[s], label=f'Cenário {s}') for s in SCENARIO_ORDER]
        ax.legend(handles=legend_elements, fontsize=8)
        ax.set_ylabel('Proporção (%)')
        ax.set_title('Tarefa 9 — Eficiência: Dados vs Controle', fontweight='bold')
        _save_fig(fig, 'task09_efficiency')

        self.task_results['task_09'] = {'status': 'ok', 'data': rows}

    # ------------------------------------------------------------------ Tarefa 10
    def task_10_statistical_convergence(self):
        print(f'\n[Tarefa 10] Convergência Estatística — {self.runs} execuções, IC 95%')
        all_tp: dict[str, list[float]] = {scen: [] for scen in SCENARIO_ORDER}
        rows = []

        for scen in SCENARIO_ORDER:
            for i in range(self.runs):
                cfg = SimConfig.from_scenario(scen, file_size_bytes=1024 * 1024, seed=10000 + i)
                res = run_simulation(cfg)
                all_tp[scen].append(res.throughput_mbps)

            tp_mean, tp_lo, tp_hi = _ci95(all_tp[scen])
            rows.append({
                'scenario': scen,
                'n_runs': self.runs,
                'throughput_mean': tp_mean,
                'throughput_ci95_low': tp_lo,
                'throughput_ci95_high': tp_hi,
            })

        df = pd.DataFrame(rows)
        df.to_csv(DATA_DIR / 'task10_convergence.csv', index=False)

        # 1 subplot por cenário com curva de convergência + IC 95% sombreado
        n_range = list(range(2, self.runs + 1))
        scen_labels = {s: SCENARIOS[s]['label'] for s in SCENARIO_ORDER}

        fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=False)
        for ax, scen in zip(axes, SCENARIO_ORDER):
            vals = all_tp[scen]
            means, lows, highs = [], [], []
            for n in n_range:
                m, lo, hi = _ci95(vals[:n])
                means.append(m)
                lows.append(lo)
                highs.append(hi)

            color = COLORS[scen]
            ax.plot(n_range, means, '-', color=color, linewidth=2)
            ax.fill_between(n_range, lows, highs, alpha=0.25, color=color)
            ax.set_xlabel('Número de repetições (n)')
            ax.set_ylabel('Vazão média (Mbps)')
            ax.set_title(f'Cenário {scen}\n{scen_labels[scen]}', fontsize=9)

        fig.suptitle(f'Tarefa 10 — Convergência da Vazão com IC 95% (n até {self.runs})', fontweight='bold')
        fig.tight_layout()
        _save_fig(fig, 'task10_convergence')

        self.task_results['task_10'] = {'status': 'ok', 'n_runs': self.runs, 'data': rows}


def main():
    quick = '--quick' in sys.argv
    runner = ValidationRunner(quick=quick)
    runner.run_all()


if __name__ == '__main__':
    main()
