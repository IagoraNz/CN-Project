"""R-UDP (Reliable UDP) Protocol Implementation with Go-Back-N Windowing"""
import socket
import struct
import time
import hashlib
from typing import Tuple, Optional, List
from collections import defaultdict
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
        self.timestamp = timestamp & 0xFFFFFFFF  # Keep only lower 32 bits
        self.flags = flags
        self.data = data[:length] if data else b''
        self.checksum = self._calculate_checksum()

    def _calculate_checksum(self) -> bytes:
        """Calculate MD5 checksum of header + data"""
        timestamp = int(time.time() * 1000) & 0xFFFFFFFF  # Keep only lower 32 bits
        packet = struct.pack('!HHIIB', self.sequence, self.ack, self.length,
                            timestamp, self.flags) + self.data
        hash_obj = hashlib.md5(packet)
        return hash_obj.digest()[:2]

    def serialize(self) -> bytes:
        """Pack header into bytes"""
        return struct.pack(self.FORMAT, self.sequence, self.ack, self.length,
                          self.timestamp, self.flags) + self.checksum + self.data

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

    def __init__(self, timeout: float = 1.5, max_retries: int = 10,
                 window_size: int = 8, chunk_size: int = 1024,
                 transfer_timeout: float = 120.0):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.timeout = timeout
        self.max_retries = max_retries
        self.window_size = window_size
        self.chunk_size = chunk_size
        self.transfer_timeout = transfer_timeout

        # Sender state
        self.send_seq = 0  # Next sequence to send
        self.send_base = 0  # Base of window
        self.unacked_packets = {}  # seq -> (packet, timestamp, retries)

        # Receiver state
        self.recv_seq = 0  # Next expected sequence
        self.received_packets = {}  # seq -> data (for out-of-order handling)

        # Connection state
        self.remote_addr = None
        self.connected = False

        # Metrics
        self.stats = {
            'packets_sent': 0,
            'packets_received': 0,
            'retransmissions': 0,
            'bytes_sent': 0,
            'bytes_received': 0
        }

        self.socket.settimeout(self.timeout)

    def bind(self, host: str, port: int):
        """Bind socket to address"""
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((host, port))

    def connect(self, host: str, port: int):
        """Establish connection with handshake (SYN)"""
        self.remote_addr = (host, port)
        self.connected = False

        # Send SYN
        syn_header = RUDPHeader(
            self.send_seq, 0, 0,
            int(time.time() * 1000),
            RUDPHeader.FLAG_SYN
        )
        syn_packet = syn_header.serialize()

        for attempt in range(3):
            try:
                self.socket.sendto(syn_packet, self.remote_addr)
                self.stats['packets_sent'] += 1

                # Wait for SYN-ACK
                ack_data, addr = self.socket.recvfrom(RUDPHeader.SIZE + 1024)
                ack_header, _ = RUDPHeader.deserialize(ack_data)

                if ack_header.flags & RUDPHeader.FLAG_SYN and ack_header.flags & RUDPHeader.FLAG_ACK:
                    self.send_seq = (self.send_seq + 1) & 0xFFFF
                    self.connected = True
                    logger.info(f"Connected to {host}:{port}")
                    return

            except socket.timeout:
                if attempt < 2:
                    continue
                raise TimeoutError("Connection SYN-ACK timeout")

    def send_data(self, data: bytes) -> int:
        """Send data with sliding window, retransmission and global deadline."""
        if not self.connected:
            raise RuntimeError("Not connected")

        offset = 0
        deadline = time.time() + self.transfer_timeout

        while offset < len(data) or self.unacked_packets:
            # ----- global timeout guard -----
            if time.time() > deadline:
                raise TimeoutError(
                    f"R-UDP transfer timed out after {self.transfer_timeout}s "
                    f"({offset}/{len(data)} bytes sent)"
                )

            # Clean up any already-acked packets from previous iterations
            self._process_acks()

            # Fill the send window
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

            # Wait for ACK
            try:
                ack_data, _ = self.socket.recvfrom(RUDPHeader.SIZE + 1024)
                ack_header, _ = RUDPHeader.deserialize(ack_data)

                if ack_header.flags & RUDPHeader.FLAG_ACK:
                    acked_seq = ack_header.ack
                    # Cumulative ACK: remove everything up to and including acked_seq
                    for seq in list(self.unacked_packets.keys()):
                        if (acked_seq - seq) & 0xFFFF <= 32768:
                            del self.unacked_packets[seq]
                    self.send_base = (acked_seq + 1) & 0xFFFF

            except socket.timeout:
                # Go-Back-N: retransmit window; raises if max_retries exhausted
                self._retransmit_window()

        # Send FIN
        self._send_fin()
        return offset

    def recv_data(self, expected_size: Optional[int] = None, timeout: float = 5.0) -> bytes:
        """Receive data with window management"""
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

                # Handle SYN (connection setup)
                if header.flags & RUDPHeader.FLAG_SYN:
                    self._send_syn_ack(header.sequence)
                    self.recv_seq = (header.sequence + 1) & 0xFFFF
                    self.connected = True
                    continue

                # Handle FIN (connection close)
                if header.flags & RUDPHeader.FLAG_FIN:
                    self._send_ack(header.sequence)
                    break

                # Handle data
                if header.sequence == self.recv_seq:
                    data += payload
                    self.stats['packets_received'] += 1
                    self.stats['bytes_received'] += len(payload)

                    self.recv_seq = (self.recv_seq + 1) & 0xFFFF

                    # Send ACK
                    self._send_ack(header.sequence)

                    if expected_size and len(data) >= expected_size:
                        break
                else:
                    # Out of order packet, send ACK for expected
                    self._send_ack((self.recv_seq - 1) & 0xFFFF)

            except socket.timeout:
                if expected_size is None or len(data) == 0:
                    break
                continue

        return data

    def _process_acks(self):
        """Try to receive ACK without blocking"""
        self.socket.settimeout(0.001)
        try:
            ack_data, _ = self.socket.recvfrom(RUDPHeader.SIZE + 1024)
            ack_header, _ = RUDPHeader.deserialize(ack_data)

            if ack_header.flags & RUDPHeader.FLAG_ACK:
                acked_seq = ack_header.ack
                # Remove acked packets
                for seq in list(self.unacked_packets.keys()):
                    if (acked_seq - seq) & 0xFFFF <= 32768:
                        del self.unacked_packets[seq]
                        self.send_base = (seq + 1) & 0xFFFF

        except socket.timeout:
            pass
        finally:
            self.socket.settimeout(self.timeout)

    def _retransmit_window(self):
        """Retransmit unacked packets (Go-Back-N).
        Raises RuntimeError if any packet has exceeded max_retries.
        """
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

    def close(self):
        """Close socket"""
        if self.socket:
            self.socket.close()

    def get_stats(self) -> dict:
        """Return statistics"""
        return {
            'packets_sent': self.stats['packets_sent'],
            'packets_received': self.stats['packets_received'],
            'retransmissions': self.stats['retransmissions'],
            'bytes_sent': self.stats['bytes_sent'],
            'bytes_received': self.stats['bytes_received']
        }
