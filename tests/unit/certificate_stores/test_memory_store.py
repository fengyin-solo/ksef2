"""The in-memory signing-certificate stores, run against the shared store contract."""

import concurrent.futures
import os

import pytest

from ksef2._certificate_stores.async_memory import AsyncInMemorySigningCertificateStore
from ksef2._certificate_stores.memory import InMemorySigningCertificateStore
from ksef2._config import Environment
from ksef2._core.exceptions import (
    KSeFArgumentError,
    KSeFCertificateStoreNotFoundError,
)
from tests.unit.certificate_stores.contract import (
    AsyncSigningStoreContract,
    SyncSigningStoreContract,
    make_record,
    pair,
)

requires_unchecked_types = pytest.mark.skipif(
    bool(os.environ.get("KSEF2_RUNTIME_CHECKS")),
    reason="beartype rejects the out-of-contract value before the guard runs",
)


class TestInMemorySigningCertificateStore(SyncSigningStoreContract):
    def make_store(self) -> InMemorySigningCertificateStore:
        return InMemorySigningCertificateStore()

    def test_the_repr_counts_records_and_shows_no_material(self) -> None:
        key, certificate = pair("rsa")
        store = self.make_store()

        assert repr(store) == "InMemorySigningCertificateStore(records=0)"
        store.save(make_record(key, certificate, Environment.TEST))

        assert repr(store) == "InMemorySigningCertificateStore(records=1)"
        assert "PRIVATE KEY" not in repr(store)

    @requires_unchecked_types
    def test_save_needs_a_record(self) -> None:
        with pytest.raises(KSeFArgumentError, match="needs a SigningCertificate"):
            self.make_store().save("not a record")  # pyright: ignore[reportArgumentType]

    def test_two_stores_hold_their_own_records(self) -> None:
        key, certificate = pair("rsa")
        first, second = self.make_store(), self.make_store()
        record = make_record(key, certificate, Environment.TEST)
        first.save(record)

        assert second.list(environment=Environment.TEST) == ()
        with pytest.raises(KSeFCertificateStoreNotFoundError):
            second.load(record.reference)

    def test_eight_threads_saving_one_record_all_see_the_same_metadata(self) -> None:
        key, certificate = pair("rsa")
        store = self.make_store()
        record = make_record(
            key, certificate, Environment.TEST, certificate_type="offline"
        )

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: store.save(record), range(8)))

        assert all(info == record.info for info in results)
        assert len(store.list(environment=Environment.TEST)) == 1


class TestAsyncInMemorySigningCertificateStore(AsyncSigningStoreContract):
    def make_store(self) -> AsyncInMemorySigningCertificateStore:
        return AsyncInMemorySigningCertificateStore()

    async def test_the_repr_counts_records_and_shows_no_material(self) -> None:
        key, certificate = pair("rsa")
        store = self.make_store()

        assert repr(store) == "AsyncInMemorySigningCertificateStore(records=0)"
        await store.save(make_record(key, certificate, Environment.TEST))

        assert repr(store) == "AsyncInMemorySigningCertificateStore(records=1)"
        assert "PRIVATE KEY" not in repr(store)

    @requires_unchecked_types
    async def test_save_needs_a_record(self) -> None:
        with pytest.raises(KSeFArgumentError, match="needs a SigningCertificate"):
            await self.make_store().save("not a record")  # pyright: ignore[reportArgumentType]

    async def test_two_stores_hold_their_own_records(self) -> None:
        key, certificate = pair("rsa")
        first, second = self.make_store(), self.make_store()
        record = make_record(key, certificate, Environment.TEST)
        await first.save(record)

        assert await second.list(environment=Environment.TEST) == ()
        with pytest.raises(KSeFCertificateStoreNotFoundError):
            await second.load(record.reference)
