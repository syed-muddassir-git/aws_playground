#!/bin/bash
#
# Wrapper script to run AWS Dashboard with LocalStack
#
# Usage: ./run_with_localstack.sh
#

# Activate virtual environment
source venv/bin/activate

# Check if LocalStack is running
if ! curl -s http://localhost:4566/_localstack/health > /dev/null 2>&1; then
    echo "❌ Error: LocalStack is not running"
    echo ""
    echo "Start LocalStack first:"
    echo "  docker-compose -f docker-compose.localstack.yml up -d"
    echo ""
    exit 1
fi

echo "✅ LocalStack is running"
echo "✅ Virtual environment activated"
echo ""

# Run the dashboard with LocalStack config wrapper
python3 localstack_config.py "$@"
