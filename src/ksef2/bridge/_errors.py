"""Errors raised while describing the public sync API."""


class ManifestError(RuntimeError):
    """Raised when the manifest cannot be built without guessing.

    A manifest is only useful when every entry describes what the caller would
    see in Python. Two models sharing one short schema name, one id describing
    two members, a reference pointing at nothing, or a value that is not JSON
    would all make it lie about the API, so the build stops instead.
    """


class UnsupportedSignature(Exception):
    """Raised when a signature has no JSON Schema representation.

    Callables, unannotated parameters and classes the SDK does not describe as
    data cannot cross a language boundary as JSON, so the member that carries
    them is reported as excluded rather than given an invented schema.

    Attributes:
        detail: Name of the parameter, or the type, that has no schema.
    """

    def __init__(self, detail: str) -> None:
        """Record which part of the signature has no schema.

        Args:
            detail: Name of the parameter, or the type, that has no schema.
        """
        super().__init__(detail)
        self.detail = detail


class HandsBackAnotherClient(Exception):
    """Raised when a member hands back a client the manifest walks separately.

    Accessors such as ``client.tokens`` return an object whose own methods are
    already operations. Describing the accessor as well would duplicate that
    surface under a second schema, so the accessor is reported as excluded.

    Attributes:
        detail: Name of the class the member hands back.
    """

    def __init__(self, detail: str) -> None:
        """Record which object the member returns.

        Args:
            detail: Name of the class the member hands back.
        """
        super().__init__(detail)
        self.detail = detail
