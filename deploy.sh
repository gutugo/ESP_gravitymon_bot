#!/bin/bash
# GravityMon Deployment Script

set -e

echo "=== GravityMon Deployment ==="

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
    echo "Docker installed successfully"
fi

# Check if Docker Compose is available
if ! docker compose version &> /dev/null; then
    echo "Docker Compose not found. Installing..."
    apt-get update
    apt-get install -y docker-compose-plugin
fi

# Create data directory
mkdir -p /opt/gravitymon/data

# Navigate to project directory
cd /opt/gravitymon

# Check if .env file exists
if [ ! -f .env ]; then
    echo ""
    echo "ERROR: .env file not found!"
    echo "Please create /opt/gravitymon/.env with your Telegram bot token:"
    echo ""
    echo "  echo 'TELEGRAM_BOT_TOKEN=your_token_here' > /opt/gravitymon/.env"
    echo ""
    exit 1
fi

# Build and start containers
echo "Building containers..."
docker compose build

echo "Starting services..."
docker compose up -d

# Wait for services to start
echo "Waiting for services to start..."
sleep 5

# Check status
echo ""
echo "=== Service Status ==="
docker compose ps

echo ""
echo "=== Testing API ==="
curl -s http://localhost:8080/health || echo "API not responding yet, may need more time to start"

echo ""
echo "==================================="
echo "Deployment complete!"
echo ""
echo "API Endpoint: http://YOUR_SERVER_IP:8080/api/v1/webhook"
echo ""
echo "Configure your ESP device to send data to this endpoint."
echo "==================================="
