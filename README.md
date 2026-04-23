# Pipeboard Meta Ads Automation

Automated hourly management of Meta (Facebook) Ads via the [Pipeboard](https://pipeboard.co) MCP server and Claude.

## Overview

This repo contains a cron-driven automation that:
1. Connects to Pipeboard's Meta Ads MCP server
2. Uses Claude (via the Anthropic API with MCP connector) to evaluate ad performance
3. Pauses underperforming ads based on configurable rules
4. Logs every action to `logs/automation.log`

## Architecture

```
cron (hourly)
   |
      v
      pause_ads.py  --->  Anthropic API (Claude)  --->  Pipeboard MCP  --->  Meta Ads API
         |
            v
            logs/automation.log
            ```

            ## Setup

            ### 1. Clone the repo
            ```bash
            git clone https://github.com/indianbill007/pipeboard.git
            cd pipeboard
            ```

            ### 2. Install dependencies
            ```bash
            pip install -r requirements.txt
            ```

            ### 3. Configure environment variables
            Copy `.env.example` to `.env` and fill in:
            ```
            ANTHROPIC_API_KEY=sk-ant-...
            PIPEBOARD_API_KEY=pk_...
            ```

            ### 4. Configure pause rules
            Edit `config.yaml` to set your thresholds (CPA, CTR, ROAS, frequency, etc.)

            ### 5. Test run
            ```bash
            python pause_ads.py --dry-run
            ```

            ### 6. Install the cron job
            ```bash
            bash install_cron.sh
            ```
            This installs a cron entry that runs every hour at minute 0.

            ## Files

            | File | Purpose |
            |------|---------|
            | `pause_ads.py` | Main automation script |
            | `config.yaml` | Pause/action rules and thresholds |
            | `requirements.txt` | Python dependencies |
            | `.env.example` | Template for environment variables |
            | `install_cron.sh` | Helper to install the hourly cron job |
            | `logs/` | Log output directory |

            ## Pause Rules (configurable in `config.yaml`)

            An ad will be paused if ANY of these conditions are met:
            - **CPA (Cost Per Action)** exceeds the configured max
            - **CTR (Click-Through Rate)** falls below the configured min with spend above threshold
            - **ROAS (Return On Ad Spend)** drops below the configured floor over lookback window
            - **Frequency** (ad fatigue) exceeds the configured max
            - **Spend-with-zero-conversions** exceeds the configured max

            All thresholds are tunable per account in `config.yaml`.

            ## Safety

            - `--dry-run` flag lists ads that *would* be paused without taking action
            - Every action writes to `logs/automation.log` with timestamp, ad id, rule triggered, metric value
            - A daily summary email can be enabled in `config.yaml`

            ## License

            MIT
            
