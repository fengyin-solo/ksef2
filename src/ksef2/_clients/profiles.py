"""Profile configuration shared by SDK authentication clients."""

import datetime
import os
import tomllib
from collections.abc import Callable, Mapping
from enum import StrEnum
from types import MappingProxyType
import json
import math
from pathlib import Path
import re
import warnings
from typing import Self, cast

from cryptography.x509 import Certificate
from pydantic import (
    BaseModel,
    Field,
    PrivateAttr,
    ValidationError,
    field_validator,
    model_validator,
)

from ksef2._config import Environment
from ksef2._core import exceptions
from ksef2._core.xades import (
    XAdESPrivateKey,
    load_certificate_and_key_from_p12,
    load_certificate_from_pem,
    load_private_key_from_pem,
)
from ksef2._domain.models.auth import ContextIdentifierType, ContextIdentifierTypeEnum

CONFIG_ENV_VAR = "KSEF2_CONFIG"
PROFILE_ENV_VAR = "KSEF2_PROFILE"
CONFIG_FILE_MODE = 0o600
PROFILE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
CONFIG_DIR_NAME = "ksef2"
LEGACY_CONFIG_DIR_NAME = "ksef2-cli"

_ENVIRONMENT_TO_PROFILE = {
    Environment.PRODUCTION: "production",
    Environment.DEMO: "demo",
    Environment.TEST: "test",
}


class ProfileEnvironment(StrEnum):
    """KSeF environment names as written in profile files."""

    PRODUCTION = "production"
    DEMO = "demo"
    TEST = "test"


class ProfileAuthType(StrEnum):
    """Authentication methods a profile can use."""

    TOKEN = "token"
    TEST_CERTIFICATE = "test_certificate"
    XADES_PEM = "xades_pem"
    XADES_P12 = "xades_p12"


# ``auth_timeout`` is consumed by the deprecation mapping below, so rewriting a
# profile drops it instead of carrying the deprecated key over.
_MIGRATED_KEYS = frozenset({"auth_timeout"})


class _UnknownKeyPreservingModel(BaseModel):
    """Base for config models that keep unrecognised keys across rewrites.

    The SDK ignores keys it does not model, but the config file is shared with
    ``ksef2-cli`` and other tools. Unrecognised keys are captured on validation
    and written back verbatim by ``render_profile_config()``.
    """

    _unknown_keys: dict[str, object] = PrivateAttr(default_factory=dict)
    """Keys present in the source document that this model does not define."""

    @model_validator(mode="wrap")
    @classmethod
    def _capture_unknown_keys(
        cls, data: object, handler: Callable[[object], Self]
    ) -> Self:
        model = handler(data)
        if isinstance(data, Mapping):
            known = set(cls.model_fields)
            entries = cast(Mapping[object, object], data)
            model._unknown_keys = {
                key: value
                for key, value in entries.items()
                if isinstance(key, str)
                and key not in known
                and key not in _MIGRATED_KEYS
            }
        return model

    def unknown_keys(self) -> Mapping[str, object]:
        """Return the config keys this model read but does not define.

        The SDK ignores these keys, but rewriting the config file keeps them.

        Returns:
            Unknown keys of this config table, in document order.
        """
        return MappingProxyType(self._unknown_keys)


class ProfileAuthConfig(_UnknownKeyPreservingModel):
    """Authentication settings of a profile.

    Which fields are required depends on ``type``: token profiles need ``token_env``, PEM XAdES profiles need ``cert`` and ``key``, and PKCS#12 profiles need ``p12``. Secrets are never stored; the ``*_env`` fields name the environment variables that hold them.
    """

    type: ProfileAuthType
    """Authentication method."""
    token_env: str | None = Field(
        default=None, description="Environment variable containing a KSeF token."
    )
    """Name of the environment variable holding the KSeF token."""
    context_type: ContextIdentifierTypeEnum | ContextIdentifierType | None = Field(
        default=None, description="Token-auth context type."
    )
    """Kind of context identifier for token authentication; defaults to ``nip``."""
    cert: str | Path | None = Field(
        default=None, description="PEM certificate path for XAdES authentication."
    )
    """Path to the PEM certificate for XAdES authentication."""
    key: str | Path | None = Field(
        default=None, description="PEM private key path for XAdES authentication."
    )
    """Path to the PEM private key for XAdES authentication."""
    key_password_env: str | None = Field(
        default=None,
        description="Environment variable containing an encrypted PEM key password.",
    )
    """Name of the environment variable holding the password of an encrypted PEM key."""
    p12: str | Path | None = Field(
        default=None, description="PKCS#12/PFX archive path for XAdES authentication."
    )
    """Path to the PKCS#12/PFX archive for XAdES authentication."""
    p12_password_env: str | None = Field(
        default=None,
        description="Environment variable containing a PKCS#12/PFX archive password.",
    )
    """Name of the environment variable holding the PKCS#12/PFX archive password."""

    @field_validator("cert", "key", "p12", mode="after")
    @classmethod
    def _expand_path(cls, value: str | Path | None) -> Path | None:
        return Path(value).expanduser() if value else None

    @model_validator(mode="after")
    def _validate_auth_fields(self) -> Self:
        if self.type is ProfileAuthType.TOKEN and not self.token_env:
            raise ValueError("Token profiles require auth.token_env.")
        if self.type is ProfileAuthType.XADES_PEM and (
            self.cert is None or self.key is None
        ):
            raise ValueError("PEM XAdES profiles require auth.cert and auth.key.")
        if self.type is ProfileAuthType.XADES_P12 and self.p12 is None:
            raise ValueError("PKCS#12/PFX profiles require auth.p12.")
        return self


class TokenProfileAuth(ProfileAuthConfig):
    """Authentication settings for token authentication; ``type`` defaults to ``token``."""

    type: ProfileAuthType = ProfileAuthType.TOKEN
    """Authentication method; ``token``."""


class TestCertificateProfileAuth(ProfileAuthConfig):
    """Authentication settings for the SDK-generated TEST certificate; ``type`` defaults to ``test_certificate``."""

    type: ProfileAuthType = ProfileAuthType.TEST_CERTIFICATE
    """Authentication method; ``test_certificate``."""


class XadesPemProfileAuth(ProfileAuthConfig):
    """Authentication settings for XAdES with a PEM certificate and key; ``type`` defaults to ``xades_pem``."""

    type: ProfileAuthType = ProfileAuthType.XADES_PEM
    """Authentication method; ``xades_pem``."""


class XadesP12ProfileAuth(ProfileAuthConfig):
    """Authentication settings for XAdES with a PKCS#12/PFX archive; ``type`` defaults to ``xades_p12``."""

    type: ProfileAuthType = ProfileAuthType.XADES_P12
    """Authentication method; ``xades_p12``."""


class ProfileConfig(_UnknownKeyPreservingModel):
    """One named profile: environment, NIP and authentication settings.

    Profiles are shared with ``ksef2-cli``, so both read the same config file.

    Deprecated:
        The flat ``auth_timeout`` key written by ksef2-cli 0.0.2 may be removed no earlier than ksef2 2.0.0; use ``max_poll_attempts`` and optionally ``poll_interval`` instead.
    """

    environment: ProfileEnvironment | Environment
    """Environment the profile targets; ``Environment`` values are normalized to their profile names."""
    nip: str
    """NIP of the context to authenticate in."""
    auth: ProfileAuthConfig
    """Authentication settings."""
    poll_interval: float | None = Field(
        default=None, ge=0.1, description="Authentication polling interval."
    )
    """Delay in seconds between authentication status checks (at least 0.1); ``None`` for the default."""
    max_poll_attempts: int | None = Field(
        default=None, ge=1, description="Authentication polling attempts."
    )
    """Maximum number of authentication status checks (at least 1); ``None`` for the default."""

    @model_validator(mode="before")
    @classmethod
    def _map_legacy_auth_timeout(cls, data: object) -> object:
        """Accept the flat ``auth_timeout`` key written by ksef2-cli 0.0.2.

        ``with_profile()`` waits ``max_poll_attempts * poll_interval`` seconds, so
        the equivalent attempt count is ``ceil(auth_timeout / poll_interval)``.
        Explicit ``max_poll_attempts`` wins. Other unknown keys are ignored by
        the SDK and kept as-is when the file is rewritten.
        """
        if not isinstance(data, dict):
            return data
        profile_data = cast(dict[str, object], data)
        if "auth_timeout" not in profile_data:
            return profile_data

        warnings.warn(
            "The `auth_timeout` profile key is deprecated and will be removed "
            "no earlier than ksef2 2.0.0; use `max_poll_attempts` (and optionally "
            "`poll_interval`) instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        timeout = profile_data["auth_timeout"]
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int | float)
            or not math.isfinite(timeout)
            or timeout <= 0
            or profile_data.get("max_poll_attempts") is not None
        ):
            return profile_data

        interval = profile_data.get("poll_interval")
        if isinstance(interval, bool) or not isinstance(interval, int | float):
            interval = 1.0
        if interval <= 0:
            return profile_data
        mapped = dict(profile_data)
        mapped["max_poll_attempts"] = max(1, math.ceil(timeout / interval))
        return mapped

    @field_validator("environment", mode="before")
    @classmethod
    def _normalize_environment(cls, value: object) -> object:
        if isinstance(value, Environment):
            return _ENVIRONMENT_TO_PROFILE[value]
        return value

    @property
    def sdk_environment(self) -> Environment:
        """Return the profile environment as an SDK ``Environment``.

        Returns:
            The matching ``Environment`` value.
        """
        if isinstance(self.environment, Environment):
            return self.environment
        return _profile_environment_to_sdk(self.environment)


class CliProfileConfig(_UnknownKeyPreservingModel):
    """Contents of the ``ksef2-cli`` config file: profiles and the active profile name."""

    active_profile: str | None = None
    """Name of the profile used when none is selected; ``None`` when no profile is active."""
    profiles: dict[str, ProfileConfig] = Field(default_factory=dict)
    """Profiles keyed by name."""

    @model_validator(mode="after")
    def _validate_active_profile(self) -> Self:
        if self.active_profile is not None and self.active_profile not in self.profiles:
            raise ValueError(f"Active profile {self.active_profile!r} is not defined.")
        return self


Profile = ProfileConfig


class ProfileStore:
    """Read and write local profiles compatible with ``ksef2-cli``."""

    def __init__(self, path: str | Path | None = None) -> None:
        """Create the ProfileStore.

        Args:
            path: Path of the config file; the default location is used when ``None``.
        """
        self.path = _resolve_profile_config_path(path)

    @classmethod
    def default(cls) -> Self:
        """Create a store at the default config location.

        Returns:
            A store reading and writing ``KSEF2_CONFIG``, or the default ``ksef2`` config file.
        """
        return cls()

    def load(self) -> CliProfileConfig:
        """Read the config file.

        Returns:
            The parsed config; empty when the file does not exist.

        Raises:
            KSeFValidationError: If the file is not valid TOML or does not match the profile schema.
        """
        return load_profile_config(self.path)

    def save(
        self,
        name: str,
        profile: ProfileConfig,
        *,
        activate: bool = True,
        overwrite: bool = False,
    ) -> ProfileConfig:
        """Add or replace a profile and write the config file.

        Args:
            name: Name of the profile.
            profile: Profile to store.
            activate: Whether to make it the active profile.
            overwrite: Whether to replace an existing profile with the same name.

        Returns:
            The stored profile.

        Raises:
            KSeFValidationError: If the profile exists and ``overwrite`` is false, or the file cannot be read or written.
        """
        config = self.load()
        if name in config.profiles and not overwrite:
            raise exceptions.KSeFValidationError(
                f"ksef2-cli profile {name!r} already exists.",
                config_path=str(self.path),
                profile_name=name,
            )

        config.profiles[name] = profile
        if activate:
            config.active_profile = name
        write_profile_config(self.path, config)
        return profile

    def get(self, name: str) -> ProfileConfig:
        """Look up a profile by name.

        Args:
            name: Name of the profile.

        Returns:
            The profile.

        Raises:
            KSeFValidationError: If the profile is not defined.
        """
        config = self.load()
        profile = config.profiles.get(name)
        if profile is None:
            raise exceptions.KSeFValidationError(
                f"ksef2-cli profile {name!r} is not defined in {self.path}.",
                config_path=str(self.path),
                profile_name=name,
            )
        return profile

    def list(self) -> dict[str, ProfileConfig]:
        """List all profiles.

        Returns:
            A copy of the profile mapping, keyed by name.
        """
        return dict(self.load().profiles)

    def current(self) -> tuple[str, ProfileConfig] | None:
        """Return the active profile.

        Returns:
            The active profile's name and settings, or ``None`` when no profile is active.
        """
        config = self.load()
        if config.active_profile is None:
            return None
        return config.active_profile, config.profiles[config.active_profile]

    def use(self, name: str) -> ProfileConfig:
        """Make a profile the active one.

        Args:
            name: Name of the profile.

        Returns:
            The newly active profile.

        Raises:
            KSeFValidationError: If the profile is not defined.
        """
        config = self.load()
        profile = config.profiles.get(name)
        if profile is None:
            raise exceptions.KSeFValidationError(
                f"ksef2-cli profile {name!r} is not defined in {self.path}.",
                config_path=str(self.path),
                profile_name=name,
            )

        config.active_profile = name
        write_profile_config(self.path, config)
        return profile

    def delete(self, name: str) -> ProfileConfig:
        """Remove a profile.

        If it was the active profile, no profile is active afterwards.

        Args:
            name: Name of the profile.

        Returns:
            The removed profile.

        Raises:
            KSeFValidationError: If the profile is not defined.
        """
        config = self.load()
        profile = config.profiles.pop(name, None)
        if profile is None:
            raise exceptions.KSeFValidationError(
                f"ksef2-cli profile {name!r} is not defined in {self.path}.",
                config_path=str(self.path),
                profile_name=name,
            )

        if config.active_profile == name:
            config.active_profile = None
        write_profile_config(self.path, config)
        return profile


def default_profile_config_path(environ: Mapping[str, str] | None = None) -> Path:
    """Resolve the default config file location.

    Uses ``KSEF2_CONFIG`` when set, otherwise ``ksef2/config.toml`` under ``XDG_CONFIG_HOME`` (or ``~/.config``), falling back to the legacy ``ksef2-cli`` directory when only that exists.

    Args:
        environ: Environment mapping to read; ``os.environ`` when ``None``.

    Returns:
        Path of the config file.
    """
    env = os.environ if environ is None else environ
    override = env.get(CONFIG_ENV_VAR)
    if override:
        return Path(override).expanduser()
    config_home = Path(env.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    config_dir = config_home.expanduser()
    config_path = config_dir / CONFIG_DIR_NAME / "config.toml"
    legacy_config_path = config_dir / LEGACY_CONFIG_DIR_NAME / "config.toml"
    if not config_path.exists() and legacy_config_path.exists():
        return legacy_config_path
    return config_path


def load_profile_config(path: str | Path | None = None) -> CliProfileConfig:
    """Read and validate a profile config file.

    Args:
        path: Path of the config file; the default location is used when ``None``.

    Returns:
        The parsed config; empty when the file does not exist.

    Raises:
        KSeFValidationError: If the file is not valid TOML or does not match the profile schema.
    """
    config_path = _resolve_profile_config_path(path)
    if not config_path.exists():
        return CliProfileConfig()

    try:
        payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
        return CliProfileConfig.model_validate(payload)
    except tomllib.TOMLDecodeError as exc:
        raise exceptions.KSeFValidationError(
            f"Invalid ksef2-cli profile config at {config_path}: {exc}",
            config_path=str(config_path),
        ) from exc
    except ValidationError as exc:
        raise exceptions.KSeFValidationError(
            f"Invalid ksef2-cli profile config at {config_path}: {exc}",
            config_path=str(config_path),
        ) from exc


def write_profile_config(path: str | Path, config: CliProfileConfig) -> None:
    """Write a profile config file, creating parent directories and restricting permissions to the owner.

    Args:
        path: Path of the config file.
        config: Config to write.

    Raises:
        KSeFValidationError: If the file cannot be written.
    """
    config_path = Path(path).expanduser()
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        _ = config_path.write_text(render_profile_config(config), encoding="utf-8")
        _ = config_path.chmod(CONFIG_FILE_MODE)
    except OSError as exc:
        raise exceptions.KSeFValidationError(
            f"Failed to write ksef2-cli profile config at {config_path}: {exc}",
            config_path=str(config_path),
        ) from exc


def render_profile_config(config: CliProfileConfig) -> str:
    """Render a profile config as TOML text.

    Args:
        config: Config to render.

    Returns:
        The TOML document.
    """
    lines = [
        "# ksef2-cli local profiles",
        "# CLI options override the selected profile for one invocation.",
        "# Store token and password secrets in environment variables.",
    ]
    if config.active_profile is not None:
        lines.append(f"active_profile = {_toml_string(config.active_profile)}")
    lines.extend(_render_unknown_scalars(config.unknown_keys()))

    for name, profile in config.profiles.items():
        table = f"profiles.{_toml_key(name)}"
        profile_keys = profile.unknown_keys()
        lines.extend(
            [
                "",
                f"[{table}]",
                f"environment = {_toml_string(_profile_environment_value(profile.environment))}",
                f"nip = {_toml_string(profile.nip)}",
            ]
        )
        if profile.poll_interval is not None:
            lines.append(f"poll_interval = {_toml_number(profile.poll_interval)}")
        if profile.max_poll_attempts is not None:
            lines.append(f"max_poll_attempts = {profile.max_poll_attempts}")
        lines.extend(_render_unknown_scalars(profile_keys))

        auth = profile.auth
        auth_keys = auth.unknown_keys()
        lines.extend(
            [
                "",
                f"[{table}.auth]",
                f"type = {_toml_string(auth.type.value)}",
            ]
        )
        if auth.token_env is not None:
            lines.append(f"token_env = {_toml_string(auth.token_env)}")
        if auth.context_type is not None:
            lines.append(f"context_type = {_toml_string(profile_context_type(auth))}")
        if auth.cert is not None:
            lines.append(f"cert = {_toml_string(str(auth.cert))}")
        if auth.key is not None:
            lines.append(f"key = {_toml_string(str(auth.key))}")
        if auth.key_password_env is not None:
            lines.append(f"key_password_env = {_toml_string(auth.key_password_env)}")
        if auth.p12 is not None:
            lines.append(f"p12 = {_toml_string(str(auth.p12))}")
        if auth.p12_password_env is not None:
            lines.append(f"p12_password_env = {_toml_string(auth.p12_password_env)}")
        lines.extend(_render_unknown_scalars(auth_keys))
        lines.extend(_render_unknown_tables(f"{table}.auth", auth_keys))
        lines.extend(_render_unknown_tables(table, profile_keys))

    lines.extend(_render_unknown_tables(None, config.unknown_keys()))

    return "\n".join(lines) + "\n"


def load_cli_profile(
    name: str | None = None,
    *,
    config_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[str, ProfileConfig]:
    """Select and load a profile the way the CLI does.

    The profile is chosen from ``name``, then ``KSEF2_PROFILE``, then the config's ``active_profile``.

    Args:
        name: Profile name to load; ``None`` to fall back to the environment variable and active profile.
        config_path: Path of the config file; the default location is used when ``None``.
        environ: Environment mapping to read; ``os.environ`` when ``None``.

    Returns:
        The selected profile's name and settings.

    Raises:
        KSeFValidationError: If no profile is selected, the profile is not defined, or the config file is invalid.
    """
    env = os.environ if environ is None else environ
    resolved_config_path = _resolve_profile_config_path(config_path, environ=env)
    config = load_profile_config(resolved_config_path)
    selected_name = name or env.get(PROFILE_ENV_VAR) or config.active_profile

    if selected_name is None:
        raise exceptions.KSeFValidationError(
            "No ksef2-cli profile selected. Pass a profile name, set KSEF2_PROFILE, "
            f"or configure active_profile in {resolved_config_path}.",
            config_path=str(resolved_config_path),
        )

    profile = config.profiles.get(selected_name)
    if profile is None:
        raise exceptions.KSeFValidationError(
            f"ksef2-cli profile {selected_name!r} is not defined in "
            f"{resolved_config_path}.",
            config_path=str(resolved_config_path),
            profile_name=selected_name,
        )

    return selected_name, profile


def resolve_profile_secret(
    envvar: str | None,
    *,
    label: str,
    profile_name: str,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    if envvar is None:
        return None

    env = os.environ if environ is None else environ
    value = env.get(envvar)
    if value is None:
        raise exceptions.KSeFValidationError(
            f"{label} environment variable {envvar} is not set for "
            f"ksef2-cli profile {profile_name!r}.",
            profile_name=profile_name,
            envvar=envvar,
        )
    return value


def load_profile_pem_credentials(
    profile: ProfileConfig,
    *,
    profile_name: str,
) -> tuple[Certificate, XAdESPrivateKey]:
    auth = profile.auth
    if auth.cert is None or auth.key is None:
        raise exceptions.KSeFValidationError(
            f"ksef2-cli profile {profile_name!r} requires auth.cert and auth.key.",
            profile_name=profile_name,
        )

    password = resolve_profile_secret(
        auth.key_password_env,
        label="PEM private key password",
        profile_name=profile_name,
    )
    try:
        return (
            load_certificate_from_pem(auth.cert),
            load_private_key_from_pem(
                auth.key,
                password=password.encode("utf-8") if password else None,
            ),
        )
    except (OSError, TypeError, ValueError) as exc:
        raise exceptions.KSeFValidationError(
            f"Failed to load PEM credentials for ksef2-cli profile "
            f"{profile_name!r}: {exc}",
            profile_name=profile_name,
            cert_path=str(auth.cert),
            key_path=str(auth.key),
        ) from exc


def load_profile_p12_credentials(
    profile: ProfileConfig,
    *,
    profile_name: str,
) -> tuple[Certificate, XAdESPrivateKey]:
    auth = profile.auth
    if auth.p12 is None:
        raise exceptions.KSeFValidationError(
            f"ksef2-cli profile {profile_name!r} requires auth.p12.",
            profile_name=profile_name,
        )

    password = resolve_profile_secret(
        auth.p12_password_env,
        label="PKCS#12/PFX password",
        profile_name=profile_name,
    )
    try:
        return load_certificate_and_key_from_p12(
            auth.p12,
            password=password.encode("utf-8") if password else None,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise exceptions.KSeFValidationError(
            f"Failed to load PKCS#12/PFX credentials for ksef2-cli profile "
            f"{profile_name!r}: {exc}",
            profile_name=profile_name,
            p12_path=str(auth.p12),
        ) from exc


def _resolve_profile_config_path(
    path: str | Path | None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    if path is not None:
        return Path(path).expanduser()
    return default_profile_config_path(environ)


def profile_context_type(auth: ProfileAuthConfig) -> ContextIdentifierType:
    context_type = auth.context_type
    if isinstance(context_type, ContextIdentifierTypeEnum):
        return context_type.value
    return context_type or "nip"


def _profile_environment_to_sdk(environment: ProfileEnvironment) -> Environment:
    if environment is ProfileEnvironment.PRODUCTION:
        return Environment.PRODUCTION
    if environment is ProfileEnvironment.DEMO:
        return Environment.DEMO
    return Environment.TEST


def _profile_environment_value(environment: ProfileEnvironment | Environment) -> str:
    if isinstance(environment, Environment):
        return _ENVIRONMENT_TO_PROFILE[environment]
    return environment.value


def _toml_key(value: str) -> str:
    if PROFILE_NAME_PATTERN.fullmatch(value):
        return value
    return _toml_string(value)


def _render_unknown_scalars(values: Mapping[str, object]) -> list[str]:
    """Render preserved unknown keys that are not TOML tables.

    Args:
        values: Unknown keys of one config table.

    Returns:
        ``key = value`` lines for the entries that are not nested tables.
    """
    return [
        f"{_toml_key(key)} = {_toml_value(value)}"
        for key, value in values.items()
        if not isinstance(value, Mapping)
    ]


def _render_unknown_tables(
    parent: str | None, values: Mapping[str, object]
) -> list[str]:
    """Render preserved unknown keys that are TOML tables.

    Args:
        parent: Table the entries belong to; ``None`` for the document root.
        values: Unknown keys of one config table.

    Returns:
        Table blocks for the nested entries, including their own unknown keys.
    """
    lines: list[str] = []
    for key, value in values.items():
        if not isinstance(value, Mapping):
            continue
        nested = cast(Mapping[str, object], value)
        table = f"{parent}.{_toml_key(key)}" if parent else _toml_key(key)
        lines.extend(["", f"[{table}]"])
        lines.extend(_render_unknown_scalars(nested))
        lines.extend(_render_unknown_tables(table, nested))
    return lines


def _toml_value(value: object) -> str:
    """Render one preserved config value as a TOML literal.

    Args:
        value: Value read from the config file.

    Returns:
        The TOML representation.

    Raises:
        KSeFValidationError: If the value has no TOML representation.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, datetime.datetime | datetime.date | datetime.time):
        return value.isoformat()
    if isinstance(value, list):
        items = cast(list[object], value)
        return f"[{', '.join(_toml_value(item) for item in items)}]"
    if isinstance(value, Mapping):
        entries = cast(Mapping[object, object], value)
        rendered = ", ".join(
            f"{_toml_key(str(key))} = {_toml_value(item)}"
            for key, item in entries.items()
        )
        return f"{{{rendered}}}"
    raise exceptions.KSeFValidationError(
        f"Cannot write profile setting of type {type(value).__name__} as TOML."
    )


def _toml_string(value: str) -> str:
    return json.dumps(value)


def _toml_number(value: float) -> str:
    return str(value)
