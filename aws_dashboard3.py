#!/usr/bin/env python3
"""
AWS Multi-Account Dashboard
Author: Syed Muddassir
Description: Interactive TUI dashboard to inventory and search AWS resources
             across all accounts in an AWS Organization. Runs from the master
             (management) account using cross-account IAM role assumption.

API Call Budget (approximate per action):
  - Account discovery     :  1 call  (organizations:ListAccounts)
  - Role assumption       :  1 call per account (sts:AssumeRole)
  - Region discovery      :  1 call per account (ec2:DescribeRegions)
  - EC2 Inventory         :  1 call per region per account (ec2:DescribeInstances)
  - RDS Inventory         :  1 call per region per account (rds:DescribeDBInstances)
  - S3 Inventory          :  1 call total + 1 per bucket for location (s3:ListBuckets + GetBucketLocation)
  - Load Balancer Inv.    :  2 calls per region per account (elbv2 + elb classic)
  - EC2 Search by ID      :  1 call per region per account (ec2:DescribeInstances with filter)
  - RDS Search by ID      :  1 call per region per account (rds:DescribeDBInstances with filter)
  - S3 Search by name     :  1 call total (s3:ListBuckets) + 1 for location
  - LB Search by name     :  1 call per region per account (elbv2:DescribeLoadBalancers with name filter)

Optimization notes:
  - Regions are fetched once per account and reused across resource types.
  - S3 is global — only one ListBuckets call needed per account.
  - Pagination is handled via boto3 paginators to avoid missed resources.
  - Search short-circuits as soon as the resource is found.
"""

import boto3
import curses
import sys
import csv
import os
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple
from botocore.exceptions import ClientError, NoCredentialsError, EndpointConnectionError, ConnectTimeoutError

# Catch-all for AWS call failures (API errors + unreachable endpoints)
AWSError = (ClientError, EndpointConnectionError, ConnectTimeoutError, ConnectionError, OSError)

def _err(e: Exception) -> str:
    """Safely extract a short error string from any AWS/network exception."""
    if hasattr(e, "response") and e.response:
        code = e.response.get("Error", {}).get("Code", "UnknownCode")
        msg  = e.response.get("Error", {}).get("Message", "")
        return f"{code}: {msg}"
    return type(e).__name__ + ": " + str(e)

# ─────────────────────────── CONFIG ─────────────────────────────────────────

# Default role assumed in child accounts.
# Override at runtime:  python3 aws_dashboard.py --role MyRoleName
ROLE_NAME = "Operative-FullAccess"

# Per-account role overrides. Accounts listed here will use their specific role
# instead of ROLE_NAME. Matches your original script exactly.
ACCOUNT_ROLE_OVERRIDES = {
    "150898802241": "SM-Admin-Access",
    "573853700727": "Operative_FullAccess",
    "669676298473": "Operative_FullAccess",
}

SESSION_NAME  = "AWSdashboardSession"
RESULTS_DIR   = os.path.expanduser("~/aws_dashboard_exports")
DEBUG_LOG     = os.path.expanduser("~/aws_dashboard_debug.log")

def _log(msg: str):
    """Write a timestamped line to the debug log. Safe to call inside curses."""
    os.makedirs(os.path.dirname(DEBUG_LOG) if os.path.dirname(DEBUG_LOG) else ".", exist_ok=True)
    with open(DEBUG_LOG, "a") as fh:
        fh.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")

# Parse --role override from CLI args before curses takes over
_cli_role = None
if "--role" in sys.argv:
    _idx = sys.argv.index("--role")
    if _idx + 1 < len(sys.argv):
        _cli_role = sys.argv[_idx + 1]
if _cli_role:
    ROLE_NAME = _cli_role

# Tags to collect for EC2 inventory
EC2_TAGS = [
    "Name", "Application", "Budget_Code", "Customer", "Environment",
    "Environment_Type", "Function", "Grade", "Layer", "Tenancy",
    "Usage", "LifeCycle", "Product", "ManagedBy"
]

# ─────────────────────────── COLOURS ────────────────────────────────────────

def init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN,    -1)   # header / title
    curses.init_pair(2, curses.COLOR_GREEN,   -1)   # selected item
    curses.init_pair(3, curses.COLOR_YELLOW,  -1)   # labels / keys
    curses.init_pair(4, curses.COLOR_WHITE,   -1)   # normal text
    curses.init_pair(5, curses.COLOR_RED,     -1)   # errors
    curses.init_pair(6, curses.COLOR_MAGENTA, -1)   # account names
    curses.init_pair(7, curses.COLOR_BLACK,   curses.COLOR_CYAN)  # highlight bar


HDR  = lambda: curses.color_pair(1) | curses.A_BOLD
SEL  = lambda: curses.color_pair(7) | curses.A_BOLD
LBL  = lambda: curses.color_pair(3)
NRM  = lambda: curses.color_pair(4)
ERR  = lambda: curses.color_pair(5)
ACC  = lambda: curses.color_pair(6)


# ─────────────────────────── TUI HELPERS ────────────────────────────────────

def draw_border(win):
    win.box()

def draw_header(win, title: str):
    h, w = win.getmaxyx()
    banner = f"  AWS Multi-Account Dashboard  |  {title}  "
    win.addstr(0, max(0, (w - len(banner)) // 2), banner[:w-1], HDR())

def safe_addstr(win, y, x, text, attr=0):
    """Write text without crashing on out-of-bounds."""
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x < 0 or x >= w:
        return
    max_len = w - x - 1
    if max_len <= 0:
        return
    try:
        win.addstr(y, x, str(text)[:max_len], attr)
    except curses.error:
        pass

def menu(stdscr, title: str, options: list, subtitle: str = "") -> int:
    """
    Arrow-key navigable menu. Returns selected index or -1 on ESC/q.
    """
    curses.curs_set(0)
    current = 0
    while True:
        stdscr.clear()
        draw_border(stdscr)
        draw_header(stdscr, title)
        h, w = stdscr.getmaxyx()

        if subtitle:
            safe_addstr(stdscr, 2, 3, subtitle, LBL())

        start_y = 4
        for i, opt in enumerate(options):
            y = start_y + i
            if y >= h - 2:
                break
            prefix = "  > " if i == current else "    "
            attr = SEL() if i == current else NRM()
            safe_addstr(stdscr, y, 2, f"{prefix}{opt}", attr)

        safe_addstr(stdscr, h - 2, 3,
                    "↑/↓ Navigate   ENTER Select   Q/ESC Back", LBL())
        stdscr.refresh()

        key = stdscr.getch()
        if key == curses.KEY_UP and current > 0:
            current -= 1
        elif key == curses.KEY_DOWN and current < len(options) - 1:
            current += 1
        elif key in (curses.KEY_ENTER, 10, 13):
            return current
        elif key in (ord('q'), ord('Q'), 27):
            return -1


def pager(stdscr, title: str, lines: list):
    """Scrollable text pager for results."""
    curses.curs_set(0)
    offset = 0
    h, w = stdscr.getmaxyx()
    visible = h - 5

    while True:
        stdscr.clear()
        draw_border(stdscr)
        draw_header(stdscr, title)
        h, w = stdscr.getmaxyx()
        visible = h - 5

        for i in range(visible):
            idx = offset + i
            if idx >= len(lines):
                break
            row_y = 2 + i
            line_text, line_attr = lines[idx] if isinstance(lines[idx], tuple) else (lines[idx], NRM())
            safe_addstr(stdscr, row_y, 2, str(line_text)[:w-4], line_attr)

        pct = int((offset + visible) / max(len(lines), 1) * 100)
        safe_addstr(stdscr, h - 2, 3,
                    f"↑/↓/PgUp/PgDn Scroll   S Save CSV   Q Back   [{pct}%]", LBL())
        stdscr.refresh()

        key = stdscr.getch()
        if key in (ord('q'), ord('Q'), 27):
            return None
        elif key == curses.KEY_UP and offset > 0:
            offset -= 1
        elif key == curses.KEY_DOWN and offset < len(lines) - visible:
            offset += 1
        elif key == curses.KEY_PPAGE:
            offset = max(0, offset - visible)
        elif key == curses.KEY_NPAGE:
            offset = min(len(lines) - visible, offset + visible)
        elif key in (ord('s'), ord('S')):
            return "save"


def loading(stdscr, msg: str):
    """Show a simple loading message."""
    h, w = stdscr.getmaxyx()
    stdscr.clear()
    draw_border(stdscr)
    draw_header(stdscr, "Working...")
    safe_addstr(stdscr, h // 2, max(3, (w - len(msg)) // 2), msg, LBL())
    safe_addstr(stdscr, h // 2 + 1, 3, "Please wait...", NRM())
    stdscr.refresh()


def input_box(stdscr, prompt: str) -> str:
    """Single-line text input."""
    curses.curs_set(1)
    curses.echo()
    h, w = stdscr.getmaxyx()
    stdscr.clear()
    draw_border(stdscr)
    draw_header(stdscr, "Search")
    safe_addstr(stdscr, h // 2 - 1, 3, prompt, LBL())
    safe_addstr(stdscr, h // 2, 3, "> ", NRM())
    stdscr.refresh()
    try:
        raw = stdscr.getstr(h // 2, 5, 60)
        val = raw.decode("utf-8").strip()
    except Exception:
        val = ""
    curses.noecho()
    curses.curs_set(0)
    return val


# ─────────────────────────── AWS HELPERS ────────────────────────────────────

# Tracks role assumption failures for display in the summary
_role_failures: List[str] = []

def get_session(account_id: str, caller_id: str, account_name: str = "") -> Optional[boto3.Session]:
    """Return a boto3 Session for the target account (assume role if needed)."""
    if account_id == caller_id:
        _log(f"get_session: {account_id} is caller account, using default session")
        return boto3.Session()
    role = ACCOUNT_ROLE_OVERRIDES.get(account_id, ROLE_NAME)
    role_arn = f"arn:aws:iam::{account_id}:role/{role}"
    _log(f"get_session: assuming {role_arn}")
    try:
        sts = boto3.client("sts")
        creds = sts.assume_role(RoleArn=role_arn, RoleSessionName=SESSION_NAME)["Credentials"]
        _log(f"get_session: SUCCESS {account_id}")
        return boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )
    except AWSError as e:
        label = account_name or account_id
        msg = f"SKIP {label} ({account_id}) role={role} => {_err(e)}"
        _log(f"get_session: FAILED {msg}")
        _role_failures.append(msg)
        return None
    except Exception as e:
        _log(f"get_session: UNEXPECTED ERROR {account_id}: {_err(e)}")
        return None


def list_org_accounts() -> List[dict]:
    """
    Fetch all active accounts from AWS Organizations.
    API calls: 1 (+ pagination if >20 accounts)
    """
    org = boto3.client("organizations")
    paginator = org.get_paginator("list_accounts")
    accounts = []
    for page in paginator.paginate():
        for acct in page["Accounts"]:
            if acct["Status"] == "ACTIVE":
                accounts.append({"id": acct["Id"], "name": acct["Name"]})
    _log(f"list_org_accounts: found {len(accounts)} active accounts")
    for a in accounts:
        _log(f"  account: {a['id']}  {a['name']}")
    return accounts


def get_enabled_regions(session: boto3.Session) -> List[str]:
    """
    API calls: 1 (ec2:DescribeRegions)
    Returns empty list on failure (logged).
    """
    try:
        ec2 = session.client("ec2")
        regions = [r["RegionName"] for r in ec2.describe_regions(AllRegions=False)["Regions"]]
        _log(f"get_enabled_regions: found {len(regions)} regions")
        return regions
    except AWSError as e:
        _log(f"get_enabled_regions: FAILED {_err(e)}")
        return []
    except Exception as e:
        _log(f"get_enabled_regions: UNEXPECTED {e}")
        return []


def tags_to_dict(tag_list: list) -> dict:
    return {t["Key"]: t["Value"] for t in (tag_list or [])}


# ─────────────────────────── INVENTORY FUNCTIONS ────────────────────────────

def inventory_ec2(stdscr, accounts: list, caller_id: str) -> List[dict]:
    """
    EC2 inventory across all accounts + regions.
    API calls: accounts x regions x 1 DescribeInstances (paginated)
    """
    results = []
    for acct in accounts:
        role_used = ACCOUNT_ROLE_OVERRIDES.get(acct["id"], ROLE_NAME)
        loading(stdscr, f"EC2  {acct['id']} ({acct['name']})  role={role_used}")
        session = get_session(acct["id"], caller_id, acct["name"])
        if not session:
            continue
        regions = get_enabled_regions(session)
        if not regions:
            _log(f"inventory_ec2: no regions for {acct['id']}, skipping")
            continue
        for region in regions:
            try:
                ec2 = session.client("ec2", region_name=region)
                paginator = ec2.get_paginator("describe_instances")
                for page in paginator.paginate():
                    for res in page["Reservations"]:
                        for inst in res["Instances"]:
                            t = tags_to_dict(inst.get("Tags", []))
                            results.append({
                                "AccountId": acct["id"],
                                "AccountName": acct["name"],
                                "Region": region,
                                "InstanceId": inst["InstanceId"],
                                "State": inst["State"]["Name"],
                                "Type": inst["InstanceType"],
                                "PrivateIP": inst.get("PrivateIpAddress", "N/A"),
                                "PublicIP": inst.get("PublicIpAddress", "N/A"),
                                "LaunchTime": inst["LaunchTime"].strftime("%Y-%m-%d"),
                                "OS": inst.get("Platform", "Linux/Unix"),
                                "Name": t.get("Name", "N/A"),
                                "Environment": t.get("Environment", "N/A"),
                                "Application": t.get("Application", "N/A"),
                            })
            except AWSError as e:
                _log(f"inventory_ec2: {acct['id']} {region} => {_err(e)}")
                continue
        _log(f"inventory_ec2: {acct['id']} done, total so far={len(results)}")
    return results


def inventory_rds(stdscr, accounts: list, caller_id: str) -> List[dict]:
    """
    RDS inventory across all accounts + regions.
    API calls: accounts x regions x 1 DescribeDBInstances (paginated)
    """
    results = []
    for acct in accounts:
        loading(stdscr, f"RDS  {acct['id']} ({acct['name']})")
        session = get_session(acct["id"], caller_id, acct["name"])
        if not session:
            continue
        regions = get_enabled_regions(session)
        if not regions:
            continue
        for region in regions:
            try:
                rds = session.client("rds", region_name=region)
                paginator = rds.get_paginator("describe_db_instances")
                for page in paginator.paginate():
                    for db in page["DBInstances"]:
                        results.append({
                            "AccountId": acct["id"],
                            "AccountName": acct["name"],
                            "Region": region,
                            "DBIdentifier": db["DBInstanceIdentifier"],
                            "Engine": f"{db['Engine']} {db.get('EngineVersion', '')}",
                            "Class": db["DBInstanceClass"],
                            "Status": db["DBInstanceStatus"],
                            "MultiAZ": str(db.get("MultiAZ", False)),
                            "Storage": f"{db.get('AllocatedStorage', 'N/A')} GiB",
                            "Endpoint": db.get("Endpoint", {}).get("Address", "N/A"),
                        })
            except AWSError as e:
                _log(f"inventory_rds: {acct['id']} {region} => {_err(e)}")
                continue
    return results


def inventory_s3(stdscr, accounts: list, caller_id: str) -> List[dict]:
    """
    S3 inventory across all accounts.
    API calls: accounts x 1 ListBuckets + accounts x buckets x 1 GetBucketLocation
    S3 is global so no region loop needed.
    """
    results = []
    for acct in accounts:
        loading(stdscr, f"S3   {acct['id']} ({acct['name']})")
        session = get_session(acct["id"], caller_id, acct["name"])
        if not session:
            continue
        try:
            s3 = session.client("s3")
            buckets = s3.list_buckets().get("Buckets", [])
            _log(f"inventory_s3: {acct['id']} has {len(buckets)} buckets")
            for b in buckets:
                try:
                    loc = s3.get_bucket_location(Bucket=b["Name"])
                    region = loc["LocationConstraint"] or "us-east-1"
                except AWSError:
                    region = "unknown"
                results.append({
                    "AccountId": acct["id"],
                    "AccountName": acct["name"],
                    "BucketName": b["Name"],
                    "Region": region,
                    "CreatedOn": b["CreationDate"].strftime("%Y-%m-%d"),
                })
        except AWSError as e:
            _log(f"inventory_s3: {acct['id']} => {_err(e)}")
            continue
    return results


def inventory_lb(stdscr, accounts: list, caller_id: str) -> List[dict]:
    """
    Load Balancer inventory (ALB/NLB + Classic ELB) across all accounts + regions.
    API calls: accounts x regions x 2 (elbv2 + elb classic)
    """
    results = []
    for acct in accounts:
        loading(stdscr, f"LB   {acct['id']} ({acct['name']})")
        session = get_session(acct["id"], caller_id, acct["name"])
        if not session:
            continue
        regions = get_enabled_regions(session)
        if not regions:
            continue
        for region in regions:
            # ALB / NLB
            try:
                elbv2 = session.client("elbv2", region_name=region)
                paginator = elbv2.get_paginator("describe_load_balancers")
                for page in paginator.paginate():
                    for lb in page["LoadBalancers"]:
                        results.append({
                            "AccountId": acct["id"],
                            "AccountName": acct["name"],
                            "Region": region,
                            "Name": lb["LoadBalancerName"],
                            "Type": lb["Type"],
                            "Scheme": lb["Scheme"],
                            "State": lb["State"]["Code"],
                            "DNS": lb["DNSName"],
                        })
            except AWSError as e:
                _log(f"inventory_lb elbv2: {acct['id']} {region} => {_err(e)}")
            # Classic ELB
            try:
                elb = session.client("elb", region_name=region)
                paginator = elb.get_paginator("describe_load_balancers")
                for page in paginator.paginate():
                    for lb in page["LoadBalancerDescriptions"]:
                        targets = ", ".join(
                            i["InstanceId"] for i in lb.get("Instances", [])
                        ) or "N/A"
                        results.append({
                            "AccountId": acct["id"],
                            "AccountName": acct["name"],
                            "Region": region,
                            "Name": lb["LoadBalancerName"],
                            "Type": "classic",
                            "Scheme": lb.get("Scheme", "N/A"),
                            "State": "active",
                            "DNS": lb["DNSName"],
                            "Targets": targets,
                        })
            except AWSError as e:
                _log(f"inventory_lb classic: {acct['id']} {region} => {_err(e)}")
    return results


# ─────────────────────────── SEARCH FUNCTIONS ───────────────────────────────

def search_ec2(stdscr, resource_id: str, accounts: list, caller_id: str) -> List[dict]:
    """
    Search EC2 by instance-id across all accounts.
    API calls: accounts × regions × 1 DescribeInstances (with filter — minimal data returned)
    Short-circuits to next account once found.
    """
    results = []
    for acct in accounts:
        loading(stdscr, f"Searching EC2 in {acct['name']} ({acct['id']})")
        session = get_session(acct["id"], caller_id, acct["name"])
        if not session:
            continue
        try:
            regions = get_enabled_regions(session)
        except AWSError:
            continue
        for region in regions:
            try:
                ec2 = session.client("ec2", region_name=region)
                resp = ec2.describe_instances(
                    Filters=[{"Name": "instance-id", "Values": [resource_id]}]
                )
                for res in resp["Reservations"]:
                    for inst in res["Instances"]:
                        t = tags_to_dict(inst.get("Tags", []))
                        # Fetch attached volumes
                        vols = ec2.describe_volumes(
                            Filters=[{"Name": "attachment.instance-id", "Values": [resource_id]}]
                        )
                        vol_info = ", ".join(
                            f"{v['VolumeId']} ({v['Size']}GiB {v['VolumeType']})"
                            for v in vols["Volumes"]
                        ) or "N/A"

                        results.append({
                            "field": "FOUND",
                            "Account": f"{acct['name']} ({acct['id']})",
                            "Region": region,
                            "InstanceId": inst["InstanceId"],
                            "State": inst["State"]["Name"],
                            "Type": inst["InstanceType"],
                            "PrivateIP": inst.get("PrivateIpAddress", "N/A"),
                            "PublicIP": inst.get("PublicIpAddress", "N/A"),
                            "LaunchTime": inst["LaunchTime"].strftime("%Y-%m-%d %H:%M UTC"),
                            "OS": inst.get("Platform", "Linux/Unix"),
                            "KeyName": inst.get("KeyName", "N/A"),
                            "VPC": inst.get("VpcId", "N/A"),
                            "Subnet": inst.get("SubnetId", "N/A"),
                            "Volumes": vol_info,
                            **{tag: t.get(tag, "N/A") for tag in EC2_TAGS},
                        })
            except AWSError:
                continue
    return results


def search_rds(stdscr, resource_id: str, accounts: list, caller_id: str) -> List[dict]:
    """
    Search RDS by DB identifier across all accounts.
    API calls: accounts × regions × 1 DescribeDBInstances (with DBInstanceIdentifier filter)
    """
    results = []
    for acct in accounts:
        loading(stdscr, f"Searching RDS in {acct['name']} ({acct['id']})")
        session = get_session(acct["id"], caller_id, acct["name"])
        if not session:
            continue
        try:
            regions = get_enabled_regions(session)
        except AWSError:
            continue
        for region in regions:
            try:
                rds = session.client("rds", region_name=region)
                resp = rds.describe_db_instances(DBInstanceIdentifier=resource_id)
                for db in resp["DBInstances"]:
                    results.append({
                        "Account": f"{acct['name']} ({acct['id']})",
                        "Region": region,
                        "DBIdentifier": db["DBInstanceIdentifier"],
                        "Engine": f"{db['Engine']} {db.get('EngineVersion', '')}",
                        "Class": db["DBInstanceClass"],
                        "Status": db["DBInstanceStatus"],
                        "MultiAZ": str(db.get("MultiAZ", False)),
                        "Storage": f"{db.get('AllocatedStorage', 'N/A')} GiB",
                        "StorageType": db.get("StorageType", "N/A"),
                        "Endpoint": db.get("Endpoint", {}).get("Address", "N/A"),
                        "Port": str(db.get("Endpoint", {}).get("Port", "N/A")),
                        "VPC": db.get("DBSubnetGroup", {}).get("VpcId", "N/A"),
                        "BackupRetention": f"{db.get('BackupRetentionPeriod', 0)} days",
                        "Encrypted": str(db.get("StorageEncrypted", False)),
                    })
            except AWSError:
                continue
    return results


def search_s3(stdscr, bucket_name: str, accounts: list, caller_id: str) -> List[dict]:
    """
    Search S3 bucket by name across all accounts.
    API calls: accounts × 1 ListBuckets + 1 GetBucketLocation + several metadata calls
    """
    results = []
    for acct in accounts:
        loading(stdscr, f"Searching S3 in {acct['name']} ({acct['id']})")
        session = get_session(acct["id"], caller_id, acct["name"])
        if not session:
            continue
        try:
            s3 = session.client("s3")
            buckets = s3.list_buckets().get("Buckets", [])
            match = next((b for b in buckets if b["Name"] == bucket_name), None)
            if not match:
                continue
            loc = s3.get_bucket_location(Bucket=bucket_name)
            region = loc["LocationConstraint"] or "us-east-1"
            # Versioning
            try:
                ver = s3.get_bucket_versioning(Bucket=bucket_name)
                versioning = ver.get("Status", "Disabled")
            except AWSError:
                versioning = "Unknown"
            # Encryption
            try:
                enc = s3.get_bucket_encryption(Bucket=bucket_name)
                encryption = enc["ServerSideEncryptionConfiguration"]["Rules"][0] \
                    ["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"]
            except AWSError:
                encryption = "None"
            # Tags
            try:
                tag_resp = s3.get_bucket_tagging(Bucket=bucket_name)
                btags = tags_to_dict(tag_resp.get("TagSet", []))
            except AWSError:
                btags = {}

            results.append({
                "Account": f"{acct['name']} ({acct['id']})",
                "BucketName": bucket_name,
                "Region": region,
                "CreatedOn": match["CreationDate"].strftime("%Y-%m-%d"),
                "Versioning": versioning,
                "Encryption": encryption,
                **{f"Tag:{k}": v for k, v in btags.items()},
            })
        except AWSError:
            continue
    return results


def search_lb(stdscr, lb_name: str, accounts: list, caller_id: str) -> List[dict]:
    """
    Search Load Balancer by name across all accounts.
    API calls: accounts × regions × 2 (elbv2 + classic) with name filter
    """
    results = []
    for acct in accounts:
        loading(stdscr, f"Searching LB in {acct['name']} ({acct['id']})")
        session = get_session(acct["id"], caller_id, acct["name"])
        if not session:
            continue
        try:
            regions = get_enabled_regions(session)
        except AWSError:
            continue
        for region in regions:
            # ALB/NLB
            try:
                elbv2 = session.client("elbv2", region_name=region)
                resp = elbv2.describe_load_balancers(Names=[lb_name])
                for lb in resp["LoadBalancers"]:
                    # Get target groups
                    tg_resp = elbv2.describe_target_groups(LoadBalancerArn=lb["LoadBalancerArn"])
                    tg_names = ", ".join(
                        tg["TargetGroupName"] for tg in tg_resp.get("TargetGroups", [])
                    ) or "N/A"
                    results.append({
                        "Account": f"{acct['name']} ({acct['id']})",
                        "Region": region,
                        "Name": lb["LoadBalancerName"],
                        "Type": lb["Type"],
                        "Scheme": lb["Scheme"],
                        "State": lb["State"]["Code"],
                        "DNS": lb["DNSName"],
                        "VPC": lb.get("VpcId", "N/A"),
                        "AvailabilityZones": ", ".join(
                            az["ZoneName"] for az in lb.get("AvailabilityZones", [])
                        ),
                        "TargetGroups": tg_names,
                    })
            except AWSError:
                pass
            # Classic ELB
            try:
                elb = session.client("elb", region_name=region)
                resp = elb.describe_load_balancers(LoadBalancerNames=[lb_name])
                for lb in resp["LoadBalancerDescriptions"]:
                    instances = ", ".join(
                        i["InstanceId"] for i in lb.get("Instances", [])
                    ) or "N/A"
                    hc = lb.get("HealthCheck", {})
                    results.append({
                        "Account": f"{acct['name']} ({acct['id']})",
                        "Region": region,
                        "Name": lb["LoadBalancerName"],
                        "Type": "classic",
                        "Scheme": lb.get("Scheme", "N/A"),
                        "State": "active",
                        "DNS": lb["DNSName"],
                        "VPC": lb.get("VPCId", "N/A"),
                        "Instances": instances,
                        "HealthCheck": hc.get("Target", "N/A"),
                    })
            except AWSError:
                pass
    return results


# ─────────────────────────── FORMATTERS ─────────────────────────────────────

def format_ec2_rows(data: List[dict]) -> List[tuple]:
    lines = []
    if not data:
        return [("  No EC2 instances found.", ERR())]
    header = f"{'AccountId':<14} {'Region':<16} {'InstanceId':<22} {'State':<10} {'Type':<14} {'PrivateIP':<16} {'Name':<30}"
    lines.append((header, HDR()))
    lines.append(("─" * len(header), LBL()))
    for r in data:
        state_attr = curses.color_pair(2) if r["State"] == "running" else curses.color_pair(5)
        line = (
            f"  {r['AccountId']:<12} {r['Region']:<16} {r['InstanceId']:<22} "
            f"{r['State']:<10} {r['Type']:<14} {r['PrivateIP']:<16} {r['Name']:<30}"
        )
        lines.append((line, state_attr if r["State"] in ("running", "stopped") else NRM()))
    lines.append(("", NRM()))
    lines.append((f"  Total: {len(data)} instances", LBL()))
    return lines


def format_rds_rows(data: List[dict]) -> List[tuple]:
    lines = []
    if not data:
        return [("  No RDS instances found.", ERR())]
    header = f"{'AccountId':<14} {'Region':<16} {'DBIdentifier':<30} {'Engine':<20} {'Class':<16} {'Status':<12}"
    lines.append((header, HDR()))
    lines.append(("─" * len(header), LBL()))
    for r in data:
        line = (
            f"  {r['AccountId']:<12} {r['Region']:<16} {r['DBIdentifier']:<30} "
            f"{r['Engine']:<20} {r['Class']:<16} {r['Status']:<12}"
        )
        lines.append((line, NRM()))
    lines.append(("", NRM()))
    lines.append((f"  Total: {len(data)} DB instances", LBL()))
    return lines


def format_s3_rows(data: List[dict]) -> List[tuple]:
    lines = []
    if not data:
        return [("  No S3 buckets found.", ERR())]
    header = f"{'AccountId':<14} {'BucketName':<50} {'Region':<20} {'Created':<12}"
    lines.append((header, HDR()))
    lines.append(("─" * len(header), LBL()))
    for r in data:
        line = (
            f"  {r['AccountId']:<12} {r['BucketName']:<50} "
            f"{r['Region']:<20} {r['CreatedOn']:<12}"
        )
        lines.append((line, NRM()))
    lines.append(("", NRM()))
    lines.append((f"  Total: {len(data)} buckets", LBL()))
    return lines


def format_lb_rows(data: List[dict]) -> List[tuple]:
    lines = []
    if not data:
        return [("  No Load Balancers found.", ERR())]
    header = f"{'AccountId':<14} {'Region':<16} {'Name':<35} {'Type':<10} {'State':<10} {'Scheme':<16}"
    lines.append((header, HDR()))
    lines.append(("─" * len(header), LBL()))
    for r in data:
        line = (
            f"  {r['AccountId']:<12} {r['Region']:<16} {r['Name']:<35} "
            f"{r['Type']:<10} {r['State']:<10} {r['Scheme']:<16}"
        )
        lines.append((line, NRM()))
    lines.append(("", NRM()))
    lines.append((f"  Total: {len(data)} load balancers", LBL()))
    return lines


def format_detail_rows(data: dict) -> List[tuple]:
    """Key-value detail view for search results."""
    lines = []
    for k, v in data.items():
        lines.append((f"  {k:<28}: {v}", NRM()))
    return lines


def format_search_results(results: List[dict]) -> List[tuple]:
    if not results:
        return [("  [NOT FOUND] Resource not found across all accounts.", ERR())]
    lines = [("  [FOUND] Resource found!", curses.color_pair(2) | curses.A_BOLD)]
    for i, r in enumerate(results):
        lines.append((f"  ── Result {i+1} ──────────────────────────────────", LBL()))
        for k, v in r.items():
            lines.append((f"  {k:<28}: {v}", NRM()))
        lines.append(("", NRM()))
    return lines


# ─────────────────────────── CSV EXPORT ─────────────────────────────────────

def save_csv(data: List[dict], prefix: str):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = os.path.join(RESULTS_DIR, f"{prefix}_{ts}.csv")
    if not data:
        return path
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
    return path


# ─────────────────────────── MAIN APP ───────────────────────────────────────

def run_inventory(stdscr, accounts: list, caller_id: str):
    options = ["EC2 Instances", "RDS Databases", "S3 Buckets", "Load Balancers", "← Back"]
    while True:
        choice = menu(stdscr, "Inventory", options, f"Scanning across {len(accounts)} accounts")
        if choice < 0 or choice == 4:
            return

        _role_failures.clear()
        loading(stdscr, "Fetching data across all accounts...")

        data, label, formatter = [], "", None
        if choice == 0:
            data = inventory_ec2(stdscr, accounts, caller_id)
            label, formatter = "ec2_inventory", format_ec2_rows
        elif choice == 1:
            data = inventory_rds(stdscr, accounts, caller_id)
            label, formatter = "rds_inventory", format_rds_rows
        elif choice == 2:
            data = inventory_s3(stdscr, accounts, caller_id)
            label, formatter = "s3_inventory", format_s3_rows
        elif choice == 3:
            data = inventory_lb(stdscr, accounts, caller_id)
            label, formatter = "lb_inventory", format_lb_rows

        lines = formatter(data)
        if _role_failures:
            skip_lines = [("  The following accounts were skipped (role assumption failed):", curses.color_pair(5))]
            for f in _role_failures:
                skip_lines.append((f, curses.color_pair(3)))
            skip_lines.append(("", 0))
            skip_lines.append(("  TIP: Run with --role <RoleName> to override the default role.", curses.color_pair(3)))
            lines = skip_lines + [("", 0), ("  ── Results ──────────────────────────────", curses.color_pair(1))] + lines
        action = pager(stdscr, f"{options[choice]} — {len(data)} results", lines)
        if action == "save":
            path = save_csv(data, label)
            # Show save confirmation
            stdscr.clear()
            draw_border(stdscr)
            h, w = stdscr.getmaxyx()
            msg = f"Saved → {path}"
            safe_addstr(stdscr, h // 2, 3, msg, curses.color_pair(2))
            safe_addstr(stdscr, h // 2 + 1, 3, "Press any key...", LBL())
            stdscr.refresh()
            stdscr.getch()


def run_search(stdscr, accounts: list, caller_id: str):
    type_options = ["EC2 Instance", "RDS Database", "S3 Bucket", "Load Balancer", "← Back"]
    while True:
        choice = menu(stdscr, "Search for a Resource", type_options)
        if choice < 0 or choice == 4:
            return

        prompts = {
            0: "Enter EC2 Instance ID  (e.g. i-0abc1234def56789)",
            1: "Enter RDS DB Identifier (e.g. my-db-instance)",
            2: "Enter S3 Bucket Name    (exact name)",
            3: "Enter Load Balancer Name (exact name)",
        }
        resource_id = input_box(stdscr, prompts[choice])
        if not resource_id:
            continue

        loading(stdscr, f"Searching for [{resource_id}] across {len(accounts)} accounts...")

        results = []
        if choice == 0:
            results = search_ec2(stdscr, resource_id, accounts, caller_id)
        elif choice == 1:
            results = search_rds(stdscr, resource_id, accounts, caller_id)
        elif choice == 2:
            results = search_s3(stdscr, resource_id, accounts, caller_id)
        elif choice == 3:
            results = search_lb(stdscr, resource_id, accounts, caller_id)

        lines = format_search_results(results)
        action = pager(stdscr, f"Search: {resource_id}", lines)
        if action == "save" and results:
            path = save_csv(results, f"search_{type_options[choice].lower().replace(' ', '_')}")
            stdscr.clear()
            draw_border(stdscr)
            h, w = stdscr.getmaxyx()
            safe_addstr(stdscr, h // 2, 3, f"Saved → {path}", curses.color_pair(2))
            safe_addstr(stdscr, h // 2 + 1, 3, "Press any key...", LBL())
            stdscr.refresh()
            stdscr.getch()


def main(stdscr):
    init_colors()
    curses.curs_set(0)

    stdscr.clear()
    draw_border(stdscr)
    h, w = stdscr.getmaxyx()
    safe_addstr(stdscr, h // 2 - 2, 3, "AWS Multi-Account Dashboard", HDR())
    safe_addstr(stdscr, h // 2,     3, "Initializing - checking credentials...", LBL())
    stdscr.refresh()

    try:
        sts = boto3.client("sts")
        caller_id = sts.get_caller_identity()["Account"]
    except (NoCredentialsError, ClientError) as e:
        stdscr.clear()
        draw_border(stdscr)
        safe_addstr(stdscr, h // 2, 3, f"[ERROR] AWS credentials not found: {e}", ERR())
        safe_addstr(stdscr, h // 2 + 1, 3, "Configure with 'aws configure' or set env vars. Press any key.", LBL())
        stdscr.refresh()
        stdscr.getch()
        return

    safe_addstr(stdscr, h // 2 + 1, 3, "Discovering accounts via AWS Organizations...", LBL())
    stdscr.refresh()

    accounts = []
    org_error = None
    try:
        accounts = list_org_accounts()
    except Exception as e:
        org_error = str(e)

    if not accounts:
        accounts = [{"id": caller_id, "name": "CurrentAccount"}]

    # Show startup summary - this is the key diagnostic screen
    stdscr.clear()
    draw_border(stdscr)
    draw_header(stdscr, "Startup")
    safe_addstr(stdscr, 2, 3, f"Caller Account  : {caller_id}", LBL())
    safe_addstr(stdscr, 3, 3, f"Role to assume  : {ROLE_NAME}", LBL())
    safe_addstr(stdscr, 4, 3, f"Accounts loaded : {len(accounts)}", LBL())
    if org_error:
        safe_addstr(stdscr, 5, 3, f"[WARN] Organizations call failed:", ERR())
        safe_addstr(stdscr, 6, 5, org_error[:w - 8], ERR())
        safe_addstr(stdscr, 7, 3, "-> Falling back to current account only.", ERR())
        safe_addstr(stdscr, 8, 3, "-> Ensure you are on the master/management account.", ERR())
        safe_addstr(stdscr, 9, 3, "-> Or that your role has organizations:ListAccounts permission.", ERR())
    else:
        safe_addstr(stdscr, 5, 3, "Accounts:", NRM())
        for i, acct in enumerate(accounts[:12]):
            safe_addstr(stdscr, 6 + i, 5, f"{acct['id']}  {acct['name']}", NRM())
        if len(accounts) > 12:
            safe_addstr(stdscr, 18, 5, f"... and {len(accounts) - 12} more", LBL())
    safe_addstr(stdscr, h - 3, 3, f"Debug log: {DEBUG_LOG}", LBL())
    safe_addstr(stdscr, h - 2, 3, "Press any key to continue...", LBL())
    stdscr.refresh()
    stdscr.getch()

    main_options = [
        "Inventory",
        "Search for a Resource",
        "Exit",
    ]
    while True:
        choice = menu(
            stdscr, "Main Menu", main_options,
            f"Account: {caller_id}  |  {len(accounts)} accounts loaded  |  Role: {ROLE_NAME}"
        )
        if choice == 0:
            run_inventory(stdscr, accounts, caller_id)
        elif choice == 1:
            run_search(stdscr, accounts, caller_id)
        elif choice in (-1, 2):
            break



if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        print("\nExited.")
    except Exception as e:
        print(f"\nFatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
