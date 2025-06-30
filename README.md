# EPG (Electronic Program Guide) for Icelandic Television

This application fetches and serves an Electronic Program Guide (EPG) for Icelandic TV channels. It queries the Redbee **Exposure** API, converts the response to XMLTV‑compatible format, saves the XML to disk every hour at **XX:45 UTC**, and exposes it via a lightweight HTTP endpoint with millisecond latency.

## 📌 What’s new in v1.1

* **Background refresh with APScheduler** – the EPG is regenerated hourly at `:45` and written to `epg.xml`.
* **Instant responses** – the `/epg` route now serves the cached file instead of generating on‑request.
* **Shared volume** – the XML file is stored in `/data/epg.xml` so it survives container restarts.
* **Production‑ready Gunicorn launch** with `--preload` and a single worker.

---

## Features

* Hourly automatic fetch of EPG data
* Converts data to XMLTV schema
* Single HTTP endpoint (`/epg`) that returns XML instantly
* Structured logging to `/app/logs`
* Lightweight single‑container deployment (Flask + scheduler)

---

## Prerequisites

| Tool           | Minimum Version |
|----------------|-----------------|
| Docker         | 20.10           |
| Docker Compose | 2.0             |

---

## Quick Start

```bash
# 1. Pull the image
docker pull ghcr.io/aronhr/epg:main

# 2. Clone the repo (optional – only if you want to edit compose or code)
git clone https://github.com/aronhr/epg.git
cd epg

# 3. Start the service
docker compose up -d   # docker‑compose up -d works too
```

### Folder layout created on the host

```
docker-services/
└─ epg/
   ├─ logs/   # container logs
   └─ epg.xml # epg.xml lives here
```

---

## Configuration

| Variable   | Default                            | Description                                            |
| ---------- | ---------------------------------- | ------------------------------------------------------ |
| `BASE_URL` | `https://exposure.api.redbee.live` | Base URL of Redbee Exposure API                        |
| `TZ`       | `UTC`                              | Time‑zone inside the container (affects the scheduler) |

Set environment variables under `environment:` in `docker-compose.yml`.

---

## API

| Method | Path   | Description                                                       |
| ------ | ------ | ----------------------------------------------------------------- |
| `GET`  | `/epg` | Returns the latest `epg.xml` with `Content-Type: application/xml` |

Example:

```bash
curl http://localhost:34455/epg > epg.xml
```

---

## Logs

All logs are written to `./docker-services/epg/logs/app.log` on the host.

---

## Updating the image

```bash
docker pull ghcr.io/aronhr/epg:main
docker compose up -d
```

---

## Contributing

Pull requests are welcome! Please open an issue first to discuss major changes.

---

## License

MIT
