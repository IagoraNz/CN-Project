"""Utility functions for network transfers"""
import socket
import time
import re


AUTH_PATTERN = re.compile(rb'^X-Custom-Auth:\s*(.+?)\r\n')


def get_tcp_retrans_segs() -> int:
    """Read cumulative TCP RetransSegs from /proc/net/snmp (Linux)."""
    try:
        with open('/proc/net/snmp') as f:
            lines = [ln for ln in f if ln.startswith('Tcp:')]
        if len(lines) >= 2:
            return int(lines[1].split()[12])
    except (OSError, IndexError, ValueError):
        pass
    return 0


def build_auth_header(student_id: str, student_name: str) -> bytes:
    """Build X-Custom-Auth header bytes (Matrícula + Nome)."""
    return f'X-Custom-Auth: {student_id}-{student_name}\r\n'.encode('utf-8')


def wrap_with_auth(student_id: str, student_name: str, payload: bytes) -> bytes:
    """Prepend length-prefixed X-Custom-Auth header to payload."""
    auth = build_auth_header(student_id, student_name)
    return len(auth).to_bytes(2, 'big') + auth + payload


def parse_auth_prefix(data: bytes) -> tuple[str, bytes]:
    """Extract X-Custom-Auth value from length-prefixed header. Returns (auth_value, rest)."""
    if len(data) < 2:
        raise ValueError('Missing auth length prefix')

    auth_len = int.from_bytes(data[:2], 'big')
    if len(data) < 2 + auth_len:
        raise ValueError('Incomplete auth header')

    auth_bytes = data[2:2 + auth_len]
    match = AUTH_PATTERN.match(auth_bytes)
    if not match:
        raise ValueError(f'Invalid X-Custom-Auth header: {auth_bytes!r}')

    return match.group(1).decode('utf-8'), data[2 + auth_len:]


def recv_all(sock: socket.socket, size: int, timeout: float = 5.0) -> bytes:
    """Receive exactly `size` bytes from socket, handling stream fragmentation."""
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
