import asyncio
import hashlib
import json
import logging
import os
import secrets
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

from fastapi import FastAPI, Request, Cookie
from fastapi.responses import HTMLResponse, JSONResponse, Response, RedirectResponse

from data_loader import list_companies_detail, load_company, get_news
from pipeline import run_pipeline

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("cortex.app")

app = FastAPI(title="Cortex")

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "index.html")
LOGIN_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "login.html")

# Hardcoded credentials
AUTH_USER = "admin@cortex.com"
AUTH_PASS = "cortex@123"

# Active sessions (in-memory)
active_sessions: set[str] = set()


def check_session(session_token: str | None) -> bool:
    return session_token is not None and session_token in active_sessions


def send_login_notification(email: str):
    smtp_user = os.getenv("GMAIL_USER")
    smtp_pass = os.getenv("GMAIL_APP_PASSWORD")
    if not smtp_user or not smtp_pass:
        logger.warning("GMAIL_USER or GMAIL_APP_PASSWORD not set — skipping login notification")
        return
    try:
        body = f"Login detected on Cortex.\n\nUser: {email}\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        msg = MIMEText(body)
        msg["Subject"] = "Cortex Login"
        msg["From"] = smtp_user
        msg["To"] = "nbkarthi@gmail.com"
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, "nbkarthi@gmail.com", msg.as_string())
        logger.info("Login notification sent for %s", email)
    except Exception as e:
        logger.error("Failed to send login notification: %s", e)


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    logger.info("GET /login")
    with open(LOGIN_TEMPLATE_PATH) as f:
        return f.read()


@app.post("/api/login")
async def login(request: Request):
    body = await request.json()
    email = body.get("email", "").strip()
    password = body.get("password", "")
    logger.info("POST /api/login — email=%s", email)

    if email == AUTH_USER and password == AUTH_PASS:
        token = secrets.token_hex(32)
        active_sessions.add(token)
        logger.info("Login successful for %s", email)
        send_login_notification(email)
        response = JSONResponse(content={"ok": True})
        response.set_cookie(key="session", value=token, httponly=True, samesite="lax", max_age=86400)
        return response
    else:
        logger.warning("Login failed for %s", email)
        return JSONResponse(status_code=401, content={"detail": "Invalid email or password"})


@app.post("/api/logout")
async def logout(session: str | None = Cookie(default=None)):
    if session:
        active_sessions.discard(session)
    response = JSONResponse(content={"ok": True})
    response.delete_cookie("session")
    return response


@app.get("/", response_class=HTMLResponse)
async def index(session: str | None = Cookie(default=None)):
    if not check_session(session):
        return RedirectResponse(url="/login", status_code=302)
    logger.info("GET / — serving UI")
    with open(TEMPLATE_PATH) as f:
        return f.read()


@app.get("/api/companies")
async def api_companies(session: str | None = Cookie(default=None)):
    if not check_session(session):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    logger.info("GET /api/companies")
    companies = list_companies_detail()
    logger.info("Returning %d companies", len(companies))
    return companies


@app.get("/api/company/{ticker}")
async def api_company(ticker: str, session: str | None = Cookie(default=None)):
    if not check_session(session):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    logger.info("GET /api/company/%s", ticker)
    try:
        data = load_company(ticker)
        logger.info("Loaded %s — %d transcripts, %d news",
                     data["company"], len(data["transcripts"]), len(data.get("news", [])))
        return data
    except ValueError as e:
        logger.error("Company not found: %s", e)
        return JSONResponse(status_code=404, content={"detail": str(e)})


@app.post("/api/analyze")
async def analyze(request: Request, session: str | None = Cookie(default=None)):
    if not check_session(session):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    body = await request.json()
    company = body.get("company", "").strip()
    logger.info("POST /api/analyze — company=%s", company)

    if not company:
        logger.warning("Empty company name submitted")
        return JSONResponse(status_code=400, content={"detail": "Please enter a company name"})

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, run_pipeline, company)
        logger.info("Analysis complete for %s in %ss", company, result["elapsed_seconds"])
        return result
    except ValueError as e:
        logger.error("Company not found: %s", e)
        return JSONResponse(status_code=404, content={"detail": str(e)})
    except Exception as e:
        logger.exception("Pipeline failed for %s", company)
        return JSONResponse(status_code=500, content={"detail": f"Analysis failed: {e}"})


if __name__ == "__main__":
    import uvicorn
    logger.info("Starting Cortex server on http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
