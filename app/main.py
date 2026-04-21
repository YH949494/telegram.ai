import asyncio
import contextlib
import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import get_settings
from .handlers import setup_application, start_bot, stop_bot

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title="AI Observer Admin")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "templates" / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.on_event("startup")
async def startup_event() -> None:
    settings = get_settings()
    logger.info("Starting AI Observer app on port %s", settings.port)
    app.state.bot_application = None
    app.state.bot_task = None
    app.state.bot_running = False
    app.state.bot_last_error = None

    async def _bot_runner() -> None:
        try:
            application = setup_application()
            app.state.bot_application = application
            await start_bot(application)
            app.state.bot_running = True
            app.state.bot_last_error = None
            logger.info("Telegram bot started successfully")
        except Exception as exc:
            app.state.bot_running = False
            app.state.bot_last_error = str(exc)
            logger.exception("Telegram bot failed to start; web UI will stay available")

    app.state.bot_task = asyncio.create_task(_bot_runner())


@app.on_event("shutdown")
async def shutdown_event() -> None:
    bot_task: Optional[asyncio.Task] = getattr(app.state, "bot_task", None)
    application = getattr(app.state, "bot_application", None)
    if application is not None:
        await stop_bot(application)
    if bot_task and not bot_task.done():
        bot_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bot_task


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    settings = get_settings()
    feature_flags = {
        "tagging": settings.enable_tagging,
        "suggestions": settings.enable_suggestions,
        "low_risk_auto_reply": settings.enable_low_risk_auto_reply,
        "threaded_replies": settings.enable_threaded_replies,
    }
    mode_by_category = {
        category: "auto-reply" if category in settings.auto_reply_categories else "suggestion-only"
        for category in sorted(settings.auto_reply_categories | settings.suggestion_only_categories)
    }
    system_status = {
        "web": "running",
        "bot": "running" if getattr(app.state, "bot_running", False) else "degraded",
        "bot_last_error": getattr(app.state, "bot_last_error", None),
        "mongodb_db": settings.mongodb_db,
        "mongodb_collection": settings.mongodb_collection,
    }
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "feature_flags": feature_flags,
            "mode_by_category": mode_by_category,
            "system_status": system_status,
        },
    )


@app.get("/healthz", response_class=JSONResponse)
async def healthz() -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "web": "running",
            "bot_running": bool(getattr(app.state, "bot_running", False)),
            "bot_last_error": getattr(app.state, "bot_last_error", None),
        }
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)
