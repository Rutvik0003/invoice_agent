"""The content of one generated invoice, independent of its visual layout.

Scenarios build an InvoiceSpec (and mutate it); templates only draw it; the label's ground_truth is
derived from the same spec, so the label always describes exactly what is printed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from datagen.formats import amount_in_words, format_amount, format_date, spaced_gstin

ZERO = Decimal("0.00")


def money(value: Decimal | float | int) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class Party:
    name: str
    address: str
    gstin: str | None
    state: str
    state_code: str
    phone: str = ""
    email: str = ""


@dataclass
class SpecLine:
    description: str
    hsn_sac: str
    quantity: int
    unit: str
    unit_price: Decimal
    gst_rate: float
    po_line_no: int | None = None  # which PO line this bills (truth, not printed)
    amount_override: Decimal | None = None  # a deliberately wrong printed amount
    cgst: Decimal = ZERO
    sgst: Decimal = ZERO
    igst: Decimal = ZERO

    @property
    def correct_amount(self) -> Decimal:
        return money(self.quantity * self.unit_price)

    @property
    def amount(self) -> Decimal:
        """The amount printed on the line."""
        return self.amount_override if self.amount_override is not None else self.correct_amount


@dataclass
class InvoiceSpec:
    invoice_id: str
    template: str
    document_type: str  # tax_invoice | quotation | proforma | credit_note | delivery_challan | purchase_order
    title: str
    vendor: Party
    buyer: Party
    invoice_number: str | None
    invoice_date: date
    po_reference: str | None
    lines: list[SpecLine]
    tax_split: str  # "cgst_sgst" or "igst" (what is printed; wrong on purpose in GST-type scenarios)
    bank_name: str | None
    bank_account: str | None
    bank_ifsc: str | None
    payment_terms_days: int
    # Printed-form knobs
    vendor_name_printed: str = ""
    gstin_spaced: bool = False
    date_style: str = "dd/mm/yyyy"
    amount_style: str = "rupee_symbol"
    invoice_no_label: str = "Invoice No."
    date_label: str = "Date"
    po_label: str = "PO No."
    po_in_notes: bool = False
    tax_per_line: bool = False
    show_round_off: bool = True
    show_amount_in_words: bool = True
    discount: Decimal = ZERO
    other_charges: Decimal = ZERO
    other_charges_label: str = "Freight Charges"
    # Totals (filled by compute_totals; mutations may override afterwards)
    subtotal: Decimal = ZERO
    cgst: Decimal = ZERO
    sgst: Decimal = ZERO
    igst: Decimal = ZERO
    round_off: Decimal | None = None
    total_amount: Decimal = ZERO
    words_override: str | None = None
    notes: list[str] = field(default_factory=list)
    knobs: dict = field(default_factory=dict)

    # ----- totals -----

    def compute_totals(self) -> None:
        """Recompute every tax and total from the lines, exactly as an honest vendor would."""
        for line in self.lines:
            line.cgst = line.sgst = line.igst = ZERO
        self.subtotal = sum((line.amount for line in self.lines), ZERO)
        taxable = self.subtotal - self.discount + self.other_charges
        if self.discount or self.other_charges:
            # One GST rate on the whole taxable value (only used when all lines share a rate)
            rate = Decimal(str(self.lines[0].gst_rate))
            tax = money(taxable * rate / 100)
            half = money(tax / 2)
            self.cgst, self.sgst, self.igst = (half, half, ZERO) if self.tax_split == "cgst_sgst" else (ZERO, ZERO, tax)
        else:
            for line in self.lines:
                rate = Decimal(str(line.gst_rate))
                if self.tax_split == "cgst_sgst":
                    line.cgst = line.sgst = money(line.amount * rate / 200)
                else:
                    line.igst = money(line.amount * rate / 100)
            self.cgst = sum((line.cgst for line in self.lines), ZERO)
            self.sgst = sum((line.sgst for line in self.lines), ZERO)
            self.igst = sum((line.igst for line in self.lines), ZERO)
        before_round = taxable + self.cgst + self.sgst + self.igst
        if self.show_round_off:
            total = before_round.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            self.round_off = money(total - before_round)
            self.total_amount = money(total)
        else:
            self.round_off = None
            self.total_amount = money(before_round)

    @property
    def taxable_value(self) -> Decimal:
        return self.subtotal - self.discount + self.other_charges

    @property
    def single_rate(self) -> bool:
        return len({line.gst_rate for line in self.lines}) == 1

    # ----- printed strings (templates and labels both use these) -----

    def amount_text(self, value: Decimal) -> str:
        return format_amount(value, self.amount_style)

    @property
    def date_text(self) -> str:
        return format_date(self.invoice_date, self.date_style)

    def gstin_text(self, gstin: str | None) -> str | None:
        if gstin is None:
            return None
        return spaced_gstin(gstin) if self.gstin_spaced else gstin

    @property
    def words_text(self) -> str | None:
        if not self.show_amount_in_words:
            return None
        return self.words_override or amount_in_words(self.total_amount)

    @property
    def due_date(self) -> date:
        from datetime import timedelta

        return self.invoice_date + timedelta(days=self.payment_terms_days)

    def printed_values(self) -> dict[str, str | None]:
        """Exact text of every key value as it is printed (None = not printed)."""
        is_inter = self.tax_split == "igst"
        return {
            "vendor_name": self.vendor_name_printed,
            "vendor_gstin": self.gstin_text(self.vendor.gstin),
            "buyer_gstin": self.gstin_text(self.buyer.gstin),
            "invoice_number": self.invoice_number,
            "invoice_date": self.date_text,
            "po_reference": self.po_reference,
            "subtotal": self.amount_text(self.subtotal),
            "cgst": None if is_inter else self.amount_text(self.cgst),
            "sgst": None if is_inter else self.amount_text(self.sgst),
            "igst": self.amount_text(self.igst) if is_inter else None,
            "total_amount": self.amount_text(self.total_amount),
            "bank_account": self.bank_account,
        }
