"""Generate the buyer, vendors, purchase orders and invoice history (all fictional, fully reproducible).

PO status is never set directly: it is derived from how much of each PO line has been billed
(open = nothing billed, partially_billed = some, closed = everything). The `qty_billed` column on
PO lines is the PO ledger, and every history invoice records which PO lines it billed.

Phase 2 scenarios use `reserve_po`, `reserve_vendor`, `add_po` and `bill` to set up the exact
history they need before `write_master` writes the final CSVs (see datagen/generate_all.py).
"""

from __future__ import annotations

import csv
import json
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Callable

from faker import Faker

from datagen.catalog import CATALOG, CatalogItem
from datagen.gstin import STATES, make_bank_account, make_gstin, make_ifsc, make_pan

DEFAULT_SEED = 20261030
# Fixed "today" for the generated world, so output never depends on when it is run
REFERENCE_DATE = date(2026, 10, 30)
PO_PERIOD_START = date(2026, 2, 1)
PO_PERIOD_END = date(2026, 10, 24)

BUYER_STATE_CODE = "27"
VENDOR_COUNT = 40
MAHARASHTRA_VENDORS = 12
STATUS_COUNTS = {"approved": 34, "pending": 3, "blocked": 3}
PO_COUNT = 200
PO_NUMBER_START = 1001

PAISE = Decimal("0.01")
RUPEE = Decimal("1")

BANKS: list[tuple[str, str]] = [
    ("HDFC Bank", "HDFC"),
    ("ICICI Bank", "ICIC"),
    ("State Bank of India", "SBIN"),
    ("Axis Bank", "UTIB"),
    ("Kotak Mahindra Bank", "KKBK"),
    ("Bank of Baroda", "BARB"),
    ("Punjab National Bank", "PUNB"),
    ("IDFC FIRST Bank", "IDFB"),
    ("Yes Bank", "YESB"),
    ("Canara Bank", "CNRB"),
]

# state code -> [(city, 3-digit PIN prefix)]
CITIES: dict[str, list[tuple[str, str]]] = {
    "03": [("Ludhiana", "141"), ("Mohali", "160")],
    "06": [("Gurugram", "122"), ("Faridabad", "121")],
    "07": [("New Delhi", "110")],
    "08": [("Jaipur", "302"), ("Udaipur", "313")],
    "09": [("Noida", "201"), ("Lucknow", "226"), ("Kanpur", "208")],
    "19": [("Kolkata", "700"), ("Howrah", "711")],
    "23": [("Indore", "452"), ("Bhopal", "462")],
    "24": [("Ahmedabad", "380"), ("Surat", "395"), ("Vadodara", "390")],
    "27": [("Mumbai", "400"), ("Pune", "411"), ("Thane", "400"), ("Nagpur", "440"), ("Bhiwandi", "421")],
    "29": [("Bengaluru", "560"), ("Mysuru", "570")],
    "32": [("Kochi", "682"), ("Thiruvananthapuram", "695")],
    "33": [("Chennai", "600"), ("Coimbatore", "641")],
    "36": [("Hyderabad", "500"), ("Secunderabad", "500")],
}

COINED_WORDS = [
    "Apex", "Vardhan", "Nexa", "Trident", "Bluewave", "Kosmic", "Silverline", "Vriddhi", "Samarth",
    "Orbit", "Pinnacle", "Navkar", "Suvidha", "Prism", "Zenon", "Akshar", "Meridian", "Tejas",
    "Sapphire", "Unnati", "Kalpana", "Evergreen", "Shubham", "Vertex", "Nirmaan", "Indus", "Saffron",
]

CATEGORY_WORDS: dict[str, list[str]] = {
    "it_hardware": ["Computers", "Infotech Systems", "Digital Systems", "Computer World"],
    "it_services": ["IT Solutions", "Technologies", "Softech", "Infoservices"],
    "office_supplies": ["Stationers", "Office Mart", "Paper Products", "Office Solutions"],
    "packaging": ["Packaging", "Packwell Industries", "Cartons", "Pack Solutions"],
    "logistics": ["Logistics", "Roadways", "Cargo Movers", "Freight Carriers"],
    "facility_management": ["Facility Services", "Facility Management", "Property Services", "Hygiene Services"],
    "raw_materials": ["Industries", "Polymers", "Textiles", "Metals"],
    "marketing_printing": ["Printers", "Graphics", "Advertising", "Print Solutions"],
    "furniture": ["Furniture", "Interiors", "Furnishers", "Woodcraft"],
    "electrical_maintenance": ["Electricals", "Electric Works", "Power Systems", "Engineering Services"],
}

DELIVERY_LOCATIONS = [
    "Zenith Retail Central Warehouse, Bhiwandi",
    "Zenith Retail HQ, Lower Parel, Mumbai",
    "Zenith Store #12, Andheri West, Mumbai",
    "Zenith Store #07, FC Road, Pune",
    "Zenith Store #19, Thane West",
]

# Invoice-number styles: (prefix, sequence number, invoice date) -> printed invoice number
InvoiceStyle = Callable[[str, int, date], str]


def _fy_short(on: date) -> str:
    """Indian financial year, short form: 26-27 for Apr 2026 - Mar 2027."""
    start = on.year if on.month >= 4 else on.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def _fy_long(on: date) -> str:
    start = on.year if on.month >= 4 else on.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


INVOICE_STYLES: dict[str, InvoiceStyle] = {
    "prefix_fy_seq": lambda p, n, d: f"{p}/{_fy_short(d)}/{n:04d}",  # SIT/26-27/0881
    "inv_dash_seq": lambda p, n, d: f"INV-{n:05d}",  # INV-00457
    "year_prefix_seq": lambda p, n, d: f"{d.year}/{p}/{n}",  # 2026/KOS/57
    "prefix_seq": lambda p, n, d: f"{p}{n:04d}",  # BW1234
    "prefix_dash_seq": lambda p, n, d: f"{p}-{n:04d}",  # KOS-0457
    "fy_long_seq": lambda p, n, d: f"{_fy_long(d)}/{n}",  # 2026-27/112
    "plain_seq": lambda p, n, d: f"{n}",  # 1457
    "prefix_seq_yy": lambda p, n, d: f"{p}/{n:03d}/{d.year % 100:02d}",  # GT/045/26
}


def money(value: Decimal | float | int) -> Decimal:
    """Round to paise (half-up, as on Indian invoices)."""
    return Decimal(str(value)).quantize(PAISE, rounding=ROUND_HALF_UP)


@dataclass
class Buyer:
    legal_name: str
    name_variants: list[str]
    gstin: str
    pan: str
    state: str
    state_code: str
    address: str
    email: str
    phone: str

    def to_json(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Vendor:
    vendor_id: str
    legal_name: str
    trade_name: str
    gstin: str
    pan: str
    state: str
    state_code: str
    address: str
    email: str
    phone: str
    bank_name: str
    bank_account: str
    ifsc: str
    status: str
    category: str
    payment_terms_days: int
    # Generator-only fields (not written to vendors.csv)
    invoice_style: str = ""
    invoice_prefix: str = ""
    next_invoice_seq: int = 1

    CSV_FIELDS = (
        "vendor_id", "legal_name", "trade_name", "gstin", "pan", "state", "state_code", "address", "email",
        "phone", "bank_name", "bank_account", "ifsc", "status", "category", "payment_terms_days",
    )

    @property
    def is_intra_state(self) -> bool:
        """Same state as the buyer -> CGST + SGST; otherwise IGST."""
        return self.state_code == BUYER_STATE_CODE

    def to_row(self) -> dict:
        return {name: getattr(self, name) for name in self.CSV_FIELDS}


@dataclass
class POLine:
    po_number: str
    line_no: int
    description: str
    hsn_sac: str
    unit: str
    qty_ordered: int
    unit_price: Decimal
    gst_rate: float
    qty_billed: int = 0

    CSV_FIELDS = (
        "po_number", "line_no", "description", "hsn_sac", "unit", "qty_ordered", "unit_price", "gst_rate",
        "line_value", "qty_billed", "qty_remaining",
    )

    @property
    def line_value(self) -> Decimal:
        return money(self.qty_ordered * self.unit_price)

    @property
    def qty_remaining(self) -> int:
        return self.qty_ordered - self.qty_billed

    def to_row(self) -> dict:
        return {name: getattr(self, name) for name in self.CSV_FIELDS}


@dataclass
class PurchaseOrder:
    po_number: str
    vendor_id: str
    po_date: date
    delivery_location: str
    requested_by: str
    payment_terms_days: int
    lines: list[POLine] = field(default_factory=list)

    CSV_FIELDS = (
        "po_number", "vendor_id", "po_date", "status", "taxable_value", "gst_amount", "total_value",
        "billed_value", "remaining_value", "delivery_location", "requested_by", "payment_terms_days",
    )

    @property
    def status(self) -> str:
        """Derived from billing: open (nothing billed), partially_billed, or closed (fully billed)."""
        if all(line.qty_billed == 0 for line in self.lines):
            return "open"
        if all(line.qty_remaining == 0 for line in self.lines):
            return "closed"
        return "partially_billed"

    @property
    def taxable_value(self) -> Decimal:
        return sum((line.line_value for line in self.lines), Decimal("0.00"))

    @property
    def gst_amount(self) -> Decimal:
        return sum((money(line.line_value * Decimal(str(line.gst_rate)) / 100) for line in self.lines), Decimal("0.00"))

    @property
    def total_value(self) -> Decimal:
        return self.taxable_value + self.gst_amount

    @property
    def billed_value(self) -> Decimal:
        return sum((money(line.qty_billed * line.unit_price) for line in self.lines), Decimal("0.00"))

    @property
    def remaining_value(self) -> Decimal:
        return self.taxable_value - self.billed_value

    def line(self, line_no: int) -> POLine:
        return next(line for line in self.lines if line.line_no == line_no)

    def to_row(self) -> dict:
        return {name: getattr(self, name) for name in self.CSV_FIELDS}


@dataclass
class HistoryLine:
    po_line_no: int
    description: str
    hsn_sac: str
    quantity: int
    unit: str
    unit_price: Decimal
    gst_rate: float

    @property
    def amount(self) -> Decimal:
        return money(self.quantity * self.unit_price)

    def to_json(self) -> dict:
        return {
            "po_line_no": self.po_line_no,
            "description": self.description,
            "hsn_sac": self.hsn_sac,
            "quantity": self.quantity,
            "unit": self.unit,
            "unit_price": str(self.unit_price),
            "gst_rate": self.gst_rate,
            "amount": str(self.amount),
        }


@dataclass
class HistoryInvoice:
    history_id: str
    vendor_id: str
    invoice_number: str
    invoice_date: date
    po_number: str
    lines: list[HistoryLine]
    taxable_value: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    round_off: Decimal
    total_amount: Decimal
    status: str
    payment_date: date | None

    CSV_FIELDS = (
        "history_id", "vendor_id", "invoice_number", "invoice_date", "po_number", "taxable_value", "cgst", "sgst",
        "igst", "round_off", "total_amount", "status", "payment_date", "lines_json",
    )

    def to_row(self) -> dict:
        row = {name: getattr(self, name) for name in self.CSV_FIELDS if name != "lines_json"}
        row["payment_date"] = self.payment_date or ""
        row["lines_json"] = json.dumps([line.to_json() for line in self.lines])
        return row


def compute_invoice_totals(lines: list[HistoryLine], intra_state: bool) -> dict[str, Decimal]:
    """Taxable value, GST split by the state rule, and total rounded to the rupee with a round-off line."""
    taxable = sum((line.amount for line in lines), Decimal("0.00"))
    tax = sum((line.amount * Decimal(str(line.gst_rate)) / 100 for line in lines), Decimal("0"))
    if intra_state:
        cgst = sgst = money(tax / 2)
        igst = Decimal("0.00")
    else:
        cgst = sgst = Decimal("0.00")
        igst = money(tax)
    before_round = taxable + cgst + sgst + igst
    total = before_round.quantize(RUPEE, rounding=ROUND_HALF_UP)
    return {
        "taxable_value": taxable,
        "cgst": cgst,
        "sgst": sgst,
        "igst": igst,
        "round_off": money(total - before_round),
        "total_amount": money(total),
    }


class MasterData:
    """The generated world: buyer, vendors, POs and invoice history, plus helpers for scenarios."""

    def __init__(self, seed: int = DEFAULT_SEED) -> None:
        self.seed = seed
        self.rng = random.Random(seed)
        self.faker = Faker("en_IN")
        self.faker.seed_instance(seed)
        self.buyer: Buyer = _make_buyer(self.rng)
        self.vendors: list[Vendor] = []
        self.pos: list[PurchaseOrder] = []
        self.history: list[HistoryInvoice] = []
        self._reserved_pos: set[str] = set()
        self._reserved_vendors: set[str] = set()
        self._next_po_no = PO_NUMBER_START

    # ----- lookups -----

    def vendor(self, vendor_id: str) -> Vendor:
        return next(v for v in self.vendors if v.vendor_id == vendor_id)

    def po(self, po_number: str) -> PurchaseOrder:
        return next(p for p in self.pos if p.po_number == po_number)

    def vendor_of(self, po: PurchaseOrder) -> Vendor:
        return self.vendor(po.vendor_id)

    # ----- scenario helpers (used by Phase 2) -----

    def reserve_vendor(
        self,
        status: str = "approved",
        intra_state: bool | None = None,
        predicate: Callable[[Vendor], bool] | None = None,
    ) -> Vendor:
        """Pick an unreserved vendor matching the filters and mark it reserved for one scenario."""
        candidates = [
            v for v in self.vendors
            if v.vendor_id not in self._reserved_vendors
            and v.status == status
            and (intra_state is None or v.is_intra_state == intra_state)
            and (predicate is None or predicate(v))
        ]
        if not candidates:
            raise LookupError(f"No unreserved vendor with status={status}, intra_state={intra_state}")
        vendor = self.rng.choice(candidates)
        self._reserved_vendors.add(vendor.vendor_id)
        return vendor

    def reserve_po(
        self,
        statuses: tuple[str, ...] = ("open", "partially_billed"),
        vendor_status: str = "approved",
        intra_state: bool | None = None,
        predicate: Callable[[PurchaseOrder], bool] | None = None,
    ) -> PurchaseOrder:
        """Pick an unreserved PO matching the filters and mark it reserved for one scenario."""
        candidates = [
            p for p in self.pos
            if p.po_number not in self._reserved_pos
            and p.status in statuses
            and self.vendor_of(p).status == vendor_status
            and (intra_state is None or self.vendor_of(p).is_intra_state == intra_state)
            and (predicate is None or predicate(p))
        ]
        if not candidates:
            raise LookupError(f"No unreserved PO with statuses={statuses}, intra_state={intra_state}")
        po = self.rng.choice(candidates)
        self._reserved_pos.add(po.po_number)
        return po

    def add_po(self, vendor: Vendor, po_date: date, items: list[tuple[CatalogItem, int, Decimal]]) -> PurchaseOrder:
        """Create a new PO for a vendor from (catalog item, quantity, unit price) tuples."""
        po = PurchaseOrder(
            po_number=f"PO-{po_date.year}-{self._next_po_no:04d}",
            vendor_id=vendor.vendor_id,
            po_date=po_date,
            delivery_location=self.rng.choice(DELIVERY_LOCATIONS),
            requested_by=self.faker.name(),
            payment_terms_days=vendor.payment_terms_days,
        )
        self._next_po_no += 1
        for line_no, (item, qty, price) in enumerate(items, start=1):
            po.lines.append(
                POLine(po.po_number, line_no, item.description, item.hsn_sac, item.unit, qty, money(price), item.gst_rate)
            )
        self.pos.append(po)
        self._reserved_pos.add(po.po_number)  # scenario-created POs are never handed out again
        return po

    def next_invoice_number(self, vendor: Vendor, on: date) -> str:
        """Next printed invoice number in this vendor's own numbering style."""
        number = INVOICE_STYLES[vendor.invoice_style](vendor.invoice_prefix, vendor.next_invoice_seq, on)
        vendor.next_invoice_seq += 1
        return number

    def bill(
        self,
        po: PurchaseOrder,
        quantities: dict[int, int],
        invoice_date: date,
        invoice_number: str | None = None,
    ) -> HistoryInvoice:
        """Record a past invoice against a PO ({line_no: qty}) and update the PO ledger."""
        vendor = self.vendor_of(po)
        lines: list[HistoryLine] = []
        for line_no, qty in sorted(quantities.items()):
            po_line = po.line(line_no)
            if qty <= 0 or qty > po_line.qty_remaining:
                raise ValueError(f"{po.po_number} line {line_no}: cannot bill {qty} (remaining {po_line.qty_remaining})")
            po_line.qty_billed += qty
            lines.append(
                HistoryLine(line_no, po_line.description, po_line.hsn_sac, qty, po_line.unit, po_line.unit_price, po_line.gst_rate)
            )
        totals = compute_invoice_totals(lines, vendor.is_intra_state)
        status, payment_date = _payment_status(self.rng, invoice_date, vendor.payment_terms_days)
        invoice = HistoryInvoice(
            history_id=f"H{len(self.history) + 1:04d}",
            vendor_id=vendor.vendor_id,
            invoice_number=invoice_number or self.next_invoice_number(vendor, invoice_date),
            invoice_date=invoice_date,
            po_number=po.po_number,
            lines=lines,
            status=status,
            payment_date=payment_date,
            **totals,
        )
        self.history.append(invoice)
        return invoice


# ---------------------------------------------------------------- building


def build_master(seed: int = DEFAULT_SEED) -> MasterData:
    """Generate the complete seeded master data set."""
    md = MasterData(seed)
    md.vendors = _make_vendors(md)
    _make_pos(md)
    _make_history(md)
    return md


def _make_buyer(rng: random.Random) -> Buyer:
    pan = make_pan("C", rng, name_initial="Z")
    return Buyer(
        legal_name="Zenith Retail Pvt Ltd",
        name_variants=["Zenith Retail Pvt Ltd", "Zenith Retail Private Limited", "Zenith Retail Pvt. Ltd."],
        gstin=make_gstin(BUYER_STATE_CODE, pan, 1),
        pan=pan,
        state=STATES[BUYER_STATE_CODE],
        state_code=BUYER_STATE_CODE,
        address="7th Floor, Kamala Trade Centre, Senapati Bapat Marg, Lower Parel, Mumbai - 400013, Maharashtra",
        email="accounts.payable@zenithretail.example",
        phone="+91 22 4890 2200",
    )


def _vendor_states(rng: random.Random) -> list[str]:
    """12 Maharashtra vendors, every other state at least once, the rest spread randomly."""
    others = [code for code in STATES if code != BUYER_STATE_CODE]
    remaining = VENDOR_COUNT - MAHARASHTRA_VENDORS - len(others)
    states = [BUYER_STATE_CODE] * MAHARASHTRA_VENDORS + others + [rng.choice(others) for _ in range(remaining)]
    rng.shuffle(states)
    return states


def _vendor_names(md: MasterData, category: str, used: set[str]) -> tuple[str, str, str]:
    """Return (legal_name, trade_name, PAN entity type), unique across vendors."""
    rng, faker = md.rng, md.faker
    while True:
        base = rng.choice(COINED_WORDS) if rng.random() < 0.5 else faker.last_name()
        business = f"{base} {rng.choice(CATEGORY_WORDS[category])}"
        if business in used:
            continue
        used.add(business)
        entity = rng.choices(["C", "F", "P"], weights=[0.6, 0.2, 0.2])[0]
        if entity == "C":
            legal = f"{business} Private Limited"
            trade = rng.choice([business, f"{business} Pvt Ltd", f"{business} Pvt. Ltd."])
        elif entity == "F":
            legal = rng.choice([f"{business} LLP", f"M/s {business} & Co."])
            trade = business
        else:  # proprietorship: legal name is the proprietor, trade name is the business
            legal = f"{faker.first_name()} {base}" if base not in COINED_WORDS else faker.name()
            trade = rng.choice([f"{base} Enterprises", f"{base} Traders", business])
        return legal, trade, entity


def _invoice_prefix(trade_name: str) -> str:
    """Invoice-number prefix from the brand's initials, e.g. Kosmic Cartons Pvt Ltd -> KC."""
    words = [w for w in trade_name.replace(".", "").split() if w[0].isalpha() and w.lower() not in {"pvt", "ltd"}]
    if len(words) >= 2:
        return "".join(w[0] for w in words[:3]).upper()
    return words[0][:3].upper()


def _make_vendors(md: MasterData) -> list[Vendor]:
    rng, faker = md.rng, md.faker
    states = _vendor_states(rng)
    categories = [c for c in CATALOG for _ in range(VENDOR_COUNT // len(CATALOG))]
    rng.shuffle(categories)
    statuses = [s for s, n in STATUS_COUNTS.items() for _ in range(n)]
    rng.shuffle(statuses)
    used: set[str] = set()
    vendors = []
    for index, (state_code, category, status) in enumerate(zip(states, categories, statuses), start=1):
        legal, trade, entity = _vendor_names(md, category, used)
        # PAN 5th character: first letter of the entity name, or of the surname for a proprietor
        initial = legal.split()[-1][0] if entity == "P" else legal.removeprefix("M/s ")[0]
        pan = make_pan(entity, rng, name_initial=initial)
        city, pin_prefix = rng.choice(CITIES[state_code])
        bank_name, bank_code = rng.choice(BANKS)
        brand = " ".join(w for w in trade.split() if w.rstrip(".").lower() not in {"pvt", "ltd"})
        slug = "".join(ch for ch in brand.lower() if ch.isalnum())[:24]
        vendors.append(
            Vendor(
                vendor_id=f"V{index:03d}",
                legal_name=legal,
                trade_name=trade,
                gstin=make_gstin(state_code, pan, rng.choice([1, 1, 1, 2])),
                pan=pan,
                state=STATES[state_code],
                state_code=state_code,
                address=f"{faker.building_number()}, {faker.street_name()}, {city} - {pin_prefix}{rng.randint(1, 99):03d}, {STATES[state_code]}",
                email=f"{rng.choice(['accounts', 'billing', 'sales', 'info'])}@{slug}.in",
                phone=f"+91 {rng.randint(6, 9)}{rng.randint(0, 999999999):09d}",
                bank_name=bank_name,
                bank_account=make_bank_account(rng),
                ifsc=make_ifsc(bank_code, rng),
                status=status,
                category=category,
                payment_terms_days=rng.choice([15, 30, 30, 45, 60]),
                invoice_style=rng.choice(list(INVOICE_STYLES)),
                invoice_prefix=_invoice_prefix(trade),
                next_invoice_seq=rng.randint(40, 1800),
            )
        )
    return vendors


def _round_price(value: float) -> Decimal:
    """Make prices look like real list prices (e.g. 12,450 not 12,447.83)."""
    if value >= 1000:
        step = Decimal("50")
    elif value >= 100:
        step = Decimal("5")
    elif value >= 10:
        step = Decimal("0.5")
    else:
        step = Decimal("0.05")
    return money((Decimal(str(value)) / step).quantize(RUPEE, rounding=ROUND_HALF_UP) * step)


SERVICE_QTY = {
    "Year": (1, 1), "Month": (1, 6), "Hrs": (10, 160), "Job": (1, 1), "Day": (2, 20), "Trip": (1, 12),
    "Kg": (500, 5000), "Sq Ft": (1000, 8000), "Shipment": (100, 2000), "Seat": (10, 150), "User": (10, 150),
    "Guard-Month": (2, 12), "Visit": (1, 12), "Container": (1, 6), "Nos": (5, 40),
}


def random_quantity(rng: random.Random, item: CatalogItem) -> int:
    """A believable order quantity for an item, based on its unit and price."""
    if item.is_service:
        low, high = SERVICE_QTY.get(item.unit, (1, 10))
        qty = rng.randint(low, high)
    elif item.price_max > 20000:
        qty = rng.randint(1, 15)
    elif item.price_max > 2000:
        qty = rng.randint(2, 40)
    elif item.price_max > 200:
        qty = rng.randint(10, 200)
    else:
        qty = rng.randint(50, 2000)
    return qty if qty < 100 else round(qty, -1)


def random_price(rng: random.Random, item: CatalogItem) -> Decimal:
    return _round_price(rng.uniform(item.price_min, item.price_max))


def _make_pos(md: MasterData) -> None:
    """~200 POs over the last 9 months for approved and blocked vendors (pending vendors have none yet)."""
    rng = md.rng
    eligible = [v for v in md.vendors if v.status != "pending"]
    owners = eligible * 2 + [rng.choice(eligible) for _ in range(PO_COUNT - 2 * len(eligible))]
    span = (PO_PERIOD_END - PO_PERIOD_START).days
    dates = sorted(PO_PERIOD_START + timedelta(days=rng.randint(0, span)) for _ in owners)
    rng.shuffle(owners)
    for vendor, po_date in zip(owners, dates):
        items = rng.sample(CATALOG[vendor.category], k=rng.randint(1, min(8, len(CATALOG[vendor.category]))))
        md.add_po(vendor, po_date, [(item, random_quantity(rng, item), random_price(rng, item)) for item in items])
    md._reserved_pos.clear()  # base POs are free for scenarios to reserve


def _target_status(rng: random.Random, po_date: date) -> str:
    """Older POs are more likely to be fully billed."""
    age = (REFERENCE_DATE - po_date).days
    if age < 25:
        weights = (0.7, 0.3, 0.0)
    elif age < 60:
        weights = (0.30, 0.45, 0.25)
    elif age < 120:
        weights = (0.15, 0.40, 0.45)
    else:
        weights = (0.08, 0.32, 0.60)
    return rng.choices(["open", "partially_billed", "closed"], weights=weights)[0]


def _split(rng: random.Random, qty: int, parts: int) -> list[int]:
    """Split a quantity into `parts` non-negative integers that add up to it."""
    if qty == 0:
        return [0] * parts
    if qty < parts or rng.random() < 0.3:
        shares = [0] * parts
        shares[rng.randrange(parts)] = qty
        return shares
    cuts = sorted(rng.sample(range(1, qty), parts - 1)) if parts > 1 else []
    bounds = [0, *cuts, qty]
    return [bounds[i + 1] - bounds[i] for i in range(parts)]


def _billed_quantities(rng: random.Random, po: PurchaseOrder, status: str) -> dict[int, int]:
    """Total quantity to bill per line so the PO ends in the target status."""
    if status == "closed":
        return {line.line_no: line.qty_ordered for line in po.lines}
    billed = {}
    for line in po.lines:
        share = rng.choices([0.0, rng.uniform(0.2, 0.9), 1.0], weights=[0.25, 0.5, 0.25])[0]
        billed[line.line_no] = int(line.qty_ordered * share)
    if all(billed[line.line_no] == line.qty_ordered for line in po.lines):
        first = po.lines[0]
        billed[first.line_no] = first.qty_ordered - max(1, first.qty_ordered // 3)
    if sum(billed.values()) == 0:
        biggest = max(po.lines, key=lambda line: line.qty_ordered)
        billed[biggest.line_no] = max(1, biggest.qty_ordered // 2) if biggest.qty_ordered > 1 else 1
    if all(billed[line.line_no] == line.qty_ordered for line in po.lines):
        return {}  # single line of qty 1 cannot be part-billed; leave the PO open
    return billed


def _make_history(md: MasterData) -> None:
    """Bill each PO in 1-4 invoices dated after the PO, then record them in date order."""
    rng = md.rng
    events: list[tuple[date, str, dict[int, int]]] = []
    for po in md.pos:
        status = _target_status(rng, po.po_date)
        if status == "open":
            continue
        window_start = po.po_date + timedelta(days=4)
        window_end = min(po.po_date + timedelta(days=160), REFERENCE_DATE - timedelta(days=3))
        window_days = (window_end - window_start).days + 1
        if window_days <= 0:
            continue
        counts = (1, 2, 3, 4) if status == "closed" else (1, 2, 3)
        weights = (0.10, 0.25, 0.35, 0.30) if status == "closed" else (0.20, 0.40, 0.40)
        parts = min(rng.choices(counts, weights=weights)[0], window_days)
        totals = _billed_quantities(rng, po, status)
        if not totals:
            continue
        splits = {line_no: _split(rng, qty, parts) for line_no, qty in totals.items()}
        offsets = sorted(rng.sample(range(window_days), parts))
        for index, offset in enumerate(offsets):
            quantities = {line_no: shares[index] for line_no, shares in splits.items() if shares[index] > 0}
            if quantities:
                events.append((window_start + timedelta(days=offset), po.po_number, quantities))
    for invoice_date, po_number, quantities in sorted(events, key=lambda e: (e[0], e[1])):
        md.bill(md.po(po_number), quantities, invoice_date)


def _payment_status(rng: random.Random, invoice_date: date, terms_days: int) -> tuple[str, date | None]:
    """Invoices past their due date are paid; newer ones are approved and awaiting payment."""
    due = invoice_date + timedelta(days=terms_days)
    if due <= REFERENCE_DATE - timedelta(days=2):
        paid_on = min(due + timedelta(days=rng.randint(-5, 3)), REFERENCE_DATE - timedelta(days=1))
        return "paid", max(paid_on, invoice_date + timedelta(days=1))
    return "approved", None


# ---------------------------------------------------------------- writing


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_master(md: MasterData, out_dir: Path) -> None:
    """Write buyer.json and the four master CSVs."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "buyer.json").write_text(json.dumps(md.buyer.to_json(), indent=2) + "\n", encoding="utf-8")
    _write_csv(out_dir / "vendors.csv", Vendor.CSV_FIELDS, [v.to_row() for v in md.vendors])
    pos = sorted(md.pos, key=lambda p: p.po_number)
    _write_csv(out_dir / "po_headers.csv", PurchaseOrder.CSV_FIELDS, [p.to_row() for p in pos])
    _write_csv(out_dir / "po_lines.csv", POLine.CSV_FIELDS, [line.to_row() for p in pos for line in p.lines])
    _write_csv(out_dir / "invoice_history.csv", HistoryInvoice.CSV_FIELDS, [h.to_row() for h in md.history])
