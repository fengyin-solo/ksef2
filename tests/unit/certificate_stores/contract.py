"""Shared save/load/list/delete contract every signing-certificate store must meet.

The classes here are not collected: their names do not start with ``Test``. A store
adapter gets the contract by subclassing ``SyncSigningStoreContract`` or
``AsyncSigningStoreContract`` and supplying ``make_store()``.
"""

import datetime
import functools
from typing import cast

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.serialization import Encoding
import pytest

from ksef2._certificate_stores.async_protocols import (
    AsyncSigningCertificateStoreProtocol,
)
from ksef2._certificate_stores.protocols import SigningCertificateStoreProtocol
from ksef2._config import Environment
from ksef2._core.exceptions import (
    KSeFCertificateStoreConflictError,
    KSeFCertificateStoreNotFoundError,
)
from ksef2._domain.models.certificates import CertificateTypeValue
from ksef2._domain.models.signing_certificates import (
    SigningCertificate,
    SigningCertificateInfo,
)
from ksef2._domain.models.xades import XAdESCredentials
from tests.unit.support import xades_material as material
from tests.unit.support.xades_material import TestKey

MIDDLE = datetime.datetime(2026, 5, 1, 12, tzinfo=datetime.UTC)


@functools.cache
def _key(kind: str = "rsa", label: str = "") -> TestKey:
    """Return a key per ``(kind, label)``, generated once per test session.

    RSA generation dominates the contract's run time, and every adapter reruns it.
    """
    if kind == "rsa":
        return rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return ec.generate_private_key(ec.SECP256R1())


def _certificate(
    key: TestKey, common_name: str, *, valid_from: datetime.datetime = MIDDLE
) -> x509.Certificate:
    return material.self_signed_with_validity(
        key,
        not_valid_before=valid_from,
        not_valid_after=valid_from + datetime.timedelta(days=365),
        common_name=common_name,
    )


def make_record(
    key: TestKey,
    certificate: x509.Certificate,
    environment: Environment,
    certificate_type: CertificateTypeValue | None = None,
    ksef_serial_number: str | None = None,
) -> SigningCertificate:
    return SigningCertificate(
        XAdESCredentials(certificate, key),
        environment=environment,
        certificate_type=certificate_type,
        ksef_serial_number=ksef_serial_number,
    )


def pair(kind: str) -> tuple[TestKey, x509.Certificate]:
    key = _key(kind, "pair")
    return key, _certificate(key, f"ksef2 {kind} contract")


def _listing_records() -> tuple[list[SigningCertificate], SigningCertificate]:
    """Return the TEST records a ``list()`` case expects, plus one DEMO record.

    Two of the TEST records share one ``valid_from`` so the fingerprint decides
    their order, and one is expired so a store cannot quietly filter it out.
    """
    early_key, twin_key, late_key, expired_key, demo_key = (
        _key("rsa", "early"),
        _key("ec", "twin"),
        _key("rsa", "late"),
        _key("rsa", "expired"),
        _key("ec", "demo"),
    )
    late_from = MIDDLE + datetime.timedelta(days=90)
    expired = material.self_signed_with_validity(
        expired_key,
        not_valid_before=MIDDLE - datetime.timedelta(days=400),
        not_valid_after=MIDDLE - datetime.timedelta(days=30),
        common_name="ksef2 expired",
    )
    held = [
        make_record(
            early_key, _certificate(early_key, "ksef2 early"), Environment.TEST
        ),
        make_record(
            twin_key,
            _certificate(twin_key, "ksef2 twin"),
            Environment.TEST,
            certificate_type="offline",
        ),
        make_record(
            late_key,
            _certificate(late_key, "ksef2 late", valid_from=late_from),
            Environment.TEST,
            certificate_type="authentication",
        ),
        make_record(expired_key, expired, Environment.TEST),
    ]
    demo = make_record(demo_key, _certificate(demo_key, "ksef2 demo"), Environment.DEMO)
    return held, demo


def _expected_listing(held: list[SigningCertificate]) -> list[SigningCertificateInfo]:
    return sorted(
        (record.info for record in held),
        key=lambda info: (info.valid_from, info.reference.fingerprint_sha256),
    )


def _assert_loaded_pair_matches(
    loaded: SigningCertificate, original: SigningCertificate
) -> None:
    """Check the loaded record, then sign with its key and verify with its certificate."""
    assert loaded.info == original.info
    assert loaded.credentials.certificate.public_bytes(Encoding.DER) == (
        original.credentials.certificate.public_bytes(Encoding.DER)
    )

    payload = b"signing store contract"
    private_key = loaded.credentials.private_key
    issued_with = loaded.credentials.certificate.public_key()

    if isinstance(private_key, rsa.RSAPrivateKey):
        public_key = cast("rsa.RSAPublicKey", issued_with)
        signature = private_key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
        public_key.verify(signature, payload, padding.PKCS1v15(), hashes.SHA256())
        return

    public_key = cast("ec.EllipticCurvePublicKey", issued_with)
    signature = private_key.sign(payload, ec.ECDSA(hashes.SHA256()))
    public_key.verify(signature, payload, ec.ECDSA(hashes.SHA256()))


def _assert_listing(
    listed: list[SigningCertificateInfo], held: list[SigningCertificate]
) -> None:
    assert [info.reference for info in listed] == [
        info.reference for info in _expected_listing(held)
    ], "list() must order by valid_from and then by fingerprint"
    assert all(info.reference.environment is Environment.TEST for info in listed), (
        "list() returned a record of another environment"
    )
    assert any(info.valid_to < MIDDLE for info in listed), (
        "list() left out an expired record"
    )


class SyncSigningStoreContract:
    """Every case a sync signing-certificate store has to pass.

    A subject supplies ``make_store()``; the cases themselves are shared with
    :class:`AsyncSigningStoreContract`.
    """

    def make_store(self) -> SigningCertificateStoreProtocol:
        """Return an empty store to run one case against.

        Raises:
            NotImplementedError: In the contract itself; a subject store supplies it.
        """
        raise NotImplementedError

    def test_it_satisfies_the_store_protocol(self) -> None:
        assert isinstance(self.make_store(), SigningCertificateStoreProtocol)

    @pytest.mark.parametrize("kind", ["rsa", "ec"])
    def test_save_then_load_returns_the_same_pair(self, kind: str) -> None:
        key, certificate = pair(kind)
        store = self.make_store()
        record = make_record(key, certificate, Environment.TEST)

        info = store.save(record)
        loaded = store.load(record.reference)

        assert info == record.info
        _assert_loaded_pair_matches(loaded, record)

    def test_saving_an_equal_record_twice_keeps_one(self) -> None:
        key, certificate = pair("rsa")
        store = self.make_store()
        record = make_record(
            key, certificate, Environment.TEST, certificate_type="offline"
        )

        first = store.save(record)
        second = store.save(
            make_record(key, certificate, Environment.TEST, certificate_type="offline")
        )

        assert first == second
        assert len(store.list(environment=Environment.TEST)) == 1

    def test_a_different_record_under_one_reference_is_a_conflict(self) -> None:
        key, certificate = pair("rsa")
        store = self.make_store()
        original = make_record(key, certificate, Environment.TEST)
        store.save(original)

        with pytest.raises(KSeFCertificateStoreConflictError) as caught:
            store.save(
                make_record(
                    key,
                    certificate,
                    Environment.TEST,
                    certificate_type="authentication",
                )
            )

        assert caught.value.operation == "save"
        assert caught.value.reference == original.reference
        assert store.load(original.reference).info == original.info
        assert len(store.list(environment=Environment.TEST)) == 1

    def test_loading_an_unknown_reference_names_the_load_that_failed(self) -> None:
        store = self.make_store()
        key, certificate = pair("rsa")
        missing = make_record(key, certificate, Environment.TEST).reference

        with pytest.raises(KSeFCertificateStoreNotFoundError) as caught:
            store.load(missing)

        assert caught.value.operation == "load"
        assert caught.value.reference == missing

    def test_list_filters_and_orders_the_records_of_one_environment(self) -> None:
        held, demo = _listing_records()
        store = self.make_store()
        for record in [*held, demo]:
            store.save(record)

        listed = list(store.list(environment=Environment.TEST))

        _assert_listing(listed, held)

        offline = list(
            store.list(environment=Environment.TEST, certificate_type="offline")
        )

        assert [info.reference for info in offline] == [
            info.reference for info in held[1:2]
        ], "list() did not filter by certificate_type"

    def test_delete_reports_whether_a_record_was_there(self) -> None:
        key, certificate = pair("rsa")
        store = self.make_store()
        record = make_record(key, certificate, Environment.TEST)
        store.save(record)

        assert store.delete(record.reference) is True
        assert store.delete(record.reference) is False

        with pytest.raises(KSeFCertificateStoreNotFoundError):
            store.load(record.reference)

    def test_one_certificate_in_two_environments_is_two_records(self) -> None:
        key, certificate = pair("rsa")
        store = self.make_store()
        test_record = make_record(key, certificate, Environment.TEST)
        demo_record = make_record(key, certificate, Environment.DEMO)

        assert test_record.reference != demo_record.reference
        store.save(test_record)

        assert store.delete(demo_record.reference) is False
        assert store.list(environment=Environment.DEMO) == ()
        store.save(demo_record)

        assert len(store.list(environment=Environment.TEST)) == 1
        assert len(store.list(environment=Environment.DEMO)) == 1
        assert store.load(demo_record.reference).info.reference.environment is (
            Environment.DEMO
        )


class AsyncSigningStoreContract:
    """Every case an async signing-certificate store has to pass.

    A subject supplies ``make_store()``; the cases mirror
    :class:`SyncSigningStoreContract` one for one.
    """

    def make_store(self) -> AsyncSigningCertificateStoreProtocol:
        """Return an empty store to run one case against.

        Raises:
            NotImplementedError: In the contract itself; a subject store supplies it.
        """
        raise NotImplementedError

    async def test_it_satisfies_the_store_protocol(self) -> None:
        assert isinstance(self.make_store(), AsyncSigningCertificateStoreProtocol)

    @pytest.mark.parametrize("kind", ["rsa", "ec"])
    async def test_save_then_load_returns_the_same_pair(self, kind: str) -> None:
        key, certificate = pair(kind)
        store = self.make_store()
        record = make_record(key, certificate, Environment.TEST)

        info = await store.save(record)
        loaded = await store.load(record.reference)

        assert info == record.info
        _assert_loaded_pair_matches(loaded, record)

    async def test_saving_an_equal_record_twice_keeps_one(self) -> None:
        key, certificate = pair("rsa")
        store = self.make_store()
        record = make_record(
            key, certificate, Environment.TEST, certificate_type="offline"
        )

        first = await store.save(record)
        second = await store.save(
            make_record(key, certificate, Environment.TEST, certificate_type="offline")
        )

        assert first == second
        assert len(await store.list(environment=Environment.TEST)) == 1

    async def test_a_different_record_under_one_reference_is_a_conflict(self) -> None:
        key, certificate = pair("rsa")
        store = self.make_store()
        original = make_record(key, certificate, Environment.TEST)
        await store.save(original)

        with pytest.raises(KSeFCertificateStoreConflictError) as caught:
            await store.save(
                make_record(
                    key,
                    certificate,
                    Environment.TEST,
                    certificate_type="authentication",
                )
            )

        assert caught.value.operation == "save"
        assert caught.value.reference == original.reference
        assert (await store.load(original.reference)).info == original.info
        assert len(await store.list(environment=Environment.TEST)) == 1

    async def test_loading_an_unknown_reference_names_the_load_that_failed(
        self,
    ) -> None:
        store = self.make_store()
        key, certificate = pair("rsa")
        missing = make_record(key, certificate, Environment.TEST).reference

        with pytest.raises(KSeFCertificateStoreNotFoundError) as caught:
            await store.load(missing)

        assert caught.value.operation == "load"
        assert caught.value.reference == missing

    async def test_list_filters_and_orders_the_records_of_one_environment(self) -> None:
        held, demo = _listing_records()
        store = self.make_store()
        for record in [*held, demo]:
            await store.save(record)

        listed = list(await store.list(environment=Environment.TEST))

        _assert_listing(listed, held)

        offline = list(
            await store.list(environment=Environment.TEST, certificate_type="offline")
        )

        assert [info.reference for info in offline] == [
            info.reference for info in held[1:2]
        ], "list() did not filter by certificate_type"

    async def test_delete_reports_whether_a_record_was_there(self) -> None:
        key, certificate = pair("rsa")
        store = self.make_store()
        record = make_record(key, certificate, Environment.TEST)
        await store.save(record)

        assert await store.delete(record.reference) is True
        assert await store.delete(record.reference) is False

        with pytest.raises(KSeFCertificateStoreNotFoundError):
            await store.load(record.reference)

    async def test_one_certificate_in_two_environments_is_two_records(self) -> None:
        key, certificate = pair("rsa")
        store = self.make_store()
        test_record = make_record(key, certificate, Environment.TEST)
        demo_record = make_record(key, certificate, Environment.DEMO)

        assert test_record.reference != demo_record.reference
        await store.save(test_record)

        assert await store.delete(demo_record.reference) is False
        assert await store.list(environment=Environment.DEMO) == ()
        await store.save(demo_record)

        assert len(await store.list(environment=Environment.TEST)) == 1
        assert len(await store.list(environment=Environment.DEMO)) == 1
        loaded = await store.load(demo_record.reference)
        assert loaded.info.reference.environment is Environment.DEMO
