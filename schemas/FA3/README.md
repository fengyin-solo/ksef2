# FA(3) schema artifacts

This directory owns the XSD and XML files mirrored into
`src/ksef2/_infra/schema/fa3/definitions` by
`scripts/sync_generated_artifacts.py`. The four additional lookup XSDs are
runtime data and do not change the generated invoice models.

`code-lists.json` records the five code-list URLs from the bundled
`WspolneSzablonyWizualizacji_v12-0E.xsl`, their final download URLs, retrieval
date, and SHA-256 checksums. The files retain the exact bytes served by
`crd.gov.pl`, including upstream line endings. The existing countries XSD was
also fetched and verified byte for byte.

To update a list, download its `source_url`, verify that it is the expected XSD,
and update the corresponding checksum and retrieval metadata. Run
`just regenerate-fa3-models` to copy the definitions and manifest into the
package, then `just release-check`. Its artifact verification checks checksums
and the code-list bytes and provenance manifest in both the wheel and sdist
without accessing the network. The sdist includes the canonical files as well
as their packaged copies.

Rendering passes the bundled files as local `file://` stylesheet parameters.
The upstream stylesheets remain unchanged.
