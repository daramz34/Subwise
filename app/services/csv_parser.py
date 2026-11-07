"""Turns a bank-statement CSV into transactions. Pure Python, no dependencies.
Handles odd encodings, comma/semicolon/tab/pipe delimiters, preamble lines before the
header, many date and amount formats, and bad rows (skipped and counted, never fatal)."""
import codecs
import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


class CsvError(Exception):
    """A problem the user can act on. The message is safe to show them."""


@dataclass
class Transaction:
    date: date
    description: str
    amount: Decimal        # negative = money out, when the file uses signs
    currency: str | None


@dataclass
class ParseResult:
    transactions: list[Transaction]
    skipped_rows: int
    total_rows: int


ALIASES = {
    "date": {"date", "txn date", "transaction date", "trans date", "posting date", "posted date",
             "value date", "booking date", "post date"},
    "description": {"description", "narration", "details", "transaction details", "merchant", "memo",
                    "particulars", "remarks", "payee", "reference", "transaction description", "name"},
    "amount": {"amount", "debit", "withdrawal", "withdrawals", "debit amount", "value", "money out",
               "paid out", "transaction amount", "amount (ngn)", "amount (usd)"},
    "currency": {"currency", "ccy", "curr"},
}
FALLBACK_WORDS = {
    "date": ("date",),
    "description": ("narration", "description", "details", "merchant", "memo", "particulars"),
    "amount": ("amount", "debit", "withdraw"),
}
SYMBOL_CURRENCY = {"₦": "NGN", "$": "USD", "£": "GBP", "€": "EUR"}
DELIMITERS = [",", ";", "\t", "|"]


# --------------------------------------------------------------------------
# Decoding and delimiter
# --------------------------------------------------------------------------
def decode_bytes(raw: bytes) -> str:
    if raw.startswith(codecs.BOM_UTF8):
        return raw.decode("utf-8-sig")
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("cp1252")
        except UnicodeDecodeError:
            return raw.decode("latin-1")  # never fails


def detect_delimiter(text: str) -> str:
    """The delimiter that splits the first non-empty line into the most columns."""
    first = next((line for line in text.splitlines() if line.strip()), "")
    best, best_cols = ",", 1
    for delimiter in DELIMITERS:
        try:
            cols = len(next(csv.reader([first], delimiter=delimiter)))
        except (csv.Error, StopIteration):
            continue
        if cols > best_cols:
            best, best_cols = delimiter, cols
    return best


# --------------------------------------------------------------------------
# Amounts and dates
# --------------------------------------------------------------------------
def parse_amount(text: str) -> tuple[Decimal | None, str | None]:
    """Returns (amount, currency_hint). Accepts 1,234.56  1.234,56  (15.99)  -15.99  15.99-  NGN 5,000"""
    s = (text or "").strip().replace("\u2212", "-")  # unicode minus
    if not s:
        return None, None

    negative = False
    currency = None

    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1].strip()
    if s.upper().endswith("DR"):
        negative, s = True, s[:-2].strip()
    elif s.upper().endswith("CR"):
        s = s[:-2].strip()
    if s.endswith("-"):
        negative, s = True, s[:-1].strip()
    if s.startswith("-"):
        negative, s = True, s[1:].strip()

    for symbol, code in SYMBOL_CURRENCY.items():
        if symbol in s:
            currency = code
            s = s.replace(symbol, "")
    code_match = re.match(r"^([A-Za-z]{3})\s*(?=[\d.,])", s)
    if code_match:
        currency = code_match.group(1).upper()
        s = s[code_match.end():]
    s = s.replace(" ", "").replace("\u00a0", "")

    if not re.fullmatch(r"[\d.,]+", s) or not re.search(r"\d", s):
        return None, None

    if "," in s and "." in s:
        decimal_sep = s[max(s.rfind(","), s.rfind("."))]
        thousands = "," if decimal_sep == "." else "."
        s = s.replace(thousands, "").replace(decimal_sep, ".")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) in (1, 2):
            s = parts[0] + "." + parts[1]          # decimal comma: 15,99
        else:
            s = s.replace(",", "")                  # thousands: 1,234 or 1,234,567
    elif s.count(".") > 1:
        s = s.replace(".", "")                      # 1.234.567

    try:
        value = Decimal(s)
    except InvalidOperation:
        return None, None
    return (-value if negative else value), currency


_TIME_SUFFIX = re.compile(r"[\sT]+\d{1,2}:\d{2}(:\d{2})?(\.\d+)?(\s?[AaPp][Mm])?(Z|[+-]\d{2}:?\d{2})?$")
_NUMERIC_DATE = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})$")
_TEXT_FORMATS = ["%Y-%m-%d", "%Y/%m/%d", "%d-%b-%Y", "%d %b %Y", "%d-%B-%Y", "%d %B %Y",
                 "%b %d, %Y", "%B %d, %Y", "%d-%b-%y"]


def infer_dayfirst(date_strings: list[str]) -> bool:
    """Decide dd/mm vs mm/dd from the whole file: one date like 25/12/2026 settles it.
    If it's truly ambiguous, day-first wins (most of the world, including Nigeria)."""
    for s in date_strings:
        m = _NUMERIC_DATE.match(_TIME_SUFFIX.sub("", (s or "").strip()))
        if m:
            if int(m.group(1)) > 12:
                return True
            if int(m.group(2)) > 12:
                return False
    return True


def parse_date(text: str, dayfirst: bool = True) -> date | None:
    s = _TIME_SUFFIX.sub("", (text or "").strip())
    if not s:
        return None
    for fmt in _TEXT_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    m = _NUMERIC_DATE.match(s)
    if m:
        a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 2000
        day, month = (a, b) if dayfirst else (b, a)
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


# --------------------------------------------------------------------------
# Columns
# --------------------------------------------------------------------------
def _norm(header: str) -> str:
    return re.sub(r"\s+", " ", (header or "").strip().lower())


def guess_columns(header: list[str]) -> dict[str, int] | None:
    normed = [_norm(h) for h in header]
    found: dict[str, int] = {}
    for field, aliases in ALIASES.items():
        for i, h in enumerate(normed):
            if h in aliases and i not in found.values():
                found[field] = i
                break
    for field, words in FALLBACK_WORDS.items():
        if field in found:
            continue
        for i, h in enumerate(normed):
            if i not in found.values() and any(w in h for w in words):
                found[field] = i
                break
    return found if {"date", "description", "amount"} <= found.keys() else None


def _columns_from_mapping(header: list[str], mapping: dict[str, str]) -> dict[str, int] | None:
    normed = [_norm(h) for h in header]
    found = {}
    for field, column_name in mapping.items():
        wanted = _norm(column_name)
        if wanted not in normed:
            return None
        found[field] = normed.index(wanted)
    return found


def _find_header(rows: list[list[str]], mapping: dict[str, str] | None):
    for index, row in enumerate(rows[:25]):
        columns = _columns_from_mapping(row, mapping) if mapping else guess_columns(row)
        if columns:
            return index, columns
    return None, None


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------
def parse_csv(raw: bytes, mapping: dict[str, str] | None = None, max_rows: int = 5000) -> ParseResult:
    text = decode_bytes(raw)
    try:
        rows = list(csv.reader(io.StringIO(text), delimiter=detect_delimiter(text)))
    except csv.Error:
        raise CsvError("The file couldn't be read as CSV.")
    rows = [r for r in rows if any(cell.strip() for cell in r)]
    if len(rows) < 2:
        raise CsvError("The file has no transactions in it.")
    if len(rows) - 1 > max_rows:
        raise CsvError(f"The file has more than {max_rows} rows. Split it into smaller files.")

    header_index, columns = _find_header(rows, mapping)
    if columns is None:
        raise CsvError(
            "Couldn't recognise the columns. The file needs date, description and amount columns. "
            "Save a column mapping for this bank and try again."
        )

    data_rows = rows[header_index + 1:]
    needed = max(columns.values())
    dayfirst = infer_dayfirst([r[columns["date"]] for r in data_rows if len(r) > columns["date"]])

    transactions: list[Transaction] = []
    skipped = 0
    for row in data_rows:
        if len(row) <= needed:
            skipped += 1
            continue
        when = parse_date(row[columns["date"]], dayfirst)
        amount, hint = parse_amount(row[columns["amount"]])
        description = row[columns["description"]].strip()
        if when is None or amount is None or not description or amount == 0:
            skipped += 1
            continue
        currency = None
        if "currency" in columns:
            code = row[columns["currency"]].strip().upper()
            currency = code if re.fullmatch(r"[A-Z]{3}", code) else None
        transactions.append(Transaction(when, description, amount, currency or hint))

    if not transactions:
        raise CsvError(
            "None of the rows could be read. Check the date and amount columns, "
            "or save a column mapping for this bank."
        )
    return ParseResult(transactions, skipped, len(data_rows))