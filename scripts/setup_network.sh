#!/bin/bash

# Network simulation setup script
# Applies tc (traffic control) to simulate network conditions

INTERFACE="${1:-eth0}"
SCENARIO="${2:-A}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

# Check if interface exists
if ! ip link show "$INTERFACE" > /dev/null 2>&1; then
    log_error "Interface $INTERFACE not found"
    exit 1
fi

# Clear existing rules
log_info "Clearing existing tc rules on $INTERFACE"
sudo tc qdisc del dev "$INTERFACE" root 2>/dev/null

case "$SCENARIO" in
    A)
        log_info "Applying Scenario A: 0% loss, 10ms delay"
        sudo tc qdisc add dev "$INTERFACE" root netem delay 10ms
        ;;
    B)
        log_info "Applying Scenario B: 10% loss, 50ms delay"
        sudo tc qdisc add dev "$INTERFACE" root netem delay 50ms loss 10%
        ;;
    C)
        log_info "Applying Scenario C: 20% loss, 100ms delay"
        sudo tc qdisc add dev "$INTERFACE" root netem delay 100ms loss 20%
        ;;
    *)
        log_error "Unknown scenario: $SCENARIO"
        echo "Available scenarios: A, B, C"
        exit 1
        ;;
esac

# Display current rules
log_info "Current tc configuration:"
sudo tc qdisc show dev "$INTERFACE"
