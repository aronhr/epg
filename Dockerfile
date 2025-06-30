# Use an official Python runtime as the base image
FROM python:3.9-slim

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir flask requests gunicorn apscheduler

ENV BASE_URL https://exposure.api.redbee.live
EXPOSE 34455

# --preload tryggir að scheduler-inn keyri bara einu sinni (í master-process) –
# 1 sync worker er nóg því við erum bara að þjóna static xml
CMD ["gunicorn", "--preload", "-w", "1", "-b", "0.0.0.0:34455", "main:app"]
