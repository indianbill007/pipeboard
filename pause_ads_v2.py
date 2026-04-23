#!/usr/bin/env python3
"""
pause_ads_v2.py — direct Meta Marketing API, no Pipeboard, no LLM.

Evaluates active ads across all visible ad accounts against the rules in
config.yaml and reports what would be paused. Dry-run only (never writes).
"""
import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
(ROOT / "reports").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "automation.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("pause-ads-v2")

load_dotenv(ROOT / ".env")
TOKEN = os.getenv("META_ACCESS_TOKEN")
if not TOKEN:
    log.error("Missing META_ACCESS_TOKEN in .env")
    sys.exit(1)

GRAPH = "https://graph.facebook.com/v21.0"

# Action types that count as a "conversion" for CPA / zero-conv rules.
# Broad set — matches standard, onsite, offsite, and lead events.
# Custom pixel events (offsite_conversion.custom.<id>) matched via prefix.
CONVERSION_TYPES = {
    "purchase",
    "offsite_conversion.fb_pixel_purchase",
    "onsite_conversion.purchase",
    "lead",
    "offsite_conversion.fb_pixel_lead",
    "onsite_conversion.lead_grouped",
    "submit_application",
    "offsite_conversion.fb_pixel_submit_application",
    "complete_registration",
    "offsite_conversion.fb_pixel_complete_registration",
}
CONVERSION_PREFIXES = ("offsite_conversion.custom.",)


def is_conversion(action_type: str) -> bool:
    return action_type in CONVERSION_TYPES or any(
        action_type.startswith(p) for p in CONVERSION_PREFIXES
    )


def graph(path: str, **params) -> dict:
    params.setdefault("access_token", TOKEN)
    url = f"{GRAPH}/{path}?" + urllib.parse.urlencode(params, doseq=True)
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = {}
        try:
            body = json.loads(e.read().decode())
        except Exception:
            pass
        err = body.get("error", {})
        raise RuntimeError(
            f"Graph {e.code} {path}: {err.get('message','?')} (code={err.get('code','?')})"
        ) from e


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


def sum_conv_count(actions) -> int:
    return sum(int(float(a.get("value", 0))) for a in (actions or []) if is_conversion(a.get("action_type", "")))


def sum_conv_value(action_values) -> float:
    total = 0.0
    for a in action_values or []:
        if is_conversion(a.get("action_type", "")):
            try:
                total += float(a.get("value", 0))
            except (TypeError, ValueError):
                pass
    return total


def evaluate(ad, insights, rules, min_age_hours) -> list:
    """Return list of (rule, value) violations. Empty list = clean."""
    # Age guard — don't flag ads in the learning phase
    try:
        created = datetime.fromisoformat(ad["created_time"])
        if datetime.now(created.tzinfo) - created < timedelta(hours=min_age_hours):
            return []
    except (KeyError, ValueError):
        pass

    spend = float(insights.get("spend") or 0)
    ctr = float(insights.get("ctr") or 0)
    frequency = float(insights.get("frequency") or 0)
    actions = insights.get("actions") or []
    action_values = insights.get("action_values") or []

    conversions = sum_conv_count(actions)
    revenue = sum_conv_value(action_values)
    roas = (revenue / spend) if spend > 0 else None

    v = []
    if spend > rules["max_spend_zero_conv"] and conversions == 0:
        v.append((f"Spend>{rules['max_spend_zero_conv']} with 0 conv",
                  f"spend={spend:.2f}, conversions=0"))
    if conversions > 0 and (spend / conversions) > rules["max_cpa"]:
        v.append((f"CPA>{rules['max_cpa']}",
                  f"CPA={spend/conversions:.2f} (spend={spend:.2f}, conv={conversions})"))
    if ctr < rules["min_ctr"] and spend > rules["min_spend_for_ctr_rule"]:
        v.append((f"CTR<{rules['min_ctr']}% and spend>{rules['min_spend_for_ctr_rule']}",
                  f"CTR={ctr:.3f}%, spend={spend:.2f}"))
    if roas is not None and revenue > 0 and roas < rules["min_roas"]:
        v.append((f"ROAS<{rules['min_roas']}",
                  f"ROAS={roas:.2f} (rev={revenue:.2f}, spend={spend:.2f})"))
    if frequency > rules["max_frequency"]:
        v.append((f"Frequency>{rules['max_frequency']}",
                  f"frequency={frequency:.2f}"))
    return v


def ads_manager_url(account_num: str, ad_id: str) -> str:
    return f"https://business.facebook.com/adsmanager/manage/ads?act={account_num}&selected_ad_ids={ad_id}"


def fetch_ad_insights(account_id: str, ad_ids: list, lookback: int) -> dict:
    if not ad_ids:
        return {}
    preset = f"last_{lookback}d" if lookback in (3, 7, 14, 28, 30, 90) else "last_3d"
    rows = graph_all(
        f"{account_id}/insights",
        fields="ad_id,ad_name,spend,impressions,clicks,ctr,frequency,actions,action_values",
        level="ad",
        filtering=json.dumps([{"field": "ad.id", "operator": "IN", "value": ad_ids}]),
        date_preset=preset,
        limit=500,
    )
    return {r["ad_id"]: r for r in rows}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--account", action="append",
                   help="Restrict to one or more ad account IDs (repeatable). "
                        "Overrides config.yaml.")
    args = p.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    rules = cfg["pause_rules"]
    lookback = cfg.get("lookback_days", 3)
    min_age_hours = cfg.get("min_age_hours", 24)
    cfg_accounts = cfg.get("ad_accounts", "all")

    log.info("=" * 72)
    log.info(f"Run start | lookback={lookback}d | min_age={min_age_hours}h | DRY-RUN")

    visible = graph_all("me/adaccounts", fields="id,account_id,name,currency,account_status")
    log.info(f"Token sees {len(visible)} ad account(s)")

    # Figure out which accounts to scan
    if args.account:
        target_ids = set(args.account)
    elif isinstance(cfg_accounts, list):
        target_ids = set(cfg_accounts)
    else:  # "all" or anything else
        target_ids = {a["id"] for a in visible}

    targets = [a for a in visible if a["id"] in target_ids]
    missing = target_ids - {a["id"] for a in visible}
    if missing:
        log.warning(f"Requested but not visible: {sorted(missing)}")
    log.info(f"Scanning {len(targets)} account(s)")

    evaluated = 0
    flagged = []

    for acc in targets:
        acc_id, acc_name, acc_num = acc["id"], acc["name"], acc["account_id"]
        log.info(f"--- {acc_name} ({acc_id}) ---")

        try:
            ads = graph_all(
                f"{acc_id}/ads",
                fields="id,name,status,effective_status,created_time,adset_id,campaign_id",
                effective_status='["ACTIVE"]',
                limit=500,
            )
        except RuntimeError as e:
            log.error(f"  list ads: {e}")
            continue

        if not ads:
            log.info("  no delivering ads")
            continue
        log.info(f"  {len(ads)} delivering ad(s)")

        try:
            insights_by_ad = fetch_ad_insights(acc_id, [a["id"] for a in ads], lookback)
        except RuntimeError as e:
            log.error(f"  insights: {e}")
            continue

        for ad in ads:
            ins = insights_by_ad.get(ad["id"])
            if not ins:
                continue
            evaluated += 1
            for rule, value in evaluate(ad, ins, rules, min_age_hours):
                flagged.append({
                    "ad_id": ad["id"],
                    "name": ad["name"],
                    "account": acc_name,
                    "account_id": acc_id,
                    "rule": rule,
                    "value": value,
                    "link": ads_manager_url(acc_num, ad["id"]),
                })

    summary = {
        "evaluated": evaluated,
        "flagged": len(flagged),
        "paused": 0,
        "actions": flagged,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "lookback_days": lookback,
    }

    log.info("=" * 72)
    log.info(f"Evaluated: {evaluated}  |  Flagged: {len(flagged)}  |  Paused: 0 (dry-run)")
    for f in flagged:
        log.info(f"FLAG | {f['account'][:25]:25s} | {f['name'][:35]:35s} | {f['rule']:40s} | {f['value']}")
        log.info(f"     | {f['link']}")

    out_path = ROOT / "reports" / f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log.info(f"Report: {out_path}")


if __name__ == "__main__":
    main()
