#!/bin/bash

# Network scenario tests
# Tests TCP and R-UDP under different network conditions (A, B, C)

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$PROJECT_ROOT/data"
TEST_FILE="$DATA_DIR/test_file.bin"
TEST_FILE_SIZE=$((1024 * 1024))  # 1MB

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[SCENARIO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

# Create test file
create_test_file() {
    log_info "Creating test file ($TEST_FILE_SIZE bytes)..."
    mkdir -p "$DATA_DIR/send"
    dd if=/dev/urandom of="$TEST_FILE" bs=1M count=1 2>/dev/null
    log_success "Test file created: $TEST_FILE"
}

# Run test with given scenario and protocol
run_scenario_test() {
    local scenario=$1
    local protocol=$2
    local interface=$3

    log_info "Scenario $scenario - $protocol"

    # Apply network conditions
    bash "$PROJECT_ROOT/scripts/setup_network.sh" "$interface" "$scenario"

    # Start traffic capture
    bash "$PROJECT_ROOT/scripts/capture_traffic.sh" "$interface" "$DATA_DIR/pcap" 30 &
    CAPTURE_PID=$!
    sleep 1

    # Run transfer
    log_info "Transferring via $protocol..."
    docker exec cn-client python3 src/client.py "$TEST_FILE" \
        --protocol "$protocol" \
        --server server \
        --tcp-port 9000 \
        --udp-port 9001

    # Wait for capture
    wait $CAPTURE_PID 2>/dev/null || true
    log_success "Scenario $scenario - $protocol completed"
    sleep 2
}

# Main
main() {
    log_info "Network Scenario Tests"
    log_info "======================="

    # Check Docker
    if ! docker ps > /dev/null 2>&1; then
        log_warn "Docker not running. Please start containers first:"
        echo "  docker-compose up -d"
        exit 1
    fi

    create_test_file

    # Test all scenarios and protocols
    SCENARIOS=("A" "B" "C")
    PROTOCOLS=("tcp" "rudp")
    INTERFACE="eth0"

    TESTS_PASSED=0
    TESTS_TOTAL=0

    for scenario in "${SCENARIOS[@]}"; do
        for protocol in "${PROTOCOLS[@]}"; do
            TESTS_TOTAL=$((TESTS_TOTAL + 1))
            if run_scenario_test "$scenario" "$protocol" "$INTERFACE"; then
                TESTS_PASSED=$((TESTS_PASSED + 1))
            fi
        done
    done

    log_success "Tests completed: $TESTS_PASSED/$TESTS_TOTAL passed"
    echo ""
    echo "Results:"
    echo "  Scenario A: 0% loss, 10ms delay"
    echo "  Scenario B: 10% loss, 50ms delay"
    echo "  Scenario C: 20% loss, 100ms delay"
    echo ""
    echo "Data saved to: $DATA_DIR"
    echo "  PCAP files: $DATA_DIR/pcap/"
    echo "  CSV exports: $DATA_DIR/csv/"
    echo "  Logs: $DATA_DIR/logs/"
}

main
