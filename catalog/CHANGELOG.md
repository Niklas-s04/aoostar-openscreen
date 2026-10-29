# Catalog distribution changelog

## 1.0.2 — unreleased candidate

- Introduce the separate browser-only canvas editor/player distribution.
- Exclude TrueNAS management, telemetry collectors, Docker sockets, broker and
  USB/device code structurally from the image and configuration schema.
- Enforce trusted-peer/Host allowlists, same-origin requests and bounded uploads.
- Preserve data atomically under assigned storage; provide explicit canvas-only
  migration into a new directory without rewriting the original installation.
- Use UID/GID 10001, read-only root, dropped capabilities and no-new-privileges.
- Pin the Alpine Python runtime and dependency lock; use patched system zlib.
- Preserve the fonts and their notices, including all italic/condensed variants.
- Add real image, persistence, permission, codec, browser and negative boundary
  checks, reproducible builds and bounded native musl regex regression checks.

This candidate has not been published and has not been accepted by TrueNAS.
The complete Docker distribution uses version 1.0.2 independently. Catalog metadata version
1.0.0 is separate from the application version above. Once this document is
published, verify its public URL before setting `changelog_url`; do not point
catalog metadata at a file that is only present in a local checkout.
