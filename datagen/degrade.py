"""Scan degradation for rendered invoice pages (mild / heavy), targeted obscuring of a field, and extras.

Field boxes are transformed with the same rotation as the page so labels still point at the values
(marked approximate after rotation, because the box of a rotated rectangle is a little larger).
"""

from __future__ import annotations

import io
import math
import random
from dataclasses import dataclass, field

import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFilter, ImageFont

MILD = "mild"
HEAVY = "heavy"


@dataclass
class ScanResult:
    pages: list[Image.Image]
    page_sizes_pt: list[tuple[float, float]]
    field_boxes: dict[str, dict]
    degradations: list[str] = field(default_factory=list)
    jpeg_quality: int = 75
    dpi: int = 150


def rasterise(pdf_bytes: bytes, dpi: int) -> tuple[list[Image.Image], list[tuple[float, float]]]:
    """Render every PDF page to an RGB image."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    images, sizes = [], []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        images.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
        sizes.append((page.rect.width, page.rect.height))
    return images, sizes


def _pixel_box(bbox: list[float], img: Image.Image) -> tuple[float, float, float, float]:
    return bbox[0] * img.width, bbox[1] * img.height, bbox[2] * img.width, bbox[3] * img.height


def rotate_box(bbox: list[float], angle_deg: float, width: int, height: int) -> list[float]:
    """Where a normalised box ends up after PIL rotates the page by angle_deg (counter-clockwise, about the centre)."""
    a = math.radians(angle_deg)
    cx, cy = width / 2, height / 2
    corners = [(bbox[0] * width, bbox[1] * height), (bbox[2] * width, bbox[1] * height),
               (bbox[0] * width, bbox[3] * height), (bbox[2] * width, bbox[3] * height)]
    moved = [(cx + (x - cx) * math.cos(a) + (y - cy) * math.sin(a),
              cy - (x - cx) * math.sin(a) + (y - cy) * math.cos(a)) for x, y in corners]
    xs, ys = [p[0] for p in moved], [p[1] for p in moved]
    clamp = lambda v: round(min(max(v, 0.0), 1.0), 5)  # noqa: E731
    return [clamp(min(xs) / width), clamp(min(ys) / height), clamp(max(xs) / width), clamp(max(ys) / height)]


def _add_noise(img: Image.Image, sigma: float, rng: random.Random) -> Image.Image:
    arr = np.asarray(img).astype(np.int16)
    noise = np.random.default_rng(rng.randint(0, 2**31)).normal(0, sigma, arr.shape[:2])[..., None]
    return Image.fromarray(np.clip(arr + noise, 0, 255).astype(np.uint8))


def _jpeg_roundtrip(img: Image.Image, quality: int) -> Image.Image:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


def _shadow_gradient(img: Image.Image, rng: random.Random) -> Image.Image:
    """Uneven lighting, as when a page is photographed or scanned with the lid open."""
    w, h = img.size
    xs = np.linspace(0, 1, w)[None, :]
    ys = np.linspace(0, 1, h)[:, None]
    direction = rng.choice(["left", "right", "top", "corner"])
    grad = {"left": 1 - xs + ys * 0, "right": xs + ys * 0, "top": 1 - ys + xs * 0, "corner": (xs + ys) / 2}[direction]
    shade = 1 - 0.35 * grad
    arr = np.asarray(img).astype(np.float32) * shade[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def _free_spot(img: Image.Image, size: tuple[int, int], avoid: list[tuple[float, float, float, float]],
               rng: random.Random) -> tuple[int, int]:
    """Top-left corner for an overlay that does not cover any key value (falls back to a margin)."""
    w, h = size
    for _ in range(60):
        x, y = rng.randint(0, max(1, img.width - w)), rng.randint(0, max(1, img.height - h))
        if all(x + w < bx0 or x > bx1 or y + h < by0 or y > by1 for bx0, by0, bx1, by1 in avoid):
            return x, y
    return rng.randint(0, max(1, img.width - w)), img.height - h - 5


def _coffee_stain(img: Image.Image, avoid, rng: random.Random) -> Image.Image:
    r = int(img.width * rng.uniform(0.07, 0.12))
    x, y = _free_spot(img, (2 * r, 2 * r), avoid, rng)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.ellipse([x, y, x + 2 * r, y + 2 * r], fill=(150, 105, 50, 45), outline=(120, 80, 35, 120), width=max(3, r // 12))
    return Image.alpha_composite(img.convert("RGBA"), overlay.filter(ImageFilter.GaussianBlur(3))).convert("RGB")


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arialbd.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _rubber_stamp(img: Image.Image, avoid, rng: random.Random, text: str = "RECEIVED") -> Image.Image:
    size = int(img.width * 0.16)
    x, y = _free_spot(img, (size, size), avoid, rng)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    colour = rng.choice([(200, 30, 40, 150), (40, 60, 170, 150)])
    draw.ellipse([x, y, x + size, y + size], outline=colour, width=max(3, size // 25))
    draw.ellipse([x + size // 9, y + size // 9, x + size - size // 9, y + size - size // 9], outline=colour, width=max(2, size // 40))
    draw.text((x + size / 2, y + size / 2), text, fill=colour, font=_font(max(10, size // 7)), anchor="mm")
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def _signature(img: Image.Image, avoid, rng: random.Random) -> Image.Image:
    w, h = int(img.width * 0.2), int(img.height * 0.04)
    x, y = _free_spot(img, (w, h), avoid, rng)
    draw = ImageDraw.Draw(img)
    points = [(x + i * w / 24, y + h / 2 + math.sin(i * rng.uniform(0.8, 1.6)) * h / 2 * rng.uniform(0.4, 1)) for i in range(25)]
    draw.line(points, fill=(20, 30, 110), width=max(2, img.width // 500), joint="curve")
    return img


def _punch_holes(img: Image.Image) -> Image.Image:
    draw = ImageDraw.Draw(img)
    r = int(img.width * 0.012)
    x = int(img.width * 0.025)
    for frac in (0.38, 0.62):
        y = int(img.height * frac)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(30, 30, 30))
    return img


def _fax(img: Image.Image) -> Image.Image:
    grey = img.convert("L")
    return grey.point(lambda v: 255 if v > 150 else 0).convert("RGB")


def obscure(img: Image.Image, bbox: list[float], method: str, rng: random.Random) -> Image.Image:
    """Make one printed value unreadable: an ink blot, a heavy smudge, or a dense stamp on top of it."""
    x0, y0, x1, y1 = _pixel_box(bbox, img)
    pad_x, pad_y = (x1 - x0) * 0.12 + 4, (y1 - y0) * 0.35 + 4
    box = [int(x0 - pad_x), int(y0 - pad_y), int(x1 + pad_x), int(y1 + pad_y)]
    if method == "smudge":
        region = img.crop(box).filter(ImageFilter.GaussianBlur(max(6, (y1 - y0) * 0.45)))
        img.paste(region, box[:2])
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(overlay).rectangle(box, fill=(90, 90, 90, 175))
        return Image.alpha_composite(img.convert("RGBA"), overlay.filter(ImageFilter.GaussianBlur(4))).convert("RGB")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    colour = (25, 25, 60, 245) if method == "ink_blot" else (170, 30, 40, 235)
    for _ in range(9):  # irregular blob made of overlapping ellipses
        jx, jy = rng.uniform(-0.15, 0.15) * (box[2] - box[0]), rng.uniform(-0.3, 0.3) * (box[3] - box[1])
        draw.ellipse([box[0] + jx, box[1] + jy, box[2] + jx, box[3] + jy], fill=colour)
    draw.rectangle(box, fill=colour)
    return Image.alpha_composite(img.convert("RGBA"), overlay.filter(ImageFilter.GaussianBlur(2))).convert("RGB")


def degrade(pdf_bytes: bytes, field_boxes: dict[str, dict], level: str, obscured_fields: list[str],
            rng: random.Random) -> ScanResult:
    """Turn a clean PDF into scanned page images, keeping field boxes in step with the page."""
    dpi = rng.randint(150, 200) if level == MILD else 100
    pages, sizes = rasterise(pdf_bytes, dpi)
    boxes = {name: dict(box) for name, box in field_boxes.items()}
    applied = [f"{level}_scan", f"dpi_{dpi}"]

    # 1. obscure chosen fields on the clean page (exact boxes)
    for name in obscured_fields:
        method = rng.choice(["ink_blot", "smudge", "stamp"])
        for key, box in boxes.items():  # every place the value is printed
            if key == name or key.startswith(f"{name}#"):
                pages[box["page"] - 1] = obscure(pages[box["page"] - 1], box["bbox"], method, rng)
        applied.append(f"obscured_{name}_{method}")

    # 2. extras that avoid key values
    extras = rng.sample(["rubber_stamp", "signature", "punch_holes", "coffee_stain", "fax"], k=rng.randint(0, 2))
    if level == HEAVY:
        extras = list(dict.fromkeys(extras + ["coffee_stain"]))
    for index, img in enumerate(pages):
        avoid = [_pixel_box(b["bbox"], img) for b in boxes.values() if b["page"] == index + 1]
        if "rubber_stamp" in extras:
            img = _rubber_stamp(img, avoid, rng, rng.choice(["RECEIVED", "VERIFIED", "ACCOUNTS"]))
        if "signature" in extras:
            img = _signature(img, avoid, rng)
        if "punch_holes" in extras:
            img = _punch_holes(img)
        if "coffee_stain" in extras:
            img = _coffee_stain(img, avoid, rng)
        if level == HEAVY:
            img = _shadow_gradient(img, rng)
        pages[index] = img
    applied += extras

    # 3. scanner effects: rotation, blur, noise, (fax), JPEG compression
    angle = rng.uniform(-1.5, 1.5) if level == MILD else rng.choice([-1, 1]) * rng.uniform(2.0, 4.0)
    blur = rng.uniform(0.3, 0.7) if level == MILD else rng.uniform(1.0, 1.5)
    sigma = rng.uniform(3, 7) if level == MILD else rng.uniform(12, 20)
    quality = rng.randint(60, 80) if level == MILD else rng.randint(35, 50)
    for index, img in enumerate(pages):
        img = img.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=(255, 255, 255))
        img = img.filter(ImageFilter.GaussianBlur(blur))
        img = _add_noise(img, sigma, rng)
        if "fax" in extras:
            img = _fax(img)
        pages[index] = _jpeg_roundtrip(img, quality)
    for box in boxes.values():
        img = pages[box["page"] - 1]
        box["bbox"] = rotate_box(box["bbox"], angle, img.width, img.height)
        box["approximate"] = abs(angle) > 0.05
    applied += [f"rotation_{angle:+.1f}deg", f"blur_{blur:.1f}", f"noise_{sigma:.0f}", f"jpeg_q{quality}"]
    return ScanResult(pages, sizes, boxes, applied, quality, dpi)


def save_scan(result: ScanResult, path, file_format: str) -> None:
    """Image-only PDF (one JPEG per page), or a single PNG/JPG image."""
    if file_format == "pdf":
        doc = pymupdf.open()
        for img, (w, h) in zip(result.pages, result.page_sizes_pt):
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=result.jpeg_quality)
            page = doc.new_page(width=w, height=h)
            page.insert_image(page.rect, stream=buf.getvalue())
        doc.save(str(path), garbage=3, deflate=True, no_new_id=True)
        return
    if len(result.pages) != 1:
        raise ValueError("Image formats hold a single page")
    if file_format == "png":
        result.pages[0].save(path, "PNG", optimize=True, dpi=(result.dpi, result.dpi))
    else:
        result.pages[0].save(path, "JPEG", quality=result.jpeg_quality, dpi=(result.dpi, result.dpi))


# ---------------------------------------------------------------- phone photos (Phase 8 robustness tests)


def _perspective_coeffs(src: list[tuple[float, float]], dst: list[tuple[float, float]]) -> list[float]:
    """PIL PERSPECTIVE coefficients mapping output pixels (dst quad) back to input pixels (src quad)."""
    rows = []
    for (x, y), (u, v) in zip(dst, src):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    return list(np.linalg.solve(np.array(rows, dtype=float), np.array(src, dtype=float).reshape(8)))


def phone_photo(img: Image.Image, rng: random.Random) -> Image.Image:
    """A page photographed with a phone: on a desk, tilted (perspective), unevenly lit, with a glare spot,
    slightly soft and JPEG-compressed. Field boxes are NOT tracked through this (tests check outcomes only)."""
    w, h = img.size
    m = 0.06
    jitter = lambda: rng.uniform(0.0, m)  # noqa: E731
    corners = [(w * jitter(), h * jitter()), (w * (1 - jitter()), h * jitter()),
               (w * (1 - jitter()), h * (1 - jitter())), (w * jitter(), h * (1 - jitter()))]
    canvas_w, canvas_h = int(w * 1.05), int(h * 1.05)
    off_x, off_y = (canvas_w - w) / 2, (canvas_h - h) / 2
    dst = [(x + off_x, y + off_y) for x, y in corners]
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    desk = Image.new("RGB", (canvas_w, canvas_h), (118, 96, 74))
    page = img.transform((canvas_w, canvas_h), Image.PERSPECTIVE, _perspective_coeffs(src, dst), Image.BICUBIC,
                         fillcolor=(0, 0, 0))
    mask = Image.new("L", img.size, 255).transform((canvas_w, canvas_h), Image.PERSPECTIVE,
                                                   _perspective_coeffs(src, dst), Image.BICUBIC, fillcolor=0)
    desk.paste(page, (0, 0), mask)
    photo = _shadow_gradient(desk, rng)
    # glare: a soft bright ellipse that washes out part of the page
    gx, gy = rng.uniform(0.2, 0.8) * canvas_w, rng.uniform(0.2, 0.8) * canvas_h
    ys, xs = np.mgrid[0:canvas_h, 0:canvas_w]
    radius = 0.18 * canvas_w
    glare = np.exp(-(((xs - gx) / radius) ** 2 + ((ys - gy) / (radius * 0.6)) ** 2)) * 0.55
    arr = np.asarray(photo).astype(np.float32)
    arr = arr + (255 - arr) * glare[..., None]
    photo = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8))
    return _jpeg_roundtrip(_add_noise(photo, 4, rng), 80)
