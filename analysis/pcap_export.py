#!/usr/bin/env python3
"""Export PCAP to CSV/JSON using tcpdump (exclusive capture tool per project spec)."""
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

LINE_RE = re.compile(
    r'^(\d+\.\d+)\s+IP\s+(\S+)\.(\d+)\s+>\s+(\S+)\.(\d+):\s+'
    r'(.*?)(?:,\s*length\s+(\d+))?$'
)
TCP_SEQ_RE = re.compile(
    r'Flags \[([^\]]*)\], seq (\d+)(?::(\d+))?, ack (\d+)(?:, win \d+)?(?:, options [^,]+)?, length (\d+)'
)


def detect_auth_in_pcap(pcap_file: Path) -> bool:
    """Search packet payloads for X-Custom-Auth using tcpdump -A."""
    result = subprocess.run(
        ['tcpdump', '-r', str(pcap_file), '-A', '-s', '256', '-q'],
        capture_output=True, text=True, check=False
    )
    return 'X-Custom-Auth' in result.stdout


def count_tcp_retransmissions(pcap_file: Path, port: int = 9000) -> int:
    """Count TCP retransmissions via duplicate sequence numbers (client → server)."""
    result = subprocess.run(
        ['tcpdump', '-r', str(pcap_file), '-nn', '-S'],
        capture_output=True, text=True, check=False
    )
    seen_seqs: set[int] = set()
    retrans = 0
    for line in result.stdout.splitlines():
        if f'.{port} >' in line or f':{port},' in line:
            continue
        if f'.{port}:' not in line and f'.{port},' not in line:
            if f'>{port}' not in line:
                continue
        m = TCP_SEQ_RE.search(line)
        if not m or int(m.group(5)) == 0:
            continue
        seq = int(m.group(2))
        if seq in seen_seqs:
            retrans += 1
        seen_seqs.add(seq)
    return retrans


def parse_pcap_with_tcpdump(pcap_file: Path) -> list[dict]:
    """Parse pcap using tcpdump -r (no tshark/wireshark)."""
    result = subprocess.run(
        ['tcpdump', '-r', str(pcap_file), '-tt', '-nn', '-S'],
        capture_output=True, text=True, check=False
    )
    packets = []
    for i, line in enumerate(result.stdout.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        m = LINE_RE.match(line)
        tcp_seq = ''
        tcp_match = TCP_SEQ_RE.search(line)
        if tcp_match:
            tcp_seq = tcp_match.group(2)

        if m:
            ts, src_ip, src_port, dst_ip, dst_port, proto_info, length = m.groups()
            packets.append({
                'frame.number': i,
                'frame.time_epoch': ts,
                'ip.src': src_ip,
                'ip.dst': dst_ip,
                'srcport': src_port,
                'dstport': dst_port,
                'protocol': proto_info.split(',')[0].strip(),
                'frame.len': length or (tcp_match.group(5) if tcp_match else ''),
                'tcp.seq': tcp_seq,
                'raw': line,
            })
        else:
            packets.append({
                'frame.number': i,
                'frame.time_epoch': '',
                'ip.src': '', 'ip.dst': '',
                'srcport': '', 'dstport': '',
                'protocol': '', 'frame.len': '',
                'tcp.seq': tcp_seq,
                'raw': line,
            })
    return packets


def export_pcap(pcap_file: Path, csv_file: Path, json_file: Path) -> int:
    packets = parse_pcap_with_tcpdump(pcap_file)
    has_auth = detect_auth_in_pcap(pcap_file)
    tcp_retrans = count_tcp_retransmissions(pcap_file)

    fieldnames = [
        'frame.number', 'frame.time_epoch', 'ip.src', 'ip.dst',
        'srcport', 'dstport', 'protocol', 'frame.len', 'tcp.seq', 'raw'
    ]
    with open(csv_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(packets)

    with open(json_file, 'w') as f:
        json.dump({
            'source': str(pcap_file),
            'packet_count': len(packets),
            'x_custom_auth_detected': has_auth,
            'tcp_retransmissions': tcp_retrans,
            'packets': packets,
        }, f, indent=2)

    auth_status = 'found' if has_auth else 'NOT FOUND'
    print(f'Exported {len(packets)} packets via tcpdump (X-Custom-Auth: {auth_status}, TCP retrans: {tcp_retrans})')
    return len(packets)


if __name__ == '__main__':
    if len(sys.argv) < 4:
        print(f'Usage: {sys.argv[0]} <pcap> <csv> <json>', file=sys.stderr)
        sys.exit(1)
    count = export_pcap(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
    sys.exit(0 if count > 0 else 1)
