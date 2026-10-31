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
from app.logging_setup import get_logger
from app.verification.page_text import PageWords, Word


logger = get_logger("ocr")


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


# (image variant, page-segmentation mode). Each pass misreads different words; the union finds far more printed
# values (mild scans, 25-file sample: 1 pass 80%, 2 passes 89%, 4 passes 91%), and a wrong AI value still has to
# match a word exactly, so extra words do not let hallucinations through. Every machine runs every pass.
# The 'adaptive' pass (local threshold) reads faded or unevenly lit print: real receipt photos 16 -> 18 of 33 values,
# held-out scans 94.8% -> 96.7%, mild stress scans 92.0% -> 93.0%.
OCR_PASSES: tuple[tuple[str, int], ...] = (("plain", 3), ("sharp", 11), ("sharp", 3), ("plain", 11), ("adaptive", 3))
ADAPTIVE_RADIUS = 25  # neighbourhood (pixels) a pixel is compared with
ADAPTIVE_OFFSET = 12  # how much darker than its neighbourhood a pixel must be to count as ink
# Share of black pixels above which the adaptive image is mostly noise (heavy scans: median 19%, golden 08: 12%)
# and the pass is skipped: there it read nothing, yet took ~5x longer and ~100 MB more memory. Ordinary pages
# stay below it (mild scans <= 6.4%, phone photos <= 9.3%); the two receipt photos above it gained nothing.
ADAPTIVE_MAX_INK = 0.10


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


def available_memory_mb() -> float | None:
    """The container's memory limit in MB (cgroup v2, then v1), or None when there is no limit."""
    for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            value = Path(path).read_text().strip()
        except OSError:
            continue
        if value.isdigit() and int(value) < 1 << 50:  # cgroup v1 writes a huge number for "no limit"
            return int(value) / 1024 / 1024
    return None


# Measured in the Docker image on a 300-DPI A4 scan (peak, OCR code only): 1 or 2 passes at once ~340 MB, 3 ~400 MB,
# 4 ~466 MB. The running server (FastAPI, database) needs more on top, so a 512 MB machine runs at most 2 at once.
APP_BASE_MB = 330
TESSERACT_MB = 65


def parallel_passes(cpus: float, memory_mb: float | None) -> int:
    """How many passes may run at once: no more than whole CPUs (extra processes on a fraction of a CPU only
    fight each other) and no more than the memory limit allows. 1 means one after another - slower, same result."""
    by_cpu = max(1, int(cpus))
    by_memory = len(OCR_PASSES) if memory_mb is None else max(1, int((memory_mb - APP_BASE_MB) // TESSERACT_MB))
    return min(len(OCR_PASSES), by_cpu, by_memory)


OCR_TIMEOUT_S = 20  # per pass on one full CPU: a stuck Tesseract must not hold a run hostage


def pass_timeout(cpus: float) -> int:
    """The per-pass time limit, stretched on a fraction of a CPU (0.1 CPU -> 200 s) so slow machines are
    patient rather than giving up on OCR; accuracy matters more than speed here."""
    return int(OCR_TIMEOUT_S / min(max(cpus, 0.1), 1.0))


def adaptive_threshold(gray: Image.Image, radius: int = ADAPTIVE_RADIUS, offset: int = ADAPTIVE_OFFSET) -> Image.Image:
    """Black where a pixel is clearly darker than its neighbourhood's mean, white elsewhere: faint print on a
    shaded or uneven background becomes crisp, where one global contrast setting would lose it."""
    pixels = np.asarray(gray, dtype=np.int16)
    local_mean = np.asarray(gray.filter(ImageFilter.BoxBlur(radius)), dtype=np.int16)
    return Image.fromarray(np.where(pixels < local_mean - offset, 0, 255).astype(np.uint8))


def variants(work: Image.Image, wanted: set[str]) -> dict[str, Image.Image]:
    """The page images the passes read, each built once; 'adaptive' is left out when it is mostly noise."""
    out = {"plain": work}
    if "sharp" in wanted:
        out["sharp"] = work.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))
    if "adaptive" in wanted:
        binary = adaptive_threshold(work)
        if (np.asarray(binary) == 0).mean() <= ADAPTIVE_MAX_INK:
            out["adaptive"] = binary
    return out


def _run_pass(image: Image.Image, psm: int, timeout: int = OCR_TIMEOUT_S) -> dict:
    return pytesseract.image_to_data(image, config=f"--oem 1 --psm {psm}", output_type=pytesseract.Output.DICT,
                                     timeout=timeout)


def _try_pass(image: Image.Image, psm: int, timeout: int) -> dict | Exception:
    try:
        return _run_pass(image, psm, timeout)
    except Exception as exc:  # noqa: BLE001 - one failed pass must not throw away the others
        return exc


def ocr_image(image: Image.Image, page_no: int, settings: Settings, deskew: bool = True, denoise: int = 0,
              contrast: bool = True, psm: int | None = None) -> PageWords:
    """OCR one page image -> words with normalised boxes on the ORIGINAL image and per-word confidence.

    By default runs every pass in OCR_PASSES (as many at once as CPUs and memory allow; Tesseract runs as
    separate processes) and keeps the words from all that succeed; psm=N runs just one plain pass with that mode.
    Only if every pass fails is OCR unavailable for the page.
    """
    configure_tesseract(settings)
    work, angle = preprocess(image, deskew, denoise, contrast)
    passes = OCR_PASSES if psm is None else (("plain", psm),)
    images = variants(work, {variant for variant, _ in passes})
    passes = tuple(p for p in passes if p[0] in images)
    cpus = available_cpus()
    timeout = pass_timeout(cpus)
    with ThreadPoolExecutor(max_workers=min(len(passes), parallel_passes(cpus, available_memory_mb()))) as pool:
        outcomes = list(pool.map(lambda p: _try_pass(images[p[0]], p[1], timeout), passes))
    failures = [o for o in outcomes if isinstance(o, Exception)]
    if len(failures) == len(outcomes):
        raise OcrUnavailable(f"{type(failures[0]).__name__}: {failures[0]}")
    if failures:
        logger.warning("some OCR passes failed", extra={"page": page_no, "failed": len(failures),
                                                        "error": f"{type(failures[0]).__name__}: {failures[0]}"})
    results = [o for o in outcomes if not isinstance(o, Exception)]
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
