#!/usr/bin/env python3
"""Compare first-page native extraction and optional PaddleOCR on local PDFs."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def normalize_paddle(result) -> list[dict]:
    """Read the common PaddleOCR 2.x list and 3.x mapping result forms."""
    if hasattr(result, "json"):
        result = result.json
    if isinstance(result, str):
        result = json.loads(result)
    if isinstance(result, (list, tuple)) and result and isinstance(result[0], dict):
        result = result[0]
    if isinstance(result, dict):
        payload = result.get("res", result)
        texts = payload.get("rec_texts", [])
        scores = payload.get("rec_scores", [])
        boxes = payload.get("dt_polys") or payload.get("rec_polys") or payload.get("rec_boxes") or []
        detections = []
        for index, (text, box) in enumerate(zip(texts, boxes)):
            points = box.tolist() if hasattr(box, "tolist") else box
            if points and isinstance(points[0], (int, float)):
                xs = [float(points[0]), float(points[2])]
                ys = [float(points[1]), float(points[3])]
            else:
                xs = [float(point[0]) for point in points]
                ys = [float(point[1]) for point in points]
            detections.append({
                "text": str(text), "x0": min(xs), "y0": min(ys),
                "x1": max(xs), "y1": max(ys),
                "confidence": float(scores[index]) if index < len(scores) else None,
            })
        return detections

    pages = result.tolist() if hasattr(result, "tolist") else result
    if not pages:
        return []
    lines = pages[0] if len(pages) == 1 and isinstance(pages[0], list) else pages
    detections = []
    for item in lines or []:
        try:
            box, (text, score) = item
            points = box.tolist() if hasattr(box, "tolist") else box
            xs = [float(point[0]) for point in points]
            ys = [float(point[1]) for point in points]
            detections.append({
                "text": str(text), "x0": min(xs), "y0": min(ys),
                "x1": max(xs), "y1": max(ys), "confidence": float(score),
            })
        except (TypeError, ValueError, IndexError):
            continue
    return detections


def benchmark_native(pdf_path: Path) -> dict:
    import pymupdf

    started = time.perf_counter()
    with pymupdf.open(pdf_path) as doc:
        page = doc[0]
        words = page.get_text("words")
        text = " ".join(item[4] for item in words)
        page_count = len(doc)
        page_size = [float(page.rect.width), float(page.rect.height)]
    return {
        "engine": "pymupdf-native",
        "version": package_version("PyMuPDF"),
        "elapsed_seconds": round(time.perf_counter() - started, 4),
        "page_count": page_count,
        "page_size_points": page_size,
        "word_count": len(words),
        "box_count": len(words),
        "text_preview": text[:500],
    }


def benchmark_paddle(pdf_path: Path, language: str, dpi: int, runs: int) -> dict:
    import numpy as np
    import pymupdf
    from paddleocr import PaddleOCR

    init_started = time.perf_counter()
    try:
        engine = PaddleOCR(
            lang=language,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
    except TypeError:
        # PaddleOCR 2.x uses a smaller constructor surface than 3.x.
        engine = PaddleOCR(lang=language, use_angle_cls=False, show_log=False)
    init_seconds = time.perf_counter() - init_started

    with pymupdf.open(pdf_path) as doc:
        page = doc[0]
        pixmap = page.get_pixmap(dpi=dpi, alpha=False)
        image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
            pixmap.height, pixmap.width, pixmap.n,
        )[:, :, :3]

    timings = []
    detections = []
    for _ in range(max(1, runs)):
        started = time.perf_counter()
        result = engine.ocr(image)
        timings.append(time.perf_counter() - started)
        detections = normalize_paddle(result)
    detections.sort(key=lambda item: (round(item["y0"] / 12), item["x0"]))
    scores = [item["confidence"] for item in detections if item["confidence"] is not None]
    return {
        "engine": "paddleocr",
        "version": package_version("paddleocr"),
        "language_model": language,
        "dpi": dpi,
        "initialization_seconds": round(init_seconds, 4),
        "warm_runs_seconds": [round(value, 4) for value in timings],
        "warm_median_seconds": round(statistics.median(timings), 4),
        "word_count": sum(len(item["text"].split()) for item in detections),
        "box_count": len(detections),
        "mean_confidence": round(statistics.mean(scores), 4) if scores else None,
        "text_preview": " ".join(item["text"] for item in detections)[:1000],
    }


def benchmark_vision(pdf_path: Path, worker, language: str, dpi: int, runs: int) -> dict:
    import pymupdf

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
        image_path = Path(handle.name)
    try:
        with pymupdf.open(pdf_path) as doc:
            pixmap = doc[0].get_pixmap(dpi=dpi, alpha=False)
            pixmap.save(str(image_path))

        timings = []
        detections = []
        engine_ms = []
        for _ in range(max(1, runs)):
            request = json.dumps({"image_path": str(image_path), "language": language})
            started = time.perf_counter()
            worker.stdin.write(request + "\n")
            worker.stdin.flush()
            response = json.loads(worker.stdout.readline())
            timings.append(time.perf_counter() - started)
            if response.get("error"):
                raise RuntimeError(response["error"])
            detections = response.get("detections", [])
            engine_ms.append(float(response.get("elapsed_ms", 0)))
        return {
            "engine": "macos-vision-fast",
            "language": language,
            "dpi": dpi,
            "warm_runs_seconds": [round(value, 4) for value in timings],
            "warm_median_seconds": round(statistics.median(timings), 4),
            "vision_recognition_median_ms": round(statistics.median(engine_ms), 2),
            "granularity": "line",
            "box_count": len(detections),
            "word_count": sum(len(item.get("text", "").split()) for item in detections),
            "mean_confidence": round(statistics.mean(
                float(item["confidence"]) for item in detections if item.get("confidence") is not None
            ), 4) if any(item.get("confidence") is not None for item in detections) else None,
            "text_preview": " ".join(item.get("text", "") for item in detections)[:1000],
        }
    finally:
        image_path.unlink(missing_ok=True)


def start_vision_worker():
    import shutil
    import sys

    if sys.platform != "darwin":
        return None, {"engine": "macos-vision-fast", "available": False, "reason": "requires macOS"}
    swiftc = shutil.which("swiftc")
    if not swiftc:
        return None, {"engine": "macos-vision-fast", "available": False, "reason": "swiftc not found"}
    worker_dir = tempfile.TemporaryDirectory(prefix="dc-vision-benchmark-")
    binary = Path(worker_dir.name) / "vision-ocr-worker"
    source = Path(__file__).with_name("vision_ocr_worker.swift")
    started = time.perf_counter()
    compile_result = subprocess.run(
        [swiftc, str(source), "-o", str(binary)],
        capture_output=True, text=True, check=False,
    )
    compile_seconds = time.perf_counter() - started
    if compile_result.returncode:
        worker_dir.cleanup()
        return None, {
            "engine": "macos-vision-fast", "available": False,
            "reason": compile_result.stderr.strip() or "Swift compilation failed",
        }
    process = subprocess.Popen(
        [str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, bufsize=1,
    )
    return (worker_dir, process), {
        "engine": "macos-vision-fast", "available": True,
        "helper_compile_seconds": round(compile_seconds, 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, nargs="+")
    parser.add_argument("--engine", choices=("native", "paddle", "vision", "all"), default="all")
    parser.add_argument("--paddle-language", default="pl")
    parser.add_argument("--vision-language", default="pl-PL")
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    output = []
    vision = None
    vision_status = None
    if args.engine in {"vision", "all"}:
        vision, vision_status = start_vision_worker()
    try:
        for pdf_path in args.pdf:
            entry = {"file": str(pdf_path), "bytes": pdf_path.stat().st_size, "results": []}
            if args.engine in {"native", "all"}:
                entry["results"].append(benchmark_native(pdf_path))
            if args.engine in {"paddle", "all"}:
                if package_version("paddleocr") is None:
                    entry["results"].append({"engine": "paddleocr", "available": False})
                else:
                    entry["results"].append(benchmark_paddle(
                        pdf_path, args.paddle_language, args.dpi, args.runs,
                    ))
            if args.engine in {"vision", "all"}:
                if vision is None:
                    entry["results"].append(vision_status)
                else:
                    vision_result = benchmark_vision(
                        pdf_path, vision[1], args.vision_language, args.dpi, args.runs,
                    )
                    vision_result["helper_compile_seconds"] = vision_status["helper_compile_seconds"]
                    entry["results"].append(vision_result)
            output.append(entry)
    finally:
        if vision is not None:
            process = vision[1]
            process.stdin.close()
            process.wait(timeout=5)
            vision[0].cleanup()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
