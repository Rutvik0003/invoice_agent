"""Stage 3b: values OCR missed are confirmed only by our own records or by arithmetic anchored on the page."""

from app.pipeline.engine import run_rules
from app.schemas import FieldVerification
from app.verification.cross_check import cross_check
from app.verification.verify import is_trusted
from tests.rules_fixtures import BUYER, INTER, INTRA, SETTINGS, invoice, repo, verification

T = SETTINGS.confidence_threshold


def checked(inv, ver):
    return cross_check(inv, ver, repo(), T)


def test_buyer_gstin_matching_zenith_is_confirmed_even_if_ocr_missed_it():
    inv = invoice()
    out = checked(inv, verification(inv, buyer_gstin="not_found"))
    field = out.fields["buyer_gstin"]
    assert field.status == "cross_checked" and field.source == "master_data"
    assert BUYER.legal_name in field.matched_text
    assert is_trusted("buyer_gstin", inv, out, T)


def test_a_different_buyer_gstin_stays_not_found():
    inv = invoice(buyer_gstin="27AAAAA0000A1Z5")
    assert checked(inv, verification(inv, buyer_gstin="not_found")).fields["buyer_gstin"].status == "not_found"


def test_vendor_gstin_confirmed_by_the_vendor_named_on_the_page():
    inv = invoice()
    out = checked(inv, verification(inv, vendor_gstin="not_found"))
    assert out.fields["vendor_gstin"].status == "cross_checked"
    assert "V1" in out.fields["vendor_gstin"].matched_text


def test_vendor_name_confirmed_by_the_gstin_on_the_page():
    inv = invoice(vendor_name="Sharma IT Solutions Pvt. Ltd.")
    out = checked(inv, verification(inv, vendor_name="not_found"))
    assert out.fields["vendor_name"].status == "cross_checked"


def test_gstin_of_another_vendor_is_not_confirmed():
    """The AI's GSTIN belongs to a different vendor than the name: a misread, so nothing is confirmed."""
    inv = invoice(vendor_gstin=INTER.gstin)
    out = checked(inv, verification(inv, vendor_gstin="not_found", vendor_name="not_found"))
    assert out.fields["vendor_gstin"].status == "not_found"
    assert out.fields["vendor_name"].status == "not_found"


def test_one_wrong_character_in_the_gstin_is_not_confirmed():
    inv = invoice(vendor_gstin=INTRA.gstin[:-1] + "6")
    assert checked(inv, verification(inv, vendor_gstin="not_found")).fields["vendor_gstin"].status == "not_found"


def test_even_with_ocr_unavailable_the_records_confirm_identity_fields():
    inv = invoice(confidence=0.5)
    out = checked(inv, verification(inv, status="unavailable"))
    for name in ("buyer_gstin", "vendor_gstin", "vendor_name", "bank_account", "po_reference"):
        assert out.fields[name].status == "cross_checked", name
    # amounts have no page anchor, so they stay unavailable (and low confidence still holds them)
    assert out.fields["total_amount"].status == "unavailable"
    assert not is_trusted("total_amount", inv, out, T)


def test_bank_account_must_be_the_one_on_file():
    inv = invoice(bank_account="99999999999")
    assert checked(inv, verification(inv, bank_account="not_found")).fields["bank_account"].status == "not_found"


def test_po_of_another_vendor_is_not_confirmed():
    inv = invoice(po_reference="PO-2026-1002")  # belongs to V2
    assert checked(inv, verification(inv, po_reference="not_found")).fields["po_reference"].status == "not_found"


def test_total_confirmed_from_subtotal_and_gst_on_the_page():
    inv = invoice()
    out = checked(inv, verification(inv, total_amount="not_found"))
    assert out.fields["total_amount"].status == "cross_checked"
    assert out.fields["total_amount"].source == "calculation"


def test_a_total_that_does_not_add_up_stays_not_found():
    inv = invoice(total_amount=71000.0)
    assert checked(inv, verification(inv, total_amount="not_found")).fields["total_amount"].status == "not_found"


def test_total_needs_an_anchor_on_the_page():
    """Subtotal, taxes and total all missing from the page: AI numbers agreeing with each other prove nothing."""
    inv = invoice()
    ver = verification(inv, total_amount="not_found", subtotal="not_found", cgst="not_found", sgst="not_found")
    out = checked(inv, ver)
    assert {out.fields[n].status for n in ("total_amount", "subtotal", "cgst", "sgst")} == {"not_found"}


def test_one_gst_half_confirms_the_other():
    inv = invoice()
    out = checked(inv, verification(inv, sgst="not_found"))
    assert out.fields["sgst"].status == "cross_checked"


def test_subtotal_from_line_amounts_found_on_the_page():
    inv = invoice()
    ver = verification(inv, subtotal="not_found").model_copy(update={"line_items": [FieldVerification(status="verified")]})
    assert checked(inv, ver).fields["subtotal"].status == "cross_checked"


def test_cross_checked_invoice_is_approved_with_a_note():
    inv = invoice()
    out = checked(inv, verification(inv, vendor_gstin="not_found", total_amount="not_found"))
    decision = run_rules(inv, out, repo(), SETTINGS).decision
    assert decision.outcome == "APPROVE" and decision.approve_with_note
    note = next(r for r in decision.reasons if r.code == "FIELD_CROSS_CHECKED")
    assert "vendor_gstin" in note.message and "total_amount" in note.message


def test_invoice_number_cannot_be_cross_checked_so_it_still_holds():
    inv = invoice()
    out = checked(inv, verification(inv, invoice_number="not_found"))
    assert out.fields["invoice_number"].status == "not_found"
    assert run_rules(inv, out, repo(), SETTINGS).decision.outcome == "HOLD"


def test_a_misread_buyer_gstin_is_confirmed_when_the_page_shows_zeniths():
    """Groq read Zenith's 27RHRCZ5469N1Z7 as 27RHRCS5469N1Z7: invalid check digit, one letter off, ours on the page."""
    from dataclasses import replace

    from app.pipeline.normalise import gstin_check_char
    from app.verification.page_text import PageWords, Word
    from tests.rules_fixtures import BUYER, INTER, PENDING, BLOCKED, PO_OPEN, PO_PARTIAL, PO_CLOSED, PO_PENDING, HISTORY
    from app.pipeline.repository import InMemoryRepository

    ours = "27RHRCZ5469N1Z" + gstin_check_char("27RHRCZ5469N1Z")
    buyer = replace(BUYER, gstin=ours)
    world = InMemoryRepository(buyer, [INTRA, INTER, PENDING, BLOCKED], [PO_OPEN, PO_PARTIAL, PO_CLOSED, PO_PENDING],
                               list(HISTORY))
    misread = ours.replace("CZ", "CS", 1)
    inv = invoice(buyer_gstin=misread)
    page = PageWords(1, "text_layer", [Word(ours, (0.1, 0.2, 0.3, 0.22), (1, 0))])
    out = cross_check(inv, verification(inv, buyer_gstin="not_found"), world, T, [page])
    field = out.fields["buyer_gstin"]
    assert field.status == "cross_checked" and field.reference_value == ours and field.page == 1
    assert run_rules(inv, out, world, SETTINGS).decision.outcome == "APPROVE"

    # not on the page -> stays not found; a valid GSTIN of someone else is never "corrected"
    assert cross_check(inv, verification(inv, buyer_gstin="not_found"), world, T, []).fields["buyer_gstin"].status == "not_found"
    other = "27AAAAA0000A1Z" + gstin_check_char("27AAAAA0000A1Z")
    inv2 = invoice(buyer_gstin=other)
    assert cross_check(inv2, verification(inv2, buyer_gstin="not_found"), world, T, [page]).fields["buyer_gstin"].status == "not_found"
