"""Blocking file and crypto work shared by both filesystem signing-certificate stores.

One JSON record per certificate lives at ``<root>/<environment>/<fingerprint>.json``:
the certificate as DER, its private key as password-encrypted PKCS#8 DER, and the two
annotations a store keeps. The path names the record, so the record does not repeat
it. The sync store calls these functions directly and the async store runs them in a
worker thread.
"""

import base64
import errno
import json
import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import cast

from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes
from cryptography.hazmat.primitives.serialization import (
    BestAvailableEncryption,
    Encoding,
    PrivateFormat,
    load_der_private_key,
)
from cryptography.x509 import Certificate

from ksef2._config import Environment
from ksef2._core import exceptions
from ksef2._domain.models.certificates import (
    CertificateTypeValue,
    validate_certificate_serial_number,
)
from ksef2._domain.models.signing_certificates import (
    SigningCertificate,
    SigningCertificateInfo,
    SigningCertificateRef,
    derive_signing_certificate_info,
)
from ksef2._domain.models.xades import XAdESCredentials

type PasswordProvider = Callable[[SigningCertificateRef], bytes]
"""Return the password protecting the record of the reference it is given."""

FORMAT = "ksef2-signing-certificate"
"""Value of a record's ``format`` field, so an unrelated JSON file is not read as one."""

VERSION = 1
"""Version written to a record, and the only version read back."""

type _Envelope = dict[str, object]

_CERTIFICATE_TYPES: tuple[CertificateTypeValue | None, ...] = (
    None,
    "authentication",
    "offline",
)
_RECORD_NAME = re.compile(r"[0-9a-f]{64}\.json")
_READ_FAILURES = (KeyError, TypeError, ValueError, UnsupportedAlgorithm)
_OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)


def prepare_root(root: Path) -> Path:
    """Return *root*, created owner-only when it is missing."""
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def save(
    root: Path,
    password_provider: PasswordProvider,
    certificate: SigningCertificate,
) -> SigningCertificateInfo:
    """Write the record of ``certificate`` unless one is stored already.

    Returns:
        The metadata of the stored record.

    Raises:
        KSeFCertificateStoreConflictError: If a different record is stored already.
    """
    # The guard is for callers without runtime type checking; the annotation above
    # is what type checkers see.
    if not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance]
        certificate, SigningCertificate
    ):
        raise exceptions.KSeFArgumentError(  # pyright: ignore[reportUnreachable]
            "save() needs a SigningCertificate.",
            hint="Wrap the XAdESCredentials in SigningCertificate(credentials, "
            "environment=...).",
        )

    reference = certificate.reference
    path = _record_path(root, reference)
    try:
        path.parent.mkdir(mode=0o700, exist_ok=True)
        raw = _read(path)
    except FileNotFoundError:
        raw = None
    except OSError as exc:
        raise _os_error(exc, "save", reference) from exc

    if raw is None:
        payload = _encode(certificate, _password(password_provider, reference, "save"))
        try:
            if _publish(path, payload):
                return certificate.info
            # Another writer published first; compare against its record.
            raw = _read(path)
        except OSError as exc:
            raise _os_error(exc, "save", reference) from exc

    _, stored = _describe(_parse(raw, reference, "save"), reference, "save")
    if stored != certificate.info:
        raise exceptions.KSeFCertificateStoreConflictError(
            "A different signing certificate record is already stored under this "
            "reference.",
            operation="save",
            reference=reference,
        )
    return stored


def load(
    root: Path,
    password_provider: PasswordProvider,
    reference: SigningCertificateRef,
) -> SigningCertificate:
    """Read, decrypt and rebuild the record stored under ``reference``."""
    reference = _checked_reference(reference, "load")
    try:
        raw = _read(_record_path(root, reference))
    except FileNotFoundError:
        raise exceptions.KSeFCertificateStoreNotFoundError(
            "No signing certificate is stored under this reference.",
            operation="load",
            reference=reference,
        ) from None
    except OSError as exc:
        raise _os_error(exc, "load", reference) from exc

    # Reading the record first reports a broken one without asking for a password.
    envelope = _parse(raw, reference, "load")
    certificate, info = _describe(envelope, reference, "load")
    private_key = _private_key(
        envelope, _password(password_provider, reference, "load"), reference
    )
    try:
        credentials = XAdESCredentials(certificate, private_key)
    except exceptions.KSeFArgumentError:
        raise _broken(
            "holds a private key that does not belong to its certificate",
            reference,
            "load",
        ) from None

    return SigningCertificate(
        credentials,
        environment=reference.environment,
        certificate_type=info.certificate_type,
        ksef_serial_number=info.ksef_serial_number,
    )


def list_records(
    root: Path,
    environment: Environment,
    certificate_type: CertificateTypeValue | None,
) -> tuple[SigningCertificateInfo, ...]:
    """Return the metadata of every record for one environment, without any password.

    A record that cannot be read is an error rather than a gap in the listing; a
    record deleted while listing is skipped.
    """
    directory = root / environment.name.lower()
    try:
        names = [name for name in os.listdir(directory) if _RECORD_NAME.fullmatch(name)]
    except FileNotFoundError:
        return ()
    except OSError as exc:
        raise _os_error(exc, "list", None) from exc

    infos: list[SigningCertificateInfo] = []
    for name in names:
        reference = SigningCertificateRef(
            environment=environment, fingerprint_sha256=name.removesuffix(".json")
        )
        try:
            raw = _read(directory / name)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise _os_error(exc, "list", reference) from exc
        _, info = _describe(_parse(raw, reference, "list"), reference, "list")
        if certificate_type is None or info.certificate_type == certificate_type:
            infos.append(info)

    return tuple(
        sorted(
            infos, key=lambda info: (info.valid_from, info.reference.fingerprint_sha256)
        )
    )


def delete(root: Path, reference: SigningCertificateRef) -> bool:
    """Remove the record stored under ``reference``; say whether there was one.

    Unlinking a symbolic link removes the link, never the file it points at.
    """
    reference = _checked_reference(reference, "delete")
    try:
        os.unlink(_record_path(root, reference))
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise _os_error(exc, "delete", reference) from exc
    return True


def _checked_reference(
    reference: SigningCertificateRef, operation: str
) -> SigningCertificateRef:
    # The guard is for callers without runtime type checking; the annotation is what
    # type checkers see.
    if not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance]
        reference, SigningCertificateRef
    ):
        raise exceptions.KSeFArgumentError(  # pyright: ignore[reportUnreachable]
            f"{operation}() needs a SigningCertificateRef.",
            hint="Pass record.info.reference, or build one with "
            "SigningCertificateRef.for_certificate(certificate, environment=...).",
        )
    return reference


def _record_path(root: Path, reference: SigningCertificateRef) -> Path:
    # The reference model validates the fingerprint as 64 lowercase hex characters,
    # so it cannot name anything outside the environment directory.
    environment = reference.environment.name.lower()
    return root / environment / f"{reference.fingerprint_sha256}.json"


def _read(path: Path) -> bytes:
    """Return the bytes at ``path``, refusing to follow a symbolic link to it."""
    with os.fdopen(os.open(path, _OPEN_FLAGS), "rb") as handle:
        return handle.read()


def _publish(path: Path, payload: bytes) -> bool:
    """Write ``payload`` to ``path`` atomically; ``False`` if a record was there first.

    The bytes reach stable storage in a temporary file before ``os.link`` publishes
    them, so a record is complete or absent, and the link never replaces a record
    another writer published.
    """
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "wb") as handle:
            _ = handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp_name, path)
        except FileExistsError:
            return False
        return True
    finally:
        try:
            os.unlink(temp_name)
        except OSError:
            pass


def _encode(certificate: SigningCertificate, password: bytes) -> bytes:
    """Return the record JSON for ``certificate``, its key encrypted under ``password``.

    Validity, serial number and fingerprints are left out: a reader recomputes them
    from the certificate, so a record cannot contradict its own certificate.
    """
    credentials = certificate.credentials
    key_der = credentials.private_key.private_bytes(
        Encoding.DER, PrivateFormat.PKCS8, BestAvailableEncryption(password)
    )
    envelope = {
        "format": FORMAT,
        "version": VERSION,
        "certificate_type": certificate.info.certificate_type,
        "ksef_serial_number": certificate.info.ksef_serial_number,
        "certificate_der": _b64(credentials.certificate.public_bytes(Encoding.DER)),
        "private_key_der": _b64(key_der),
    }
    return json.dumps(envelope, sort_keys=True).encode("utf-8")


def _parse(raw: bytes, reference: SigningCertificateRef, operation: str) -> _Envelope:
    """Return the record object in *raw* once its format and version are known."""
    try:
        parsed = cast(object, json.loads(raw))
    except ValueError:
        raise _broken("is not valid JSON", reference, operation) from None
    if not isinstance(parsed, dict):
        raise _broken("is not a JSON object", reference, operation)
    envelope = cast(_Envelope, parsed)
    if envelope.get("format") != FORMAT:
        raise _broken(
            "is not in the ksef2 signing-certificate format",
            reference,
            operation,
            hint="Point the store at a directory only it writes to.",
        )
    version = envelope.get("version")
    if version != VERSION:
        raise _broken(
            f"has unsupported version {version!r}",
            reference,
            operation,
            hint="Upgrade the SDK to one that reads this record.",
        )
    return envelope


def _describe(
    envelope: _Envelope, reference: SigningCertificateRef, operation: str
) -> tuple[Certificate, SigningCertificateInfo]:
    """Return a record's certificate and metadata, checked against ``reference``.

    The private key stays locked, so this needs no password.
    """
    certificate_type = envelope.get("certificate_type")
    if certificate_type not in _CERTIFICATE_TYPES:
        raise _broken(
            f"declares the unknown certificate type {certificate_type!r}",
            reference,
            operation,
        )
    serial_number = envelope.get("ksef_serial_number")
    try:
        if serial_number is not None:
            if not isinstance(serial_number, str):
                raise TypeError("ksef_serial_number")
            serial_number = validate_certificate_serial_number(serial_number)
        certificate = x509.load_der_x509_certificate(
            _b64_field(envelope, "certificate_der")
        )
    except _READ_FAILURES:
        raise _broken(
            "holds a certificate or serial number that cannot be read",
            reference,
            operation,
        ) from None

    info = derive_signing_certificate_info(
        certificate,
        environment=reference.environment,
        certificate_type=certificate_type,
        ksef_serial_number=serial_number,
    )
    if info.reference != reference:
        raise _broken(
            "does not hold the certificate its file name's fingerprint names",
            reference,
            operation,
            hint="Rename the record to the fingerprint of the certificate it holds, "
            "or restore an intact copy.",
        )
    return certificate, info


def _private_key(
    envelope: _Envelope, password: bytes, reference: SigningCertificateRef
) -> PrivateKeyTypes:
    """Return a record's private key once ``password`` unlocks it."""
    try:
        return load_der_private_key(
            _b64_field(envelope, "private_key_der"), password=password
        )
    except _READ_FAILURES:
        raise _broken(
            "holds a private key that could not be decrypted or parsed",
            reference,
            "load",
            hint="Check the password source, or restore an intact copy of the record.",
        ) from None


def _b64_field(envelope: _Envelope, name: str) -> bytes:
    """Return the Base64 field ``name`` decoded; raise a read failure otherwise."""
    value = envelope[name]
    if not isinstance(value, str):
        raise TypeError(name)
    return base64.b64decode(value, validate=True)


def _broken(
    problem: str,
    reference: SigningCertificateRef,
    operation: str,
    *,
    hint: str = "Restore an intact copy of the record.",
) -> exceptions.KSeFCertificateStoreMaterialError:
    return exceptions.KSeFCertificateStoreMaterialError(
        f"The signing certificate record {problem}.",
        operation=operation,
        reference=reference,
        hint=hint,
    )


def _password(
    password_provider: PasswordProvider,
    reference: SigningCertificateRef,
    operation: str,
) -> bytes:
    """Return the provider's password for ``reference``, held only as a local value.

    Anything the provider raises propagates unchanged.
    """
    password = password_provider(reference)
    # The guard is for unannotated providers and runs without runtime type checking.
    if not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance]
        password, bytes
    ):
        raise exceptions.KSeFArgumentError(
            "The password provider must return bytes.",
            hint="Return the password encoded, for example password.encode().",
        )
    if not password:
        raise exceptions.KSeFCertificateStoreAccessError(
            "The password provider returned an empty password.",
            operation=operation,
            reference=reference,
            hint="Return the non-empty password that protects this store's records.",
        )
    return password


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _os_error(
    exc: OSError, operation: str, reference: SigningCertificateRef | None
) -> exceptions.KSeFCertificateStoreError:
    """Return the store error for an OS failure; callers chain ``exc`` for its path."""
    if exc.errno == errno.ELOOP:
        return exceptions.KSeFCertificateStoreAccessError(
            "The store refuses to follow a symbolic link to a record.",
            operation=operation,
            reference=reference,
            hint="Replace the link with the record file itself.",
        )
    if isinstance(exc, PermissionError):
        return exceptions.KSeFCertificateStoreAccessError(
            "The store's files are not accessible to this process.",
            operation=operation,
            reference=reference,
        )
    return exceptions.KSeFCertificateStoreUnavailableError(
        f"The store could not complete {operation}() "
        f"({exc.strerror or type(exc).__name__}).",
        operation=operation,
        reference=reference,
    )
