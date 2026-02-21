"""FastAPI application entry point."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from src.api.routes import router
from src.db.database import Database

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def _check_env() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. "
            "Add it to .env or set it in your environment.\n"
            "Get a key at: console.anthropic.com"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_env()
    db = Database()
    await db.connect()
    app.state.db = db
    logger.info("Database connected")
    yield
    await db.close()
    logger.info("Database closed")


app = FastAPI(title="CARB Regulations Chatbot", lifespan=lifespan)
app.include_router(router)


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(content=html_path.read_text())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=False)
