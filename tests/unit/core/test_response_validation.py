import httpx
import pytest
from pydantic import ValidationError

from ksef2._core.exceptions import KSeFResponseValidationError
from ksef2._endpoints.shared import parse_response, parse_response_list
from ksef2._infra.schema.api import spec


@pytest.mark.parametrize("as_list", [False, True])
def test_response_validation_exposes_field_paths_and_messages(as_list: bool) -> None:
    payload = {
        "certificates": [
            {
                "certificate": "REVSLUJZVEVT",
                "certificateSerialNumber": "014AA06A66BE5720",
                "certificateType": "invalid",
            }
        ]
    }
    response = httpx.Response(200, json=[payload] if as_list else payload)

    with pytest.raises(KSeFResponseValidationError) as exc_info:
        if as_list:
            parse_response_list(response, spec.RetrieveCertificatesResponse)
        else:
            parse_response(response, spec.RetrieveCertificatesResponse)

    error = exc_info.value
    assert error.details == [
        "certificates.0.certificateName: Field required",
        "certificates.0.certificateType: Input should be 'Authentication' or 'Offline'",
    ]
    assert error.context["details"] == error.details
    assert isinstance(error.__cause__, ValidationError)
    assert error.validation_error is error.__cause__
    assert error.errors()[0]["loc"] == ("certificates", 0, "certificateName")
