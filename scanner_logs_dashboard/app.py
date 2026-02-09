import json
import os
import sqlite3
from pathlib import Path
from datetime import datetime
from flask import Flask, abort, redirect, render_template, request, send_from_directory, url_for

APP_ROOT = Path(__file__).parent
DEFAULT_BASE_DIR = Path("/tmp/scanner_logs")
BASE_DIR = Path(os.getenv("SCANNER_LOGS_DIR", DEFAULT_BASE_DIR))

app = Flask(__name__)


def _run_dir(run_name: str) -> Path:
    return BASE_DIR / run_name


def _list_runs():
    if not BASE_DIR.exists():
        return []

    runs = []
    for run_path in BASE_DIR.iterdir():
        if not run_path.is_dir():
            continue
        if not run_path.name.startswith("scanner-test-"):
            continue
        db_path = run_path / "scanner.db"
        stat = run_path.stat()
        runs.append({
            "name": run_path.name,
            "path": run_path,
            "db_exists": db_path.exists(),
            "mtime": stat.st_mtime,
            "mtime_human": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        })

    runs.sort(key=lambda r: r["mtime"], reverse=True)
    return runs


def _read_log_tail(path: Path, max_lines: int = 300):
    if not path.exists():
        return [], False

    with path.open("r", encoding="utf-8", errors="replace") as log_file:
        lines = log_file.readlines()

    if len(lines) > max_lines:
        return lines[-max_lines:], True
    return lines, False


def _load_run_data(run_path: Path):
    db_path = run_path / "scanner.db"
    scanner_log_path = run_path / "scanner.log"
    docker_log_path = run_path / "docker.log"
    screenshot_dir = run_path / "screenshots"

    data = {
        "db_path": db_path,
        "scanner_log_path": scanner_log_path,
        "docker_log_path": docker_log_path,
        "screenshots": [],
        "services": [],
        "endpoints": [],
        "found_credentials": [],
        "login_panels": [],
        "summary": {
            "services": 0,
            "endpoints": 0,
            "login_panels": 0,
            "found_credentials": 0,
            "screenshots": 0
        }
    }

    if screenshot_dir.exists():
        shots = sorted([p for p in screenshot_dir.iterdir() if p.is_file()])
        data["screenshots"] = shots
        data["summary"]["screenshots"] = len(shots)

    if db_path.exists():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            services = conn.execute("SELECT pk, host, port, https, _credentials FROM service").fetchall()
            endpoints = conn.execute(
                "SELECT pk, service_id, path, is_login, working_credentials FROM endpoint"
            ).fetchall()
        finally:
            conn.close()

        service_map = {}
        for row in services:
            protocol = "https" if row["https"] else "http"
            url = f"{protocol}://{row['host']}:{row['port']}"
            creds = None
            if row["_credentials"]:
                try:
                    creds = json.loads(row["_credentials"])
                except json.JSONDecodeError:
                    creds = None
            service_map[row["pk"]] = {
                "pk": row["pk"],
                "url": url,
                "credentials": creds or []
            }

        endpoint_list = []
        found_credentials = []
        login_panels = []
        for row in endpoints:
            service = service_map.get(row["service_id"])
            endpoint_url = None
            if service:
                endpoint_url = f"{service['url']}/{str(row['path']).lstrip('/')}"
            item = {
                "pk": row["pk"],
                "service_id": row["service_id"],
                "path": row["path"],
                "is_login": bool(row["is_login"]),
                "working_credentials": row["working_credentials"] or "",
                "url": endpoint_url
            }
            endpoint_list.append(item)

            if item["working_credentials"]:
                found_credentials.append(item)
            if item["is_login"]:
                login_panels.append(item)

        data["services"] = list(service_map.values())
        data["endpoints"] = endpoint_list
        data["found_credentials"] = found_credentials
        data["login_panels"] = login_panels

        data["summary"]["services"] = len(data["services"])
        data["summary"]["endpoints"] = len(endpoint_list)
        data["summary"]["login_panels"] = len(login_panels)
        data["summary"]["found_credentials"] = len(found_credentials)

    scanner_log_lines, scanner_truncated = _read_log_tail(scanner_log_path)
    docker_log_lines, docker_truncated = _read_log_tail(docker_log_path)
    data["scanner_log_lines"] = scanner_log_lines
    data["scanner_log_truncated"] = scanner_truncated
    data["docker_log_lines"] = docker_log_lines
    data["docker_log_truncated"] = docker_truncated

    return data


@app.route("/")
def index():
    runs = _list_runs()
    selected = request.args.get("run")
    if selected:
        return redirect(url_for("run_view", run_name=selected))
    return render_template("index.html", runs=runs, base_dir=str(BASE_DIR))


@app.route("/run/<run_name>")
def run_view(run_name: str):
    run_path = _run_dir(run_name)
    if not run_path.exists() or not run_path.is_dir():
        abort(404)

    runs = _list_runs()
    data = _load_run_data(run_path)
    return render_template(
        "run.html",
        runs=runs,
        run_name=run_name,
        base_dir=str(BASE_DIR),
        data=data
    )


@app.route("/run/<run_name>/screenshots/<path:filename>")
def screenshot(run_name: str, filename: str):
    run_path = _run_dir(run_name)
    shot_dir = run_path / "screenshots"
    if not shot_dir.exists():
        abort(404)
    return send_from_directory(shot_dir, filename)


@app.route("/health")
def health():
    return {"status": "ok", "base_dir": str(BASE_DIR)}


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8089, debug=True)
