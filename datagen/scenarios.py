"""Scenario definitions: each one sets up the master data it needs, builds an invoice and declares its expected outcome.

Rule 6: expected decisions and reason codes come from these definitions only. Nothing here imports or
runs the decision engine or the verifier.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from datagen.catalog import CATALOG, CatalogItem
from datagen.formats import abbreviate_name
from datagen.gstin import STATES, make_bank_account, make_gstin, make_ifsc, make_pan
from datagen.invoice_spec import InvoiceSpec, Party, SpecLine, money
from datagen.master_data import (
    BANKS,
    CITIES,
    COINED_WORDS,
    REFERENCE_DATE,
    HistoryInvoice,
    MasterData,
    PurchaseOrder,
    Vendor,
    random_price,
    random_quantity,
)

TEMPLATES = ("classic", "modern", "services", "compact", "multipage", "landscape", "tally", "small_vendor")
SERVICE_CATEGORIES = ("it_services", "logistics", "facility_management")
VERIFIED_FIELDS = (
    "vendor_gstin", "vendor_name", "invoice_number", "invoice_date", "total_amount", "po_reference",
    "subtotal", "cgst", "sgst", "igst", "bank_account", "buyer_gstin",
)
LOW_SIGNAL = {"confidence": 0.40, "verification_status": "not_found"}
DOUBTFUL_CODES = ["FIELD_NOT_VERIFIED", "LOW_CONFIDENCE_FIELD"]
# fields our own records can confirm when the scan hides them (vendor master / the page's arithmetic)
CROSS_CHECKABLE = {"vendor_gstin": "the vendor master (GSTIN of the vendor named on the page)",
                   "total_amount": "the page's own arithmetic (subtotal + GST)"}

APPROVE, HOLD, REJECT = "APPROVE", "HOLD", "REJECT"

OTHER_BUYERS = [
    ("Horizon Lifestyle Pvt Ltd", "Unit 4, Phoenix Market City, Kurla West, Mumbai - 400070, Maharashtra"),
    ("Nova Hypermarts Pvt Ltd", "Survey No. 112, Baner Road, Pune - 411045, Maharashtra"),
    ("Zenitha Fashions LLP", "22, Linking Road, Bandra West, Mumbai - 400050, Maharashtra"),
    ("Sahyadri Supermart Pvt Ltd", "Plot 9, MIDC Ambad, Nashik - 422010, Maharashtra"),
]
NOT_INVOICE_DOCS = [
    ("quotation", "Quotation", "Quotation No."),
    ("proforma", "Proforma Invoice", "Proforma No."),
    ("credit_note", "Credit Note", "Credit Note No."),
    ("delivery_challan", "Delivery Challan", "Challan No."),
    ("purchase_order", "Purchase Order", "Order No."),
]


@dataclass
class PlannedInvoice:
    """An invoice to render, with everything the label needs except where things landed on the page."""

    spec: InvoiceSpec
    set_name: str  # golden | stress
    scenario: str
    expected_decision: str
    expected_reason_codes: list[str]
    acceptable_decisions: list[str] = field(default_factory=list)
    expected_reason_codes_any_of: list[list[str]] = field(default_factory=list)
    scan: str = "none"  # none | mild | heavy
    file_format: str = "pdf"  # pdf | png | jpg
    obscured_fields: list[str] = field(default_factory=list)
    true_po_number: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.acceptable_decisions:
            self.acceptable_decisions = [self.expected_decision]

    @property
    def is_scanned(self) -> bool:
        return self.scan != "none"

    def rules_eval_signals(self) -> dict[str, dict]:
        """What the rules evaluation should assume Stage 2/3 reported for each verified field."""
        printed = self.spec.printed_values()
        signals = {}
        for name in VERIFIED_FIELDS:
            if name in self.obscured_fields:
                signals[name] = dict(LOW_SIGNAL)
            elif printed.get(name) is None:
                signals[name] = {"confidence": 0.95, "verification_status": "not_applicable"}
            else:
                signals[name] = {"confidence": 0.95, "verification_status": "verified"}
        return signals


def normalise_invoice_number(number: str) -> str:
    """Generator-side copy of the §6 rule, used only to prove disguised duplicates still collide."""
    compact = re.sub(r"[\s\-/_.]", "", number.upper())
    match = re.fullmatch(r"([A-Z]*)0*(\d+)", compact)
    return f"{match.group(1)}{match.group(2)}" if match else compact


def disguise_invoice_number(number: str, rng: random.Random) -> str:
    """Restyle an invoice number so it looks different but normalises to the same value (KOS-0457 -> KOS/457)."""
    candidates = set()
    for old, new in (("/", "-"), ("-", "/"), ("/", " / "), ("-", " "), ("/", ""), ("-", "")):
        if old in number:
            candidates.add(number.replace(old, new))
    leading = re.fullmatch(r"([A-Za-z]+)([-/ ]?)(0+)(\d+)", number)
    if leading:
        prefix, _, _, digits = leading.groups()
        candidates.update({f"{prefix}/{digits}", f"{prefix}-{digits}", f"{prefix}{digits}"})
    if re.fullmatch(r"\d+", number):
        candidates.add("0" + number)
    if any(ch.isalpha() for ch in number):
        candidates.add(number.lower())
    candidates = sorted(c for c in candidates if c != number and normalise_invoice_number(c) == normalise_invoice_number(number))
    if not candidates:
        raise ValueError(f"Cannot disguise invoice number {number!r}")
    return rng.choice(candidates)


class Planner:
    """Builds every golden and stress invoice against one shared MasterData."""

    def __init__(self, md: MasterData, seed: int) -> None:
        self.md = md
        self.rng = random.Random(seed + 2)
        self.buyer_party = Party(
            name=md.buyer.legal_name,
            address=md.buyer.address,
            gstin=md.buyer.gstin,
            state=md.buyer.state,
            state_code=md.buyer.state_code,
        )
        self._unknown_vendor_names: set[str] = set()
        self._no_po_vendors: list[Vendor] = []  # exclusive vendors shared by the stress no-PO scenarios

    # ---------------------------------------------------------------- building blocks

    def vendor_party(self, vendor: Vendor) -> Party:
        return Party(vendor.legal_name, vendor.address, vendor.gstin, vendor.state, vendor.state_code, vendor.phone, vendor.email)

    def invoice_date_for(self, po: PurchaseOrder | None, after: date | None = None) -> date:
        """A date in the last few weeks, after the PO and after any earlier invoice on it."""
        earliest = REFERENCE_DATE - timedelta(days=25)
        if po is not None:
            earliest = max(earliest, po.po_date + timedelta(days=3))
            billed_dates = [h.invoice_date for h in self.md.history if h.po_number == po.po_number]
            if billed_dates:
                earliest = max(earliest, max(billed_dates) + timedelta(days=2))
        if after is not None:
            earliest = max(earliest, after + timedelta(days=1))
        latest = REFERENCE_DATE - timedelta(days=1)
        if earliest > latest:
            earliest = latest
        return earliest + timedelta(days=self.rng.randint(0, (latest - earliest).days))

    def fresh_po(
        self,
        vendor: Vendor | None = None,
        intra_state: bool | None = None,
        n_lines: tuple[int, int] = (1, 5),
        min_value: Decimal = Decimal("15000"),
        categories: tuple[str, ...] | None = None,
        items: list[CatalogItem] | None = None,
    ) -> PurchaseOrder:
        """A new open PO for an approved, unreserved vendor (used when the seeded POs run out)."""
        if vendor is None:
            vendor = self.md.reserve_vendor(
                status="approved",
                intra_state=intra_state,
                predicate=lambda v: categories is None or v.category in categories,
                exclusive=False,
            )
        po_date = REFERENCE_DATE - timedelta(days=self.rng.randint(20, 110))
        while True:
            chosen = items or self.rng.sample(CATALOG[vendor.category], k=self.rng.randint(*n_lines))
            lines = [(item, random_quantity(self.rng, item), random_price(self.rng, item)) for item in chosen]
            if sum(qty * price for _, qty, price in lines) >= min_value or items:
                return self.md.add_po(vendor, po_date, lines)

    def clean_po(self, intra_state: bool | None = None, categories: tuple[str, ...] | None = None,
                 min_open_lines: int = 1) -> PurchaseOrder:
        """An open or part-billed PO of an approved vendor with something left to bill."""
        try:
            return self.md.reserve_po(
                intra_state=intra_state,
                predicate=lambda p: p.po_date <= REFERENCE_DATE - timedelta(days=5)
                and (categories is None or self.md.vendor_of(p).category in categories)
                and sum(l.qty_remaining > 0 for l in p.lines) >= min_open_lines,
            )
        except LookupError:
            n = max(min_open_lines, 1)
            return self.fresh_po(intra_state=intra_state, categories=categories, n_lines=(n, max(n, 5)))

    def pick_quantities(self, po: PurchaseOrder, max_share: float = 1.0) -> dict[int, int]:
        """Bill some of what is left on the PO; never more than max_share of any line's remaining quantity."""
        open_lines = [line for line in po.lines if line.qty_remaining > 0]
        chosen = self.rng.sample(open_lines, k=self.rng.randint(1, len(open_lines)))
        quantities = {}
        for line in chosen:
            cap = max(1, int(line.qty_remaining * max_share))
            quantities[line.line_no] = self.rng.randint(max(1, cap // 2), cap)
        return quantities

    def spec_from_po(
        self,
        invoice_id: str,
        po: PurchaseOrder,
        quantities: dict[int, int],
        inv_date: date,
        template: str | None = None,
        invoice_number: str | None = None,
        allow_adjustments: bool = False,
    ) -> InvoiceSpec:
        """An honest invoice for the given quantities of a PO, at PO prices, with randomised print knobs."""
        vendor = self.md.vendor_of(po)
        lines = [
            SpecLine(
                description=po.line(no).description,
                hsn_sac=po.line(no).hsn_sac,
                quantity=qty,
                unit=po.line(no).unit,
                unit_price=po.line(no).unit_price,
                gst_rate=po.line(no).gst_rate,
                po_line_no=no,
            )
            for no, qty in sorted(quantities.items())
        ]
        spec = InvoiceSpec(
            invoice_id=invoice_id,
            template=template or self.choose_template(lines),
            document_type="tax_invoice",
            title="Tax Invoice",
            vendor=self.vendor_party(vendor),
            buyer=self.buyer_party,
            invoice_number=invoice_number or self.md.next_invoice_number(vendor, inv_date),
            invoice_date=inv_date,
            po_reference=po.po_number,
            lines=lines,
            tax_split="cgst_sgst" if vendor.is_intra_state else "igst",
            bank_name=vendor.bank_name,
            bank_account=vendor.bank_account,
            bank_ifsc=vendor.ifsc,
            payment_terms_days=vendor.payment_terms_days,
        )
        self.apply_knobs(spec, vendor, allow_adjustments)
        spec.compute_totals()
        return spec

    def choose_template(self, lines: list[SpecLine]) -> str:
        all_services = all(line.hsn_sac.startswith("99") for line in lines)
        options = [t for t in TEMPLATES if len(lines) >= 3 or t != "multipage"]  # multipage needs a few lines
        if all_services:
            return self.rng.choice(options + ["services", "services"])
        return self.rng.choice([t for t in options if t != "services"])

    def apply_knobs(self, spec: InvoiceSpec, vendor: Vendor | None, allow_adjustments: bool) -> None:
        """Randomise how the invoice is printed (titles, labels, formats, optional lines)."""
        rng = self.rng
        spec.title = rng.choice(["Tax Invoice", "TAX INVOICE", "GST Invoice", "Invoice"])
        spec.invoice_no_label = rng.choice(["Invoice No.", "Inv. No.", "Bill No.", "Invoice #"])
        spec.date_label = rng.choice(["Date", "Inv Date", "Dated"])
        spec.po_label = rng.choice(["PO No.", "P.O. Ref", "Your Order No.", "Against PO"])
        spec.po_in_notes = rng.random() < 0.15
        if spec.po_reference and rng.random() < 0.2:
            spec.po_reference = spec.po_reference.replace("-", "/")
        spec.date_style = rng.choice(
            ["dd/mm/yyyy", "dd-mm-yyyy", "d Mon yyyy", "dd-Mon-yy", "Month d, yyyy", "yyyy-mm-dd"]
        )
        spec.amount_style = rng.choice(["rupee_symbol", "rs_slash", "inr_plain", "no_symbol"])
        spec.tax_per_line = rng.random() < 0.5
        spec.show_round_off = rng.random() < 0.75
        spec.show_amount_in_words = rng.random() < 0.7
        spec.gstin_spaced = rng.random() < 0.15
        spec.vendor_name_printed = self.printed_vendor_name(vendor) if vendor else spec.vendor.name
        template_rules = {
            "classic": {"tax_per_line": True},
            "compact": {"tax_per_line": False},
            "landscape": {"tax_per_line": False},
            "tally": {"show_amount_in_words": True, "invoice_no_label": "Invoice No.", "date_label": "Dated",
                      "po_label": "Buyer's Order No."},
        }
        for key, value in template_rules.get(spec.template, {}).items():
            setattr(spec, key, value)
        subtotal = sum((line.amount for line in spec.lines), Decimal("0"))
        if allow_adjustments and len({line.gst_rate for line in spec.lines}) == 1 and not spec.tax_per_line:
            charges = [c for c in (250, 400, 500, 750, 1200, 1800, 2500) if c <= subtotal * Decimal("0.10")]
            if charges and rng.random() < 0.3:
                spec.other_charges = money(rng.choice(charges))
                spec.other_charges_label = rng.choice(["Freight Charges", "Packing & Forwarding", "Transport Charges"])
            if rng.random() < 0.2:
                spec.discount = money(subtotal * Decimal(rng.choice([1, 2, 2.5, 3, 5])) / 100)
        spec.notes = [rng.choice([
            "Goods once sold will not be taken back.",
            "Interest @ 18% p.a. will be charged on payments delayed beyond the due date.",
            "Subject to Mumbai jurisdiction.",
            "Please quote the invoice number in all payment advices.",
            "Certified that the particulars given above are true and correct.",
        ])]
        spec.knobs = {
            "title": spec.title,
            "invoice_no_label": spec.invoice_no_label,
            "date_label": spec.date_label,
            "po_label": spec.po_label,
            "po_in_notes": spec.po_in_notes,
            "date_style": spec.date_style,
            "amount_style": spec.amount_style,
            "tax_per_line": spec.tax_per_line,
            "show_round_off": spec.show_round_off,
            "show_amount_in_words": spec.show_amount_in_words,
            "gstin_spaced": spec.gstin_spaced,
            "discount": str(spec.discount),
            "other_charges": str(spec.other_charges),
        }

    def printed_vendor_name(self, vendor: Vendor) -> str:
        """Legal name, trade name or an abbreviation (proprietors always print the business name)."""
        is_proprietor = vendor.pan[3] == "P"
        options = [vendor.trade_name, abbreviate_name(vendor.trade_name)] if is_proprietor else [
            vendor.legal_name, vendor.trade_name, abbreviate_name(vendor.legal_name)
        ]
        return self.rng.choice(options)

    def planned(self, spec: InvoiceSpec, set_name: str, scenario: str, decision: str, codes: list[str], **kwargs) -> PlannedInvoice:
        spec.knobs["vendor_name_printed"] = spec.vendor_name_printed
        spec.knobs["template"] = spec.template
        return PlannedInvoice(spec=spec, set_name=set_name, scenario=scenario, expected_decision=decision,
                              expected_reason_codes=codes, **kwargs)

    # ---------------------------------------------------------------- scenarios

    def clean(self, invoice_id: str, set_name: str, template: str | None = None, intra_state: bool | None = None,
              scenario: str = "CLEAN_EXACT", allow_adjustments: bool = True) -> PlannedInvoice:
        """Approved vendor, PO quoted, everything matches the PO -> APPROVE."""
        po = self.clean_po(intra_state=intra_state)
        spec = self.spec_from_po(invoice_id, po, self.pick_quantities(po, 0.8), self.invoice_date_for(po), template,
                                 allow_adjustments=allow_adjustments)
        return self.planned(spec, set_name, scenario, APPROVE, [], true_po_number=po.po_number,
                            notes="Clean invoice that exactly matches its PO.")

    def within_tolerance(self, invoice_id: str, set_name: str, template: str | None = None,
                         target_diff: Decimal | None = None) -> PlannedInvoice:
        """One line priced slightly above the PO, well inside min(1%, ₹500) -> APPROVE with a note."""
        while True:
            po = self.clean_po() if target_diff is None else self.fresh_po(n_lines=(1, 2), min_value=Decimal("120000"))
            quantities = self.pick_quantities(po, 0.6)
            spec = self.spec_from_po(invoice_id, po, quantities, self.invoice_date_for(po), template)
            line = max(spec.lines, key=lambda l: l.correct_amount)
            # target_diff must stay under 0.4% of the line value (tolerance is 1%, capped at ₹500)
            if target_diff is None or line.correct_amount * Decimal("0.004") >= target_diff:
                break
        wanted = target_diff if target_diff is not None else min(line.correct_amount * Decimal("0.004"), Decimal("200"))
        bump = max(Decimal("0.01"), money(wanted / line.quantity))
        old = line.unit_price
        line.unit_price = money(old + bump)
        spec.compute_totals()
        return self.planned(spec, set_name, "CLEAN_WITHIN_TOLERANCE", APPROVE, ["PRICE_VARIANCE_WITHIN_TOLERANCE"],
                            true_po_number=po.po_number,
                            notes=f"'{line.description}' billed at ₹{line.unit_price} vs PO ₹{old} "
                                  f"(₹{money(bump * line.quantity)} on the line), inside tolerance.")

    def overrun(self, invoice_id: str, set_name: str, template: str | None = None) -> PlannedInvoice:
        """Third partial invoice: two earlier bills took ~88% of the PO, this one takes ~25% more -> HOLD."""
        po = self.fresh_po(n_lines=(1, 2), min_value=Decimal("60000"))
        for line in po.lines:  # make quantities divisible enough to split
            if line.qty_ordered < 20:
                line.qty_ordered = 20 + self.rng.randint(0, 20)
        first_date = po.po_date + timedelta(days=self.rng.randint(8, 15))
        second_date = first_date + timedelta(days=self.rng.randint(6, 12))
        first = {l.line_no: int(l.qty_ordered * 0.5) for l in po.lines}
        second = {l.line_no: int(l.qty_ordered * 0.88) - first[l.line_no] for l in po.lines}
        h1 = self.md.bill(po, first, first_date)
        h2 = self.md.bill(po, second, second_date)
        third = {l.line_no: max(l.qty_remaining + 1, int(l.qty_ordered * 0.25)) for l in po.lines}
        spec = self.spec_from_po(invoice_id, po, third, self.invoice_date_for(po), template)
        return self.planned(spec, set_name, "PO_OVERRUN", HOLD, ["PO_OVERRUN", "QTY_EXCEEDS_PO"],
                            true_po_number=po.po_number,
                            notes=f"Earlier bills {h1.invoice_number} and {h2.invoice_number} took 88% of {po.po_number}; "
                                  "this invoice bills ~25% more, so the PO is exceeded.")

    def _history_on_reserved_po(self, predicate) -> tuple[PurchaseOrder, HistoryInvoice]:
        po = self.md.reserve_po(
            statuses=("partially_billed", "closed"),
            predicate=lambda p: any(predicate(h) for h in self.md.history if h.po_number == p.po_number),
        )
        original = self.rng.choice([h for h in self.md.history if h.po_number == po.po_number and predicate(h)])
        return po, original

    def _replay_history(self, invoice_id: str, po: PurchaseOrder, original: HistoryInvoice, number: str,
                        inv_date: date, template: str | None) -> InvoiceSpec:
        """Re-create a past invoice exactly (same lines and totals)."""
        quantities = {line.po_line_no: line.quantity for line in original.lines}
        spec = self.spec_from_po(invoice_id, po, quantities, inv_date, template, invoice_number=number)
        spec.tax_per_line = False
        spec.show_round_off = True
        spec.knobs.update(tax_per_line=False, show_round_off=True)
        spec.compute_totals()
        spec.cgst, spec.sgst, spec.igst = original.cgst, original.sgst, original.igst
        spec.round_off, spec.total_amount = original.round_off, original.total_amount
        return spec

    def duplicate(self, invoice_id: str, set_name: str, disguised: bool, template: str | None = None,
                  golden_style: bool = False) -> PlannedInvoice:
        """A past (already approved/paid) invoice sent again, number exact or restyled -> REJECT."""
        if golden_style:
            pattern = re.compile(r"[A-Z]+-0\d+")
            po, original = self._history_on_reserved_po(lambda h: bool(pattern.fullmatch(h.invoice_number)))
        else:
            po, original = self._history_on_reserved_po(lambda h: True)
        if golden_style:
            number = re.sub(r"-0*", "/", original.invoice_number, count=1)  # KOS-0457 -> KOS/457
        elif disguised:
            number = disguise_invoice_number(original.invoice_number, self.rng)
        else:
            number = original.invoice_number
        spec = self._replay_history(invoice_id, po, original, number, original.invoice_date, template)
        scenario = "DUPLICATE_DISGUISED_NUMBER" if disguised else "DUPLICATE_EXACT_NUMBER"
        return self.planned(spec, set_name, scenario, REJECT, ["DUPLICATE_INVOICE_NUMBER"], true_po_number=po.po_number,
                            notes=f"Duplicate of history {original.history_id} ({original.invoice_number}, "
                                  f"{original.invoice_date}, ₹{original.total_amount}, {original.status}); printed as {number}.")

    def possible_duplicate(self, invoice_id: str, set_name: str) -> PlannedInvoice:
        """Same vendor and amount as a recent invoice, dated 1-2 days apart, new number -> HOLD."""
        po = self.fresh_po(n_lines=(1, 3), min_value=Decimal("20000"))
        for line in po.lines:
            line.qty_ordered = max(line.qty_ordered, 4) * 3
        quantities = {l.line_no: l.qty_ordered // 3 for l in po.lines}
        original_date = REFERENCE_DATE - timedelta(days=self.rng.randint(6, 15))
        original = self.md.bill(po, quantities, original_date)
        inv_date = original_date + timedelta(days=self.rng.choice([-2, -1, 1, 2]))
        spec = self._replay_history(invoice_id, po, original, self.md.next_invoice_number(self.md.vendor_of(po), inv_date),
                                    inv_date, None)
        return self.planned(spec, set_name, "POSSIBLE_DUPLICATE", HOLD, ["POSSIBLE_DUPLICATE"], true_po_number=po.po_number,
                            notes=f"Same vendor and total (₹{original.total_amount}) as {original.invoice_number} "
                                  f"dated {original.invoice_date}; different invoice number.")

    def _free_items(self, vendor: Vendor) -> list[CatalogItem]:
        """Catalog items of the vendor's category that none of its open POs contain."""
        open_items = {l.description for p in self.md.pos if p.vendor_id == vendor.vendor_id and p.status != "closed"
                      for l in p.lines}
        return [item for item in CATALOG[vendor.category] if item.description not in open_items]

    def _no_po_vendor(self, min_free: int, only_closed_pos: bool = False) -> tuple[Vendor, list[CatalogItem]]:
        """An exclusively reserved vendor plus catalog items that none of its open POs contain.

        Stress no-PO scenarios share vendors; each uses items no other open PO of that vendor has,
        so a PO can only ever be inferred from the invoice it was created for.
        """
        if not only_closed_pos:
            reusable = [v for v in self._no_po_vendors if len(self._free_items(v)) >= min_free]
            if reusable:
                vendor = self.rng.choice(reusable)
                return vendor, self._free_items(vendor)

        def suitable(v: Vendor) -> bool:
            if only_closed_pos and any(p.status != "closed" for p in self.md.pos if p.vendor_id == v.vendor_id):
                return False
            return len(self._free_items(v)) >= min_free

        vendor = self.md.reserve_vendor(status="approved", predicate=suitable)
        if not only_closed_pos:
            self._no_po_vendors.append(vendor)
        return vendor, self._free_items(vendor)

    def no_po_clear(self, invoice_id: str, set_name: str, template: str | None = None,
                    only_two_open_pos: bool = False) -> PlannedInvoice:
        """No PO printed; exactly one open PO of this vendor matches the items and amount -> HOLD (PO_INFERRED)."""
        if only_two_open_pos:
            try:
                vendor, free = self._no_po_vendor(4, only_closed_pos=True)
            except LookupError:
                vendor, free = self._no_po_vendor(4)
        else:
            vendor, free = self._no_po_vendor(2)
        self.rng.shuffle(free)
        k = self.rng.randint(1, min(3, len(free) - 1))
        target = self.fresh_po(vendor, items=free[:k])
        if only_two_open_pos:  # the golden story: a second open PO for different items
            self.fresh_po(vendor, items=free[k:k + self.rng.randint(1, 3)])
        quantities = {l.line_no: l.qty_ordered for l in target.lines}
        spec = self.spec_from_po(invoice_id, target, quantities, self.invoice_date_for(target), template)
        spec.po_reference = None
        spec.po_in_notes = False
        spec.knobs["po_in_notes"] = False
        return self.planned(spec, set_name, "NO_PO_CLEAR_MATCH", HOLD, ["PO_INFERRED"], true_po_number=target.po_number,
                            notes=f"No PO printed. {target.po_number} matches every item, quantity and amount; "
                                  "none of the vendor's other open POs contain these items.")

    def no_po_ambiguous(self, invoice_id: str, set_name: str) -> PlannedInvoice:
        """No PO printed; two repeat-order POs match equally well -> HOLD (PO_AMBIGUOUS)."""
        vendor, free = self._no_po_vendor(2)
        items = self.rng.sample(free, k=self.rng.randint(1, 2))
        first = self.fresh_po(vendor, items=items)
        second = self.md.add_po(vendor, first.po_date + timedelta(days=self.rng.randint(5, 20)),
                                [(item, l.qty_ordered, l.unit_price) for item, l in zip(items, first.lines)])
        quantities = {l.line_no: max(1, l.qty_ordered // 2) for l in first.lines}
        spec = self.spec_from_po(invoice_id, first, quantities, self.invoice_date_for(second), None)
        spec.po_reference = None
        spec.po_in_notes = False
        spec.knobs["po_in_notes"] = False
        return self.planned(spec, set_name, "NO_PO_AMBIGUOUS", HOLD, ["PO_AMBIGUOUS"], true_po_number=None,
                            notes=f"No PO printed. {first.po_number} and {second.po_number} are identical repeat orders.")

    def bank_change(self, invoice_id: str, set_name: str, template: str | None = None) -> PlannedInvoice:
        """Bank account (and usually IFSC) differ from the vendor master -> HOLD (fraud flag)."""
        po = self.clean_po()
        spec = self.spec_from_po(invoice_id, po, self.pick_quantities(po, 0.8), self.invoice_date_for(po), template)
        self._change_bank(spec)
        return self.planned(spec, set_name, "BANK_CHANGE", HOLD, ["BANK_DETAILS_MISMATCH"], true_po_number=po.po_number,
                            notes="Bank details on the invoice differ from the vendor master.")

    def _change_bank(self, spec: InvoiceSpec) -> None:
        bank_name, code = self.rng.choice(BANKS)
        spec.bank_account = make_bank_account(self.rng)
        if self.rng.random() < 0.8:
            spec.bank_name, spec.bank_ifsc = bank_name, make_ifsc(code, self.rng)

    def wrong_gst(self, invoice_id: str, set_name: str, template: str | None = None,
                  intra_state: bool | None = None) -> PlannedInvoice:
        """Inter-state vendor charges CGST+SGST, or a same-state vendor charges IGST -> REJECT."""
        if intra_state is None:
            intra_state = self.rng.random() < 0.5
        po = self.clean_po(intra_state=intra_state)
        spec = self.spec_from_po(invoice_id, po, self.pick_quantities(po, 0.8), self.invoice_date_for(po), template)
        spec.tax_split = "igst" if intra_state else "cgst_sgst"
        spec.compute_totals()
        wrong = "IGST charged by a Maharashtra vendor" if intra_state else "CGST+SGST charged by an out-of-state vendor"
        return self.planned(spec, set_name, "GST_WRONG_TYPE", REJECT, ["GST_TYPE_INVALID"], true_po_number=po.po_number,
                            notes=wrong + ".")

    def heavy_scan(self, invoice_id: str, set_name: str, template: str | None = None,
                   obscure: str | None = None, scenario: str = "HEAVY_SCAN_LOW_CONFIDENCE",
                   scan: str = "heavy") -> PlannedInvoice:
        """A correct invoice whose scan hides one critical field.

        Invoice number or date hidden -> HOLD until a person confirms it (nothing else can confirm it).
        Vendor GSTIN hidden -> the vendor master confirms the GSTIN the AI read (its name is on the page);
        total hidden -> subtotal + GST printed on the page add up to it. Both -> APPROVE with a note
        (FIELD_CROSS_CHECKED); a real scan may also hide the anchors, so HOLD stays acceptable there.
        """
        po = self.clean_po()
        spec = self.spec_from_po(invoice_id, po, self.pick_quantities(po, 0.8), self.invoice_date_for(po), template)
        field_name = obscure or self.rng.choice(["total_amount", "invoice_number", "invoice_date", "vendor_gstin"])
        if field_name == "total_amount":  # the words would give the hidden total away
            spec.show_amount_in_words = False
            spec.knobs["show_amount_in_words"] = False
        if field_name in CROSS_CHECKABLE:
            return self.planned(spec, set_name, scenario, APPROVE, [], acceptable_decisions=[APPROVE, HOLD],
                                expected_reason_codes_any_of=[["FIELD_CROSS_CHECKED", *DOUBTFUL_CODES]],
                                scan=scan, obscured_fields=[field_name],
                                true_po_number=po.po_number,
                                notes=f"Underlying invoice is correct; {field_name} is obscured on the {scan} scan, "
                                      f"but {CROSS_CHECKABLE[field_name]} confirms it.")
        return self.planned(spec, set_name, scenario, HOLD, [], acceptable_decisions=[HOLD],
                            expected_reason_codes_any_of=[DOUBTFUL_CODES], scan=scan, obscured_fields=[field_name],
                            true_po_number=po.po_number,
                            notes=f"Underlying invoice is correct, but {field_name} is obscured on the {scan} scan.")

    def price_over(self, invoice_id: str, set_name: str, template: str | None = None, pct: int | None = None) -> PlannedInvoice:
        """One line billed 3-8% above the PO price -> HOLD for the buyer to accept or dispute."""
        po = self.clean_po()
        spec = self.spec_from_po(invoice_id, po, self.pick_quantities(po, 0.5), self.invoice_date_for(po), template)
        pct = pct or self.rng.randint(3, 8)
        line = max(spec.lines, key=lambda l: l.correct_amount)
        old = line.unit_price
        line.unit_price = money(old * (100 + pct) / 100)
        spec.compute_totals()
        return self.planned(spec, set_name, "PRICE_OVER_TOLERANCE", HOLD, ["PRICE_VARIANCE_OVER_TOLERANCE"],
                            true_po_number=po.po_number,
                            notes=f"'{line.description}' billed at ₹{line.unit_price} vs PO ₹{old} (+{pct}%).")

    def qty_exceeds(self, invoice_id: str, set_name: str) -> PlannedInvoice:
        """One line bills more units than remain on the PO (but the PO total is not exceeded) -> HOLD."""
        po = self.fresh_po(n_lines=(3, 5), min_value=Decimal("40000"))
        small = min(po.lines, key=lambda l: l.line_value)
        extra = max(1, small.qty_ordered // 10)
        spec = self.spec_from_po(invoice_id, po, {small.line_no: small.qty_ordered + extra}, self.invoice_date_for(po), None)
        return self.planned(spec, set_name, "QTY_EXCEEDS_PO", HOLD, ["QTY_EXCEEDS_PO"], true_po_number=po.po_number,
                            notes=f"'{small.description}': billed {small.qty_ordered + extra}, PO has {small.qty_ordered}.")

    def item_not_on_po(self, invoice_id: str, set_name: str) -> PlannedInvoice:
        """An extra line for an item that is not on the PO -> HOLD."""
        po = self.clean_po()
        spec = self.spec_from_po(invoice_id, po, self.pick_quantities(po, 0.5), self.invoice_date_for(po), None)
        self._add_unordered_item(spec, po)
        return self.planned(spec, set_name, "ITEM_NOT_ON_PO", HOLD, ["ITEM_NOT_ON_PO"], true_po_number=po.po_number,
                            notes=f"'{spec.lines[-1].description}' is not on {po.po_number}.")

    def _add_unordered_item(self, spec: InvoiceSpec, po: PurchaseOrder) -> None:
        on_po = {l.description for l in po.lines}
        vendor = self.md.vendor_of(po)
        # Keep the extra item small (<= 5% of what is left on the PO) so the PO total is not exceeded too
        budget = max(po.remaining_value * Decimal("0.05"), Decimal("1"))
        candidates = [i for i in CATALOG[vendor.category] if i.description not in on_po]
        affordable = [i for i in candidates if Decimal(str(i.price_max)) <= budget] or [min(candidates, key=lambda i: i.price_min)]
        item = self.rng.choice(affordable)
        price = random_price(self.rng, item)
        qty = max(1, min(int(budget / price), self.rng.randint(1, 5)))
        spec.lines.append(SpecLine(item.description, item.hsn_sac, qty, item.unit, price, item.gst_rate))
        if not spec.single_rate:
            spec.discount = spec.other_charges = Decimal("0.00")
        spec.compute_totals()

    def arithmetic_error(self, invoice_id: str, set_name: str, template: str | None = None,
                         kind: str | None = None, min_lines: int = 1) -> PlannedInvoice:
        """The printed figures do not add up -> REJECT (vendor must reissue)."""
        po = self.clean_po(min_open_lines=min_lines)
        quantities = self.pick_quantities(po, 0.8)
        if min_lines > 1:  # bill every open line so the layout has enough rows
            quantities = {l.line_no: max(1, int(l.qty_remaining * 0.8)) for l in po.lines if l.qty_remaining > 0}
        spec = self.spec_from_po(invoice_id, po, quantities, self.invoice_date_for(po), template)
        self._break_arithmetic(spec, kind)
        return self.planned(spec, set_name, "ARITHMETIC_ERROR", REJECT, ["ARITHMETIC_MISMATCH"], true_po_number=po.po_number,
                            notes=spec.knobs["arithmetic_error"])

    def _break_arithmetic(self, spec: InvoiceSpec, kind: str | None = None) -> None:
        kind = kind or self.rng.choice(["line_amount", "total", "tax"])
        delta = money(max(Decimal("150"), spec.subtotal * Decimal(self.rng.choice([2, 4, 6, 9])) / 100))
        if kind == "line_amount":
            line = self.rng.choice(spec.lines)
            line.amount_override = line.correct_amount + delta
            spec.tax_per_line = False
            message = f"Line '{line.description}' printed as {line.amount} instead of {line.correct_amount}; lines no longer sum to the subtotal."
        elif kind == "total":
            spec.total_amount = spec.total_amount + money(delta).quantize(Decimal("1"))
            message = f"Grand total printed ₹{delta.quantize(Decimal('1'))} too high."
        else:
            if spec.tax_split == "igst":
                spec.igst += delta
            else:
                spec.cgst += delta
            spec.tax_per_line = False
            message = f"A tax amount printed ₹{delta} too high; subtotal + tax no longer equals the total."
        spec.knobs.update(tax_per_line=spec.tax_per_line, arithmetic_error=message)

    def not_an_invoice(self, invoice_id: str, set_name: str, template: str | None = None,
                       doc: tuple[str, str, str] | None = None) -> PlannedInvoice:
        """A quotation / proforma / credit note / challan / PO copy sent to AP -> REJECT."""
        doc_type, title, number_label = doc or self.rng.choice(NOT_INVOICE_DOCS)
        po = self.clean_po()
        spec = self.spec_from_po(invoice_id, po, self.pick_quantities(po, 0.8), self.invoice_date_for(po), template,
                                 allow_adjustments=True)
        spec.document_type, spec.title, spec.invoice_no_label = doc_type, title, number_label
        prefix = {"quotation": "QT", "proforma": "PI", "credit_note": "CN", "delivery_challan": "DC"}.get(doc_type)
        if doc_type == "purchase_order":
            spec.invoice_number = po.po_number
            spec.po_reference = None
        else:
            spec.invoice_number = f"{prefix}-{self.rng.randint(100, 9999)}"
            if doc_type in ("quotation", "proforma"):
                spec.po_reference = None
        spec.knobs.update(title=title, invoice_no_label=number_label)
        return self.planned(spec, set_name, "NOT_AN_INVOICE", REJECT, ["NOT_A_TAX_INVOICE"], true_po_number=po.po_number,
                            notes=f"Document is a {title}, not a tax invoice; its document number is in invoice_number.")

    def vendor_status(self, invoice_id: str, set_name: str, status: str, template: str | None = None) -> PlannedInvoice:
        """A pending (not yet approved) or blocked vendor -> HOLD for procurement."""
        vendor = self.md.reserve_vendor(status=status, exclusive=False)
        po = self.fresh_po(vendor, n_lines=(1, 3))
        spec = self.spec_from_po(invoice_id, po, self.pick_quantities(po, 0.8), self.invoice_date_for(po), template)
        code = "VENDOR_NOT_APPROVED" if status == "pending" else "VENDOR_BLOCKED"
        scenario = "VENDOR_NOT_APPROVED" if status == "pending" else "VENDOR_BLOCKED"
        return self.planned(spec, set_name, scenario, HOLD, [code], true_po_number=po.po_number,
                            notes=f"Vendor {vendor.vendor_id} has status '{status}' in the vendor master.")

    def vendor_unknown(self, invoice_id: str, set_name: str) -> PlannedInvoice:
        """A vendor that is not in the master at all (no PO quoted) -> HOLD for procurement."""
        rng = self.rng
        category = rng.choice(list(CATALOG))
        state_code = rng.choice(list(STATES))
        while True:
            base = rng.choice(COINED_WORDS + ["Mehra", "Kulkarni", "Bhatia", "Rao", "Saxena", "Pillai"])
            name = f"{base} {rng.choice(['Supplies', 'Trading Co.', 'Distributors', 'Agencies'])}"
            if name not in self._unknown_vendor_names and all(name not in v.trade_name for v in self.md.vendors):
                self._unknown_vendor_names.add(name)
                break
        pan = make_pan(rng.choice("CFP"), rng, name_initial=name[0])
        city, pin = rng.choice(CITIES[state_code])
        bank_name, code = rng.choice(BANKS)
        vendor = Party(name, f"{rng.randint(1, 300)}, Industrial Estate, {city} - {pin}{rng.randint(1, 99):03d}, {STATES[state_code]}",
                       make_gstin(state_code, pan, 1), STATES[state_code], state_code,
                       f"+91 {rng.randint(6, 9)}{rng.randint(0, 999999999):09d}", f"accounts@{base.lower()}supplies.in")
        items = rng.sample(CATALOG[category], k=rng.randint(1, 3))
        lines = [SpecLine(i.description, i.hsn_sac, random_quantity(rng, i), i.unit, random_price(rng, i), i.gst_rate) for i in items]
        inv_date = self.invoice_date_for(None)
        spec = InvoiceSpec(
            invoice_id=invoice_id, template=self.choose_template(lines), document_type="tax_invoice", title="Tax Invoice",
            vendor=vendor, buyer=self.buyer_party, invoice_number=f"{name[:2].upper()}/{rng.randint(10, 999)}",
            invoice_date=inv_date, po_reference=None, lines=lines,
            tax_split="cgst_sgst" if state_code == self.md.buyer.state_code else "igst",
            bank_name=bank_name, bank_account=make_bank_account(rng), bank_ifsc=make_ifsc(code, rng), payment_terms_days=30,
        )
        self.apply_knobs(spec, None, allow_adjustments=False)
        spec.po_reference = None
        spec.compute_totals()
        return self.planned(spec, set_name, "VENDOR_UNKNOWN", HOLD, ["VENDOR_UNKNOWN"],
                            notes=f"'{name}' (GSTIN {vendor.gstin}) is not in the vendor master; no PO quoted.")

    def buyer_mismatch(self, invoice_id: str, set_name: str) -> PlannedInvoice:
        """Invoice addressed to a different company -> HOLD."""
        po = self.clean_po()
        spec = self.spec_from_po(invoice_id, po, self.pick_quantities(po, 0.8), self.invoice_date_for(po), None)
        self._change_buyer(spec)
        return self.planned(spec, set_name, "BUYER_MISMATCH", HOLD, ["BUYER_MISMATCH"], true_po_number=po.po_number,
                            notes=f"Addressed to {spec.buyer.name} ({spec.buyer.gstin}), not Zenith Retail.")

    def _change_buyer(self, spec: InvoiceSpec) -> None:
        name, address = self.rng.choice(OTHER_BUYERS)
        gstin = make_gstin("27", make_pan("F" if "LLP" in name else "C", self.rng, name_initial=name[0]), 1)
        spec.buyer = Party(name, address, gstin, "Maharashtra", "27")

    def po_closed(self, invoice_id: str, set_name: str) -> PlannedInvoice:
        """Invoice against a PO that is already fully billed and closed -> REJECT."""
        po = self.md.reserve_po(statuses=("closed",))
        line = self.rng.choice(po.lines)
        qty = max(1, line.qty_ordered // self.rng.choice([2, 3, 4]))
        last_billed = max(h.invoice_date for h in self.md.history if h.po_number == po.po_number)
        spec = self.spec_from_po(invoice_id, po, {line.line_no: qty}, self.invoice_date_for(None, after=last_billed), None)
        return self.planned(spec, set_name, "PO_CLOSED", REJECT, ["PO_CLOSED"], true_po_number=po.po_number,
                            notes=f"{po.po_number} is closed (fully billed).")

    def gst_rate_unusual(self, invoice_id: str, set_name: str) -> PlannedInvoice:
        """A 12% or 28% rate on an invoice dated after GST 2.0 removed those slabs -> HOLD for the tax team."""
        po = self.clean_po()
        spec = self.spec_from_po(invoice_id, po, self.pick_quantities(po, 0.8), self.invoice_date_for(po), None)
        self._unusual_rate(spec)
        return self.planned(spec, set_name, "GST_RATE_UNUSUAL", HOLD, ["GST_RATE_UNUSUAL"], true_po_number=po.po_number,
                            notes=spec.knobs["unusual_rate"])

    def _unusual_rate(self, spec: InvoiceSpec) -> None:
        line = self.rng.choice(spec.lines)
        old = line.gst_rate
        line.gst_rate = 12.0 if old <= 12 else 28.0
        spec.discount = spec.other_charges = Decimal("0.00")
        spec.compute_totals()
        spec.knobs["unusual_rate"] = f"'{line.description}' charged GST {line.gst_rate:g}% (PO {old:g}%) on {spec.invoice_date}."

    def missing_invoice_number(self, invoice_id: str, set_name: str) -> PlannedInvoice:
        """No invoice number printed at all -> HOLD."""
        po = self.clean_po()
        spec = self.spec_from_po(invoice_id, po, self.pick_quantities(po, 0.8), self.invoice_date_for(po), None)
        spec.invoice_number = None
        return self.planned(spec, set_name, "MISSING_INVOICE_NUMBER", HOLD, ["MISSING_REQUIRED_FIELD"],
                            true_po_number=po.po_number, notes="The invoice number is missing from the document.")

    def multi_issue(self, invoice_id: str, set_name: str) -> PlannedInvoice:
        """2-3 independent problems at once; the decision follows severity precedence and every code is listed."""
        po = self.clean_po()
        spec = self.spec_from_po(invoice_id, po, self.pick_quantities(po, 0.5), self.invoice_date_for(po), None)
        problems = sorted(self.rng.sample(["bank", "price_over", "item_not_on_po", "gst_type", "gst_rate", "buyer", "arithmetic"],
                                          k=self.rng.randint(2, 3)))
        codes: list[str] = []
        if "price_over" in problems:
            line = max(spec.lines, key=lambda l: l.correct_amount)
            line.unit_price = money(line.unit_price * Decimal(100 + self.rng.randint(3, 8)) / 100)
            codes.append("PRICE_VARIANCE_OVER_TOLERANCE")
        if "item_not_on_po" in problems:
            self._add_unordered_item(spec, po)
            codes.append("ITEM_NOT_ON_PO")
        if "gst_type" in problems:
            spec.tax_split = "cgst_sgst" if spec.tax_split == "igst" else "igst"
            codes.append("GST_TYPE_INVALID")
        if "gst_rate" in problems:
            self._unusual_rate(spec)
            codes.append("GST_RATE_UNUSUAL")
        spec.compute_totals()
        if "bank" in problems:
            self._change_bank(spec)
            codes.append("BANK_DETAILS_MISMATCH")
        if "buyer" in problems:
            self._change_buyer(spec)
            codes.append("BUYER_MISMATCH")
        if "arithmetic" in problems:
            self._break_arithmetic(spec, self.rng.choice(["total", "line_amount"]))
            codes.append("ARITHMETIC_MISMATCH")
        decision = REJECT if {"GST_TYPE_INVALID", "ARITHMETIC_MISMATCH"} & set(codes) else HOLD
        return self.planned(spec, set_name, "MULTI_ISSUE", decision, sorted(codes), true_po_number=po.po_number,
                            notes="Problems: " + ", ".join(problems) + ".")


# ---------------------------------------------------------------- the two sets

STRESS_COUNTS: dict[str, int] = {
    "CLEAN_EXACT": 40, "CLEAN_WITHIN_TOLERANCE": 15, "PO_OVERRUN": 15,
    "DUPLICATE_EXACT_NUMBER": 8, "DUPLICATE_DISGUISED_NUMBER": 12, "POSSIBLE_DUPLICATE": 8,
    "NO_PO_CLEAR_MATCH": 12, "NO_PO_AMBIGUOUS": 8, "BANK_CHANGE": 12, "GST_WRONG_TYPE": 12,
    "HEAVY_SCAN_LOW_CONFIDENCE": 12, "OBSCURED_INVOICE_NUMBER": 6, "OBSCURED_GSTIN": 4,
    "PRICE_OVER_TOLERANCE": 12, "QTY_EXCEEDS_PO": 8, "ITEM_NOT_ON_PO": 6, "ARITHMETIC_ERROR": 12,
    "NOT_AN_INVOICE": 12, "VENDOR_NOT_APPROVED": 6, "VENDOR_BLOCKED": 4, "VENDOR_UNKNOWN": 8, "BUYER_MISMATCH": 6,
    "PO_CLOSED": 6, "GST_RATE_UNUSUAL": 6, "MISSING_INVOICE_NUMBER": 6, "MULTI_ISSUE": 15,
}

# Scenarios that need exclusive vendors run first so nothing else touches those vendors' POs
STRESS_ORDER = ["NO_PO_CLEAR_MATCH", "NO_PO_AMBIGUOUS"] + [s for s in STRESS_COUNTS if not s.startswith("NO_PO")]


def plan_golden(p: Planner) -> list[PlannedInvoice]:
    """The 12 fixed demo invoices (CLAUDE.md / PHASE_PROMPTS Phase 2)."""
    golden = [
        p.no_po_clear("05_C_no_po", "golden", "landscape", only_two_open_pos=True),
        p.clean("01_happy_clean", "golden", "classic", intra_state=True, allow_adjustments=False),
        p.within_tolerance("02_happy_tolerance", "golden", "modern", target_diff=Decimal("200")),
        p.overrun("03_A_split_overrun", "golden", "tally"),
        p.duplicate("04_B_duplicate", "golden", disguised=True, template="compact", golden_style=True),
        p.bank_change("06_D_bank_change", "golden", "small_vendor"),
        p.wrong_gst("07_E_wrong_gst", "golden", "classic", intra_state=False),
        p.heavy_scan("08_F_blurry_scan", "golden", "modern", obscure="invoice_number"),
        _golden_price_variance(p),
        p.arithmetic_error("10_H_bad_maths", "golden", "multipage", kind="line_amount", min_lines=4),
        p.not_an_invoice("11_I_quotation", "golden", "compact", doc=NOT_INVOICE_DOCS[0]),
        p.vendor_status("12_J_unapproved_vendor", "golden", "pending", "tally"),
    ]
    for item in golden:
        item.spec.knobs["template"] = item.spec.template
    return sorted(golden, key=lambda g: g.spec.invoice_id)


def _golden_price_variance(p: Planner) -> PlannedInvoice:
    """09: a services vendor bills one line exactly 3% above the PO price."""
    po = p.clean_po(categories=SERVICE_CATEGORIES)
    spec = p.spec_from_po("09_G_price_variance", po, p.pick_quantities(po, 0.5), p.invoice_date_for(po), "services")
    line = max(spec.lines, key=lambda l: l.correct_amount)
    old = line.unit_price
    line.unit_price = money(old * Decimal("1.03"))
    spec.compute_totals()
    return p.planned(spec, "golden", "PRICE_OVER_TOLERANCE", HOLD, ["PRICE_VARIANCE_OVER_TOLERANCE"],
                     true_po_number=po.po_number, notes=f"'{line.description}' billed at ₹{line.unit_price} vs PO ₹{old} (+3%).")


def plan_stress(p: Planner) -> list[PlannedInvoice]:
    """~270 randomised invoices across every scenario; ~30% of the ordinary ones become mild scans."""
    builders = {
        "CLEAN_EXACT": lambda i: p.clean(i, "stress"),
        "CLEAN_WITHIN_TOLERANCE": lambda i: p.within_tolerance(i, "stress"),
        "PO_OVERRUN": lambda i: p.overrun(i, "stress"),
        "DUPLICATE_EXACT_NUMBER": lambda i: p.duplicate(i, "stress", disguised=False),
        "DUPLICATE_DISGUISED_NUMBER": lambda i: p.duplicate(i, "stress", disguised=True),
        "POSSIBLE_DUPLICATE": lambda i: p.possible_duplicate(i, "stress"),
        "NO_PO_CLEAR_MATCH": lambda i: p.no_po_clear(i, "stress"),
        "NO_PO_AMBIGUOUS": lambda i: p.no_po_ambiguous(i, "stress"),
        "BANK_CHANGE": lambda i: p.bank_change(i, "stress"),
        "GST_WRONG_TYPE": lambda i: p.wrong_gst(i, "stress"),
        "HEAVY_SCAN_LOW_CONFIDENCE": lambda i: p.heavy_scan(i, "stress"),
        "OBSCURED_INVOICE_NUMBER": lambda i: p.heavy_scan(i, "stress", obscure="invoice_number",
                                                          scenario="OBSCURED_INVOICE_NUMBER", scan="mild"),
        "OBSCURED_GSTIN": lambda i: p.heavy_scan(i, "stress", obscure="vendor_gstin", scenario="OBSCURED_GSTIN", scan="mild"),
        "PRICE_OVER_TOLERANCE": lambda i: p.price_over(i, "stress"),
        "QTY_EXCEEDS_PO": lambda i: p.qty_exceeds(i, "stress"),
        "ITEM_NOT_ON_PO": lambda i: p.item_not_on_po(i, "stress"),
        "ARITHMETIC_ERROR": lambda i: p.arithmetic_error(i, "stress"),
        "NOT_AN_INVOICE": lambda i: p.not_an_invoice(i, "stress"),
        "VENDOR_NOT_APPROVED": lambda i: p.vendor_status(i, "stress", "pending"),
        "VENDOR_BLOCKED": lambda i: p.vendor_status(i, "stress", "blocked"),
        "VENDOR_UNKNOWN": lambda i: p.vendor_unknown(i, "stress"),
        "BUYER_MISMATCH": lambda i: p.buyer_mismatch(i, "stress"),
        "PO_CLOSED": lambda i: p.po_closed(i, "stress"),
        "GST_RATE_UNUSUAL": lambda i: p.gst_rate_unusual(i, "stress"),
        "MISSING_INVOICE_NUMBER": lambda i: p.missing_invoice_number(i, "stress"),
        "MULTI_ISSUE": lambda i: p.multi_issue(i, "stress"),
    }
    planned = []
    for scenario in STRESS_ORDER:
        for _ in range(STRESS_COUNTS[scenario]):
            planned.append(builders[scenario]("pending"))
    p.rng.shuffle(planned)
    for index, item in enumerate(planned, start=1):
        item.spec.invoice_id = f"S{index:04d}"
        if item.scan == "none" and p.rng.random() < 0.30:
            item.scan = "mild"
        if item.scan == "mild" and not item.obscured_fields and p.rng.random() < 0.35:
            item.file_format = p.rng.choice(["png", "jpg"])  # single-page image uploads (multi-page stays PDF)
    return planned
