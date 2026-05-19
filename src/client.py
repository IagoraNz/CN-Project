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

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from rudp import RUDPSocket
from utils import send_all, recv_all

# Configure logging
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

    def send_file_tcp(self, filepath: str) -> dict:
        """Send file via TCP"""
        logger.info(f'Sending {filepath} via TCP to {self.server_host}:{self.tcp_port}')

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10.0)
            sock.connect((self.server_host, self.tcp_port))

            filename = os.path.basename(filepath)
            file_size = os.path.getsize(filepath)

            start_time = time.time()

            # Send filename length (4 bytes)
            filename_len_data = len(filename).to_bytes(4, 'big')
            send_all(sock, filename_len_data)

            # Send filename
            send_all(sock, filename.encode('utf-8'))

            # Send file size (8 bytes)
            file_size_data = file_size.to_bytes(8, 'big')
            send_all(sock, file_size_data)

            # Send file data in chunks
            bytes_sent = 0
            with open(filepath, 'rb') as f:
                while True:
                    chunk = f.read(4096)
                    if not chunk:
                        break
                    send_all(sock, chunk)
                    bytes_sent += len(chunk)

            # Receive ACK
            ack = recv_all(sock, 3, timeout=5.0)
            elapsed = time.time() - start_time
            throughput = (bytes_sent * 8) / elapsed / 1e6 if elapsed > 0 else 0

            # Calculate file checksum
            file_checksum = self._calculate_checksum(filepath)

            transfer_info = {
                'protocol': 'TCP',
                'filename': filename,
                'size_bytes': file_size,
                'sent_bytes': bytes_sent,
                'elapsed_seconds': elapsed,
                'throughput_mbps': throughput,
                'checksum': file_checksum,
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
        """Send file via R-UDP"""
        logger.info(f'Sending {filepath} via R-UDP to {self.server_host}:{self.udp_port}')

        try:
            rudp_socket = RUDPSocket()
            rudp_socket.connect(self.server_host, self.udp_port)

            filename = os.path.basename(filepath)
            file_size = os.path.getsize(filepath)

            start_time = time.time()

            # Read file
            with open(filepath, 'rb') as f:
                file_data = f.read()

            # Prepare: filename_len (2 bytes) + filename + file_data
            packet = len(filename).to_bytes(2, 'big') + filename.encode('utf-8') + file_data

            # Send via R-UDP
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
                'packets_sent': stats['packets_sent'],
                'retransmissions': stats['retransmissions'],
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
        """Save metrics to JSON"""
        metrics_file = Path('/app/data/logs') / f'client_metrics_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        with open(metrics_file, 'w') as f:
            json.dump(self.metrics, f, indent=2)
        logger.info(f'Metrics saved to {metrics_file}')

    def _calculate_checksum(self, filepath: str) -> str:
        """Calculate SHA256 checksum of file"""
        sha256_hash = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()

    def add_custom_header(self, data: bytes) -> bytes:
        """Add X-Custom-Auth header"""
        header = f'X-Custom-Auth: {self.student_id}-{self.student_name}\r\n'.encode()
        return header + data


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='File Transfer Client')
    parser.add_argument('file', help='File to send')
    parser.add_argument('--protocol', choices=['tcp', 'rudp'], default='tcp',
                       help='Protocol to use')
    parser.add_argument('--server', default='server', help='Server hostname')
    parser.add_argument('--tcp-port', type=int, default=9000, help='TCP port')
    parser.add_argument('--udp-port', type=int, default=9001, help='UDP port')

    args = parser.parse_args()

    client = FileTransferClient(args.server, args.tcp_port, args.udp_port)
    result = client.send_file(args.file, args.protocol)

    print(json.dumps(result, indent=2))
    client.save_metrics()
