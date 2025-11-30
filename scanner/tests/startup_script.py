import subprocess
import logging


class StartupScript:
    """
    Helper class for tests to automatically deploy an app using a startup script from apps/
    Implements the context manager protocol to start and stop the script.
    """

    def __init__(self, script, wait_string):
        self.script = script
        self.wait_string = wait_string
        self.process = None

    def __enter__(self):
        subprocess.run(["sudo", "docker", "container", "prune", "-f"], check=True)
        subprocess.run(["sudo", "docker", "network", "prune", "-f"], check=True)

        self.process = subprocess.Popen(
            ["sudo", "/bin/bash", self.script],
            cwd="/tmp",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1
        )
        for line in self.process.stdout:
            print(line.strip())
            if self.wait_string in line:
                break
        logging.info("Startup script %s has started successfully.", self.script)
        return self.process

    def __exit__(self, exc_type, exc_value, traceback):
        if self.process:
            self.process.kill()
