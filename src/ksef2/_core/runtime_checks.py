"""Runtime type checking of the SDK's own annotations.

``ksef2`` installs a beartype import hook when ``KSEF2_RUNTIME_CHECKS`` is set, so the
annotations callers read are also enforced while the SDK runs. Two things about that hook
have to sit outside the optional beartype dependency, and are owned here: whether this
process asked for runtime checks at all, and a way to keep one public annotation while
beartype validates a narrower hint than that annotation names.
"""

import os
from collections.abc import Callable
from typing import ParamSpec, TypeVar, cast

_TRUE_ENV_VALUES = {"1", "true", "yes", "on"}

RUNTIME_CHECKS_ENABLED = (
    os.environ.get("KSEF2_RUNTIME_CHECKS", "").lower() in _TRUE_ENV_VALUES
)
"""Whether this process asks for the SDK's annotations to be enforced at runtime."""

_P = ParamSpec("_P")
_R = TypeVar("_R")


def check_return_against(
    *, public_hint: object, runtime_hint: object
) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """Return a decorator that validates a return value against ``runtime_hint``.

    Beartype tests a returned value against the class object its annotation denotes. When
    a method is annotated with a generic model parameterized by its own class's unresolved
    type variable, that object is a parameterization no value can be an instance of, so
    the check fails for every correct return value. This decorator keeps the annotation
    exactly as written -- for ``typing.get_type_hints``, for ``inspect.signature``, for
    static checkers and for documentation -- and tells beartype to test the value against
    ``runtime_hint`` instead. Arguments of the decorated callable keep their own checks,
    and so does any check ``runtime_hint`` still carries.

    Without runtime checks enabled the callable is returned untouched, so a default
    install neither pays for the check nor needs beartype.

    Args:
        public_hint: The hint the annotation already names, which stays public.
        runtime_hint: The hint to validate the return value against at runtime.

    Returns:
        A decorator that leaves the signature as written and narrows the runtime check.
    """

    def decorate(func: Callable[_P, _R]) -> Callable[_P, _R]:
        if not RUNTIME_CHECKS_ENABLED:
            return func

        # beartype is the optional ksef2[runtime-checks] extra, imported only on the
        # branch that needs it so the default install never reaches for it.
        from beartype import BeartypeConf, FrozenDict, beartype

        conf = BeartypeConf(hint_overrides=FrozenDict({public_hint: runtime_hint}))
        # beartype's decorator is typed for a single argument or a lone conf, not for the
        # ParamSpec'd callable handed to it here, so the callable goes over as a plain one
        # and the decorated result comes back as this function's own signature.
        narrowed = beartype(conf=conf)
        return cast("Callable[_P, _R]", narrowed(cast("Callable[..., object]", func)))

    return decorate
