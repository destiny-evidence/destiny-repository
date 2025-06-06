"""Import fake data into a server using a simple HTTP server."""  # noqa: INP001

# ruff: noqa: G004
import argparse
import http.server
import logging
import socketserver
import threading
import uuid
from difflib import ndiff
from functools import partial
from pathlib import Path

import httpx

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

finished = threading.Condition()


class RequestHandler(http.server.SimpleHTTPRequestHandler):
    """Custom request handler to serve files from the current directory."""

    def __init__(
        self,
        *args,  # noqa: ANN002
        filename: str,
        callback_id: str,
        **kwargs,  # noqa: ANN003
    ) -> None:
        """Initialize the request handler with a specific filename."""
        self._filename = filename
        self._callback_id = callback_id
        super().__init__(*args, **kwargs)

    def log_message(self, log_format, *args):  # noqa: ANN001, ANN002, ANN201
        """Suppress logging by overriding the log_message method."""

    def do_GET(self) -> None:  # noqa: N802
        """Handle GET requests. Only serves the specified file."""
        if self.path == f"/{self._filename}":
            return super().do_GET()

        return self.send_error(404, "File not found")

    def do_POST(self) -> None:  # noqa: N802
        """Handle POST requests."""
        # For simplicity, we can just acknowledge the POST request
        self.send_response(200)
        self.end_headers()
        logger.info(f"Callback ID: {self._callback_id}")
        logger.info(f"Received POST request for {self.path}")
        if self.path == f"/complete/{self._callback_id}":
            with finished:
                logger.info("Received request to complete import.")
                finished.notify_all()
        else:
            logger.info(f"expected /complete/{self._callback_id} but got {self.path}")
            logger.info("".join(ndiff([f"/complete/{self._callback_id}"], [self.path])))


def run_server(
    filename: str, callback_id: str, port: int = 8001
) -> socketserver.TCPServer:
    """Run a simple HTTP server in a separate thread."""
    handler = partial(RequestHandler, filename=filename, callback_id=callback_id)

    httpd = socketserver.TCPServer(("", port), handler)
    logger.info(f"Serving at http://localhost:{port}")
    return httpd


def start_server_thread(
    filename: str,
    callback_id: str,
    port: int = 8001,
) -> tuple[threading.Thread, socketserver.TCPServer]:
    """Start the server in a separate thread."""
    httpd = run_server(filename, callback_id, port=port)
    server_thread = threading.Thread(target=httpd.serve_forever)
    server_thread.daemon = True  # Thread will exit when main program exits
    server_thread.start()
    return server_thread, httpd


def check_file_exists(filename: str) -> None:
    """Check if the file exists."""
    if not Path(filename).is_file():
        msg = f"The file {filename} does not exist."
        raise FileNotFoundError(msg)


def import_fake_data(filename: str, callback_id: str) -> None:
    """Import fake data into the server."""
    check_file_exists(filename)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # Suppress httpx logs
    client = httpx.Client(base_url="http://localhost:8000")
    # Register a new import
    logger.info("Registering a new import...")
    import_record = client.post(
        "/imports/record/",
        json={
            "processor_name": "test_robot",
            "processor_version": "0.0.1",
            "source_name": "test_source",
            "expected_reference_count": -1,
        },
    ).json()

    # Register an import batch

    logger.info("Registering an import batch...")
    batch = client.post(
        f"/imports/record/{import_record['id']}/batch/",
        json={
            "storage_url": f"http://localhost:8001/{filename}",
            "callback_url": f"http://localhost:8001/complete/{callback_id}",
        },
    ).json()
    logger.info(f"Registered batch: {batch['id']} for file: {filename}")

    finalize_resp = client.patch(f"/imports/record/{import_record["id"]}/finalise/")
    finalize_resp.raise_for_status()


if __name__ == "__main__":
    # Start the server in a background thread
    # Use argparse for command-line arguments
    parser = argparse.ArgumentParser(description="Import fake data into the server.")
    parser.add_argument("filename", type=str, help="JSONL file to import")
    args = parser.parse_args()
    callback_id = str(uuid.uuid4())

    thread, httpd = start_server_thread(args.filename, callback_id)
    try:
        import_fake_data(args.filename, callback_id)
        # Keep the main thread running
        logger.info("Main thread is running. Press Ctrl+C to stop.")
        with finished:
            finished.wait()  # Wait until the server is done
        logger.info("Import completed successfully.")
    except KeyboardInterrupt:
        logger.info("Server is shutting down...")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=1)  # Ensure the thread is cleaned up
