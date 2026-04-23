#!/usr/bin/env python3
"""
pause_ads.py
-------------
Hourly automation that evaluates Meta Ads performance via the Pipeboard MCP
server and pauses ads that violate configured thresholds.

Usage:
    python pause_ads.py                # live run
        python pause_ads.py --dry-run      # preview only, no changes
        """

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv
from anthropic import Anthropic

# ---------------------------------------------------------------------------
# Config & logging
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
      level=logging.INFO,
      format="%(asctime)s | %(levelname)s | %(message)s",
      handlers=[
                logging.FileHandler(LOG_DIR / "automation.log"),
                logging.StreamHandler(sys.stdout),
      ],
)
log = logging.getLogger("pipeboard-automation")

load_dotenv(ROOT / ".env")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
PIPEBOARD_API_KEY = os.getenv("PIPEBOARD_API_KEY")

if not ANTHROPIC_API_KEY or not PIPEBOARD_API_KEY:
      log.error("Missing ANTHROPIC_API_KEY or PIPEBOARD_API_KEY in .env")
      sys.exit(1)

MCP_URL = f"https://meta-ads.mcp.pipeboard.co/?token={PIPEBOARD_API_KEY}"


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
def load_config() -> dict:
      with open(ROOT / "config.yaml", "r") as f:
                return yaml.safe_load(f)


def build_prompt(cfg: dict, dry_run: bool) -> str:
      rules = cfg["pause_rules"]
      accounts = cfg.get("ad_accounts", "all")
      lookback = cfg.get("lookback_days", 3)

    action_clause = (
              "For each matching ad, DO NOT actually pause it. Instead, list the ad "
              "id, name, account, the rule it violated, and the metric value."
              if dry_run
              else "For each matching ad, call the pause_ad tool with the ad id. "
              "After pausing, report the ad id, name, account, rule triggered, and metric value."
    )

    return f"""
    You are an ad-ops automation agent. Use the pipeboard-meta-ads MCP tools to:

    1. List all ACTIVE ads across these accounts: {accounts}
    2. Pull performance metrics for each ad over the last {lookback} days.
    3. Evaluate each ad against these pause rules (pause if ANY rule matches):

       - CPA  > {rules['max_cpa']}                (cost per result, account currency)
          - CTR  < {rules['min_ctr']}%  AND spend > {rules['min_spend_for_ctr_rule']}
             - ROAS < {rules['min_roas']}                (purchase ROAS)
                - Frequency > {rules['max_frequency']}
                   - Spend > {rules['max_spend_zero_conv']} with 0 conversions

                   4. {action_clause}

                   5. Return a final JSON summary with shape:
                      {{
                           "evaluated": <int>,
                                "paused":    <int>,
                                     "actions":   [ {{ "ad_id": "...", "name": "...", "account": "...",
                                                            "rule": "...", "value": "..." }} ]
                                                               }}

                                                               Be conservative. If data is missing for an ad, skip it. Do not pause any ad
                                                               that has been active for less than {cfg.get('min_age_hours', 24)} hours.
                                                               """.strip()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
      parser = argparse.ArgumentParser()
      parser.add_argument("--dry-run", action="store_true",
                          help="Evaluate only, do not pause any ads")
      args = parser.parse_args()

    cfg = load_config()
    prompt = build_prompt(cfg, dry_run=args.dry_run)

    log.info("=" * 72)
    log.info("Run start | dry_run=%s | accounts=%s",
                          args.dry_run, cfg.get("ad_accounts", "all"))

    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    response = client.beta.messages.create(
              model=cfg.get("model", "claude-sonnet-4-5"),
              max_tokens=8192,
              mcp_servers=[{
                            "type": "url",
                            "url": MCP_URL,
                            "name": "pipeboard-meta-ads",
              }],
              messages=[{"role": "user", "content": prompt}],
              betas=["mcp-client-2025-04-04"],
    )

    # Extract final text / JSON summary
    summary_text = ""
    for block in response.content:
              if getattr(block, "type", None) == "text":
                            summary_text += block.text

          log.info("Claude response:\n%s", summary_text)

    # Try to parse the JSON summary for structured logging
    try:
              start = summary_text.find("{")
              end = summary_text.rfind("}") + 1
              summary = json.loads(summary_text[start:end])
              log.info("Evaluated=%s Paused=%s",
                       summary.get("evaluated"), summary.get("paused"))
              for a in summary.get("actions", []):
                            log.info("ACTION | account=%s | ad=%s | rule=%s | value=%s",
                                                          a.get("account"), a.get("ad_id"),
                                                          a.get("rule"), a.get("value"))
    except Exception as e:  # noqa: BLE001
              log.warning("Could not parse JSON summary: %s", e)

    log.info("Run end   | %s", datetime.utcnow().isoformat())


if __name__ == "__main__":
      main()
  
