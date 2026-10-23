"""Machine-readable description of the public synchronous SDK API.

Binding generators read this instead of re-deriving the API with ``inspect``.
:func:`manifest` returns plain JSON-compatible data: one operation per public
sync method, a JSON Schema for every parameter, return value and state, named
definitions for every model and every ``Literal`` alias, and an ``excluded`` list
that says why each remaining member is not an operation.

Run ``python -m ksef2.bridge manifest`` to print the same document as JSON.

Example:
    ```python
    import json

    from ksef2.bridge import manifest

    document = manifest()
    print(len(document["operations"]), document["format_version"])
    print(json.dumps(document["$defs"]["ContextIdentifierType"]))
    ```
"""

from ksef2.bridge._manifest import FORMAT_VERSION, manifest, manifest_json
from ksef2.bridge._schema import SCHEMA_DIALECT

__all__ = ["FORMAT_VERSION", "SCHEMA_DIALECT", "manifest", "manifest_json"]
