# EPG Flask Application

This application fetches EPG (Electronic Program Guide) data and serves it in real time. 
The application interacts with the Redbee API to obtain the data, processes it, and provides the data in a structured XML format.

## Features

- Fetches EPG data in real-time.
- Processes and structures the data into XML.
- Serves the XML data over a web endpoint for easy consumption.

## Prerequisites

- [Docker](https://www.docker.com/get-started)
- [Docker Compose](https://docs.docker.com/compose/install/)

## Setup & Running

1. **Pull the Docker Image from GitHub Container Registry**:
    ```bash
    docker pull ghcr.io/aronhr/epg:main
    ```

2. **Clone the Repository** (if you haven't already):
    ```bash
    git clone git@github.com:aronhr/epg.git
    cd epg
    ```

3. **Build and Run with Docker Compose**:
    ```bash
    docker-compose up -d
    ```

4. **Access the Application**:
   Once the Docker container is running, the application can be accessed at:

## API Endpoints

- `/epg`: Fetch the EPG data in XML format.

## Logging

Logs for the application are stored in the `./docker-services/epg/logs` directory on the host machine.

## Contributing

If you wish to contribute to this project, please fork the repository and submit a pull request.

## License

[MIT License](LICENSE)
