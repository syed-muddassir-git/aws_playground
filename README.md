# AWS Multi-Account Dashboard

Interactive Terminal UI dashboard for inventorying and searching AWS resources across all accounts in an AWS Organization.

## Features

- **Multi-Account Support**: Auto-discovers all accounts in your AWS Organization
- **Resource Inventory**: EC2, RDS, S3, Load Balancers
- **Resource Search**: Find specific resources by ID/name across all accounts
- **CSV Export**: Export results with timestamps
- **Interactive TUI**: Color-coded, arrow-key navigation

## Quick Start

### 1. Installation

```bash
# Clone and navigate
git clone <repository-url>
cd aws_playground

# Setup virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure AWS Credentials

**Option A - AWS CLI (Recommended):**
```bash
aws configure
```

**Option B - Environment Variables:**
```bash
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_DEFAULT_REGION="us-east-1"
```

**Verify:**
```bash
aws sts get-caller-identity
```

### 3. Run

```bash
python3 aws_dashboard3.py
```

**Custom IAM role:**
```bash
python3 aws_dashboard3.py --role YourRoleName
```

## Navigation

- **↑/↓** - Navigate
- **Enter** - Select
- **Q/ESC** - Back/Exit
- **S** - Save to CSV

## Prerequisites

- Python 3.6+
- AWS Organization management account access
- IAM role in child accounts (default: `Operative-FullAccess`)

## Configuration

**Account-specific roles** (`aws_dashboard3.py`):
```python
ACCOUNT_ROLE_OVERRIDES = {
    "123456789012": "CustomRoleName",
}
```

**EC2 tags to collect**:
```python
EC2_TAGS = ["Name", "Application", "Environment", ...]
```

**CSV export location**: `~/aws_dashboard_exports/`

## Versions

- **aws_dashboard3.py** (Recommended) - Enhanced error handling, debug logging
- **aws_dashboard.py** - Original version

## Troubleshooting

**"Organizations access denied"**
- Run from AWS Organization management account
- Ensure `organizations:ListAccounts` permission

**"Role assumption failed"**
- Verify IAM role exists in child accounts
- Check trust policy allows management account
- Use `--role` flag if using different role name
- Check debug log: `~/aws_dashboard_debug.log`

**No resources found**
- Verify assumed role has required permissions (EC2, RDS, S3, ELB)
- Check resources exist in those accounts/regions

## Author

Syed Muddassir
