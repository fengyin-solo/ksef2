"""The filesystem signing-certificate stores: their contract, their format, their files.

Every case that only needs the protocol runs twice, once per flavour, through the
shared store contract. The rest check what this backend promises on top of it: one
encrypted record per certificate on disk, an atomic write, owner-only files, and which
error each broken situation turns into.

The corruption cases each rewrite a record into a shape that cannot be read for a known
reason -- a byte count that no longer adds up, a version that does not exist yet -- so
none of them rests on a random key or a lucky padding failure.
"""

import base64
import concurrent.futures
import errno
import json
import os
import stat
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
import pytest

from ksef2._certificate_stores import _filesystem_ops
from ksef2._certificate_stores.async_filesystem import (
    AsyncFilesystemSigningCertificateStore,
)
from ksef2._certificate_stores.filesystem import FilesystemSigningCertificateStore
from ksef2._config import Environment
from ksef2._core.exceptions import (
    KSeFArgumentError,
    KSeFCertificateStoreAccessError,
    KSeFCertificateStoreConflictError,
    KSeFCertificateStoreMaterialError,
    KSeFCertificateStoreUnavailableError,
)
from ksef2._domain.models.signing_certificates import (
    SigningCertificate,
    SigningCertificateInfo,
    SigningCertificateRef,
)
from ksef2._domain.models.xades import XAdESCredentials
from tests.unit.certificate_stores.contract import (
    AsyncSigningStoreContract,
    SyncSigningStoreContract,
    _assert_loaded_pair_matches,
    make_record,
    pair,
)
from tests.unit.support.xades_material import key_der

requires_unchecked_types = pytest.mark.skipif(
    bool(os.environ.get("KSEF2_RUNTIME_CHECKS")),
    reason="beartype rejects the out-of-contract value before the guard runs",
)

posix_only = pytest.mark.skipif(
    os.name == "nt", reason="POSIX file modes and symbolic links"
)

PASSWORD = b"correct horse battery staple"
"""The password every record written by this file is protected with."""


def provider(reference: SigningCertificateRef) -> bytes:
    """Return the password protecting the records written in this file."""
    return PASSWORD


class ExplodingProvider:
    """A password source that says so, and counts the times it was asked."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, reference: SigningCertificateRef) -> bytes:
        self.calls += 1
        raise AssertionError("the store must not ask for a password here")


def env_dir(store: Any, environment: Environment) -> Path:
    """Return the directory holding one environment's records."""
    return store.root / environment.name.lower()


def record_file(store: Any, record: SigningCertificate) -> Path:
    """Return the file holding one record, by the layout the store promises."""
    reference = record.reference
    return (
        env_dir(store, reference.environment) / f"{reference.fingerprint_sha256}.json"
    )


def read_envelope(path: Path) -> dict[str, Any]:
    """Return the JSON object stored at ``path``."""
    envelope: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return envelope


def tamper(path: Path, **changes: object) -> None:
    """Rewrite the record at ``path`` with ``changes`` applied to it."""
    envelope = read_envelope(path)
    envelope.update(changes)
    path.write_text(json.dumps(envelope, sort_keys=True), encoding="utf-8")


def leftovers(directory: Path) -> list[str]:
    """Return the hidden names left in ``directory``, which should be none."""
    return [entry.name for entry in directory.iterdir() if entry.name.startswith(".")]


def unencrypted_der(key: rsa.RSAPrivateKey) -> bytes:
    """Return *key* as the PKCS#8 DER an unencrypted record would have held."""
    return key.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())


@pytest.fixture
def store(tmp_path: Path) -> FilesystemSigningCertificateStore:
    """Return an empty sync store on a directory that does not exist yet."""
    return FilesystemSigningCertificateStore(
        tmp_path / "store", password_provider=provider
    )


@pytest.fixture
def record() -> SigningCertificate:
    """Return a TEST record, generated once per test that asks for one."""
    key, certificate = pair("rsa")
    return make_record(key, certificate, Environment.TEST)


@pytest.fixture
def stored(
    store: FilesystemSigningCertificateStore, record: SigningCertificate
) -> SigningCertificate:
    """Return ``record`` as saved into ``store``."""
    store.save(record)
    return record


@pytest.fixture
def other_store(
    tmp_path: Path,
) -> FilesystemSigningCertificateStore:
    """Return a sync store on a root no other case in this test touches."""
    return FilesystemSigningCertificateStore(
        tmp_path / "elsewhere", password_provider=provider
    )


class TestFilesystemSigningCertificateStore(SyncSigningStoreContract):
    # The contract's cases call ``make_store()`` without a fixture of their own, so
    # the autouse fixture below hands each test its directory through this attribute.
    _root: Path = Path()

    @pytest.fixture(autouse=True)
    def _store_root(self, tmp_path: Path) -> None:
        """Give every case here, contract cases included, a directory of its own."""
        self._root = tmp_path / "store"

    def make_store(self) -> FilesystemSigningCertificateStore:
        return FilesystemSigningCertificateStore(self._root, password_provider=provider)

    def test_the_stored_pair_survives_a_restart(self) -> None:
        key, certificate = pair("ec")
        record = make_record(
            key, certificate, Environment.TEST, certificate_type="offline"
        )
        self.make_store().save(record)

        reopened = self.make_store()

        loaded = reopened.load(record.reference)
        _assert_loaded_pair_matches(loaded, record)
        assert [
            info.reference for info in reopened.list(environment=Environment.TEST)
        ] == [record.reference]

    def test_listing_needs_no_password(self) -> None:
        record = make_record(*pair("rsa"), Environment.TEST)
        self.make_store().save(record)

        asked_for_a_password = ExplodingProvider()
        store = FilesystemSigningCertificateStore(
            self._root, password_provider=asked_for_a_password
        )

        assert [
            info.reference for info in store.list(environment=Environment.TEST)
        ] == [record.reference]
        assert asked_for_a_password.calls == 0

    def test_saving_an_equal_record_again_needs_no_password(self) -> None:
        record = make_record(*pair("rsa"), Environment.TEST)
        self.make_store().save(record)

        asked_for_a_password = ExplodingProvider()
        store = FilesystemSigningCertificateStore(
            self._root, password_provider=asked_for_a_password
        )

        assert store.save(record) == record.info
        assert asked_for_a_password.calls == 0

    def test_the_root_directory_is_made_when_missing(self, tmp_path: Path) -> None:
        root = tmp_path / "deep" / "store"

        store = FilesystemSigningCertificateStore(root, password_provider=provider)

        assert store.root == root
        assert root.is_dir()

    @requires_unchecked_types
    def test_the_root_must_be_a_path(self, tmp_path: Path) -> None:
        with pytest.raises(KSeFArgumentError, match="root must be a pathlib.Path"):
            FilesystemSigningCertificateStore(
                str(tmp_path / "store"),  # pyright: ignore[reportArgumentType]
                password_provider=provider,
            )

    @requires_unchecked_types
    def test_the_password_source_must_be_callable(self, tmp_path: Path) -> None:
        with pytest.raises(
            KSeFArgumentError, match="password_provider must be callable"
        ):
            FilesystemSigningCertificateStore(
                tmp_path / "store",
                password_provider="not callable",  # pyright: ignore[reportArgumentType]
            )

    def test_the_repr_names_the_root_and_never_the_provider(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "store"

        text = repr(FilesystemSigningCertificateStore(root, password_provider=provider))

        assert text == f"FilesystemSigningCertificateStore(root={str(root)!r})"
        assert PASSWORD.decode("ascii") not in text
        assert "provider" not in text
        assert "PRIVATE KEY" not in text


class TestAsyncFilesystemSigningCertificateStore(AsyncSigningStoreContract):
    # The contract's cases call ``make_store()`` without a fixture of their own, so
    # the autouse fixture below hands each test its directory through this attribute.
    _root: Path = Path()

    @pytest.fixture(autouse=True)
    def _store_root(self, tmp_path: Path) -> None:
        """Give every case here, contract cases included, a directory of its own."""
        self._root = tmp_path / "store"

    def make_store(self) -> AsyncFilesystemSigningCertificateStore:
        return AsyncFilesystemSigningCertificateStore(
            self._root, password_provider=provider
        )

    async def test_the_stored_pair_survives_a_restart(self) -> None:
        key, certificate = pair("ec")
        record = make_record(
            key, certificate, Environment.TEST, certificate_type="offline"
        )
        await self.make_store().save(record)

        reopened = self.make_store()

        loaded = await reopened.load(record.reference)
        _assert_loaded_pair_matches(loaded, record)
        assert [
            info.reference for info in await reopened.list(environment=Environment.TEST)
        ] == [record.reference]

    async def test_listing_needs_no_password(self) -> None:
        record = make_record(*pair("rsa"), Environment.TEST)
        await self.make_store().save(record)

        asked_for_a_password = ExplodingProvider()
        store = AsyncFilesystemSigningCertificateStore(
            self._root, password_provider=asked_for_a_password
        )

        assert [
            info.reference for info in await store.list(environment=Environment.TEST)
        ] == [record.reference]
        assert asked_for_a_password.calls == 0

    async def test_saving_an_equal_record_again_needs_no_password(self) -> None:
        record = make_record(*pair("rsa"), Environment.TEST)
        await self.make_store().save(record)

        asked_for_a_password = ExplodingProvider()
        store = AsyncFilesystemSigningCertificateStore(
            self._root, password_provider=asked_for_a_password
        )

        assert await store.save(record) == record.info
        assert asked_for_a_password.calls == 0

    async def test_the_record_work_never_runs_on_the_event_loop_thread(self) -> None:
        asked_from: list[int] = []

        def provider_in_a_worker_thread(reference: SigningCertificateRef) -> bytes:
            asked_from.append(threading.get_ident())
            return PASSWORD

        store = AsyncFilesystemSigningCertificateStore(
            self._root, password_provider=provider_in_a_worker_thread
        )
        record = make_record(*pair("rsa"), Environment.TEST)
        waiting_thread = threading.get_ident()

        await store.save(record)
        await store.load(record.reference)

        assert len(asked_from) == 2, "save() and load() each ask the provider once"
        assert all(asked != waiting_thread for asked in asked_from), (
            "the blocking file and crypto work has to leave the event loop's thread"
        )

    async def test_the_root_directory_is_made_when_missing(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "deep" / "store"

        store = AsyncFilesystemSigningCertificateStore(root, password_provider=provider)

        assert store.root == root
        assert root.is_dir()

    @requires_unchecked_types
    def test_the_root_must_be_a_path(self, tmp_path: Path) -> None:
        with pytest.raises(KSeFArgumentError, match="root must be a pathlib.Path"):
            AsyncFilesystemSigningCertificateStore(
                str(tmp_path / "store"),  # pyright: ignore[reportArgumentType]
                password_provider=provider,
            )

    @requires_unchecked_types
    def test_the_password_source_must_be_callable(self, tmp_path: Path) -> None:
        with pytest.raises(
            KSeFArgumentError, match="password_provider must be callable"
        ):
            AsyncFilesystemSigningCertificateStore(
                tmp_path / "store",
                password_provider="not callable",  # pyright: ignore[reportArgumentType]
            )

    def test_the_repr_names_the_root_and_never_the_provider(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "store"

        text = repr(
            AsyncFilesystemSigningCertificateStore(root, password_provider=provider)
        )

        assert text == f"AsyncFilesystemSigningCertificateStore(root={str(root)!r})"
        assert PASSWORD.decode("ascii") not in text
        assert "provider" not in text


class TestFilesystemRecordFormat:
    def test_the_record_holds_the_certificate_and_an_encrypted_key(
        self, store: FilesystemSigningCertificateStore, stored: SigningCertificate
    ) -> None:
        path = record_file(store, stored)

        envelope = read_envelope(path)

        assert path == (
            store.root / "test" / f"{stored.reference.fingerprint_sha256}.json"
        )
        assert set(envelope) == {
            "format",
            "version",
            "environment",
            "fingerprint_sha256",
            "certificate_type",
            "ksef_serial_number",
            "certificate_der",
            "private_key_der",
        }
        assert envelope["format"] == _filesystem_ops.FORMAT
        assert envelope["version"] == _filesystem_ops.VERSION
        assert envelope["environment"] == "test"
        assert envelope["fingerprint_sha256"] == stored.reference.fingerprint_sha256
        assert envelope["certificate_type"] is None
        assert envelope["ksef_serial_number"] is None

    def test_the_record_holds_no_plaintext_key_and_no_password(
        self, store: FilesystemSigningCertificateStore, stored: SigningCertificate
    ) -> None:
        path = record_file(store, stored)
        key = stored.credentials.private_key
        assert isinstance(key, rsa.RSAPrivateKey)
        plaintext = unencrypted_der(key)
        text = path.read_text(encoding="utf-8")

        assert "PRIVATE KEY" not in text
        assert base64.b64encode(plaintext).decode("ascii") not in text
        assert PASSWORD.decode("ascii") not in text
        assert (
            base64.b64decode(str(read_envelope(path)["private_key_der"])) != plaintext
        )

    def test_the_record_holds_the_certificate_it_is_named_for(
        self, store: FilesystemSigningCertificateStore, stored: SigningCertificate
    ) -> None:
        envelope = read_envelope(record_file(store, stored))

        certificate = x509.load_der_x509_certificate(
            base64.b64decode(str(envelope["certificate_der"]))
        )

        assert certificate.public_bytes(Encoding.DER) == (
            stored.credentials.certificate.public_bytes(Encoding.DER)
        )

    def test_the_record_keeps_the_metadata_the_application_added(
        self, store: FilesystemSigningCertificateStore
    ) -> None:
        key, certificate = pair("ec")
        record = make_record(
            key,
            certificate,
            Environment.DEMO,
            certificate_type="authentication",
            ksef_serial_number="0123456789ABCDEF",
        )

        store.save(record)

        envelope = read_envelope(record_file(store, record))
        assert envelope["environment"] == "demo"
        assert envelope["certificate_type"] == "authentication"
        assert envelope["ksef_serial_number"] == "0123456789ABCDEF"
        assert env_dir(store, Environment.DEMO).is_dir()
        assert list(store.list(environment=Environment.DEMO)) == [record.info]


class TestFilesystemRecordMaterial:
    @pytest.fixture
    def path(
        self,
        store: FilesystemSigningCertificateStore,
        stored: SigningCertificate,
    ) -> Path:
        return record_file(store, stored)

    def test_bytes_that_are_not_json_stop_a_load(
        self,
        store: FilesystemSigningCertificateStore,
        stored: SigningCertificate,
        path: Path,
    ) -> None:
        path.write_bytes(b"not json")

        with pytest.raises(KSeFCertificateStoreMaterialError) as caught:
            store.load(stored.reference)

        assert caught.value.operation == "load"
        assert caught.value.reference == stored.reference

    def test_a_record_of_another_format_is_refused(
        self,
        store: FilesystemSigningCertificateStore,
        stored: SigningCertificate,
        path: Path,
    ) -> None:
        tamper(path, format="some-other-tool")

        with pytest.raises(KSeFCertificateStoreMaterialError, match="unknown format"):
            store.load(stored.reference)

    def test_an_unsupported_version_is_refused_and_left_untouched(
        self,
        store: FilesystemSigningCertificateStore,
        stored: SigningCertificate,
        path: Path,
    ) -> None:
        tamper(path, version=2)
        before = path.read_bytes()

        with pytest.raises(
            KSeFCertificateStoreMaterialError,
            match="Unsupported signing certificate record version 2.",
        ) as caught:
            store.load(stored.reference)

        assert caught.value.operation == "load"
        assert path.read_bytes() == before, (
            "a record in a version this SDK cannot write must not be rewritten"
        )

    def test_a_record_claiming_another_fingerprint_is_refused(
        self,
        store: FilesystemSigningCertificateStore,
        stored: SigningCertificate,
        path: Path,
    ) -> None:
        tamper(path, fingerprint_sha256="a" * 64)

        with pytest.raises(KSeFCertificateStoreMaterialError, match="fingerprint"):
            store.load(stored.reference)

    def test_a_record_named_for_another_certificate_is_refused(
        self,
        store: FilesystemSigningCertificateStore,
        stored: SigningCertificate,
        path: Path,
    ) -> None:
        other = SigningCertificateRef(
            environment=Environment.TEST, fingerprint_sha256="b" * 64
        )
        path.rename(
            env_dir(store, Environment.TEST) / f"{other.fingerprint_sha256}.json"
        )

        with pytest.raises(KSeFCertificateStoreMaterialError, match="fingerprint"):
            store.load(other)

    def test_a_private_key_of_the_wrong_length_is_refused(
        self,
        store: FilesystemSigningCertificateStore,
        stored: SigningCertificate,
        path: Path,
    ) -> None:
        encrypted = base64.b64decode(str(read_envelope(path)["private_key_der"]))
        tamper(path, private_key_der=base64.b64encode(encrypted[:-1]).decode("ascii"))

        with pytest.raises(
            KSeFCertificateStoreMaterialError, match="could not be decrypted or parsed"
        ):
            store.load(stored.reference)

    def test_a_private_key_issued_for_another_certificate_is_refused(
        self,
        store: FilesystemSigningCertificateStore,
        stored: SigningCertificate,
        path: Path,
    ) -> None:
        stranger = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        tamper(
            path,
            private_key_der=base64.b64encode(
                key_der(stranger, password=PASSWORD)
            ).decode("ascii"),
        )

        with pytest.raises(
            KSeFCertificateStoreMaterialError,
            match="does not belong to the stored certificate",
        ):
            store.load(stored.reference)

    def test_a_record_from_an_unknown_environment_is_refused(
        self,
        store: FilesystemSigningCertificateStore,
        stored: SigningCertificate,
        path: Path,
    ) -> None:
        tamper(path, environment="staging")

        with pytest.raises(
            KSeFCertificateStoreMaterialError, match="unknown KSeF environment"
        ):
            store.load(stored.reference)

    def test_a_record_from_another_environment_is_refused(
        self,
        store: FilesystemSigningCertificateStore,
        stored: SigningCertificate,
        path: Path,
    ) -> None:
        tamper(path, environment="demo")

        with pytest.raises(KSeFCertificateStoreMaterialError, match="environment"):
            store.load(stored.reference)

    def test_a_corrupt_record_stops_a_listing_rather_than_vanishing_from_it(
        self,
        store: FilesystemSigningCertificateStore,
        stored: SigningCertificate,
        path: Path,
    ) -> None:
        path.write_bytes(b"{")

        with pytest.raises(KSeFCertificateStoreMaterialError) as caught:
            store.list(environment=Environment.TEST)

        assert caught.value.operation == "list"
        assert caught.value.reference == stored.reference

    def test_a_record_that_vanishes_mid_listing_is_stepped_over(
        self,
        store: FilesystemSigningCertificateStore,
        stored: SigningCertificate,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        listed_names = _filesystem_ops._record_names
        vanished = f"{'0' * 64}.json"

        def names_including_the_vanished_record(directory: Path) -> list[str]:
            return [*listed_names(directory), vanished]

        monkeypatch.setattr(
            _filesystem_ops, "_record_names", names_including_the_vanished_record
        )

        assert list(store.list(environment=Environment.TEST)) == [stored.info]

    def test_a_damaged_record_is_refused_by_listing_too(
        self,
        store: FilesystemSigningCertificateStore,
        stored: SigningCertificate,
        path: Path,
    ) -> None:
        tamper(path, version=2)

        with pytest.raises(
            KSeFCertificateStoreMaterialError, match="Unsupported signing certificate"
        ):
            store.list(environment=Environment.TEST)


class TestFilesystemPasswordSource:
    def test_an_empty_password_is_an_access_error_on_save(self, tmp_path: Path) -> None:
        store = FilesystemSigningCertificateStore(
            tmp_path / "store", password_provider=lambda reference: b""
        )

        with pytest.raises(
            KSeFCertificateStoreAccessError, match="returned an empty password"
        ) as caught:
            store.save(make_record(*pair("rsa"), Environment.TEST))

        assert caught.value.operation == "save"

    def test_an_empty_password_is_an_access_error_on_load(
        self, tmp_path: Path, record: SigningCertificate
    ) -> None:
        FilesystemSigningCertificateStore(
            tmp_path / "store", password_provider=provider
        ).save(record)
        store = FilesystemSigningCertificateStore(
            tmp_path / "store", password_provider=lambda reference: b""
        )

        with pytest.raises(
            KSeFCertificateStoreAccessError, match="returned an empty password"
        ) as caught:
            store.load(record.reference)

        assert caught.value.operation == "load"

    def test_a_password_that_is_not_bytes_is_an_argument_error(
        self, tmp_path: Path
    ) -> None:
        store = FilesystemSigningCertificateStore(
            tmp_path / "store",
            password_provider=lambda reference: "text",  # pyright: ignore[reportArgumentType]
        )

        with pytest.raises(KSeFArgumentError, match="must return bytes"):
            store.save(make_record(*pair("rsa"), Environment.TEST))

    def test_a_password_source_that_breaks_is_reported_as_it_is(
        self, tmp_path: Path, record: SigningCertificate
    ) -> None:
        FilesystemSigningCertificateStore(
            tmp_path / "store", password_provider=provider
        ).save(record)

        def failing_provider(reference: SigningCertificateRef) -> bytes:
            raise RuntimeError("boom")

        store = FilesystemSigningCertificateStore(
            tmp_path / "store", password_provider=failing_provider
        )
        other = make_record(*pair("ec"), Environment.TEST)

        with pytest.raises(RuntimeError, match="boom"):
            store.save(other)

        with pytest.raises(RuntimeError, match="boom"):
            store.load(record.reference)


class TestFilesystemFiles:
    @posix_only
    def test_records_and_environment_directories_are_owner_only(
        self, store: FilesystemSigningCertificateStore, stored: SigningCertificate
    ) -> None:
        path = record_file(store, stored)

        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(env_dir(store, Environment.TEST).stat().st_mode) == 0o700

    @posix_only
    def test_a_link_where_a_record_belongs_is_not_read(
        self,
        store: FilesystemSigningCertificateStore,
        record: SigningCertificate,
        other_store: FilesystemSigningCertificateStore,
    ) -> None:
        other_record = make_record(*pair("ec"), Environment.TEST)
        other_store.save(other_record)
        target = record_file(other_store, other_record)
        directory = env_dir(store, Environment.TEST)
        directory.mkdir(mode=0o700)
        (directory / f"{record.reference.fingerprint_sha256}.json").symlink_to(target)

        with pytest.raises(
            KSeFCertificateStoreAccessError, match="symbolic link to a record"
        ) as caught:
            store.load(record.reference)

        assert caught.value.operation == "load"
        assert target.exists(), "the record a link pointed at has to be intact"

    @posix_only
    def test_a_link_where_a_record_belongs_is_not_listed_either(
        self,
        store: FilesystemSigningCertificateStore,
        other_store: FilesystemSigningCertificateStore,
    ) -> None:
        other_record = make_record(*pair("ec"), Environment.TEST)
        other_store.save(other_record)
        directory = env_dir(store, Environment.TEST)
        directory.mkdir(mode=0o700)
        (directory / f"{other_record.reference.fingerprint_sha256}.json").symlink_to(
            record_file(other_store, other_record)
        )

        with pytest.raises(
            KSeFCertificateStoreAccessError, match="symbolic link to a record"
        ) as caught:
            store.list(environment=Environment.TEST)

        assert caught.value.operation == "list"

    @posix_only
    def test_a_link_where_an_environment_directory_belongs_is_not_used(
        self,
        tmp_path: Path,
        record: SigningCertificate,
        other_store: FilesystemSigningCertificateStore,
    ) -> None:
        other_store.save(record)
        root = tmp_path / "store"
        root.mkdir()
        (root / "test").symlink_to(env_dir(other_store, Environment.TEST))
        store = FilesystemSigningCertificateStore(root, password_provider=provider)

        with pytest.raises(
            KSeFCertificateStoreAccessError, match="environment directory"
        ) as caught:
            store.save(record)

        assert caught.value.operation == "save"
        assert list(other_store.list(environment=Environment.TEST)) == [record.info]

    @posix_only
    def test_a_link_where_an_environment_directory_belongs_stops_every_operation(
        self,
        tmp_path: Path,
        record: SigningCertificate,
        other_store: FilesystemSigningCertificateStore,
    ) -> None:
        other_store.save(record)
        root = tmp_path / "store"
        root.mkdir()
        (root / "test").symlink_to(env_dir(other_store, Environment.TEST))
        store = FilesystemSigningCertificateStore(root, password_provider=provider)
        operations: list[tuple[str, Callable[[], object]]] = [
            ("load", lambda: store.load(record.reference)),
            ("list", lambda: store.list(environment=Environment.TEST)),
            ("delete", lambda: store.delete(record.reference)),
        ]

        for operation, call in operations:
            with pytest.raises(
                KSeFCertificateStoreAccessError, match="environment directory"
            ) as caught:
                call()
            assert caught.value.operation == operation

    @posix_only
    def test_deleting_a_record_takes_the_link_and_not_what_it_points_at(
        self,
        store: FilesystemSigningCertificateStore,
        other_store: FilesystemSigningCertificateStore,
    ) -> None:
        other_record = make_record(*pair("ec"), Environment.TEST)
        other_store.save(other_record)
        target = record_file(other_store, other_record)
        directory = env_dir(store, Environment.TEST)
        directory.mkdir(mode=0o700)
        link = directory / f"{other_record.reference.fingerprint_sha256}.json"
        link.symlink_to(target)

        assert store.delete(other_record.reference) is True

        assert link.is_symlink() is False
        assert target.exists()


class TestFilesystemPublication:
    def test_a_full_disk_is_reported_as_unavailable(
        self,
        store: FilesystemSigningCertificateStore,
        record: SigningCertificate,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _fail_os_call(
            monkeypatch, "link", OSError(errno.ENOSPC, "No space left on device")
        )

        with pytest.raises(KSeFCertificateStoreUnavailableError) as caught:
            store.save(record)

        assert caught.value.operation == "save"
        assert caught.value.outcome_ambiguous is False
        assert not record_file(store, record).exists()
        assert leftovers(env_dir(store, Environment.TEST)) == []

    def test_unreadable_files_are_an_access_error(
        self,
        store: FilesystemSigningCertificateStore,
        record: SigningCertificate,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _fail_os_call(
            monkeypatch, "link", PermissionError(errno.EACCES, "Permission denied")
        )

        with pytest.raises(KSeFCertificateStoreAccessError) as caught:
            store.save(record)

        assert caught.value.operation == "save"
        assert caught.value.outcome_ambiguous is False
        assert not record_file(store, record).exists()
        assert leftovers(env_dir(store, Environment.TEST)) == []

    def test_a_failing_flush_before_the_record_exists_is_not_ambiguous(
        self,
        store: FilesystemSigningCertificateStore,
        record: SigningCertificate,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _fail_os_call(
            monkeypatch, "fsync", OSError(errno.EIO, "I/O error"), on_calls=(1,)
        )

        with pytest.raises(KSeFCertificateStoreUnavailableError) as caught:
            store.save(record)

        assert caught.value.outcome_ambiguous is False
        assert not record_file(store, record).exists()
        assert leftovers(env_dir(store, Environment.TEST)) == []

    @posix_only
    def test_a_failing_directory_flush_leaves_the_caller_uncertain(
        self,
        store: FilesystemSigningCertificateStore,
        record: SigningCertificate,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The first flush settles the temporary file and the second settles the
        # directory holding the link that published the record. Only the second one
        # can fail on a record that is already visible.
        _fail_os_call(
            monkeypatch, "fsync", OSError(errno.EIO, "I/O error"), on_calls=(2,)
        )

        with pytest.raises(KSeFCertificateStoreUnavailableError) as caught:
            store.save(record)

        assert caught.value.outcome_ambiguous is True
        assert record_file(store, record).exists()
        assert leftovers(env_dir(store, Environment.TEST)) == []

        monkeypatch.undo()

        assert store.save(record) == record.info

    def test_a_conflict_leaves_one_record_and_no_temporary_file(
        self, store: FilesystemSigningCertificateStore, stored: SigningCertificate
    ) -> None:
        key = stored.credentials.private_key
        assert isinstance(key, rsa.RSAPrivateKey)
        other = SigningCertificate(
            XAdESCredentials(stored.credentials.certificate, key),
            environment=Environment.TEST,
            certificate_type="authentication",
        )
        assert other.reference == stored.reference

        with pytest.raises(KSeFCertificateStoreConflictError):
            store.save(other)

        assert list(store.list(environment=Environment.TEST)) == [stored.info]
        assert leftovers(env_dir(store, Environment.TEST)) == []

    def test_an_equal_save_keeps_one_file_and_no_temporary_file(
        self, store: FilesystemSigningCertificateStore, record: SigningCertificate
    ) -> None:
        store.save(record)

        store.save(
            SigningCertificate(
                XAdESCredentials(
                    record.credentials.certificate,
                    record.credentials.private_key,
                ),
                environment=Environment.TEST,
            )
        )

        assert list(env_dir(store, Environment.TEST).iterdir()) == [
            record_file(store, record)
        ]
        assert leftovers(env_dir(store, Environment.TEST)) == []


class TestFilesystemConcurrency:
    def test_eight_writers_of_one_record_leave_one_record(
        self, store: FilesystemSigningCertificateStore
    ) -> None:
        key, certificate = pair("rsa")
        record = make_record(
            key, certificate, Environment.TEST, certificate_type="offline"
        )

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            infos = list(pool.map(lambda _: store.save(record), range(8)))

        assert all(info == record.info for info in infos)
        assert list(env_dir(store, Environment.TEST).iterdir()) == [
            record_file(store, record)
        ]
        assert leftovers(env_dir(store, Environment.TEST)) == []

    def test_eight_writers_of_two_variants_keep_the_winner_and_report_the_rest(
        self, store: FilesystemSigningCertificateStore
    ) -> None:
        key, certificate = pair("rsa")
        authentication = make_record(
            key, certificate, Environment.TEST, certificate_type="authentication"
        )
        unannotated = make_record(key, certificate, Environment.TEST)
        assert authentication.reference == unannotated.reference
        assert authentication.info != unannotated.info
        writers = [
            authentication if index % 2 == 0 else unannotated for index in range(8)
        ]

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(_saved_or_raised(store), writers))

        kept = [
            outcome
            for outcome in outcomes
            if isinstance(outcome, SigningCertificateInfo)
        ]
        conflicts = [
            outcome
            for outcome in outcomes
            if isinstance(outcome, KSeFCertificateStoreConflictError)
        ]
        assert len(kept) + len(conflicts) == 8, (
            "every writer has to report one outcome of its save"
        )
        assert len(set(kept)) == 1, "exactly one variant may win the record"
        assert len(kept) == 4, (
            "the writers of the winning variant all get its metadata back"
        )
        assert len(conflicts) == 4, "the writers of the other variant report a conflict"
        winner = kept[0]
        assert winner is not None
        assert list(store.list(environment=Environment.TEST)) == [winner]
        assert store.load(winner.reference).info == winner
        assert leftovers(env_dir(store, Environment.TEST)) == []

    def test_the_losers_leave_the_winners_record_behind(
        self, store: FilesystemSigningCertificateStore
    ) -> None:
        key, certificate = pair("ec")
        writers = [
            make_record(key, certificate, Environment.TEST, certificate_type=kind)
            for kind in ("authentication", None, "offline")
        ]

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            outcomes = list(pool.map(_saved_or_raised(store), writers))

        kept = [
            outcome
            for outcome in outcomes
            if isinstance(outcome, SigningCertificateInfo)
        ]
        conflicts = [
            outcome
            for outcome in outcomes
            if isinstance(outcome, KSeFCertificateStoreConflictError)
        ]
        assert len(kept) == 1
        assert len(conflicts) == 2
        winner = kept[0]
        assert winner is not None
        assert store.load(winner.reference).info == winner
        assert list(env_dir(store, Environment.TEST).iterdir()) == [
            record_file(store, writers[0])
        ]


def _saved_or_raised(
    store: FilesystemSigningCertificateStore,
) -> Callable[[SigningCertificate], object]:
    """Return a callable saving one record, reporting what went wrong instead."""

    def save(record: SigningCertificate) -> object:
        try:
            return store.save(record)
        except Exception as exc:
            return exc

    return save


def _fail_os_call(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    error: OSError,
    *,
    on_calls: tuple[int, ...] | None = None,
) -> None:
    """Make ``os.<name>``, as the record operations call it, raise ``error``.

    ``on_calls`` numbers the calls that fail, counting from 1; the rest reach the
    function that was there before.
    """
    real = getattr(os, name)
    seen = 0

    def failing(*args: object, **kwargs: object) -> object:
        nonlocal seen
        seen += 1
        if on_calls is None or seen in on_calls:
            raise error
        return real(*args, **kwargs)

    monkeypatch.setattr(_filesystem_ops.os, name, failing)
