# Phishing Simulation Email Generator

A single-page tool for generating simulated phishing emails for authorized
internal security-awareness training. A trainer picks a scenario /
delivery-mechanism / social-engineering-lever / action / difficulty
combination, and the backend streams a guided-decoding chat request to a
local **Ollama** server to produce one simulated phishing email per click.

A second, unrelated capability — async document OCR ingestion (PDF/image →
text via RapidOCR + `pdf2image`/`tesseract`) — lives behind the same FastAPI
process (`api/main.py`) purely for deployment convenience.

## Setup

```bash
pip install -r api/requirements.txt
sudo apt install tesseract-ocr
cd api && uvicorn main:app --workers 2
```

Or via Docker:

```bash
cd api && docker compose up
```

`docker-compose.yml` expects an external Docker network named `app-network`
to already exist.

## Configuration

`api/.env` must set `OLLAMA_URL`:

- Docker: `http://host.docker.internal:11434`
- Local: `http://localhost:11434`

## Usage

Once running, open `/` (served from `api/index.html`) to use the generator.
The auto-generated API docs (`/docs`, `/redoc`, `/openapi.json`) are disabled;
see `api/main.py` for the full API surface (generate, classification, tags,
ingest endpoints).

## Docs

- [`task.md`](task.md) — authoritative spec for the phishing email generator
  (data contract, prompt design, guardrails, acceptance criteria)
- [`CLAUDE.md`](CLAUDE.md) — architecture notes and known failure modes for
  anyone (human or AI) modifying `api/main.py` or `api/index.html`
