"""R-UDP (Reliable UDP) Protocol Implementation with Go-Back-N Windowing"""
import socket
import struct
import time
import hashlib
from typing import Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class RUDPHeader:
    """R-UDP Header with sequence/ACK/flags"""
    FORMAT = '!HHIIB'  # sequence, ack, length, timestamp, flags
    SIZE = struct.calcsize(FORMAT) + 2  # + 2 bytes for checksum

    FLAG_ACK = 0x01
    FLAG_FIN = 0x02
    FLAG_SYN = 0x04

    def __init__(self, sequence: int, ack: int, length: int, timestamp: int,
                 flags: int, data: bytes = b''):
        self.sequence = sequence & 0xFFFF
        self.ack = ack & 0xFFFF
        self.length = length
        self.timestamp = timestamp & 0xFFFFFFFF
        self.flags = flags
        self.data = data[:length] if data else b''
        self.checksum = self._calculate_checksum()

    def _calculate_checksum(self) -> bytes:
        """Calculate MD5 checksum of header fields + data."""
        packet = struct.pack(
            '!HHIIB', self.sequence, self.ack, self.length,
            self.timestamp, self.flags
        ) + self.data
        return hashlib.md5(packet).digest()[:2]

    def validate_checksum(self) -> bool:
        """Verify stored checksum matches recalculated value."""
        return self.checksum == self._calculate_checksum()

    def serialize(self) -> bytes:
        """Pack header into bytes"""
        return struct.pack(
            self.FORMAT, self.sequence, self.ack, self.length,
            self.timestamp, self.flags
        ) + self.checksum + self.data

    @staticmethod
    def deserialize(data: bytes) -> Tuple['RUDPHeader', bytes]:
        """Unpack bytes into header"""
        if len(data) < RUDPHeader.SIZE:
            raise ValueError("Incomplete header")

        header_data = data[:RUDPHeader.SIZE]
        try:
            unpacked = struct.unpack('!HHIIB', header_data[:struct.calcsize('!HHIIB')])
            sequence, ack, length, timestamp, flags = unpacked
            checksum = header_data[struct.calcsize('!HHIIB'):RUDPHeader.SIZE]
        except struct.error as e:
            raise ValueError(f"Invalid header: {e}")

        payload = data[RUDPHeader.SIZE:RUDPHeader.SIZE + length]
        header = RUDPHeader(sequence, ack, length, timestamp, flags, payload)
        header.checksum = checksum

        return header, payload


class RUDPSocket:
    """Reliable UDP Socket with Go-Back-N Windowing"""

    def __init__(self, timeout: float = 2.0, max_retries: int = 50,
                 window_size: int = 16, chunk_size: int = 1024,
                 transfer_timeout: float = 600.0):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.timeout = timeout
        self.max_retries = max_retries
        self.window_size = window_size
        self.chunk_size = chunk_size
        self.transfer_timeout = transfer_timeout

        self.send_seq = 0
        self.send_base = 0
        self.unacked_packets = {}

        self.recv_seq = 0
        self.received_packets = {}

        self.remote_addr = None
        self.connected = False

        self.stats = {
            'packets_sent': 0,
            'packets_received': 0,
            'retransmissions': 0,
            'checksum_errors': 0,
            'bytes_sent': 0,
            'bytes_received': 0
        }

        self.socket.settimeout(self.timeout)

    def bind(self, host: str, port: int):
        """Bind socket to address"""
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((host, port))

    def connect(self, host: str, port: int):
        """Establish connection with handshake (SYN).

        Retries up to 10 times with exponential backoff so that scenarios
        with up to 20% packet loss (C) succeed with >99.9% probability.
        """
        self.remote_addr = (host, port)
        self.connected = False

        max_attempts = 10
        backoff = self.timeout
        for attempt in range(max_attempts):
            syn_header = RUDPHeader(
                self.send_seq, 0, 0,
                int(time.time() * 1000),
                RUDPHeader.FLAG_SYN
            )
            self.socket.settimeout(backoff)
            t_sent = time.monotonic()
            try:
                self.socket.sendto(syn_header.serialize(), self.remote_addr)
                self.stats['packets_sent'] += 1

                ack_data, addr = self.socket.recvfrom(RUDPHeader.SIZE + 1024)
                ack_header, _ = RUDPHeader.deserialize(ack_data)

                if not ack_header.validate_checksum():
                    self.stats['checksum_errors'] += 1
                    continue

                if ack_header.flags & RUDPHeader.FLAG_SYN and ack_header.flags & RUDPHeader.FLAG_ACK:
                    # RTT measured with monotonic clock (avoids 32-bit timestamp wrap-around)
                    rtt_s = time.monotonic() - t_sent
                    # Keep timeout in [0.5s, original timeout]: reduce for low-latency paths
                    self.timeout = max(0.5, min(rtt_s * 4, self.timeout))
                    self.socket.settimeout(self.timeout)
                    self.send_seq = (self.send_seq + 1) & 0xFFFF
                    self.send_base = self.send_seq
                    self.connected = True
                    logger.info(f"Connected to {host}:{port} (RTT≈{rtt_s*1000:.0f}ms, timeout={self.timeout:.2f}s)")
                    return

            except socket.timeout:
                backoff = min(backoff * 1.5, 10.0)
                if attempt < max_attempts - 1:
                    logger.debug(f"SYN attempt {attempt + 1}/{max_attempts} timed out, retrying")
                    continue
                raise TimeoutError("Connection SYN-ACK timeout")

    def send_data(self, data: bytes) -> int:
        """Send data with sliding window, retransmission and global deadline."""
        if not self.connected:
            raise RuntimeError("Not connected")

        offset = 0
        deadline = time.time() + self.transfer_timeout

        while offset < len(data) or self.unacked_packets:
            if time.time() > deadline:
                raise TimeoutError(
                    f"R-UDP transfer timed out after {self.transfer_timeout}s "
                    f"({offset}/{len(data)} bytes sent)"
                )

            self._process_acks()

            while (
                (self.send_seq - self.send_base) & 0xFFFF < self.window_size
                and offset < len(data)
            ):
                chunk = data[offset:offset + self.chunk_size]
                offset += len(chunk)

                header = RUDPHeader(
                    self.send_seq, self.recv_seq, len(chunk),
                    int(time.time() * 1000), 0, chunk
                )
                packet = header.serialize()

                self.socket.sendto(packet, self.remote_addr)
                self.unacked_packets[self.send_seq] = (packet, time.time(), 0)
                self.stats['packets_sent'] += 1
                self.stats['bytes_sent'] += len(chunk)
                self.send_seq = (self.send_seq + 1) & 0xFFFF

            try:
                ack_data, _ = self.socket.recvfrom(RUDPHeader.SIZE + 1024)
                ack_header, _ = RUDPHeader.deserialize(ack_data)

                if not ack_header.validate_checksum():
                    self.stats['checksum_errors'] += 1
                    continue

                if ack_header.flags & RUDPHeader.FLAG_ACK:
                    acked_seq = ack_header.ack
                    for seq in list(self.unacked_packets.keys()):
                        if (acked_seq - seq) & 0xFFFF <= 32768:
                            del self.unacked_packets[seq]
                    self.send_base = (acked_seq + 1) & 0xFFFF

            except socket.timeout:
                self._retransmit_window()

        self._send_fin()
        return offset

    def recv_data(self, expected_size: Optional[int] = None, timeout: float = 5.0) -> bytes:
        """Receive data with window management and checksum validation."""
        data = b''
        start_time = time.time()

        while True:
            try:
                remaining_timeout = timeout - (time.time() - start_time)
                if remaining_timeout <= 0:
                    break

                self.socket.settimeout(min(remaining_timeout, self.timeout))
                packet, addr = self.socket.recvfrom(RUDPHeader.SIZE + self.chunk_size + 1024)

                if not self.remote_addr:
                    self.remote_addr = addr

                header, payload = RUDPHeader.deserialize(packet)

                if not header.validate_checksum():
                    self.stats['checksum_errors'] += 1
                    logger.warning(f"Checksum error on seq={header.sequence}, discarding")
                    continue

                if header.flags & RUDPHeader.FLAG_SYN:
                    self._send_syn_ack(header.sequence)
                    self.recv_seq = (header.sequence + 1) & 0xFFFF
                    self.connected = True
                    continue

                if header.flags & RUDPHeader.FLAG_FIN:
                    self._send_ack(header.sequence)
                    break

                if header.sequence == self.recv_seq:
                    data += payload
                    self.stats['packets_received'] += 1
                    self.stats['bytes_received'] += len(payload)
                    self.recv_seq = (self.recv_seq + 1) & 0xFFFF
                    self._send_ack(header.sequence)

                    while self.recv_seq in self.received_packets:
                        buffered = self.received_packets.pop(self.recv_seq)
                        data += buffered
                        self.stats['bytes_received'] += len(buffered)
                        self._send_ack((self.recv_seq - 1) & 0xFFFF)
                        self.recv_seq = (self.recv_seq + 1) & 0xFFFF

                    if expected_size and len(data) >= expected_size:
                        break
                elif (header.sequence - self.recv_seq) & 0xFFFF < 32768:
                    self.received_packets[header.sequence] = payload
                    self._send_ack((self.recv_seq - 1) & 0xFFFF)
                else:
                    self._send_ack((self.recv_seq - 1) & 0xFFFF)

            except socket.timeout:
                if time.time() - start_time >= timeout:
                    break
                continue

        return data

    def _process_acks(self):
        """Try to receive ACK without blocking"""
        self.socket.settimeout(0.001)
        try:
            ack_data, _ = self.socket.recvfrom(RUDPHeader.SIZE + 1024)
            ack_header, _ = RUDPHeader.deserialize(ack_data)

            if not ack_header.validate_checksum():
                self.stats['checksum_errors'] += 1
                return

            if ack_header.flags & RUDPHeader.FLAG_ACK:
                acked_seq = ack_header.ack
                for seq in list(self.unacked_packets.keys()):
                    if (acked_seq - seq) & 0xFFFF <= 32768:
                        del self.unacked_packets[seq]
                self.send_base = (acked_seq + 1) & 0xFFFF

        except socket.timeout:
            pass
        finally:
            self.socket.settimeout(self.timeout)

    def _retransmit_window(self):
        """Retransmit unacked packets (Go-Back-N)."""
        now = time.time()
        for seq in sorted(self.unacked_packets.keys()):
            packet, last_time, retries = self.unacked_packets[seq]

            if retries >= self.max_retries:
                raise RuntimeError(
                    f"R-UDP: seq={seq} exceeded max retries ({self.max_retries}). "
                    "Network too lossy or server unreachable."
                )

            if now - last_time > self.timeout:
                self.socket.sendto(packet, self.remote_addr)
                self.unacked_packets[seq] = (packet, now, retries + 1)
                self.stats['retransmissions'] += 1
                logger.debug(f"Retransmit seq={seq}, retry={retries + 1}")

    def _send_ack(self, seq: int):
        """Send ACK packet"""
        ack_header = RUDPHeader(self.recv_seq, seq, 0,
                               int(time.time() * 1000),
                               RUDPHeader.FLAG_ACK)
        self.socket.sendto(ack_header.serialize(), self.remote_addr)

    def _send_syn_ack(self, seq: int):
        """Send SYN-ACK for connection setup"""
        syn_ack_header = RUDPHeader(self.recv_seq, seq, 0,
                                   int(time.time() * 1000),
                                   RUDPHeader.FLAG_SYN | RUDPHeader.FLAG_ACK)
        self.socket.sendto(syn_ack_header.serialize(), self.remote_addr)

    def _send_fin(self):
        """Send FIN to close connection"""
        fin_header = RUDPHeader(self.send_seq, self.recv_seq, 0,
                               int(time.time() * 1000),
                               RUDPHeader.FLAG_FIN)
        self.socket.sendto(fin_header.serialize(), self.remote_addr)
        self.send_seq = (self.send_seq + 1) & 0xFFFF

    def reset(self):
        """Reset connection state for a new transfer on the same socket."""
        self.send_seq = 0
        self.send_base = 0
        self.unacked_packets.clear()
        self.recv_seq = 0
        self.received_packets.clear()
        self.remote_addr = None
        self.connected = False
        self.stats = {
            'packets_sent': 0,
            'packets_received': 0,
            'retransmissions': 0,
            'checksum_errors': 0,
            'bytes_sent': 0,
            'bytes_received': 0,
        }

    def close(self):
        """Close socket"""
        if self.socket:
            self.socket.close()

    def get_stats(self) -> dict:
        """Return statistics"""
        return dict(self.stats)
