"""Strips personal identifiers from text BEFORE it is sent to an AI service.
Pure Python, no dependencies.

It catches emails, card numbers, IBANs, phone numbers and long account-style numbers.
It can NOT recognise names or street addresses, so it reduces exposure rather than
eliminating it. Amounts, dates and merchant names are deliberately left intact."""
import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
GROUPED_CARD_RE = re.compile(r"\b\d{4}(?:[ -]\d{4}){3,4}\b")
PLAIN_CARD_RE = re.compile(r"\b\d{13,19}\b")
PHONE_RE = re.compile(r"(?<![\w.,])\+?\d[\d ()\-]{7,}\d(?!\w)")
LONG_NUMBER_RE = re.compile(r"(?<![\d.,])\d{9,}(?!\d|[.,]\d)")  # not followed by decimals, so amounts survive


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _card_or_number(match: re.Match) -> str:
    digits = re.sub(r"\D", "", match.group())
    if 13 <= len(digits) <= 19 and _luhn_ok(digits):
        return "[CARD]"
    return "[NUMBER]"


def _phone(match: re.Match) -> str:
    text = match.group()
    digits = re.sub(r"\D", "", text)
    if not 9 <= len(digits) <= 15:
        return text  # too short or long to be a phone number (dates, amounts, ids)
    if digits == text.lstrip("+"):
        return text  # a plain run of digits is handled by the account-number rule
    return "[PHONE]"


def redact_pii(text: str) -> str:
    text = EMAIL_RE.sub("[EMAIL]", text)
    text = IBAN_RE.sub("[IBAN]", text)
    text = GROUPED_CARD_RE.sub(_card_or_number, text)
    text = PLAIN_CARD_RE.sub(_card_or_number, text)
    text = PHONE_RE.sub(_phone, text)
    text = LONG_NUMBER_RE.sub("[NUMBER]", text)
    return text