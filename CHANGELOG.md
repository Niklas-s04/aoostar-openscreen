# Changelog

## 1.0.2

This release updates the **full Docker/Custom App distribution**. It does not
publish or claim acceptance of the separate TrueNAS Community Catalog candidate.

- Add the MIT license selected by the project owner.
- Upgrade Pillow to 13.0.0 and use digest-pinned Alpine Python build/runtime images
  with patched system zlib. Remove unused runtime packaging tools.
- Include all DejaVu italic and condensed fonts, preserving upstream notices.
- Share canvas and network-access primitives without removing full-version
  collectors, the broker or the AOOSTAR protocol implementation.
- Prepare an isolated browser-only catalog distribution with separate schema,
  UI, dependencies and allowlisted build context. It remains unreleased.
- Add reproducibility, image permissions, persistence, browser, network-boundary,
  native-library and negative configuration checks.
- Consolidate publication into one tested-image workflow for GHCR and Docker Hub;
  verify anonymous access and matching image contents before updating `latest`.

Back up the assigned data directory before upgrading and retain its existing
mount. This release does not require a configuration schema migration or NAS
system changes. The web UI remains restricted to explicitly trusted LAN peers;
it is not intended for public exposure. Real AOOSTAR USB output/hotplug and live
NAS integrations are not hardware-certified by the software tests.

The full image scan has no Critical/High findings at release preparation time.
One musl finding with unspecified severity remains in the unfiltered scanner
report; Alpine's stable-branch source identifies the installed package as fixed.
The corrected native rejection paths were exercised. This is not a claim of an
entirely finding-free scan; see [security evidence](catalog/SECURITY.md).
