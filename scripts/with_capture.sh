#!/bin/bash
# Run a client transfer with packet capture on the server.
# Usage: with_capture.sh <protocol> [interface] [scenario]
#   protocol: tcp|rudp
#   scenario: A|B|C (optional, for per-scenario graphs)

set -e
PROTOCOL="${1:-tcp}"
INTERFACE="${2:-eth0}"
SCENARIO="${3:-}"

SCENARIO_ARGS=()
if [[ -n "$SCENARIO" ]]; then
    SCENARIO_ARGS=(--scenario "$SCENARIO")
fi

docker exec cn-server bash /app/scripts/capture_traffic.sh start "$INTERFACE" /app/data/pcap
sleep 0.5
docker exec cn-client python3 src/client.py /app/data/send/test_file.bin \
    --protocol "$PROTOCOL" "${SCENARIO_ARGS[@]}"
docker exec cn-server bash /app/scripts/capture_traffic.sh stop /app/data/pcap
