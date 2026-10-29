from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

app = FastAPI(title="DataCompiler Preview API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://data-compiler.com",
        "https://www.data-compiler.com",
        "http://localhost:3000",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

JOBS_DIR = Path(os.getenv("DATACOMPILER_PREVIEW_DIR", Path(tempfile.gettempdir()) / "dc-preview-jobs"))
JOBS_DIR.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
FIRST_PAGE_THRESHOLD = 20 * 1024 * 1024
RETENTION_SECONDS = 60 * 60
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
VISION_LOCK = threading.Lock()
VISION_PROCESS: subprocess.Popen | None = None

LANGUAGE_NAMES = {
    "de": "German", "en": "English", "fr": "French", "it": "Italian",
    "pl": "Polish", "es": "Spanish", "tr": "Turkish",
}
TARGET_PRIORITY = ["en", "fr", "de"]


@app.get("/health")
def health():
    return {"status": "online", "service": "datacompiler-api", "version": app.version}


def purge_old_jobs() -> None:
    cutoff = time.time() - RETENTION_SECONDS
    for child in JOBS_DIR.iterdir():
        try:
            if child.is_file() and child.stat().st_mtime < cutoff:
                child.unlink()
            elif child.is_dir() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child)
        except OSError:
            pass


def _vision_worker() -> subprocess.Popen:
    """Start the persistent macOS Vision helper once per API process."""
    global VISION_PROCESS
    with VISION_LOCK:
        if VISION_PROCESS and VISION_PROCESS.poll() is None:
            return VISION_PROCESS
        swiftc = shutil.which("swiftc")
        if not swiftc:
            raise RuntimeError("No scan OCR provider is available on this server.")
        helper = Path(__file__).parent / "assets" / "vision_ocr_worker.swift"
        binary = JOBS_DIR / "vision-ocr-worker"
        compiled = subprocess.run(
            [swiftc, str(helper), "-o", str(binary)],
            capture_output=True, text=True, timeout=60, check=False,
        )
        if compiled.returncode:
            raise RuntimeError("The local Vision OCR helper could not be compiled.")
        VISION_PROCESS = subprocess.Popen(
            [str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1,
        )
        return VISION_PROCESS


def _scan_ocr(image_path: Path, language: str = "") -> dict:
    import json

    worker = _vision_worker()
    with VISION_LOCK:
        worker.stdin.write(json.dumps({"image_path": str(image_path), "language": language}) + "\n")
        worker.stdin.flush()
        result = json.loads(worker.stdout.readline())
    if result.get("error"):
        raise RuntimeError(result["error"])
    return result


def _native_words(page) -> list[dict]:
    words = []
    bounds = page.rect
    for item in page.get_text("words", sort=True):
        x0, y0, x1, y1, text = item[:5]
        if not text.strip() or x1 <= x0 or y1 <= y0:
            continue
        words.append({
            "x": max(0.0, min(1.0, x0 / bounds.width)),
            "y": max(0.0, min(1.0, y0 / bounds.height)),
            "width": max(0.0, min(1.0, (x1 - x0) / bounds.width)),
            "height": max(0.0, min(1.0, (y1 - y0) / bounds.height)),
            "order": len(words),
            "confidence": 1.0,
        })
    return words


def _vision_boxes(result: dict) -> list[dict]:
    boxes = []
    for item in result.get("detections", []):
        boxes.append({
            key: item[key] for key in ("x", "y", "width", "height", "confidence")
        } | {"order": len(boxes)} )
    return boxes


def _detect_language(text: str) -> str | None:
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        return detect(text) if len(text.split()) >= 5 else None
    except Exception:  # noqa: BLE001 - short OCR samples are often ambiguous
        return None


def _target_languages(source: str | None) -> list[str]:
    source = (source or "").split("-")[0].lower()
    return [code for code in TARGET_PRIORITY if code != source][:2]


def _translate_sample(text: str, source: str | None, targets: list[str]) -> dict[str, str]:
    key = os.getenv("DEEPL_AUTH_KEY")
    if not key or not text.strip():
        return {}
    try:
        import deepl

        client = deepl.DeepLClient(key)
        results = {}
        for target in targets:
            deepl_target = {"en": "EN-US", "fr": "FR", "de": "DE"}.get(target, target.upper())
            options = {"target_lang": deepl_target, "preserve_formatting": True}
            if source:
                options["source_lang"] = source.upper()
            response = client.translate_text(text, **options)
            results[target] = response.text
        return results
    except Exception as exc:  # noqa: BLE001 - keep OCR preview if translation is unavailable
        print("Preview translation failed:", repr(exc))
        return {}


def _font(size: int):
    from PIL import ImageFont

    font_path = Path(__file__).parent / "assets" / "fonts" / "DejaVuSans.ttf"
    return ImageFont.truetype(str(font_path), size)


def _render_text_preview(lines: list[str], output: Path, width: int, height: int) -> None:
    from PIL import Image, ImageDraw, ImageFilter

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = _font(max(18, int(width * 0.035)))
    x = int(width * 0.075)
    y = int(height * 0.075)
    line_height = int(font.size * 1.5)
    max_width = width - x * 2
    for line in lines:
        current = ""
        for word in line.split():
            candidate = f"{current} {word}".strip()
            if current and draw.textlength(candidate, font=font) > max_width:
                draw.text((x, y), current, font=font, fill=(20, 27, 42))
                y += line_height
                current = word
            else:
                current = candidate
        if current and y < height:
            draw.text((x, y), current, font=font, fill=(20, 27, 42))
            y += line_height
    blurred = image.filter(ImageFilter.GaussianBlur(11))
    cut = int(height * 0.16)
    image.paste(blurred.crop((0, cut, width, height)), (0, cut))
    image.save(output, format="PNG")


def _render_target_preview(sample: str, output: Path, width: int, height: int) -> None:
    from PIL import Image, ImageDraw, ImageFilter

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = _font(max(18, int(width * 0.035)))
    x, y = int(width * 0.075), int(height * 0.075)
    max_width = width - x * 2
    line_height = int(font.size * 1.5)
    current = ""
    for word in sample.split():
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate, font=font) > max_width:
            draw.text((x, y), current, font=font, fill=(20, 27, 42))
            y += line_height
            current = word
        else:
            current = candidate
    if current:
        draw.text((x, y), current, font=font, fill=(20, 27, 42))
    # The obscured lower text is generated locally; it contains no untranslated
    # document content and does not require translating the entire page.
    for offset in range(4):
        row_y = int(height * 0.28) + offset * line_height
        if row_y < height - 12:
            draw.rounded_rectangle((x, row_y, width - x, row_y + max(5, font.size // 2)), radius=3, fill=(205, 210, 219))
    blurred = image.filter(ImageFilter.GaussianBlur(11))
    cut = int(height * 0.16)
    image.paste(blurred.crop((0, cut, width, height)), (0, cut))
    image.save(output, format="PNG")


def _process(job_id: str, path: Path, uploaded_bytes: int, first_page_only: bool) -> None:
    import pymupdf

    job_dir = JOBS_DIR / job_id
    try:
        with pymupdf.open(path) as doc:
            page_count = len(doc)
            page = doc[0]
            preview = job_dir / "original.png"
            scale = min(1.5, 1200 / max(page.rect.width, page.rect.height))
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            pix.save(str(preview))
            width, height = pix.width, pix.height
            native = _native_words(page)
            page_text = ""
            granularity = "word"
            if native:
                page_text = page.get_text("text", sort=True)
                source_lines = [line for line in page_text.splitlines() if line.strip()]
                boxes = native
                mode = "native"
            else:
                ocr_input = job_dir / "ocr-page.png"
                pix.save(str(ocr_input))
                result = _scan_ocr(ocr_input, os.getenv("DATACOMPILER_VISION_LANGUAGE", ""))
                detections = result.get("detections", [])
                source_lines = [item.get("text", "").strip() for item in detections if item.get("text", "").strip()]
                page_text = "\n".join(source_lines)
                boxes = _vision_boxes(result)
                granularity = result.get("granularity", "line")
                mode = "scan"
            page_words = len(page_text.split())
            estimated_words = page_words * page_count if page_count > 1 else page_words
            source_code = _detect_language(page_text)
            source_name = LANGUAGE_NAMES.get(source_code, source_code or "Unknown")
            # Native-text PDFs keep using the existing faithful rebuild path for
            # now; do not spend DeepL calls on a preview the website will not use.
            targets = _target_languages(source_code) if mode == "scan" else []
            sample = source_lines[0] if source_lines else ""
            _render_text_preview(source_lines, job_dir / "source-text.png", width, height)
            diagnostic_bytes = path.stat().st_size
            result = {
                "schema_version": 1,
                "job_id": job_id,
                "status": "preview_ready",
                "document": {
                    "page_count": page_count,
                    "pages_processed": 1,
                    "first_page_only": first_page_only,
                    "mode": mode,
                    "source_language": source_name,
                    "source_language_code": source_code,
                    "word_count": estimated_words,
                    "word_count_is_estimated": page_count > 1,
                },
                "preview": {
                    "original_png_url": f"/v1/diagnostics/{job_id}/original.png",
                    "source_text_png_url": f"/v1/diagnostics/{job_id}/source-text.png",
                    "width": width,
                    "height": height,
                    "box_granularity": granularity,
                    "word_boxes": boxes,
                },
                "translations": [],
                "translation_status": "processing",
                "file_size_estimate": {
                    "basis": "first_page_diagnostic",
                    "input_bytes": diagnostic_bytes,
                    "uploaded_bytes": uploaded_bytes,
                    "first_page_only": first_page_only,
                },
            }
            with JOBS_LOCK:
                JOBS[job_id] = {"status": "preview_ready", "result": result}
            # Publish OCR, boxes, and the source preview before waiting on
            # translation providers. Each language is added as it finishes.
            for target in targets:
                translated = _translate_sample(sample, source_code, [target]).get(target)
                if translated:
                    image_name = f"target-{target}.png"
                    _render_target_preview(translated, job_dir / image_name, width, height)
                    result["translations"].append({
                        "language": LANGUAGE_NAMES.get(target, target),
                        "language_code": target,
                        "sample_png_url": f"/v1/diagnostics/{job_id}/{image_name}",
                    })
                    with JOBS_LOCK:
                        JOBS[job_id]["result"] = dict(result)
            result["translation_status"] = "ready" if result["translations"] else "unavailable"
            result["status"] = "done"
            with JOBS_LOCK:
                JOBS[job_id] = {"status": "done", "result": result}
        path.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001 - expose safe status; keep details server-side
        print("Diagnostic failed:", job_id, repr(exc))
        with JOBS_LOCK:
            JOBS[job_id] = {"status": "error", "message": "The document could not be diagnosed."}
        path.unlink(missing_ok=True)


@app.post("/v1/diagnostics", status_code=202)
async def create_diagnostic(
    file: UploadFile = File(...),
    first_page_only_confirmed: bool = Form(False),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".png", ".jpg", ".jpeg"}:
        raise HTTPException(status_code=400, detail="Unsupported file type.")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Upload exceeds the 100 MiB limit.")
    if suffix == ".pdf" and len(data) > FIRST_PAGE_THRESHOLD and not first_page_only_confirmed:
        raise HTTPException(status_code=409, detail={
            "code": "first_page_confirmation_required",
            "message": "This PDF is large. Confirm that only its first page will be diagnosed.",
        })

    purge_old_jobs()
    job_id = uuid.uuid4().hex
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / f"input{suffix}"
    path.write_bytes(data)
    first_page_only = suffix == ".pdf" and len(data) > FIRST_PAGE_THRESHOLD
    if first_page_only:
        import pymupdf

        first_page_path = job_dir / "first-page.pdf"
        with pymupdf.open(path) as source_pdf:
            if len(source_pdf) > 1:
                first = pymupdf.open()
                first.insert_pdf(source_pdf, from_page=0, to_page=0)
                first.save(first_page_path)
                first.close()
        if first_page_path.exists():
            first_page_path.replace(path)
        else:
            first_page_only = False

    with JOBS_LOCK:
        JOBS[job_id] = {"status": "processing"}
    threading.Thread(target=_process, args=(job_id, path, len(data), first_page_only), daemon=True).start()
    return {"job_id": job_id, "status": "processing"}


@app.get("/v1/diagnostics/{job_id}")
def get_diagnostic(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown diagnostic job.")
    if job.get("result"):
        return job["result"]
    response = {"job_id": job_id, "status": job["status"]}
    if job.get("message"):
        response["message"] = job["message"]
    return response


@app.get("/v1/diagnostics/{job_id}/{artifact_name}")
def get_artifact(job_id: str, artifact_name: str):
    allowed = {"original.png", "source-text.png"}
    if artifact_name.startswith("target-") and artifact_name.endswith(".png"):
        allowed.add(artifact_name)
    if artifact_name not in allowed:
        raise HTTPException(status_code=404)
    path = JOBS_DIR / Path(job_id).name / artifact_name
    if not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, no-store"})
