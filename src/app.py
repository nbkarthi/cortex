import asyncio
import json
import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

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


@app.get("/", response_class=HTMLResponse)
async def index():
    logger.info("GET / — serving UI")
    with open(TEMPLATE_PATH) as f:
        return f.read()


@app.get("/api/companies")
async def api_companies():
    logger.info("GET /api/companies")
    companies = list_companies_detail()
    logger.info("Returning %d companies", len(companies))
    return companies


@app.get("/api/company/{ticker}")
async def api_company(ticker: str):
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
async def analyze(request: Request):
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
