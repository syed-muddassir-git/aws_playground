#!/bin/bash
#
# Setup script to populate LocalStack with sample AWS resources
# Run this after starting LocalStack to create test data
#

# Activate virtual environment
source venv/bin/activate

# Run the Python setup script
python3 setup_localstack_data.py
