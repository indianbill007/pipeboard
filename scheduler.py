#!/usr/bin/env python3
"""
scheduler.py
-------------
Platform-independent scheduler that runs the Pipeboard Meta Ads automation
(pause_ads.py) every hour. Works on Windows, Linux, and macOS.

Uses APScheduler's BlockingScheduler - no system cron needed.

Usage:
    python scheduler.py                       # run hourly at minute 0 (default)
        python scheduler.py --interval 30         # run every 30 minutes
            python scheduler.py --cron "0 * * * *"    # custom cron expression
                python scheduler.py --run-now             # also run once immediately on start
                    python scheduler.py --dry-run             # forward --dry-run to pause_ads.py
                    """

import argparse
import logging
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

# ---------------------------------------------------------------------------
# Paths & logging
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
      level=logging.INFO,
      format="%(asctime)s | %(levelname)s | scheduler | %(message)s",
      handlers=[
                logging.FileHandler(LOG_DIR / "scheduler.log"),
                logging.StreamHandler(sys.stdout),
      ],
)
# Quiet down the noisy APScheduler internal logger
logging.getLogger("apscheduler").setLevel(logging.WARNING)

log = logging.getLogger("scheduler")


# ---------------------------------------------------------------------------
# The job
# ---------------------------------------------------------------------------
def run_pause_ads(dry_run: bool = False) -> None:
      """Invoke pause_ads.py as a subprocess and stream its output to the log."""
      cmd = [sys.executable, str(ROOT / "pause_ads.py")]
      if dry_run:
                cmd.append("--dry-run")

      start = datetime.utcnow()
      log.info("Job start | cmd=%s", " ".join(cmd))

    try:
              result = subprocess.run(
                            cmd,
                            cwd=ROOT,
                            capture_output=True,
                            text=True,
                            check=False,
                            timeout=55 * 60,  # 55-minute timeout, so we never overlap hourly runs
              )
              duration = (datetime.utcnow() - start).total_seconds()

        if result.stdout:
                      for line in result.stdout.rstrip().splitlines():
                                        log.info("pause_ads | %s", line)
                                if result.stderr:
                                              for line in result.stderr.rstrip().splitlines():
                                                                log.warning("pause_ads[stderr] | %s", line)

                                          log.info("Job end   | rc=%s | duration=%.1fs",
                                                                    result.returncode, duration)
except subprocess.TimeoutExpired:
        log.error("Job TIMED OUT after 55 minutes - killing and continuing.")
except Exception as exc:  # noqa: BLE001
        log.exception("Job FAILED with unexpected error: %s", exc)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
      p = argparse.ArgumentParser(description="Platform-independent scheduler for Pipeboard automation")
    group = p.add_mutually_exclusive_group()
    group.add_argument(
              "--interval",
              type=int,
              help="Run every N minutes (alternative to --cron)",
    )
    group.add_argument(
              "--cron",
              type=str,
              default="0 * * * *",
              help="Cron expression in standard 5-field format. Default: '0 * * * *' (hourly).",
    )
    p.add_argument(
              "--run-now",
              action="store_true",
              help="Execute pause_ads.py once immediately on startup, in addition to the schedule.",
    )
    p.add_argument(
              "--dry-run",
              action="store_true",
              help="Forward --dry-run to pause_ads.py (no ads will be paused).",
    )
    return p.parse_args()


def build_trigger(args: argparse.Namespace):
      if args.interval:
                log.info("Trigger: every %d minute(s)", args.interval)
        return IntervalTrigger(minutes=args.interval)

    fields = args.cron.split()
    if len(fields) != 5:
              raise ValueError(f"--cron must be a 5-field expression, got: {args.cron!r}")
    minute, hour, day, month, dow = fields
    log.info("Trigger: cron '%s'", args.cron)
    return CronTrigger(
              minute=minute, hour=hour, day=day, month=month, day_of_week=dow,
    )


def install_signal_handlers(scheduler: BlockingScheduler) -> None:
      def _shutdown(signum, _frame):
                log.info("Received signal %s - shutting down scheduler.", signum)
        scheduler.shutdown(wait=False)
        sys.exit(0)

    # SIGINT works everywhere; SIGTERM is POSIX-only.
    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):
              try:
                            signal.signal(signal.SIGTERM, _shutdown)
except (ValueError, OSError):
            # Ignored on Windows when not running in main thread
            pass


def main() -> None:
      args = parse_args()

    log.info("=" * 72)
    log.info("Pipeboard scheduler starting on %s | Python %s",
                          sys.platform, sys.version.split()[0])

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
              run_pause_ads,
              trigger=build_trigger(args),
              kwargs={"dry_run": args.dry_run},
              id="pause_ads",
              name="Pipeboard Meta Ads auto-pause",
              max_instances=1,
              coalesce=True,
              misfire_grace_time=300,
    )

    install_signal_handlers(scheduler)

    if args.run_now:
              log.info("--run-now set: executing pause_ads.py once before starting schedule.")
        run_pause_ads(dry_run=args.dry_run)

    next_run = scheduler.get_jobs()[0].trigger
    log.info("Scheduler armed. Next fire based on: %s", next_run)
    log.info("Press Ctrl+C to stop.")

    try:
              scheduler.start()
except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


if __name__ == "__main__":
      main()
