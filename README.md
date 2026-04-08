# AWS Multi-Account Dashboard

Interactive Terminal UI for inventorying and searching AWS resources across multiple accounts in an AWS Organization.

**🆓 Works with LocalStack - completely free for testing and learning!**

## Features

- Multi-account AWS inventory (EC2, RDS, S3, Load Balancers)
- Cross-region resource search by ID or name
- CSV export with timestamps
- Interactive TUI with keyboard navigation
- Debug logging for troubleshooting
- Works with LocalStack (free) or real AWS

## Quick Start

### Option 1: LocalStack (Free, No AWS Account Needed) 🎉

Perfect for learning and testing without any AWS costs!

```bash
# 1. Install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Start LocalStack (requires Docker)
docker-compose -f docker-compose.localstack.yml up -d

# 3. Create sample data (3 EC2 instances + 3 S3 buckets)
./setup_localstack_data.sh

# 4. Run dashboard
./run_with_localstack.sh
```

**What you get:**
- 3 EC2 instances (WebServer-1, Database-Server)
- 3 S3 buckets (my-app-data, backup-bucket, logs-storage)
- Full inventory and search capabilities

**LocalStack Free Tier Limitations:**
- ✅ EC2, S3, ELB - Fully supported
- ❌ RDS - Pro feature only (not included in sample data)
- ❌ AWS Organizations - Pro feature (dashboard uses single-account mode)

### Option 2: Real AWS

```bash
# 1. Install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Configure AWS credentials
aws configure
# You'll be prompted for:
#   - AWS Access Key ID
#   - AWS Secret Access Key
#   - Default region (e.g., us-east-1)

# 3. Run dashboard
source venv/bin/activate
python3 aws_dashboard3.py
```

**Custom IAM role:**
```bash
python3 aws_dashboard3.py --role YourRoleName
```

**Use aws_dashboard.py (original version):**
```bash
python3 aws_dashboard.py
```

## Navigation

| Key | Action |
|-----|--------|
| **↑/↓** | Navigate menus |
| **Enter** | Select item |
| **Q/ESC** | Back/Exit |
| **S** | Save results to CSV |
| **PgUp/PgDn** | Scroll through results |

## Configuration

### Role Overrides

For accounts requiring different IAM role names, edit `aws_dashboard3.py`:

```python
ACCOUNT_ROLE_OVERRIDES = {
    "123456789012": "CustomRoleName",
    "987654321098": "AnotherRole",
}
```

### EC2 Tags to Collect

Customize which EC2 tags appear in inventory by editing `aws_dashboard3.py`:

```python
EC2_TAGS = [
    "Name", "Application", "Environment",
    "Owner", "CostCenter", "Project"
]
```

### Output Locations

- **CSV exports:** `~/aws_dashboard_exports/`
- **Debug log:** `~/aws_dashboard_debug.log` (aws_dashboard3.py only)

## Prerequisites

### For LocalStack
- Docker installed and running
- Python 3.6+
- ~500MB disk space

### For Real AWS
- Python 3.6+
- AWS account (free tier works!)
- AWS credentials configured
- IAM permissions:
  - `sts:GetCallerIdentity`, `sts:AssumeRole`
  - `organizations:ListAccounts` (for multi-account)
  - `ec2:DescribeInstances`, `ec2:DescribeRegions`, `ec2:DescribeVolumes`
  - `rds:DescribeDBInstances`
  - `s3:ListBuckets`, `s3:GetBucketLocation`, `s3:GetBucket*`
  - `elasticloadbalancing:DescribeLoadBalancers`, `elasticloadbalancing:DescribeTargetGroups`

## Troubleshooting

### LocalStack Issues

**"Connection refused" or LocalStack not responding:**
```bash
# Check if LocalStack is running
docker ps | grep localstack

# Start LocalStack
docker-compose -f docker-compose.localstack.yml up -d

# Check logs
docker logs aws_dashboard_localstack
```

**No resources showing up in dashboard:**
```bash
# Re-create sample data
./setup_localstack_data.sh

# Verify resources exist
docker exec aws_dashboard_localstack awslocal s3 ls
```

**Stop LocalStack:**
```bash
docker-compose -f docker-compose.localstack.yml down
```

### Real AWS Issues

**"AWS credentials not found":**
```bash
# Option 1: Use AWS CLI
aws configure

# Option 2: Environment variables
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_DEFAULT_REGION="us-east-1"

# Verify credentials
aws sts get-caller-identity
```

**"Organizations access denied":**
- Run from AWS Organization **management account**
- Ensure IAM permissions for `organizations:ListAccounts`
- Dashboard automatically falls back to single-account mode if unavailable

**"Role assumption failed":**
- Verify IAM role exists in child accounts (check `ROLE_NAME` in code)
- Check role trust policy allows management account to assume it
- Use `--role` flag to specify correct role name
- Check debug log: `~/aws_dashboard_debug.log`

**Virtual environment issues:**
```bash
# Always activate venv before running
source venv/bin/activate

# Verify boto3 is installed
pip list | grep boto3

# Reinstall if needed
pip install -r requirements.txt
```

## Project Structure

```
aws_playground/
├── aws_dashboard3.py              # Enhanced dashboard (recommended)
├── aws_dashboard.py               # Original dashboard
├── localstack_config.py           # Boto3 patching for LocalStack
├── setup_localstack_data.py       # Creates sample resources
├── setup_localstack_data.sh       # Shell wrapper
├── run_with_localstack.sh         # LocalStack launcher
├── docker-compose.localstack.yml  # LocalStack Docker config
├── requirements.txt               # Python dependencies
├── CLAUDE.md                      # Documentation for Claude Code
└── README.md                      # This file
```

## Differences Between Versions

| Feature | aws_dashboard.py | aws_dashboard3.py |
|---------|-----------------|-------------------|
| Core functionality | ✅ | ✅ |
| Debug logging | ❌ | ✅ |
| Startup diagnostics | ❌ | ✅ |
| Enhanced error messages | ❌ | ✅ |
| Account-specific role overrides | ❌ | ✅ |
| Failed account tracking | ❌ | ✅ |

**Recommendation:** Use `aws_dashboard3.py` for better debugging and error handling.

## Author

Syed Muddassir

## License

See repository license file.
