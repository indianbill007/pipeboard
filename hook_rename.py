#!/usr/bin/env python3
"""
hook_rename.py — extract the hook from each active ad's body copy and propose
a rename. Dry-run only; does NOT call Meta to rename.

Writes proposals to reports/hook_rename_proposals_<timestamp>.json for review.

Usage:
    python hook_rename.py                      # all active ads, all accounts
    python hook_rename.py --account act_X      # restrict to one account
    python hook_rename.py --sample 5           # only first 5 ads
    python hook_rename.py --prefix "🎯"        # alternate prefix (default: "[Hook]")
"""
import argparse
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Force UTF-8 on Windows stdout so emoji in ad bodies don't crash the logger
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
(ROOT / "reports").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "hook_rename.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("hook-rename")

load_dotenv(ROOT / ".env")
TOKEN = os.getenv("META_ACCESS_TOKEN")
if not TOKEN:
    log.error("Missing META_ACCESS_TOKEN in .env")
    sys.exit(1)

GRAPH = "https://graph.facebook.com/v21.0"


def graph_all(path: str, **params) -> list:
    params.setdefault("limit", 100)
    params["access_token"] = TOKEN
    next_url = f"{GRAPH}/{path}?" + urllib.parse.urlencode(params, doseq=True)
    out = []
    while next_url:
        with urllib.request.urlopen(next_url, timeout=30) as r:
            page = json.loads(r.read().decode())
        out.extend(page.get("data", []))
        next_url = page.get("paging", {}).get("next")
    return out


def extract_hook(body: str, max_chars: int = 80) -> str:
    """Take the hook (first line or first sentence) from ad body copy."""
    if not body:
        return ""
    first_line = body.split("\n", 1)[0].strip()
    # Strip leading emojis/punctuation that don't carry meaning — keep them if
    # they're part of a proper word. Heuristic: drop leading spaces only.
    if len(first_line) <= max_chars:
        return first_line
    # Line too long — try first sentence
    m = re.split(r"(?<=[.!?])\s+", first_line, maxsplit=1)
    if m and len(m[0]) <= max_chars and len(m[0]) > 10:
        return m[0]
    # Still too long — hard-truncate on word boundary
    cut = first_line[:max_chars].rsplit(" ", 1)[0]
    return cut + "…" if cut else first_line[:max_chars]


def propose_name(hook: str, prefix: str, max_total: int = 120) -> str:
    """Build a rename string. Meta ad names tolerate Unicode and long strings."""
    if not hook:
        return ""
    name = f"{prefix} {hook}".strip()
    if len(name) > max_total:
        name = name[: max_total - 1].rstrip() + "…"
    return name


def has_video(creative: dict) -> bool:
    if not creative:
        return False
    if creative.get("video_id"):
        return True
    oss = creative.get("object_story_spec") or {}
    if (oss.get("video_data") or {}).get("video_id"):
        return True
    for v in (creative.get("asset_feed_spec") or {}).get("videos") or []:
        if v.get("video_id"):
            return True
    return False


def fetch_active_ads_with_creative(account_id: str) -> list:
    """One paginated call per account — efficient."""
    return graph_all(
        f"{account_id}/ads",
        fields=(
            "id,name,effective_status,created_time,"
            "creative{id,body,title,thumbnail_url,video_id,object_story_spec,asset_feed_spec}"
        ),
        effective_status='["ACTIVE"]',
        limit=200,
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--account", action="append",
                   help="Restrict to one or more act_ ids (repeatable). Default: all visible.")
    p.add_argument("--sample", type=int, default=0,
                   help="Only process the first N ads across all scanned accounts (0 = no cap).")
    p.add_argument("--prefix", default="[Hook]",
                   help="Prefix for proposed rename (default '[Hook]').")
    p.add_argument("--max-chars", type=int, default=80,
                   help="Max hook length in chars (default 80).")
    args = p.parse_args()

    log.info("=" * 72)
    visible = graph_all("me/adaccounts", fields="id,account_id,name")
    if args.account:
        targets = [a for a in visible if a["id"] in set(args.account)]
    else:
        targets = visible
    log.info(f"Scanning {len(targets)} account(s)")

    proposals = []
    processed = 0
    no_body = 0
    unchanged = 0

    for acc in targets:
        acc_id, acc_name = acc["id"], acc["name"]
        if args.sample and processed >= args.sample:
            break

        log.info(f"--- {acc_name} ({acc_id}) ---")
        try:
            ads = fetch_active_ads_with_creative(acc_id)
        except Exception as e:
            log.error(f"  ads fetch failed: {e}")
            continue
        log.info(f"  {len(ads)} active ad(s)")

        for ad in ads:
            if args.sample and processed >= args.sample:
                break
            creative = ad.get("creative") or {}
            body = (creative.get("body") or "").strip()
            if not body:
                no_body += 1
                continue

            hook = extract_hook(body, max_chars=args.max_chars)
            proposed = propose_name(hook, prefix=args.prefix)
            current = ad.get("name", "")

            if not proposed or proposed == current:
                unchanged += 1
                continue

            proposals.append({
                "ad_id": ad["id"],
                "account_id": acc_id,
                "account_name": acc_name,
                "name_current": current,
                "name_proposed": proposed,
                "hook": hook,
                "body_preview": body[:200],
                "has_video": has_video(creative),
                "thumbnail_url": creative.get("thumbnail_url", ""),
            })
            processed += 1

    out = ROOT / "reports" / f"hook_rename_proposals_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps({
        "run_at": datetime.now(timezone.utc).isoformat(),
        "source": "creative.body",
        "prefix": args.prefix,
        "max_hook_chars": args.max_chars,
        "processed": processed,
        "skipped_no_body": no_body,
        "skipped_unchanged": unchanged,
        "proposals": proposals,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    log.info("=" * 72)
    log.info(f"Proposed renames: {len(proposals)}  |  no body: {no_body}  |  unchanged: {unchanged}")
    for pr in proposals[:20]:
        log.info(f"  {pr['account_name'][:20]:20s} | current: {pr['name_current'][:40]:40s}")
        log.info(f"  {' ':20s}   proposed: {pr['name_proposed']}")
    if len(proposals) > 20:
        log.info(f"  ... and {len(proposals) - 20} more (see JSON)")
    log.info(f"Report: {out}")
    log.info("NO ADS WERE RENAMED. Review the JSON and approve before applying.")


if __name__ == "__main__":
    main()
