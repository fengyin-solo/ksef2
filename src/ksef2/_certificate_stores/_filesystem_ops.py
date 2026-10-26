"""Blocking file and crypto work shared by the filesystem signing-certificate stores.

One JSON record per certificate lives at ``<root>/<environment>/<fingerprint>.json``:
the certificate in DER, its private key as password-encrypted PKCS#8 DER, and the two
metadata annotations a store keeps. Nothing here is public API; the store classes in
``ksef2.certificate_stores`` are the supported entry point, and both of them call
these functions.

Every function blocks. The sync adapter calls them directly and the async adapter
runs them in a worker thread, which is why this module holds the whole implementation
once instead of writing it twice.

There is no plaintext mode: a record always carries an encrypted key, and a read never
rewrites a record.
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
    CertificateSerialNumber,
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

_ID_FIELDS = ("format", "environment", "fingerprint_sha256")
_DER_FIELDS = ("certificate_der", "private_key_der")
_CERTIFICATE_TYPES: tuple[CertificateTypeValue, ...] = ("authentication", "offline")
_RECORD_NAME_RE = re.compile(r"^[0-9a-f]{64}\.json$")
_READ_FAILURES = (ValueError, TypeError, UnsupportedAlgorithm)
_RDONLY = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
_TEMP_PREFIX = ".tmp-"
_SUFFIX = ".json"


def prepare_root(root: Path) -> Path:
    """Return *root*, created as an owner-only directory when it is missing.

    An existing directory keeps the permissions it has: the application may have set
    them on purpose. The root itself is not resolved, so a root under a symlink such
    as macOS ``/var`` keeps working.

    Args:
        root: Directory that holds this store's environment directories.

    Returns:
        The same ``root`` the store keeps using.

    Raises:
        OSError: If the directory could not be created; the store maps it.
    """
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def save(
    root: Path,
    password_provider: PasswordProvider,
    certificate: SigningCertificate,
) -> SigningCertificateInfo:
    """Write one record under ``certificate.reference`` and return its metadata.

    Args:
        root: Directory that holds this store's records.
        password_provider: Supplies the password that encrypts the key.
        certificate: The validated pair to persist.

    Returns:
        The metadata of the stored record: the given one for a new record, the
            stored one when an equal record was already there.

    Raises:
        KSeFArgumentError: If ``certificate`` is not a ``SigningCertificate``.
        KSeFCertificateStoreConflictError: If a different record is stored already.
        KSeFCertificateStoreAccessError: If a file is unreadable, a link is in the
            way, or the password provider returned an empty password.
        KSeFCertificateStoreMaterialError: If an existing record cannot be read.
        KSeFCertificateStoreUnavailableError: If the files could not be written.
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
    env_dir = _env_dir(root, reference.environment)
    path = _record_path(root, reference)
    try:
        _ensure_env_dir(env_dir, operation="save", reference=reference)
    except OSError as exc:
        raise _os_error(exc, operation="save", reference=reference) from exc

    stored = _stored_info(path, reference, operation="save")
    if stored is not None:
        return _equal_or_conflict(stored, certificate)

    payload = _envelope_bytes(
        reference,
        _password(password_provider, reference, operation="save"),
        certificate,
    )
    if not _publish(env_dir, path, payload, reference):
        # Another writer published between the read above and the failed link.
        raced = _stored_info(path, reference, operation="save")
        if raced is None:
            # The record it published is gone again; the store cannot say what is on
            # disk, so it reports the ambiguity instead of guessing.
            raise exceptions.KSeFCertificateStoreUnavailableError(
                "The store could not complete save() (the record disappeared while "
                "it was being written).",
                operation="save",
                reference=reference,
                outcome_ambiguous=True,
            )
        return _equal_or_conflict(raced, certificate)

    return certificate.info


def load(
    root: Path,
    password_provider: PasswordProvider,
    reference: SigningCertificateRef,
) -> SigningCertificate:
    """Read, decrypt and rebuild the record stored under ``reference``.

    Args:
        root: Directory that holds this store's records.
        password_provider: Supplies the password that decrypts the key.
        reference: Environment and certificate fingerprint to read back.

    Returns:
        The stored pair, ready to sign with.

    Raises:
        KSeFArgumentError: If ``reference`` is not a ``SigningCertificateRef``.
        KSeFCertificateStoreNotFoundError: If no record is stored under ``reference``.
        KSeFCertificateStoreMaterialError: If the record, its key or its identity is
            not usable.
        KSeFCertificateStoreAccessError: If a file is unreadable, a link is in the
            way, or the password provider returned an empty password.
        KSeFCertificateStoreUnavailableError: If the files could not be read.
    """
    reference = _checked_reference(reference, operation="load")
    env_dir = _env_dir(root, reference.environment)
    path = _record_path(root, reference)
    try:
        _refuse_env_symlink(env_dir, operation="load", reference=reference)
        envelope = _read_envelope(path, reference, operation="load")
    except FileNotFoundError:
        raise exceptions.KSeFCertificateStoreNotFoundError(
            "No signing certificate is stored under this reference.",
            operation="load",
            reference=reference,
        ) from None
    except OSError as exc:
        raise _os_error(exc, operation="load", reference=reference) from exc

    # The password is asked for only once the envelope parsed: a broken record is
    # reported as broken without prompting anyone for a secret.
    password = _password(password_provider, reference, operation="load")
    certificate = _certificate(envelope, reference, operation="load")
    private_key = _private_key(
        _bytes_field(envelope, "private_key_der", reference, operation="load"),
        password,
        reference,
        operation="load",
    )

    try:
        credentials = XAdESCredentials(certificate, private_key)
    except exceptions.KSeFArgumentError:
        raise exceptions.KSeFCertificateStoreMaterialError(
            "The stored private key does not belong to the stored certificate.",
            operation="load",
            reference=reference,
            hint="Restore an intact copy of the record: the key it holds was never "
            "issued for the certificate beside it.",
        ) from None

    certificate_type = _certificate_type_field(envelope, reference, operation="load")
    ksef_serial_number = _serial_number_field(envelope, reference, operation="load")
    record = SigningCertificate(
        credentials,
        environment=reference.environment,
        certificate_type=certificate_type,
        ksef_serial_number=ksef_serial_number,
    )
    if (
        record.info != _info_from_envelope(envelope, reference, operation="load")
        or record.reference != reference
    ):
        raise exceptions.KSeFCertificateStoreMaterialError(
            "The record rebuilt from the stored material does not match the "
            "stored metadata.",
            operation="load",
            reference=reference,
            hint="Restore an intact copy of the record.",
        ) from None

    return record


def list_records(
    root: Path,
    environment: Environment,
    certificate_type: CertificateTypeValue | None,
) -> tuple[SigningCertificateInfo, ...]:
    """Return the metadata of every record stored for one environment.

    A record's private key is never decrypted here, so this asks for no password. A
    record whose metadata cannot be read is an error rather than a gap in the
    listing; a record that vanishes mid-listing is not.

    Args:
        root: Directory that holds this store's records.
        environment: Environment whose records to return.
        certificate_type: When given, return only records of this KSeF purpose.

    Returns:
        Metadata for every matching record, ordered by ``valid_from`` and then by
            ``fingerprint_sha256``.

    Raises:
        KSeFCertificateStoreMaterialError: If a stored record cannot be read.
        KSeFCertificateStoreAccessError: If a link stands in place of the environment
            directory.
        KSeFCertificateStoreUnavailableError: If the directory could not be read.
    """
    env_dir = _env_dir(root, environment)
    infos: list[SigningCertificateInfo] = []
    try:
        if not env_dir.exists():
            return ()
        _refuse_env_symlink(env_dir, operation="list", reference=None)
        names = _record_names(env_dir)
    except OSError as exc:
        raise _os_error(exc, operation="list", reference=None) from exc

    for name in names:
        reference = SigningCertificateRef(
            environment=environment,
            fingerprint_sha256=name[: -len(_SUFFIX)],
        )
        try:
            envelope = _read_envelope(env_dir / name, reference, operation="list")
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise _os_error(exc, operation="list", reference=reference) from exc

        info = _info_from_envelope(envelope, reference, operation="list")
        if certificate_type is not None and info.certificate_type != certificate_type:
            continue
        infos.append(info)

    return tuple(
        sorted(
            infos,
            key=lambda info: (info.valid_from, info.reference.fingerprint_sha256),
        )
    )


def delete(root: Path, reference: SigningCertificateRef) -> bool:
    """Remove the record stored under ``reference``.

    Unlinking removes a symlink itself and never the file it points at, so a link
    left where a record belongs cannot delete anything outside the store.

    Args:
        root: Directory that holds this store's records.
        reference: Environment and certificate fingerprint to remove.

    Returns:
        ``True`` when a record was removed, ``False`` when there was none.

    Raises:
        KSeFArgumentError: If ``reference`` is not a ``SigningCertificateRef``.
        KSeFCertificateStoreAccessError: If a link stands in place of the environment
            directory.
        KSeFCertificateStoreUnavailableError: If the record could not be removed.
    """
    reference = _checked_reference(reference, operation="delete")
    env_dir = _env_dir(root, reference.environment)
    path = _record_path(root, reference)
    try:
        _refuse_env_symlink(env_dir, operation="delete", reference=reference)
        os.unlink(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise _os_error(exc, operation="delete", reference=reference) from exc

    return True


def _checked_reference(
    reference: SigningCertificateRef, *, operation: str
) -> SigningCertificateRef:
    """Return *reference* once it really is a reference, or raise an argument error.

    The guard is for callers without runtime type checking; the annotation is what
    type checkers see.
    """
    if not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance]
        reference, SigningCertificateRef
    ):
        raise exceptions.KSeFArgumentError(  # pyright: ignore[reportUnreachable]
            f"{operation}() needs a SigningCertificateRef.",
            hint="Pass record.info.reference, or build one with "
            "SigningCertificateRef.for_certificate(certificate, environment=...).",
        )
    return reference


def _env_dir(root: Path, environment: Environment) -> Path:
    """Return the directory holding one environment's records."""
    return root / environment.name.lower()


def _record_path(root: Path, reference: SigningCertificateRef) -> Path:
    """Return the file holding the record of ``reference``.

    The reference model validates the fingerprint as 64 lowercase hex characters, so
    it cannot name anything outside the environment directory. The check below keeps
    that guarantee local to this function.

    Raises:
        AssertionError: If a reference named something outside its directory.
    """
    env_dir = _env_dir(root, reference.environment)
    path = env_dir / f"{reference.fingerprint_sha256}{_SUFFIX}"
    assert path.parent == env_dir, "a record must stay inside its environment directory"
    return path


def _refuse_env_symlink(
    env_dir: Path, *, operation: str, reference: SigningCertificateRef | None
) -> None:
    """Raise an access error when a link stands where ``env_dir`` belongs."""
    if env_dir.is_symlink():
        raise exceptions.KSeFCertificateStoreAccessError(
            "The store refuses a symbolic link in place of an environment directory.",
            operation=operation,
            reference=reference,
            hint="Replace the link with a real directory owned by this application.",
        )


def _ensure_env_dir(
    env_dir: Path, *, operation: str, reference: SigningCertificateRef
) -> None:
    """Create ``env_dir`` owner-only, refusing a link that already occupies it."""
    _refuse_env_symlink(env_dir, operation=operation, reference=reference)
    try:
        os.mkdir(env_dir, 0o700)
    except FileExistsError:
        pass


def _record_names(env_dir: Path) -> list[str]:
    """Return the entry names in ``env_dir`` that can hold a record.

    A dot-prefixed name is the temporary file of a concurrent or interrupted write,
    and anything else that does not look like a fingerprint was not written here.
    """
    names: list[str] = []
    with os.scandir(env_dir) as entries:
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if _RECORD_NAME_RE.match(entry.name):
                names.append(entry.name)
    return names


def _read_envelope(
    path: Path, reference: SigningCertificateRef, *, operation: str
) -> dict[str, object]:
    """Return the parsed record at ``path``, refusing to follow a link to it.

    ``FileNotFoundError`` is left to the caller to decide: ``load()`` reports a
    missing record, ``list()`` steps over one that vanished.

    Raises:
        KSeFCertificateStoreAccessError: If ``path`` is a symbolic link.
        KSeFCertificateStoreMaterialError: If the bytes are not an intact record.
    """
    if path.is_symlink():
        raise _refuses_link(reference, operation)

    try:
        fd = os.open(path, _RDONLY)
    except FileNotFoundError:
        raise
    except OSError as exc:
        # O_NOFOLLOW is missing only on platforms that lack it; the stat after the
        # failure covers those too, and says nothing about a file that never was.
        if exc.errno == errno.ELOOP or path.is_symlink():
            raise _refuses_link(reference, operation) from exc
        raise

    try:
        with os.fdopen(fd, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        raise _os_error(exc, operation=operation, reference=reference) from exc

    return _envelope_from_bytes(raw, reference, operation=operation)


def _refuses_link(
    reference: SigningCertificateRef, operation: str
) -> exceptions.KSeFCertificateStoreAccessError:
    """Return the error for a link left where a record belongs."""
    return exceptions.KSeFCertificateStoreAccessError(
        "The store refuses to follow a symbolic link to a record.",
        operation=operation,
        reference=reference,
        hint="Replace the link with the record file itself.",
    )


def _envelope_from_bytes(
    raw: bytes, reference: SigningCertificateRef, *, operation: str
) -> dict[str, object]:
    """Return the record object held in *raw*, or raise the error for it."""
    try:
        parsed = cast(object, json.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, ValueError):
        raise exceptions.KSeFCertificateStoreMaterialError(
            "The signing certificate record is not valid UTF-8 JSON.",
            operation=operation,
            reference=reference,
        ) from None

    if not isinstance(parsed, dict):
        raise exceptions.KSeFCertificateStoreMaterialError(
            "The signing certificate record is not a JSON object.",
            operation=operation,
            reference=reference,
        ) from None

    envelope = cast("dict[str, object]", parsed)
    recorded_format = envelope.get("format")
    if not isinstance(recorded_format, str):
        raise _missing_field("format", reference, operation=operation)
    if recorded_format != FORMAT:
        raise exceptions.KSeFCertificateStoreMaterialError(
            "The signing certificate record declares the unknown format "
            f"{recorded_format!r}.",
            operation=operation,
            reference=reference,
            hint="This file was not written by a ksef2 signing-certificate store. "
            "Point the store at its own directory, or restore an intact copy.",
        ) from None

    version = envelope.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise _missing_field("version", reference, operation=operation)
    if version != VERSION:
        raise exceptions.KSeFCertificateStoreMaterialError(
            f"Unsupported signing certificate record version {version!r}.",
            operation=operation,
            reference=reference,
            hint="Upgrade the SDK to one that reads this record. A store never "
            "rewrites a record it cannot read.",
        ) from None

    for name in _ID_FIELDS[1:]:
        if not isinstance(envelope.get(name), str):
            raise _missing_field(name, reference, operation=operation)
    for name in _DER_FIELDS:
        # The value is not needed here; reading it is what proves the record holds
        # Base64 the reader can decode later.
        _ = _bytes_field(envelope, name, reference, operation=operation)

    return envelope


def _missing_field(
    name: str, reference: SigningCertificateRef, *, operation: str
) -> exceptions.KSeFCertificateStoreMaterialError:
    """Return the error for a record field that is absent or not of its own type."""
    return exceptions.KSeFCertificateStoreMaterialError(
        f"The signing certificate record has no usable {name!r} field.",
        operation=operation,
        reference=reference,
    )


def _bytes_field(
    envelope: dict[str, object],
    name: str,
    reference: SigningCertificateRef,
    *,
    operation: str,
) -> bytes:
    """Return the Base64 field ``name`` of ``envelope`` decoded to bytes.

    Raises:
        KSeFCertificateStoreMaterialError: If the field is not Base64 text.
    """
    value = envelope.get(name)
    if not isinstance(value, str):
        raise _missing_field(name, reference, operation=operation)
    try:
        return base64.b64decode(value, validate=True)
    except ValueError:
        raise exceptions.KSeFCertificateStoreMaterialError(
            f"The signing certificate record's {name!r} field is not valid Base64.",
            operation=operation,
            reference=reference,
        ) from None


def _optional_str_field(
    envelope: dict[str, object],
    name: str,
    reference: SigningCertificateRef,
    *,
    operation: str,
) -> str | None:
    """Return the optional text field ``name`` of ``envelope``.

    Raises:
        KSeFCertificateStoreMaterialError: If the field holds neither ``null`` nor
            text.
    """
    value = envelope.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _missing_field(name, reference, operation=operation)
    return value


def _certificate_type_field(
    envelope: dict[str, object], reference: SigningCertificateRef, *, operation: str
) -> CertificateTypeValue | None:
    """Return the KSeF purpose a record claims.

    Checking it here, rather than letting the metadata model refuse it, keeps a
    damaged record reported as damaged under runtime type checking too.

    Raises:
        KSeFCertificateStoreMaterialError: If the claimed purpose is not one KSeF has.
    """
    value = _optional_str_field(
        envelope, "certificate_type", reference, operation=operation
    )
    if value is None:
        return None
    if value in _CERTIFICATE_TYPES:
        return value
    raise exceptions.KSeFCertificateStoreMaterialError(
        "The signing certificate record declares the unknown certificate type "
        f"{value!r}.",
        operation=operation,
        reference=reference,
        hint="Restore an intact copy of the record.",
    )


def _serial_number_field(
    envelope: dict[str, object], reference: SigningCertificateRef, *, operation: str
) -> CertificateSerialNumber | None:
    """Return the KSeF serial number a record claims.

    Raises:
        KSeFCertificateStoreMaterialError: If the field is neither ``null`` nor a
            serial number KSeF could have assigned.
    """
    value = _optional_str_field(
        envelope, "ksef_serial_number", reference, operation=operation
    )
    if value is None:
        return None
    try:
        return validate_certificate_serial_number(value)
    except exceptions.KSeFValidationError:
        raise exceptions.KSeFCertificateStoreMaterialError(
            "The signing certificate record claims a KSeF serial number KSeF could "
            "not have assigned.",
            operation=operation,
            reference=reference,
            hint="Restore an intact copy of the record.",
        ) from None


def _info_from_envelope(
    envelope: dict[str, object], reference: SigningCertificateRef, *, operation: str
) -> SigningCertificateInfo:
    """Return the metadata a record claims, reading its certificate but not its key.

    Raises:
        KSeFCertificateStoreMaterialError: If the record does not describe
            ``reference``, or its metadata is not valid.
    """
    certificate = _certificate(envelope, reference, operation=operation)
    return derive_signing_certificate_info(
        certificate,
        environment=_environment(envelope, reference, operation=operation),
        certificate_type=_certificate_type_field(
            envelope, reference, operation=operation
        ),
        ksef_serial_number=_serial_number_field(
            envelope, reference, operation=operation
        ),
    )


def _environment(
    envelope: dict[str, object], reference: SigningCertificateRef, *, operation: str
) -> Environment:
    """Return the environment a record names, checked against ``reference``.

    Raises:
        KSeFCertificateStoreMaterialError: If the name is not a KSeF environment, or
            not the one ``reference`` asks for.
    """
    recorded = envelope.get("environment")
    if not isinstance(recorded, str):
        raise _missing_field("environment", reference, operation=operation)
    try:
        environment = Environment[recorded.upper()]
    except KeyError:
        raise exceptions.KSeFCertificateStoreMaterialError(
            "The signing certificate record names an unknown KSeF environment.",
            operation=operation,
            reference=reference,
        ) from None

    if recorded != reference.environment.name.lower():
        raise exceptions.KSeFCertificateStoreMaterialError(
            "The signing certificate record belongs to another environment than the "
            "one it is stored under.",
            operation=operation,
            reference=reference,
            hint="Move the record into the directory of its own environment, or "
            "restore an intact copy.",
        ) from None

    return environment


def _certificate(
    envelope: dict[str, object], reference: SigningCertificateRef, *, operation: str
) -> Certificate:
    """Return the certificate a record holds, checked against ``reference``.

    Raises:
        KSeFCertificateStoreMaterialError: If the DER does not parse, or the
            certificate is not the one ``reference`` names.
    """
    der = _bytes_field(envelope, "certificate_der", reference, operation=operation)

    recorded_fingerprint = envelope.get("fingerprint_sha256")
    if recorded_fingerprint != reference.fingerprint_sha256:
        raise exceptions.KSeFCertificateStoreMaterialError(
            "The signing certificate record is stored under a fingerprint other "
            "than its own.",
            operation=operation,
            reference=reference,
            hint="Rename the record to the fingerprint of the certificate it holds, "
            "or restore an intact copy.",
        ) from None

    try:
        certificate = x509.load_der_x509_certificate(der)
    except _READ_FAILURES:
        raise exceptions.KSeFCertificateStoreMaterialError(
            "The stored certificate could not be parsed.",
            operation=operation,
            reference=reference,
            hint="Restore an intact copy of the record.",
        ) from None

    if (
        SigningCertificateRef.for_certificate(
            certificate, environment=reference.environment
        )
        != reference
    ):
        raise exceptions.KSeFCertificateStoreMaterialError(
            "The stored certificate does not match the fingerprint it is stored under.",
            operation=operation,
            reference=reference,
            hint="Restore an intact copy of the record.",
        ) from None

    return certificate


def _private_key(
    key_der: bytes,
    password: bytes,
    reference: SigningCertificateRef,
    *,
    operation: str,
) -> PrivateKeyTypes:
    """Return the private key a record holds once ``password`` unlocks it.

    Raises:
        KSeFCertificateStoreMaterialError: If the bytes are not a key this password
            unlocks.
    """
    try:
        return load_der_private_key(key_der, password=password)
    except _READ_FAILURES:
        raise exceptions.KSeFCertificateStoreMaterialError(
            "The stored private key could not be decrypted or parsed.",
            operation=operation,
            reference=reference,
            hint="Check the password source, or restore an intact copy of the record.",
        ) from None


def _password(
    password_provider: PasswordProvider,
    reference: SigningCertificateRef,
    *,
    operation: str,
) -> bytes:
    """Return the password for ``reference``, held only as a local value.

    Anything the provider itself raises propagates unchanged: a provider that cannot
    reach its source is a programming or deployment fault, not a damaged record.

    Raises:
        KSeFArgumentError: If the provider returned something other than bytes.
        KSeFCertificateStoreAccessError: If the provider returned an empty password.
    """
    password = password_provider(reference)
    # The guard is for callers whose provider is unannotated, and for runs without
    # runtime type checking; the annotation above is what type checkers see.
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


def _stored_info(
    path: Path, reference: SigningCertificateRef, *, operation: str
) -> SigningCertificateInfo | None:
    """Return the metadata of the record at ``path``, or ``None`` when there is none."""
    try:
        envelope = _read_envelope(path, reference, operation=operation)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _os_error(exc, operation=operation, reference=reference) from exc

    return _info_from_envelope(envelope, reference, operation=operation)


def _equal_or_conflict(
    stored: SigningCertificateInfo, certificate: SigningCertificate
) -> SigningCertificateInfo:
    """Return ``stored`` when it equals the record being saved, else raise a conflict."""
    if stored == certificate.info:
        return stored
    raise exceptions.KSeFCertificateStoreConflictError(
        "A different signing certificate record is already stored under this reference.",
        operation="save",
        reference=certificate.reference,
    )


def _envelope_bytes(
    reference: SigningCertificateRef, password: bytes, certificate: SigningCertificate
) -> bytes:
    """Return the record JSON for ``certificate``, its key encrypted under ``password``.

    Validity, serial number and the public-key fingerprint are left out on purpose: a
    reader recomputes them from the certificate, so a record cannot carry metadata its
    own certificate contradicts.
    """
    key_der = certificate.credentials.private_key.private_bytes(
        Encoding.DER, PrivateFormat.PKCS8, BestAvailableEncryption(password)
    )
    envelope = {
        "format": FORMAT,
        "version": VERSION,
        "environment": reference.environment.name.lower(),
        "fingerprint_sha256": reference.fingerprint_sha256,
        "certificate_type": certificate.info.certificate_type,
        "ksef_serial_number": certificate.info.ksef_serial_number,
        "certificate_der": _b64(
            certificate.credentials.certificate.public_bytes(Encoding.DER)
        ),
        "private_key_der": _b64(key_der),
    }
    return json.dumps(envelope, sort_keys=True).encode("utf-8")


def _b64(data: bytes) -> str:
    """Return *data* as the Base64 text a record stores."""
    return base64.b64encode(data).decode("ascii")


def _publish(
    env_dir: Path, path: Path, payload: bytes, reference: SigningCertificateRef
) -> bool:
    """Write ``payload`` to ``path`` atomically; say whether this call published it.

    The bytes go to a temporary file inside the environment directory, reach stable
    storage, and then reach ``path`` through ``os.link``, which publishes atomically
    and refuses to replace a record another writer put there first. ``False`` means
    the record was already there and the caller has to compare it.

    Raises:
        KSeFCertificateStoreUnavailableError: If the temporary file, the link or the
            directory sync failed. After the link succeeded the record is on disk or
            is not, and the store cannot tell, so that error is ambiguous.
    """
    try:
        fd, temp_name = tempfile.mkstemp(
            dir=env_dir, prefix=_TEMP_PREFIX, suffix=_SUFFIX
        )
    except OSError as exc:
        raise _os_error(exc, operation="save", reference=reference) from exc

    try:
        try:
            _write_all(fd, payload)
            os.fsync(fd)
        except OSError as exc:
            raise _os_error(exc, operation="save", reference=reference) from exc
        finally:
            os.close(fd)

        try:
            os.link(temp_name, path)
        except FileExistsError:
            return False
        except OSError as exc:
            raise _os_error(exc, operation="save", reference=reference) from exc

        try:
            _sync_dir(env_dir)
        except OSError as exc:
            raise _os_error(
                exc,
                operation="save",
                reference=reference,
                outcome_ambiguous=True,
            ) from exc
    finally:
        _discard(temp_name)

    return True


def _write_all(fd: int, payload: bytes) -> None:
    """Write every byte of *payload* to the open file ``fd``."""
    written = 0
    while written < len(payload):
        written += os.write(fd, payload[written:])


def _sync_dir(env_dir: Path) -> None:
    """Flush ``env_dir`` itself, so a fresh link survives a power loss.

    POSIX only: Windows has no directory handle to flush.
    """
    if os.name == "nt":
        return
    fd = os.open(env_dir, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _discard(temp_name: str) -> None:
    """Remove a temporary file, ignoring one that is already gone.

    This stays quiet on purpose: a leftover temporary file is untidy, while the error
    that made us clean up is the one the caller needs.
    """
    try:
        os.unlink(temp_name)
    except OSError:
        pass


def _os_error(
    exc: OSError,
    *,
    operation: str,
    reference: SigningCertificateRef | None,
    outcome_ambiguous: bool = False,
) -> exceptions.KSeFCertificateStoreError:
    """Return the store error for an OS failure while running ``operation``.

    A permission failure is the application's own doing in the files around this
    store, so it reads as an access error; every other OS failure says the storage
    itself could not take the call. File paths are not secret, so callers chain the
    original error: which file and which system call is what makes these diagnosable.
    """
    if isinstance(exc, PermissionError):
        return exceptions.KSeFCertificateStoreAccessError(
            "The store's files are not accessible to this process.",
            operation=operation,
            reference=reference,
            outcome_ambiguous=outcome_ambiguous,
        )
    return exceptions.KSeFCertificateStoreUnavailableError(
        f"The store could not complete {operation}() "
        f"({exc.strerror or type(exc).__name__}).",
        operation=operation,
        reference=reference,
        outcome_ambiguous=outcome_ambiguous,
    )
