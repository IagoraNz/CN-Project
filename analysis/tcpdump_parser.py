"""Parse tcpdump PCAP files and extract metrics"""
import json
import csv
from pathlib import Path
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)


class TCPDumpParser:
    """Parse tcpdump CSV exports"""

    def __init__(self, csv_file: Path):
        self.csv_file = csv_file
        self.packets = []
        self.parse()

    def parse(self):
        """Parse CSV file from tcpdump"""
        try:
            with open(self.csv_file, 'r') as f:
                reader = csv.DictReader(f)
                self.packets = list(reader)
            logger.info(f"Parsed {len(self.packets)} packets from {self.csv_file.name}")
        except Exception as e:
            logger.error(f"Error parsing {self.csv_file}: {e}")
            self.packets = []

    def get_packet_count(self) -> int:
        """Get total packet count"""
        return len(self.packets)

    def get_total_bytes(self) -> int:
        """Get total bytes transmitted"""
        total = 0
        for packet in self.packets:
            try:
                if 'frame.len' in packet and packet['frame.len']:
                    total += int(packet['frame.len'])
            except (ValueError, KeyError):
                pass
        return total

    def get_tcp_stats(self) -> Dict:
        """Get TCP-specific statistics"""
        tcp_packets = [p for p in self.packets if 'tcp.seq' in p and p['tcp.seq']]
        retransmissions = 0

        # Count retransmissions (packets with duplicate sequence numbers)
        seen_seqs = {}
        for p in tcp_packets:
            try:
                seq = p.get('tcp.seq', '')
                if seq and seq in seen_seqs:
                    retransmissions += 1
                seen_seqs[seq] = True
            except:
                pass

        return {
            'total_packets': len(tcp_packets),
            'retransmissions': retransmissions,
            'bytes': sum(int(p.get('frame.len', 0)) for p in tcp_packets if p.get('frame.len'))
        }

    def get_udp_stats(self) -> Dict:
        """Get UDP-specific statistics"""
        udp_packets = [p for p in self.packets if 'udp.srcport' in p and p['udp.srcport']]
        return {
            'total_packets': len(udp_packets),
            'bytes': sum(int(p.get('frame.len', 0)) for p in udp_packets if p.get('frame.len'))
        }

    def get_port_statistics(self, port: int) -> Dict:
        """Get statistics for specific port"""
        port_packets = []
        for p in self.packets:
            try:
                src_port = p.get('tcp.srcport') or p.get('udp.srcport')
                dst_port = p.get('tcp.dstport') or p.get('udp.dstport')
                if src_port and int(src_port) == port or dst_port and int(dst_port) == port:
                    port_packets.append(p)
            except (ValueError, TypeError):
                pass

        return {
            'port': port,
            'packet_count': len(port_packets),
            'bytes': sum(int(p.get('frame.len', 0)) for p in port_packets if p.get('frame.len')),
            'packets': port_packets
        }

    def export_json(self, output_file: Path):
        """Export parsed data to JSON"""
        data = {
            'source_file': str(self.csv_file),
            'packet_count': len(self.packets),
            'total_bytes': self.get_total_bytes(),
            'tcp_stats': self.get_tcp_stats(),
            'udp_stats': self.get_udp_stats(),
            'packets': self.packets
        }

        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)

        logger.info(f"Exported JSON to {output_file}")


class CrossValidator:
    """Validate application metrics against tcpdump data"""

    def __init__(self, app_metrics: Dict, pcap_metrics: Dict):
        self.app_metrics = app_metrics
        self.pcap_metrics = pcap_metrics
        self.validation_results = {}

    def validate_bytes_transferred(self) -> Dict:
        """Compare bytes sent/received"""
        app_bytes = self.app_metrics.get('bytes_sent') or self.app_metrics.get('sent_bytes', 0)
        pcap_bytes = self.pcap_metrics.get('bytes', 0)

        discrepancy = abs(app_bytes - pcap_bytes)
        discrepancy_pct = (discrepancy / app_bytes * 100) if app_bytes > 0 else 0

        result = {
            'app_bytes': app_bytes,
            'pcap_bytes': pcap_bytes,
            'discrepancy': discrepancy,
            'discrepancy_percent': discrepancy_pct,
            'valid': discrepancy_pct < 5  # Allow 5% discrepancy
        }

        self.validation_results['bytes'] = result
        return result

    def validate_packet_count(self) -> Dict:
        """Compare packet counts"""
        app_packets = self.app_metrics.get('packets_sent', 0)
        pcap_packets = self.pcap_metrics.get('total_packets', 0)

        discrepancy = abs(app_packets - pcap_packets)
        discrepancy_pct = (discrepancy / app_packets * 100) if app_packets > 0 else 0

        result = {
            'app_packets': app_packets,
            'pcap_packets': pcap_packets,
            'discrepancy': discrepancy,
            'discrepancy_percent': discrepancy_pct,
            'valid': discrepancy_pct < 10  # Allow 10% discrepancy
        }

        self.validation_results['packets'] = result
        return result

    def validate_retransmissions(self) -> Dict:
        """Compare retransmission counts"""
        app_retrans = self.app_metrics.get('retransmissions', 0)
        pcap_retrans = self.pcap_metrics.get('retransmissions', 0)

        result = {
            'app_retransmissions': app_retrans,
            'pcap_retransmissions': pcap_retrans,
            'discrepancy': abs(app_retrans - pcap_retrans),
            'valid': abs(app_retrans - pcap_retrans) < 5
        }

        self.validation_results['retransmissions'] = result
        return result

    def run_validation(self) -> Dict:
        """Run all validation checks"""
        self.validate_bytes_transferred()
        self.validate_packet_count()
        self.validate_retransmissions()

        return {
            'valid': all(v.get('valid', False) for v in self.validation_results.values()),
            'details': self.validation_results
        }

    def generate_report(self) -> str:
        """Generate HTML validation report"""
        validation = self.run_validation()

        html = f"""
        <html>
        <head>
            <title>Cross-Validation Report</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .valid {{ color: green; }}
                .invalid {{ color: red; }}
                table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #4CAF50; color: white; }}
            </style>
        </head>
        <body>
            <h1>Cross-Validation Report</h1>
            <p>Status: <span class="{'valid' if validation['valid'] else 'invalid'}">
                {'PASS' if validation['valid'] else 'FAIL'}</span></p>
            <h2>Bytes Transferred</h2>
            <table>
                <tr>
                    <th>Metric</th>
                    <th>Value</th>
                </tr>
                <tr>
                    <td>App Bytes</td>
                    <td>{validation['details']['bytes']['app_bytes']}</td>
                </tr>
                <tr>
                    <td>PCAP Bytes</td>
                    <td>{validation['details']['bytes']['pcap_bytes']}</td>
                </tr>
                <tr>
                    <td>Discrepancy</td>
                    <td>{validation['details']['bytes']['discrepancy_percent']:.2f}%</td>
                </tr>
            </table>
            <h2>Packet Count</h2>
            <table>
                <tr>
                    <th>Metric</th>
                    <th>Value</th>
                </tr>
                <tr>
                    <td>App Packets</td>
                    <td>{validation['details']['packets']['app_packets']}</td>
                </tr>
                <tr>
                    <td>PCAP Packets</td>
                    <td>{validation['details']['packets']['pcap_packets']}</td>
                </tr>
                <tr>
                    <td>Discrepancy</td>
                    <td>{validation['details']['packets']['discrepancy_percent']:.2f}%</td>
                </tr>
            </table>
            <h2>Retransmissions</h2>
            <table>
                <tr>
                    <th>Metric</th>
                    <th>Value</th>
                </tr>
                <tr>
                    <td>App Retransmissions</td>
                    <td>{validation['details']['retransmissions']['app_retransmissions']}</td>
                </tr>
                <tr>
                    <td>PCAP Retransmissions</td>
                    <td>{validation['details']['retransmissions']['pcap_retransmissions']}</td>
                </tr>
            </table>
        </body>
        </html>
        """

        return html
