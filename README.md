# Real-Time Collaborative Editor

This project implements a real-time collaborative editor using Conflict-free Replicated Data Types (CRDTs) and a message broker for synchronization.

## Features

*   Real-time collaboration for multiple clients (text or drawing - TBD).
*   Synchronization via a message broker (e.g., RabbitMQ, Redis Pub/Sub - specific choice TBD).
*   CRDT-based data model for eventual consistency without locking.
*   Version history and undo functionality using periodic snapshots.

## Project Goal

The primary goal is to create a simple, minimally viable collaborative editor demonstrating the core concepts of CRDTs for synchronization in a distributed environment. This project avoids external libraries like Yjs to focus on the fundamental implementation details.

## Technology Stack (Planned)

*   **Language:** Python (assumed, can be changed)
*   **CRDT Implementation:** Custom implementation (e.g., Sequence CRDT for text)
*   **Message Broker:** TBD (e.g., RabbitMQ, Redis Pub/Sub, ZeroMQ)
*   **Client:** TBD (e.g., simple terminal UI, basic web UI using Flask/Django/FastAPI + JS)

## How to Run (Placeholder)

Instructions on setting up the environment, starting the broker, server, and clients will be added here.

## Running Locally (Without Docker)

1.  **Prerequisites:**
    *   Python 3.9+
    *   Redis server running (e.g., `redis-server` on `localhost:6379`)
2.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
3.  **Run the Server:**
    ```bash
    python server/main.py
    ```
4.  **Open Clients:** Open multiple browser tabs to `http://localhost:5000`.

## Running with Docker Compose (Recommended for Testing)

1.  **Prerequisites:**
    *   Docker ([https://www.docker.com/get-started](https://www.docker.com/get-started))
    *   Docker Compose (usually included with Docker Desktop)
2.  **Build and Run:**
    From the project root directory, run:
    ```bash
    docker-compose up --build
    ```
    *   `--build` forces Docker to rebuild the application image if the `Dockerfile` or copied files have changed.
    *   This will start both the Redis container and the Flask web application container.
3.  **Access the Application:** Open multiple browser tabs to `http://localhost:5000`.
4.  **Stopping:** Press `Ctrl+C` in the terminal where `docker-compose up` is running. To remove the containers, run `docker-compose down`.
5.  **Code Changes:** Thanks to the volume mount in `docker-compose.yml`, changes to the Python code (`.py` files) should be reflected automatically by the Flask development server inside the container (it will restart). Changes to `requirements.txt` or the `Dockerfile` will require rebuilding the image (`docker-compose up --build`).

## Validation Checklist

*   [ ] Show consistent state across multiple users.
*   [ ] Simulate network delay and confirm proper synchronization.
*   [ ] Demonstrate editing sessions and replay/undo. 