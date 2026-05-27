#!/bin/bash

# Test runner — executes file transfer tests under network scenarios.
# Runs REPETITIONS times per scenario/protocol for statistical analysis.

set -e

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$TEST_DIR/data"
TEST_FILE="$DATA_DIR/send/test_file.bin"
TEST_FILE_SIZE=$((1024 * 1024))
REPETITIONS="${REPETITIONS:-5}"
INTERFACE="${INTERFACE:-eth0}"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[TEST]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

create_test_file() {
    log_info "Creating test file ($TEST_FILE_SIZE bytes)..."
    mkdir -p "$DATA_DIR/send"
    if [[ ! -f "$TEST_FILE" ]]; then
        dd if=/dev/urandom of="$TEST_FILE" bs=1M count=1 2>/dev/null
    fi
    log_success "Test file ready: $TEST_FILE"
}

run_test() {
    local scenario=$1
    local protocol=$2
    local run=$3

    log_info "Scenario $scenario | $protocol | run $run/$REPETITIONS"

    bash "$TEST_DIR/scripts/apply_scenario.sh" "$scenario" "$INTERFACE"

    docker exec cn-server bash /app/scripts/capture_traffic.sh start "$INTERFACE" /app/data/pcap
    sleep 0.5

    docker exec cn-client python3 src/client.py "/app/data/send/test_file.bin" \
        --protocol "$protocol" --scenario "$scenario" --run "$run" \
        --server server --tcp-port 9000 --udp-port 9001

    sleep 2
    docker exec cn-server bash /app/scripts/capture_traffic.sh stop /app/data/pcap
    log_success "Done: scenario=$scenario protocol=$protocol run=$run"
    sleep 1
}

main() {
    log_info "Network Simulation Tests (${REPETITIONS} repetitions per combo)"
    log_info "Test directory: $TEST_DIR"

    if ! docker ps --format '{{.Names}}' | grep -q '^cn-server$'; then
        log_warn "Containers not running. Start with: make up"
        exit 1
    fi

    create_test_file

    # Reset consolidated metrics
    docker exec cn-client bash -c 'echo "[]" > /app/data/logs/client_metrics_all.json'

    SCENARIOS=("A" "B" "C")
    PROTOCOLS=("tcp" "rudp")

    for scenario in "${SCENARIOS[@]}"; do
        for protocol in "${PROTOCOLS[@]}"; do
            for run in $(seq 1 "$REPETITIONS"); do
                run_test "$scenario" "$protocol" "$run"
            done
        done
    done

    log_success "All tests completed (${REPETITIONS}×3×2 = $((REPETITIONS * 6)) runs)"
    log_info "Results: $DATA_DIR"
    log_info "  PCAP:  $DATA_DIR/pcap/"
    log_info "  CSV:   $DATA_DIR/csv/"
    log_info "  Logs:  $DATA_DIR/logs/client_metrics_all.json"
}

main
