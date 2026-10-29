# Dependency license inventory

Package-declared runtime licenses inspected on 2026-10-29. This is not an
independent legal provenance audit. Frozen versions are recorded in the root
and catalog `uv.lock` files; the two distributions have separate environments.

| Catalog Python package | Version | Declared license |
| --- | --- | --- |
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| click | 8.5.0 | BSD-3-Clause |
| fastapi | 0.162.0 | MIT |
| h11 | 0.16.0 | MIT |
| idna | 3.20 | BSD-3-Clause |
| opentelemetry-api | 1.45.1 | Apache-2.0 |
| pillow | 13.0.0 | MIT-CMU |
| pydantic | 2.14.1 | MIT |
| pydantic_core | 2.50.1 | MIT |
| starlette | 1.10.0 | BSD-3-Clause |
| typing_extensions | 4.16.0 | PSF-2.0 |
| typing-inspection | 0.4.4 | MIT |
| tzdata | 2026.6 | Apache-2.0 |
| uvicorn | 0.54.0 | BSD-3-Clause |

Additional full-Docker runtime packages:

| Package | Version | Declared license |
| --- | --- | --- |
| psutil | 7.2.2 | BSD-3-Clause |
| pyserial | 3.5 | BSD |
| httpx | 0.28.1 | BSD-3-Clause |
| websocket-client | 1.9.2 | Apache-2.0 |
| certifi | 2026.10.23 | MPL-2.0 |
| httpcore | 1.0.9 | BSD-3-Clause |

The full Docker lock uses Python tzdata 2026.5, also Apache-2.0. Test dependencies
are separately locked. OS tzdata is a different package from Python tzdata.

OpenScreen's own code is MIT, selected by the owner. The generated TrueNAS library
retains its upstream LGPL-3.0 license; see [TRUENAS-LICENSE](TRUENAS-LICENSE).
The library is not included in the application image. DejaVu core/extra and
Liberation font notices accompany the actual font files under `/usr/share/doc`.
Alpine's package database and application package metadata are retained.

An SPDX inventory was generated from the actual catalog image. Some scanner
records have no declared license (image root, virtual `.python-rundeps`, libbsd,
libmd, libxau, libxdmcp, OS tzdata and Python). These are inventory gaps, not
evidence of prohibited licensing. Scanner output does not replace upstream
notices. Generate current inventories using the commands in [SECURITY.md](SECURITY.md).

Local history attributes the full protocol implementation to the project owner;
its module describes AOOSTAR-X interoperability, not a third-party source grant.
History alone cannot prove legal authorship. That module is not part of the
catalog artifact, and the project's MIT license does not relicense dependencies.
