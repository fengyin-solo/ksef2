import asyncio

import pytest

from ksef2._core.polling import async_poll_until, poll_until


class PollTimeoutError(Exception):
    pass


class PollTerminalError(Exception):
    pass


def test_poll_until_returns_first_non_retry_result() -> None:
    values = iter([0, 0, 1])
    sleeps: list[float] = []

    result = poll_until(
        operation=lambda: next(values),
        retry_predicate=lambda value: value < 1,
        poll_interval=0.25,
        max_attempts=3,
        timeout_error_factory=PollTimeoutError,
        sleep=sleeps.append,
    )

    assert result == 1
    assert sleeps == [0.25, 0.25]


def test_poll_until_converts_retry_exhaustion_to_timeout_error() -> None:
    with pytest.raises(PollTimeoutError):
        _ = poll_until(
            operation=lambda: 0,
            retry_predicate=lambda value: value < 1,
            poll_interval=0.25,
            max_attempts=2,
            timeout_error_factory=PollTimeoutError,
            sleep=lambda _: None,
        )


@pytest.mark.parametrize("max_attempts", [0, -1])
def test_poll_until_times_out_without_attempt_for_non_positive_max_attempts(
    max_attempts: int,
) -> None:
    def _operation() -> int:
        raise AssertionError("operation should not be called")

    with pytest.raises(PollTimeoutError):
        _ = poll_until(
            operation=_operation,
            retry_predicate=lambda value: value < 1,
            poll_interval=0.25,
            max_attempts=max_attempts,
            timeout_error_factory=PollTimeoutError,
            sleep=lambda _: None,
        )


def test_poll_until_propagates_operation_exceptions() -> None:
    def _raise() -> int:
        raise PollTerminalError("terminal")

    with pytest.raises(PollTerminalError, match="terminal"):
        _ = poll_until(
            operation=_raise,
            retry_predicate=lambda value: value < 1,
            poll_interval=0.25,
            max_attempts=2,
            timeout_error_factory=PollTimeoutError,
            sleep=lambda _: None,
        )


def test_poll_until_does_not_sleep_after_final_attempt() -> None:
    sleeps: list[float] = []

    with pytest.raises(PollTimeoutError):
        _ = poll_until(
            operation=lambda: 0,
            retry_predicate=lambda value: value < 1,
            poll_interval=0.25,
            max_attempts=3,
            timeout_error_factory=PollTimeoutError,
            sleep=sleeps.append,
        )

    assert sleeps == [0.25, 0.25]


def test_async_poll_until_returns_first_non_retry_result() -> None:
    async def _run() -> tuple[int, list[float]]:
        values = iter([0, 0, 1])
        sleeps: list[float] = []

        async def _operation() -> int:
            return next(values)

        async def _sleep(delay: float) -> None:
            sleeps.append(delay)

        result = await async_poll_until(
            operation=_operation,
            retry_predicate=lambda value: value < 1,
            poll_interval=0.25,
            max_attempts=3,
            timeout_error_factory=PollTimeoutError,
            sleep=_sleep,
        )
        return result, sleeps

    result, sleeps = asyncio.run(_run())

    assert result == 1
    assert sleeps == [0.25, 0.25]


def test_async_poll_until_converts_retry_exhaustion_to_timeout_error() -> None:
    async def _run() -> None:
        async def _operation() -> int:
            return 0

        async def _sleep(_: float) -> None:
            return None

        _ = await async_poll_until(
            operation=_operation,
            retry_predicate=lambda value: value < 1,
            poll_interval=0.25,
            max_attempts=2,
            timeout_error_factory=PollTimeoutError,
            sleep=_sleep,
        )

    with pytest.raises(PollTimeoutError):
        asyncio.run(_run())


@pytest.mark.parametrize("max_attempts", [0, -1])
def test_async_poll_until_times_out_without_attempt_for_non_positive_max_attempts(
    max_attempts: int,
) -> None:
    async def _run() -> None:
        async def _operation() -> int:
            raise AssertionError("operation should not be called")

        async def _sleep(_: float) -> None:
            return None

        _ = await async_poll_until(
            operation=_operation,
            retry_predicate=lambda value: value < 1,
            poll_interval=0.25,
            max_attempts=max_attempts,
            timeout_error_factory=PollTimeoutError,
            sleep=_sleep,
        )

    with pytest.raises(PollTimeoutError):
        asyncio.run(_run())


def test_async_poll_until_propagates_operation_exceptions() -> None:
    async def _run() -> None:
        async def _operation() -> int:
            raise PollTerminalError("terminal")

        async def _sleep(_: float) -> None:
            return None

        _ = await async_poll_until(
            operation=_operation,
            retry_predicate=lambda value: value < 1,
            poll_interval=0.25,
            max_attempts=2,
            timeout_error_factory=PollTimeoutError,
            sleep=_sleep,
        )

    with pytest.raises(PollTerminalError, match="terminal"):
        asyncio.run(_run())


def test_async_poll_until_does_not_sleep_after_final_attempt() -> None:
    async def _run() -> list[float]:
        sleeps: list[float] = []

        async def _operation() -> int:
            return 0

        async def _sleep(delay: float) -> None:
            sleeps.append(delay)

        with pytest.raises(PollTimeoutError):
            _ = await async_poll_until(
                operation=_operation,
                retry_predicate=lambda value: value < 1,
                poll_interval=0.25,
                max_attempts=3,
                timeout_error_factory=PollTimeoutError,
                sleep=_sleep,
            )
        return sleeps

    assert asyncio.run(_run()) == [0.25, 0.25]


@pytest.mark.parametrize("is_async", [False, True])
def test_polling_respects_timeout_before_next_attempt(
    monkeypatch: pytest.MonkeyPatch, is_async: bool
) -> None:
    now = 0.0
    attempts = 0
    sleeps: list[float] = []
    monkeypatch.setattr("time.monotonic", lambda: now)

    def operation() -> bool:
        nonlocal attempts
        attempts += 1
        return False

    def sleep(delay: float) -> None:
        nonlocal now
        sleeps.append(delay)
        now += delay

    async def async_operation() -> bool:
        return operation()

    async def async_sleep(delay: float) -> None:
        sleep(delay)

    with pytest.raises(TimeoutError):
        if is_async:
            _ = asyncio.run(
                async_poll_until(
                    operation=async_operation,
                    retry_predicate=lambda result: not result,
                    poll_interval=0.03,
                    timeout_seconds=0.005,
                    timeout_error_factory=TimeoutError,
                    sleep=async_sleep,
                )
            )
        else:
            _ = poll_until(
                operation=operation,
                retry_predicate=lambda result: not result,
                poll_interval=0.03,
                timeout_seconds=0.005,
                timeout_error_factory=TimeoutError,
                sleep=sleep,
            )

    assert sleeps == [0.005]
    assert now == 0.005
    assert attempts == 1
