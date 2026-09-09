#!/usr/bin/env python3
"""
CLI Viewer for the Centralized Error Log (error_log.jsonl).

Usage:
  python view_errors.py                     # View last 15 errors
  python view_errors.py --limit 30          # View last 30 errors
  python view_errors.py --channel rcs       # Filter by channel (rcs, whatsapp, sms)
  python view_errors.py --account tcl_promo # Filter by account
  python view_errors.py --id <error_id>     # Inspect full stack trace and context
  python view_errors.py --summary           # View category and channel breakdown
"""

import argparse
import json
import sys

from error_tracker import get_error_summary, load_errors


def _fmt_ts(iso_str: str) -> str:
    if not iso_str:
        return ""
    return iso_str.replace("T", " ")[:19]


def show_summary():
    s = get_error_summary()
    print("\n" + "=" * 60)
    print("📊 CENTRAL ERROR LOG SUMMARY")
    print("=" * 60)
    print(f"Total Logged Incidents: {s['total_errors']}")

    print("\nBy Channel:")
    for chan, count in s["by_channel"].items():
        print(f"  • {chan.upper():12}: {count}")

    print("\nBy Severity:")
    for sev, count in s["by_severity"].items():
        print(f"  • {sev:12}: {count}")

    print("\nBy Category:")
    for cat, count in s["by_category"].items():
        print(f"  • {cat:15}: {count}")

    if s.get("latest_error"):
        le = s["latest_error"]
        print(f"\nMost Recent Error ({_fmt_ts(le.get('timestamp', ''))}):")
        print(f"  [{le.get('id')}] {le.get('error_type')}: {le.get('error_message')}")
    print("=" * 60 + "\n")


def show_error_detail(err_id: str):
    errs = load_errors(limit=5000)
    target = next((e for e in errs if e.get("id") == err_id or err_id in e.get("id", "")), None)
    if not target:
        print(f"❌ No error found with ID matching '{err_id}'")
        sys.exit(1)

    print("\n" + "=" * 70)
    print(f"🔍 ERROR INCIDENT DETAILS: [{target.get('id')}]")
    print("=" * 70)
    print(f"Timestamp   : {_fmt_ts(target.get('timestamp', ''))}")
    print(f"Severity    : {target.get('severity')}")
    print(f"Category    : {target.get('category')}")
    print(f"Channel     : {target.get('channel', '').upper()}")
    print(f"Account     : {target.get('account')}")
    print(f"Location    : {target.get('module')}:{target.get('function')}")
    print(f"Exception   : {target.get('error_type')}")
    print(f"Message     : {target.get('error_message')}")

    if target.get("remediation_hint"):
        print("\n💡 Remediation:")
        print(f"   {target.get('remediation_hint')}")

    if target.get("context"):
        print("\nContext:")
        print(json.dumps(target.get("context"), indent=3))

    if target.get("stack_trace"):
        print("\nTraceback:")
        print("-" * 70)
        print(target.get("stack_trace").strip())
        print("-" * 70)
    print("=" * 70 + "\n")


def show_learned_patterns():
    from error_learning import load_learned_patterns

    patterns = load_learned_patterns()
    print("\n" + "=" * 80)
    print(f"🧠 LEARNED ERROR PATTERNS & PREVENTATIVE RULES ({len(patterns)} Active Rules)")
    print("=" * 80)

    for p in patterns:
        print(f"\n[{p.get('id')}] {p.get('name')}")
        print(f"  • Category         : {p.get('category')}")
        print(f"  • Seen             : {p.get('frequency', 1)} times (last: {_fmt_ts(p.get('last_seen', ''))})")
        print(f"  • Channels         : {', '.join(p.get('channels_affected', []))}")
        print(f"  • Root Cause       : {p.get('root_cause')}")
        print(f"  • Preventative Fix : {p.get('preventative_action')}")
        print(f"  • Auto-Fixable     : {'✅ Yes' if p.get('auto_fixable') else '⚠️ Manual Guidance'}")
        print("-" * 80)
    print()


def show_error_list(account=None, channel=None, category=None, severity=None, limit=15):
    errs = load_errors(account=account, channel=channel, category=category, severity=severity, limit=limit)
    if not errs:
        print("✅ No errors found matching criteria.")
        return

    print("\n" + "=" * 90)
    print(f"🚨 CENTRAL ERROR LOG (Showing {len(errs)} most recent incidents)")
    print("=" * 90)
    header = f"{'ID':14} {'TIMESTAMP':19} {'CHANNEL':8} {'ACCOUNT':12} {'TYPE':20} {'MESSAGE'}"
    print(header)
    print("-" * 90)

    for e in errs:
        eid = e.get("id", "")
        ts = _fmt_ts(e.get("timestamp", ""))
        chan = e.get("channel", "sys")[:7].upper()
        acc = e.get("account", "all")[:11]
        etype = (e.get("error_type") or e.get("category") or "Error")[:19]
        msg = e.get("error_message", "")
        if len(msg) > 40:
            msg = msg[:37] + "..."
        print(f"{eid:14} {ts:19} {chan:8} {acc:12} {etype:20} {msg}")

    print("-" * 90)
    print("Tip: Run 'python view_errors.py --id <ID>' to see the full stack trace and context.\n")


def main():
    parser = argparse.ArgumentParser(description="View and inspect system and platform errors.")
    parser.add_argument("--id", help="Inspect detailed stack trace for an error by ID")
    parser.add_argument("--account", help="Filter errors by account (e.g. tcl_promo, tchfl, etc.)")
    parser.add_argument("--channel", help="Filter errors by channel (e.g. rcs, whatsapp, sms)")
    parser.add_argument("--category", help="Filter by category (API_ERROR, TIMEOUT, DEPENDENCY, etc.)")
    parser.add_argument("--severity", help="Filter by severity (ERROR, CRITICAL, WARNING)")
    parser.add_argument("--limit", type=int, default=15, help="Number of records to show (default: 15)")
    parser.add_argument("--summary", action="store_true", help="Show error summary breakdown")
    parser.add_argument("--learned", action="store_true", help="View synthesized learned error patterns and preventative rules")
    args = parser.parse_args()

    if args.learned:
        show_learned_patterns()
    elif args.summary:
        show_summary()
    elif args.id:
        show_error_detail(args.id)
    else:
        show_error_list(
            account=args.account,
            channel=args.channel,
            category=args.category,
            severity=args.severity,
            limit=args.limit,
        )


if __name__ == "__main__":
    main()
