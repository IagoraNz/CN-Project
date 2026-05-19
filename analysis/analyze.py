#!/usr/bin/env python3

import pandas as pd
import json
from pathlib import Path
import matplotlib.pyplot as plt
import seaborn as sns
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
import sys
import os

# Add parent src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'analysis'))

from tcpdump_parser import TCPDumpParser, CrossValidator


class NetworkAnalyzer:
    def __init__(self, data_dir='/app/data'):
        self.data_dir = Path(data_dir)
        self.csv_dir = self.data_dir / 'csv'
        self.logs_dir = self.data_dir / 'logs'
        self.results_dir = Path('/app/results/graphs')
        self.results_dir.mkdir(parents=True, exist_ok=True)

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
        """Load metrics JSON files from application"""
        metrics = []
        for json_file in sorted(self.logs_dir.glob('metrics_*.json')):
            try:
                with open(json_file) as f:
                    data = json.load(f)
                    metrics.append(data)
            except Exception as e:
                print(f"Error loading {json_file}: {e}")

        return metrics

    def plot_throughput_comparison(self, metrics):
        """Plot throughput comparison TCP vs R-UDP"""
        tcp_throughput = []
        rudp_throughput = []
        tcp_times = []
        rudp_times = []

        for m in metrics:
            for transfer in m.get('tcp', {}).get('transfers', []):
                tp = transfer.get('throughput_mbps', 0)
                if tp > 0:
                    tcp_throughput.append(tp)
                    tcp_times.append(transfer.get('elapsed_seconds', 0))
            for transfer in m.get('rudp', {}).get('transfers', []):
                tp = transfer.get('throughput_mbps', 0)
                if tp > 0:
                    rudp_throughput.append(tp)
                    rudp_times.append(transfer.get('elapsed_seconds', 0))

        fig = go.Figure()

        fig.add_trace(go.Box(
            y=tcp_throughput,
            name='TCP',
            boxmean='sd'
        ))
        fig.add_trace(go.Box(
            y=rudp_throughput,
            name='R-UDP',
            boxmean='sd'
        ))

        fig.update_layout(
            title='Throughput Comparison: TCP vs R-UDP',
            yaxis_title='Throughput (Mbps)',
            template='plotly_white',
            height=500
        )

        output_file = self.results_dir / 'throughput_comparison.html'
        fig.write_html(str(output_file))
        print(f"✓ Saved: {output_file}")

        return fig

    def plot_transfer_time_comparison(self, metrics):
        """Plot transfer time comparison"""
        tcp_times = []
        rudp_times = []

        for m in metrics:
            for transfer in m.get('tcp', {}).get('transfers', []):
                t = transfer.get('elapsed_seconds', 0)
                if t > 0:
                    tcp_times.append(t)
            for transfer in m.get('rudp', {}).get('transfers', []):
                t = transfer.get('elapsed_seconds', 0)
                if t > 0:
                    rudp_times.append(t)

        fig = go.Figure()

        fig.add_trace(go.Box(
            y=tcp_times,
            name='TCP',
            boxmean='sd'
        ))
        fig.add_trace(go.Box(
            y=rudp_times,
            name='R-UDP',
            boxmean='sd'
        ))

        fig.update_layout(
            title='Transfer Time Comparison',
            yaxis_title='Time (seconds)',
            template='plotly_white',
            height=500
        )

        output_file = self.results_dir / 'transfer_time_comparison.html'
        fig.write_html(str(output_file))
        print(f"✓ Saved: {output_file}")

        return fig

    def plot_retransmission_stats(self, metrics):
        """Plot retransmission statistics"""
        retransmissions = []
        filenames = []

        for m in metrics:
            for transfer in m.get('rudp', {}).get('transfers', []):
                retransmissions.append(transfer.get('retransmissions', 0))
                filenames.append(transfer.get('filename', 'unknown'))

        if not retransmissions:
            print("No R-UDP retransmission data available")
            return None

        fig = px.bar(
            x=filenames,
            y=retransmissions,
            labels={'x': 'Transfer', 'y': 'Retransmissions'},
            title='Retransmissions by Transfer (R-UDP)',
            color=retransmissions,
            color_continuous_scale='Viridis'
        )

        output_file = self.results_dir / 'retransmissions.html'
        fig.write_html(str(output_file))
        print(f"✓ Saved: {output_file}")

        return fig

    def analyze_packet_loss(self, tcpdump_data):
        """Analyze packet loss from tcpdump data"""
        if tcpdump_data.empty:
            print("No tcpdump data available")
            return None

        # Group by file and count packets
        packet_stats = tcpdump_data.groupby('file').size().reset_index(name='packets')

        if packet_stats.empty:
            return None

        fig = px.bar(
            packet_stats,
            x='file',
            y='packets',
            title='Packets Captured by Test',
            labels={'file': 'Test', 'packets': 'Number of Packets'}
        )

        output_file = self.results_dir / 'packet_analysis.html'
        fig.write_html(str(output_file))
        print(f"✓ Saved: {output_file}")

        return fig

    def cross_validate(self):
        """Perform cross-validation between app metrics and tcpdump"""
        print("\n=== Cross-Validation Analysis ===\n")

        metrics = self.load_metrics()
        if not metrics:
            print("No metrics available for cross-validation")
            return

        # Get TCP and R-UDP aggregated stats
        tcp_stats = self._aggregate_stats(metrics, 'tcp')
        rudp_stats = self._aggregate_stats(metrics, 'rudp')

        # Load tcpdump data
        all_csv_files = list(self.csv_dir.glob('*.csv'))
        if not all_csv_files:
            print("No tcpdump CSV files for validation")
            return

        # Create validation reports
        validation_reports = {
            'tcp': self._validate_protocol(tcp_stats, 'tcp'),
            'rudp': self._validate_protocol(rudp_stats, 'rudp')
        }

        # Save validation results
        validation_file = Path('/app/results') / f'cross_validation_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        with open(validation_file, 'w') as f:
            json.dump(validation_reports, f, indent=2)

        print(f"✓ Cross-validation report saved: {validation_file}\n")

        # Print summary
        for protocol, report in validation_reports.items():
            print(f"\n{protocol.upper()} Protocol:")
            print(f"  Total transfers: {report.get('transfer_count', 0)}")
            print(f"  Total bytes: {report.get('total_bytes', 0)}")
            print(f"  Avg throughput: {report.get('avg_throughput', 0):.2f} Mbps")
            print(f"  Retransmissions: {report.get('retransmissions', 0)}")

    def _aggregate_stats(self, metrics, protocol):
        """Aggregate statistics for a protocol"""
        stats = {
            'transfer_count': 0,
            'total_bytes': 0,
            'total_time': 0,
            'retransmissions': 0,
            'errors': 0,
            'transfers': []
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
        """Validate protocol stats"""
        report = {
            'protocol': protocol,
            'transfer_count': app_stats['transfer_count'],
            'total_bytes': app_stats['total_bytes'],
            'avg_throughput': app_stats.get('avg_throughput', 0),
            'retransmissions': app_stats['retransmissions'],
            'errors': app_stats['errors'],
            'status': 'OK' if app_stats['errors'] == 0 else 'ERRORS'
        }
        return report

    def generate_summary_report(self):
        """Generate summary statistics"""
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
        """Compute statistics for a protocol"""
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
                total_bytes += transfer.get('size_bytes', 0)
                retransmissions += transfer.get('retransmissions', 0)
            errors += m.get(protocol, {}).get('errors', 0)

        import numpy as np

        return {
            'transfers': len(throughputs),
            'avg_throughput': float(np.mean(throughputs)) if throughputs else 0,
            'std_throughput': float(np.std(throughputs)) if throughputs else 0,
            'min_throughput': float(np.min(throughputs)) if throughputs else 0,
            'max_throughput': float(np.max(throughputs)) if throughputs else 0,
            'avg_time': float(np.mean(times)) if times else 0,
            'total_bytes': total_bytes,
            'errors': errors,
            'retransmissions': retransmissions
        }

    def run_all(self):
        """Run all analyses"""
        print("=== Network Analysis ===\n")
        print("Loading data...")
        metrics = self.load_metrics()
        tcpdump_data = self.load_csv_data()

        print(f"  ✓ Loaded {len(metrics)} metric files")
        print(f"  ✓ Loaded {len(tcpdump_data)} pcap entries\n")

        print("Generating plots...")
        self.plot_throughput_comparison(metrics)
        self.plot_transfer_time_comparison(metrics)
        self.plot_retransmission_stats(metrics)
        self.analyze_packet_loss(tcpdump_data)

        print("\nGenerating summary report...")
        self.generate_summary_report()

        print("\nPerforming cross-validation...")
        self.cross_validate()

        print("\n✓ Analysis complete!")
        print(f"Results saved to: {self.results_dir}")


if __name__ == '__main__':
    analyzer = NetworkAnalyzer()
    analyzer.run_all()


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
        """Load metrics JSON files from application"""
        metrics = []
        for json_file in sorted(self.logs_dir.glob('metrics_*.json')):
            try:
                with open(json_file) as f:
                    data = json.load(f)
                    metrics.append(data)
            except Exception as e:
                print(f"Error loading {json_file}: {e}")

        return metrics

    def plot_throughput_comparison(self, metrics):
        """Plot throughput comparison TCP vs R-UDP"""
        tcp_throughput = []
        rudp_throughput = []

        for m in metrics:
            for transfer in m.get('tcp', {}).get('transfers', []):
                tcp_throughput.append(transfer.get('throughput_mbps', 0))
            for transfer in m.get('rudp', {}).get('transfers', []):
                rudp_throughput.append(transfer.get('throughput_mbps', 0))

        fig = go.Figure()

        fig.add_trace(go.Box(
            y=tcp_throughput,
            name='TCP',
            boxmean='sd'
        ))
        fig.add_trace(go.Box(
            y=rudp_throughput,
            name='R-UDP',
            boxmean='sd'
        ))

        fig.update_layout(
            title='Throughput Comparison: TCP vs R-UDP',
            yaxis_title='Throughput (Mbps)',
            template='plotly_white',
            height=500
        )

        output_file = self.results_dir / 'throughput_comparison.html'
        fig.write_html(str(output_file))
        print(f"Saved: {output_file}")

        return fig

    def plot_retransmission_stats(self, metrics):
        """Plot retransmission statistics"""
        retransmissions = []
        scenarios = []

        for m in metrics:
            for transfer in m.get('rudp', {}).get('transfers', []):
                retransmissions.append(transfer.get('retransmissions', 0))
                scenarios.append(transfer.get('filename', 'unknown'))

        fig = px.bar(
            x=scenarios,
            y=retransmissions,
            labels={'x': 'Scenario', 'y': 'Retransmissions'},
            title='Retransmissions by Scenario (R-UDP)'
        )

        output_file = self.results_dir / 'retransmissions.html'
        fig.write_html(str(output_file))
        print(f"Saved: {output_file}")

        return fig

    def analyze_packet_loss(self, tcpdump_data):
        """Analyze packet loss from tcpdump data"""
        if tcpdump_data.empty:
            print("No tcpdump data available")
            return None

        # Group by file and count packets
        packet_stats = tcpdump_data.groupby('file').size().reset_index(name='packets')

        fig = px.bar(
            packet_stats,
            x='file',
            y='packets',
            title='Packets Captured by Test',
            labels={'file': 'Test', 'packets': 'Number of Packets'}
        )

        output_file = self.results_dir / 'packet_loss_analysis.html'
        fig.write_html(str(output_file))
        print(f"Saved: {output_file}")

        return fig

    def generate_summary_report(self):
        """Generate summary statistics"""
        metrics = self.load_metrics()

        if not metrics:
            print("No metrics available")
            return

        report = {
            'timestamp': datetime.now().isoformat(),
            'tcp_stats': self._compute_protocol_stats(metrics, 'tcp'),
            'rudp_stats': self._compute_protocol_stats(metrics, 'rudp'),
        }

        output_file = self.results_dir.parent / 'summary_report.json'
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2)

        print(f"Summary report saved: {output_file}")
        print(json.dumps(report, indent=2))

    def _compute_protocol_stats(self, metrics, protocol):
        """Compute statistics for a protocol"""
        throughputs = []
        times = []
        errors = 0
        total_bytes = 0
        retransmissions = 0

        for m in metrics:
            for transfer in m.get(protocol, {}).get('transfers', []):
                throughputs.append(transfer.get('throughput_mbps', 0))
                times.append(transfer.get('elapsed_seconds', 0))
                total_bytes += transfer.get('size_bytes', 0)
                retransmissions += transfer.get('retransmissions', 0)
            errors += m.get(protocol, {}).get('errors', 0)

        import numpy as np

        return {
            'transfers': len(throughputs),
            'avg_throughput': float(np.mean(throughputs)) if throughputs else 0,
            'std_throughput': float(np.std(throughputs)) if throughputs else 0,
            'min_throughput': float(np.min(throughputs)) if throughputs else 0,
            'max_throughput': float(np.max(throughputs)) if throughputs else 0,
            'avg_time': float(np.mean(times)) if times else 0,
            'total_bytes': total_bytes,
            'errors': errors,
            'retransmissions': retransmissions
        }

    def run_all(self):
        """Run all analyses"""
        print("Loading data...")
        metrics = self.load_metrics()
        tcpdump_data = self.load_csv_data()

        print("Generating plots...")
        self.plot_throughput_comparison(metrics)
        self.plot_retransmission_stats(metrics)
        self.analyze_packet_loss(tcpdump_data)

        print("Generating summary report...")
        self.generate_summary_report()

        print("\nAnalysis complete!")
        print(f"Results saved to: {self.results_dir}")


if __name__ == '__main__':
    analyzer = NetworkAnalyzer()
    analyzer.run_all()
