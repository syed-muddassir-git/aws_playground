#!/usr/bin/env python3
"""
LocalStack configuration wrapper for aws_dashboard3.py
Patches boto3 to use LocalStack endpoints without modifying the main code.
"""
import os
import sys

# Set LocalStack configuration before importing boto3
os.environ['AWS_ACCESS_KEY_ID'] = 'test'
os.environ['AWS_SECRET_ACCESS_KEY'] = 'test'
os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'

LOCALSTACK_ENDPOINT = 'http://localhost:4566'

# Import boto3 and patch it
import boto3
from botocore.client import Config

# Save original client method
_original_client = boto3.client
_original_session_client = boto3.Session.client

def patched_client(service_name, **kwargs):
    """Patched boto3.client() to always use LocalStack endpoint"""
    kwargs['endpoint_url'] = LOCALSTACK_ENDPOINT
    kwargs['region_name'] = kwargs.get('region_name', 'us-east-1')
    return _original_client(service_name, **kwargs)

def patched_session_client(self, service_name, **kwargs):
    """Patched Session.client() to always use LocalStack endpoint"""
    kwargs['endpoint_url'] = LOCALSTACK_ENDPOINT
    kwargs['region_name'] = kwargs.get('region_name', 'us-east-1')
    return _original_session_client(self, service_name, **kwargs)

# Apply patches
boto3.client = patched_client
boto3.Session.client = patched_session_client

print("=" * 50)
print("🚀 LocalStack Mode Activated")
print("=" * 50)
print(f"Endpoint: {LOCALSTACK_ENDPOINT}")
print(f"Region: us-east-1")
print("=" * 50)
print()

# Import and run the main dashboard
if __name__ == '__main__':
    # Remove this script from argv so dashboard doesn't see it
    sys.argv = ['aws_dashboard3.py'] + sys.argv[1:]

    # Import curses first (it's used in the dashboard)
    import curses

    # Import the dashboard module and get its main function
    import importlib.util
    spec = importlib.util.spec_from_file_location("aws_dashboard3", "aws_dashboard3.py")
    dashboard = importlib.util.module_from_spec(spec)

    # Execute the module to define all functions
    spec.loader.exec_module(dashboard)

    # Now run the main function using curses wrapper
    try:
        curses.wrapper(dashboard.main)
    except KeyboardInterrupt:
        print("\nExited.")
    except Exception as e:
        print(f"\nFatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
