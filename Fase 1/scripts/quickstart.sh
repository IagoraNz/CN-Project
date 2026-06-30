#!/bin/bash

# Quick start script for CN-Project Phase 1
# Sets up Docker environment and creates test file

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="$PROJECT_ROOT/scripts/compose.sh"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[SETUP]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_info "CN-Project Phase 1 - Quick Start"
log_info "=================================="

# Check .env file
if [ ! -f .env ]; then
    log_info "Creating .env from .env.example..."
    cp .env.example .env
    log_error "Please edit .env with your student information!"
    echo "   STUDENT_ID=your_id"
    echo "   STUDENT_NAME=Your Name"
fi

# Create data directories
log_info "Creating data directories..."
mkdir -p data/{pcap,csv,logs,send,received}
touch data/.gitkeep data/pcap/.gitkeep data/csv/.gitkeep data/logs/.gitkeep
log_success "Data directories created"

# Build Docker image
log_info "Building Docker image..."
"$COMPOSE" build --quiet
log_success "Docker image built"

# Start containers
log_info "Starting containers..."
"$COMPOSE" up -d
log_success "Containers started"

# Wait for containers to be ready
log_info "Waiting for containers to be ready..."
sleep 3

# Create test file on host (shared by server and client via bind mount)
log_info "Creating test file (1MB)..."
mkdir -p "$PROJECT_ROOT/data/send"
dd if=/dev/urandom of="$PROJECT_ROOT/data/send/test_file.bin" bs=1M count=1 2>/dev/null
log_success "Test file created: data/send/test_file.bin"

# Show container info
log_info "Container status:"
"$COMPOSE" ps

log_info ""
log_success "Setup complete!"
log_info ""
echo "Next steps:"
echo "1. Test TCP transfer:"
echo "   docker exec -it cn-client python3 src/client.py /app/data/send/test_file.bin --protocol tcp"
echo ""
echo "2. Test R-UDP transfer:"
echo "   docker exec -it cn-client python3 src/client.py /app/data/send/test_file.bin --protocol rudp"
echo ""
echo "3. View documentation:"
echo "   cat docs/README_FASE1.md"
echo ""
