# AI Observer for Telegram Groups

This project implements an AI‑assisted observer for Telegram groups that triages messages, suggests
appropriate replies and low‑risk reactions, and exposes an admin UI for enabling and disabling its
behaviours.  It is designed to run on **Fly.io** and to store conversation logs in **MongoDB**.

## Features

- **Message tagging** – categorises incoming messages into several intent classes (new users,
  voucher questions, win celebrations, negative feedback, support issues, high intent, etc.).
- **Reply suggestion** – generates a suggested reply for messages that require a human touch and
  forwards it to a designated admin chat.
- **Low‑risk auto response** – automatically replies and reacts to low‑risk messages such as
  welcome messages, congratulations and positive feedback.
- **Threaded replies** – replies are sent as a reply to the original message to keep the
  conversation thread neat.
- **Admin UI** – a simple web interface to enable or disable features like tagging, suggestion and
  auto reaction.

## Getting Started

### Prerequisites

- [Python 3.10+](https://www.python.org/)
- A Telegram bot token – create via [BotFather](https://t.me/botfather).
- A MongoDB database URI.
- (Optional) An admin chat id for sending reply suggestions.
- A Fly.io account and [flyctl](https://fly.io/docs/flyctl/install/) CLI.

### Installation

```bash
git clone https://github.com/yourorg/telegram_ai_observer.git
cd telegram_ai_observer
pip install -r requirements.txt
```

Create a `.env` file or supply environment variables:

```env
TELEGRAM_TOKEN=123456:ABCDEF
MONGODB_URI=mongodb+srv://user:password@cluster.example.mongodb.net/mydb
MONGODB_DB=telegram_ai
MONGODB_COLLECTION=messages
ADMIN_CHAT_ID=123456789       # optional
```

### Running Locally

```bash
uvicorn app.main:app --reload
```

This starts both the FastAPI web server and the Telegram bot in the background.  Open
<http://localhost:8000/> to access the admin UI.

### Deploying to Fly.io

1. Ensure you have logged in with `flyctl auth login`.
2. Create the Fly.io app: `flyctl apps create your-app-name`.
3. Set secrets (see the *Environment variables* section below).
4. Deploy: `flyctl deploy`.

A GitHub Actions workflow is provided at `.github/workflows/deploy.yml` to automatically deploy on
every push to the `main` branch. Make sure to add the `FLY_API_TOKEN` secret to your GitHub
repository.

## Environment variables

The following environment variables must be set either in your local `.env`, as Fly.io secrets or as
GitHub secrets:

| Variable            | Description                                           |
|---------------------|-------------------------------------------------------|
| `TELEGRAM_TOKEN`    | Telegram bot token from BotFather.                    |
| `MONGODB_URI`       | MongoDB connection string.                            |
| `MONGODB_DB`        | MongoDB database name (default: `telegram_ai`).       |
| `MONGODB_COLLECTION`| MongoDB collection for message logs.                  |
| `ADMIN_CHAT_ID`     | Optional chat id where suggestions are sent.          |
| `PORT`              | HTTP port for FastAPI/Fly (default: `8000`).          |
| `ENABLE_TAGGING`    | Enable message classification (default: `true`).      |
| `ENABLE_SUGGESTIONS`| Enable admin suggestion forwarding (default: `true`). |
| `ENABLE_LOW_RISK_AUTO_REPLY` | Enable low-risk auto replies (default: `true`). |
| `ENABLE_THREADED_REPLIES` | Reply using Telegram threading (default: `true`). |
| `FLY_API_TOKEN`     | Fly.io API token used by GitHub Actions.              |

For Fly.io, set the secrets using `flyctl secrets set`:

```bash
flyctl secrets set TELEGRAM_TOKEN=... MONGODB_URI=... MONGODB_DB=telegram_ai MONGODB_COLLECTION=messages ADMIN_CHAT_ID=...
```

## Repository structure

```
├── app/                   # application code
│   ├── __init__.py
│   ├── main.py            # FastAPI entry point and Telegram bot integration
│   ├── config.py          # pydantic settings loaded from env vars
│   ├── classifier.py      # simple rule‑based message classifier
│   ├── responses.py       # canned responses and reactions
│   ├── db.py              # MongoDB connection and logging
│   └── templates/
│       ├── index.html     # admin UI
│       └── static/
│           └── style.css  # UI styling
├── config.toml           # default configuration values
├── fly.toml              # Fly.io configuration
├── Dockerfile            # container definition
├── requirements.txt      # Python dependencies
└── .github/workflows/
    └── deploy.yml        # CI/CD pipeline for Fly.io
```