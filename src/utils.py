"""Utility functions for network transfers"""
import socket
import time


def recv_all(sock: socket.socket, size: int, timeout: float = 5.0) -> bytes:
    """Receive exactly `size` bytes from socket, handling stream fragmentation.

    TCP is stream-based, not message-based. This ensures all bytes are received.
    """
    sock.settimeout(timeout)
    data = b''
    start_time = time.time()

    while len(data) < size:
        try:
            chunk = sock.recv(min(4096, size - len(data)))
            if not chunk:
                if len(data) < size:
                    raise ConnectionError(f"Socket closed. Received {len(data)}/{size} bytes")
                break
            data += chunk
        except socket.timeout:
            elapsed = time.time() - start_time
            raise TimeoutError(f"recv_all timeout after {elapsed:.2f}s. Received {len(data)}/{size} bytes")

    return data


def send_all(sock: socket.socket, data: bytes, timeout: float = 5.0) -> int:
    """Send all bytes to socket, handling incomplete sends."""
    sock.settimeout(timeout)
    total_sent = 0

    while total_sent < len(data):
        try:
            sent = sock.send(data[total_sent:])
            if sent == 0:
                raise ConnectionError("Socket connection broken")
            total_sent += sent
        except socket.timeout:
            raise TimeoutError(f"send_all timeout. Sent {total_sent}/{len(data)} bytes")

    return total_sent
