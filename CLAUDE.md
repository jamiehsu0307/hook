# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A phishing-simulation email content generator for authorized internal security-awareness training, plus an unrelated document-OCR feature bolted onto the same FastAPI backend. Two capabilities live behind one app (`api/main.py`):

1. **Phishing simulation generator** — `api/index.html` is the actual product: a single-page vanilla-JS app where a trainer picks a scenario/delivery-mechanism/social-engineering-lever/action/difficulty combo, and the backend proxies a streaming, guided-decoding chat request to a local **Ollama** server to generate one simulated phishing email per click. **`task.md` is the authoritative spec** for this feature (data contract, prompt design, guardrails, acceptance criteria) — read it before changing `index.html`'s generation logic; this file only covers things `task.md` doesn't.
2. **Document OCR ingestion** — async job pipeline that converts uploaded PDFs/images to text via RapidOCR + `pdf2image`/`tesseract`. Unrelated to the generator; shares the process only because it's the same FastAPI app.

There used to be a third capability (emotion-tagging text classifier + title generator) — it has been removed. `api/xlmr-classifier/` (a 1.1GB fine-tuned model dir) and `api/title.jsonl` are now orphaned leftovers on disk with no code referencing them; `api/system_prompt_old.md` is the old emotion-tagging prompt, kept only for reference.

## Commands

Local (Ubuntu):
```bash
pip install -r api/requirements.txt
sudo apt install tesseract-ocr
cd api && uvicorn main:app --workers 2
```

Docker (via `docker-compose.yml`, checked into repo):
```bash
cd api && docker compose up
```

Docker (actual command used in this environment — bind-mounts `api/` into the container so code edits apply without rebuilding; there's no `--env-file`, since `.env` is picked up from the bind-mounted `/data`):
```bash
docker run -d -w /data -v ./api:/data --restart=unless-stopped --name hook_api -p 7788:8000 api-python-api:latest
```
Access via `http://localhost:7788/docs`. **Do not map the host port to `6000`.** Chrome/Firefox both hard-block port 6000 as an "unsafe port" (it's the legacy X11 port), so `/docs` etc. will return a browser-level connection error even though the server itself is completely healthy — `curl` still works fine on a blocked port, which is what makes this confusing to debug.

`index.html` is served fresh from disk on every request (`FileResponse`), so editing it takes effect immediately with no restart. `main.py` is imported once at container startup, so editing it **requires a container restart** to take effect.

There is no lint, format, or test tooling configured in this repo (no pytest/ruff/black config present). `index.html` has a manual browser-console self-check instead: run `__selfTest()` after the page loads to assert the JSON schema shape, prompt-building, and SSE-content-classification logic.

## Configuration

- `api/.env` must set `OLLAMA_URL`:
  - Docker: `http://host.docker.internal:11434`
  - Local: `http://localhost:11434`
- `docker-compose.yml` expects an external Docker network named `app-network` to already exist.

## Architecture notes

- **Everything backend-side lives in one file**, `api/main.py` — no routers/modules split.
- **`POST /query`** is a thin SSE-streaming proxy to Ollama's native `/api/chat` (not the OpenAI-compat endpoint). It no longer injects any default `format` — the caller must always supply its own guided-decoding JSON Schema, or Ollama will just do unstructured generation.
  - Before streaming, it makes a short-timeout (`5s`) call to `POST {OLLAMA_URL}/api/show` to check if the requested model has a `thinking` capability, and only sets `num_predict=1500` if it doesn't (thinking models are allowed to run longer). This check is best-effort — failures are silently swallowed and treated as "not thinking". **Known failure mode (reproduced in testing):** a thinking model can burn its entire `num_predict` budget on the `thinking` field and emit zero characters of real `content` before the stream cuts off with `done:false`. The frontend treats empty content as `truncated` (not `refused`) specifically because of this — see `classifyParseFailure()` in `index.html`.
- **`GET /tags`** filters Ollama's `/api/tags` response down to models whose `details.family` is in the hardcoded `LLM_FAMILIES` allowlist — update that list when adding support for a new model family. `index.html` calls this on page load to populate the model dropdown; there's no hardcoded model name anywhere.
- **`GET /system-prompt`** serves `api/system_prompt.md` verbatim as plain text. `index.html` fetches this on page load into a `SYSTEM_PROMPT` variable instead of hardcoding the prompt string, specifically so the prompt only needs to be maintained in one place. If `system_prompt.md` and `index.html`'s expectations of it drift, the generator's guardrails silently drift too — there's no schema tying them together.
- **`index.html` builds the guided-decoding JSON Schema and the full user prompt client-side** (`buildSchema()` / `buildUserPrompt()`), including picking exactly one few-shot example (from a hardcoded `EXAMPLES` array) whose `delivery_mechanism` matches the user's current selection — it does not send all examples. `task.md` §5/§5.1/§6 is the spec for this; the field-dependency rules per mechanism (`link_text`/`callback_number`/`oauth_app_name`) live in both places and must stay in sync if changed.
- **Multi-count generation is strictly sequential**, not parallel — one `/query` call completes (success or terminal failure) before the next one starts. A failure in one card never blocks or aborts the others; each card retries independently.
- **`requirements.txt` lists `docling[all]`, but `main.py` does not import or use it** — the actual OCR path is RapidOCR (`ENGINE = RapidOCR()`) + `pdf2image.convert_from_path`. Treat `docling` as dead weight unless you find a use for it.
- **`/ingest` is a fire-and-forget async job queue**, not a request/response endpoint:
  - `POST /ingest` saves the upload to a temp file, creates an in-memory job entry in the `JOBS` dict, and kicks off `process_document` as a background `asyncio` task.
  - `GET /ingest/{job_id}/status` and `GET /ingest/{job_id}/result` poll that same in-memory dict.
  - `JOBS` is process-local with no persistence — restarting the server drops all jobs. A background `cleanup_loop` (started on app startup) purges jobs older than `JOB_EXPIRATION_SECONDS` (1 hour) every `JOB_NEXT_CLEANING_SECONDS` (10 minutes).
- `convert()` (OCR → text) does its own layout reconstruction from RapidOCR's raw boxes/scores: it clusters boxes into columns (right-to-left, for vertical/CJK multi-column layouts) then into lines within each column, using thresholds derived from the median box height/width on that page. If you need to tune OCR text ordering/quality, this is the function to touch — it doesn't rely on any library's built-in layout analysis.
