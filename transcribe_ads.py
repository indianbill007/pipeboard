#!/usr/bin/env python3
"""
transcribe_ads.py — fetch active video ads, transcribe with local Whisper,
propose hook-based renames. Dry-run only; does NOT call Meta to rename.

Run with Python 3.11 (where whisper is installed):
    /c/Python/Python311/python.exe transcribe_ads.py --sample 3
    /c/Python/Python311/python.exe transcribe_ads.py              # all active video ads

Output: reports/hook_rename_proposals_<timestamp>.json
"""
import argparse
import json
import logging
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Make ffmpeg findable by whisper regardless of which shell started us.
_FFMPEG_CANDIDATES = [
    r"C:\Users\Admin\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin",
]
for _dir in _FFMPEG_CANDIDATES:
    if os.path.isfile(os.path.join(_dir, "ffmpeg.exe")):
        os.environ["PATH"] = _dir + os.pathsep + os.environ.get("PATH", "")
        break

import yaml  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
import whisper  # noqa: E402

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
(ROOT / "reports").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "transcribe.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("transcribe")

load_dotenv(ROOT / ".env")
TOKEN = os.getenv("META_ACCESS_TOKEN")
if not TOKEN:
    log.error("Missing META_ACCESS_TOKEN in .env")
    sys.exit(1)

GRAPH = "https://graph.facebook.com/v21.0"


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


def video_ids_for_ad(ad_id: str) -> list:
    """Return distinct video_ids referenced by this ad's creative(s)."""
    try:
        creatives = graph_all(
            f"{ad_id}/adcreatives",
            fields="id,video_id,object_story_spec,asset_feed_spec",
        )
    except RuntimeError as e:
        log.warning(f"  ad={ad_id}: creative fetch failed: {e}")
        return []
    vids = []
    for c in creatives:
        if c.get("video_id"):
            vids.append(c["video_id"])
        oss = c.get("object_story_spec") or {}
        vd = (oss.get("video_data") or {}).get("video_id")
        if vd:
            vids.append(vd)
        for v in (c.get("asset_feed_spec") or {}).get("videos") or []:
            if v.get("video_id"):
                vids.append(v["video_id"])
    return list(dict.fromkeys(vids))  # dedupe, preserve order


def video_source(video_id: str) -> str:
    try:
        data = graph(video_id, fields="source")
    except RuntimeError as e:
        log.warning(f"  video={video_id}: source fetch failed: {e}")
        return ""
    return data.get("source", "")


def download(url: str, dest: str) -> bool:
    try:
        urllib.request.urlretrieve(url, dest)
        return True
    except Exception as e:
        log.warning(f"  download failed: {e}")
        return False


def extract_hook(segments, max_seconds: float = 6.0) -> str:
    parts = []
    for seg in segments or []:
        if seg.get("start", 0) >= max_seconds:
            break
        parts.append(seg.get("text", "").strip())
    hook = " ".join(parts).strip()
    # If whisper returned no segments but we do have text, fall back to first N words
    return hook


def propose_name(hook: str, max_chars: int = 70) -> str:
    cleaned = " ".join(hook.split())
    cleaned = cleaned.strip(" ,.!?;:—-")
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars].rsplit(" ", 1)[0] + "…"
    return f"[Hook] {cleaned}" if cleaned else ""


def list_active_video_ads(account_id: str, limit_ads: int | None) -> list:
    ads = graph_all(
        f"{account_id}/ads",
        fields="id,name,status,effective_status,created_time",
        effective_status='["ACTIVE"]',
        limit=500,
    )
    if limit_ads:
        ads = ads[:limit_ads]
    return ads


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sample", type=int, default=0,
                   help="Only process the first N ads across all accounts combined "
                        "(0 = process all active video ads).")
    p.add_argument("--account", action="append",
                   help="Restrict to one or more act_ ids (repeatable). Default: all visible.")
    p.add_argument("--model", default="base",
                   help="Whisper model size: tiny|base|small|medium|large. "
                        "Larger = slower but better accuracy. Default: base.")
    args = p.parse_args()

    log.info("=" * 72)
    log.info(f"Whisper model: {args.model} (loading — ~100MB for base, ~1.5GB for large)")
    model = whisper.load_model(args.model)

    visible = graph_all("me/adaccounts", fields="id,account_id,name")
    if args.account:
        targets = [a for a in visible if a["id"] in set(args.account)]
    else:
        targets = visible
    log.info(f"Accounts to scan: {len(targets)}")

    proposals = []
    processed = 0
    skipped_non_video = 0

    for acc in targets:
        acc_id, acc_name = acc["id"], acc["name"]
        remaining = (args.sample - processed) if args.sample else None
        if remaining is not None and remaining <= 0:
            break

        log.info(f"--- {acc_name} ({acc_id}) ---")
        ads = list_active_video_ads(acc_id, remaining)
        log.info(f"  {len(ads)} active ad(s) to inspect")

        for ad in ads:
            if args.sample and processed >= args.sample:
                break
            ad_id, ad_name = ad["id"], ad["name"]

            vids = video_ids_for_ad(ad_id)
            if not vids:
                skipped_non_video += 1
                continue

            vid = vids[0]
            src = video_source(vid)
            if not src:
                continue

            tmp_path = tempfile.mktemp(suffix=".mp4")
            try:
                t0 = time.time()
                log.info(f"  [{processed+1}] {ad_name[:50]}  downloading…")
                if not download(src, tmp_path):
                    continue

                log.info(f"  [{processed+1}] transcribing…")
                result = model.transcribe(tmp_path, verbose=False)
                elapsed = time.time() - t0

                full_text = (result.get("text") or "").strip()
                segments = result.get("segments") or []
                hook = extract_hook(segments)
                proposed = propose_name(hook)
                lang = result.get("language", "?")

                log.info(f"  [{processed+1}] {elapsed:.0f}s  lang={lang}  hook={hook[:80]!r}")
                log.info(f"      current: {ad_name}")
                log.info(f"      proposed: {proposed}")

                proposals.append({
                    "ad_id": ad_id,
                    "account_id": acc_id,
                    "account_name": acc_name,
                    "name_current": ad_name,
                    "name_proposed": proposed,
                    "hook": hook,
                    "language": lang,
                    "video_id": vid,
                    "transcript_preview": full_text[:400],
                    "transcribe_seconds": round(elapsed, 1),
                })
                processed += 1
            finally:
                if os.path.isfile(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

    out = ROOT / "reports" / f"hook_rename_proposals_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps({
        "run_at": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "processed": processed,
        "skipped_non_video": skipped_non_video,
        "proposals": proposals,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("=" * 72)
    log.info(f"Processed: {processed} video ads  |  Skipped (no video): {skipped_non_video}")
    log.info(f"Proposals file: {out}")
    log.info("NO ADS WERE RENAMED. Review the JSON and approve before applying.")


if __name__ == "__main__":
    main()
