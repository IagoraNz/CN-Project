#!/usr/bin/env python3

import json
from pathlib import Path
from datetime import datetime
import sys
import os

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'analysis'))

from tcpdump_parser import TCPDumpParser, CrossValidator  # noqa: F401

sns.set_theme(style='whitegrid', palette='muted')

SCENARIO_LABELS = {
    'A': 'Cenário A\n(0% perda, 10 ms)',
    'B': 'Cenário B\n(10% perda, 50 ms)',
    'C': 'Cenário C\n(20% perda, 100 ms)',
    'N/A': 'Sem cenário',
}


class NetworkAnalyzer:
    def __init__(self, data_dir='/app/data'):
        self.data_dir = Path(data_dir)
        self.csv_dir = self.data_dir / 'csv'
        self.logs_dir = self.data_dir / 'logs'
        self.results_dir = Path('/app/results/graphs')
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def _save_fig(self, fig, name: str, subdir: str = ''):
        out_dir = self.results_dir / subdir if subdir else self.results_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        output_file = out_dir / f'{name}.png'
        fig.savefig(output_file, dpi=150, bbox_inches='tight')
        plt.close(fig)
        print(f"✓ Saved: {output_file}")
        return output_file

    def load_csv_data(self):
        """Load all CSV files from tcpdump exports"""
        dfs = []
        for csv_file in sorted(self.csv_dir.glob('*.csv')):
            try:
                df = pd.read_csv(csv_file)
                df['file'] = csv_file.name
                dfs.append(df)
            except Exception as e:
                print(f"Error loading {csv_file}: {e}")

        return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

    def load_metrics(self):
        """Load metrics JSON files from server and client logs"""
        metrics = []

        for json_file in sorted(self.logs_dir.glob('metrics_*.json')):
            try:
                with open(json_file) as f:
                    metrics.append(json.load(f))
            except Exception as e:
                print(f"Error loading {json_file}: {e}")

        # Client logs: list of transfers → normalize to server metrics shape
        client_transfers = {'tcp': [], 'rudp': []}
        for json_file in sorted(self.logs_dir.glob('client_metrics_*.json')):
            try:
                with open(json_file) as f:
                    for entry in json.load(f):
                        proto = entry.get('protocol', '').upper()
                        if proto == 'TCP':
                            client_transfers['tcp'].append(entry)
                        elif proto in ('R-UDP', 'RUDP'):
                            client_transfers['rudp'].append(entry)
            except Exception as e:
                print(f"Error loading {json_file}: {e}")

        if client_transfers['tcp'] or client_transfers['rudp']:
            metrics.append({
                'tcp': {'transfers': client_transfers['tcp']},
                'rudp': {'transfers': client_transfers['rudp']},
            })

        return metrics

    def transfers_dataframe(self, metrics) -> pd.DataFrame:
        """Flatten all transfers into a single DataFrame."""
        rows = []
        for m in metrics:
            for proto_key, label in (('tcp', 'TCP'), ('rudp', 'R-UDP')):
                for transfer in m.get(proto_key, {}).get('transfers', []):
                    if 'error' in transfer:
                        continue
                    rows.append({
                        'scenario': str(transfer.get('scenario', 'N/A')).upper(),
                        'protocol': label,
                        'throughput_mbps': transfer.get('throughput_mbps', 0),
                        'elapsed_seconds': transfer.get('elapsed_seconds', 0),
                        'retransmissions': transfer.get('retransmissions', 0),
                        'filename': transfer.get('filename', ''),
                        'timestamp': transfer.get('timestamp', ''),
                    })
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    def _infer_scenarios(self, df: pd.DataFrame) -> pd.DataFrame:
        """Infer A/B/C from test-all order when scenario was not recorded."""
        if df.empty or (df['scenario'] != 'N/A').any():
            return df

        ordered = df.sort_values('timestamp').reset_index(drop=True)
        pattern = ['A', 'A', 'B', 'B', 'C', 'C']  # tcp+rudp per scenario
        n = len(ordered)
        blocks = n // len(pattern)
        if blocks == 0:
            return ordered

        for block in range(blocks):
            start = block * len(pattern)
            for i, sc in enumerate(pattern):
                ordered.loc[start + i, 'scenario'] = sc

        print(f"  ℹ Cenários inferidos para {blocks * len(pattern)} transferências (ordem make test-all)")
        return ordered

    def _aggregate_runs(self, df: pd.DataFrame) -> pd.DataFrame:
        """Average metrics when the same scenario+protocol was run more than once."""
        if df.empty:
            return df
        return (
            df.groupby(['scenario', 'protocol'], as_index=False)
            .agg({
                'throughput_mbps': 'mean',
                'elapsed_seconds': 'mean',
                'retransmissions': 'mean',
                'filename': 'first',
                'timestamp': 'last',
            })
        )

    def plot_throughput_comparison(self, metrics):
        """Plot throughput comparison TCP vs R-UDP"""
        rows = []
        for m in metrics:
            for transfer in m.get('tcp', {}).get('transfers', []):
                tp = transfer.get('throughput_mbps', 0)
                if tp > 0:
                    rows.append({'protocol': 'TCP', 'throughput_mbps': tp})
            for transfer in m.get('rudp', {}).get('transfers', []):
                tp = transfer.get('throughput_mbps', 0)
                if tp > 0:
                    rows.append({'protocol': 'R-UDP', 'throughput_mbps': tp})

        if not rows:
            print("No throughput data for plot")
            return None

        df = pd.DataFrame(rows)
        fig, ax = plt.subplots(figsize=(8, 5))
        sns.boxplot(data=df, x='protocol', y='throughput_mbps', ax=ax)
        ax.set_title('Throughput Comparison: TCP vs R-UDP')
        ax.set_ylabel('Throughput (Mbps)')
        ax.set_xlabel('Protocol')
        return self._save_fig(fig, 'throughput_comparison')

    def plot_transfer_time_comparison(self, metrics):
        """Plot transfer time comparison"""
        rows = []
        for m in metrics:
            for transfer in m.get('tcp', {}).get('transfers', []):
                t = transfer.get('elapsed_seconds', 0)
                if t > 0:
                    rows.append({'protocol': 'TCP', 'elapsed_seconds': t})
            for transfer in m.get('rudp', {}).get('transfers', []):
                t = transfer.get('elapsed_seconds', 0)
                if t > 0:
                    rows.append({'protocol': 'R-UDP', 'elapsed_seconds': t})

        if not rows:
            print("No transfer time data for plot")
            return None

        df = pd.DataFrame(rows)
        fig, ax = plt.subplots(figsize=(8, 5))
        sns.boxplot(data=df, x='protocol', y='elapsed_seconds', ax=ax)
        ax.set_title('Transfer Time Comparison')
        ax.set_ylabel('Time (seconds)')
        ax.set_xlabel('Protocol')
        return self._save_fig(fig, 'transfer_time_comparison')

    def plot_retransmission_stats(self, metrics):
        """Plot retransmission statistics for R-UDP"""
        rows = []
        for m in metrics:
            for i, transfer in enumerate(m.get('rudp', {}).get('transfers', [])):
                rows.append({
                    'transfer': transfer.get('filename', f'transfer_{i}'),
                    'retransmissions': transfer.get('retransmissions', 0),
                })

        if not rows:
            print("No R-UDP retransmission data available")
            return None

        df = pd.DataFrame(rows)
        fig, ax = plt.subplots(figsize=(10, 5))
        sns.barplot(data=df, x='transfer', y='retransmissions', ax=ax, palette='viridis')
        ax.set_title('Retransmissions by Transfer (R-UDP)')
        ax.set_ylabel('Retransmissions')
        ax.set_xlabel('Transfer')
        plt.xticks(rotation=45, ha='right')
        return self._save_fig(fig, 'retransmissions')

    def analyze_packet_loss(self, tcpdump_data):
        """Plot packets captured per test file"""
        if tcpdump_data.empty:
            print("No tcpdump CSV data available (run tests with capture first)")
            return None

        packet_stats = tcpdump_data.groupby('file').size().reset_index(name='packets')
        fig, ax = plt.subplots(figsize=(10, 5))
        sns.barplot(data=packet_stats, x='file', y='packets', ax=ax)
        ax.set_title('Packets Captured by Test')
        ax.set_ylabel('Number of Packets')
        ax.set_xlabel('Capture file')
        plt.xticks(rotation=45, ha='right')
        return self._save_fig(fig, 'packet_analysis')

    def plot_by_scenario(self, df: pd.DataFrame):
        """Generate per-scenario PNG charts (throughput, time, retransmissions)."""
        if df.empty:
            print("No transfer data for per-scenario plots")
            return

        df = self._infer_scenarios(df)
        df = self._aggregate_runs(df[df['scenario'].isin(['A', 'B', 'C'])])
        scenarios = [s for s in ['A', 'B', 'C'] if s in df['scenario'].values]

        if not scenarios:
            print("No scenario-tagged data (run: make test-all)")
            return

        subdir = 'by_scenario'

        # Overview: all scenarios side by side
        overview = df[df['scenario'].isin(scenarios)].copy()
        overview['scenario_label'] = overview['scenario'].map(
            lambda s: SCENARIO_LABELS.get(s, s)
        )

        for metric, ycol, ylabel, fname in [
            ('throughput', 'throughput_mbps', 'Throughput (Mbps)', 'throughput_all_scenarios'),
            ('time', 'elapsed_seconds', 'Tempo (s)', 'transfer_time_all_scenarios'),
            ('retransmissions', 'retransmissions', 'Retransmissões', 'retransmissions_all_scenarios'),
        ]:
            sub = overview[overview[ycol] > 0] if metric != 'retransmissions' else overview
            if sub.empty:
                continue
            fig, ax = plt.subplots(figsize=(10, 5))
            sns.barplot(data=sub, x='scenario_label', y=ycol, hue='protocol', ax=ax)
            ax.set_title(f'{ylabel} por cenário')
            ax.set_xlabel('Cenário de rede')
            ax.set_ylabel(ylabel)
            ax.legend(title='Protocolo')
            self._save_fig(fig, fname, subdir)

        # Individual chart per scenario
        for scenario in scenarios:
            sub = df[df['scenario'] == scenario]
            label = SCENARIO_LABELS.get(scenario, f'Cenário {scenario}')

            fig, ax = plt.subplots(figsize=(6, 5))
            tp = sub[sub['throughput_mbps'] > 0]
            if not tp.empty:
                sns.barplot(data=tp, x='protocol', y='throughput_mbps', ax=ax, palette='muted')
                ax.set_title(f'{label}\nThroughput')
                ax.set_ylabel('Mbps')
                ax.set_xlabel('Protocolo')
                self._save_fig(fig, f'scenario_{scenario}_throughput', subdir)

            fig, ax = plt.subplots(figsize=(6, 5))
            tm = sub[sub['elapsed_seconds'] > 0]
            if not tm.empty:
                sns.barplot(data=tm, x='protocol', y='elapsed_seconds', ax=ax, palette='muted')
                ax.set_title(f'{label}\nTempo de transferência')
                ax.set_ylabel('Segundos')
                ax.set_xlabel('Protocolo')
                self._save_fig(fig, f'scenario_{scenario}_transfer_time', subdir)

            fig, ax = plt.subplots(figsize=(6, 5))
            rudp = sub[sub['protocol'] == 'R-UDP']
            if not rudp.empty:
                sns.barplot(data=rudp, x='protocol', y='retransmissions', ax=ax, color='steelblue')
                ax.set_title(f'{label}\nRetransmissões (R-UDP)')
                ax.set_ylabel('Quantidade')
                self._save_fig(fig, f'scenario_{scenario}_retransmissions', subdir)

        print(f"✓ Per-scenario graphs: {self.results_dir / subdir}/")

    def cross_validate(self):
        """Perform cross-validation between app metrics and tcpdump"""
        print("\n=== Cross-Validation Analysis ===\n")

        metrics = self.load_metrics()
        if not metrics:
            print("No metrics available for cross-validation")
            return

        tcp_stats = self._aggregate_stats(metrics, 'tcp')
        rudp_stats = self._aggregate_stats(metrics, 'rudp')

        if not list(self.csv_dir.glob('*.csv')):
            print("No tcpdump CSV files for validation (PCAP→CSV needs tshark)")

        validation_reports = {
            'tcp': self._validate_protocol(tcp_stats, 'tcp'),
            'rudp': self._validate_protocol(rudp_stats, 'rudp'),
        }

        validation_file = Path('/app/results') / f'cross_validation_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        with open(validation_file, 'w') as f:
            json.dump(validation_reports, f, indent=2)

        print(f"✓ Cross-validation report saved: {validation_file}\n")

        for protocol, report in validation_reports.items():
            print(f"\n{protocol.upper()} Protocol:")
            print(f"  Total transfers: {report.get('transfer_count', 0)}")
            print(f"  Total bytes: {report.get('total_bytes', 0)}")
            print(f"  Avg throughput: {report.get('avg_throughput', 0):.2f} Mbps")
            print(f"  Retransmissions: {report.get('retransmissions', 0)}")

    def _aggregate_stats(self, metrics, protocol):
        stats = {
            'transfer_count': 0,
            'total_bytes': 0,
            'total_time': 0,
            'retransmissions': 0,
            'errors': 0,
            'transfers': [],
        }

        for m in metrics:
            proto_data = m.get(protocol, {})
            stats['transfer_count'] += len(proto_data.get('transfers', []))
            stats['total_bytes'] += proto_data.get('total_bytes', 0)
            stats['retransmissions'] += proto_data.get('retransmissions', 0)
            stats['errors'] += proto_data.get('errors', 0)
            stats['transfers'].extend(proto_data.get('transfers', []))

        if stats['transfers']:
            stats['total_time'] = sum(t.get('elapsed_seconds', 0) for t in stats['transfers'])
            stats['avg_throughput'] = (
                stats['total_bytes'] * 8 / stats['total_time'] / 1e6
                if stats['total_time'] > 0 else 0
            )

        return stats

    def _validate_protocol(self, app_stats, protocol):
        return {
            'protocol': protocol,
            'transfer_count': app_stats['transfer_count'],
            'total_bytes': app_stats['total_bytes'],
            'avg_throughput': app_stats.get('avg_throughput', 0),
            'retransmissions': app_stats['retransmissions'],
            'errors': app_stats['errors'],
            'status': 'OK' if app_stats['errors'] == 0 else 'ERRORS',
        }

    def generate_summary_report(self):
        metrics = self.load_metrics()
        if not metrics:
            print("No metrics available")
            return

        report = {
            'timestamp': datetime.now().isoformat(),
            'tcp_stats': self._compute_protocol_stats(metrics, 'tcp'),
            'rudp_stats': self._compute_protocol_stats(metrics, 'rudp'),
        }

        output_file = Path('/app/results') / f'summary_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2)

        print(f"✓ Summary report saved: {output_file}")

    def _compute_protocol_stats(self, metrics, protocol):
        throughputs = []
        times = []
        errors = 0
        total_bytes = 0
        retransmissions = 0

        for m in metrics:
            for transfer in m.get(protocol, {}).get('transfers', []):
                tp = transfer.get('throughput_mbps', 0)
                if tp > 0:
                    throughputs.append(tp)
                times.append(transfer.get('elapsed_seconds', 0))
                total_bytes += transfer.get('size_bytes', transfer.get('received_bytes', 0))
                retransmissions += transfer.get('retransmissions', 0)
            errors += m.get(protocol, {}).get('errors', 0)

        return {
            'transfers': len(throughputs),
            'avg_throughput': float(np.mean(throughputs)) if throughputs else 0,
            'std_throughput': float(np.std(throughputs)) if throughputs else 0,
            'min_throughput': float(np.min(throughputs)) if throughputs else 0,
            'max_throughput': float(np.max(throughputs)) if throughputs else 0,
            'avg_time': float(np.mean(times)) if times else 0,
            'total_bytes': total_bytes,
            'errors': errors,
            'retransmissions': retransmissions,
        }

    def run_all(self):
        print("=== Network Analysis ===\n")
        print("Loading data...")
        metrics = self.load_metrics()
        tcpdump_data = self.load_csv_data()

        print(f"  ✓ Loaded {len(metrics)} metric files")
        print(f"  ✓ Loaded {len(tcpdump_data)} packet rows from CSV\n")

        transfers_df = self.transfers_dataframe(metrics)

        print("Generating PNG plots...")
        self.plot_throughput_comparison(metrics)
        self.plot_transfer_time_comparison(metrics)
        self.plot_retransmission_stats(metrics)
        self.plot_by_scenario(transfers_df)
        self.analyze_packet_loss(tcpdump_data)

        print("\nGenerating summary report...")
        self.generate_summary_report()

        print("\nPerforming cross-validation...")
        self.cross_validate()

        print("\n✓ Analysis complete!")
        print(f"PNG graphs saved to: {self.results_dir}")


if __name__ == '__main__':
    analyzer = NetworkAnalyzer()
    analyzer.run_all()
