# Security boundaries and validation

Checked 2026-10-29. The full Docker release and the unreleased catalog candidate
are separate artifacts. No catalog admission or physical-hardware certification
is implied by this document.

## Distribution boundary

The full Docker image retains TrueNAS/Docker/Proxmox collectors, optional USB
transport and the display broker. It is **not eligible for the official catalog**
because it contains TrueNAS management-API functionality. Its optional hardware
and Docker overlays must only be used with explicitly authorized resources.

The catalog image copies only `openscreen_catalog`, shared canvas/render/assets/
network-access primitives and the shared editor JavaScript/CSS. Its allowlisted
build context excludes the full application, collectors, TrueNAS adapter,
protocol, discovery and broker. Its independent schema rejects nonempty sources,
rules, hardware settings, secrets and URLs. Removed APIs return 404; no feature
flag restores them. It cannot install optional integrations at runtime.

Catalog deployment has one UID/GID 10001 container, read-only root, cap_drop ALL,
no-new-privileges, assigned `/data` and a 64 MiB `/tmp`. No devices, host
namespaces, wildcard device rules, Docker sockets or helper services are used.
The rendering library's supplementary group 568 does not itself grant mounts.
The app performs no outbound collection; Docker bridge networking is not claimed
to enforce an egress firewall. Library code executes during template rendering,
not inside the application image.

## Trusted-LAN access

Exact Host and private peer-CIDR allowlists guard administration and player routes.
Forwarded headers cannot change peer identity. Cross-origin/cross-site requests
are denied; writes require a custom header and bounded request bodies. The local
health probe reveals only an `ok` boolean. There is no public documentation API
or permissive CORS policy in the catalog application.

This is not per-user authentication. Every allowed peer is an administrator.
NAT, shared networks or reverse proxies can collapse multiple users into one
trusted peer. Do not expose the application publicly or treat an allowlisted
hostname as a password. Maintainers must assess this model before catalog entry.

## Native dependencies and scanner evidence

Both application builds pin their Python/Alpine and uv images and use frozen
Python lockfiles. A separate Debian snapshot stage supplies only font data and
notices; no Debian executable or library enters the runtime. Unused pip,
ensurepip and packaging/vendor code are actually removed, while the APK database
and installed application-package metadata remain intact.

The earlier catalog image had eight high Debian findings in util-linux, Perl and
zlib. The current Alpine runtime removes the affected old util-linux/Perl packages
and uses zlib 1.3.2-r1 with the upstream security patch. CPython and Pillow were
observed loading `/usr/lib/libz.so.1.3.2` after actual image processing. Tests
check system-library use, not merely the Python package version.

At release preparation, Scout 1.29.0 reports **0 Critical, 0 High, 0 Medium,
0 Low and 1 Unspecified** for the full Docker image and the catalog candidate.
The unchanged critical/high gate passes. A full all-severity `--exit-code` scan
still exits 1. No CVE was suppressed and no severity threshold was weakened.

The remaining CVE-2026-107891 finding maps musl 1.2.6-r3 to an r6 fixed version.
Alpine's official tracker distinguishes **stable 3.24 r3** from **edge r6**;
the exact source commit recorded in the installed APK includes the fix for r3.
No edge package was mixed into stable Alpine to change the scanner result.

Direct tests of the shipped libc `regcomp`/`regexec` accept a normal expression
and correctly distinguish match/non-match. A 1,024,000-byte expression and two
nested repetition inputs return `REG_ESPACE` under 128 MiB address-space and
five-second CPU limits. These are bounded rejection-path tests, not proof against
every exploit or a comparison with an unpatched binary. The scanner discrepancy
remains visible and should be reviewed when vulnerability data changes.

Both Python-environment pip-audit checks report no known findings. This does not
prove that all native dependencies are vulnerability-free.

Reproduce with a locally built image (the catalog image is not yet published):

```sh
docker scout cves ghcr.io/niklas-s04/aoostar-openscreen:1.0.2 --format sarif --output full.sarif --exit-code
docker scout cves ghcr.io/niklas-s04/aoostar-openscreen:1.0.2 --only-severity critical,high --exit-code
docker scout sbom ghcr.io/niklas-s04/aoostar-openscreen:1.0.2 --format spdx --output full.spdx.json
```

Raw reports, old renders and machine-specific investigation notes are local
validation artifacts, excluded from the release source tree. Public documentation
does not link to private filesystem paths or present old scans as current.

## Sources

- [Pillow 13.0.0 release](https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html)
- [Installed zlib source and security fix](https://github.com/alpinelinux/aports/blob/0afa2da0e8c8051c6f8f64a7a388e5a259904245/main/zlib/APKBUILD)
- [Installed musl source and security fix](https://github.com/alpinelinux/aports/blob/8f79d39391b46d6dbf1800fb68b8212a21d5ee2e/main/musl/APKBUILD)
- [Alpine branch-specific musl status](https://security.alpinelinux.org/vuln/CVE-2026-107891)
- [musl patch and regression input classes](https://github.com/alpinelinux/aports/blob/8f79d39391b46d6dbf1800fb68b8212a21d5ee2e/main/musl/CVE-2026-107891.patch)

Actual NAS ACLs, TrueNAS installation/upgrade and physical USB/hotplug remain
unverified. Software socket/PTY fixtures do not establish hardware compatibility.
