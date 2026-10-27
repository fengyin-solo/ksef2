---
title: Zarządzanie certyfikatami
description: Limity certyfikatów, rejestracja, wyszukiwanie wydanych certyfikatów i ich unieważnianie.
---

Użyj `auth.certificates` do rejestracji, wyszukiwania, pobierania i unieważniania certyfikatów KSeF. SDK wysyła CSR i żądania cyklu życia. Klucz prywatny generujesz i przechowujesz własnymi narzędziami.

## Sprawdź limity i dane rejestracji

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

Tych danych użyj, gdy składasz CSR we własnych narzędziach certyfikatowych.

## Zarejestruj certyfikat

Wyślij CSR i zapisz zwrócony numer referencyjny rejestracji.

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

# CertificateEnrollment: udostępnia każde pole odpowiedzi rejestracji
# {
#   "reference_number": "20260625-CERT-...",
#   "timestamp": "2026-06-25T10:00:00Z"
# }
```

Parametr `csr` to żądanie CSR zakodowane najpierw w DER, a potem w Base64. To nie jest tekst PEM z liniami `-----BEGIN`.

`enroll()` zwraca obiekt `CertificateEnrollment`. Poczekaj, aż KSeF wyda certyfikat:

```python
status = enrollment.wait(timeout=60.0, poll_interval=2.0)
```

`wait()` zgłasza `KSeFCertificateEnrollmentFailedError`, gdy KSeF odrzuci albo anuluje wniosek, oraz `KSeFCertificateEnrollmentTimeoutError`, gdy nie skończy w czasie. Aby sprawdzić status raz, bez czekania, wywołaj `enrollment.get_status()` albo `auth.certificates.get_enrollment_status(reference_number=...)`, gdy zapisałeś tylko numer referencyjny:

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

:::caution[Trzymaj klucze prywatne poza SDK]
SDK nie potrzebuje klucza prywatnego do rejestracji certyfikatu. Wygeneruj i chroń klucz prywatny we własnych narzędziach, do KSeF wyślij tylko CSR, a wydany certyfikat zapisz razem z pasującym kluczem.
:::

### Wznów zgłoszenie po restarcie

`enrollment.resume_state()` zwraca `CertificateEnrollmentResumeState` z numerem referencyjnym zgłoszenia. Zapisz go przez `to_json()` i przekaż do `auth.certificates.enrollment()`, gdy później inny proces przejmuje pracę:

```python
zapisany_stan = enrollment.resume_state().to_json()

# Później, w tym samym lub innym procesie:
enrollment = auth.certificates.enrollment(zapisany_stan)
status = enrollment.wait(timeout=60.0, poll_interval=2.0)
```

`enrollment()` przyjmuje obiekt stanu albo jego JSON i zwraca obiekt, który sprawdza status tego samego numeru referencyjnego. Znacznik czasu przyjęcia wniosku nie trafia do stanu, więc wznowiony obiekt nie ma `timestamp` ani `response`.

## Wyszukaj, pobierz i unieważnij

### Wyszukaj

```python
for certificate in auth.certificates.list(status="active"):
    print(certificate.serial_number, certificate.name, certificate.valid_to)
```

### Pobierz

```python
result = auth.certificates.retrieve(
    certificate_serial_numbers=["0123456789ABCDEF"],
)

for certificate in result.certificates:
    print(certificate.serial_number, certificate.certificate_type)
```

### Unieważnij

```python
auth.certificates.revoke(
    certificate_serial_number="0123456789ABCDEF",
    reason="key_compromise",
)
```

## Zapisz wydany certyfikat

KSeF przechowuje certyfikat. Twoja aplikacja przechowuje parę, którą faktycznie podpisuje, w magazynie certyfikatów podpisu z `ksef2.certificate_stores`.

1. Wygeneruj klucz prywatny i CSR własnymi narzędziami.
2. Zabezpiecz trwale oczekujący klucz prywatny, zanim wywołasz `enroll()`, i zapisz, do którego CSR on należy. Od tej chwili tylko ten klucz użyje certyfikatu, który KSeF ma wydać.
3. Wyślij CSR jako Base64 z DER i zapisz `enrollment.resume_state()` obok tego klucza.
4. Poczekaj na wydanie, a potem pobierz certyfikat po numerze seryjnym zwróconym przez KSeF.
5. Zdekoduj DER, zbuduj `XAdESCredentials` z certyfikatu i oczekującego klucza (to sprawdza, że do siebie pasują), ułóż z nich `SigningCertificate` dla tego środowiska i tego typu certyfikatu KSeF, a następnie zapisz rekord przez `save()`.
6. Pozbądź się oczekującego klucza zgodnie z własną polityką kluczy dopiero wtedy, gdy `save()` się zwróci.

Poniższy przykład zakłada, że `store` to jeden z magazynów certyfikatów podpisu z `ksef2.certificate_stores`, a `csr_base64_der` to Base64 z DER tego CSR, który wytworzyły Twoje narzędzia.

```python
import base64

from cryptography.x509 import load_der_x509_certificate

from ksef2 import Environment
from ksef2.certificate_stores import SigningCertificate
from ksef2.xades import XAdESCredentials

# `pending_key` to klucz wygenerowany dla tego CSR i już zabezpieczony przez
# Twoje narzędzia. Poniższy kod zakłada, że aplikacja zapisała stan wznowienia
# obok tego klucza.
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

# Para jest teraz dostępna przez `info.reference`. Klucz `pending_key` wycofaj
# dopiero tutaj.
```

### Gdy coś się nie uda

Gdy pobranie albo zapis certyfikatu nie wyjdzie, wznów to samo zgłoszenie ze zapisanego stanu przez `auth.certificates.enrollment(state)`, ponów pobranie i zapisz certyfikat na oryginalnym kluczu. Nie generuj nowego klucza i nie rejestruj ponownie: KSeF już przyjął tamto zgłoszenie. Nieudane `save()` to problem lokalny i nie może wywołać `revoke()`.

Jeśli proces padnie po przyjęciu `enroll()` przez KSeF, ale przed zapisem stanu wznowienia, SDK nie odzyska tego zgłoszenia. Rejestracja w KSeF nie jest idempotentna i żądania nie da się powtórzyć.

Uwierzytelnij się zapisaną parą przez [`with_stored_certificate()`](authenticate.md). Aby trzymać rekord na własnym backendzie, zobacz [Własny magazyn certyfikatów podpisu](write-signing-certificate-store.md).

## Zalecany przepływ

1. Sprawdź limity certyfikatów i rejestracji.

2. Pobierz dane podmiotu do rejestracji.

3. Wygeneruj klucz prywatny i CSR poza SDK.

4. Wyślij rejestrację i zapisz numer referencyjny.

5. Poczekaj na wydanie, pobierz certyfikat i zapisz go z kluczem prywatnym.

6. Unieważnij certyfikaty, które nie są już potrzebne albo których klucz prywatny mógł wyciec.

## Następne kroki

- [Podpisy XAdES](use-xades-helpers.md): Wczytaj certyfikat i uwierzytelnij się przez XAdES.
- [Certyfikaty](../concepts/certificates.md): Do czego służą certyfikaty przy uwierzytelnianiu, podpisie i rejestracji.
- [Uwierzytelnianie](authenticate.md): Użyj wydanego certyfikatu do uwierzytelniania w SDK.
