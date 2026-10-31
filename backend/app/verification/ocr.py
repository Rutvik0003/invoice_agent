"""Tesseract OCR: words, boxes and confidences for scanned pages and photos.

Light preprocessing (grayscale, auto-contrast, cheap deskew). Boxes are mapped back to the original
page image so the UI can highlight them. Any Tesseract failure raises OcrUnavailable (rule 14).
"""

from __future__ import annotations

import math
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytesseract
from PIL import Image, ImageFilter, ImageOps
from pydantic import BaseModel

from app.config import Settings
from app.verification.page_text import PageWords, Word


class OcrStatus(BaseModel):
    available: bool
    version: str | None


class OcrUnavailable(Exception):
    """Tesseract is missing or crashed; verification falls back to model confidence."""


def configure_tesseract(settings: Settings) -> None:
    """Point pytesseract at TESSERACT_CMD when set; otherwise it uses `tesseract` from PATH."""
    if settings.tesseract_cmd.strip():
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd.strip()


def tesseract_status(settings: Settings) -> OcrStatus:
    """Report whether Tesseract can be run; any failure means 'unavailable', never an exception."""
    try:
        configure_tesseract(settings)
        return OcrStatus(available=True, version=str(pytesseract.get_tesseract_version()))
    except Exception:
        return OcrStatus(available=False, version=None)


def estimate_skew(gray: Image.Image, max_angle: float = 5.0, step: float = 0.25) -> float:
    """Angle (degrees) that makes text lines horizontal: the rotation whose row profile is sharpest."""
    small = gray.copy()
    small.thumbnail((900, 900))
    ink = np.asarray(small) < 160
    if ink.mean() < 0.002:
        return 0.0
    mask = Image.fromarray((ink * 255).astype(np.uint8))
    best_angle, best_score = 0.0, -1.0
    for angle in np.arange(-max_angle, max_angle + step / 2, step):
        rows = np.asarray(mask.rotate(float(angle), resample=Image.NEAREST)).sum(axis=1).astype(np.float64)
        score = float(np.var(rows))
        if score > best_score:
            best_angle, best_score = float(angle), score
    return best_angle


def _unrotate_box(box: tuple[float, float, float, float], angle: float, w: int, h: int) -> tuple[float, float, float, float]:
    """Map a box found on the deskewed image back onto the original image (PIL rotates counter-clockwise)."""
    a = math.radians(-angle)
    cx, cy = w / 2, h / 2
    corners = [(box[0], box[1]), (box[2], box[1]), (box[0], box[3]), (box[2], box[3])]
    moved = [(cx + (x - cx) * math.cos(a) + (y - cy) * math.sin(a), cy - (x - cx) * math.sin(a) + (y - cy) * math.cos(a))
             for x, y in corners]
    xs, ys = [p[0] for p in moved], [p[1] for p in moved]
    return max(min(xs), 0), max(min(ys), 0), min(max(xs), w), min(max(ys), h)


def preprocess(image: Image.Image, deskew: bool = True, denoise: int = 0, contrast: bool = True) -> tuple[Image.Image, float]:
    """Grayscale, optional auto-contrast, optional median denoise, optional deskew -> (image, angle used)."""
    gray = ImageOps.grayscale(image)
    if contrast:
        gray = ImageOps.autocontrast(gray, cutoff=1)
    if denoise:
        gray = gray.filter(ImageFilter.MedianFilter(denoise))
    angle = estimate_skew(gray) if deskew else 0.0
    if abs(angle) < 0.25:
        return gray, 0.0
    return gray.rotate(angle, resample=Image.BICUBIC, fillcolor=255), angle


# (sharpen?, page-segmentation mode), most useful first. Each pass misreads different words; the union finds far
# more printed values (mild scans, 25-file sample: 1 pass 80%, first 2 passes 89%, first 3 or all 4 passes 91%),
# and a wrong AI value still has to match a word exactly, so extra words do not let hallucinations through.
OCR_PASSES: tuple[tuple[bool, int], ...] = ((False, 3), (True, 11), (True, 3), (False, 11))


def available_cpus() -> float:
    """CPUs this process may use: the container's CPU quota (cgroup v2, then v1) if one is set, else the core count."""
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()[:2]
        if quota != "max":
            return int(quota) / int(period)
    except (OSError, ValueError):
        pass
    try:
        quota = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text())
        period = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text())
        if quota > 0:
            return quota / period
    except (OSError, ValueError):
        pass
    return float(os.cpu_count() or 1)


def passes_for(cpus: float) -> tuple[tuple[bool, int], ...]:
    """All passes cost ~6 CPU-seconds per A4 page. On a fraction of a CPU (Render's free instance has 0.1) they
    would overrun the per-page timeout and lose OCR entirely, so smaller machines run fewer passes: lower recall
    means more 'not found on page' holds, never a value trusted without evidence."""
    if cpus >= 2:
        return OCR_PASSES
    if cpus >= 0.5:
        return OCR_PASSES[:2]
    return OCR_PASSES[:1]


OCR_TIMEOUT_S = 20  # per page: a stuck or very slow Tesseract must not hold a run hostage


def _run_pass(work: Image.Image, sharpen: bool, psm: int) -> dict:
    image = work.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3)) if sharpen else work
    return pytesseract.image_to_data(image, config=f"--oem 1 --psm {psm}", output_type=pytesseract.Output.DICT,
                                     timeout=OCR_TIMEOUT_S)


def ocr_image(image: Image.Image, page_no: int, settings: Settings, deskew: bool = True, denoise: int = 0,
              contrast: bool = True, psm: int | None = None) -> PageWords:
    """OCR one page image -> words with normalised boxes on the ORIGINAL image and per-word confidence.

    By default runs as many OCR_PASSES as the CPUs allow, in parallel (Tesseract runs as separate processes),
    and keeps the words from all of them; psm=N runs just one plain pass with that mode.
    """
    configure_tesseract(settings)
    work, angle = preprocess(image, deskew, denoise, contrast)
    passes = passes_for(available_cpus()) if psm is None else ((False, psm),)
    try:
        with ThreadPoolExecutor(max_workers=len(passes)) as pool:
            results = list(pool.map(lambda p: _run_pass(work, *p), passes))
    except Exception as exc:  # noqa: BLE001 - never crash a run because of OCR
        raise OcrUnavailable(f"{type(exc).__name__}: {exc}") from exc
    w, h = work.size
    words = []
    for pass_no, data in enumerate(results):
        for i, text in enumerate(data["text"]):
            conf = float(data["conf"][i])
            if not text.strip() or conf < settings.ocr_min_word_conf:
                continue
            box = (data["left"][i], data["top"][i], data["left"][i] + data["width"][i], data["top"][i] + data["height"][i])
            if angle:
                box = _unrotate_box(box, angle, w, h)
            line = (pass_no, data["block_num"][i], data["par_num"][i], data["line_num"][i])
            words.append(Word(text.strip(), (box[0] / w, box[1] / h, box[2] / w, box[3] / h), line, round(conf, 1)))
    return PageWords(page_no, "ocr", words)
