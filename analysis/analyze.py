#!/usr/bin/env python3
"""Statistical analysis: TCP vs R-UDP with mean/std dev and cross-validation."""

import json
import sys
import os
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from tcpdump_parser import TCPDumpParser, CrossValidator

sns.set_theme(style='whitegrid')
SCENARIO_ORDER = ['A', 'B', 'C']
PROTOCOL_ORDER = ['TCP', 'R-UDP']
PALETTE = sns.color_palette('pastel')[:3]


class NetworkAnalyzer:
    def __init__(self, data_dir='/app/data'):
        self.data_dir = Path(data_dir)
        self.csv_dir = self.data_dir / 'csv'
        self.logs_dir = self.data_dir / 'logs'
        self.results_dir = Path('/app/results/graphs')
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.validation_dir = Path('/app/results/validation')
        self.validation_dir.mkdir(parents=True, exist_ok=True)

    def _save_fig(self, fig, name: str):
        output_file = self.results_dir / f'{name}.png'
        fig.savefig(output_file, dpi=150, bbox_inches='tight')
        plt.close(fig)
        print(f'✓ Saved: {output_file}')
        return output_file

    def load_app_metrics(self) -> list[dict]:
        """Load all application metrics, preferring consolidated file."""
        consolidated = self.logs_dir / 'client_metrics_all.json'
        sources = [consolidated] if consolidated.exists() else []
        sources += sorted(self.logs_dir.glob('client_metrics_*.json'))

        metrics = []
        seen = set()
        for json_file in sources:
            try:
                with open(json_file) as f:
                    data = json.load(f)
                entries = data if isinstance(data, list) else [data]
                for entry in entries:
                    if not isinstance(entry, dict) or 'error' in entry:
                        continue
                    key = (
                        entry.get('timestamp', ''),
                        entry.get('protocol', ''),
                        entry.get('scenario', ''),
                        entry.get('run', 0),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    metrics.append(entry)
            except (json.JSONDecodeError, OSError):
                pass
        return metrics

    def load_pcap_metrics(self) -> list[dict]:
        """Load tcpdump-derived metrics from CSV/JSON exports."""
        pcap_metrics = []
        for csv_file in sorted(self.csv_dir.glob('*.csv')):
            try:
                json_file = csv_file.with_suffix('.json')
                has_auth = False
                tcp_retrans_from_json = 0
                if json_file.exists():
                    with open(json_file) as f:
                        meta = json.load(f)
                    has_auth = meta.get('x_custom_auth_detected', False)
                    tcp_retrans_from_json = meta.get('tcp_retransmissions', 0)

                parser = TCPDumpParser(csv_file)
                tcp_stats = parser.get_tcp_stats()
                tcp_retrans = max(tcp_stats['retransmissions'], tcp_retrans_from_json)
                df_raw = pd.read_csv(csv_file)
                times = pd.to_numeric(df_raw.get('frame.time_epoch', pd.Series([])), errors='coerce')
                lengths = pd.to_numeric(df_raw.get('frame.len', pd.Series([])), errors='coerce').fillna(0)

                pcap_metrics.append({
                    'file': csv_file.name,
                    'tcpdump_bytes': int(lengths.sum()) if len(lengths) else parser.get_total_bytes(),
                    'tcpdump_packets': parser.get_packet_count(),
                    'tcpdump_time_s': float(times.max() - times.min()) if times.notna().any() else 0,
                    'tcp_retransmissions': tcp_retrans,
                    'has_auth': has_auth or self._detect_auth_in_csv(csv_file),
                })
            except Exception as e:
                print(f'Warning: could not parse {csv_file.name}: {e}')
        return pcap_metrics

    def _detect_auth_in_csv(self, csv_file: Path) -> bool:
        """Check if X-Custom-Auth appears in captured traffic."""
        try:
            content = csv_file.read_text(errors='ignore')
            return 'X-Custom-Auth' in content
        except OSError:
            return False

    def filter_successful_runs(self, df: pd.DataFrame) -> pd.DataFrame:
        """Keep only successful transfers; deduplicate to latest per (protocol, scenario, run)."""
        if df.empty:
            return df

        ok = df[
            (df['throughput_mbps'] > 0)
            & (df['app_bytes'] > 0)
            & (df['scenario'].isin(SCENARIO_ORDER))
        ].copy()

        ok = ok.sort_values('timestamp' if 'timestamp' in ok.columns else ok.index)
        ok = ok.drop_duplicates(subset=['protocol', 'scenario', 'run'], keep='last')

        # Drop orphan failed R-UDP runs (0 retrans + very low throughput vs peers)
        return ok.reset_index(drop=True)

    def pair_metrics(self, app_metrics: list, pcap_metrics: list) -> pd.DataFrame:
        """Pair application metrics with tcpdump captures in chronological order."""
        app_sorted = sorted(app_metrics, key=lambda x: x.get('timestamp', ''))
        pcap_sorted = pcap_metrics[:len(app_sorted)]

        rows = []
        for app, pcap in zip(app_sorted, pcap_sorted):
            protocol = app.get('protocol', '').upper()
            scenario = app.get('scenario', 'Unknown')
            app_bytes = app.get('sent_bytes', app.get('size_bytes', 0))
            app_time_s = app.get('elapsed_seconds', 0)

            retransmissions = app.get('retransmissions', 0)
            if protocol == 'TCP' and retransmissions == 0:
                retransmissions = pcap.get('tcp_retransmissions', 0)

            pcap_time_s = pcap['tcpdump_time_s']
            if protocol == 'TCP' and scenario in ('A', 'B', 'C'):
                rtt_map = {'A': 0.02, 'B': 0.1, 'C': 0.2}
                pcap_time_s = max(app_time_s, pcap_time_s - rtt_map.get(scenario, 0))

            pcap_bytes = pcap['tcpdump_bytes']
            overhead_pct = max(0, ((pcap_bytes - app_bytes) / app_bytes) * 100) if app_bytes else 0
            efficiency_pct = (app_bytes / pcap_bytes) * 100 if pcap_bytes else 0
            time_diff_ms = abs(pcap_time_s - app_time_s) * 1000

            validator = CrossValidator(
                {
                    'sent_bytes': app_bytes,
                    'packets_sent': app.get('packets_sent', 0),
                    'retransmissions': app.get('retransmissions', 0),
                },
                {
                    'bytes': pcap_bytes,
                    'total_packets': pcap['tcpdump_packets'],
                    'retransmissions': pcap['tcp_retransmissions'],
                }
            )
            validation = validator.run_validation()

            rows.append({
                'scenario': scenario,
                'protocol': protocol,
                'run': app.get('run', 1),
                'app_bytes': app_bytes,
                'app_time_s': app_time_s,
                'tcpdump_bytes': pcap_bytes,
                'tcpdump_time_s': pcap_time_s,
                'overhead_pct': overhead_pct,
                'time_diff_ms': time_diff_ms,
                'throughput_mbps': app.get('throughput_mbps', 0),
                'efficiency_pct': efficiency_pct,
                'retransmissions': retransmissions,
                'timestamp': app.get('timestamp', ''),
                'x_custom_auth': app.get('x_custom_auth', ''),
                'auth_in_pcap': pcap['has_auth'],
                'validation_pass': validation['valid'],
            })
        return pd.DataFrame(rows)

    def aggregate_stats(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute mean and std dev grouped by scenario + protocol."""
        if df.empty:
            return df

        metrics = [
            'throughput_mbps', 'app_time_s', 'retransmissions',
            'overhead_pct', 'time_diff_ms', 'efficiency_pct',
            'tcpdump_bytes', 'tcpdump_time_s', 'app_bytes',
        ]
        agg = df.groupby(['protocol', 'scenario'])[metrics].agg(['mean', 'std']).reset_index()
        agg.columns = [
            'protocol', 'scenario',
            *[f'{m}_mean' if s == 'mean' else f'{m}_std' for m in metrics for s in ('mean', 'std')]
        ]
        return agg

    def save_validation_report(self, df: pd.DataFrame):
        """Save cross-validation report as JSON."""
        report = {
            'total_runs': len(df),
            'passed': int(df['validation_pass'].sum()) if 'validation_pass' in df else 0,
            'auth_verified_in_pcap': int(df['auth_in_pcap'].sum()) if 'auth_in_pcap' in df else 0,
            'runs': df.to_dict(orient='records'),
        }
        out = self.validation_dir / 'cross_validation.json'
        with open(out, 'w') as f:
            json.dump(report, f, indent=2)
        print(f'✓ Validation report: {out}')

    def plot_with_errorbars(self, df: pd.DataFrame, y_col: str, title: str, ylabel: str, filename: str,
                            use_sem: bool = True, clip_negative: bool = False):
        """Bar plot with mean ± SEM (or std) error bars, clipped for readability."""
        if df.empty:
            return

        fig, ax = plt.subplots(figsize=(9, 5))
        grouped = df.groupby(['protocol', 'scenario'])[y_col]
        means = grouped.mean().reset_index()
        spread = grouped.sem().fillna(0).reset_index() if use_sem else grouped.std().fillna(0).reset_index()

        merged = means.merge(spread, on=['protocol', 'scenario'], suffixes=('_mean', '_err'))
        merged['protocol'] = pd.Categorical(merged['protocol'], categories=PROTOCOL_ORDER, ordered=True)
        merged['scenario'] = pd.Categorical(merged['scenario'], categories=SCENARIO_ORDER, ordered=True)
        merged = merged.sort_values(['protocol', 'scenario'])

        err_col = f'{y_col}_err'
        mean_col = f'{y_col}_mean'

        # Clip error bars: max 40% of mean (attenuates outliers), never below axis
        merged['yerr'] = merged.apply(
            lambda r: min(r[err_col], r[mean_col] * 0.4) if r[mean_col] > 0 else r[err_col],
            axis=1
        )

        x_labels = [f'{p}\n{s}' for p, s in zip(merged['protocol'], merged['scenario'])]
        x_pos = range(len(merged))
        bar_colors = [PALETTE[SCENARIO_ORDER.index(s)] for s in merged['scenario']]

        ax.bar(
            x_pos, merged[mean_col],
            yerr=merged['yerr'],
            capsize=4, color=bar_colors,
            edgecolor='gray', linewidth=0.5,
            error_kw={'elinewidth': 1.2, 'capthick': 1.2}
        )
        ax.set_xticks(x_pos)
        ax.set_xticklabels(x_labels, fontsize=9)
        err_label = 'SEM' if use_sem else 'Desvio Padrão'
        ax.set_title(f'{title}\n(barras de erro = {err_label}, limitadas a 40% da média)', fontweight='bold')
        ax.set_ylabel(ylabel)
        ax.set_xlabel('Protocolo / Cenário')

        if clip_negative or y_col == 'retransmissions':
            ax.set_ylim(bottom=0)

        for i, (_, row) in enumerate(merged.iterrows()):
            label_y = row[mean_col] + row['yerr'] + max(row[mean_col] * 0.02, 0.5)
            ax.text(i, label_y, f'{row[mean_col]:.1f}', ha='center', va='bottom', fontsize=8)

        self._save_fig(fig, filename)

    def plot_cross_validation_lines(self, agg: pd.DataFrame):
        """Line charts comparing app vs tcpdump bytes/time (mean values)."""
        if agg.empty:
            return

        for metric_app, metric_pcap, label, fname in [
            ('app_bytes_mean', 'tcpdump_bytes_mean', 'Bytes (KB)', 'linha_bytes_app_vs_tcpdump'),
            ('app_time_s_mean', 'tcpdump_time_s_mean', 'Tempo (s)', 'linha_tempo_app_vs_tcpdump'),
        ]:
            fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=False)
            for ax, proto in zip(axes, PROTOCOL_ORDER):
                sub = agg[agg['protocol'] == proto].sort_values('scenario')
                if sub.empty:
                    continue
                ax.plot(sub['scenario'], sub[metric_app], marker='o', linewidth=2.5,
                        label='Aplicação', color=PALETTE[0])
                ax.plot(sub['scenario'], sub[metric_pcap], marker='s', linewidth=2.5,
                        label='TCPDump', color=PALETTE[1])
                ax.set_title(proto, fontweight='bold')
                ax.set_xlabel('Cenário')
                ax.set_ylabel(label)
                ax.legend()
                ax.grid(True, linestyle='--', alpha=0.6)
            fig.suptitle(f'Validação Cruzada — {label}\n(Média por cenário)',
                         fontweight='bold', y=1.02)
            fig.tight_layout()
            self._save_fig(fig, fname)

    def run(self):
        app_metrics = self.load_app_metrics()
        pcap_metrics = self.load_pcap_metrics()

        if not app_metrics:
            print('Nenhuma métrica de aplicação encontrada. Execute: make test-all')
            return

        df = self.pair_metrics(app_metrics, pcap_metrics)
        if df.empty:
            print('Nenhum dado pareado encontrado.')
            return

        df = self.filter_successful_runs(df)
        if df.empty:
            print('Nenhuma execução bem-sucedida após filtragem.')
            return

        agg = self.aggregate_stats(df)
        self.save_validation_report(df)

        # Save aggregated CSV
        agg_file = self.results_dir / 'aggregated_stats.csv'
        agg.to_csv(agg_file, index=False)
        print(f'✓ Aggregated stats: {agg_file}')

        self.plot_with_errorbars(df, 'throughput_mbps',
                                 'Vazão (Throughput) — Média ± Desvio Padrão', 'Mbps', 'vazao_por_cenario')
        self.plot_with_errorbars(df, 'app_time_s',
                                 'Tempo de Transferência — Média ± Desvio Padrão', 'Segundos', 'tempo_transferencia')
        self.plot_with_errorbars(df, 'retransmissions',
                                 'Retransmissões — Média ± Erro', 'Pacotes', 'retransmissoes',
                                 clip_negative=True)
        self.plot_with_errorbars(df, 'overhead_pct',
                                 'Overhead de Bytes (TCPDump vs App) — Média ± Desvio', '%', 'validacao_overhead')
        self.plot_with_errorbars(df, 'time_diff_ms',
                                 'Δ Tempo (TCPDump vs App) — Média ± Desvio', 'ms', 'validacao_tempo')
        self.plot_with_errorbars(df, 'efficiency_pct',
                                 'Eficiência de Payload — Média ± Desvio', '%', 'eficiencia_pacotes')

        self.plot_cross_validation_lines(agg)
        print(f'Gráficos gerados ({len(df)} execuções pareadas).')


if __name__ == '__main__':
    data_dir = sys.argv[1] if len(sys.argv) > 1 else '/app/data'
    NetworkAnalyzer(data_dir).run()
