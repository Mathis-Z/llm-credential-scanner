import ast
import json
import os
import re
import sqlite3
from pathlib import Path
from datetime import datetime
from flask import Flask, abort, redirect, render_template, request, send_from_directory, url_for

APP_ROOT = Path(__file__).parent
DEFAULT_BASE_DIR = Path("/tmp/scan_artifacts")
BASE_DIR = Path(os.getenv("SCANNER_LOGS_DIR", DEFAULT_BASE_DIR))

app = Flask(__name__)


def _is_safe_run_name(value: str) -> bool:
    if not value:
        return False
    if value in {".", ".."}:
        return False
    if any(sep in value for sep in ("/", "\\")):
        return False
    return bool(re.match(r"^[A-Za-z0-9._-]+$", value))


def _run_dir(run_name: str) -> Path:
    return BASE_DIR / run_name


def _run_state(run_path: Path):
    db_path = run_path / "scanner.db"
    scanner_log_path = run_path / "scanner.log"
    docker_log_path = run_path / "docker.log"
    screenshot_dir = run_path / "screenshots"

    def safe_stat(path: Path):
        if not path.exists():
            return {"mtime": 0, "size": 0}
        stat = path.stat()
        return {"mtime": stat.st_mtime, "size": stat.st_size}

    screenshots = 0
    if screenshot_dir.exists():
        screenshots = len([p for p in screenshot_dir.iterdir() if p.is_file()])

    return {
        "run": run_path.name,
        "db": safe_stat(db_path),
        "scanner_log": safe_stat(scanner_log_path),
        "docker_log": safe_stat(docker_log_path),
        "screenshots": screenshots,
        "run_mtime": run_path.stat().st_mtime if run_path.exists() else 0
    }


def _list_runs():
    if not BASE_DIR.exists():
        return []

    runs = []
    for run_path in BASE_DIR.iterdir():
        if not run_path.is_dir():
            continue
        # if not run_path.name.startswith("scanner-test-"):
        #     continue
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


def _read_log_full(path: Path):
    if not path.exists():
        return None

    with path.open("r", encoding="utf-8", errors="replace") as log_file:
        return log_file.read()


def _log_path(run_path: Path, log_name: str):
    log_map = {
        "scanner": "scanner.log",
        "docker": "docker.log"
    }
    filename = log_map.get(log_name)
    if not filename:
        return None
    return run_path / filename


def _parse_screenshot_name(name: str):
    match = re.match(
        r"^endpoint-(\d+)_(.+)_user-(.+)_pass-(.+)_(before|after)_(\d+)\.png$",
        name
    )
    if not match:
        return None

    endpoint_pk = int(match.group(1))
    prefix = match.group(2)
    user = match.group(3)
    pwd = match.group(4)
    phase = match.group(5)
    ts = int(match.group(6))

    parts = prefix.split("_")
    label = parts[-1] if parts else "unknown"
    host_path = "_".join(parts[:-1]) if len(parts) > 1 else "unknown"

    return {
        "endpoint_pk": endpoint_pk,
        "host_path": host_path,
        "label": label,
        "user": user,
        "password": pwd,
        "phase": phase,
        "ts": ts
    }


def _parse_keywords(raw_value):
    if raw_value is None:
        return []

    if isinstance(raw_value, (list, tuple)):
        return [str(item).strip() for item in raw_value if str(item).strip()]

    try:
        loaded = json.loads(raw_value)
        if loaded is None:
            return []
        if isinstance(loaded, str):
            return [loaded.strip()] if loaded.strip() else []
        if isinstance(loaded, list):
            return [str(item).strip() for item in loaded if str(item).strip()]
    except json.JSONDecodeError:
        pass

    try:
        loaded = ast.literal_eval(raw_value)
        if isinstance(loaded, str):
            return [loaded.strip()] if loaded.strip() else []
        if isinstance(loaded, (list, tuple, set)):
            return [str(item).strip() for item in loaded if str(item).strip()]
    except (ValueError, SyntaxError):
        return []

    return []


def _group_screenshots(shots, endpoint_map):
    groups = {}
    unparsed = []

    for shot in shots:
        meta = _parse_screenshot_name(shot.name)
        if not meta:
            unparsed.append(shot)
            continue

        key = (meta["endpoint_pk"], meta["user"], meta["password"], meta["label"])
        endpoint = endpoint_map.get(meta["endpoint_pk"], {})
        group = groups.setdefault(
            key,
            {
                "endpoint_pk": meta["endpoint_pk"],
                "endpoint_url": endpoint.get("url"),
            "service_id": endpoint.get("service_id"),
            "service_url": endpoint.get("service_url"),
                "host_path": meta["host_path"],
                "label": meta["label"],
                "user": meta["user"],
                "password": meta["password"],
                "before": [],
                "after": []
            }
        )
        group[meta["phase"]].append({
            "path": shot,
            "name": shot.name,
            "ts": meta["ts"]
        })

    for group in groups.values():
        group["before"].sort(key=lambda s: s["ts"])
        group["after"].sort(key=lambda s: s["ts"])

    grouped = sorted(
        groups.values(),
        key=lambda g: (g["endpoint_pk"], g["user"], g["label"])
    )

    return grouped, unparsed


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
        "screenshot_groups": [],
        "screenshot_unparsed": [],
        "service_keywords": [],
        "service_screenshots": [],
        "services": [],
        "endpoints": [],
        "found_credentials": [],
        "login_panels": [],
        "summary": {
            "services": 0,
            "endpoints": 0,
            "login_panels": 0,
            "found_credentials": 0,
            "screenshots": 0,
            "keywords": 0
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
                "SELECT pk, service_id, path, is_login, working_credentials, _keywords FROM endpoint"
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
        keyword_counts = {}
        service_keyword_map = {}
        for row in endpoints:
            service = service_map.get(row["service_id"])
            endpoint_url = None
            if service:
                endpoint_url = f"{service['url']}/{str(row['path']).lstrip('/')}"
            item = {
                "pk": row["pk"],
                "service_id": row["service_id"],
                "service_url": service["url"] if service else None,
                "path": row["path"],
                "is_login": bool(row["is_login"]),
                "working_credentials": row["working_credentials"] or "",
                "url": endpoint_url,
                "keywords": []
            }
            item["keywords"] = _parse_keywords(row["_keywords"])

            for keyword in item["keywords"]:
                keyword_counts[keyword] = keyword_counts.get(keyword, 0) + 1
                if service:
                    service_entry = service_keyword_map.setdefault(
                        service["pk"],
                        {"service_id": service["pk"], "service_url": service["url"], "counts": {}}
                    )
                    service_entry["counts"][keyword] = service_entry["counts"].get(keyword, 0) + 1

            endpoint_list.append(item)

            if item["working_credentials"]:
                found_credentials.append(item)
            if item["is_login"]:
                login_panels.append(item)

        data["services"] = list(service_map.values())
        data["endpoints"] = endpoint_list
        data["found_credentials"] = found_credentials
        data["login_panels"] = login_panels
        data["keywords"] = [
            {"keyword": key, "count": count}
            for key, count in sorted(keyword_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ]

        service_keywords = []
        for service in data["services"]:
            entry = service_keyword_map.get(service["pk"], {"counts": {}})
            keywords = [
                {"keyword": key, "count": count}
                for key, count in sorted(entry["counts"].items(), key=lambda kv: (-kv[1], kv[0]))
            ]
            if keywords:
                service_keywords.append({
                    "service_id": service["pk"],
                    "service_url": service["url"],
                    "keyword_total": len(keywords),
                    "keywords": keywords
                })
        service_keywords.sort(key=lambda s: s["service_url"])
        data["service_keywords"] = service_keywords

        endpoint_map = {item["pk"]: item for item in endpoint_list}
        if data["screenshots"]:
            groups, unparsed = _group_screenshots(data["screenshots"], endpoint_map)
            data["screenshot_groups"] = groups
            data["screenshot_unparsed"] = unparsed

            service_shots = {}
            for group in groups:
                service_id = group.get("service_id")
                service_url = group.get("service_url") or "Unknown service"
                key = service_id if service_id is not None else f"unknown:{group.get('endpoint_pk')}"
                entry = service_shots.setdefault(
                    key,
                    {
                        "service_id": service_id,
                        "service_url": service_url,
                        "groups": [],
                        "screenshot_count": 0
                    }
                )
                entry["groups"].append(group)
                entry["screenshot_count"] += len(group.get("before", [])) + len(group.get("after", []))

            for entry in service_shots.values():
                entry["group_count"] = len(entry["groups"])
                entry["groups"].sort(
                    key=lambda g: (g.get("endpoint_url") or g.get("host_path") or "")
                )

            data["service_screenshots"] = sorted(
                service_shots.values(),
                key=lambda s: s["service_url"]
            )

        data["summary"]["services"] = len(data["services"])
        data["summary"]["endpoints"] = len(endpoint_list)
        data["summary"]["login_panels"] = len(login_panels)
        data["summary"]["found_credentials"] = len(found_credentials)
        data["summary"]["keywords"] = len(keyword_counts)

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


@app.route("/run/<run_name>/rename", methods=["POST"])
def rename_run(run_name: str):
    run_path = _run_dir(run_name)
    if not run_path.exists() or not run_path.is_dir():
        abort(404)

    new_name = request.form.get("new_name", "").strip()
    if not _is_safe_run_name(new_name):
        abort(400)

    new_path = _run_dir(new_name)
    if new_path.exists():
        abort(409)

    run_path.rename(new_path)
    return redirect(url_for("run_view", run_name=new_name))


@app.route("/run/<run_name>/screenshots/<path:filename>")
def screenshot(run_name: str, filename: str):
    run_path = _run_dir(run_name)
    shot_dir = run_path / "screenshots"
    if not shot_dir.exists():
        abort(404)
    return send_from_directory(shot_dir, filename)


@app.route("/run/<run_name>/log/<log_name>")
def log_view(run_name: str, log_name: str):
    run_path = _run_dir(run_name)
    if not run_path.exists() or not run_path.is_dir():
        abort(404)

    log_path = _log_path(run_path, log_name)
    if not log_path:
        abort(404)
    log_content = _read_log_full(log_path)
    if log_content is None:
        abort(404)

    runs = _list_runs()
    return render_template(
        "log.html",
        runs=runs,
        run_name=run_name,
        base_dir=str(BASE_DIR),
        log_name=log_name,
        log_content=log_content
    )


@app.route("/run/<run_name>/log-tail/<log_name>")
def log_tail(run_name: str, log_name: str):
    run_path = _run_dir(run_name)
    if not run_path.exists() or not run_path.is_dir():
        abort(404)

    log_path = _log_path(run_path, log_name)
    if not log_path:
        abort(404)

    lines, truncated = _read_log_tail(log_path)
    return {
        "lines": lines,
        "truncated": truncated
    }


@app.route("/run/<run_name>/log-content/<log_name>")
def log_content(run_name: str, log_name: str):
    run_path = _run_dir(run_name)
    if not run_path.exists() or not run_path.is_dir():
        abort(404)

    log_path = _log_path(run_path, log_name)
    if not log_path:
        abort(404)

    content = _read_log_full(log_path)
    if content is None:
        abort(404)

    return content, 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/run/<run_name>/poll")
def run_poll(run_name: str):
    run_path = _run_dir(run_name)
    if not run_path.exists() or not run_path.is_dir():
        abort(404)

    return _run_state(run_path)


@app.route("/runs")
def runs_poll():
    return {
        "runs": [
            {
                "name": run["name"],
                "db_exists": run["db_exists"],
                "mtime": run["mtime"],
                "mtime_human": run["mtime_human"]
            }
            for run in _list_runs()
        ]
    }


@app.route("/health")
def health():
    return {"status": "ok", "base_dir": str(BASE_DIR)}


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8089, debug=True)
