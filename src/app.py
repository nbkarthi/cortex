import asyncio
import json
import logging
import os

from io import BytesIO
from fpdf import FPDF

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


@app.post("/api/memo-pdf")
async def memo_pdf(request: Request):
    body = await request.json()
    memo_md = body.get("memo", "")
    ticker = body.get("ticker", "memo")
    logger.info("POST /api/memo-pdf — generating PDF for %s", ticker)

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_font("Helvetica", size=11)
    pdf.write_html(md_to_html(memo_md))

    buf = BytesIO()
    pdf.output(buf)
    pdf_bytes = buf.getvalue()

    logger.info("PDF generated for %s — %d bytes", ticker, len(pdf_bytes))
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={ticker}_memo.pdf"},
    )


def md_to_html(text: str) -> str:
    """Convert markdown to simple HTML that fpdf2 write_html supports."""
    import re
    lines = text.split("\n")
    html_lines = []
    in_table = False
    in_list = False
    table_rows = []

    def bold(s):
        return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)

    for line in lines:
        stripped = line.strip()

        # Table separator row - skip
        if re.match(r"^\|[-| :]+\|$", stripped):
            continue

        # Table row
        if stripped.startswith("|") and stripped.endswith("|"):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            if not in_table:
                in_table = True
                table_rows = []
                header = "".join(f'<th align="left"><b>{bold(c)}</b></th>' for c in cells)
                table_rows.append(f"<tr>{header}</tr>")
            else:
                row = "".join(f"<td>{bold(c)}</td>" for c in cells)
                table_rows.append(f"<tr>{row}</tr>")
            continue

        # Close table if we left it
        if in_table:
            html_lines.append('<table border="1" cellpadding="4">' + "".join(table_rows) + "</table><br>")
            in_table = False
            table_rows = []

        # List items (- or 1.)
        is_bullet = stripped.startswith("- ")
        is_numbered = bool(re.match(r"^\d+\.\s", stripped))
        if is_bullet or is_numbered:
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            content = stripped[2:] if is_bullet else re.sub(r"^\d+\.\s", "", stripped)
            html_lines.append(f"<li>{bold(content)}</li>")
            continue

        # Close list if we left it
        if in_list:
            html_lines.append("</ul>")
            in_list = False

        if stripped.startswith("# "):
            html_lines.append(f"<h1>{bold(stripped[2:])}</h1>")
        elif stripped.startswith("## "):
            html_lines.append(f'<h2><font color="#2563eb">{bold(stripped[3:])}</font></h2>')
        elif stripped.startswith("### "):
            html_lines.append(f"<h3>{bold(stripped[4:])}</h3>")
        elif stripped.startswith("---"):
            html_lines.append("<br><hr><br>")
        elif stripped.startswith("> "):
            html_lines.append(f'<font color="#6b7280"><i>{bold(stripped[2:])}</i></font><br>')
        elif stripped == "":
            html_lines.append("<br>")
        else:
            html_lines.append(f"{bold(stripped)}<br>")

    if in_list:
        html_lines.append("</ul>")
    if in_table:
        html_lines.append('<table border="1" cellpadding="4">' + "".join(table_rows) + "</table>")

    return "\n".join(html_lines)


if __name__ == "__main__":
    import uvicorn
    logger.info("Starting Cortex server on http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
