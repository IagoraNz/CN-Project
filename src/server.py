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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from rudp import RUDPSocket
from utils import recv_all, send_all, parse_auth_prefix

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

    def _parse_file_payload(self, data: bytes) -> tuple[str, bytes]:
        """Parse filename_len + filename + file_size + file_data from payload."""
        if len(data) < 2:
            raise ValueError('Incomplete file payload')
        filename_len = int.from_bytes(data[:2], 'big')
        offset = 2 + filename_len
        if len(data) < offset + 8:
            raise ValueError('Incomplete file payload (missing size)')
        filename = data[2:offset].decode('utf-8')
        file_size = int.from_bytes(data[offset:offset + 8], 'big')
        file_data = data[offset + 8:offset + 8 + file_size]
        if len(file_data) != file_size:
            raise ValueError(f'Expected {file_size} bytes, got {len(file_data)}')
        return filename, file_data

    def handle_tcp_client(self, conn, addr):
        """Handle TCP file transfer with X-Custom-Auth validation."""
        logger.info(f'TCP Client connected: {addr}')
        start_time = time.time()

        try:
            auth_len = int.from_bytes(recv_all(conn, 2, timeout=10.0), 'big')
            auth_value, _ = parse_auth_prefix(
                auth_len.to_bytes(2, 'big') + recv_all(conn, auth_len, timeout=10.0)
            )
            logger.info(f'X-Custom-Auth received: {auth_value}')

            filename_len = int.from_bytes(recv_all(conn, 2, timeout=10.0), 'big')
            filename = recv_all(conn, filename_len, timeout=10.0).decode('utf-8')
            file_size = int.from_bytes(recv_all(conn, 8, timeout=10.0), 'big')

            file_data = b''
            remaining = file_size
            while remaining > 0:
                chunk_size = min(4096, remaining)
                chunk = recv_all(conn, chunk_size, timeout=30.0)
                file_data += chunk
                remaining -= len(chunk)

            total_bytes = len(file_data)
            elapsed = time.time() - start_time
            throughput = (total_bytes * 8) / elapsed / 1e6 if elapsed > 0 else 0

            output_path = Path('/app/data') / 'received' / filename
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'wb') as f:
                f.write(file_data)

            file_checksum = self._calculate_checksum(output_path)

            transfer_info = {
                'filename': filename,
                'received_bytes': total_bytes,
                'elapsed_seconds': elapsed,
                'throughput_mbps': throughput,
                'checksum': file_checksum,
                'x_custom_auth': auth_value,
                'timestamp': datetime.now().isoformat()
            }

            with self.metrics_lock:
                self.metrics['tcp']['transfers'].append(transfer_info)
                self.metrics['tcp']['total_bytes'] += total_bytes

            logger.info(f'TCP Transfer complete: {filename} ({total_bytes} bytes, '
                       f'{throughput:.2f} Mbps, auth={auth_value})')

            send_all(conn, b'ACK', timeout=5.0)

        except Exception as e:
            logger.error(f'TCP Error: {e}', exc_info=True)
            with self.metrics_lock:
                self.metrics['tcp']['errors'] += 1
        finally:
            conn.close()

    def handle_rudp_client(self, data, remote_addr, stats=None):
        """Handle R-UDP file transfer with X-Custom-Auth validation."""
        logger.info(f'R-UDP Client connected: {remote_addr}')

        try:
            if stats:
                with self.metrics_lock:
                    self.metrics['rudp']['retransmissions'] += stats.get('retransmissions', 0)

            if not data or len(data) < 2:
                logger.warning('Invalid R-UDP data')
                return

            auth_value, rest = parse_auth_prefix(data)
            logger.info(f'X-Custom-Auth received: {auth_value}')

            filename, file_data = self._parse_file_payload(rest)
            start_time = time.time()

            output_path = Path('/app/data') / 'received' / filename
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'wb') as f:
                f.write(file_data)

            elapsed = time.time() - start_time
            throughput = (len(file_data) * 8) / elapsed / 1e6 if elapsed > 0 else 0
            file_checksum = self._calculate_checksum(output_path)

            transfer_info = {
                'filename': filename,
                'received_bytes': len(file_data),
                'elapsed_seconds': elapsed,
                'throughput_mbps': throughput,
                'checksum': file_checksum,
                'x_custom_auth': auth_value,
                'timestamp': datetime.now().isoformat()
            }

            with self.metrics_lock:
                self.metrics['rudp']['transfers'].append(transfer_info)
                self.metrics['rudp']['total_bytes'] += len(file_data)

            logger.info(f'R-UDP Transfer complete: {filename} ({len(file_data)} bytes, '
                       f'{throughput:.2f} Mbps, auth={auth_value})')

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
        """Run R-UDP server with a single persistent socket."""
        def rudp_thread():
            rudp_socket = RUDPSocket()
            rudp_socket.bind(self.host, self.udp_port)
            logger.info(f'R-UDP Server listening on {self.host}:{self.udp_port}')

            try:
                while True:
                    rudp_socket.reset()
                    try:
                        data = rudp_socket.recv_data(timeout=600.0)
                    except Exception as e:
                        logger.error(f'R-UDP receive error: {e}', exc_info=True)
                        continue

                    remote_addr = rudp_socket.remote_addr
                    stats = rudp_socket.get_stats()

                    if not data or not remote_addr:
                        continue

                    client_thread = threading.Thread(
                        target=self.handle_rudp_client,
                        args=(data, remote_addr, stats)
                    )
                    client_thread.daemon = True
                    client_thread.start()
            except KeyboardInterrupt:
                logger.info('R-UDP Server shutting down')
            finally:
                rudp_socket.close()
                self.save_metrics()

        t = threading.Thread(target=rudp_thread, daemon=True)
        t.start()
        return t

    def save_metrics(self):
        """Save metrics to JSON"""
        metrics_file = log_dir / f'metrics_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
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
