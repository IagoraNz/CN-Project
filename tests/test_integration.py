#!/usr/bin/env python3
"""Integration tests for client/server communication"""
import sys
import os
import unittest
import threading
import time
import tempfile
import hashlib
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from client import FileTransferClient
from server import FileTransferServer


class TestFileTransferIntegration(unittest.TestCase):
    """Integration tests for file transfer protocols"""

    @classmethod
    def setUpClass(cls):
        """Start test server"""
        cls.server = FileTransferServer('127.0.0.1', 19000, 19001)
        cls.tcp_thread = cls.server.run_tcp_server()
        cls.rudp_thread = cls.server.run_rudp_server()
        time.sleep(0.5)  # Wait for server to start

    @classmethod
    def tearDownClass(cls):
        """Stop test server"""
        try:
            cls.tcp_thread.join(timeout=2)
        except:
            pass
        try:
            cls.rudp_thread.join(timeout=2)
        except:
            pass

    def setUp(self):
        """Create test file"""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_file = Path(self.temp_dir.name) / 'test.bin'

    def tearDown(self):
        """Clean up"""
        self.temp_dir.cleanup()

    def _create_test_file(self, size: int = 1024):
        """Create test file of given size"""
        with open(self.test_file, 'wb') as f:
            f.write(os.urandom(size))

    def _calculate_checksum(self, filepath: Path) -> str:
        """Calculate file checksum"""
        sha256_hash = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()

    def test_tcp_small_file(self):
        """Test TCP transfer with small file (1KB)"""
        self._create_test_file(1024)
        client = FileTransferClient('127.0.0.1', 19000, 19001)

        try:
            result = client.send_file(str(self.test_file), 'tcp')
            self.assertNotIn('error', result)
            self.assertEqual(result['protocol'], 'TCP')
            self.assertEqual(result['size_bytes'], 1024)
            self.assertGreaterEqual(result['sent_bytes'], 1024)
            self.assertIn('x_custom_auth', result)
            self.assertGreater(result['throughput_mbps'], 0)
        except Exception as e:
            self.fail(f"TCP transfer failed: {e}")

    def test_tcp_medium_file(self):
        """Test TCP transfer with medium file (1MB)"""
        self._create_test_file(1024 * 1024)
        client = FileTransferClient('127.0.0.1', 19000, 19001)

        try:
            result = client.send_file(str(self.test_file), 'tcp')
            self.assertNotIn('error', result)
            self.assertEqual(result['size_bytes'], 1024 * 1024)
            self.assertGreaterEqual(result['sent_bytes'], 1024 * 1024)
            self.assertGreater(result['throughput_mbps'], 0)
        except Exception as e:
            self.fail(f"TCP transfer failed: {e}")

    def test_tcp_checksum_validation(self):
        """Test that received file has correct checksum"""
        self._create_test_file(10240)
        original_checksum = self._calculate_checksum(self.test_file)

        client = FileTransferClient('127.0.0.1', 19000, 19001)
        result = client.send_file(str(self.test_file), 'tcp')

        self.assertNotIn('error', result)
        self.assertEqual(result['checksum'], original_checksum)

    def test_rudp_small_file(self):
        """Test R-UDP transfer with small file (1KB)"""
        self._create_test_file(1024)
        client = FileTransferClient('127.0.0.1', 19000, 19001)

        try:
            result = client.send_file(str(self.test_file), 'rudp')
            self.assertNotIn('error', result)
            self.assertEqual(result['protocol'], 'R-UDP')
            self.assertGreater(result['throughput_mbps'], 0)
        except Exception as e:
            self.fail(f"R-UDP transfer failed: {e}")

    def test_rudp_medium_file(self):
        """Test R-UDP transfer with medium file (1MB)"""
        self._create_test_file(1024 * 1024)
        client = FileTransferClient('127.0.0.1', 19000, 19001)

        try:
            result = client.send_file(str(self.test_file), 'rudp')
            self.assertNotIn('error', result)
            self.assertEqual(result['protocol'], 'R-UDP')
        except Exception as e:
            self.fail(f"R-UDP transfer failed: {e}")

    def test_rudp_checksum_validation(self):
        """Test R-UDP received file checksum"""
        self._create_test_file(10240)
        original_checksum = self._calculate_checksum(self.test_file)

        client = FileTransferClient('127.0.0.1', 19000, 19001)
        result = client.send_file(str(self.test_file), 'rudp')

        self.assertNotIn('error', result)
        self.assertEqual(result['checksum'], original_checksum)

    def test_tcp_error_handling(self):
        """Test TCP error handling with unreachable server"""
        self._create_test_file(1024)
        client = FileTransferClient('127.0.0.1', 39999, 39998)  # Non-existent server

        result = client.send_file(str(self.test_file), 'tcp')
        self.assertIn('error', result)

    def test_nonexistent_file(self):
        """Test error handling for non-existent file"""
        client = FileTransferClient('127.0.0.1', 19000, 19001)
        result = client.send_file('/nonexistent/file.bin', 'tcp')
        self.assertIn('error', result)


def run_tests():
    """Run all integration tests"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestFileTransferIntegration))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
