import subprocess
import logging
import time
import os
import requests
from pathlib import Path


class StartupScript:
    """
    Helper class for tests to automatically deploy an app using a startup script from apps/
    Implements the context manager protocol to start and stop the script.
    """

    def __init__(self, cmd: list[str], wait_for_port: int, timeout: int = 30, cwd="/tmp"):
        self.cmd = cmd
        self.cwd = cwd
        self.wait_for_port = wait_for_port
        self.process = None
        self.timeout = timeout

    def __enter__(self):
        subprocess.run(["sudo", "docker", "container", "prune", "-f"], check=True)
        subprocess.run(["sudo", "docker", "network", "prune", "-f"], check=True)

        self.process = subprocess.Popen(
            self.cmd,
            cwd=self.cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1
        )

        start_time = time.time()
        while True:
            try:
                response = requests.get(f"http://localhost:{self.wait_for_port}", timeout=3)
                if response.status_code < 400:
                    break
            except requests.ConnectionError:
                pass

            if time.time() - start_time > self.timeout:
                raise TimeoutError(f"Timeout reached while waiting for port {self.wait_for_port} to respond.")
            time.sleep(1)

        logging.info("Startup command %s ran successfully.", self.cmd)
        return self.process

    def __exit__(self, exc_type, exc_value, traceback):
        if self.process:
            self.process.kill()


class RunDockerCompose(StartupScript):
    """Run a docker compose file from the test-network directory and wait for a port to respond."""

    def __init__(self, compose_file_path: str, wait_for_port, timeout: int = 30):
        full_path = Path(__file__).parent / "test-network" / compose_file_path
        compose_file_name = full_path.name if (full_path.suffix == ".yaml" or full_path.suffix == ".yml") else "docker-compose.yml"

        super().__init__(
            cmd=["docker", "compose", "up", "--abort-on-container-exit", "-f", compose_file_name],
            cwd=full_path.parent,
            wait_for_port=wait_for_port,
            timeout=timeout
        )
