#!/usr/bin/env python3

import subprocess
from pathlib import Path

CPUS = 4
MEMORY = "8G"
DISK = "30G"

class TestVM:
    def __init__(self, remove_existing=False):
        self.name = "nsip"

        if remove_existing:
            self.remove()

        result = subprocess.run(["/bin/sh", "-c", f"multipass list | grep {self.name}"], capture_output=True, text=True, check=False)
        if "Running" in result.stdout:
            return

        if "Stopped" in result.stdout:
            print("Starting existing VM...")
            subprocess.run(["multipass", "start", self.name], check=True)
        elif "Deleted" in result.stdout:
            print("Restoring deleted VM...")
            subprocess.run(["multipass", "restore", self.name], check=True)
        else:
            print("Launching fresh VM...")
            src_path = Path(__file__).parent.parent.parent.resolve()

            subprocess.run(["multipass", "launch",
                            "--name", self.name,
                            "--cloud-init", "tests/vm/vm-config.yaml",
                            "--disk",
                            DISK,
                            "--memory",
                            MEMORY,
                            "--cpus",
                            CPUS,
                            "--mount",
                            "./:/scanner",
                            "25.04"],
                            check=True,
                            cwd=src_path)

            # For some reason this does not want to run during cloud-init, so we do it here
            self.run_cmd("sudo -u ubuntu python3 -m pip install --user -r /scanner/requirements.txt --break-system-packages")

    def get_ip(self):
        result = subprocess.run(["/bin/sh", "-c", f"multipass info {self.name} | grep IPv4"], capture_output=True, text=True, check=True)
        return result.stdout.strip().split()[-1]

    def popen(self, cmd):
        return subprocess.Popen(["multipass", "exec", self.name, "--", "bash", "-c", cmd])

    def run_cmd(self, cmd, capture_output=False, check=True):
        return subprocess.run(["multipass", "exec", self.name, "--", "bash", "-c", cmd], check=check, capture_output=capture_output, text=True)

    def remove(self):
        print("Removing VM...")
        subprocess.run(["multipass", "delete", self.name], check=False)
        subprocess.run(["multipass", "purge"], check=False)

    def stop(self):
        subprocess.run(["multipass", "stop", self.name], check=False)
