"""Read type information off live objects without letting unknowns leak out.

Describing an API from its own annotations means handling objects whose shape is
only known at runtime. Every helper here takes ``object`` and returns something
the rest of the package can rely on, so a partially known type stops at the
boundary instead of spreading through the manifest code.
"""

import typing
from typing import cast


def type_args(annotation: object) -> tuple[object, ...]:
    """Return the arguments of a parameterised annotation.

    Args:
        annotation: Annotation read from a public signature.

    Returns:
        Its type arguments, empty for a bare class or scalar.
    """
    return cast("tuple[object, ...]", typing.get_args(annotation))


def type_origin(annotation: object) -> object | None:
    """Return what a parameterised annotation stands for.

    Args:
        annotation: Annotation read from a public signature.

    Returns:
        The origin class or special form, or ``None`` for an unparameterised
        annotation.
    """
    return cast("object | None", typing.get_origin(annotation))


def attribute_of(annotation: object, name: str) -> object | None:
    """Read one attribute of an annotation, if it has it.

    Args:
        annotation: Object to inspect.
        name: Attribute name.

    Returns:
        The value, or ``None`` when the object does not carry it.
    """
    return cast("object | None", getattr(annotation, name, None))


def name_of(annotation: object) -> str:
    """Label an annotation for a name or an error message.

    Args:
        annotation: Object to name.

    Returns:
        Its declared name, or its text form when it has none.
    """
    raw = attribute_of(annotation, "__name__")
    return raw if isinstance(raw, str) else str(annotation)


def module_of(annotation: object) -> str:
    """Return the module an annotation was defined in.

    Args:
        annotation: Object to inspect.

    Returns:
        Its module name, or an empty string when it declares none.
    """
    raw = attribute_of(annotation, "__module__")
    return raw if isinstance(raw, str) else ""


def original_bases(cls: object) -> tuple[object, ...]:
    """Return the bases of a class with their type arguments kept.

    Args:
        cls: Class to inspect.

    Returns:
        Each base as it was written, including the arguments supplied to it.
    """
    bases = attribute_of(cls, "__orig_bases__")
    return cast("tuple[object, ...]", bases if isinstance(bases, tuple) else ())


def type_parameters(obj: object) -> tuple[object, ...]:
    """Return the type variables a generic class declares.

    Args:
        obj: Class or alias to inspect.

    Returns:
        Its declared type variables, in order.
    """
    parameters = attribute_of(obj, "__parameters__")
    return cast(
        "tuple[object, ...]", parameters if isinstance(parameters, tuple) else ()
    )


def members_of(module: object) -> tuple[tuple[str, object], ...]:
    """Return the names a module exports, with the objects behind them.

    Args:
        module: Imported module to inspect.

    Returns:
        Each public and private module-level name with its value.
    """
    namespace = cast("dict[str, object]", vars(module))
    return tuple(namespace.items())


def alias_value(alias: object) -> object:
    """Return the type a ``TypeAliasType`` stands for.

    Args:
        alias: The alias object.

    Returns:
        The value the alias was declared with.
    """
    return cast("object", attribute_of(alias, "__value__"))
