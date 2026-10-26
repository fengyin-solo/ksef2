---
title: Metody uwierzytelniania
description: Uwierzytelnianie tokenem KSeF, podpisem XAdES, certyfikatem testowym i profilami w ksef2.
---

Uwierzytelnianie zamienia głównego `Client` albo `AsyncClient` w klienta uwierzytelnionego dla jednego kontekstu logowania. Klient główny wybiera środowisko i trzyma zasoby transportu. Metoda uwierzytelniania potwierdza, kto może działać w wybranym kontekście.

KSeF rozdziela dwa pojęcia, które łatwo pomylić:

| Pojęcie | Znaczenie w KSeF | W SDK |
| --- | --- | --- |
| Kontekst logowania | Podatnik albo inny podmiot, w imieniu którego będą wykonywane operacje. | `nip` oraz `context_type`, na przykład `context_type="nip"`. |
| Podmiot uwierzytelniający | Token albo tożsamość z certyfikatu, która potwierdza prawo wejścia w ten kontekst. | `ksef_token` albo `cert` i `private_key`. |

Po udanym uwierzytelnieniu SDK zwraca `AuthenticatedClient`. Ten klient trzyma token dostępu (`accessToken`) i token odświeżający (`refreshToken`) oraz udostępnia chronione moduły: sesje, faktury, tokeny, uprawnienia, certyfikaty, limity i historię sesji.

```text
Client(Environment.TEST)
  -> client.authentication
    -> with_token(), with_xades(), with_test_certificate() albo with_profile()
      -> AuthenticatedClient dla jednego kontekstu KSeF
        -> sesje online, sesje batch, faktury
        -> tokeny, uprawnienia, certyfikaty, limity
```

## Metody KSeF i metody SDK

Na poziomie API KSeF uwierzytelnianie ma dwie główne rodziny:

| Rodzina KSeF | Co trafia do KSeF | Metoda SDK |
| --- | --- | --- |
| Uwierzytelnianie XAdES | Podpisany dokument XML `AuthTokenRequest`. | `with_xades()` |
| Uwierzytelnianie tokenem KSeF | Token KSeF zaszyfrowany aktualnym certyfikatem do szyfrowania tokenów. | `with_token()` |

SDK dokłada dwie wygodne metody:

| Metoda SDK | Co dodaje |
| --- | --- |
| `with_test_certificate()` | Generuje tymczasowy certyfikat środowiska testowego, a potem używa przepływu XAdES. |
| `with_profile()` | Czyta lokalną konfigurację profilu `ksef2-cli` i wybiera token, certyfikat testowy, PEM XAdES albo PKCS#12 XAdES. |

:::note[Profil nie jest kolejnymi danymi uwierzytelniającymi KSeF]
Profil zapisuje sposób uwierzytelnienia: środowisko, NIP, metodę, ścieżki certyfikatów, ustawienia sprawdzania statusu i nazwy zmiennych środowiskowych z sekretami. Danymi, które naprawdę potwierdzają tożsamość, nadal są token KSeF albo podpis XAdES oparty na certyfikacie.
:::

## Wybierz metodę

| Metoda | Kiedy jej używać | Co robi SDK |
| --- | --- | --- |
| `with_test_certificate()` | Pracujesz w `Environment.TEST` i chcesz jak najmniej konfiguracji. | Generuje certyfikat testowy z NIP-u i uwierzytelnia się przez XAdES. |
| `with_token()` | Aplikacja ma już token KSeF dla docelowego kontekstu logowania. | Pobiera certyfikat KSeF do szyfrowania tokenów, szyfruje token ze znacznikiem czasu wyzwania, zaczyna uwierzytelnianie, sprawdza status i pobiera tokeny. |
| `with_xades()` | Aplikacja ma certyfikat i klucz prywatny dostępne w Pythonie. | Buduje XML wyzwania KSeF, podpisuje go XAdES, wysyła podpisany XML, sprawdza status i pobiera tokeny. |
| `with_profile()` | Kod SDK i `ksef2-cli` mają współdzielić nazwane ustawienia lokalne. | Odczytuje wybrany profil i wywołuje właściwą metodę SDK. |

**Zobacz też:**

- [Uwierzytelnianie](../how-to-guides/authenticate.md): wybrana metoda w kodzie, ze zmiennymi środowiskowymi i miejscem na sekrety.
- [Profile](../how-to-guides/profiles.md): wspólne ustawienia lokalne dla terminala i SDK, zgodne z CLI.

## Podmiot i kontekst przy XAdES

Przy uwierzytelnianiu XAdES SDK buduje i podpisuje żądanie XML dla kontekstu NIP przekazanego do `with_xades()`. KSeF odczytuje podmiot uwierzytelniający z certyfikatu użytego do podpisu. Może to być pieczęć firmowa, certyfikat osoby z NIP-em albo PESEL-em, certyfikat KSeF typu `Authentication` albo certyfikat dopuszczony przez uprawnienia nadane na odcisk palca certyfikatu.

`nip` jest więc identyfikatorem kontekstu logowania, a nie zawsze identyfikatorem wpisanym w certyfikat podpisujący. Osoba może uwierzytelnić się w kontekście firmy, jeśli KSeF widzi aktywne uprawnienia tej osoby albo certyfikatu.

:::tip[XML podpisywany poza Pythonem]
`with_xades()` jest ścieżką wysokiego poziomu, gdy Python może wczytać certyfikat i klucz prywatny. Jeśli podpis powstaje poza Pythonem, użyj operacji uwierzytelniania niskiego poziomu i powiąż pobrane `AuthTokens` przez `client.authentication.resume(AuthenticationResumeState.from_tokens(auth_tokens))`.
:::

## Token dostępu odświeża się sam

Token dostępu KSeF jest krótkotrwały. Klient uwierzytelniony trzyma więc obok niego token odświeżający i odnawia token dostępu bez udziału Twojego kodu: krótko przed `access_token_valid_until` oraz raz po odpowiedzi `401`, ponawiając nieudane żądanie jeden raz. Równoległe żądania współdzielą jedno odświeżenie.

Dotyczy to każdego sposobu uzyskania klienta uwierzytelnionego: metod `with_*` oraz `client.authentication.resume(state)`. `resume` przyjmuje obiekt stanu albo jego JSON. Stan z wygasłym tokenem dostępu działa, dopóki token odświeżający jest ważny. Sesje wznowione przez `state=` używają tego samego klienta, więc też się odświeżają. `auth.resume_state()` i `auth.auth_tokens` zwracają bieżące tokeny, więc po dłuższej pracy zapisz stan ponownie.

Gdy token odświeżający wygasł albo został odrzucony, klient zgłasza wyjątek `KSeFAuthenticationExpiredError`, podklasę `KSeFAuthError`. Aby kontynuować, uwierzytelnij się ponownie. Aby odświeżać tokeny samodzielnie, przekaż `TransportConfig(auto_refresh_tokens=False)`. Dokładne reguły opisuje [Odświeżanie tokena dostępu](../reference/operations.md#odświeżanie-tokena-dostępu).

## Profile są lokalną konfiguracją uwierzytelniania

`with_profile()` nie jest osobnym rodzajem danych uwierzytelniających. To warstwa konfiguracji nad tymi samymi metodami:

| Typ w profilu | Bezpośrednia metoda SDK |
| --- | --- |
| `token` | `with_token()` |
| `test_certificate` | `with_test_certificate()` |
| `xades_pem` | `with_xades()` z plikami certyfikatu i klucza PEM |
| `xades_p12` | `with_xades()` z archiwum PKCS#12/PFX |

Profil przechowuje ustawienia, które nie są sekretami: środowisko, NIP, rodzaj uwierzytelniania, ścieżki certyfikatów, ustawienia sprawdzania statusu i nazwę zmiennej środowiskowej z sekretem. Nie powinien przechowywać wartości tokenów, haseł kluczy prywatnych ani haseł PKCS#12.

Kolejność wyboru profilu jest taka sama w SDK i CLI:

1. Jawna nazwa profilu przekazana do `with_profile("name")`.
2. `KSEF2_PROFILE`.
3. `active_profile` w lokalnej konfiguracji profili.

:::tip[Profile dobrze działają z CLI]
Twórz i wybieraj profile przez `ksef2-cli`, gdy te same osoby obsługują ten sam kontekst logowania z terminala. Użyj `ProfileStore`, gdy narzędzie w Pythonie ma samo tworzyć albo aktualizować wspólny plik profili.
:::

Środowisko klienta głównego musi zgadzać się ze środowiskiem wybranego profilu. Profilu `test` używaj z `Client(Environment.TEST)`, profilu `demo` z `Client(Environment.DEMO)`, a profilu `production` z `Client(Environment.PRODUCTION)`.

## Przebieg uwierzytelniania

1. Klient główny pobiera wyzwanie z wybranego środowiska KSeF.

2. Wybrana metoda potwierdza tożsamość dla żądanego kontekstu logowania.

   Uwierzytelnianie tokenem szyfruje token KSeF razem ze znacznikiem czasu z wyzwania. Uwierzytelnianie XAdES podpisuje XML wyzwania. Certyfikat testowy najpierw generuje materiał certyfikatu dla środowiska testowego. Profil odczytuje jedną z tych ścieżek z lokalnej konfiguracji.

3. KSeF zaczyna asynchroniczną operację uwierzytelniania.

   SDK trzyma tymczasowy token operacji i numer referencyjny wewnętrznie, gdy sprawdza status.

4. SDK zamienia zakończoną operację na token dostępu i token odświeżający.

5. Zwrócony `AuthenticatedClient` używa tych tokenów w chronionych operacjach SDK.

Klient asynchroniczny ma te same nazwy metod na `AsyncClient`. Wywołuj je z `await`. Wybór między tokenem KSeF, certyfikatem testowym, XAdES i profilem pozostaje taki sam.

## Co chronić

| Wartość | Dlaczego jest ważna |
| --- | --- |
| Token KSeF | Może uwierzytelnić się w swoim kontekście logowania, dopóki nie zostanie unieważniony albo nie wygaśnie. |
| Klucz prywatny i hasło certyfikatu | Mogą potwierdzić tożsamość używaną przy uwierzytelnianiu XAdES. |
| Token dostępu (`accessToken`) | Upoważnia do chronionych wywołań SDK, dopóki jest ważny. |
| Token odświeżający (`refreshToken`) | Może pobrać nowy token dostępu, dopóki jest ważny. |
| Stan wznowienia uwierzytelnienia | Zawiera oba tokeny potrzebne do odtworzenia klienta uwierzytelnionego. |
| Zapisany stan sesji | Może zawierać materiał szyfrowania sesji i adresy przesłania potrzebne do wznowienia przepływu. |

Sekrety trzymaj w zmiennych środowiskowych, w menedżerze sekretów albo w bezpiecznym magazynie aplikacji. W plikach profili zostaw ustawienia bez sekretów i nazwy zmiennych środowiskowych, które te sekrety zawierają.

## Uwierzytelnienie nie jest zgodą na operację

Uwierzytelnienie potwierdza tożsamość dla kontekstu logowania. Uprawnienia nadal określają, które operacje ta tożsamość może wykonać. Dane uwierzytelniające mogą potwierdzić tożsamość, a potem nie wystarczyć do wysyłki faktur, odczytu metadanych, zarządzania tokenami albo nadawania uprawnień.

:::note[Sprawdzaj kontekst logowania i uprawnienia razem]
Gdy chroniona operacja nie powiedzie się po uwierzytelnieniu, sprawdź wybrane środowisko, identyfikator kontekstu i aktywny zestaw uprawnień. Sam rodzaj danych uwierzytelniających nie rozstrzyga, czy operacja jest dozwolona.
:::

## Powiązane strony

- [Uwierzytelnianie](../how-to-guides/authenticate.md): zmienne środowiskowe, token KSeF, XAdES, certyfikaty testowe i profile.
- [Profile](../how-to-guides/profiles.md): lokalna konfiguracja ksef2-cli, uwierzytelnianie SDK i `ProfileStore`.
- [Uwierzytelnianie niskiego poziomu](../reference/low-level/authentication.md): ręczna operacja, gdy inny system podpisuje XML albo wymienia tokeny.
- [Uwierzytelnianie w CLI](../../cli/guides/authentication.md): te same metody uwierzytelniania z profilami w ksef2-cli.
- [Tokeny i uprawnienia](permissions.md): jak dane uwierzytelniające łączą się z chronionymi uprawnieniami.
- [XAdES](xades.md): podpis XML używany przy uwierzytelnianiu certyfikatem.
