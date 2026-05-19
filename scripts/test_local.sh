#!/bin/bash

# Local test runner - validates protocols without Docker
# Run unit and integration tests locally

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[TEST]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[PASS]${NC} $1"
}

log_error() {
    echo -e "${RED}[FAIL]${NC} $1"
}

cd "$PROJECT_ROOT"

# Check Python version
log_info "Checking Python version..."
$PYTHON --version

# Install dependencies if needed
log_info "Installing dependencies..."
$PYTHON -m pip install -q pytest 2>/dev/null || true

# Run unit tests
log_info "Running unit tests (R-UDP protocol)..."
if $PYTHON tests/test_rudp.py; then
    log_success "Unit tests passed"
else
    log_error "Unit tests failed"
    exit 1
fi

# Run integration tests
log_info "Running integration tests (client/server)..."
if $PYTHON tests/test_integration.py; then
    log_success "Integration tests passed"
else
    log_error "Integration tests failed"
    exit 1
fi

log_success "All tests passed!"
echo ""
echo "Summary:"
echo "  ✓ R-UDP protocol implementation"
echo "  ✓ Header serialization/deserialization"
echo "  ✓ Sequence numbering and wraparound"
echo "  ✓ TCP file transfer"
echo "  ✓ R-UDP file transfer"
echo "  ✓ Checksum validation"
echo ""
echo "Ready for network simulation tests!"
