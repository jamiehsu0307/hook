from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, PlainTextResponse, FileResponse
from fastapi.concurrency import run_in_threadpool
from dotenv import load_dotenv
from pathlib import Path
from rapidocr import RapidOCR
from pdf2image import convert_from_path
from PIL import Image
import os, re, time, uuid, httpx, aiofiles, tempfile, asyncio, traceback, statistics
from typing import Dict, Any

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB
OLLAMA_BASE_URL = os.getenv("OLLAMA_URL")
LLM_FAMILIES = ["llama", "mistral", "qwen", "qwen35moe", "gemma3", "gemma4", "phi", "deepseek", "gpt-oss"]
ENGINE = RapidOCR()
JOBS: Dict[str, Dict[str, Any]] = {}
JOB_EXPIRATION_SECONDS = 1 * 60 * 60
JOB_NEXT_CLEANING_SECONDS = 10 * 60

async def process_document(job_id: str, temp_path: str, original_filename: str, content_type: str, file_size: int):
    try:
        JOBS[job_id]["status"] = "processing"
        JOBS[job_id]["progress"] = 20

        # You can mark stages manually
        JOBS[job_id]["stage"] = "running_rapid_ocr"

        result = await run_in_threadpool(convert, temp_path)

        JOBS[job_id]["progress"] = 90
        JOBS[job_id]["stage"] = "serializing_output"

        JOBS[job_id]["status"] = "completed"
        JOBS[job_id]["progress"] = 100
        JOBS[job_id]["result"] = {
            "filename": original_filename,
            "content_type": content_type,
            "size_bytes": file_size,
            "text": result
        }

    except Exception as e:
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["error"] = str(e)
        JOBS[job_id]["trace"] = traceback.format_exc()

    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

async def cleanup_loop():
    while True:
        remove_expired_job()
        await asyncio.sleep(JOB_NEXT_CLEANING_SECONDS)

def remove_expired_job():
    now = time.time()
    for job_id in list(JOBS.keys()):
        if now - JOBS[job_id]["timestamp"] > JOB_EXPIRATION_SECONDS:
            del JOBS[job_id]

def convert(source: str):
    images = []
    file_type = detect_file_type(source)
    if file_type == "PDF":
        images = convert_from_path(source, dpi=300)
    elif file_type == "Image":
        images.append(source)

    all_pages_text = []
    try:
        for page_num, image in enumerate(images, start=1):
            output = ENGINE(image)

            if output.boxes is None:
                all_pages_text.append("")
                continue

            data = []

            for box, text, score in zip(output.boxes, output.txts, output.scores):
                if not text or not text.strip():
                    continue
                if score < 0.5:  # filter low-confidence OCR noise
                    continue

                x_coords = [p[0] for p in box]
                y_coords = [p[1] for p in box]

                left = min(x_coords)
                right = max(x_coords)
                top = min(y_coords)
                bottom = max(y_coords)

                data.append({
                    "text": text.strip(),
                    "left": left,
                    "right": right,
                    "top": top,
                    "bottom": bottom,
                    "x": (left + right) / 2,
                    "y": (top + bottom) / 2,
                    "width": right - left,
                    "height": bottom - top,
                    "score": score
                })

            if not data:
                all_pages_text.append("")
                continue

            # Dynamic thresholds
            avg_height = statistics.median([d["height"] for d in data])
            avg_width = statistics.median([d["width"] for d in data])

            line_threshold = max(8, avg_height * 0.6)
            paragraph_gap_threshold = avg_height * 1.5
            column_threshold = max(40, avg_width * 3)

            # --- Step 1: detect columns (right-to-left, for vertical / multi-column layouts) ---
            # Sort by x descending, then y ascending
            data_sorted = sorted(data, key=lambda x: (-x["x"], x["y"]))

            columns = []
            for item in data_sorted:
                placed = False
                for col in columns:
                    # compare with representative x of column
                    col_x = statistics.mean([c["x"] for c in col])
                    if abs(item["x"] - col_x) < column_threshold:
                        col.append(item)
                        placed = True
                        break
                if not placed:
                    columns.append([item])

            # Sort columns from right to left
            columns = sorted(columns, key=lambda col: -statistics.mean([c["x"] for c in col]))

            page_lines = []

            # --- Step 2: inside each column, group into lines ---
            for col in columns:
                col_sorted = sorted(col, key=lambda x: x["top"])

                lines = []
                for item in col_sorted:
                    placed = False
                    for line in lines:
                        line_y = statistics.mean([l["y"] for l in line])
                        if abs(item["y"] - line_y) < line_threshold:
                            line.append(item)
                            placed = True
                            break
                    if not placed:
                        lines.append([item])

                # --- Step 3: sort words in each line left-to-right ---
                lines = sorted(lines, key=lambda line: statistics.mean([l["top"] for l in line]))

                prev_line_y = None
                for line in lines:
                    line_sorted = sorted(line, key=lambda x: x["left"])
                    line_text = " ".join(item["text"] for item in line_sorted)

                    current_y = statistics.mean([l["top"] for l in line])

                    # Insert paragraph break if vertical gap is large
                    if prev_line_y is not None and (current_y - prev_line_y) > paragraph_gap_threshold:
                        page_lines.append("")

                    page_lines.append(line_text)
                    prev_line_y = current_y

                # blank line between columns
                page_lines.append("")

            # --- Step 4: post-process ---
            page_text = "\n".join(page_lines)

            # Merge hyphenated line breaks: "informa-\ntion" -> "information"
            page_text = re.sub(r'(\w)-\n(\w)', r'\1\2', page_text)

            # Remove excessive blank lines
            page_text = re.sub(r'\n{3,}', '\n\n', page_text).strip()

            all_pages_text.append(page_text)
    except Exception as e:
        print(e)
    return "".join(all_pages_text)

def is_pdf(file_path):
    with open(file_path, 'rb') as f:
        header = f.read(4)
        return header == b'%PDF'
    
def is_image(file_path):
    try:
        Image.open(file_path)
        return True
    except IOError:
        return False
    
def detect_file_type(file_path):
    if is_pdf(file_path):
        return 'PDF'
    elif is_image(file_path):
        return 'Image'
    else:
        return 'Unknown'

@app.on_event("startup")
def startup_event():
    asyncio.create_task(cleanup_loop())

# -----------------------------
# GET /system-prompt
# -----------------------------
@app.get("/system-prompt")
async def system_prompt():
    path = Path("./system_prompt.md")
    if not path.exists():
        raise HTTPException(status_code=404, detail="system_prompt.md not found")
    return PlainTextResponse(path.read_text(encoding="utf-8"))

# -----------------------------
# GET /tags
# -----------------------------
@app.get("/tags")
async def tags():
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")

    if not response.is_success:
        return {}

    result = response.json()

    # Defensive checks
    if not result or "models" not in result:
        return {}

    filtered_models = []

    for item in result.get("models", []):
        details = item.get("details")
        if details:
            family = details.get("family")
            if family and family in LLM_FAMILIES:
                filtered_models.append(item)

    result["models"] = filtered_models
    return result

# -----------------------------
# POST /query (Streaming SSE)
# -----------------------------
@app.post("/query")
async def query(request: Request):
    payload = await request.json()
    is_thinking = False
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            show = await client.post(f"{OLLAMA_BASE_URL}/api/show", json={"name": payload.get("model", "")})
            is_thinking = "thinking" in show.json().get("capabilities", [])
    except Exception:
        pass

    payload.setdefault("options", {})
    if not is_thinking:
        payload["options"].setdefault("num_predict", 1500)
    payload["options"].setdefault("repeat_penalty", 1.3)

    async def event_generator():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{OLLAMA_BASE_URL}/api/chat",
                json=payload,
            ) as response:

                if not response.is_success:
                    raise HTTPException(
                        status_code=response.status_code,
                        detail="Ollama request failed",
                    )

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    yield f"data: {line}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )

# -----------------------------
# GET /ingest/{job_id}/status
# -----------------------------
@app.get("/ingest/{job_id}/status")
async def get_ingest_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job_id,
        "status": job["status"],
        "progress": job.get("progress"),
    }

# -----------------------------
# GET /ingest/{job_id}/result
# -----------------------------
@app.get("/ingest/{job_id}/result")
async def get_ingest_result(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] == "failed":
        raise HTTPException(status_code=500, detail=job["error"])

    if job["status"] != "completed":
        return {
            "job_id": job_id,
            "status": job["status"],
            "message": "Result not ready yet"
        }

    return job["result"]

# -----------------------------
# POST /ingest
# -----------------------------
@app.post("/ingest")
async def ingest_document(file: UploadFile = File(...)):
    temp_path = None
    file_size = 0

    try:
        file_extension = os.path.splitext(file.filename)[1]
        temp_filename = f"{uuid.uuid4()}{file_extension}"
        temp_path = os.path.join(tempfile.gettempdir(), temp_filename)

        async with aiofiles.open(temp_path, "wb") as out_file:
            while content := await file.read(1024 * 1024):
                file_size += len(content)
                await out_file.write(content)

        job_id = str(uuid.uuid4())

        JOBS[job_id] = {
            "status": "queued",
            "progress": 0,
            "stage": "uploaded",
            "result": None,
            "error": None,
            "timestamp": time.time()
        }

        asyncio.create_task(
            process_document(
                job_id=job_id,
                temp_path=temp_path,
                original_filename=file.filename,
                content_type=file.content_type,
                file_size=file_size,
            )
        )

        return {
            "job_id": job_id,
            "status": "queued",
        }

    except Exception as e:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def index():
    return FileResponse("index.html")

@app.get("/style.css")
async def style():
    return FileResponse("style.css", media_type="text/css")

