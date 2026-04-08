#!/usr/bin/env python3
"""
Setup script to populate LocalStack with sample AWS resources
Run this after starting LocalStack to create test data
"""
import boto3
import sys
import requests

ENDPOINT = "http://localhost:4566"
REGION = "us-east-1"

# Configure boto3 for LocalStack
session_kwargs = {
    'aws_access_key_id': 'test',
    'aws_secret_access_key': 'test',
    'region_name': REGION
}

client_kwargs = {
    'endpoint_url': ENDPOINT,
    **session_kwargs
}

print("=" * 50)
print("Populating LocalStack with sample data")
print("=" * 50)
print()

# Check if LocalStack is running
try:
    resp = requests.get(f"{ENDPOINT}/_localstack/health", timeout=2)
    if resp.status_code != 200:
        raise Exception("LocalStack not responding")
    print("✅ LocalStack is running")
    print()
except Exception as e:
    print("❌ Error: LocalStack is not running")
    print()
    print("Start LocalStack first:")
    print("  docker-compose -f docker-compose.localstack.yml up -d")
    print()
    sys.exit(1)

# Create EC2 instances
print("Creating EC2 instances...")
ec2 = boto3.client('ec2', **client_kwargs)

try:
    # Create instances with tags
    ec2.run_instances(
        ImageId='ami-12345678',
        InstanceType='t2.micro',
        MinCount=2,
        MaxCount=2,
        TagSpecifications=[{
            'ResourceType': 'instance',
            'Tags': [
                {'Key': 'Name', 'Value': 'WebServer-1'},
                {'Key': 'Environment', 'Value': 'Production'},
                {'Key': 'Application', 'Value': 'WebApp'}
            ]
        }]
    )

    ec2.run_instances(
        ImageId='ami-87654321',
        InstanceType='t3.small',
        MinCount=1,
        MaxCount=1,
        TagSpecifications=[{
            'ResourceType': 'instance',
            'Tags': [
                {'Key': 'Name', 'Value': 'Database-Server'},
                {'Key': 'Environment', 'Value': 'Development'},
                {'Key': 'Application', 'Value': 'MySQL'}
            ]
        }]
    )
    print("✅ Created 3 EC2 instances")
except Exception as e:
    print(f"⚠️  EC2 creation error: {e}")

# Create S3 buckets
print("Creating S3 buckets...")
s3 = boto3.client('s3', **client_kwargs)

buckets = ['my-app-data', 'backup-bucket', 'logs-storage']
created = 0
for bucket_name in buckets:
    try:
        s3.create_bucket(Bucket=bucket_name)
        created += 1
    except Exception as e:
        print(f"⚠️  Failed to create {bucket_name}: {e}")

print(f"✅ Created {created} S3 buckets")

# Create RDS instance (only if RDS is available - it's a Pro feature in LocalStack)
print("Creating RDS instance...")
rds = boto3.client('rds', **client_kwargs)

rds_created = False
try:
    rds.create_db_instance(
        DBInstanceIdentifier='my-database',
        DBInstanceClass='db.t3.micro',
        Engine='mysql',
        MasterUsername='admin',
        MasterUserPassword='password123',
        AllocatedStorage=20
    )
    print("✅ Created 1 RDS instance")
    rds_created = True
except Exception as e:
    if "not yet implemented or pro feature" in str(e):
        print("ℹ️  RDS is a LocalStack Pro feature (skipped)")
    else:
        print(f"⚠️  RDS creation error: {e}")

print()
print("=" * 50)
print("✅ Sample data created successfully!")
print("=" * 50)
print()
print("You can now run the dashboard:")
print("  ./run_with_localstack.sh")
print()
print("Resources created:")
print("  - 3 EC2 instances (WebServer-1, Database-Server)")
print("  - 3 S3 buckets (my-app-data, backup-bucket, logs-storage)")
if rds_created:
    print("  - 1 RDS instance (my-database)")
print()
