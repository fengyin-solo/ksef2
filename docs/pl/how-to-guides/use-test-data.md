---
title: Dane testowe
description: Twórz podmioty, osoby, uprawnienia, flagi załączników i blokady kontekstów w środowisku testowym.
---

Używaj `client.testdata` tylko z `Environment.TEST`. Te metody zmieniają dane środowiska testowego KSeF, dzięki czemu testy i pokazy mogą tworzyć znane konteksty logowania.

## Utwórz dane ręcznie

Metod bezpośrednich używaj dla wspólnych danych testowych, które mają przetrwać wiele uruchomień testów.

### Podmiot

```python
client.testdata.create_subject(
    nip="5261040828",
    subject_type="vat_group",
    description="Sandbox company",
)

client.testdata.enable_attachments(nip="5261040828")
```

### Osoba

```python
client.testdata.create_person(
    nip="5261040828",
    pesel="90010112345",
    description="Sandbox person",
)
```

### Blokada kontekstu

```python
from ksef2.models import AuthContextIdentifier

context = AuthContextIdentifier(type="nip", value="5261040828")

client.testdata.block_context(context=context)
client.testdata.unblock_context(context=context)
```

Usuń wspólne dane jawnie, gdy nie są już potrzebne:

```python
client.testdata.delete_person(nip="5261040828")
client.testdata.delete_subject(nip="5261040828")
```

## Sprzątanie po wyjściu z bloku

`temporal()` zapisuje zmiany i po wyjściu z bloku próbuje je posprzątać. Sprzątanie jest podejmowane w miarę możliwości, bez gwarancji, że każda zmiana zniknie.

### Podmiot i załączniki

```python
with client.testdata.temporal() as data:
    data.create_subject(
        nip="5261040828",
        subject_type="vat_group",
        description="Integration test subject",
    )
    data.enable_attachments(nip="5261040828")
```

### Uprawnienia

```python
from ksef2.models import Identifier, Permission

with client.testdata.temporal() as data:
    data.grant_permissions(
        permissions=[
            Permission(type="invoice_read", description="Read invoices"),
        ],
        grant_to=Identifier(type="nip", value="1111111111"),
        in_context_of=Identifier(type="nip", value="5261040828"),
    )
```

### Blokada kontekstu

```python
from ksef2.models import AuthContextIdentifier

context = AuthContextIdentifier(type="nip", value="5261040828")

with client.testdata.temporal() as data:
    data.block_context(context=context)
```

:::caution[Tylko TEST]
Moduł danych testowych służy do przygotowania danych w środowisku testowym. Nie buduj na nim przepływów produktu w środowisku przedprodukcyjnym (Demo) ani produkcyjnym.
:::

## Generowanie identyfikatorów

`ksef2.testdata` generuje numery NIP i PESEL z poprawną sumą kontrolną, dzięki czemu każde uruchomienie testów może użyć nowych podmiotów w środowisku testowym:

```python
from ksef2.testdata import generate_nip, generate_pesel

nip = generate_nip()
pesel = generate_pesel()
```

## Zalecany przebieg

1. Utwórz tylko te podmioty, osoby, uprawnienia, flagi załączników albo blokady kontekstu logowania, których wymaga test.

2. Użyj `temporal()` dla danych, które powinny zostać posprzątane automatycznie.

3. Użyj bezpośrednich metod tworzenia i usuwania dla danych wspólnych dla wielu uruchomień testów.

4. Wygenerowane identyfikatory trzymaj w konfiguracji testów, nie w konfiguracji produkcyjnej.

## Następne strony

- [Konfiguracja klienta](client-setup.md): klient główny środowiska testowego, zanim użyjesz `testdata`.
- [Uwierzytelnianie](authenticate.md): uwierzytelnianie w kontekstach logowania utworzonych przez metody danych testowych.
- [Konfiguracja uprawnień](configure-permissions.md): produkcyjne API uprawnień po sprawdzeniu nadań w środowisku testowym.
