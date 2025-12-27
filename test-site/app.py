from __future__ import annotations

import os
from flask import Flask, redirect, render_template, request, session, url_for


def create_app() -> Flask:
    app = Flask(__name__)

    # For a test site this is fine; override via env var if you want persistence.
    app.secret_key = os.environ.get("TEST_SITE_SECRET", "dev-secret-change-me")

    VALID_USERNAME = "admin"
    VALID_PASSWORD = "nsip"

    @app.get("/")
    def index():
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return render_template("welcome.html", username=session.get("username"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error: str | None = None

        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""

            if username == VALID_USERNAME and password == VALID_PASSWORD:
                session.clear()
                session["logged_in"] = True
                session["username"] = username
                return redirect(url_for("index"))

            error = "Invalid username or password"

        return render_template("login.html", error=error)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=8000, debug=True)
