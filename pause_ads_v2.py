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

# Meta returns conversion data in two places depending on the ad's objective:
#   `conversions` — curated "business outcomes" (what Ads Manager shows as Results).
#                   Populated for purchase/submit-app-style ads. Empty for many lead-gen ads.
#   `actions`     — every engagement event. Lead-gen ads put their leads here only.
# Strategy: use `conversions` when populated; fall back to `actions` with family-based
# deduplication (same conversion counted under multiple action_types with equal values).
_VARIANT_SUFFIXES = ("_website", "_app", "_mobile_app", "_offline")

# Within each family, the same conversions are counted multiple ways — take MAX to dedupe.
_ACTION_CONVERSION_FAMILIES = {
    "purchase":              ("purchase", "offsite_conversion.fb_pixel_purchase", "onsite_conversion.purchase", "omni_purchase"),
    "lead":                  ("lead", "offsite_conversion.fb_pixel_lead", "onsite_web_lead"),
    "submit_application":    ("submit_application", "offsite_conversion.fb_pixel_submit_application"),
    "complete_registration": ("complete_registration", "offsite_conversion.fb_pixel_complete_registration"),
    "subscribe":             ("subscribe", "offsite_conversion.fb_pixel_subscribe"),
    "pixel_custom":          ("offsite_conversion.fb_pixel_custom",),
}


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


def _dedupe_variants(entries):
    """Drop `<family>_website`/`_app`/etc entries when `<family>_total` is also present."""
    all_types = {e.get("action_type", "") for e in entries}
    totals = {t[:-len("_total")] for t in all_types if t.endswith("_total")}
    result = []
    for e in entries:
        at = e.get("action_type", "")
        if any(at.endswith(s) and at[:-len(s)] in totals for s in _VARIANT_SUFFIXES):
            continue
        result.append(e)
    return result


def _sum_from_conversions(conversions_field) -> int:
    total = 0
    for e in _dedupe_variants(conversions_field):
        try:
            total += int(float(e.get("value", 0)))
        except (TypeError, ValueError):
            pass
    return total


def _sum_from_actions(actions_field) -> int:
    """Fallback when conversions[] is empty — sum curated conversion action_types,
    de-duplicating per family by taking MAX across equivalent types."""
    if not actions_field:
        return 0
    by_type = {}
    for a in actions_field:
        at = a.get("action_type", "")
        try:
            by_type[at] = int(float(a.get("value", 0)))
        except (TypeError, ValueError):
            pass
    total = 0
    for family_types in _ACTION_CONVERSION_FAMILIES.values():
        values = [by_type[t] for t in family_types if t in by_type]
        if values:
            total += max(values)
    # Named custom-conversion IDs are independent events, sum them all
    for at, v in by_type.items():
        if at.startswith("offsite_conversion.custom."):
            total += v
    return total


def count_conversions(insights) -> int:
    """Use Meta's curated conversions field if populated; otherwise fall back
    to actions[] with family-based deduplication."""
    conv = insights.get("conversions")
    if conv:
        return _sum_from_conversions(conv)
    return _sum_from_actions(insights.get("actions"))


def sum_conversion_values(conversion_values_field) -> float:
    if not conversion_values_field:
        return 0.0
    total = 0.0
    for e in _dedupe_variants(conversion_values_field):
        try:
            total += float(e.get("value", 0))
        except (TypeError, ValueError):
            pass
    return total


def pick_purchase_roas(roas_field) -> float | None:
    """Meta returns purchase_roas as a list like [{'action_type':'omni_purchase','value':'2.54'}]."""
    if not roas_field:
        return None
    for e in roas_field:
        try:
            return float(e.get("value", 0))
        except (TypeError, ValueError):
            continue
    return None


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
    # Spend floor — under this threshold, don't judge the ad at all
    if spend < rules.get("min_spend_before_eval", 0):
        return []

    ctr = float(insights.get("ctr") or 0)
    frequency = float(insights.get("frequency") or 0)

    conversions = count_conversions(insights)
    revenue = sum_conversion_values(insights.get("conversion_values"))
    purchase_roas = pick_purchase_roas(insights.get("purchase_roas"))
    roas = purchase_roas if purchase_roas is not None else ((revenue / spend) if spend > 0 and revenue > 0 else None)

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
        fields="ad_id,ad_name,spend,impressions,clicks,ctr,frequency,conversions,conversion_values,purchase_roas,actions",
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
    rules_cfg = cfg["pause_rules"]
    defaults = rules_cfg["defaults"]
    per_account = rules_cfg.get("accounts") or {}
    lookback = cfg.get("lookback_days", 3)
    min_age_hours = cfg.get("min_age_hours", 24)
    cfg_accounts = cfg.get("ad_accounts", "all")

    def effective_rules_for(acc_id: str) -> dict:
        """Merge defaults with per-account overrides; drop non-rule keys like `name`."""
        merged = dict(defaults)
        merged.update({k: v for k, v in (per_account.get(acc_id) or {}).items()
                       if k != "name"})
        return merged

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
        acc_rules = effective_rules_for(acc_id)
        override_fields = sorted(set(acc_rules) - {k for k, v in defaults.items() if acc_rules.get(k) == v})
        override_note = f"  overrides: {override_fields}" if per_account.get(acc_id) else "  (using defaults)"
        log.info(f"--- {acc_name} ({acc_id}) ---{override_note}")

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
            for rule, value in evaluate(ad, ins, acc_rules, min_age_hours):
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
