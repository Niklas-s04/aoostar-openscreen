# Catalog candidate status

The browser-only Catalog distribution is **unreleased and not accepted by
TrueNAS**. The full Docker 1.0.2 release is independent and must not be substituted
for this catalog image.

Policy checked against truenas/apps revision
`ea9e6a18c58031ee9ecb850390c56ac48c819230`, confirmed 2026-10-29:
[contribution guide and inclusion policy](https://github.com/truenas/apps/blob/ea9e6a18c58031ee9ecb850390c56ac48c819230/CONTRIBUTIONS.md).
Library 2.3.17 and its files were generated with official tooling; they must stay
in the entry. Default port 32176 passed the official uniqueness validator.

| Requirement | Implemented boundary / evidence | Status |
| --- | --- | --- |
| No TrueNAS management/API | Independent image, schema, routes and UI; excluded-module and forbidden-source tests | Locally verified |
| Assigned resources only | No USB, broker, host namespaces, Docker sockets or wildcard devices; negative rendered-Compose tests | Locally verified |
| Data integrity / ZFS protection | Only assigned data storage, atomic saves, explicit migration, no ZFS/system operations | Local persistence/error tests pass; NAS ACLs unverified |
| Container hardening | UID/GID 10001, read-only root, all capabilities dropped, no-new-privileges, bounded tmpfs | Real container tests pass |
| Access control | Exact Hosts/private peer CIDRs, no proxy trust, same-origin and bounded writes | Tests pass; trusted-LAN model needs maintainer assessment |
| Official storage/library | ixVolume default plus official host-path schema; two rendering scenarios | Official renderer and local Compose starts pass |
| Image security | Patched system zlib; old high-risk Debian packages absent | Critical/high gate passes; one documented scanner discrepancy remains |
| Official metadata and CI | No fake CDN URLs and no skipped metadata check | Blocked by missing real CDN icon |
| Public versioned catalog image | Separate version 1.0.2 planned | Not published; owner has not authorized catalog release |
| Final acceptance | Separate distribution and its usefulness require review | Maintainer decision outstanding |

Application tests cover startup, health, schema validation, assets, persistence,
permission failures, network restrictions and upgrade/migration boundaries.
Real image checks cover 28 font styles, PNG/JPEG/WebP/GIF, animations, timezone,
HTTP output, native-library use and bounded musl regex rejection. Uncached
builds are compared for reproducibility. Physical AOOSTAR output is not claimed.

Both official `ci.py` scenarios and `generate_metadata.py` stop at the absent
TrueNAS-CDN icon. `item.yaml` and final generated user metadata remain pending.
An additional `apps_dev_charts_validate` invocation fails at libzfs initialization
on the local Docker Desktop host; no host devices or privileges were added.
Neither limitation is represented as a passing official CI run.

The icon and real screenshots are ready for the official review/media process.
The candidate changelog is local source, with no invented public URL. A TrueNAS
issue/PR and catalog image publication remain unrequested external actions.

**Technically verified:** the stated local application/container boundaries.
**Not verified:** full official CI, real NAS storage/updates and physical hardware.
**Policy-blocked:** submitting the full management-API image.
**Needs maintainer approval:** acceptance of the separate browser distribution,
trusted-LAN model, storage provisioning and final inclusion.

Meeting local technical checks does not guarantee catalog inclusion. See
[installation](README.md), [security](SECURITY.md), and [license inventory](DEPENDENCIES.md).
