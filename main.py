from __future__ import annotations

import logging
import os
import pathlib
import threading
from datetime import datetime, timezone, timedelta
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
SYN_API_URL = os.getenv("SYN_API_URL", "https://www.syn.is/api/epg")
EPG_FILE = pathlib.Path("data/epg.xml")        # must live in a write‑able volume
LOG_FILE = pathlib.Path("logs/app.log")

# Ensure directories exist
EPG_FILE.parent.mkdir(parents=True, exist_ok=True)
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# Configure logging
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


def normalize_channel_slug(slug: str, source: str = "") -> str:
    """Normalize channel slugs for consistent matching between sources."""
    # Remove hyphens and convert to lowercase
    normalized = slug.lower().replace("-", "")
    
    # Handle specific channel mappings
    channel_mappings = {
        # syn.is -> redbee mappings
        "synsport": "synsport1",
        # Add more mappings here as needed
        # "syn_channel": "redbee_channel",
    }
    
    # Apply mappings if this is from syn.is source
    if source == "syn" and normalized in channel_mappings:
        normalized = channel_mappings[normalized]
    
    return normalized


def build_epg() -> str:
    """Build XMLTV from Redbee API and syn.is API (merged data)."""

    root = ET.Element("tv")
    channels_data = {}  # Store channel info and programmes

    # First, get data from Redbee API
    logger.info("Fetching EPG data from Redbee API...")
    try:
        listing_url = (
            f"{BASE_URL}/api/internal/customer/Nova/businessunit/novatvprod/"
            "component/63b00b6f-cf6d-4bbb-bca5-c5107029608d?deviceGroup=web"
        )
        outer = fetch_json(listing_url)

        for ch in outer.get("channels", []):
            ch_info = ch["channel"]
            slug = normalize_channel_slug(ch_info["slugs"][0], "redbee")
            title = ch_info["title"]

            # Store channel info
            channels_data[slug] = {
                "title": title,
                "images": ch_info.get("images", []),
                "programmes": []
            }

            # Fetch channel‑specific EPG JSON
            comp_url = BASE_URL + ch_info["action"]["internalUrl"]
            epg_url = get_epg_url(fetch_json(comp_url))
            if not epg_url:
                logger.warning("No EPG URL for channel %s", slug)
                continue

            for asset in fetch_json(BASE_URL + epg_url).get("assets", []):
                title_parsed, season, episode = _parse_title(asset["title"])

                programme = {
                    "start": format_date(asset["startTime"]),
                    "stop": format_date(asset["endTime"]),
                    "title": title_parsed,
                    "desc": asset["description"],
                    "season": season,
                    "episode": episode,
                    "images": asset.get("images", []),
                    "source": "redbee"
                }
                channels_data[slug]["programmes"].append(programme)

        logger.info("Fetched data for %d channels from Redbee API", len(channels_data))
    except Exception as e:
        logger.warning("Failed to fetch from Redbee API: %s", e)

    # Second, enhance with data from syn.is API
    logger.info("Fetching EPG data from syn.is API...")
    try:
        syn_channels = fetch_syn_channels()
        
        # Get data for today and next few days
        today = datetime.now(timezone.utc)
        dates_to_fetch = []
        for i in range(7):  # Fetch 7 days of data
            date = (today + timedelta(days=i)).strftime('%Y-%m-%d')
            dates_to_fetch.append(date)

        for slug in syn_channels:
            # Normalize the slug by removing hyphens and applying mappings
            normalized_slug = normalize_channel_slug(slug, "syn")
            
            # Ensure channel exists even if no programmes are found
            if normalized_slug not in channels_data:
                channels_data[normalized_slug] = {
                    "title": slug.upper(),  # Use the original slug as title if no better name is found
                    "images": [],
                    "programmes": []
                }
            
            has_programmes = False
            
            for date in dates_to_fetch:
                syn_programmes = fetch_syn_epg(slug, date)
                
                for prog_data in syn_programmes:
                    has_programmes = True
                    # Map syn.is channel slug to our channel structure (normalize and apply mappings)
                    channel_slug = normalize_channel_slug(prog_data.get("midill", slug), "syn")
                    
                    # Update channel title if we have better information
                    if prog_data.get("midill_heiti"):
                        channels_data[channel_slug]["title"] = prog_data.get("midill_heiti")

                    # Calculate end time from start time and duration
                    start_time = prog_data["upphaf"]
                    end_time = calculate_end_time(start_time, prog_data.get("slotlengd", "01:00"))

                    # Create programme entry
                    programme = {
                        "start": format_syn_date(start_time),
                        "stop": format_syn_date(end_time),
                        "title": prog_data.get("isltitill") or prog_data.get("titill", ""),
                        "desc": prog_data.get("lysing", ""),
                        "season": str(prog_data.get("seria", "")),
                        "episode": str(prog_data.get("thattur", "")),
                        "images": [],
                        "source": "syn",
                        "category": prog_data.get("flokkur", ""),
                        "live": bool(prog_data.get("beint", 0)),
                        "premiere": bool(prog_data.get("frumsyning", 0))
                    }

                    # Check if we already have this programme from Redbee (avoid duplicates)
                    existing = False
                    for existing_prog in channels_data[channel_slug]["programmes"]:
                        if (existing_prog["start"] == programme["start"] and 
                            existing_prog["title"].lower() == programme["title"].lower()):
                            # Enhance existing programme with syn.is data
                            if not existing_prog.get("category") and programme["category"]:
                                existing_prog["category"] = programme["category"]
                            if not existing_prog.get("live"):
                                existing_prog["live"] = programme["live"]
                            if not existing_prog.get("premiere"):
                                existing_prog["premiere"] = programme["premiere"]
                            existing = True
                            break
                    
                    if not existing:
                        channels_data[channel_slug]["programmes"].append(programme)
            
            # If no programmes were found for this channel, create a placeholder
            if not has_programmes and not channels_data[normalized_slug]["programmes"]:
                now = datetime.now(timezone.utc)
                placeholder_programme = {
                    "start": format_date(now.isoformat() + 'Z'),
                    "stop": format_date((now + timedelta(hours=24)).isoformat() + 'Z'),
                    "title": "No programming information available",
                    "desc": "No programme schedule is currently available for this channel.",
                    "season": "",
                    "episode": "",
                    "images": [],
                    "source": "placeholder",
                    "category": "Information",
                    "live": False,
                    "premiere": False
                }
                channels_data[normalized_slug]["programmes"].append(placeholder_programme)

        logger.info("Enhanced/added data from syn.is API")
    except Exception as e:
        logger.warning("Failed to fetch from syn.is API: %s", e)

    # Build XML from merged data
    for channel_slug, channel_info in channels_data.items():
        ch_el = ET.SubElement(root, "channel", id=channel_slug)
        ET.SubElement(ch_el, "display-name").text = escape(channel_info["title"])
        if channel_info["images"]:
            ET.SubElement(ch_el, "icon", src=channel_info["images"][0]["url"])

        # Sort programmes by start time
        sorted_programmes = sorted(channel_info["programmes"], 
                                 key=lambda x: x["start"])

        for programme in sorted_programmes:
            prog = ET.SubElement(
                root,
                "programme",
                start=programme["start"],
                stop=programme["stop"],
                channel=channel_slug,
            )
            ET.SubElement(prog, "title").text = escape(programme["title"])
            ET.SubElement(prog, "desc").text = escape(programme["desc"])
            
            if programme["season"]:
                ET.SubElement(prog, "series-number").text = programme["season"]
            if programme["episode"]:
                ET.SubElement(prog, "episode-number").text = programme["episode"]
            
            if programme["images"]:
                ET.SubElement(prog, "icon", src=programme["images"][0]["url"])
            
            # Add syn.is specific data
            if programme.get("category"):
                ET.SubElement(prog, "category").text = escape(programme["category"])
            if programme.get("live"):
                ET.SubElement(prog, "live")
            if programme.get("premiere"):
                ET.SubElement(prog, "premiere")

    logger.info("Built EPG with %d channels and programmes", len(channels_data))
    return ET.tostring(root, encoding="utf-8").decode("utf-8")


def _parse_title(raw: str) -> tuple[str, str, str]:
    """Extract title, season (Sxx) and episode (Exx) if present."""
    parts = raw.strip().split()
    if len(parts) > 2 and parts[0].startswith("S") and parts[1].startswith("E"):
        return " ".join(parts[2:]), parts[0][1:], parts[1][1:]
    return raw.strip(), "", ""


def fetch_syn_channels() -> List[str]:
    """Fetch list of channel slugs from syn.is API."""
    try:
        response = requests.get(SYN_API_URL, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.warning("Failed to fetch syn.is channels: %s", e)
        return []


def fetch_syn_epg(slug: str, date: str) -> List[Dict[str, Any]]:
    """Fetch EPG data for a specific channel and date from syn.is API."""
    try:
        url = f"{SYN_API_URL}/{slug}/{date}"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.warning("Failed to fetch syn.is EPG for %s on %s: %s", slug, date, e)
        return []


def format_syn_date(iso_str: str) -> str:
    """Convert syn.is ISO‑8601 → XMLTV datetime (YYYYMMDDHHMMSS +0000)."""
    # syn.is returns ISO format like "2025-07-31T18:30:00Z"
    return format_date(iso_str)


def calculate_end_time(start_time: str, duration_str: str) -> str:
    """Calculate end time from start time and duration string (HH:MM format)."""
    try:
        # Parse start time
        start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        
        # Parse duration (format: "HH:MM")
        duration_parts = duration_str.split(':')
        hours = int(duration_parts[0])
        minutes = int(duration_parts[1])
        
        # Calculate end time
        end_dt = start_dt + timedelta(hours=hours, minutes=minutes)
        
        # Convert back to ISO format with Z
        return end_dt.strftime('%Y-%m-%dT%H:%M:%S') + 'Z'
    except Exception as e:
        logger.warning("Failed to calculate end time: %s", e)
        # Fallback: add 1 hour to start time
        start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        end_dt = start_dt + timedelta(hours=1)
        return end_dt.strftime('%Y-%m-%dT%H:%M:%S') + 'Z'


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
