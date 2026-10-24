"""Local validation shared by authentication and permission requests."""

import re
from ksef2._core import exceptions


def validate_nip(
    nip: str | None, *, parameter: str = "nip", normalize: bool = True
) -> str:
    if not isinstance(nip, str):
        raise exceptions.KSeFArgumentError(
            f"{parameter} must be a 10-digit Polish NIP.",
            hint="Pass 10 digits; dashes and a leading PL prefix are accepted.",
        )
    hint = (
        "Pass 10 digits; dashes and a leading PL prefix are accepted."
        if normalize
        else "Pass a 10-digit NIP matching the declared identifier type."
    )
    normalized = re.sub(r"[-\s]", "", nip.strip()).upper()
    if normalized.startswith("PL"):
        normalized = normalized[2:]
    if not normalize:
        normalized = nip
    if not re.fullmatch(r"[0-9]{10}", normalized):
        raise exceptions.KSeFArgumentError(
            f"{parameter} must contain exactly 10 digits.",
            hint=hint,
        )
    weights = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    checksum = (
        sum(
            int(digit) * weight
            for digit, weight in zip(normalized[:9], weights, strict=True)
        )
        % 11
    )
    if checksum == 10 or checksum != int(normalized[9]):
        raise exceptions.KSeFArgumentError(
            f"{parameter} has an invalid checksum.",
            hint="Check the 10-digit NIP value.",
        )
    return normalized


def validate_pesel(pesel: str, *, parameter: str = "pesel") -> str:
    """Validate the 11 ASCII digits and checksum without imposing date rules."""
    if re.fullmatch(r"[0-9]{11}", pesel) is None:
        raise exceptions.KSeFArgumentError(
            f"{parameter} must contain exactly 11 digits for a PESEL.",
            hint='Pass an 11-digit PESEL for subject_type="pesel".',
        )
    checksum = (
        10
        - sum(
            int(digit) * weight
            for digit, weight in zip(
                pesel[:10], (1, 3, 7, 9, 1, 3, 7, 9, 1, 3), strict=True
            )
        )
        % 10
    ) % 10
    if checksum != int(pesel[-1]):
        raise exceptions.KSeFArgumentError(
            f"{parameter} has an invalid PESEL checksum.",
            hint="Check the 11-digit PESEL value and subject_type.",
        )
    return pesel


def require_nonempty(value: object, parameter: str) -> None:
    """Reject empty credentials, identifiers, and permission lists locally."""
    if not value or isinstance(value, str) and not value.strip():
        raise exceptions.KSeFArgumentError(
            f"{parameter} must not be empty.",
            hint=f"Pass a non-empty {parameter} value.",
        )


def validate_permission_identifiers(data: dict[str, object]) -> None:
    """Validate NIP/PESEL only where the caller declares that identifier type."""
    for prefix in (
        "subject",
        "context",
        "target",
        "author",
        "authorized",
        "authorizing",
    ):
        kind = data.get(f"{prefix}_type")
        parameter = f"{prefix}_value"
        value = data.get(parameter)
        if isinstance(value, str):
            if kind == "nip":
                _ = validate_nip(value, parameter=parameter, normalize=False)
            elif kind == "pesel":
                _ = validate_pesel(value, parameter=parameter)
