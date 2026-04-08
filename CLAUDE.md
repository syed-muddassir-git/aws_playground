# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AWS Multi-Account Dashboard - Interactive TUI application for inventorying and searching AWS resources across multiple accounts in an AWS Organization. Supports both real AWS and LocalStack (free local testing).

**Two versions available:**
- `aws_dashboard3.py` - Enhanced version with debug logging, better error handling, and startup diagnostics (recommended)
- `aws_dashboard.py` - Original version with basic functionality

## Running the Application

**With LocalStack (free):**
```bash
docker-compose -f docker-compose.localstack.yml up -d
./setup_localstack_data.sh  # Create sample data
./run_with_localstack.sh
```

**With real AWS:**
```bash
source venv/bin/activate
python3 aws_dashboard3.py
python3 aws_dashboard3.py --role CustomRoleName  # Override default role
```

**Prerequisites:**
- Virtual environment activated with boto3 installed
- AWS credentials configured (real AWS) or LocalStack running (local testing)

## Architecture

### Cross-Account Access
- Discovers accounts via `organizations:ListAccounts`
- Assumes IAM role in each child account using `sts:AssumeRole`
- Default role: `Operative-FullAccess` (override via `--role` or `ACCOUNT_ROLE_OVERRIDES`)
- Falls back to single-account mode if Organizations unavailable

### Resource Discovery
- Regions fetched once per account, then cached
- S3 treated as global (one ListBuckets call per account)
- EC2, RDS, Load Balancers iterated across all enabled regions
- All API calls use boto3 paginators to avoid missing resources

### TUI Implementation
- Built with Python `curses` library
- Must run in actual terminal (not programmatically testable)
- Color-coded display: cyan headers, green for active resources, red for errors
- Keyboard-only navigation (no mouse support)

### Error Handling
- Role assumption failures tracked in `_role_failures` list and displayed to user
- Graceful degradation: continues with accessible accounts even if some fail
- All errors logged to `~/aws_dashboard_debug.log` with timestamps
- AWS API exceptions caught using `AWSError` tuple

## LocalStack Integration

LocalStack support is **completely isolated** from main implementation via:
- `localstack_config.py` - Patches boto3 client methods to inject LocalStack endpoint
- `run_with_localstack.sh` - Wrapper script that activates venv and runs config wrapper
- No changes to `aws_dashboard3.py` required

**How it works:**
1. `localstack_config.py` monkey-patches `boto3.client()` and `boto3.Session.client()`
2. Injects `endpoint_url=http://localhost:4566` into all AWS API calls
3. Loads and executes `aws_dashboard3.py` with patched boto3

**Limitations:**
- LocalStack free tier doesn't support AWS Organizations (dashboard falls back to single account)
- Only basic services available: EC2, S3, RDS, ELB, STS
- Data is not persistent across container restarts

## File Structure

- `aws_dashboard3.py` - Main dashboard (never modify for LocalStack compatibility)
- `localstack_config.py` - LocalStack boto3 patching wrapper
- `run_with_localstack.sh` - LocalStack launcher
- `docker-compose.localstack.yml` - LocalStack Docker configuration
- `setup_localstack_data.sh` - Creates sample EC2/S3/RDS resources in LocalStack

## Key Configuration Points

**Account-specific role overrides** (`ACCOUNT_ROLE_OVERRIDES` dict):
- Maps AWS account IDs to custom IAM role names
- Overrides `ROLE_NAME` default for specific accounts

**EC2 tag collection** (`EC2_TAGS` list):
- Defines which EC2 tags to extract during inventory
- Affects both inventory display and CSV exports

**Export locations:**
- CSV files: `~/aws_dashboard_exports/`
- Debug log: `~/aws_dashboard_debug.log`

## API Call Optimization

The dashboard minimizes AWS API usage:
- Account discovery: 1 call (`organizations:ListAccounts`)
- Per account: 1 role assumption + 1 region discovery
- Per region per account: 1 call per resource type (EC2/RDS/LB)
- S3: 1 `ListBuckets` + 1 `GetBucketLocation` per bucket
- Search operations filter at API level to reduce data transfer

## Important Notes

- The TUI uses curses which requires a real terminal - cannot be tested programmatically
- When modifying LocalStack support, keep changes isolated to wrapper scripts
- The dashboard handles Organizations API failures gracefully (common in single-account AWS or LocalStack)
- Debug logging is always enabled in aws_dashboard3.py - check `~/aws_dashboard_debug.log` for troubleshooting
