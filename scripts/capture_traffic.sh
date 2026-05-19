#!/bin/bash

# TCPDump capture script
# Captures network traffic and exports to multiple formats

INTERFACE="${1:-eth0}"
OUTPUT_DIR="${2:-/app/data/pcap}"
DURATION="${3:-60}"  # Default 60 seconds

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

# Create output directory
mkdir -p "$OUTPUT_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
PCAP_FILE="$OUTPUT_DIR/traffic_${TIMESTAMP}.pcap"
CSV_FILE="$OUTPUT_DIR/traffic_${TIMESTAMP}.csv"
JSON_FILE="$OUTPUT_DIR/traffic_${TIMESTAMP}.json"

log_info "Starting packet capture on $INTERFACE"
log_info "Output files:"
log_info "  PCAP: $PCAP_FILE"
log_info "  CSV:  $CSV_FILE"
log_info "  JSON: $JSON_FILE"
log_info "Duration: ${DURATION}s"

# Start tcpdump in background
sudo tcpdump -i "$INTERFACE" -w "$PCAP_FILE" -G "$DURATION" -W 1 \
    'tcp port 9000 or udp port 9001' > /dev/null 2>&1 &

TCPDUMP_PID=$!
log_info "TCPDump started with PID $TCPDUMP_PID"

# Wait for tcpdump to finish
wait $TCPDUMP_PID
log_info "Packet capture complete"

# Convert PCAP to CSV using tshark
if command -v tshark &> /dev/null; then
    log_info "Converting PCAP to CSV format..."
    tshark -r "$PCAP_FILE" -T fields \
        -e frame.number -e frame.time -e ip.src -e ip.dst \
        -e tcp.srcport -e tcp.dstport -e udp.srcport -e udp.dstport \
        -e frame.len -e tcp.flags -e tcp.seq -e tcp.ack \
        -E header=y -E separator=',' > "$CSV_FILE"
    log_info "CSV export complete: $CSV_FILE"
else
    log_warn "tshark not found, skipping CSV export"
fi

# Convert PCAP to JSON using tshark
if command -v tshark &> /dev/null; then
    log_info "Converting PCAP to JSON format..."
    tshark -r "$PCAP_FILE" -T json > "$JSON_FILE"
    log_info "JSON export complete: $JSON_FILE"
else
    log_warn "tshark not found, skipping JSON export"
fi

log_info "Capture and conversion complete"
echo "Files saved in: $OUTPUT_DIR"
