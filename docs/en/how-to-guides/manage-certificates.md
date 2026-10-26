---
title: Manage Certificates
description: Check certificate limits, enroll certificates, query issued certificates, and revoke certificates.
---

Use `auth.certificates` for KSeF certificate enrollment, search, retrieval, and
revocation. The SDK sends CSR and lifecycle requests. Your certificate tooling
still owns private-key generation and private-key storage.

## Check limits and enrollment data

```python
limits = auth.certificates.get_limits()

# CertificateLimitsResponse
# {
#   "can_request": true,
#   "enrollment_limit": 10,
#   "enrollment_remaining": 9,
#   "certificate_limit": 10,
#   "certificate_remaining": 8
# }

subject = auth.certificates.get_enrollment_data()

# CertificateEnrollmentData
# {
#   "common_name": "Example subject",
#   "iso_country_code": "PL",
#   "organization_identifier": "VATPL-5261040828"
# }
```

Use the enrollment data when building the CSR in your certificate tooling.

## Enroll a certificate

Submit a CSR and persist the returned enrollment reference.

```python
import base64
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding

csr_pem = Path("request.csr").read_bytes()
csr_der = x509.load_pem_x509_csr(csr_pem).public_bytes(Encoding.DER)
csr = base64.b64encode(csr_der).decode("ascii")

enrollment = auth.certificates.enroll(
    certificate_name="billing-service",
    certificate_type="authentication",
    csr=csr,
)

# CertificateEnrollment: exposes every field of the enrollment response
# {
#   "reference_number": "20260625-CERT-...",
#   "timestamp": "2026-06-25T10:00:00Z"
# }
```

The `csr` argument must be the DER-encoded CSR in Base64, not PEM text with
`-----BEGIN` lines.

`enroll()` returns a `CertificateEnrollment` handle. Wait for KSeF to issue the
certificate:

```python
status = enrollment.wait(timeout=60.0, poll_interval=2.0)
```

`wait()` raises `KSeFCertificateEnrollmentFailedError` when KSeF rejects or
cancels the request and `KSeFCertificateEnrollmentTimeoutError` when it does not
finish in time. To check the status once without waiting, call
`enrollment.get_status()`, or
`auth.certificates.get_enrollment_status(reference_number=...)` when you only
stored the reference number:

```python
status = auth.certificates.get_enrollment_status(
    reference_number=enrollment.reference_number,
)

# CertificateEnrollmentStatusResponse
# {
#   "status_code": 200,
#   "status_description": "Completed",
#   "certificate_serial_number": "0123456789ABCDEF"
# }
```

:::caution[Keep private keys outside the SDK]
The SDK does not need the private key for certificate enrollment. Generate and
protect the private key in your certificate tooling, submit only the CSR to
KSeF, and store the issued certificate next to its matching key.
:::

### Resume an enrollment after a restart

`enrollment.resume_state()` returns a `CertificateEnrollmentResumeState` holding
the enrollment's reference number. Persist it with `to_json()` and pass it to
`auth.certificates.enrollment()` when a later process picks the work up:

```python
saved_state = enrollment.resume_state().to_json()

# Later, in the same or another process:
enrollment = auth.certificates.enrollment(saved_state)
status = enrollment.wait(timeout=60.0, poll_interval=2.0)
```

`enrollment()` takes the state object or its JSON string and returns a handle
that polls the same reference number. The acceptance timestamp KSeF returned at
enrollment is not part of the state, so a resumed handle has no `timestamp` and
no `response`.

## Query, retrieve, and revoke

### Query

```python
for certificate in auth.certificates.list(status="active"):
    print(certificate.serial_number, certificate.name, certificate.valid_to)
```

### Retrieve

```python
result = auth.certificates.retrieve(
    certificate_serial_numbers=["0123456789ABCDEF"],
)

for certificate in result.certificates:
    print(certificate.serial_number, certificate.certificate_type)
```

### Revoke

```python
auth.certificates.revoke(
    certificate_serial_number="0123456789ABCDEF",
    reason="key_compromise",
)
```

## Store an issued certificate

KSeF keeps the certificate. Your application keeps the pair it can actually sign
with, in a signing-certificate store from `ksef2.certificate_stores`.

1. Generate the private key and the CSR with your certificate tooling.
2. Protect the pending private key durably *before* calling `enroll()`, and record
   which CSR it belongs to. From that moment this key is the only one that can use
   the certificate KSeF is about to issue.
3. Submit the CSR as Base64-encoded DER and persist `enrollment.resume_state()`
   next to that key.
4. Wait for issuance, then retrieve the certificate by the serial number KSeF
   returned.
5. Decode the DER, build `XAdESCredentials` from the certificate and the pending
   key (this checks the two belong together), wrap them in a `SigningCertificate`
   for this environment and this KSeF certificate type, and `save()` the record.
6. Retire the pending key according to your own key policy only after `save()`
   returned.

The snippet assumes `store` is one of the signing-certificate stores from
`ksef2.certificate_stores` and `csr_base64_der` is the Base64-encoded DER of the
CSR your tooling produced.

```python
import base64

from cryptography.x509 import load_der_x509_certificate

from ksef2 import Environment
from ksef2.certificate_stores import SigningCertificate
from ksef2.xades import XAdESCredentials

# `pending_key` is the key your tooling generated for this CSR and already
# protects. Everything below assumes the application has just persisted the
# resume state next to that key.
enrollment = auth.certificates.enroll(
    certificate_name="billing-service",
    certificate_type="authentication",
    csr=csr_base64_der,
)
saved_state = enrollment.resume_state().to_json()

status = enrollment.wait(timeout=120.0, poll_interval=2.0)
issued = auth.certificates.retrieve(
    certificate_serial_numbers=[status.certificate_serial_number],
)
certificate = issued.certificates[0]

credentials = XAdESCredentials(
    load_der_x509_certificate(
        base64.b64decode(certificate.base64_encoded_certificate)
    ),
    pending_key,
)
info = store.save(
    SigningCertificate(
        credentials,
        environment=Environment.PRODUCTION,
        certificate_type="authentication",
        ksef_serial_number=certificate.serial_number,
    )
)

# The pair is now reachable through `info.reference`. Retire `pending_key`
# only here.
```

### If a step fails

If retrieving or saving the certificate fails, resume the same enrollment from
its saved state with `auth.certificates.enrollment(state)`, retry the retrieval,
and save the certificate against the *original* key. Do not generate a new key
and do not enroll again: KSeF already accepted that request. A failed `save()`
is a local problem and must not trigger `revoke()`.

If the process dies after KSeF accepted `enroll()` but before the resume state
was persisted, the SDK cannot recover that enrollment, because KSeF enrollment is
not idempotent and the request cannot be replayed.

Authenticate with the stored pair through
[`with_stored_certificate()`](authenticate.md), and see
[Write a signing-certificate store](write-signing-certificate-store.md) to put
the record behind your own backend.

## Recommended flow

1. Check certificate and enrollment quotas.

2. Fetch enrollment subject data.

3. Generate a private key and CSR outside the SDK.

4. Submit enrollment and persist the reference number.

5. Wait for issuance, retrieve the certificate, and store it with the private key.

6. Revoke certificates that are no longer valid or whose private key may be
   compromised.

## Next workflows

- [Use XAdES helpers](use-xades-helpers.md): Load certificate material and authenticate with XAdES.
- [Certificates](../concepts/certificates.md): Understand certificate roles in authentication, signing, and enrollment.
- [Authenticate](authenticate.md): Use issued certificate material for SDK authentication.
