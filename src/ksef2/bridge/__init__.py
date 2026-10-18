"""Machine-readable description of the public sync API.

``ksef2.bridge.manifest()`` answers one question without importing Python: what
can be called, with what, and what comes back. Every public sync method and
property of the SDK's client, service, handle and pager classes appears as an
operation with JSON Schema parameters and a JSON Schema result, or as an
exclusion that names the rule which kept it out. Live objects are described by
the data a caller saves and hands back, so a language binding, a job queue or a
codegen tool can drive the SDK without holding a Python object.

The document is stable plain JSON: ``json.dumps`` writes it, and
``python -m ksef2.bridge manifest`` prints it.

Example:
    ```python
    import json

    from ksef2.bridge import manifest

    data = manifest()
    print(data["format_version"], len(data["operations"]))
    print(json.dumps(data["$defs"]["GeneratedTokenResumeState"])[:80])
    ```
"""

from ksef2.bridge._manifest import build_manifest

__all__ = ["manifest"]


def manifest() -> dict[str, object]:
    """Describe the public sync API as plain JSON-compatible data.

    The result holds only dicts, lists, strings, numbers, booleans and ``None``,
    so it survives ``json.dumps`` unchanged. Its top-level keys are
    ``format_version``, ``ksef2_version``, ``operations``, ``excluded``,
    ``exceptions`` and ``$defs``. Operations and exclusions are sorted by ``id``,
    exceptions by ``name``, and every ``$ref`` points at ``$defs``.

    Returns:
        The manifest of the public sync API.

    Raises:
        ManifestError: Two schemas would share one name, an id would describe
            two members, a reference would point at nothing, or a value is not
            JSON data. Nothing is invented in that case.
    """
    return build_manifest()
