# AOOSTAR OpenScreen — browser distribution

This app edits and plays canvas layouts in a browser. **It does not drive the
built-in AOOSTAR USB display and does not collect TrueNAS or host telemetry.**
There are no external collectors, management credentials, brokers or devices.

Set the exact NAS hostname/IP and only the private client networks you trust as
administrators. Every allowed peer can edit and delete app content; there is no
per-user login. Loopback-only defaults intentionally deny LAN access until you
configure the allowlists. Do not expose through a reverse proxy, public port
forward, or an untrusted network. Forwarded IP headers are ignored.

Use a dedicated ixVolume (default) or explicitly assigned host path. UID/GID
10001 must be able to write there. Configure permissions through the supported
TrueNAS storage UI; the app will not recursively chown, alter ACLs, or repair
permissions. ACL changes are only those explicitly requested in the storage
form. A missing write permission is a startup error.

Back up the assigned data before updates. Catalog data remains in that volume.
Full-version config.json files are incompatible and are rejected unchanged.
Do not mount an existing full-version data directory: use a separate volume and
transfer reviewed canvas pages/media using the migration instructions upstream.

Submission status: draft only. Image 1.0.2 is not published, icon hosting and
screenshots are pending, and reduced-distribution acceptance needs a maintainer
decision. No catalog inclusion or physical hardware validation is claimed.
