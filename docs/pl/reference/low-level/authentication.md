---
title: Uwierzytelnianie niskiego poziomu
description: Metody uwierzytelniania raw, przebieg tokena KSeF i XAdES oraz powiązanie tokenów z SDK.
---

Użyj uwierzytelniania niskiego poziomu, gdy inny system ma podpis, szyfrowanie tokena albo własną zasadę sprawdzania statusu. Uwierzytelnianie `raw` używa modeli odpowiedzi zgodnych ze schematem, dopóki jawnie nie przeniesiesz tokenów z powrotem do publicznego modelu SDK.

## Metody

| Metoda | Transport | Zwraca | Do czego służy |
| --- | --- | --- | --- |
| `client.raw.auth.challenge()` | nieuwierzytelniony | `spec.AuthenticationChallengeResponse` | Utworzenie wyzwania dla tokena albo XAdES. |
| `client.raw.auth.token_auth(body)` | nieuwierzytelniony | `spec.AuthenticationInitResponse` | Start uwierzytelniania tokenem KSeF przez `InitTokenAuthenticationRequest`. |
| `client.raw.auth.xades_auth(signed_xml, verify_chain=False)` | nieuwierzytelniony | `spec.AuthenticationInitResponse` | Wysłanie podpisanego na zewnątrz XML XAdES. |
| `client.raw.auth.auth_status(bearer_token, reference_number)` | tymczasowy token Bearer | `spec.AuthenticationOperationStatusResponse` | Sprawdzanie statusu operacji uwierzytelniania. |
| `client.raw.auth.redeem_token(bearer_token)` | tymczasowy token Bearer | `spec.AuthenticationTokensResponse` | Wymiana tymczasowego tokena operacji na token dostępu (`accessToken`) i token odświeżający (`refreshToken`). |
| `client.raw.auth.refresh_token(bearer_token)` | token odświeżający jako Bearer | `spec.AuthenticationTokenRefreshResponse` | Odświeżenie tokena dostępu. |
| `auth.raw.auth.list_sessions(...)` | uwierzytelniony | `spec.AuthenticationListResponse` | Lista sesji uwierzytelnienia. |
| `auth.raw.auth.terminate_current_session()` | uwierzytelniony | `None` | Zamknięcie bieżącej sesji uwierzytelnienia. |
| `auth.raw.auth.terminate_auth_session(reference_number)` | uwierzytelniony | `None` | Zamknięcie innej sesji po numerze referencyjnym. |

Klienci asynchroniczni mają te same nazwy metod i wymagają `await` dla wywołań sieciowych.

## Przebieg uwierzytelniania tokenem

| Krok | Wywołanie albo obiekt | Zachowaj |
| --- | --- | --- |
| Utwórz wyzwanie | `client.raw.auth.challenge()` | `challenge.challenge`, `challenge.timestampMs` |
| Pobierz certyfikat do szyfrowania tokena | `client.raw.encryption.fetch_public_certificates()` | certyfikat z użyciem `KsefTokenEncryption` |
| Zaszyfruj token | `encrypt_token(ksef_token, str(challenge.timestampMs), cert.certificate)` | zaszyfrowany token |
| Zbuduj żądanie | `spec.InitTokenAuthenticationRequest(...)` | `challenge`, `contextIdentifier`, `encryptedToken`, `publicKeyId` |
| Rozpocznij operację | `client.raw.auth.token_auth(request)` | `init.authenticationToken.token`, `init.referenceNumber` |
| Sprawdzaj status | `client.raw.auth.auth_status(...)` | końcowy status |
| Odbierz tokeny | `client.raw.auth.redeem_token(init.authenticationToken.token)` | odpowiedź zgodna ze schematem, z tokenem dostępu i tokenem odświeżającym |
| Powiąż z SDK | `client.authentication.resume(AuthenticationResumeState.from_tokens(auth_mapper.from_spec(raw_tokens)))` | `AuthenticatedClient` |

## Przebieg XAdES z podpisem poza SDK

| Krok | Wywołanie albo obiekt | Zachowaj |
| --- | --- | --- |
| Utwórz wyzwanie | `client.raw.auth.challenge()` | treść wyzwania dla systemu podpisu |
| Podpisz poza SDK | HSM, brama albo zewnętrzny podpis | podpisany XML jako bajty |
| Rozpocznij operację | `client.raw.auth.xades_auth(signed_xml, verify_chain=True)` | `init.authenticationToken.token`, `init.referenceNumber` |
| Sprawdzaj status | `client.raw.auth.auth_status(...)` | końcowy status |
| Odbierz tokeny | `client.raw.auth.redeem_token(init.authenticationToken.token)` | odpowiedź zgodna ze schematem, z tokenem dostępu i tokenem odświeżającym |
| Powiąż z SDK | `client.authentication.resume(AuthenticationResumeState.from_tokens(auth_mapper.from_spec(raw_tokens)))` | `AuthenticatedClient` |

## Powiązanie tokenów z SDK

Przekaż odpowiedź `init` zwróconą przez `token_auth()` albo `xades_auth()` do `bind_tokens()` po sprawdzeniu operacji aż do statusu sukcesu. Funkcja zwraca klienta uwierzytelnionego:

```python
from ksef2 import Client
from ksef2.clients import AuthenticatedClient
from ksef2.models import AuthenticationResumeState
from ksef2.raw import spec
from ksef2.raw.mappers import auth as auth_mapper

def bind_tokens(client: Client, init: spec.AuthenticationInitResponse) -> AuthenticatedClient:
    raw_tokens = client.raw.auth.redeem_token(init.authenticationToken.token)
    auth_tokens = auth_mapper.from_spec(raw_tokens)
    return client.authentication.resume(AuthenticationResumeState.from_tokens(auth_tokens))
```

Przypisz wynik przez `auth = bind_tokens(client, init)`. Potem możesz używać modułów przepływu, takich jak `auth.invoices`, albo uwierzytelnionych modułów `raw`, takich jak `auth.raw.invoices`.

## Status operacji

`auth_status()` używa tymczasowego tokena operacji jako tokena Bearer, nie końcowego tokena dostępu. Sprawdzaj status, aż KSeF zwróci końcowy wynik uwierzytelniania, a potem wywołaj `redeem_token()` z tym samym tymczasowym tokenem.

| Stan | Co robi wywołujący |
| --- | --- |
| Sukces | Wymień tymczasowy token operacji przez `redeem_token()`. |
| Błąd | Przerwij i pokaż kod oraz opis statusu. |
| Lokalny limit czasu | Zapisz `init.referenceNumber` i zdecyduj, czy inny proces roboczy ma kontynuować sprawdzanie statusu. |

## Powiązane strony

- [Metody uwierzytelniania](../../concepts/authentication-methods.md): token KSeF, XAdES, certyfikat testowy i profile, zanim zejdziesz do operacji `raw`.
- [API niskiego poziomu](overview.md): własność niskiego poziomu, przestrzenie nazw modeli i eksportowane narzędzia.
- [Mapa operacji API](endpoint-map.md): wszystkie moduły `raw`.
