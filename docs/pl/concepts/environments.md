---
title: Środowiska
description: Wybór środowiska testowego, przedprodukcyjnego (Demo) i produkcyjnego w ksef2.
---

Każdy przepływ KSeF działa w jawnie wybranym środowisku. Wskazujesz je przy tworzeniu klienta głównego. Dane uwierzytelniające, profile, zapisany stan sesji i adresy pobierania zostaw w tym samym środowisku.

| Środowisko | Oficjalna rola | Adres bazowy | Typowe użycie |
| --- | --- | --- | --- |
| `Environment.TEST` | Środowisko testowe (release candidate) | `https://api-test.ksef.mf.gov.pl/v2` | Praca lokalna, CI, certyfikaty testowe generowane przez SDK, dane testowe. |
| `Environment.DEMO` | Środowisko przedprodukcyjne (Demo) | `https://api-demo.ksef.mf.gov.pl/v2` | Testy integracyjne przy zachowaniu zbliżonym do produkcji, z osobnymi danymi uwierzytelniającymi. |
| `Environment.PRODUCTION` | Środowisko produkcyjne | `https://api.ksef.mf.gov.pl/v2` | Rzeczywiste faktury podatnika i produkcyjne dane uwierzytelniające. |

:::caution[Stan środowiska nie przechodzi między środowiskami]
Nie przenoś tokenów, założeń o certyfikatach, numerów referencyjnych sesji ani adresów paczek między środowiskami. Każde środowisko trzymaj osobno.
:::

## Czym różnią się środowiska

Środowisko testowe jest celowo luźniejsze niż przedprodukcyjne (Demo) i produkcyjne. Obsługuje dane testowe, certyfikat testowy generowany przez SDK i scenariusze z certyfikatami samopodpisanymi. Dane ze środowiska testowego nie są prywatnym archiwum, więc nie wysyłaj tam rzeczywistych faktur.

Środowisko przedprodukcyjne (Demo) jest bliższe produkcji, ale nadal nie służy do faktur o pełnej mocy prawnej. Środowisko produkcyjne jest jedynym miejscem na rzeczywiste faktury podatnika. Adresy zwracane przez KSeF, na przykład linki do paczek, wskazują host tego środowiska, które je utworzyło.

Od środowiska zależy też, które struktury faktur są dostępne:

| Środowisko | Struktury faktur |
| --- | --- |
| TEST | `FA(2)`, `FA(3)`, `FA_PEF(3)`, `FA_KOR_PEF(3)` |
| DEMO | `FA(3)`, `FA_PEF(3)`, `FA_KOR_PEF(3)` |
| PRODUCTION | `FA(3)`, `FA_PEF(3)`, `FA_KOR_PEF(3)` |

## Co wybiera środowisko

Środowisko wybiera adres bazowy API KSeF. Do tego samego środowiska należą dane uwierzytelniające, profile, certyfikaty, dane testowe, numery referencyjne sesji, numery KSeF i eksporty.

```python
from ksef2 import Client, Environment

client = Client(Environment.TEST)
```

`client.testdata` jest dostępne tylko w `Environment.TEST`. Uwierzytelnianie certyfikatem testowym generowanym przez SDK też działa tylko w środowisku testowym.

## Rozdzielenie danych

Dane uwierzytelniające są przypisane do środowiska. Profil utworzony dla środowiska produkcyjnego nie powinien być wybrany przez klienta środowiska testowego. `with_profile()` odrzuca taką niezgodność.

Zapisany stan oznaczaj środowiskiem, które go utworzyło:

- nazwa profilu uwierzytelniania;
- identyfikator podatnika albo identyfikator kontekstu;
- numer referencyjny sesji interaktywnej albo wsadowej;
- numer referencyjny faktury;
- numer KSeF;
- numer referencyjny eksportu.

## Powiązane strony

- [Działanie SDK](overview.md): główne obiekty SDK i podział przepływów.
- [Konfiguracja klienta](../how-to-guides/client-setup.md): wybór środowiska testowego, przedprodukcyjnego (Demo) albo produkcyjnego przy tworzeniu klienta.
- [Uwierzytelnianie](../how-to-guides/authenticate.md): dane uwierzytelniające właściwe dla wybranego środowiska.
- [Tworzenie i zamykanie klientów](../reference/client-lifecycle.md): jak wybór środowiska wpływa na klientów SDK.
