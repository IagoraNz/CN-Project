"""Parse tcpdump CSV exports and cross-validate with application metrics."""
import json
import csv
from pathlib import Path
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)


class TCPDumpParser:
    """Parse tcpdump CSV exports (from pcap_export.py or legacy tshark format)."""

    def __init__(self, csv_file: Path):
        self.csv_file = csv_file
        self.packets = []
        self.parse()

    def parse(self):
        """Parse CSV file from tcpdump export."""
        try:
            with open(self.csv_file, 'r') as f:
                reader = csv.DictReader(f)
                self.packets = list(reader)
            logger.info(f"Parsed {len(self.packets)} packets from {self.csv_file.name}")
        except Exception as e:
            logger.error(f"Error parsing {self.csv_file}: {e}")
            self.packets = []

    def get_packet_count(self) -> int:
        return len(self.packets)

    def get_total_bytes(self) -> int:
        total = 0
        for packet in self.packets:
            for field in ('frame.len', 'frame_len'):
                try:
                    if field in packet and packet[field]:
                        total += int(float(packet[field]))
                        break
                except (ValueError, KeyError):
                    pass
        return total

    def _get_port(self, packet: dict, direction: str) -> str:
        """Get port from tcpdump or tshark column names."""
        for key in (f'tcp.{direction}port', f'udp.{direction}port', f'{direction}port'):
            if key in packet and packet[key]:
                return str(packet[key])
        return ''

    def get_tcp_stats(self) -> Dict:
        tcp_packets = [
            p for p in self.packets
            if p.get('tcp.seq')
            or ('protocol' in p and 'tcp' in str(p.get('protocol', '')).lower())
        ]
        retransmissions = 0
        seen_seqs: set[str] = set()
        for p in tcp_packets:
            seq = p.get('tcp.seq', '')
            length = int(p.get('frame.len', 0) or 0)
            if seq and length > 0:
                if seq in seen_seqs:
                    retransmissions += 1
                seen_seqs.add(seq)
            elif seq and seq in seen_seqs:
                retransmissions += 1
            elif seq:
                seen_seqs.add(seq)
        return {
            'total_packets': len(tcp_packets),
            'retransmissions': retransmissions,
            'bytes': sum(int(p.get('frame.len', 0) or 0) for p in tcp_packets),
        }

    def get_udp_stats(self) -> Dict:
        udp_packets = [
            p for p in self.packets
            if (
                'udp' in str(p.get('protocol', '')).lower()
                or '9001' in (self._get_port(p, 'src'), self._get_port(p, 'dst'))
            )
        ]
        return {
            'total_packets': len(udp_packets),
            'bytes': sum(int(p.get('frame.len', 0) or 0) for p in udp_packets),
        }

    def get_port_statistics(self, port: int) -> Dict:
        port_packets = []
        for p in self.packets:
            src = self._get_port(p, 'src')
            dst = self._get_port(p, 'dst')
            try:
                if (src and int(src) == port) or (dst and int(dst) == port):
                    port_packets.append(p)
            except (ValueError, TypeError):
                pass
        return {
            'port': port,
            'packet_count': len(port_packets),
            'bytes': sum(int(p.get('frame.len', 0) or 0) for p in port_packets),
            'packets': port_packets,
        }

    def export_json(self, output_file: Path):
        data = {
            'source_file': str(self.csv_file),
            'packet_count': len(self.packets),
            'total_bytes': self.get_total_bytes(),
            'tcp_stats': self.get_tcp_stats(),
            'udp_stats': self.get_udp_stats(),
            'packets': self.packets,
        }
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Exported JSON to {output_file}")


class CrossValidator:
    """Validate application metrics against tcpdump data."""

    def __init__(self, app_metrics: Dict, pcap_metrics: Dict):
        self.app_metrics = app_metrics
        self.pcap_metrics = pcap_metrics
        self.validation_results = {}

    def validate_bytes_transferred(self) -> Dict:
        app_bytes = self.app_metrics.get('bytes_sent') or self.app_metrics.get('sent_bytes', 0)
        pcap_bytes = self.pcap_metrics.get('bytes', 0)
        discrepancy = abs(app_bytes - pcap_bytes)
        discrepancy_pct = (discrepancy / app_bytes * 100) if app_bytes > 0 else 0
        result = {
            'app_bytes': app_bytes,
            'pcap_bytes': pcap_bytes,
            'discrepancy': discrepancy,
            'discrepancy_percent': discrepancy_pct,
            'valid': discrepancy_pct < 15,
        }
        self.validation_results['bytes'] = result
        return result

    def validate_packet_count(self) -> Dict:
        app_packets = self.app_metrics.get('packets_sent', 0)
        pcap_packets = self.pcap_metrics.get('total_packets', 0)
        if app_packets == 0:
            result = {'app_packets': 0, 'pcap_packets': pcap_packets, 'valid': pcap_packets > 0}
        else:
            discrepancy_pct = abs(app_packets - pcap_packets) / app_packets * 100
            result = {
                'app_packets': app_packets,
                'pcap_packets': pcap_packets,
                'discrepancy_percent': discrepancy_pct,
                'valid': discrepancy_pct < 20,
            }
        self.validation_results['packets'] = result
        return result

    def validate_retransmissions(self) -> Dict:
        app_retrans = self.app_metrics.get('retransmissions', 0)
        pcap_retrans = self.pcap_metrics.get('retransmissions', 0)
        result = {
            'app_retransmissions': app_retrans,
            'pcap_retransmissions': pcap_retrans,
            'discrepancy': abs(app_retrans - pcap_retrans),
            'valid': True,
        }
        self.validation_results['retransmissions'] = result
        return result

    def run_validation(self) -> Dict:
        self.validate_bytes_transferred()
        self.validate_packet_count()
        self.validate_retransmissions()
        return {
            'valid': all(v.get('valid', False) for v in self.validation_results.values()),
            'details': self.validation_results,
        }

    def generate_report(self) -> str:
        validation = self.run_validation()
        html = f"""<html><head><title>Cross-Validation Report</title></head>
        <body><h1>Cross-Validation Report</h1>
        <p>Status: {'PASS' if validation['valid'] else 'FAIL'}</p>
        <pre>{json.dumps(validation['details'], indent=2)}</pre>
        </body></html>"""
        return html
