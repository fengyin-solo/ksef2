---
title: Profile
description: Wspólna lokalna konfiguracja profili ksef2-cli i uwierzytelniania w SDK.
---

Profil to nazwane, lokalne ustawienia uwierzytelniania, z których korzystają zarówno `ksef2-cli`, jak i SDK. Sięgnij po niego, gdy na tej samej stacji roboczej uruchamiasz polecenia w terminalu i skrypty Pythona dla tego samego kontekstu logowania.

W profilu zostają tylko dane, które nie są sekretem: środowisko, NIP, metoda uwierzytelnienia, ścieżki certyfikatów, odstęp i limit prób przy cyklicznym sprawdzaniu statusu oraz nazwa zmiennej środowiskowej z sekretem. Nie zapisuj w nim tokenu KSeF, hasła klucza prywatnego ani hasła PKCS#12.

:::tip[Profile są do pracy lokalnej]
Profil upraszcza powtarzalną pracę na własnym komputerze. W CI i w aplikacji na serwerze zwykle czytelniej jest podać konfigurację przez system wdrożeniowy, a sekrety czytać wprost ze zmiennych środowiskowych.
:::

## Utwórz profil w CLI

CLI najwygodniej tworzy i pokazuje plik profili.

```bash
ksef2 profile create test-company \
  --env test \
  --nip 5261040828 \
  --test-cert

ksef2 profile current
ksef2 profile show test-company
```

Profil tokenowy i certyfikatowy zapisuje nazwę zmiennej środowiskowej z sekretem, a nie samą wartość:

```bash
export KSEF2_TOKEN=podmien-na-prawdziwy-token-ksef

ksef2 profile create prod-token \
  --env production \
  --nip 5261040828 \
  --token-env KSEF2_TOKEN
```

**Zobacz też:**

- [Konfiguracja CLI](../../cli/guides/configuration.md): Twórz, wybieraj, sprawdzaj i usuwaj profile w ksef2-cli.
- [Uwierzytelnianie CLI](../../cli/guides/authentication.md): Wybierz profil tokenowy, certyfikat testowy, PEM XAdES albo PKCS#12 z poziomu polecenia.

## Uwierzytelnij się profilem

`with_profile()` czyta ten sam plik profili co CLI. Wywołanie bez nazwy bierze profil wybrany jako aktywny.

```python
from ksef2 import Client, Environment

with Client(Environment.TEST) as client:
    auth = client.authentication.with_profile()
```

Podaj nazwę, gdy to jedno wywołanie ma pominąć aktywny profil:

```python
from ksef2 import Client, Environment

with Client(Environment.TEST) as client:
    auth = client.authentication.with_profile("test-company")
```

Środowisko klienta głównego musi być takie samo jak środowisko profilu. Profil `test` idzie z `Client(Environment.TEST)`, profil `demo` z `Client(Environment.DEMO)`, a profil `production` z `Client(Environment.PRODUCTION)`.

Gdy to profil ma wybrać środowisko klienta, wczytaj go najpierw:

```python
from ksef2 import Client
from ksef2.profiles import load_cli_profile

profile_name, profile = load_cli_profile("prod-token")

with Client(profile.sdk_environment) as client:
    auth = client.authentication.with_profile(profile_name)
```

Klient asynchroniczny korzysta z tego samego pliku i z tej samej kolejności wyboru:

```python
import asyncio

from ksef2 import AsyncClient, Environment

async def main() -> None:
    async with AsyncClient(Environment.TEST) as client:
        auth = await client.authentication.with_profile("test-company")

asyncio.run(main())
```

## Kolejność wyboru profilu

SDK wybiera profil tak samo jak `ksef2-cli`:

1. Jawna nazwa przekazana do `with_profile("name")`.
2. Zmienna `KSEF2_PROFILE` w środowisku procesu.
3. Pole `active_profile` w lokalnym pliku profili.

Domyślna ścieżka pliku:

```text
~/.config/ksef2/config.toml
```

Istniejący plik `~/.config/ksef2-cli/config.toml` nadal jest czytany, żeby zachować zgodność ze starszym układem.

Ustaw `KSEF2_CONFIG` albo podaj `config_path`, gdy plik leży gdzie indziej:

```python
from ksef2 import Client, Environment

with Client(Environment.PRODUCTION) as client:
    auth = client.authentication.with_profile(
        "prod-token",
        config_path="./local.ksef2.toml",
    )
```

## Zarządzaj profilami z kodu SDK

Użyj `ProfileStore`, gdy narzędzie w Pythonie ma tworzyć, aktualizować, wybierać albo sprawdzać ten sam plik co CLI. Gdy potrzebujesz tylko uwierzytelnienia, wystarczy `with_profile()`.

```python
from ksef2 import Environment
from ksef2.profiles import Profile, ProfileStore, TokenProfileAuth

store = ProfileStore.default()
store.save(
    "prod-token",
    Profile(
        environment=Environment.PRODUCTION,
        nip="5261040828",
        auth=TokenProfileAuth(
            token_env="KSEF2_TOKEN",
            context_type="nip",
        ),
        poll_interval=2.0,
        max_poll_attempts=90,
    ),
    activate=True,
    overwrite=True,
)
```

Profil z certyfikatem testowym:

```python
from ksef2 import Environment
from ksef2.profiles import Profile, ProfileStore, TestCertificateProfileAuth

store = ProfileStore.default()
store.save(
    "test-company",
    Profile(
        environment=Environment.TEST,
        nip="5261040828",
        auth=TestCertificateProfileAuth(),
    ),
    activate=True,
    overwrite=True,
)
```

Lista, odczyt, wybór i usunięcie też idą przez magazyn profili:

```python
from ksef2.profiles import ProfileStore

store = ProfileStore.default()

profiles = store.list()
current = store.current()
profile = store.get("prod-token")
store.use("prod-token")
store.delete("old-profile")
```

`current` to `None` albo krotka `(name, profile)`.

## Co zawiera konfiguracja

Zapisany plik używa tych samych nazw pól co publiczne modele profili SDK:

```toml
active_profile = "prod-token"

[profiles.prod-token]
environment = "production"
nip = "5261040828"
poll_interval = 2.0
max_poll_attempts = 90

[profiles.prod-token.auth]
type = "token"
token_env = "KSEF2_TOKEN"
context_type = "nip"
```

Profil XAdES zapisuje ścieżki oraz nazwy zmiennych środowiskowych z hasłami:

```python
from ksef2 import Environment
from ksef2.profiles import Profile, ProfileStore, XadesP12ProfileAuth

store = ProfileStore.default()
store.save(
    "prod-p12",
    Profile(
        environment=Environment.PRODUCTION,
        nip="5261040828",
        auth=XadesP12ProfileAuth(
            p12="signing-credentials.p12",
            p12_password_env="KSEF2_P12_PASSWORD",
        ),
    ),
    activate=False,
    overwrite=True,
)
```

## Starsze i nieznane klucze

Profil zapisany przez ksef2-cli 0.0.2 może mieć płaski klucz `auth_timeout` (sekundy). SDK nadal go przyjmuje, zamienia na `max_poll_attempts` tym samym wzorem co `with_profile()` (`timeout = max_poll_attempts * poll_interval`, czyli `max_poll_attempts = ceil(auth_timeout / poll_interval)`, domyślny odstęp to 1 sekunda) i zgłasza `DeprecationWarning`. Jawnie podane `max_poll_attempts` ma pierwszeństwo. Klucz `auth_timeout` zniknie w ksef2 2.0.0. Zastąp go kluczem `max_poll_attempts` i, jeśli trzeba, `poll_interval`.

Każdy inny nieznany klucz w profilu jest pomijany bez ostrzeżenia. Ustawienia własne narzędzia zapisane obok pól SDK nie psują wczytywania.

## Zalecany przepływ

1. Umieść sekrety w zmiennych środowiskowych.

   Przykłady: `KSEF2_TOKEN`, `KSEF2_KEY_PASSWORD` i `KSEF2_P12_PASSWORD`.

2. Utwórz albo wybierz profil przez `ksef2-cli`.

   Dzięki temu polecenia w terminalu i skrypty Pythona korzystają z tych samych ustawień.

3. Utwórz klienta SDK dla tego samego środowiska co profil.

   SDK sprawdza to przed uwierzytelnieniem.

4. Wywołaj `client.authentication.with_profile()`.

   Zwrócony klient uwierzytelniony działa tak samo jak po innych metodach uwierzytelnienia SDK.

## Powiązane strony

- [Szybki start](../getting-started/quickstart.md): Uruchom pierwszy przepływ wysyłki i pobrania, a potem podepnij go pod profil.
- [Uwierzytelnianie](authenticate.md): Porównaj profil z bezpośrednim tokenem, certyfikatem testowym i uwierzytelnianiem XAdES.
