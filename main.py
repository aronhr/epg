from datetime import datetime, timezone, timedelta
from flask import Flask, send_file, jsonify
import requests
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import logging
import os
import pathlib
import threading

app = Flask(__name__)

BASE_URL = os.getenv("BASE_URL", "https://exposure.api.redbee.live")
EPG_FILE = pathlib.Path("epg.xml")
EPG_LOCK = threading.Lock()

logging.basicConfig(filename='logs/app.log', level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s', encoding='utf-8')

# 48‑hour window ────────────────────────────────────────────────────────────────
WINDOW_HOURS = 48


def format_date(date_str: str) -> str:
    """Return XMLTV date format (yyyyMMddHHmmss +0000)."""
    return date_str.replace(":", "").replace("-", "").replace("T", "").replace("Z", "") + " +0000"


def parse_iso(date_str: str) -> datetime:
    """Parse ISO‑8601 string with Z → aware datetime(UTC)."""
    return datetime.fromisoformat(date_str.replace('Z', '+00:00')).astimezone(timezone.utc)


def fetch_json(url: str):
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()


def get_epg_url(data: dict):
    for comp in data['components']:
        if comp['id'] == f"generator-epg-{data['id']}":
            return comp['internalUrl']


def build_epg():
    root = ET.Element("tv")
    cutoff = datetime.now(timezone.utc) + timedelta(hours=WINDOW_HOURS)

    top_url = (f"{BASE_URL}/api/internal/customer/Nova/businessunit/novatvprod/"
               "component/63b00b6f-cf6d-4bbb-bca5-c5107029608d?deviceGroup=web")
    outer = fetch_json(top_url)

    for ch in outer['channels']:
        slug = ch['channel']['slugs'][0]
        channel_el = ET.SubElement(root, "channel", id=slug)
        ET.SubElement(channel_el, "display-name").text = escape(ch['channel']['title'])
        if ch['channel']['images']:
            ET.SubElement(channel_el, "icon", src=ch['channel']['images'][0]['url'])

        epg_url = get_epg_url(fetch_json(BASE_URL + ch['channel']['action']['internalUrl']))
        assets = fetch_json(BASE_URL + epg_url)['assets']
        _add_programmes(root, assets, slug, cutoff)

    return ET.tostring(root, encoding='utf-8').decode('utf-8')


def _add_programmes(root: ET.Element, programmes: list, channel_slug: str, cutoff: datetime):
    for pr in programmes:
        start_dt = parse_iso(pr['startTime'])
        if start_dt > cutoff:
            continue  # beyond 48 h window → skip

        title_parts = pr['title'].split()
        season = episode = ""
        if len(title_parts) > 2 and title_parts[0].startswith('S') and title_parts[1].startswith('E'):
            season, episode = title_parts[0][1:], title_parts[1][1:]
            title = " ".join(title_parts[2:])
        else:
            title = pr['title']

        prog_el = ET.SubElement(root, "programme",
                                start=format_date(pr['startTime']),
                                stop=format_date(pr['endTime']),
                                channel=channel_slug)
        ET.SubElement(prog_el, "title").text = escape(title)
        ET.SubElement(prog_el, "desc").text = escape(pr['description'])
        ET.SubElement(prog_el, "series-number").text = season
        ET.SubElement(prog_el, "episode-number").text = episode
        if pr['images']:
            ET.SubElement(prog_el, "icon", src=pr['images'][0]['url'])


def generate_and_store():
    try:
        xml = build_epg()
        with EPG_LOCK:
            EPG_FILE.write_text(xml, encoding='utf-8')
        logging.info("EPG refreshed (next 48h) and stored.")
    except Exception as exc:
        logging.exception("EPG refresh failed: %s", exc)


# ─────────────────────────── Scheduler ─────────────────────────────────────────
scheduler = BackgroundScheduler(timezone="UTC")
# Hourly at XX:45
scheduler.add_job(generate_and_store, CronTrigger(minute=45))
# One‑shot immediate run in background thread
scheduler.add_job(generate_and_store, trigger='date', next_run_time=datetime.utcnow())
scheduler.start()


@app.route('/epg', methods=['GET'])
def epg():
    try:
        with EPG_LOCK:
            return send_file(EPG_FILE, mimetype='application/xml')
    except FileNotFoundError:
        return jsonify({"error": "EPG not yet generated"}), 503


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=34455)
