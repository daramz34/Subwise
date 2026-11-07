"""Fast tests for the pure logic: no database, no server, no AI."""
from datetime import date
from decimal import Decimal

import pytest

from app.services.csv_parser import (
    CsvError, Transaction, decode_bytes, detect_delimiter, infer_dayfirst, parse_amount, parse_csv, parse_date,
)
from app.services.dates import add_months, next_renewal_from
from app.services.file_validation import FileRejected, validate_upload
from app.services.pattern_detector import detect_recurring, merchant_key
from app.services.redaction import redact_pii

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
PDF = b"%PDF-1.4\n%test\n"


# ---------------------------------------------------------------- file validation
def test_valid_files_are_classified_by_content():
    assert validate_upload("a.csv", b"Date,Description,Amount\n", 1000).file_type == "csv"
    assert validate_upload("a.pdf", PDF, 1000).file_type == "pdf"
    png = validate_upload("A.PNG", PNG, 1000)
    assert (png.file_type, png.extension, png.media_type) == ("image", "png", "image/png")
    assert validate_upload("b.jpeg", JPG, 1000).extension == "jpg"


@pytest.mark.parametrize("name,content", [
    ("virus.exe", b"MZ\x90\x00"),
    ("noextension", b"hello"),
    ("a.csv", PNG),                      # image pretending to be CSV
    ("a.csv", b"abc\x00\x01\x02def"),    # binary pretending to be CSV
    ("a.pdf", b"just some text"),        # text pretending to be PDF
    ("a.png", PDF),                      # PDF pretending to be PNG
    ("a.jpg", PNG),                      # wrong image type
])
def test_mismatched_or_unsupported_files_are_rejected(name, content):
    with pytest.raises(FileRejected) as exc:
        validate_upload(name, content, 1000)
    assert exc.value.status_code == 415


def test_empty_and_oversized_files():
    with pytest.raises(FileRejected) as exc:
        validate_upload("a.csv", b"", 1000)
    assert exc.value.status_code == 400
    with pytest.raises(FileRejected) as exc:
        validate_upload("a.csv", b"x" * 1001, 1000)
    assert exc.value.status_code == 413


def test_utf16_csv_is_accepted():
    assert validate_upload("a.csv", "Date,Amount\n".encode("utf-16"), 1000).file_type == "csv"


# ---------------------------------------------------------------- amounts and dates
@pytest.mark.parametrize("text,expected", [
    ("15.99", Decimal("15.99")), ("-15.99", Decimal("-15.99")), ("(15.99)", Decimal("-15.99")),
    ("15.99-", Decimal("-15.99")), ("1,234.56", Decimal("1234.56")), ("1.234,56", Decimal("1234.56")),
    ("15,99", Decimal("15.99")), ("1,234", Decimal("1234")), ("1.234.567", Decimal("1234567")),
    ("5,000.00 DR", Decimal("-5000.00")), ("\u221215.99", Decimal("-15.99")),
])
def test_parse_amount_formats(text, expected):
    assert parse_amount(text)[0] == expected


def test_parse_amount_currency_hints():
    assert parse_amount("₦5,000.00") == (Decimal("5000.00"), "NGN")
    assert parse_amount("$9.99") == (Decimal("9.99"), "USD")
    assert parse_amount("GBP 20.00") == (Decimal("20.00"), "GBP")


@pytest.mark.parametrize("text", ["", "abc", "--", "N/A", "1.2.x"])
def test_parse_amount_rejects_junk(text):
    assert parse_amount(text)[0] is None


def test_parse_date_formats():
    assert parse_date("2026-01-15") == date(2026, 1, 15)
    assert parse_date("2026-01-15 10:30:00") == date(2026, 1, 15)
    assert parse_date("15-Jan-2026") == date(2026, 1, 15)
    assert parse_date("Jan 15, 2026") == date(2026, 1, 15)
    assert parse_date("15/01/2026", dayfirst=True) == date(2026, 1, 15)
    assert parse_date("01/02/2026", dayfirst=True) == date(2026, 2, 1)
    assert parse_date("01/02/2026", dayfirst=False) == date(2026, 1, 2)
    assert parse_date("31/02/2026") is None
    assert parse_date("not a date") is None


def test_dayfirst_is_inferred_from_the_whole_file():
    assert infer_dayfirst(["01/02/2026", "25/03/2026"]) is True    # 25 can only be a day
    assert infer_dayfirst(["01/02/2026", "03/25/2026"]) is False   # 25 can only be a day (second)
    assert infer_dayfirst(["01/02/2026"]) is True                  # ambiguous: default day-first


# ---------------------------------------------------------------- decoding and delimiters
def test_decode_handles_bom_and_legacy_encodings():
    assert decode_bytes("\ufeffDate".encode("utf-8")) == "Date"
    assert decode_bytes("Café".encode("cp1252")) == "Café"
    assert decode_bytes("Date,Amount".encode("utf-16")) == "Date,Amount"


def test_delimiter_detection():
    assert detect_delimiter("Date,Description,Amount\n1,2,3") == ","
    assert detect_delimiter("Date;Description;Amount\n1;2;3") == ";"
    assert detect_delimiter("Date\tDescription\tAmount") == "\t"
    assert detect_delimiter("Date|Description|Amount") == "|"


# ---------------------------------------------------------------- csv parsing
def test_parse_csv_with_preamble_and_semicolons():
    raw = ("Account Statement;;\nGenerated 2026-06-01;;\nDate;Narration;Debit\n"
           "05/01/2026;NETFLIX.COM;15,99\n12/01/2026;SPOTIFY;9,99\n").encode()
    result = parse_csv(raw)
    assert [t.description for t in result.transactions] == ["NETFLIX.COM", "SPOTIFY"]
    assert result.transactions[0].amount == Decimal("15.99")
    assert result.transactions[0].date == date(2026, 1, 5)


def test_parse_csv_skips_bad_rows_but_keeps_good_ones():
    raw = (b"Date,Description,Amount\n2026-01-05,Netflix,-15.99\nnot-a-date,Oops,-1\n"
           b"2026-01-06,,-5\n2026-01-07,Free thing,0\n2026-01-08,Short\n2026-01-09,Spotify,-9.99\n")
    result = parse_csv(raw)
    assert [t.description for t in result.transactions] == ["Netflix", "Spotify"]
    assert result.skipped_rows == 4


def test_parse_csv_errors_are_readable():
    with pytest.raises(CsvError, match="no transactions"):
        parse_csv(b"Date,Description,Amount\n")
    with pytest.raises(CsvError, match="recognise the columns"):
        parse_csv(b"a,b,c\n1,2,3\n")
    with pytest.raises(CsvError, match="None of the rows"):
        parse_csv(b"Date,Description,Amount\nx,y,z\nq,r,s\n")
    with pytest.raises(CsvError, match="more than 2 rows"):
        parse_csv(b"Date,Description,Amount\n2026-01-01,a,-1\n2026-01-02,b,-1\n2026-01-03,c,-1\n", max_rows=2)


def test_parse_csv_with_saved_mapping():
    raw = b"col_a,col_b,col_c\n2026-01-05,Netflix,-15.99\n"
    with pytest.raises(CsvError):
        parse_csv(raw)  # unrecognisable without a mapping
    mapping = {"date": "col_a", "description": "col_b", "amount": "col_c"}
    assert len(parse_csv(raw, mapping).transactions) == 1
    with pytest.raises(CsvError):
        parse_csv(raw, {"date": "nope", "description": "col_b", "amount": "col_c"})


def test_parse_csv_reads_currency_column():
    raw = b"Date,Description,Amount,Currency\n2026-01-05,Adobe,-20.00,gbp\n"
    assert parse_csv(raw).transactions[0].currency == "GBP"


# ---------------------------------------------------------------- merchant names
def test_merchant_keys_ignore_references_and_noise():
    assert merchant_key("NETFLIX.COM 8665797172 CA") == "netflix"
    assert merchant_key("NETFLIX.COM 5551234567 CA") == "netflix"
    assert merchant_key("PAYPAL *SPOTIFY 4029357733") == "spotify"
    assert merchant_key("POS PURCHASE SHOPRITE LEKKI LAG") == "shoprite lekki"
    assert merchant_key("12345 67890") == ""


# ---------------------------------------------------------------- pattern detection
def tx(when, description, amount, currency=None):
    return Transaction(when, description, Decimal(str(amount)), currency)


def monthly(description, amount, months=6, day=5, start_month=1, currency=None):
    return [tx(date(2026, start_month + i, day), description, amount, currency) for i in range(months)]


def test_detects_monthly_subscription_and_ignores_the_rest():
    rows = (monthly("NETFLIX.COM 111 CA", -15.99) + monthly("PAYPAL *SPOTIFY 222", -9.99, day=12)
            + [tx(date(2026, 2, 20), "SHOPRITE LEKKI", -4500)]
            + [tx(date(2026, m, 25), "SALARY ACME LTD", 350000) for m in range(1, 7)])
    found = {c.name: c for c in detect_recurring(rows)}
    assert set(found) == {"Netflix", "Spotify"}
    assert found["Netflix"].interval == "month" and found["Netflix"].occurrences == 6
    assert found["Netflix"].amount == Decimal("15.99")
    assert found["Netflix"].last_date == date(2026, 6, 5)
    assert 0 < found["Netflix"].confidence <= Decimal("0.97")


def test_price_increase_is_still_one_subscription_at_the_latest_price():
    rows = monthly("SPOTIFY", -10.99, months=3) + monthly("SPOTIFY", -11.99, months=3, start_month=4)
    (candidate,) = detect_recurring(rows)
    assert candidate.amount == Decimal("11.99")


def test_weekly_and_yearly_detection():
    weekly = [tx(date(2026, 1, 1 + 7 * i), "MEAL KIT CO", -30) for i in range(4)]
    yearly = [tx(date(2025, 3, 10), "ANTIVIRUS PRO", -59.99), tx(date(2026, 3, 10), "ANTIVIRUS PRO", -59.99)]
    found = {c.name: c.interval for c in detect_recurring(weekly + yearly)}
    assert found == {"Meal Kit Co": "week", "Antivirus Pro": "year"}


def test_irregular_charges_are_not_subscriptions():
    rows = [tx(date(2026, 1, 3), "GYM DAY PASS", -3), tx(date(2026, 1, 29), "GYM DAY PASS", -3),
            tx(date(2026, 3, 30), "GYM DAY PASS", -3)]
    assert detect_recurring(rows) == []


def test_wildly_different_amounts_are_not_a_subscription():
    rows = [tx(date(2026, m, 5), "RESTAURANT", amount) for m, amount in [(1, -10), (2, -90), (3, -25), (4, -140)]]
    assert detect_recurring(rows) == []


def test_unstable_latest_price_is_rejected():
    rows = monthly("MYSTERY", -10, months=3) + [tx(date(2026, 4, 5), "MYSTERY", -14)]
    assert detect_recurring(rows) == []


def test_all_positive_amounts_are_treated_as_charges():
    rows = monthly("NETFLIX", 15.99)
    assert len(detect_recurring(rows)) == 1


def test_different_currencies_are_separate_groups():
    rows = monthly("ADOBE", -20, currency="GBP") + monthly("ADOBE", -25, currency="USD")
    found = detect_recurring(rows)
    assert sorted(c.currency for c in found) == ["GBP", "USD"]


def test_duplicate_rows_do_not_inflate_the_count():
    rows = monthly("NETFLIX", -15.99, months=3) + monthly("NETFLIX", -15.99, months=3)
    (candidate,) = detect_recurring(rows)
    assert candidate.occurrences == 3


# ---------------------------------------------------------------- dates
def test_add_months_clamps_to_month_end():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)


def test_next_renewal_counts_from_the_original_date():
    assert next_renewal_from(date(2026, 1, 31), "month", date(2026, 3, 1)) == date(2026, 3, 31)  # no drift to the 28th
    assert next_renewal_from(date(2026, 6, 5), "month", date(2026, 11, 6)) == date(2026, 12, 5)
    assert next_renewal_from(date(2026, 1, 1), "week", date(2026, 1, 20)) == date(2026, 1, 22)
    assert next_renewal_from(date(2025, 3, 10), "year", date(2026, 11, 6)) == date(2027, 3, 10)
    assert next_renewal_from(None, "month", date(2026, 1, 1)) is None
    assert next_renewal_from(date(2026, 12, 1), "month", date(2026, 11, 6)) == date(2026, 12, 1)  # already in the future


# ---------------------------------------------------------------- redaction
def test_redaction_removes_identifiers():
    out = redact_pii("Contact ada@example.com or call +234 801 234 5678")
    assert "@" not in out and "[EMAIL]" in out and "[PHONE]" in out and "801" not in out
    assert "[CARD]" in redact_pii("Paid with card 4111 1111 1111 1111 today")
    assert "4111" not in redact_pii("Paid with card 4111111111111111")
    assert "0123456789" not in redact_pii("Account 0123456789 debited")
    assert "[IBAN]" in redact_pii("Send to GB82WEST12345698765432 now")


def test_redaction_leaves_amounts_dates_and_names_alone():
    text = "Netflix charged NGN 5,000.00 on 2026-01-15, then 15.99 USD, order 123456789.50, due 15/01/2026"
    assert redact_pii(text) == text