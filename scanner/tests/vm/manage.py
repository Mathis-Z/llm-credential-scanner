#!/usr/bin/env python3

import subprocess
import os
import click
from pathlib import Path


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
                            "--cloud-init", "tests/vm/vm-config.yml",
                            "--disk",
                            "10G",
                            "--memory",
                            "4G",
                            "--cpus",
                            "2",
                            "--mount",
                            "./:/scanner",
                            "25.04"],
                            check=True,
                            cwd=src_path)

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


@click.command()
@click.argument("app_name", default="4ga_boards")
@click.option("--detach", "-d", is_flag=True, default=False)
@click.option("--clean", "-c", is_flag=True, default=False)
def run_app(app_name, detach=False, clean=False):
    vm = TestVM(remove_existing=clean)

    p = vm.popen(f"sudo /apps/{app_name}.sh")
    if not detach:
        p.wait()
    return p


if __name__ == '__main__':
    run_app() # pylint: disable=no-value-for-parameter
