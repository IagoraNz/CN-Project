#!/bin/bash

# Network scenario tests (single repetition — use run_tests.sh for full suite)

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$PROJECT_ROOT/data"
TEST_FILE="$DATA_DIR/send/test_file.bin"
TEST_FILE_SIZE=$((1024 * 1024))
INTERFACE="${INTERFACE:-eth0}"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[SCENARIO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

create_test_file() {
    log_info "Creating test file ($TEST_FILE_SIZE bytes)..."
    mkdir -p "$DATA_DIR/send"
    if [[ ! -f "$TEST_FILE" ]]; then
        dd if=/dev/urandom of="$TEST_FILE" bs=1M count=1 2>/dev/null
    fi
    log_success "Test file created: $TEST_FILE"
}

run_scenario_test() {
    local scenario=$1
    local protocol=$2

    log_info "Scenario $scenario - $protocol"

    bash "$PROJECT_ROOT/scripts/apply_scenario.sh" "$scenario" "$INTERFACE"
    docker exec cn-server bash /app/scripts/capture_traffic.sh start "$INTERFACE" /app/data/pcap
    sleep 0.5

    docker exec cn-client python3 src/client.py /app/data/send/test_file.bin \
        --protocol "$protocol" --scenario "$scenario" --run 1 \
        --server server --tcp-port 9000 --udp-port 9001

    sleep 2
    docker exec cn-server bash /app/scripts/capture_traffic.sh stop /app/data/pcap
    log_success "Scenario $scenario - $protocol completed"
    sleep 1
}

main() {
    log_info "Network Scenario Tests"
    log_info "======================="

    if ! docker ps > /dev/null 2>&1; then
        log_warn "Docker not running. Please start containers first: make up"
        exit 1
    fi

    create_test_file

    SCENARIOS=("A" "B" "C")
    PROTOCOLS=("tcp" "rudp")

    for scenario in "${SCENARIOS[@]}"; do
        for protocol in "${PROTOCOLS[@]}"; do
            run_scenario_test "$scenario" "$protocol"
        done
    done

    log_success "All scenario tests completed"
}

main
