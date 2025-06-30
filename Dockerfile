FROM python:3.9-slim

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir flask requests gunicorn apscheduler

ENV BASE_URL https://exposure.api.redbee.live
EXPOSE 34455

# Lengjum timeout í 120 s (yfirleitt nægir þegar EPG-ið tekur ~9 s)
CMD ["gunicorn", "--preload", "--timeout", "120", "-w", "1", "-b", "0.0.0.0:34455", "main:app"]