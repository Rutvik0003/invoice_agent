"""Tests for invoice rendering, label schema, self-verification and scan degradation."""

import io
import json
import random

import numpy as np
import pytest
from pydantic import ValidationError

from datagen.degrade import degrade, rasterise, rotate_box, save_scan
from datagen.labels import FieldBox, Label
from datagen.master_data import DEFAULT_SEED, build_master
from datagen.render import render_planned, write_label
from datagen.scenarios import TEMPLATES, Planner
from datagen.self_verify import check_file, iou
from datagen.templates.layouts import RENDERERS


@pytest.fixture(scope="module")
def planner():
    return Planner(build_master(), DEFAULT_SEED)


@pytest.mark.parametrize("template", TEMPLATES)
def test_every_template_prints_key_values_inside_their_boxes(planner, template, tmp_path):
    planned = planner.clean(f"T_{template}", "stress", template=template)
    label = render_planned(planned, tmp_path, DEFAULT_SEED)
    checks = check_file(label, tmp_path)
    assert checks and all(c.passed for c in checks), [c for c in checks if not c.passed]
    expected_pages = 2 if template == "multipage" else 1
    assert label.ground_truth["page_count"]["value"] >= expected_pages


def test_label_round_trips_through_json(planner, tmp_path):
    label = render_planned(planner.bank_change("T_label", "stress"), tmp_path, DEFAULT_SEED)
    write_label(label, tmp_path / "labels")
    loaded = Label(**json.loads((tmp_path / "labels" / "T_label.json").read_text(encoding="utf-8")))
    assert loaded == label
    assert loaded.ground_truth["invoice_number"]["printed"] == planner_number(label)
    assert loaded.expected_reason_codes == ["BANK_DETAILS_MISMATCH"]


def planner_number(label):
    return label.ground_truth["invoice_number"]["value"]


def test_label_schema_rejects_bad_boxes_and_unknown_codes(planner, tmp_path):
    with pytest.raises(ValidationError):
        FieldBox(page=1, bbox=[0.5, 0.5, 0.4, 0.6], approximate=False)
    label = render_planned(planner.clean("T_codes", "stress"), tmp_path, DEFAULT_SEED)
    with pytest.raises(ValidationError):
        Label(**{**label.model_dump(), "expected_reason_codes": ["NOT_A_REAL_CODE"]})


def test_rotate_box_identity_and_direction():
    box = [0.1, 0.1, 0.2, 0.15]
    assert rotate_box(box, 0, 1000, 1400) == box
    rotated = rotate_box(box, 3, 1000, 1400)
    # counter-clockwise rotation moves a top-left box down
    assert rotated[1] > box[1]


def test_iou():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0


def _rendered_pdf(planner, template="classic"):
    planned = planner.clean("T_scan", "stress", template=template)
    buffer = io.BytesIO()
    result = RENDERERS[planned.spec.template](planned.spec, buffer)
    return buffer.getvalue(), result


@pytest.mark.parametrize("level", ["mild", "heavy"])
def test_degrade_keeps_pages_and_boxes(planner, level):
    pdf, result = _rendered_pdf(planner)
    scan = degrade(pdf, result.field_boxes, level, [], random.Random(1))
    assert len(scan.pages) == result.page_count
    assert set(scan.field_boxes) == set(result.field_boxes)
    for box in scan.field_boxes.values():
        assert all(0 <= c <= 1 for c in box["bbox"])
    assert f"{level}_scan" in scan.degradations
    assert scan.dpi == (100 if level == "heavy" else scan.dpi) and 100 <= scan.dpi <= 200


def test_obscured_field_is_covered(planner):
    pdf, result = _rendered_pdf(planner)

    def ink_coverage(page, bbox):
        """Share of pixels in the box darker than paper."""
        crop = page.crop((int(bbox[0] * page.width), int(bbox[1] * page.height),
                          int(bbox[2] * page.width), int(bbox[3] * page.height)))
        return float((np.asarray(crop.convert("L")) < 200).mean())

    clean = rasterise(pdf, 100)[0][0]
    assert ink_coverage(clean, result.field_boxes["total_amount"]["bbox"]) < 0.6  # just the digit strokes
    for seed in range(4):  # different obscuring methods
        scan = degrade(pdf, result.field_boxes, "heavy", ["total_amount"], random.Random(seed))
        assert ink_coverage(scan.pages[0], scan.field_boxes["total_amount"]["bbox"]) > 0.8
        assert any(d.startswith("obscured_total_amount") for d in scan.degradations)


def test_save_scan_formats(planner, tmp_path):
    pdf, result = _rendered_pdf(planner)
    scan = degrade(pdf, result.field_boxes, "mild", [], random.Random(3))
    save_scan(scan, tmp_path / "a.pdf", "pdf")
    save_scan(scan, tmp_path / "a.png", "png")
    save_scan(scan, tmp_path / "a.jpg", "jpg")
    assert all((tmp_path / f"a.{ext}").stat().st_size > 10_000 for ext in ("pdf", "png", "jpg"))
    pdf2, result2 = _rendered_pdf(planner, "multipage")
    two_pages = degrade(pdf2, result2.field_boxes, "mild", [], random.Random(4))
    with pytest.raises(ValueError):
        save_scan(two_pages, tmp_path / "b.png", "png")
