# OpenScreen Catalog distribution — unreleased 1.0.2

This is a **browser-only** distribution prepared for review, not an accepted
TrueNAS app. Do not install the full Docker/Custom App image through this catalog
entry. [Verification and remaining blockers](STATUS.md) are part of this candidate.

## What it does

Design pages with the shared visual canvas editor, text, shapes, clocks, images
and bounded animated media. Open `/display` on a network browser player. The
default output is 960 × 376; page layouts remain editable. Network player means
an ordinary browser fetching image frames, not a privileged remote USB broker.

There is **no USB display support, NAS telemetry, TrueNAS API, Docker API,
Proxmox API, JSON/URL collector, host metrics, discovery, secret directory,
hardware endpoint or background collector** in this artifact. Metrics imported
from old pages have no source and remain unknown; they are not invented data.
The complete Docker application remains in `openscreen` and the existing files.
Only safe canvas, asset and network-access primitives are shared by both builds.

## Local build and verification

From the repository root with Python 3.13, uv and local Linux Docker available:

```sh
uv sync --frozen
uv run playwright install chromium
uv run pytest -q
uv run python scripts/catalog_reproducibility_test.py
uv run python scripts/catalog_container_test.py
```

The local Linux test runner now installs the exact root `uv.lock`, including
test dependencies, and includes a pinned Compose CLI. It needs no Docker socket
for the Compose configuration tests. Build it with
`docker build -f catalog/Dockerfile.test-tools -t aoostar-catalog-test-tools:locked .`.
Run non-browser tests with the checkout mounted read-only at `/work`, UID/GID
10001, a writable `/tmp`, no network and no added capabilities. Browser tests run
separately using the frozen Playwright version. This runner is never deployed as
part of the app. Supplemental library rendering uses the official validation
image, whose dependencies belong to the upstream toolchain.

The [candidate changelog](CHANGELOG.md) is prepared locally. Its public URL must
be verified after publication before adding `changelog_url` to the catalog.

The reproducibility command performs two uncached builds with the frozen lock,
digest-pinned Alpine Python/uv images, a fixed Debian snapshot for font data only, explicit
`SOURCE_DATE_EPOCH=1793145600` and normalized layer timestamps. It requires the
resulting OCI image digests to match. Bump the epoch intentionally for a new
release. Passing twice on one builder is evidence for that environment, not a
proof for every future builder or package mirror.

`compose.catalog.yaml` is a local example. It binds only to localhost and denies
non-loopback peers by default. Docker Desktop may NAT the client address; inspect
the actual connection source and explicitly allow only the trusted private
client subnet. Do not add all private networks merely to make a request succeed.
Never point a test runner at the NAS Docker daemon.

## TrueNAS installation after acceptance

1. Wait for the public image, actual CDN-hosted assets, completed upstream CI and
   acceptance by the maintainers. There is no current official install listing.
2. Select the Community app **AOOSTAR OpenScreen (Browser)**.
3. Set WebUI port (candidate default `32176`) and, if desired, a specific host IP.
4. Set **Allowed Hosts** to the exact hostname/IP used in the browser URL; no
   wildcard, scheme or port. Set **Allowed Networks** to the private CIDRs of
   trusted administrators and browser players. Defaults intentionally deny LAN.
5. Allocate a dedicated ixVolume, or select a dedicated host path through the
   official storage form. UID/GID `10001` must have read/write/traverse access.
   The library adds supplementary group `568`; it does not grant host mounts.
6. Set storage permissions through supported TrueNAS UI controls. ACL options in
   the storage form apply only when explicitly enabled. The app neither changes
   ownership nor recursively repairs ACLs. If permission is missing, installation
   fails visibly at startup; correct the assigned directory and restart the app.
7. Keep CPU/memory limits (defaults: 2 CPUs, 512 MiB). Open the WebUI portal, edit
   a page, save it and open Browser Player. Verify reload and app restart before
   importing more data. Real TrueNAS ixVolume/ACL behaviour is not verified here.

The app has **no per-user authentication**. Every allowed peer can administer it.
All allowed LAN users and players must therefore be trusted. Do not expose it to
the Internet, forward its port publicly, or put it behind a proxy that turns
untrusted users into a trusted peer. Forwarded headers are deliberately ignored.
HTTP is intended only for the explicitly trusted local network. For shared or
untrusted networks this model is unsuitable; do not deploy until a separate
authenticated access design has been implemented and reviewed.

## Storage, upgrades and migration

`/data/config.json` and `/data/assets` are the only persistent application data.
Configuration writes use a temporary file, fsync and atomic replacement. A
failed replacement leaves the prior config and active runtime unchanged. Root
filesystem writes are prohibited; `/tmp` is bounded ephemeral storage.

Back up the assigned data before updating. Keep the same assigned volume across
container replacements. Unsupported distribution/schema configurations are
rejected unchanged. Automatic rollback across future unknown schemas is not
claimed; restore a separate backup if a future version requires it.

For full-version migration, export a backup first. Never reuse its live directory.
The helper requires a new destination and an explicit acknowledgement that only
canvas content is retained:

```sh
uv run python scripts/migrate_catalog_canvas.py --source /path/to/exported-backup --destination /path/to/new-catalog-data --canvas-only
```

It preserves the source, removes source bindings from copied pages, omits source
credentials/rules/hardware configuration, and copies only referenced local media.
Existing or nested destinations and symlink media are rejected. A failed copy can
leave a new partial destination for inspection; it never deletes either tree.
Transfer the reviewed result using your normal storage process. Do not copy any
secret directory. This command is not a NAS administration tool.

## Upstream workspace and tools

The source entry is under `catalog/ix-dev/community/aoostar-openscreen/`.
Copy only that directory into a separate checkout of `truenas/apps`.
The inspected baseline is `ea9e6a18c58031ee9ecb850390c56ac48c819230`, library
`2.3.17`. Recheck policy/library/port availability immediately before submission.

```sh
uv run .github/scripts/port_validation.py
uv run .github/scripts/generate_metadata.py --app aoostar-openscreen --train community
uv run .github/scripts/ci.py --app aoostar-openscreen --train community --test-file basic-values.yaml --render-only=true
uv run .github/scripts/ci.py --app aoostar-openscreen --train community --test-file basic-values.yaml
```

Repeat rendering, Compose boundary checks and integration for
`hostpath-values.yaml`. The CI workflow contains the sequence. Disposable CI
fixture directories require UID/GID 10001; create them only on the local test
runner. No fixture preparation belongs in the installed application.

Generated library files came from the official `apps_catalog_hash_generate`,
not a manual library copy. `basic-rendered.yaml` and `hostpath-rendered.yaml` are
outputs of the official `apps_render_app`. They are evidence, not submission
source. Do not copy them into the PR. `item.yaml` and `run_as_context` are still
pending the blocked metadata step; do not fabricate them.

Windows bind mounts do not support the generator's `renameat2` operation. Tests
therefore used a separate Linux Docker volume for the upstream workspace. The
official tool container uses a local Docker socket as required by upstream's
test tools; **the installed application has no such mount or helper**.

## Publication gates

The MIT license was selected by the owner. See [dependency notices](DEPENDENCIES.md).
Review [security findings](SECURITY.md), not just passing Python tests.

`catalog-publish.yml` is manual-only, requires an explicit publication input and
uses the `catalog-release` environment. Configure required reviewers on that
environment before enabling it. No workflow was dispatched here. It publishes
no `latest` tag and creates no GitHub release. Verify public anonymous pulls and
record/pin the public image digest after the approved release.

The authored icon and real browser screenshots are in `icon.svg` and
`screenshots/`. Ask maintainers to host them through the official media process;
do not invent a CDN URL. The current empty icon intentionally prevents the
metadata gate from passing. A maintainer inquiry and pull request have not been
submitted; their local working drafts are intentionally not part of the release.
