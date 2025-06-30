from flask import Flask, send_file, jsonify
import requests, xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import logging, os, pathlib, threading

app = Flask(__name__)

BASE_URL = os.getenv("BASE_URL", "https://exposure.api.redbee.live")
EPG_FILE  = pathlib.Path("epg.xml")        # deilt volume
EPG_LOCK  = threading.Lock()                     # tryggir að les/rit skarist ekki

logging.basicConfig(filename='logs/app.log', level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s', encoding='utf-8')

def format_date(date):
    return date.replace(":", "").replace("-", "").replace("T", "").replace("Z", "") + " +0000"

def fetch_json(url):
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()

def get_epg_url(data):
    for c in data['components']:
        if c['id'] == f'generator-epg-{data["id"]}':
            return c['internalUrl']

def build_epg():
    root = ET.Element("tv")
    url = (f"{BASE_URL}/api/internal/customer/Nova/businessunit/novatvprod/"
           "component/63b00b6f-cf6d-4bbb-bca5-c5107029608d?deviceGroup=web")
    outer = fetch_json(url)

    for ch in outer['channels']:
        slug = ch['channel']['slugs'][0]
        channel = ET.SubElement(root, "channel", id=slug)
        ET.SubElement(channel, "display-name").text = escape(ch['channel']['title'])
        if ch['channel']['images']:
            ET.SubElement(channel, "icon", src=ch['channel']['images'][0]['url'])

        epg_url = get_epg_url(fetch_json(BASE_URL + ch['channel']['action']['internalUrl']))
        for show in fetch_json(BASE_URL + epg_url)['assets']:
            title_parts = show['title'].split()
            season = episode = ""
            if len(title_parts) > 2 and title_parts[0].startswith("S") and title_parts[1].startswith("E"):
                season, episode = title_parts[0][1:], title_parts[1][1:]
                title = " ".join(title_parts[2:])
            else:
                title = show['title']

            p = ET.SubElement(root, "programme",
                              start=format_date(show['startTime']),
                              stop=format_date(show['endTime']),
                              channel=slug)
            ET.SubElement(p, "title").text = escape(title)
            ET.SubElement(p, "desc").text  = escape(show['description'])
            ET.SubElement(p, "series-number").text  = season
            ET.SubElement(p, "episode-number").text = episode
            if show['images']:
                ET.SubElement(p, "icon", src=show['images'][0]['url'])

    return ET.tostring(root, encoding='utf-8').decode('utf-8')

def generate_and_store():
    try:
        xml = build_epg()
        with EPG_LOCK:
            EPG_FILE.write_text(xml, encoding='utf-8')
        logging.info("EPG refreshed and stored.")
    except Exception as e:
        logging.exception("EPG refresh failed: %s", e)

# ---------- Scheduler ----------
scheduler = BackgroundScheduler(timezone="UTC")
scheduler.add_job(generate_and_store, CronTrigger(minute=45))  # XX:45 hvers klukkutíma
scheduler.start()

# Frum keyrslan svo skráin sé til strax við ræsingu
print("Generating EPG for the first time...")
generate_and_store()

# ---------- API ----------
@app.route('/epg', methods=['GET'])
def epg():
    try:
        with EPG_LOCK:
            return send_file(EPG_FILE, mimetype='application/xml')
    except FileNotFoundError:
        return jsonify({"error": "EPG not yet generated"}), 503

if __name__ == "__main__":
    # Í dev-umhverfi (ekki production gunicorn) – gott í quick-testing
    app.run(host="0.0.0.0", port=34455)
