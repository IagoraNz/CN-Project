#!/bin/bash

# Apply tc for network scenarios:
#   Client egress  → full scenario (loss + delay) on data packets
#   Server egress  → delay only on ACK return path (avoids double-loss amplification)

set -e

SCENARIO="${1:-A}"
INTERFACE="${2:-eth0}"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[NET]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }

tc_cmd() {
    local container=$1
    shift
    docker exec "$container" bash -c "
        IF='$INTERFACE'
        tc qdisc del dev \$IF root 2>/dev/null || true
        tc qdisc add dev \$IF root netem $*
        echo \"[\$HOSTNAME] \$(tc qdisc show dev \$IF)\"
    "
}

case "$SCENARIO" in
    A) DELAY="10ms";  LOSS="0%" ;;
    B) DELAY="50ms";  LOSS="10%" ;;
    C) DELAY="100ms"; LOSS="20%" ;;
    *) echo "Unknown scenario: $SCENARIO"; exit 1 ;;
esac

log_info "Scenario $SCENARIO — client: delay $DELAY + loss $LOSS | server: delay $DELAY"
tc_cmd cn-client "delay $DELAY loss $LOSS"
tc_cmd cn-server "delay $DELAY"
log_success "Scenario $SCENARIO applied"
