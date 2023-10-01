from flask import Flask, jsonify
import requests
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
import logging
import os

app = Flask(__name__)

# Fetch BASE_URL from environment variables
BASE_URL = os.environ.get("BASE_URL", "https://exposure.api.redbee.live")

root = ET.Element("tv")

# Set up logging
logging.basicConfig(filename='logs/app.log',
                    level=logging.INFO,
                    encoding='utf-8',
                    format='%(asctime)s %(levelname)s %(name)s %(message)s')


def format_date(date):
    """
    Format the date to the correct format.
    :param date:
    :return:
    """
    return date.replace(":", "").replace("-", "").replace("T", "").replace("Z", "") + " +0000"


def get_epg_url(data):
    """
    Get the EPG URL from the JSON data.
    :param data:
    :return:
    """
    for component in data['components']:
        if component['id'] == f'generator-epg-{data["id"]}':
            return component['internalUrl']


def fetch_json_from_webservice(url):
    """
    Fetch JSON data from a web service.
    :param url:
    :return:
    """
    response = requests.get(url)
    response.raise_for_status()  # Raise HTTPError for bad responses
    return response.json()


def get_episode_details(title):
    """
    Get episode details from the JSON data.
    If the title starts with S2 E20, then the episode is season 2, episode 20.
    :param title: Episode or movie title
    :return: tuple of the title, season and episode
    """
    title = title.strip()
    season = ""
    episode = ""
    splitted_title = title.split(" ")
    if len(splitted_title) > 2 and splitted_title[0].startswith("S") and splitted_title[1].startswith("E"):
        season = splitted_title[0].replace("S", "")
        episode = splitted_title[1].replace("E", "")
        title = " ".join(splitted_title[2::])
    return title, season, episode


def create_channels(json_data):
    """
    Create the channel elements.
    :param json_data:
    :return:
    """
    for channel_data in json_data['channels']:
        channel = ET.SubElement(root, "channel", id=channel_data['channel']['slugs'][0])
        ET.SubElement(channel, "display-name").text = escape(channel_data['channel']['title'])
        ET.SubElement(channel, "icon", src=channel_data['channel']['images'][0]['url'])
        epg_url = get_epg_url(fetch_json_from_webservice(BASE_URL + channel_data['channel']['action']['internalUrl']))
        create_programme_element(fetch_json_from_webservice(BASE_URL + epg_url), channel_data['channel']['slugs'][0])
    return ET.tostring(root, encoding='utf-8', method='xml').decode('utf-8')


def create_programme_element(channel_data, channel_slug):
    """
    Create the programme elements.
    :param channel_data:
    :param channel_slug:
    :return:
    """
    for program_data in channel_data['assets']:

        title, season, episode = get_episode_details(program_data['title'])

        program = ET.SubElement(root, "programme",
                                start=format_date(program_data['startTime']),
                                stop=format_date(program_data['endTime']),
                                channel=channel_slug)
        ET.SubElement(program, "title").text = escape(title)
        ET.SubElement(program, "desc").text = escape(program_data['description'])
        ET.SubElement(program, "series-number").text = escape(season)
        ET.SubElement(program, "episode-number").text = escape(episode)
        ET.SubElement(program, "icon", src=program_data['images'][0]['url'])


def save_xml_to_file(xml_str, file_path):
    """
    Save the XML data to a file.
    :param xml_str: The XML data as a string.
    :param file_path: The path where to save the XML file.
    :return:
    """
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(xml_str)


@app.route('/epg', methods=['GET'])
def get_epg_data():
    try:
        url = f"{BASE_URL}/api/internal/customer/Nova/businessunit/novatvprod/component/63b00b6f-cf6d-4bbb-bca5-c5107029608d?deviceGroup=web"
        json_data = fetch_json_from_webservice(url)
        xml_str = create_channels(json_data)

        # Return XML as response
        return xml_str, 200, {'Content-Type': 'application/xml'}
    except requests.RequestException as e:
        logging.error(f"Error fetching data from web service: {e}")
        return jsonify({"error": "Failed to fetch data from web service"}), 500
    except ET.ParseError as e:
        logging.error(f"Error parsing XML: {e}")
        return jsonify({"error": "Failed to parse XML data"}), 500
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return jsonify({"error": "An unexpected error occurred"}), 500


if __name__ == "__main__":
    app.run(port=34455)

