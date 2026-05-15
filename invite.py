"""Admin CLI — invite a new subscriber and email them a welcome link.

Usage
-----
    python invite.py user@example.com
    python invite.py user@example.com --name "Alice"
    python invite.py user@example.com --tier free --no-welcome
    python invite.py --list
    python invite.py user@example.com --status paused        # toggle existing
    python invite.py user@example.com --revoke                # delete subscriber

Notes
-----
- Default tier is `paid` (since this is an invite-only system).
- Default behavior sends a welcome email (containing the first Magic Link).
- If the address already exists, you can update fields via --status / --tier;
  use --revoke to remove a subscriber entirely.
"""

import argparse
import sys
import sqlite3
from datetime import datetime

import config
import storage
import subscribers
import auth


def _print_row(sub: subscribers.Subscriber) -> None:
    paid_flag = "✓ paid" if subscribers.is_paid(sub) else "  free"
    name = sub.name or ""
    print(f"  [{sub.id:>3}] {sub.email:<32} {sub.status:<8} {sub.tier:<5} "
          f"{paid_flag}   {name}")


def cmd_list(args: argparse.Namespace) -> int:
    with storage.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM subscribers ORDER BY id"
        ).fetchall()
    if not rows:
        print("No subscribers yet. Run `python invite.py you@example.com` to add the first one.")
        return 0
    print(f"\n{len(rows)} subscriber(s):\n")
    print(f"  {'ID':>3}  {'email':<32} {'status':<8} {'tier':<5} {'access':<7}  name")
    print("  " + "-" * 70)
    for r in rows:
        _print_row(subscribers.Subscriber.from_row(r))
    print()
    return 0


def cmd_revoke(email: str) -> int:
    sub = subscribers.get_by_email(email)
    if not sub:
        print(f"× No subscriber with email {email!r}", file=sys.stderr)
        return 1
    with storage.get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE subscriber_id = ?", (sub.id,))
        conn.execute("DELETE FROM magic_links WHERE email = ?", (sub.email,))
        conn.execute("DELETE FROM subscribers WHERE id = ?", (sub.id,))
    print(f"✓ Revoked subscriber {sub.email} (id={sub.id}); sessions and tokens cleared.")
    return 0


def cmd_update(sub: subscribers.Subscriber,
               status: str | None, tier: str | None,
               name: str | None, paid_until: str | None) -> int:
    """Update an existing subscriber's fields and report the change."""
    fields, params = [], []
    if status: fields.append("status = ?"); params.append(status)
    if tier:   fields.append("tier = ?");   params.append(tier)
    if name is not None: fields.append("name = ?"); params.append(name or None)
    if paid_until is not None:
        fields.append("paid_until = ?"); params.append(paid_until or None)
    if not fields:
        print("× Email already exists. Pass --status/--tier/--name/--paid-until to update,")
        print("  or --revoke to delete.", file=sys.stderr)
        return 1
    fields.append("updated_at = ?")
    params.append(datetime.now().isoformat(timespec="seconds"))
    params.append(sub.id)
    with storage.get_conn() as conn:
        conn.execute(f"UPDATE subscribers SET {', '.join(fields)} WHERE id = ?", params)
    print(f"✓ Updated subscriber {sub.email}:")
    _print_row(subscribers.get_by_id(sub.id))  # type: ignore[arg-type]
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    email = args.email.lower().strip()
    existing = subscribers.get_by_email(email)
    if existing:
        # Already on the list — fall through to update mode
        return cmd_update(existing, args.status, args.tier,
                          args.name, args.paid_until)

    try:
        sub = subscribers.add_subscriber(
            email=email,
            name=args.name or "",
            tier=args.tier,
            status=args.status,
            paid_until=args.paid_until or None,
        )
    except sqlite3.IntegrityError as e:
        print(f"× Failed to add {email}: {e}", file=sys.stderr)
        return 1

    print(f"✓ Added subscriber:")
    _print_row(sub)

    if args.no_welcome:
        print("  (welcome email skipped — pass without --no-welcome to send)")
        return 0

    try:
        token = subscribers.create_magic_link(email)
        auth.send_welcome_email(email, args.name or "", token)
        print(f"✓ Welcome email sent to {email}")
        print(f"  Magic Link valid for {config.MAGIC_LINK_TTL_MINUTES} minutes")
    except Exception as e:
        print(f"⚠ Subscriber added but welcome email failed: {e}", file=sys.stderr)
        print(f"  You can resend later via the /login page", file=sys.stderr)
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Invite a new subscriber or manage existing ones.",
        epilog="Example: python invite.py alice@example.com --name Alice",
    )
    p.add_argument("email", nargs="?",
                   help="Email address to invite (omit when using --list)")
    p.add_argument("--list", action="store_true",
                   help="List all current subscribers and exit")
    p.add_argument("--name", default="",
                   help="Display name (optional)")
    p.add_argument("--tier", choices=["free", "paid"], default="paid",
                   help="Subscription tier (default: paid)")
    p.add_argument("--status",
                   choices=["active", "invited", "paused", "churned"],
                   default="active",
                   help="Account status (default: active)")
    p.add_argument("--paid-until",
                   help="Optional ISO date for paid expiry (e.g. 2027-01-01)")
    p.add_argument("--no-welcome", action="store_true",
                   help="Skip the welcome email (no Magic Link sent)")
    p.add_argument("--revoke", action="store_true",
                   help="Delete the subscriber and all their sessions/tokens")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Ensure schema is in place before any DB op
    storage.init_db()

    if args.list:
        return cmd_list(args)
    if not args.email:
        print("× email argument is required (or use --list)", file=sys.stderr)
        return 1
    if args.revoke:
        return cmd_revoke(args.email.lower().strip())
    return cmd_add(args)


if __name__ == "__main__":
    sys.exit(main())
