import asyncio
import os

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import get_settings
from .handlers import setup_application, run_bot

"""
FastAPI entry point.  On startup, it launches the Telegram bot as a background
task and serves a simple admin UI.  The UI allows toggling features such as
tagging, suggestion and auto reaction (implementation of the toggles is left as
an exercise – they can be wired to update the Settings object or persisted
elsewhere).
"""

app = FastAPI(title="AI Observer Admin")

# Mount the static directory to serve CSS and other assets.
app.mount("/static", StaticFiles(directory="app/templates/static"), name="static")

templates = Jinja2Templates(directory="app/templates")


@app.on_event("startup")
async def startup_event() -> None:
    """
    FastAPI startup hook.  Creates and starts the Telegram bot in the background.
    """
    # Launch Telegram bot
    application = setup_application()
    # Start the bot in a background task
    asyncio.create_task(run_bot(application))


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """
    Render the admin UI.  At present the UI consists of static HTML with
    placeholder toggles; in a full implementation these toggles would be wired
    to endpoints that modify the bot configuration.
    """
    return templates.TemplateResponse("index.html", {"request": request})


if __name__ == "__main__":
    # When running directly with python app/main.py, use uvicorn to serve the app.
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)