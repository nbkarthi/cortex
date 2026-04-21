import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from starlette.responses import StreamingResponse
from jinja2 import Template

from src.data_loader import list_companies
from src.pipeline import run_pipeline

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("cortex.app")

app = FastAPI(title="Cortex")

# SSE clients for live status updates
status_clients: list[asyncio.Queue] = []

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "index.html")


@app.get("/", response_class=HTMLResponse)
async def index():
    logger.info("GET / — serving UI")
    with open(TEMPLATE_PATH) as f:
        template = Template(f.read())
    return template.render(companies=list_companies())


@app.get("/api/status")
async def status_stream():
    queue = asyncio.Queue()
    status_clients.append(queue)

    async def event_generator():
        try:
            while True:
                data = await queue.get()
                yield f"data: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            status_clients.remove(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


async def broadcast_status(step: int, state: str):
    for queue in status_clients:
        await queue.put({"step": step, "state": state})


@app.post("/api/analyze")
async def analyze(request: Request):
    body = await request.json()
    company = body.get("company", "").strip()
    logger.info("POST /api/analyze — company=%s", company)

    if not company:
        logger.warning("Empty company name submitted")
        return {"detail": "Please enter a company name"}, 400

    # Broadcast pipeline steps
    await broadcast_status(1, "active")

    try:
        # Run pipeline in thread to not block the event loop
        loop = asyncio.get_event_loop()

        async def run_with_status():
            await broadcast_status(1, "done")
            await broadcast_status(2, "active")
            result = await loop.run_in_executor(None, run_pipeline, company)
            return result

        # Step-by-step status broadcasting via a wrapper
        await broadcast_status(1, "active")
        result = await loop.run_in_executor(None, run_pipeline, company)
        await broadcast_status(4, "done")

        logger.info("Analysis complete for %s — returning result", company)
        return result

    except ValueError as e:
        logger.error("Company not found: %s", e)
        return {"detail": str(e)}
    except Exception as e:
        logger.exception("Pipeline failed for %s", company)
        return {"detail": f"Analysis failed: {e}"}


if __name__ == "__main__":
    import uvicorn
    logger.info("Starting Cortex server on http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
