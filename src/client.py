#!/usr/bin/env python3
import socket
import os
import sys
import time
import logging
import json
from datetime import datetime
from pathlib import Path
import hashlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from rudp import RUDPSocket
from utils import send_all, recv_all, wrap_with_auth, get_tcp_retrans_segs, build_auth_header

log_dir = Path('/app/data/logs')
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / f'client_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class FileTransferClient:
    def __init__(self, server_host='server', tcp_port=9000, udp_port=9001):
        self.server_host = server_host
        self.tcp_port = tcp_port
        self.udp_port = udp_port
        self.student_id = os.getenv('STUDENT_ID', '000000')
        self.student_name = os.getenv('STUDENT_NAME', 'Unknown')
        self.metrics = []

    @property
    def auth_value(self) -> str:
        return f'{self.student_id}-{self.student_name}'

    def _build_file_payload(self, filepath: str) -> tuple[str, bytes, int]:
        """Build protocol payload: filename_len + filename + file_size + file_data."""
        filename = os.path.basename(filepath)
        file_size = os.path.getsize(filepath)
        with open(filepath, 'rb') as f:
            file_data = f.read()
        payload = (
            len(filename).to_bytes(2, 'big')
            + filename.encode('utf-8')
            + file_size.to_bytes(8, 'big')
            + file_data
        )
        return filename, payload, file_size

    def send_file_tcp(self, filepath: str) -> dict:
        """Send file via TCP with X-Custom-Auth header."""
        logger.info(f'Sending {filepath} via TCP to {self.server_host}:{self.tcp_port}')

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10.0)
            sock.connect((self.server_host, self.tcp_port))

            filename, file_payload, file_size = self._build_file_payload(filepath)
            auth_payload = wrap_with_auth(self.student_id, self.student_name, file_payload)

            start_time = time.time()
            retrans_before = get_tcp_retrans_segs()

            # Send auth + file payload
            send_all(sock, auth_payload)

            # Receive ACK
            ack = recv_all(sock, 3, timeout=5.0)
            elapsed = time.time() - start_time
            retrans_after = get_tcp_retrans_segs()
            tcp_retransmissions = max(0, retrans_after - retrans_before)
            bytes_sent = len(auth_payload)
            throughput = (bytes_sent * 8) / elapsed / 1e6 if elapsed > 0 else 0
            file_checksum = self._calculate_checksum(filepath)

            transfer_info = {
                'protocol': 'TCP',
                'filename': filename,
                'size_bytes': file_size,
                'sent_bytes': bytes_sent,
                'elapsed_seconds': elapsed,
                'throughput_mbps': throughput,
                'checksum': file_checksum,
                'x_custom_auth': self.auth_value,
                'retransmissions': tcp_retransmissions,
                'timestamp': datetime.now().isoformat()
            }

            logger.info(f'TCP Transfer complete: {filename} ({bytes_sent} bytes, '
                       f'{throughput:.2f} Mbps, {elapsed:.2f}s)')

            sock.close()
            return transfer_info

        except Exception as e:
            logger.error(f'TCP Error: {e}', exc_info=True)
            return {'protocol': 'TCP', 'error': str(e)}

    def send_file_rudp(self, filepath: str) -> dict:
        """Send file via R-UDP with X-Custom-Auth header."""
        logger.info(f'Sending {filepath} via R-UDP to {self.server_host}:{self.udp_port}')

        try:
            rudp_socket = RUDPSocket()
            rudp_socket.connect(self.server_host, self.udp_port)

            filename, file_payload, file_size = self._build_file_payload(filepath)
            packet = wrap_with_auth(self.student_id, self.student_name, file_payload)

            start_time = time.time()
            bytes_sent = rudp_socket.send_data(packet)
            elapsed = time.time() - start_time
            throughput = (bytes_sent * 8) / elapsed / 1e6 if elapsed > 0 else 0

            stats = rudp_socket.get_stats()
            file_checksum = self._calculate_checksum(filepath)

            transfer_info = {
                'protocol': 'R-UDP',
                'filename': filename,
                'size_bytes': file_size,
                'sent_bytes': bytes_sent,
                'elapsed_seconds': elapsed,
                'throughput_mbps': throughput,
                'checksum': file_checksum,
                'x_custom_auth': self.auth_value,
                'packets_sent': stats['packets_sent'],
                'retransmissions': stats['retransmissions'],
                'checksum_errors': stats['checksum_errors'],
                'timestamp': datetime.now().isoformat()
            }

            logger.info(f'R-UDP Transfer complete: {filename} ({bytes_sent} bytes, '
                       f'{throughput:.2f} Mbps, retransmissions: {stats["retransmissions"]})')

            rudp_socket.close()
            return transfer_info

        except Exception as e:
            logger.error(f'R-UDP Error: {e}', exc_info=True)
            return {'protocol': 'R-UDP', 'error': str(e)}

    def send_file(self, filepath: str, protocol: str = 'tcp') -> dict:
        """Send file using specified protocol"""
        if not os.path.exists(filepath):
            logger.error(f'File not found: {filepath}')
            return {'error': 'File not found'}

        if protocol.lower() == 'tcp':
            result = self.send_file_tcp(filepath)
        elif protocol.lower() == 'rudp':
            result = self.send_file_rudp(filepath)
        else:
            return {'error': f'Unknown protocol: {protocol}'}

        self.metrics.append(result)
        return result

    def save_metrics(self):
        """Save metrics to JSON (per-run and consolidated)."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        metrics_file = log_dir / f'client_metrics_{timestamp}.json'
        with open(metrics_file, 'w') as f:
            json.dump(self.metrics, f, indent=2)

        consolidated = log_dir / 'client_metrics_all.json'
        existing = []
        if consolidated.exists():
            try:
                with open(consolidated) as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, OSError):
                existing = []
        existing.extend(self.metrics)
        with open(consolidated, 'w') as f:
            json.dump(existing, f, indent=2)

        logger.info(f'Metrics saved to {metrics_file} and {consolidated}')

    def _calculate_checksum(self, filepath: str) -> str:
        """Calculate SHA256 checksum of file"""
        sha256_hash = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='File Transfer Client')
    parser.add_argument('file', help='File to send')
    parser.add_argument('--protocol', choices=['tcp', 'rudp'], default='tcp',
                       help='Protocol to use')
    parser.add_argument('--server', default='server', help='Server hostname')
    parser.add_argument('--tcp-port', type=int, default=9000, help='TCP port')
    parser.add_argument('--udp-port', type=int, default=9001, help='UDP port')
    parser.add_argument('--scenario', default=None,
                       help='Network scenario label (A, B, C) for analysis')
    parser.add_argument('--run', type=int, default=1,
                       help='Run number for statistical analysis')

    args = parser.parse_args()

    client = FileTransferClient(args.server, args.tcp_port, args.udp_port)
    result = client.send_file(args.file, args.protocol)

    if args.scenario and 'error' not in result:
        result['scenario'] = args.scenario.upper()
        result['run'] = args.run

    print(json.dumps(result, indent=2))
    client.save_metrics()
