"""Item catalogs per vendor category with HSN/SAC codes, units, INR price ranges and GST rates.

Rates follow the GST 2.0 slabs (0 / 5 / 18 / 40 %, effective 22 Sep 2025). They are plausible
for synthetic test data, not tax advice.
"""

from dataclasses import dataclass
from datetime import date

GST_2_0_EFFECTIVE = date(2025, 9, 22)
GST_RATES_FROM_2_0 = frozenset({0.0, 0.25, 3.0, 5.0, 18.0, 40.0})
GST_RATES_BEFORE_2_0 = frozenset({0.0, 0.25, 3.0, 5.0, 12.0, 18.0, 28.0})


def valid_gst_rates(on: date) -> frozenset[float]:
    """GST rates that were legal on a given date (GST 2.0 removed 12% and 28%)."""
    return GST_RATES_FROM_2_0 if on >= GST_2_0_EFFECTIVE else GST_RATES_BEFORE_2_0


@dataclass(frozen=True)
class CatalogItem:
    description: str
    hsn_sac: str
    unit: str
    price_min: float
    price_max: float
    gst_rate: float
    is_service: bool = False


def _goods(description: str, hsn: str, unit: str, low: float, high: float, rate: float) -> CatalogItem:
    return CatalogItem(description, hsn, unit, low, high, float(rate))


def _service(description: str, sac: str, unit: str, low: float, high: float, rate: float = 18.0) -> CatalogItem:
    return CatalogItem(description, sac, unit, low, high, float(rate), is_service=True)


CATALOG: dict[str, list[CatalogItem]] = {
    "it_hardware": [
        _goods("Laptop - Intel Core i5, 16GB RAM, 512GB SSD", "8471", "Nos", 52000, 68000, 18),
        _goods("Laptop - Intel Core i7, 16GB RAM, 1TB SSD", "8471", "Nos", 78000, 98000, 18),
        _goods("Desktop PC - Core i5, 8GB RAM, 512GB SSD", "8471", "Nos", 38000, 48000, 18),
        _goods('LED Monitor 24" Full HD', "8528", "Nos", 8500, 12500, 18),
        _goods('LED Monitor 27" QHD', "8528", "Nos", 18000, 26000, 18),
        _goods("Wireless Keyboard and Mouse Combo", "8471", "Nos", 1200, 2400, 18),
        _goods("Laser Printer - Mono, Duplex", "8443", "Nos", 14000, 22000, 18),
        _goods("Toner Cartridge - Black", "8443", "Nos", 2800, 5200, 18),
        _goods("Barcode Scanner - Handheld", "8471", "Nos", 3200, 6500, 18),
        _goods("Thermal Receipt Printer 80mm", "8443", "Nos", 6500, 11000, 18),
        _goods("POS Terminal - All-in-One Touch", "8470", "Nos", 42000, 58000, 18),
        _goods("Wi-Fi Access Point - Dual Band", "8517", "Nos", 7500, 14000, 18),
        _goods("Network Switch - 24 Port Gigabit", "8517", "Nos", 16000, 28000, 18),
        _goods("Online UPS 3 kVA", "8504", "Nos", 32000, 46000, 18),
        _goods("External SSD 1TB", "8523", "Nos", 6500, 9500, 18),
        _goods("Cat6 Patch Cable 3m", "8544", "Nos", 180, 350, 18),
    ],
    "it_services": [
        _service("Annual Software Maintenance Support", "998313", "Year", 90000, 360000),
        _service("Cloud Hosting Charges - Monthly", "998315", "Month", 18000, 85000),
        _service("Custom Software Development", "998314", "Hrs", 1200, 2800),
        _service("IT Infrastructure Management Services", "998316", "Month", 45000, 150000),
        _service("Network Setup and Configuration", "998316", "Job", 15000, 60000),
        _service("Cybersecurity Audit", "998313", "Job", 75000, 240000),
        _service("Help Desk Support - Per Seat", "998316", "Seat", 600, 1500),
        _service("Software Licence Subscription - ERP Users", "997331", "User", 1500, 4500),
        _service("Data Backup and Recovery Service", "998315", "Month", 12000, 40000),
        _service("IT Consulting - Senior Consultant", "998313", "Day", 12000, 28000),
        _service("Website Maintenance Retainer", "998314", "Month", 15000, 45000),
        _service("POS Software Customisation", "998314", "Hrs", 1500, 3200),
    ],
    "office_supplies": [
        _goods("A4 Copier Paper 75 GSM (500 sheets)", "4802", "Ream", 260, 340, 18),
        _goods("Ball Pen - Blue (Box of 50)", "9608", "Box", 220, 420, 18),
        _goods("Gel Pen - Black (Box of 20)", "9608", "Box", 240, 480, 18),
        _goods("Spiral Notebook A5 - 200 pages", "4820", "Nos", 55, 95, 5),
        _goods("Box File - Lever Arch", "4820", "Nos", 110, 190, 18),
        _goods("Stapler - Heavy Duty", "8472", "Nos", 280, 650, 18),
        _goods("Stapler Pins No. 10 (Pack of 20)", "8305", "Pack", 70, 140, 18),
        _goods("Whiteboard Marker - Assorted (Pack of 10)", "9608", "Pack", 180, 320, 18),
        _goods("Sticky Notes 3x3 (Pack of 12)", "4820", "Pack", 160, 290, 18),
        _goods("Printer Labels A4 (100 sheets)", "4821", "Pack", 420, 780, 18),
        _goods("Envelope - Brown A4 (Pack of 100)", "4817", "Pack", 280, 480, 18),
        _goods("Correction Pen", "3824", "Nos", 30, 60, 18),
        _goods("Desk Organiser - Mesh", "8304", "Nos", 320, 650, 18),
        _goods("Calculator - 12 Digit", "8470", "Nos", 280, 650, 18),
    ],
    "packaging": [
        _goods("Corrugated Box 5-Ply 18x12x12 in", "4819", "Nos", 38, 62, 5),
        _goods("Corrugated Box 3-Ply 12x10x8 in", "4819", "Nos", 16, 28, 5),
        _goods("BOPP Packing Tape 48mm x 65m", "3919", "Roll", 32, 55, 18),
        _goods("Stretch Wrap Film 23 Micron", "3920", "Roll", 380, 620, 18),
        _goods("Bubble Wrap Roll 1m x 100m", "3921", "Roll", 1100, 1800, 18),
        _goods("Paper Carry Bag - Medium, Printed", "4819", "Nos", 9, 18, 5),
        _goods("Poly Mailer Bag 12x16 in", "3923", "Nos", 3.5, 7.5, 18),
        _goods("Wooden Pallet 1200x1000 mm", "4415", "Nos", 750, 1250, 18),
        _goods("PP Strapping Roll 12mm", "3920", "Roll", 650, 1050, 18),
        _goods("Shipping Label Roll 4x6 in", "4821", "Roll", 220, 380, 18),
        _goods("Void Fill Paper Roll", "4808", "Roll", 900, 1500, 5),
        _goods("Tissue Wrapping Paper (Ream)", "4803", "Ream", 450, 750, 5),
    ],
    "logistics": [
        _service("Road Freight - Full Truck Load (Mumbai-Pune)", "996511", "Trip", 14000, 22000, 5),
        _service("Road Freight - Full Truck Load (Interstate)", "996511", "Trip", 38000, 85000, 5),
        _service("Part Truck Load Freight", "996511", "Kg", 6, 14, 5),
        _service("Warehousing Charges", "996729", "Sq Ft", 28, 55),
        _service("Loading and Unloading Charges", "996719", "Trip", 1500, 4500),
        _service("Last Mile Delivery", "996812", "Shipment", 45, 120),
        _service("Courier Charges - Express Documents", "996812", "Shipment", 90, 250),
        _service("Reverse Logistics Pickup", "996812", "Shipment", 70, 160),
        _service("Container Handling Charges", "996711", "Container", 6500, 14000),
        _service("Cold Chain Transport", "996511", "Trip", 18000, 42000),
        _service("Inventory Management Fee", "996729", "Month", 25000, 70000),
    ],
    "facility_management": [
        _service("Housekeeping Services - Monthly", "998533", "Month", 45000, 160000),
        _service("Security Guard Services (12 hr shift)", "998525", "Guard-Month", 19000, 28000),
        _service("Pest Control Treatment", "998531", "Visit", 2500, 8500),
        _service("HVAC Annual Maintenance Contract", "998719", "Year", 85000, 240000),
        _service("Deep Cleaning - Store Premises", "998533", "Job", 12000, 38000),
        _service("Garden Maintenance", "998534", "Month", 8000, 22000),
        _service("Lift Maintenance AMC", "998719", "Year", 45000, 110000),
        _service("Water Tank Cleaning", "998533", "Job", 3500, 9000),
        _service("Facility Manager Deployment", "998519", "Month", 55000, 90000),
        _service("Fire Extinguisher Refilling", "998719", "Nos", 650, 1500),
        _service("Waste Disposal Services", "999423", "Month", 9000, 26000),
    ],
    "raw_materials": [
        _goods("Cotton Fabric - Plain Weave 60 in", "5208", "Mtr", 95, 180, 5),
        _goods("Polyester Yarn 150 Denier", "5402", "Kg", 135, 210, 5),
        _goods("Denim Fabric 12 oz", "5209", "Mtr", 210, 340, 5),
        _goods("HDPE Granules", "3901", "Kg", 98, 135, 18),
        _goods("PET Preforms 28mm", "3923", "Nos", 2.2, 4.2, 18),
        _goods("Mild Steel Sheet 1.2mm", "7209", "Kg", 62, 85, 18),
        _goods("Aluminium Sheet 2mm", "7606", "Kg", 240, 320, 18),
        _goods("Acrylic Sheet 3mm Clear", "3920", "Sq Ft", 85, 150, 18),
        _goods("Synthetic Enamel Paint", "3208", "Ltr", 260, 420, 18),
        _goods("Industrial Adhesive", "3506", "Kg", 280, 520, 18),
        _goods("MDF Board 18mm", "4411", "Sheet", 1650, 2600, 18),
        _goods("Buttons - Polyester (Gross)", "9606", "Gross", 140, 320, 5),
        _goods("Zipper 7 inch Nylon", "9607", "Nos", 4.5, 9.5, 18),
    ],
    "marketing_printing": [
        _goods("Printed Brochure A4 Tri-fold", "4911", "Nos", 6, 18, 18),
        _goods("Flex Banner Printing", "3921", "Sq Ft", 14, 32, 18),
        _goods("Roll-up Standee with Print", "4911", "Nos", 1800, 3400, 18),
        _goods("Visiting Cards (Box of 100)", "4911", "Box", 220, 480, 18),
        _goods("Shelf Talkers - Printed", "4911", "Nos", 4, 12, 18),
        _goods("Window Vinyl Graphics", "3919", "Sq Ft", 85, 180, 18),
        _goods("In-store Promotional Posters A2", "4911", "Nos", 35, 85, 18),
        _goods("Gift Vouchers - Printed, Numbered", "4911", "Nos", 8, 22, 18),
        _service("Social Media Campaign Management", "998361", "Month", 45000, 180000),
        _service("Graphic Design Services", "998391", "Hrs", 900, 2400),
        _service("Outdoor Hoarding Display", "998366", "Month", 60000, 240000),
        _service("Photography - Product Catalogue", "998386", "Day", 18000, 45000),
    ],
    "furniture": [
        _goods("Ergonomic Office Chair - Mesh Back", "9401", "Nos", 7500, 16000, 18),
        _goods("Visitor Chair - Cantilever", "9401", "Nos", 2800, 5200, 18),
        _goods("Office Desk 1200x600 mm", "9403", "Nos", 8500, 15000, 18),
        _goods("Workstation 4-Seater Cluster", "9403", "Set", 48000, 85000, 18),
        _goods("Steel Filing Cabinet - 4 Drawer", "9403", "Nos", 11000, 18500, 18),
        _goods("Conference Table 8-Seater", "9403", "Nos", 42000, 78000, 18),
        _goods("Retail Display Rack - Gondola", "9403", "Nos", 9500, 18000, 18),
        _goods("Checkout Counter - Laminated", "9403", "Nos", 28000, 52000, 18),
        _goods("Storage Locker - 12 Door", "9403", "Nos", 16000, 26000, 18),
        _goods("Bamboo Display Stand", "9403", "Nos", 2400, 4800, 5),
        _goods("Garment Display Mannequin", "9618", "Nos", 4200, 9500, 18),
        _goods("Cafeteria Table with 4 Chairs", "9403", "Set", 14000, 26000, 18),
    ],
    "electrical_maintenance": [
        _goods("LED Tube Light 20W", "9405", "Nos", 180, 340, 18),
        _goods("LED Panel Light 2x2 ft 36W", "9405", "Nos", 950, 1800, 18),
        _goods("Copper Wire 2.5 sq mm (90m coil)", "8544", "Coil", 2600, 3800, 18),
        _goods("MCB Single Pole 32A", "8536", "Nos", 180, 380, 18),
        _goods("Modular Switch 16A", "8536", "Nos", 85, 190, 18),
        _goods("Ceiling Fan 1200mm", "8414", "Nos", 2200, 4200, 18),
        _goods("Exhaust Fan 300mm", "8414", "Nos", 1600, 3200, 18),
        _goods("Split Air Conditioner 1.5 Ton Inverter", "8415", "Nos", 36000, 52000, 18),
        _goods("Distribution Board 8-Way", "8537", "Nos", 1800, 3600, 18),
        _goods("Emergency Light LED", "9405", "Nos", 750, 1600, 18),
        _service("Electrical Maintenance Visit", "998719", "Visit", 1500, 4500),
        _service("AC Servicing and Gas Refill", "998719", "Nos", 1800, 3800),
        _service("DG Set Maintenance AMC", "998719", "Year", 38000, 95000),
    ],
}

CATEGORY_LABELS: dict[str, str] = {
    "it_hardware": "IT Hardware",
    "it_services": "IT Services",
    "office_supplies": "Office Supplies",
    "packaging": "Packaging",
    "logistics": "Logistics & Freight",
    "facility_management": "Facility Management",
    "raw_materials": "Raw Materials",
    "marketing_printing": "Marketing & Printing",
    "furniture": "Furniture",
    "electrical_maintenance": "Electrical & Maintenance",
}
