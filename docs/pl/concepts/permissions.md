---
title: Tokeny i uprawnienia
description: Tokeny KSeF, zakresy uprawnień, nadania, cofnięcia i status operacji.
---

Uwierzytelnienie potwierdza tożsamość. Uprawnienia określają, co ta tożsamość może zrobić. Token KSeF zbiera wybrany zestaw uprawnień w sekret, którego można użyć wielokrotnie. Poprawne uwierzytelnienie nie gwarantuje, że kolejna operacja zostanie dopuszczona.

Uprawnienia określają, co podmiot, osoba, jednostka, jednostka unijna, podmiot uprawniony albo jednostka podrzędna mogą zrobić w kontekście logowania. Wiele zmian uprawnień jest asynchronicznych: nadanie albo cofnięcie zwraca numer referencyjny operacji, a aplikacja dopiero potem sprawdza jej status.

W kodzie uprawnień jawnie wskaż identyfikator celu, zakres uprawnienia i kontekst logowania. Łatwiej wtedy odtworzyć historię i wrócić do pracy po błędzie.

## Tokeny

`auth.tokens` tworzy, listuje, sprawdza i unieważnia tokeny KSeF. Wygenerowanie tokena od razu zwraca obiekt `GeneratedToken` z jednorazową wartością tokena i numerem referencyjnym. Zapisz sekret, zanim jawnie wywołasz `wait()` na tym obiekcie. Dzięki temu limit czasu albo błąd połączenia podczas sprawdzania statusu nie skasuje jedynej kopii tokena.

Wygenerowany token ma stały zestaw uprawnień. Gdy uprawnienia mają się zmienić, wygeneruj nowy token i unieważnij stary po przejściu na nowy. Token można wygenerować tylko w obsługiwanych kontekstach logowania, takich jak NIP albo identyfikator wewnętrzny (`InternalId`). Wcześniej trzeba uwierzytelnić się podpisem XAdES.

Tokeny trzymaj jak sekrety. Nie zapisuj ich w repozytorium. Lepiej trzymać je w zmiennych środowiskowych albo w menedżerze sekretów. Profil może wskazywać zmienną środowiskową z tokenem, żeby CLI i Python korzystały ze wspólnej konfiguracji bez umieszczania sekretu w kodzie.

:::caution[Dane uwierzytelniające to nie uprawnienie]
Token albo certyfikat może poprawnie potwierdzić tożsamość, a KSeF i tak odmówi operacji, jeśli nie zgadza się kontekst logowania, identyfikator celu albo zakres uprawnień.
:::

## Uprawnienia

API uprawnień jest szczegółowe, bo KSeF rozróżnia rodzaje celów i zakresy. SDK ma osobne metody dla nadań osobie, jednostce, podmiotowi uprawnionemu, uprawnień pośrednich, jednostek podrzędnych i jednostek unijnych oraz odpowiadające im zapytania i cofnięcia.

Model uprawnień łączy identyfikator celu, typ uprawnienia i zasady przekazywania uprawnień dalej:

| Pojęcie | Skutek w projekcie |
| --- | --- |
| Identyfikator celu | Użyj właściwego rodzaju: NIP, PESEL, odcisk palca certyfikatu (`fingerprint`), NIP VAT UE albo identyfikator wewnętrzny. |
| Typ uprawnienia | Trzymaj skończony wybór wprost, na przykład przeglądanie faktur, wystawianie faktur, przeglądanie uprawnień, zarządzanie uprawnieniami, zarządzanie jednostkami podrzędnymi, wykonywanie operacji egzekucyjnych albo przeglądanie historii sesji. |
| Uprawnienia bezpośrednie i pośrednie | Pytaj i cofaj tą metodą, która odpowiada sposobowi nadania. |
| Przekazanie dalej | `can_delegate` ma sens tylko tam, gdzie KSeF pozwala przekazać uprawnienie dalej. |
| Status operacji | Nadanie i cofnięcie zwracają obiekt `PermissionOperation`. Wywołaj `wait()`, zanim uznasz, że uprawnienie się zmieniło. |

```python
from ksef2.models import EntityPermission

operation = auth.permissions.grant_entity(
    subject_value="5261040828",
    permissions=[EntityPermission(type="invoice_read", can_delegate=False)],
    description="Accounting office read access",
    entity_name="Accounting Sp. z o.o.",
)

status = operation.wait()
print(status.status.code, status.status.description)
```

Przy odmowie sprawdź:

- wybrane środowisko;
- identyfikator podatnika albo identyfikator kontekstu, na który się uwierzytelniłeś;
- nazwę profilu i rodzaj danych uwierzytelniających;
- zestaw uprawnień tokena;
- identyfikator celu i zakres uprawnienia;
- czy operacja nadania albo cofnięcia już się zakończyła.

## Powiązane strony

- [Zarządzanie tokenami](../how-to-guides/manage-tokens.md): generowanie, lista, sprawdzenie i unieważnienie tokenów KSeF.
- [Konfiguracja uprawnień](../how-to-guides/configure-permissions.md): nadawanie, wyszukiwanie, sprawdzanie i cofanie uprawnień.
- [Operacje](../reference/operations.md): numery referencyjne, sprawdzanie statusu, ponowienia i statusy.
- [Metody uwierzytelniania](authentication-methods.md): różnica między tożsamością a uprawnieniami sprawdzanymi przy operacjach chronionych.
