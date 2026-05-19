#!/usr/bin/env python3
import socket
import os
import sys
import time
import logging
import json
import threading
import hashlib
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from rudp import RUDPSocket
from utils import recv_all, send_all

# Configure logging
log_dir = Path('/app/data/logs')
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / f'server_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class FileTransferServer:
    def __init__(self, host='0.0.0.0', tcp_port=9000, udp_port=9001):
        self.host = host
        self.tcp_port = tcp_port
        self.udp_port = udp_port
        self.student_id = os.getenv('STUDENT_ID', '000000')
        self.student_name = os.getenv('STUDENT_NAME', 'Unknown')
        self.metrics = {
            'tcp': {'transfers': [], 'total_bytes': 0, 'errors': 0},
            'rudp': {'transfers': [], 'total_bytes': 0, 'errors': 0, 'retransmissions': 0}
        }
        self.metrics_lock = threading.Lock()

    def handle_tcp_client(self, conn, addr):
        """Handle TCP file transfer"""
        logger.info(f'TCP Client connected: {addr}')
        start_time = time.time()
        total_bytes = 0

        try:
            # Receive filename length
            filename_len_data = recv_all(conn, 4, timeout=10.0)
            filename_len = int.from_bytes(filename_len_data, 'big')

            # Receive filename
            filename = recv_all(conn, filename_len, timeout=10.0).decode('utf-8')
            logger.info(f'Receiving file via TCP: {filename}')

            # Receive file size
            file_size_data = recv_all(conn, 8, timeout=10.0)
            file_size = int.from_bytes(file_size_data, 'big')

            # Receive file data
            output_path = Path('/app/data') / 'received' / filename
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with open(output_path, 'wb') as f:
                remaining = file_size
                while remaining > 0:
                    chunk_size = min(4096, remaining)
                    chunk = recv_all(conn, chunk_size, timeout=10.0)
                    if not chunk:
                        break
                    f.write(chunk)
                    total_bytes += len(chunk)
                    remaining -= len(chunk)

            elapsed = time.time() - start_time
            throughput = (total_bytes * 8) / elapsed / 1e6 if elapsed > 0 else 0

            # Calculate checksum
            file_checksum = self._calculate_checksum(output_path)

            transfer_info = {
                'filename': filename,
                'expected_size': file_size,
                'received_bytes': total_bytes,
                'elapsed_seconds': elapsed,
                'throughput_mbps': throughput,
                'checksum': file_checksum,
                'timestamp': datetime.now().isoformat()
            }

            with self.metrics_lock:
                self.metrics['tcp']['transfers'].append(transfer_info)
                self.metrics['tcp']['total_bytes'] += total_bytes

            logger.info(f'TCP Transfer complete: {filename} ({total_bytes} bytes, '
                       f'{throughput:.2f} Mbps, {elapsed:.2f}s)')

            # Send acknowledgment
            send_all(conn, b'ACK', timeout=5.0)

        except Exception as e:
            logger.error(f'TCP Error: {e}', exc_info=True)
            with self.metrics_lock:
                self.metrics['tcp']['errors'] += 1
        finally:
            conn.close()

    def handle_rudp_client(self, data, remote_addr):
        """Handle R-UDP file transfer"""
        logger.info(f'R-UDP Client connected: {remote_addr}')

        try:
            if not data or len(data) < 2:
                logger.warning('Invalid R-UDP data')
                return

            # Parse: filename_len (2 bytes) + filename + file_data
            filename_len = int.from_bytes(data[:2], 'big')
            if len(data) < 2 + filename_len:
                logger.warning('Incomplete R-UDP packet')
                return

            filename = data[2:2 + filename_len].decode('utf-8')
            file_data = data[2 + filename_len:]

            start_time = time.time()
            elapsed = time.time() - start_time

            # Save file
            output_path = Path('/app/data') / 'received' / filename
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with open(output_path, 'wb') as f:
                f.write(file_data)

            throughput = (len(file_data) * 8) / elapsed / 1e6 if elapsed > 0 else 0
            file_checksum = self._calculate_checksum(output_path)

            transfer_info = {
                'filename': filename,
                'received_bytes': len(file_data),
                'elapsed_seconds': elapsed,
                'throughput_mbps': throughput,
                'checksum': file_checksum,
                'timestamp': datetime.now().isoformat()
            }

            with self.metrics_lock:
                self.metrics['rudp']['transfers'].append(transfer_info)
                self.metrics['rudp']['total_bytes'] += len(file_data)

            logger.info(f'R-UDP Transfer complete: {filename} ({len(file_data)} bytes, '
                       f'{throughput:.2f} Mbps)')

        except Exception as e:
            logger.error(f'R-UDP Error: {e}', exc_info=True)
            with self.metrics_lock:
                self.metrics['rudp']['errors'] += 1

    def run_tcp_server(self):
        """Run TCP server in background thread"""
        def tcp_thread():
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.host, self.tcp_port))
            server.listen(5)

            logger.info(f'TCP Server listening on {self.host}:{self.tcp_port}')

            try:
                while True:
                    conn, addr = server.accept()
                    # Handle client in separate thread
                    client_thread = threading.Thread(
                        target=self.handle_tcp_client,
                        args=(conn, addr)
                    )
                    client_thread.daemon = True
                    client_thread.start()
            except KeyboardInterrupt:
                logger.info('TCP Server shutting down')
            finally:
                server.close()
                self.save_metrics()

        t = threading.Thread(target=tcp_thread, daemon=True)
        t.start()
        return t

    def run_rudp_server(self):
        """Run R-UDP server in background thread"""
        def rudp_thread():
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind((self.host, self.udp_port))

            logger.info(f'R-UDP Server listening on {self.host}:{self.udp_port}')

            try:
                while True:
                    data, remote_addr = server_socket.recvfrom(65507)
                    # Handle client in separate thread
                    client_thread = threading.Thread(
                        target=self.handle_rudp_client,
                        args=(data, remote_addr)
                    )
                    client_thread.daemon = True
                    client_thread.start()
            except KeyboardInterrupt:
                logger.info('R-UDP Server shutting down')
            finally:
                server_socket.close()
                self.save_metrics()

        t = threading.Thread(target=rudp_thread, daemon=True)
        t.start()
        return t

    def save_metrics(self):
        """Save metrics to JSON"""
        metrics_file = Path('/app/data/logs') / f'metrics_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        with open(metrics_file, 'w') as f:
            json.dump(self.metrics, f, indent=2)
        logger.info(f'Metrics saved to {metrics_file}')

    def _calculate_checksum(self, filepath: Path) -> str:
        """Calculate SHA256 checksum of file"""
        sha256_hash = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()

    def run_both(self):
        """Run both TCP and R-UDP servers"""
        tcp_thread = self.run_tcp_server()
        rudp_thread = self.run_rudp_server()

        try:
            tcp_thread.join()
            rudp_thread.join()
        except KeyboardInterrupt:
            logger.info('Shutdown requested')
            self.save_metrics()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='File Transfer Server')
    parser.add_argument('--protocol', choices=['tcp', 'rudp', 'both'], default='both',
                       help='Protocol to use')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--tcp-port', type=int, default=9000, help='TCP port')
    parser.add_argument('--udp-port', type=int, default=9001, help='UDP port')

    args = parser.parse_args()

    server = FileTransferServer(args.host, args.tcp_port, args.udp_port)

    if args.protocol == 'tcp':
        logger.info('Starting TCP server')
        server.run_tcp_server().join()
    elif args.protocol == 'rudp':
        logger.info('Starting R-UDP server')
        server.run_rudp_server().join()
    else:
        logger.info('Starting both servers')
        server.run_both()
