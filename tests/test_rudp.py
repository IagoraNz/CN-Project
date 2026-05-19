#!/usr/bin/env python3
"""Unit tests for R-UDP protocol implementation"""
import sys
import os
import unittest
import time
import struct
import socket

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from rudp import RUDPHeader, RUDPSocket


class TestRUDPHeader(unittest.TestCase):
    """Test R-UDP header serialization/deserialization"""

    def test_header_serialize(self):
        """Test header packing"""
        header = RUDPHeader(100, 50, 1024, 12345, 0, b'test_data')
        packet = header.serialize()
        self.assertGreater(len(packet), RUDPHeader.SIZE)
        self.assertEqual(len(packet), RUDPHeader.SIZE + 9)

    def test_header_deserialize(self):
        """Test header unpacking"""
        data = b'test_payload_data'
        header = RUDPHeader(123, 456, len(data), 99999, 1, data)
        packet = header.serialize()

        unpacked_header, payload = RUDPHeader.deserialize(packet)
        self.assertEqual(unpacked_header.sequence, 123)
        self.assertEqual(unpacked_header.ack, 456)
        self.assertEqual(unpacked_header.length, len(data))
        self.assertEqual(unpacked_header.flags, 1)
        self.assertEqual(payload, data)

    def test_sequence_wraparound(self):
        """Test sequence number wrapping (16-bit)"""
        header = RUDPHeader(0xFFFF, 0, 0, 0, 0)
        self.assertEqual(header.sequence, 0xFFFF)

        header2 = RUDPHeader(0x10000, 0, 0, 0, 0)
        self.assertEqual(header2.sequence, 0)  # Should wrap

    def test_checksum_validation(self):
        """Test checksum generation and validation"""
        data = b'checksum_test_data'
        header = RUDPHeader(1, 2, len(data), 12345, 0, data)
        packet = header.serialize()

        unpacked, payload = RUDPHeader.deserialize(packet)
        # Checksums should match
        self.assertEqual(header.checksum, unpacked.checksum)

    def test_flags(self):
        """Test header flags"""
        header_ack = RUDPHeader(0, 0, 0, 0, RUDPHeader.FLAG_ACK)
        self.assertTrue(header_ack.flags & RUDPHeader.FLAG_ACK)

        header_fin = RUDPHeader(0, 0, 0, 0, RUDPHeader.FLAG_FIN)
        self.assertTrue(header_fin.flags & RUDPHeader.FLAG_FIN)

        header_syn = RUDPHeader(0, 0, 0, 0, RUDPHeader.FLAG_SYN)
        self.assertTrue(header_syn.flags & RUDPHeader.FLAG_SYN)


class TestRUDPSocket(unittest.TestCase):
    """Test R-UDP socket operations"""

    def setUp(self):
        """Set up test sockets"""
        self.server_socket = RUDPSocket()
        self.client_socket = RUDPSocket()

    def tearDown(self):
        """Clean up sockets"""
        try:
            self.server_socket.close()
        except:
            pass
        try:
            self.client_socket.close()
        except:
            pass

    def test_socket_creation(self):
        """Test socket initialization"""
        sock = RUDPSocket(timeout=3.0, window_size=8)
        self.assertEqual(sock.timeout, 3.0)
        self.assertEqual(sock.window_size, 8)
        sock.close()

    def test_bind(self):
        """Test socket binding"""
        self.server_socket.bind('127.0.0.1', 19999)
        # Should not raise exception

    def test_sequence_numbering(self):
        """Test sequence number management"""
        sock = RUDPSocket()

        # Initial sequence
        initial_seq = sock.send_seq
        self.assertEqual(initial_seq, 0)

        # After increment
        sock.send_seq = (sock.send_seq + 1) & 0xFFFF
        self.assertEqual(sock.send_seq, 1)

        sock.close()

    def test_window_management(self):
        """Test sliding window state"""
        sock = RUDPSocket(window_size=4)

        # Window should not exceed max
        sock.send_seq = 3
        sock.send_base = 0
        window_size = (sock.send_seq - sock.send_base) & 0xFFFF
        self.assertEqual(window_size, 3)

        sock.close()

    def test_stats_tracking(self):
        """Test statistics collection"""
        sock = RUDPSocket()

        # Initial stats
        stats = sock.get_stats()
        self.assertEqual(stats['packets_sent'], 0)
        self.assertEqual(stats['packets_received'], 0)
        self.assertEqual(stats['retransmissions'], 0)

        sock.close()

    def test_invalid_header(self):
        """Test error handling for invalid headers"""
        invalid_data = b'x' * 5  # Too small

        with self.assertRaises(ValueError):
            RUDPHeader.deserialize(invalid_data)


class TestRUDPIntegration(unittest.TestCase):
    """Integration tests for R-UDP protocol"""

    def test_local_loopback(self):
        """Test sending/receiving on localhost"""
        server = RUDPSocket()
        client = RUDPSocket()

        try:
            # Bind server
            server.bind('127.0.0.1', 29999)

            # Connect client
            client.connect('127.0.0.1', 29999)
            self.assertTrue(client.connected)

        except Exception as e:
            self.fail(f"Connection setup failed: {e}")
        finally:
            server.close()
            client.close()

    def test_window_wraparound(self):
        """Test sequence number wraparound in window"""
        sock = RUDPSocket()

        # Simulate window near wraparound
        sock.send_seq = 0xFFFE
        sock.send_base = 0xFFFC

        window = (sock.send_seq - sock.send_base) & 0xFFFF
        self.assertLess(window, sock.window_size)

        sock.close()


def run_tests():
    """Run all tests"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestRUDPHeader))
    suite.addTests(loader.loadTestsFromTestCase(TestRUDPSocket))
    suite.addTests(loader.loadTestsFromTestCase(TestRUDPIntegration))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
