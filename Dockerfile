# Use an official Python runtime as the base image
FROM python:3.9-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install required packages
RUN pip install --no-cache-dir flask requests

# Specify the environment variable for the BASE_URL
ENV BASE_URL https://exposure.api.redbee.live

# Make port 5000 available to the world outside this container
EXPOSE 34455

# Define the command to run your app using gunicorn (a production-ready WSGI server)
# You'll need to install gunicorn in your app
RUN pip install gunicorn
CMD ["gunicorn", "-b", "0.0.0.0:34455", "main:app"]
