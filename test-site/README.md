# Test Site (Login + Welcome)

Minimal Flask app for Selenium-based credential testing.

## Credentials

- Username: `admin`
- Password: `nsip`

## Run

From `test-site/`:

- `python -m venv .venv`
- `.\.venv\Scripts\Activate.ps1`
- `pip install -r requirements.txt`
- `python app.py`

Then open:
- `http://127.0.0.1:8000/login`

## Routes

- `GET /login` login form
- `POST /login` submit credentials
- `GET /` welcome page (requires session)
- `POST /logout` clears session
