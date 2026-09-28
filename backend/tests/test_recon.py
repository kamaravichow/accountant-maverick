import json

from app.recon.engines import find_missing_bills, parse_gstr2b_json, reconcile_26as, reconcile_bank, reconcile_gstr2b
from app.recon.normalize import clean_records, normalize_invoice_no, parse_amount, parse_date, rows_to_records
from app.validators.hsn import audit_register, validate_hsn
from app.validators.identifiers import validate_gstin, validate_identifier


def test_parse_amount_indian_formats():
    assert float(parse_amount("1,23,456.50 Dr")) == -123456.50
    assert float(parse_amount("₹ 5,000 Cr")) == 5000
    assert float(parse_amount("(500)")) == -500
    assert parse_amount("-") is None


def test_parse_date_dayfirst_and_serial():
    assert parse_date("05/04/2025").isoformat() == "2025-04-05"
    assert parse_date("05-Apr-25").isoformat() == "2025-04-05"
    assert parse_date(45752).isoformat() == "2025-04-05"


def test_invoice_normalisation():
    assert normalize_invoice_no("INV/2025-26/000123") == normalize_invoice_no("inv-123")


def test_header_detection_with_junk_rows():
    rows = [["HDFC BANK LTD"], ["Account No: 123"], [],
            ["Date", "Narration", "Chq./Ref.No.", "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"],
            ["01/04/25", "NEFT-ACME", "N123", "1,000.00", "", "9,000.00"],
            ["", "CONTINUED NARRATION", "", "", "", ""],
            ["Date", "Narration", "Chq./Ref.No.", "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"],
            ["02/04/25", "INTEREST", "", "", "50", "9,050.00"]]
    recs, stats = clean_records(rows_to_records(rows))
    assert len(recs) == 2
    assert recs[0]["amount"] == -1000 and "CONTINUED" in recs[0]["narration"]
    assert recs[1]["date"] == "2025-04-02"


def test_gstin_checksum():
    assert validate_gstin("27AAPFU0939F1ZV")["valid"]
    assert not validate_gstin("27AAPFU0939F1ZX")["valid"]
    assert validate_identifier("AAPFU0939F")["type"] == "PAN"


def test_hsn_rate_change_detection():
    r = validate_hsn("8415", "Split AC", 28, "2025-10-01")
    assert not r["valid"]
    assert validate_hsn("8415", "Split AC", 28, "2025-09-01")["valid"]


def test_hsn_register_inconsistency():
    res = audit_register([
        {"hsn": "8471", "description": "Laptop", "rate": 18, "invoice_date": "2025-10-01"},
        {"hsn": "8473", "description": "Laptop", "rate": 18, "invoice_date": "2025-10-02"},
    ])
    assert res["same_description_different_hsn"]


GSTR2B = {"data": {"docdata": {"b2b": [
    {"ctin": "27AAPFU0939F1ZV", "trdnm": "ACME", "inv": [
        {"inum": "INV/2025-26/001", "dt": "05-10-2025", "val": 1180, "rev": "N", "itcavl": "Y",
         "items": [{"rt": 18, "txval": 1000, "igst": 0, "cgst": 90, "sgst": 90, "cess": 0}]},
        {"inum": "INV-9", "dt": "07-10-2025", "val": 590, "rev": "N", "itcavl": "Y",
         "items": [{"rt": 18, "txval": 500, "igst": 0, "cgst": 45, "sgst": 45, "cess": 0}]}]}],
    "cdnr": []}}}


def test_gstr2b_recon():
    portal = parse_gstr2b_json(json.dumps(GSTR2B))
    books = [
        {"gstin": "27AAPFU0939F1ZV", "invoice_no": "INV-1", "date": "2025-10-05", "taxable_value": 1000, "cgst": 90, "sgst": 90},
        {"gstin": "27AAPFU0939F1ZV", "invoice_no": "X-77", "date": "2025-10-09", "taxable_value": 2000, "cgst": 180, "sgst": 180},
    ]
    r = reconcile_gstr2b(books, portal)
    assert r["summary"]["matched"] == 1
    assert r["summary"]["only_in_books"] == 1 and r["summary"]["only_in_2b"] == 1
    assert r["summary"]["itc_at_risk_only_in_books"] == 360


def test_bank_recon_brs():
    stmt = [{"date": "2025-04-03", "narration": "CHQ 000451 ACME", "debit": 5000},
            {"date": "2025-04-30", "narration": "BANK CHARGES", "debit": 118}]
    ledger = [{"date": "2025-04-01", "narration": "Paid ACME chq 000451", "credit": 5000},
              {"date": "2025-04-29", "narration": "Chq to Beta", "credit": 2000}]
    r = reconcile_bank(stmt, ledger, book_balance=10000, bank_balance=11882)
    assert r["summary"]["matched"] == 1
    assert r["brs"]["unpresented_payments"] == 2000
    assert r["brs"]["bank_debits_not_in_books"] == 118
    assert r["brs"]["unexplained_difference"] == 0


def test_26as_recon():
    r = reconcile_26as([{"tan": "MUMA12345B", "party": "A", "tds": 1000}],
                       [{"tan": "MUMA12345B", "party": "A", "tds": 1000}, {"tan": "DELB12345C", "party": "B", "tds": 50}])
    assert r["summary"]["with_issues"] == 1


def test_missing_bills():
    r = find_missing_bills([{"date": "2025-05-01", "narration": "NEFT/SHARMA TRADERS/123456", "debit": 25000},
                            {"date": "2025-05-02", "narration": "SALARY MAY", "debit": 90000}],
                           [])
    assert r["summary"]["missing_bills"] == 1
    assert "Sharma" in r["missing"][0]["likely_party"]


def test_invoice_normalisation_fy_variants():
    assert normalize_invoice_no("INV/25-26/001") == "INV1"
    assert normalize_invoice_no("INV/2025/26/001") == "INV1"
    assert normalize_invoice_no("GST-12-34") == "GST1234"  # not consecutive years -> kept
