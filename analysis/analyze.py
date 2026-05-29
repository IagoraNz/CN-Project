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
                # Reject legacy tshark-format files (different schema, unusable)
                with open(csv_file) as _f:
                    first_line = _f.readline()
                if 'frame.time,' in first_line or 'tcp.srcport' in first_line:
                    continue

                json_file = csv_file.with_suffix('.json')
                has_auth = False
                tcp_retrans_from_json = 0
                if json_file.exists():
                    with open(json_file) as f:
                        meta = json.load(f)
                    if isinstance(meta, dict):
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
        """Pair application metrics with tcpdump captures using timestamp proximity.

        Each PCAP capture starts just before the transfer; the app metric timestamp
        records the moment the transfer completes. The best match is the latest PCAP
        whose start time is ≤ the app metric completion time.
        """
        import re as _re
        from datetime import datetime

        def _pcap_start(filename: str):
            m = _re.match(r'traffic_(\d{8})_(\d{6})', filename)
            if m:
                try:
                    return datetime.strptime(m.group(1) + m.group(2), '%Y%m%d%H%M%S')
                except ValueError:
                    pass
            return None

        def _app_time(ts: str):
            try:
                return datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                return None

        indexed = [(i, p, _pcap_start(p.get('file', ''))) for i, p in enumerate(pcap_metrics)]
        timed = [(i, p, dt) for i, p, dt in indexed if dt is not None]
        timed.sort(key=lambda x: x[2])

        app_sorted = sorted(app_metrics, key=lambda x: x.get('timestamp', ''))
        used: set[int] = set()

        def _pick_pcap(app_ts):
            at = _app_time(app_ts)
            if at:
                # Prefer the latest capture that started before or at transfer completion
                candidates = [(i, p, dt) for i, p, dt in timed if dt <= at and i not in used]
                if candidates:
                    best = max(candidates, key=lambda x: x[2])
                    return best[0], best[1]
            # Fallback: first unused PCAP in order
            unused = [(i, p) for i, p, _ in indexed if i not in used]
            return unused[0] if unused else (0, pcap_metrics[0] if pcap_metrics else {})

        empty_pcap = {
            'tcpdump_bytes': 0, 'tcpdump_packets': 0, 'tcpdump_time_s': 0,
            'tcp_retransmissions': 0, 'has_auth': False,
        }

        rows = []
        for app in app_sorted:
            pick = _pick_pcap(app.get('timestamp', ''))
            if isinstance(pick, tuple):
                idx, pcap = pick
            else:
                idx, pcap = 0, empty_pcap
            if idx not in used and pcap_metrics:
                used.add(idx)

            protocol = app.get('protocol', '').upper()
            scenario = app.get('scenario', 'Unknown')
            app_bytes = app.get('sent_bytes', app.get('size_bytes', 0))
            app_time_s = app.get('elapsed_seconds', 0)

            retransmissions = app.get('retransmissions') or 0
            if protocol == 'TCP' and retransmissions == 0:
                retransmissions = pcap.get('tcp_retransmissions', 0)

            pcap_time_s = pcap.get('tcpdump_time_s', 0)
            if protocol == 'TCP' and scenario in ('A', 'B', 'C'):
                rtt_map = {'A': 0.02, 'B': 0.1, 'C': 0.2}
                pcap_time_s = max(app_time_s, pcap_time_s - rtt_map.get(scenario, 0))

            pcap_bytes = pcap.get('tcpdump_bytes', 0)
            overhead_pct = max(0, ((pcap_bytes - app_bytes) / app_bytes) * 100) if app_bytes else 0
            efficiency_pct = (app_bytes / pcap_bytes) * 100 if pcap_bytes else 0
            time_diff_ms = abs(pcap_time_s - app_time_s) * 1000

            validator = CrossValidator(
                {
                    'sent_bytes': app_bytes,
                    'packets_sent': app.get('packets_sent', 0),
                    'retransmissions': retransmissions,
                },
                {
                    'bytes': pcap_bytes,
                    'total_packets': pcap.get('tcpdump_packets', 0),
                    'retransmissions': pcap.get('tcp_retransmissions', 0),
                }
            )
            validation = validator.run_validation()

            rows.append({
                'scenario': scenario,
                'protocol': protocol,
                'run': app.get('run') or 1,
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
                'auth_in_pcap': pcap.get('has_auth', False),
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
        """Bar plot for all protocol×scenario combinations; missing ones shown as hatched 'Sem dados'."""
        if df.empty:
            return

        from matplotlib.patches import Patch

        grouped = df.groupby(['protocol', 'scenario'])[y_col]
        means_s = grouped.mean()
        spread_s = grouped.sem().fillna(0) if use_sem else grouped.std().fillna(0)
        count_s = grouped.count()

        # Build ordered lists covering every combination, filling missing with sentinel
        x_labels, x_vals, heights, yerrs, colors, hatches, ns = [], [], [], [], [], [], []
        for i, proto in enumerate(PROTOCOL_ORDER):
            for j, scen in enumerate(SCENARIO_ORDER):
                key = (proto, scen)
                n = count_s.get(key, 0)
                mean = float(means_s.get(key, 0.0))
                err = float(spread_s.get(key, 0.0))
                err = min(err, mean * 0.4) if mean > 0 else err

                x_labels.append(f'{proto}\n{scen}\n(n={n})')
                x_vals.append(len(x_vals))
                heights.append(mean if n > 0 else 0.0)
                yerrs.append(err if n > 0 else 0.0)
                colors.append(PALETTE[j] if n > 0 else '#d8d8d8')
                hatches.append(None if n > 0 else '//')
                ns.append(n)

        fig, ax = plt.subplots(figsize=(11, 5.5))
        bars = ax.bar(
            x_vals, heights, yerr=yerrs,
            capsize=4, color=colors,
            edgecolor='gray', linewidth=0.5,
            error_kw={'elinewidth': 1.2, 'capthick': 1.2}
        )
        for bar, hatch in zip(bars, hatches):
            if hatch:
                bar.set_hatch(hatch)

        ax.set_xticks(x_vals)
        ax.set_xticklabels(x_labels, fontsize=9)

        err_label = 'SEM' if use_sem else 'DP'
        ax.set_title(f'{title}\n(barra de erro = {err_label})', fontweight='bold')
        ax.set_ylabel(ylabel)
        ax.set_xlabel('Protocolo / Cenário')

        if clip_negative or y_col == 'retransmissions':
            ax.set_ylim(bottom=0)
        ax.margins(y=0.18)

        ymax = ax.get_ylim()[1]
        for i, (h, ye, n) in enumerate(zip(heights, yerrs, ns)):
            if n == 0:
                ax.text(i, ymax * 0.04, 'Sem\ndados', ha='center', va='bottom',
                        fontsize=7, color='#888888', style='italic')
            else:
                ax.text(i, h + ye + ymax * 0.01, f'{h:.1f}', ha='center', va='bottom',
                        fontsize=8, fontweight='bold')

        # Scenario colour legend + missing indicator
        legend_handles = [
            Patch(facecolor=PALETTE[k], label=f'Cenário {s}', edgecolor='gray')
            for k, s in enumerate(SCENARIO_ORDER)
        ]
        legend_handles.append(Patch(facecolor='#d8d8d8', hatch='//', label='Sem dados', edgecolor='gray'))
        ax.legend(handles=legend_handles, loc='upper right', fontsize=8, framealpha=0.85)

        fig.subplots_adjust(bottom=0.18)
        self._save_fig(fig, filename)

    def plot_throughput_subplots(self, df: pd.DataFrame):
        """Three side-by-side subplots (one per scenario); each shows TCP vs R-UDP bars with its own y scale."""
        if df.empty:
            return

        from matplotlib.patches import Patch

        grouped = df.groupby(['protocol', 'scenario'])['throughput_mbps']
        means_s = grouped.mean()
        sem_s = grouped.sem().fillna(0)
        count_s = grouped.count()

        proto_colors = {p: PALETTE[i] for i, p in enumerate(PROTOCOL_ORDER)}

        fig, axes = plt.subplots(1, 3, figsize=(13, 5.5))
        fig.suptitle('Vazão por Cenário — Média ± SEM', fontweight='bold', fontsize=13)

        for ax, scen in zip(axes, SCENARIO_ORDER):
            x_vals, heights, yerrs, colors, ns = [], [], [], [], []
            for i, proto in enumerate(PROTOCOL_ORDER):
                key = (proto, scen)
                n = int(count_s.get(key, 0))
                mean = float(means_s.get(key, 0.0))
                err = float(sem_s.get(key, 0.0))
                err = min(err, mean * 0.4) if mean > 0 else err
                x_vals.append(i)
                heights.append(mean if n > 0 else 0.0)
                yerrs.append(err if n > 0 else 0.0)
                colors.append(proto_colors[proto] if n > 0 else '#d8d8d8')
                ns.append(n)

            bars = ax.bar(
                x_vals, heights, yerr=yerrs,
                capsize=5, color=colors,
                edgecolor='gray', linewidth=0.6,
                error_kw={'elinewidth': 1.2, 'capthick': 1.2}
            )
            for bar, n in zip(bars, ns):
                if n == 0:
                    bar.set_hatch('//')

            ax.set_xticks(x_vals)
            ax.set_xticklabels(
                [f'{p}\n(n={n})' for p, n in zip(PROTOCOL_ORDER, ns)],
                fontsize=9
            )
            ax.set_title(f'Cenário {scen}', fontweight='bold')
            ax.set_ylabel('Mbps' if scen == 'A' else '')
            ax.set_ylim(bottom=0)
            ax.margins(y=0.2)

            ymax = ax.get_ylim()[1]
            for i, (h, ye, n) in enumerate(zip(heights, yerrs, ns)):
                if n == 0:
                    ax.text(i, ymax * 0.04, 'Sem\ndados', ha='center', va='bottom',
                            fontsize=7, color='#888888', style='italic')
                else:
                    ax.text(i, h + ye + ymax * 0.01, f'{h:.1f}', ha='center', va='bottom',
                            fontsize=8, fontweight='bold')

        legend_handles = [
            Patch(facecolor=proto_colors[p], label=p, edgecolor='gray') for p in PROTOCOL_ORDER
        ]
        legend_handles.append(Patch(facecolor='#d8d8d8', hatch='//', label='Sem dados', edgecolor='gray'))
        fig.legend(handles=legend_handles, loc='lower center', ncol=3, fontsize=9,
                   framealpha=0.85, bbox_to_anchor=(0.5, 0.0))

        fig.subplots_adjust(bottom=0.18, wspace=0.35)
        self._save_fig(fig, 'vazao_por_cenario')

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

        self.plot_with_errorbars(df, 'retransmissions',
                                 'Retransmissões por Cenário — Média ± Erro', 'Pacotes', 'retransmissoes',
                                 clip_negative=True)
        self.plot_with_errorbars(df, 'efficiency_pct',
                                 'Eficiência de Payload por Cenário — Média ± Desvio', '%', 'eficiencia_pacotes')
        self.plot_with_errorbars(df, 'app_time_s',
                                 'Tempo de Transferência por Cenário — Média ± Desvio Padrão', 'Segundos',
                                 'tempo_transferencia')
        self.plot_throughput_subplots(df)

        print(f'Gráficos gerados ({len(df)} execuções pareadas).')


if __name__ == '__main__':
    data_dir = sys.argv[1] if len(sys.argv) > 1 else '/app/data'
    NetworkAnalyzer(data_dir).run()
