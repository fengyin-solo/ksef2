---
title: Zarządzanie limitami
description: Odczytuj i nadpisuj limity kontekstu logowania, podmiotu i liczby żądań API KSeF przez ksef2.
---

Użyj `auth.limits`, żeby sprawdzić limity, które KSeF stosuje do bieżącego uwierzytelnionego kontekstu logowania. Metod nadpisywania używaj tylko w jawnych przepływach administracyjnych.

## Odczytaj obowiązujące limity

Odczytaj bieżące limity, zanim wybierzesz wielkość paczki, częstość sprawdzania statusu albo przepływ wystawiania certyfikatów.

### Limity sesji

```python
context = auth.limits.get_context_limits()

# ContextLimits
# {
#   "online_session": {
#     "max_invoice_size_mb": 10,
#     "max_invoice_with_attachment_size_mb": 20,
#     "max_invoices": 100
#   },
#   "batch_session": {
#     "max_invoice_size_mb": 10,
#     "max_invoice_with_attachment_size_mb": 20,
#     "max_invoices": 1000
#   }
# }

print(context.online_session.max_invoices)
print(context.batch_session.max_invoice_size_mb)
```

### Limity podmiotu

```python
subject = auth.limits.get_subject_limits()

print(subject.certificate)
print(subject.enrollment)
```

### Limity liczby żądań API

```python
rate = auth.limits.get_api_rate_limits()

print(rate.invoice_send.per_minute)
print(rate.invoice_metadata.per_minute)
print(rate.invoice_download.per_hour)
```

## Nadpisz limity sesji

Nadpisań limitów sesji używaj tylko wtedy, gdy uwierzytelniony kontekst logowania może zarządzać limitami, a zmiana jest częścią kontrolowanego testu albo procedury administracyjnej.

```python
from ksef2.models import CollectiveIdentifierLimits, ContextLimits, SessionLimits

limits = ContextLimits(
    collective_identifier=CollectiveIdentifierLimits(max_invoices=1000),
    online_session=SessionLimits(
        max_invoice_size_mb=10,
        max_invoice_with_attachment_size_mb=20,
        max_invoices=100,
    ),
    batch_session=SessionLimits(
        max_invoice_size_mb=10,
        max_invoice_with_attachment_size_mb=20,
        max_invoices=1000,
    ),
)

auth.limits.set_session_limits(limits=limits)
```

Zresetuj nadpisanie po zakończeniu testu albo zmiany tymczasowej:

```python
auth.limits.reset_session_limits()
```

## Użyj produkcyjnych domyślnych limitów liczby żądań

Użyj `set_production_rate_limits()`, gdy środowisko zbliżone do testowego ma skopiować produkcyjne domyślne limity liczby żądań API.

```python
auth.limits.set_production_rate_limits()

rate = auth.limits.get_api_rate_limits()
print(rate.invoice_send.per_minute)
```

:::caution[Nie ukrywaj zmian limitów]
Nadpisania limitów wpływają na inne procesy używające tego samego kontekstu logowania. Trzymaj je w procedurach operacyjnych, dopisz oczekiwany reset i nie ukrywaj ich w zwykłym kodzie wysyłki faktur.
:::

## Zalecany przebieg

1. Odczytaj obowiązujące limity, zanim wybierzesz wielkość paczki, sposób przesłania albo częstość sprawdzania statusu.

2. Zostaw produkcyjne wartości domyślne, chyba że kontrolowany test albo przepływ administratora wymaga nadpisania.

3. Nadpisania stosuj z jawnego kodu operacyjnego.

4. Sprawdź nowe limity po ich zastosowaniu.

5. Zresetuj tymczasowe nadpisania po teście albo oknie prac utrzymaniowych.

## Następne strony

- [Wysyłanie faktur](send-invoices.md): sesja interaktywna i wsadowa z uwzględnieniem bieżących limitów.
- [Limity i ponawianie żądań](../concepts/limits.md): jak limity KSeF wpływają na paczkę, sprawdzanie statusu i ponowienia.
- [Konfiguracja klienta](client-setup.md): limity czasu i ponowienia klienta z uwzględnieniem limitów KSeF.
