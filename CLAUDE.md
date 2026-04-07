# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AWS Multi-Account Dashboard - An interactive TUI (Terminal User Interface) application for inventorying and searching AWS resources across multiple accounts in an AWS Organization. Uses cross-account IAM role assumption to access child accounts from a management account.

## Running the Application

**Primary script (enhanced version):**
```bash
python3 aws_dashboard3.py
```

**Override the assumed role name:**
```bash
python3 aws_dashboard3.py --role YourRoleName
```

**Legacy version:**
```bash
python3 aws_dashboard.py
```

**Prerequisites:**
- AWS credentials configured (`aws configure` or environment variables)
- Must run from AWS Organization management account for multi-account access
- IAM role must exist in child accounts with required permissions

## Key Architecture

### Cross-Account Access Pattern
- Discovers accounts via `organizations:ListAccounts`
- Assumes role in each child account using `sts:AssumeRole`
- Default role: `Operative-FullAccess` (configurable via `--role` flag)
- Account-specific role overrides defined in `ACCOUNT_ROLE_OVERRIDES` dict (aws_dashboard3.py only)

### Resource Inventory Approach
- Regions fetched once per account and cached
- Pagination handled via boto3 paginators for all resources
- S3 treated as global (single ListBuckets call per account)
- EC2, RDS, and Load Balancers iterated across all enabled regions

### TUI Structure
- Built with Python `curses` library
- Color-coded display (cyan headers, green for running resources, red for errors)
- Keyboard navigation: arrow keys, Enter, Q/ESC, S for CSV export
- Three main components: menu system, scrollable pager, input boxes

### Error Handling
- `aws_dashboard3.py` has enhanced error handling with debug logging
- Role assumption failures tracked and displayed to user
- Graceful degradation: falls back to current account if Organizations access fails
- All AWS API errors caught and logged to `~/aws_dashboard_debug.log`

## File Differences

- **aws_dashboard.py**: Original implementation with basic error handling
- **aws_dashboard3.py**: Enhanced version with:
  - Debug logging to `~/aws_dashboard_debug.log`
  - Account-specific role override support via `ACCOUNT_ROLE_OVERRIDES`
  - Better error messages showing which accounts were skipped
  - Startup diagnostic screen showing loaded accounts
  - Comprehensive exception handling for network errors

## Export Functionality

CSV exports saved to `~/aws_dashboard_exports/` with timestamp:
- Format: `{resource_type}_inventory_{YYYY-MM-DD_HH-MM-SS}.csv`
- Example: `ec2_inventory_2026-04-08_14-30-15.csv`

## API Call Efficiency

Operations are optimized to minimize AWS API calls:
- Account discovery: 1 call (organizations:ListAccounts)
- Per account: 1 role assumption + 1 region discovery
- Per region per account: 1 call per resource type (EC2/RDS/LB)
- S3: 1 ListBuckets + 1 GetBucketLocation per bucket
- Search operations filter at API level to reduce data transfer

## Customization Points

**EC2 Tags** (`EC2_TAGS` list): Defines which EC2 tags to collect during inventory
**Role Configuration**: Modify `ROLE_NAME` or `ACCOUNT_ROLE_OVERRIDES` for custom IAM role assumptions
**Color Scheme**: `init_colors()` function defines curses color pairs for TUI elements
**Export Directory**: Change `RESULTS_DIR` to customize CSV export location
