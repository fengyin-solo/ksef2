---
title: Certyfikaty
description: Role certyfikatów w uwierzytelnianiu KSeF, rejestracji, trybie offline i publicznym szyfrowaniu.
---

KSeF używa słowa „certyfikat” w kilku różnych miejscach. Wszystkie opierają się na kryptografii, ale w SDK nie pełnią tej samej roli.

| Rola certyfikatu | Kto go ma | Moduł SDK | Cel |
| --- | --- | --- | --- |
| Materiał podpisu uwierzytelniania | Aplikacja, użytkownik, HSM, magazyn certyfikatów albo metoda pomocnicza środowiska testowego. | `client.authentication.with_xades()` i `ksef2.xades` | Podpisuje `AuthTokenRequest` używany do uwierzytelnienia. |
| Certyfikat wydany przez KSeF | KSeF wydaje go po wniosku. Przechowujesz go razem z kluczem prywatnym. | `auth.certificates` | Daje podmiotowi uwierzytelniającemu certyfikat KSeF typu Authentication albo Offline. |
| Publiczny certyfikat szyfrowania | Publikuje go KSeF. SDK go odczytuje. | `client.encryption` i przepływy wysokiego poziomu | Szyfruje dla KSeF dane uwierzytelniania tokenem, klucze sesji i klucze eksportu. |

Rozdzielenie tych ról chroni przed dwoma częstymi błędami: traktowaniem certyfikatu tak, jakby niósł uprawnienia KSeF, oraz traktowaniem rejestracji tak, jakby KSeF miał dostać klucz prywatny.

:::caution[Rejestracja nie jest przechowywaniem klucza]
SDK wysyła CSR i żądania dotyczące życia certyfikatu. Klucze prywatne generuje, przechowuje, wymienia i chroni aplikacja albo narzędzia do certyfikatów.
:::

## Tożsamość i uprawnienia

Certyfikat KSeF jest nośnikiem tożsamości podmiotu uwierzytelniającego. Zwykle jest powiązany z NIP-em, PESEL-em albo odciskiem palca certyfikatu. Sam nie jest przypisany do kontekstu logowania i nie zawiera zestawu uprawnień używanego przez operacje KSeF.

Uprawnienia są sprawdzane osobno. Certyfikat potwierdza, kto się uwierzytelnia. KSeF i tak sprawdza, czy ten podmiot może działać w wybranym kontekście logowania.

## Typy certyfikatów KSeF

Certyfikat wydany przez KSeF ma jeden typ. Nie da się połączyć obu ról w jednym certyfikacie.

| Wartość SDK | Znaczenie |
| --- | --- |
| `authentication` | Certyfikat KSeF typu Authentication. Służy do uwierzytelniania w KSeF. |
| `offline` | Certyfikat KSeF typu Offline. Potwierdza autentyczność wystawcy i integralność faktury w trybie offline. Nie służy do uwierzytelniania. |

Wniosek składaj o typ, którego potrzebuje dany przepływ.

## Rejestracja

Rejestracja certyfikatu wymaga uwierzytelnienia, ale nie jest zwykłym formularzem administracyjnym. KSeF bierze dane podmiotu do wniosku z certyfikatu użytego do uwierzytelnienia XAdES. CSR musi użyć tych wartości. Ich zmiana powoduje odrzucenie wniosku.

```python
limits = auth.certificates.get_limits()
print(limits.can_request, limits.enrollment_remaining)

subject = auth.certificates.get_enrollment_data()
print(subject.common_name, subject.country_name)
```

SDK udostępnia kolejne kroki jako metody wysokiego poziomu. Klucz prywatny i CSR nadal pochodzą z Twoich narzędzi:

1. Uwierzytelnij się certyfikatem i podpisem XAdES.
2. Odczytaj limity certyfikatów i dane podmiotu do wniosku.
3. Wygeneruj klucz prywatny i CSR poza SDK.
4. Wyślij CSR przez `auth.certificates.enroll()`.
5. Sprawdzaj status wniosku, aż KSeF zwróci numer seryjny certyfikatu.
6. Pobierz wydany certyfikat i zapisz go razem z kluczem prywatnym.

:::note[Token KSeF nie wystarczy do rejestracji]
Rejestracja certyfikatu wymaga uwierzytelnienia XAdES, bo KSeF bierze tożsamość z certyfikatu, którym podpisano żądanie.
:::

## Magazyn certyfikatów podpisu i pamięć certyfikatów szyfrowania

SDK ma dwie rzeczy nazywane magazynem i one się nie spotykają. Żadna nie jest usługą KSeF. Obie działają w Twojej aplikacji.

| | `ksef2.certificate_stores` | Pamięć `certificate_store=` |
| --- | --- | --- |
| Co trzyma | Twój certyfikat podpisu i jego klucz prywatny. | Publiczne certyfikaty szyfrowania KSeF. |
| Kto wkłada materiał | Twoja aplikacja przez `save()`. | SDK, pobierając z `client.encryption`. |
| Do czego służy | Przekazanie pary do `with_stored_certificate()` albo do podpisu. | Szyfrowanie dla KSeF kluczy tokena, sesji i eksportu. |
| Sekret? | Tak, trzyma klucz prywatny. | Nie. Wszystko w niej jest publiczne. |

Przekazanie magazynu certyfikatów podpisu jako `certificate_store=` albo oczekiwanie, że `with_stored_certificate()` przeczyta pamięć certyfikatów szyfrowania, miesza te role.

Lokalny rekord mówi tylko to, co twierdzi sam certyfikat. Nie mówi, czy KSeF nadal uważa certyfikat za aktywny i nieunieważniony. To sprawdzisz w KSeF przez `auth.certificates.list()`. Obie strony tej różnicy mają znaczenie. Usunięcie lokalnego rekordu niczego nie cofa w KSeF, a unieważnienie certyfikatu w KSeF nie usuwa rekordu z Twojego magazynu.

## Związek z XAdES i szyfrowaniem

XAdES używa certyfikatu do podpisania XML uwierzytelniania. Rejestracja dotyczy certyfikatów wydawanych przez KSeF. Publiczne certyfikaty szyfrowania to jeszcze coś innego: publiczne klucze KSeF, którymi SDK szyfruje klucze przesyłanych danych.

Jeśli problem dotyczy kluczy prywatnych, CSR, numerów seryjnych wydanych certyfikatów albo certyfikatu typu Offline, należy do zarządzania certyfikatami. Jeśli dotyczy `public_key_id`, szyfrowania tokena, szyfrowania sesji albo odszyfrowania paczki eksportu, należy do szyfrowania.

## Powiązane strony

- [Zarządzanie certyfikatami](../how-to-guides/manage-certificates.md): rejestracja, pobieranie, wyszukiwanie i unieważnianie certyfikatów KSeF.
- [Własny magazyn certyfikatów podpisu](../how-to-guides/write-signing-certificate-store.md): magazyn, który trzyma Twój certyfikat i klucz.
- [Konfiguracja magazynu certyfikatów](../how-to-guides/configure-certificate-store.md): pamięć publicznych certyfikatów szyfrowania KSeF.
- [XAdES](xades.md): podpis XML oparty na certyfikacie podczas uwierzytelniania.
- [Szyfrowanie](encryption.md): publiczne certyfikaty szyfrowania KSeF i zmiana kluczy.
- [Tokeny i uprawnienia](permissions.md): dlaczego tożsamość przy uwierzytelnianiu i uprawnienia operacji są osobne.
