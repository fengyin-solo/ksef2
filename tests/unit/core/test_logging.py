import io
import json
import logging

import pytest
import structlog

from ksef2 import _logging
from ksef2._logging import configure_logging, get_logger
from ksef2.logging import configure_logging as public_configure_logging


@pytest.fixture(autouse=True)
def reset_logging_state():
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level

    try:
        yield
    finally:
        structlog.reset_defaults()
        _logging._configure_stdlib_bridge()
        root_logger.handlers[:] = original_handlers
        root_logger.setLevel(original_level)


class TestPackageLogging:
    def test_public_configuration_is_same_function(self) -> None:
        assert public_configure_logging is configure_logging

    def test_sdk_is_silent_without_application_logging_configuration(
        self, capsys
    ) -> None:
        get_logger().info("silent SDK event")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_sdk_events_flow_through_standard_logging(self, caplog) -> None:
        with caplog.at_level(logging.DEBUG, logger="ksef2"):
            get_logger("ksef2.tests").info("stdlib event", marker="visible")

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert (record.name, record.levelname) == ("ksef2.tests", "INFO")
        assert record.msg["event"] == "stdlib event"
        assert record.msg["marker"] == "visible"

    def test_configure_logging_emits_json_events(self) -> None:
        stream = io.StringIO()

        configure_logging(
            level="INFO",
            renderer="json",
            stream=stream,
            force=True,
        )

        get_logger().info("SDK logger configured", component="tests")

        payload = json.loads(stream.getvalue())
        assert payload["event"] == "SDK logger configured"
        assert payload["component"] == "tests"
        assert payload["level"] == "info"
        assert payload["logger"] == "ksef2"
        assert "timestamp" in payload

    def test_get_logger_uses_explicit_logger_name(self) -> None:
        stream = io.StringIO()

        configure_logging(
            level="INFO",
            renderer="json",
            stream=stream,
            force=True,
        )

        get_logger("ksef2.tests").warning("Named logger works")

        payload = json.loads(stream.getvalue())
        assert payload["event"] == "Named logger works"
        assert payload["logger"] == "ksef2.tests"
        assert payload["level"] == "warning"
