#!/bin/bash

# Packet capture with tcpdump + export via tshark (CSV/JSON).
# Usage:
#   capture_traffic.sh start <interface> [pcap_dir]
#   capture_traffic.sh stop  [pcap_dir]
#   capture_traffic.sh <interface> [pcap_dir] [duration_seconds]   # one-shot

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

FILTER='tcp port 9000 or udp port 9001'
DEFAULT_PCAP_DIR="/app/data/pcap"

init_dirs() {
    if [[ "$PCAP_DIR" == *"/pcap" ]]; then
        CSV_DIR="${PCAP_DIR%/pcap}/csv"
    else
        CSV_DIR="$(dirname "$PCAP_DIR")/csv"
    fi
    mkdir -p "$PCAP_DIR" "$CSV_DIR"
    PID_FILE="$PCAP_DIR/.tcpdump.pid"
    PCAP_META="$PCAP_DIR/.current_pcap"
}

run_tcpdump() {
    tcpdump -i "$1" -U -w "$2" $FILTER >/dev/null 2>&1 &
    echo $!
}

export_pcap() {
    local pcap_file="$1"
    local base csv_file json_file

    if [[ ! -s "$pcap_file" ]]; then
        log_warn "PCAP empty or missing: $pcap_file"
        return 1
    fi

    log_info "PCAP saved: $pcap_file ($(wc -c < "$pcap_file") bytes)"
    base="$(basename "$pcap_file" .pcap)"
    csv_file="$CSV_DIR/${base}.csv"
    json_file="$CSV_DIR/${base}.json"

    if command -v tshark >/dev/null 2>&1; then
        log_info "Converting PCAP to CSV..."
        tshark -q -r "$pcap_file" -T fields \
            -e frame.number -e frame.time -e frame.time_epoch -e ip.src -e ip.dst \
            -e tcp.srcport -e tcp.dstport -e udp.srcport -e udp.dstport \
            -e frame.len -e tcp.flags -e tcp.seq -e tcp.ack \
            -E header=y -E separator=',' > "$csv_file" 2>/dev/null
        log_info "CSV export: $csv_file"

        log_info "Converting PCAP to JSON..."
        tshark -q -r "$pcap_file" -T json > "$json_file" 2>/dev/null
        log_info "JSON export: $json_file"
    else
        log_warn "tshark not found — rebuild image: make build"
    fi
}

cmd_start() {
    local interface="${1:-eth0}"
    PCAP_DIR="${2:-$DEFAULT_PCAP_DIR}"
    init_dirs

    local timestamp pcap_file pid
    timestamp="$(date +%Y%m%d_%H%M%S)"
    pcap_file="$PCAP_DIR/traffic_${timestamp}.pcap"

    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        log_warn "Capture already running (PID $(cat "$PID_FILE"))"
        return 0
    fi

    log_info "Starting capture on $interface → $pcap_file"
    pid="$(run_tcpdump "$interface" "$pcap_file")"
    echo "$pid" > "$PID_FILE"
    echo "$pcap_file" > "$PCAP_META"
    log_info "tcpdump PID $pid"
}

cmd_stop() {
    PCAP_DIR="${1:-$DEFAULT_PCAP_DIR}"
    init_dirs

    if [[ ! -f "$PID_FILE" ]]; then
        log_warn "No active capture"
        return 0
    fi

    local pid pcap_file
    pid="$(cat "$PID_FILE")"
    pcap_file="$(cat "$PCAP_META" 2>/dev/null || true)"

    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"

    log_info "Packet capture stopped"
    if [[ -n "$pcap_file" && -f "$pcap_file" ]]; then
        export_pcap "$pcap_file" || true
    else
        log_warn "No PCAP file to export"
    fi
    rm -f "$PCAP_META"
    log_info "Capture and conversion complete"
}

cmd_oneshot() {
    local interface="${1:-eth0}"
    local duration="${3:-30}"
    PCAP_DIR="${2:-$DEFAULT_PCAP_DIR}"
    init_dirs

    local timestamp pcap_file
    timestamp="$(date +%Y%m%d_%H%M%S)"
    pcap_file="$PCAP_DIR/traffic_${timestamp}.pcap"

    log_info "Capturing on $interface for ${duration}s → $pcap_file"
    timeout "$duration" tcpdump -i "$interface" -U -w "$pcap_file" $FILTER >/dev/null 2>&1 || true
    export_pcap "$pcap_file" || true
    log_info "Files: $PCAP_DIR (pcap), $CSV_DIR (csv/json)"
}

ACTION="${1:-}"
shift || true

case "$ACTION" in
    start) cmd_start "$@" ;;
    stop)  cmd_stop "$@" ;;
    *)     cmd_oneshot "$ACTION" "$@" ;;
esac
