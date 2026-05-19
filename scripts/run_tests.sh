#!/bin/bash

# Test runner script
# Executes file transfer tests under different network conditions

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$TEST_DIR/data"
TEST_FILE="$DATA_DIR/test_file.bin"

# Test file size (1MB)
TEST_FILE_SIZE=$((1024 * 1024))

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[TEST]${NC} $1"
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

# Run single test
run_test() {
    local scenario=$1
    local protocol=$2
    local interface=$3

    log_info "Running: Scenario $scenario, Protocol $protocol"

    # Apply network conditions
    "$TEST_DIR/scripts/setup_network.sh" "$interface" "$scenario"

    # Start traffic capture
    "$TEST_DIR/scripts/capture_traffic.sh" "$interface" "$DATA_DIR/pcap" 30 &
    CAPTURE_PID=$!
    sleep 1

    # Run transfer
    log_info "Starting file transfer..."
    cd "$TEST_DIR"
    python3 src/client.py "$TEST_FILE" --protocol "$protocol" \
        --server server --tcp-port 9000 --udp-port 9001

    # Wait for capture to finish
    wait $CAPTURE_PID 2>/dev/null
    log_success "Test completed: Scenario $scenario, $protocol"
    sleep 2
}

# Main test execution
main() {
    log_info "Starting Network Simulation Tests"
    log_info "Test directory: $TEST_DIR"

    create_test_file

    # Test scenarios
    SCENARIOS=("A" "B" "C")
    PROTOCOLS=("tcp" "rudp")
    INTERFACE="eth0"

    for scenario in "${SCENARIOS[@]}"; do
        for protocol in "${PROTOCOLS[@]}"; do
            run_test "$scenario" "$protocol" "$INTERFACE"
        done
    done

    log_success "All tests completed!"
    log_info "Results saved to: $DATA_DIR"
}

main
