"""Masking for customer PII and redaction for anything headed to the audit log."""
import re

PII_FIELDS = ("ssn", "bank_account")

# No word boundaries: an SSN glued to a letter, digit or underscore must still be caught.
_SSN_RE = re.compile(r"\d{3}-\d{2}-\d{4}")
_LONG_DIGITS_RE = re.compile(r"\d{8,}")


def mask_ssn(value: str | None) -> str:
    digits = re.sub(r"\D", "", value or "")
    return "***-**-" + digits[-4:]


def mask_bank_account(value: str | None) -> str:
    digits = re.sub(r"\D", "", value or "")
    return "****" + digits[-4:]


def redact_text(text: str) -> str:
    """Mask anything shaped like an SSN or an account number inside free text."""
    # Repeat until nothing matches: masking "123-45-6901-17-2231" once leaves "***-**-6901-17-2231",
    # which still holds an SSN. Every pass removes digits, so this ends.
    while True:
        masked = _SSN_RE.sub(lambda m: mask_ssn(m.group()), text)
        masked = _LONG_DIGITS_RE.sub(lambda m: mask_bank_account(m.group()), masked)
        if masked == text:
            return masked
        text = masked


def redact(value):
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key == "ssn":
                out[key] = mask_ssn(str(item))
            elif key == "bank_account":
                out[key] = mask_bank_account(str(item))
            else:
                out[key] = redact(item)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


def customer_view(row: dict, reveal: bool = False) -> dict:
    out = dict(row)
    if not reveal:
        out["ssn"] = mask_ssn(row["ssn"])
        out["bank_account"] = mask_bank_account(row["bank_account"])
    out["pii_revealed"] = reveal
    return out
