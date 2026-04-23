# Pipeboard Meta Ads Automation

Automated hourly management of Meta (Facebook) Ads via the [Pipeboard](https://pipeboard.co) MCP server and Claude.

Runs on **Windows, Linux, and macOS** using a pure-Python scheduler (APScheduler) - no system cron required.

## Overview

This repo contains a scheduled automation that:
1. Connects to Pipeboard's Meta Ads MCP server
2. 2. Uses Claude (via the Anthropic API with MCP connector) to evaluate ad performance
   3. 3. Pauses underperforming ads based on configurable rules
      4. 4. Logs every action to `logs/automation.log`
        
         5. ## Architecture
        
         6. ```
            scheduler.py (Python, APScheduler)  --- runs every hour --->  pause_ads.py
                                                                                |
                                                                                v
                                                           Anthropic API (Claude)
                                                                                |
                                                                                v
                                                           Pipeboard MCP --->  Meta Ads API
                                                                                |
                                                                                v
                                                           logs/automation.log
                                                           logs/scheduler.log
            ```

            ## Setup

            ### 1. Clone the repo
            ```bash
            git clone https://github.com/indianbill007/pipeboard.git
            cd pipeboard
            ```

            ### 2. Install dependencies
            ```bash
            python -m pip install -r requirements.txt
            ```

            ### 3. Configure environment variables
            Copy `.env.example` to `.env` and fill in:
            ```
            ANTHROPIC_API_KEY=sk-ant-...
            PIPEBOARD_API_KEY=pk_...
            ```

            ### 4. Configure pause rules
            Edit `config.yaml` to set your thresholds (CPA, CTR, ROAS, frequency, etc.)

            ### 5. Test run (safe)
            ```bash
            python pause_ads.py --dry-run
            ```

            ### 6. Start the scheduler
            ```bash
            python scheduler.py
            ```
            That's it. The scheduler now runs `pause_ads.py` every hour on the hour (minute 0, UTC).

            Keep the process alive with whichever tool is natural on your OS:
            - **Linux:** `systemd` service, `nohup`, `tmux`, `screen`, or Docker
            - - **macOS:** `launchd` plist, `nohup`, `tmux`, or Docker
              - - **Windows:** Task Scheduler (run at login / as a service), NSSM, or Docker Desktop
               
                - ## Scheduler options
               
                - ```bash
                  python scheduler.py                       # default: hourly at minute 0
                  python scheduler.py --interval 30         # every 30 minutes
                  python scheduler.py --cron "*/15 * * * *" # every 15 minutes, custom cron
                  python scheduler.py --run-now             # also run once immediately on startup
                  python scheduler.py --dry-run             # evaluate only, no ads will be paused
                  ```

                  ## Files

                  | File | Purpose |
                  |------|---------|
                  | `scheduler.py` | Platform-independent Python scheduler (APScheduler) |
                  | `pause_ads.py` | Core automation: fetches metrics and pauses ads |
                  | `config.yaml` | Pause/action rules and thresholds |
                  | `requirements.txt` | Python dependencies |
                  | `.env.example` | Template for environment variables |
                  | `logs/` | Log output directory (auto-created) |

                  ## Pause Rules (configurable in `config.yaml`)

                  An ad will be paused if ANY of these conditions are met:
                  - **CPA (Cost Per Action)** exceeds the configured max
                  - - **CTR (Click-Through Rate)** falls below the configured min with spend above threshold
                    - - **ROAS (Return On Ad Spend)** drops below the configured floor over lookback window
                      - - **Frequency** (ad fatigue) exceeds the configured max
                        - - **Spend-with-zero-conversions** exceeds the configured max
                         
                          - All thresholds are tunable per account in `config.yaml`.
                         
                          - ## Safety
                         
                          - - `--dry-run` flag lists ads that *would* be paused without taking action
                            - - Every action writes to `logs/automation.log` with timestamp, ad id, rule triggered, metric value
                              - - Scheduler is configured with `max_instances=1` and `coalesce=True` so runs never overlap
                                - - Ads younger than `min_age_hours` (default 24h) are never touched, protecting ads still in Meta's learning phase
                                 
                                  - ## License
                                 
                                  - MIT
                                  - 
