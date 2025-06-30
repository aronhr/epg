from __future__ import annotations

import logging
import os
import pathlib
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List

import requests
import xml.etree.ElementTree as ET
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask, jsonify, send_file
from xml.sax.saxutils import escape

# ----------------------------------------------------------------------------
# Configuration & globals
# ----------------------------------------------------------------------------

BASE_URL = os.getenv("BASE_URL", "https://exposure.api.redbee.live")
EPG_FILE = pathlib.Path("/data/epg.xml")        # must live in a write‑able volume
LOG_FILE = pathlib.Path("logs/app.log")

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8",
)
logger = logging.getLogger("epg")

app = Flask(__name__)
_lock = threading.Lock()

# ----------------------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------------------

def format_date(iso_str: str) -> str:
    """Convert ISO‑8601 → XMLTV datetime (YYYYMMDDHHMMSS +0000)."""
    return (
        iso_str.replace(":", "").replace("-", "").replace("T", "").replace("Z", "")
        + " +0000"
    )


def fetch_json(url: str) -> Dict[str, Any]:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def get_epg_url(comp_data: Dict[str, Any]) -> str | None:
    """Return the internal EPG URL from a component JSON blob."""
    for comp in comp_data.get("components", []):
        if comp.get("id") == f"generator-epg-{comp_data['id']}":
            return comp.get("internalUrl")
    return None


def build_epg() -> str:
    """Build XMLTV from Redbee API (no date cutoff)."""

    root = ET.Element("tv")

    # Top‑level component listing all channels
    listing_url = (
        f"{BASE_URL}/api/internal/customer/Nova/businessunit/novatvprod/"
        "component/63b00b6f-cf6d-4bbb-bca5-c5107029608d?deviceGroup=web"
    )
    outer = fetch_json(listing_url)

    for ch in outer.get("channels", []):
        ch_info = ch["channel"]
        slug = ch_info["slugs"][0]
        title = ch_info["title"]

        ch_el = ET.SubElement(root, "channel", id=slug)
        ET.SubElement(ch_el, "display-name").text = escape(title)
        if ch_info.get("images"):
            ET.SubElement(ch_el, "icon", src=ch_info["images"][0]["url"])

        # Fetch channel‑specific EPG JSON
        comp_url = BASE_URL + ch_info["action"]["internalUrl"]
        epg_url = get_epg_url(fetch_json(comp_url))
        if not epg_url:
            logger.warning("No EPG URL for channel %s", slug)
            continue

        for asset in fetch_json(BASE_URL + epg_url).get("assets", []):
            title, season, episode = _parse_title(asset["title"])

            prog = ET.SubElement(
                root,
                "programme",
                start=format_date(asset["startTime"]),
                stop=format_date(asset["endTime"]),
                channel=slug,
            )
            ET.SubElement(prog, "title").text = escape(title)
            ET.SubElement(prog, "desc").text = escape(asset["description"])
            ET.SubElement(prog, "series-number").text = season
            ET.SubElement(prog, "episode-number").text = episode
            if asset.get("images"):
                ET.SubElement(prog, "icon", src=asset["images"][0]["url"])

    return ET.tostring(root, encoding="utf-8").decode("utf-8")


def _parse_title(raw: str) -> tuple[str, str, str]:
    """Extract title, season (Sxx) and episode (Exx) if present."""
    parts = raw.strip().split()
    if len(parts) > 2 and parts[0].startswith("S") and parts[1].startswith("E"):
        return " ".join(parts[2:]), parts[0][1:], parts[1][1:]
    return raw.strip(), "", ""


# ----------------------------------------------------------------------------
# Scheduler job – runs in the background thread pool
# ----------------------------------------------------------------------------

def generate_and_store() -> None:
    try:
        logger.info("Refreshing full EPG …")
        xml = build_epg()
        with _lock:
            EPG_FILE.write_text(xml, encoding="utf-8")
        logger.info("EPG written to %s (%.1f KB)", EPG_FILE, EPG_FILE.stat().st_size / 1024)
    except Exception:  # noqa: BLE001
        logger.exception("EPG refresh failed")


scheduler = BackgroundScheduler(timezone="UTC")
scheduler.add_job(generate_and_store, CronTrigger(minute=45))  # XX:45 hourly
# Fire first run immediately in its own thread
scheduler.add_job(generate_and_store, trigger="date", next_run_time=datetime.utcnow())
scheduler.start()

# ----------------------------------------------------------------------------
# Flask route
# ----------------------------------------------------------------------------

@app.route("/epg", methods=["GET"])
def epg_endpoint():
    with _lock:
        if not EPG_FILE.exists():
            return jsonify({"error": "EPG not yet generated"}), 503
        return send_file(EPG_FILE, mimetype="application/xml")


if __name__ == "__main__":
    # Development only – in production run via gunicorn
    app.run(host="0.0.0.0", port=34455)
