# AOOSTAR OpenScreen

A self-hosted display dashboard for the AOOSTAR WTR Max 8845. OpenScreen runs in
Docker, collects monitoring data from your homelab, and renders editable dashboards
for the built-in 960 × 376 display or a network browser player. A web interface
provides configuration, a visual editor, and a live preview.

This is an independent project, not an official AOOSTAR application.

**Status: experimental.** Container operation and automated tests have been
verified. Physical display output and live TrueNAS/Proxmox integration still need
validation. The current web interface is in German.

## Features

- Free-placement editor with resizing, layers, alignment, grid snapping, undo/redo,
  and configurable page rotation. New installations start with one readable page.
- Text, metrics, icons, bars, rings, charts, shapes, clocks, images, and animated GIFs.
- Eight editable templates and seven offline font families with bold/italic variants.
- Independent canvas and output dimensions, rotation, and fit modes.
- AOOSTAR serial output and a network browser player for other screen sizes.
- Display preview using the same renderer as the hardware output.
- Read-only data adapters for TrueNAS, Docker, Proxmox, and HTTP JSON endpoints.
- Alerts for thresholds, service state, health, restart loops, and pool state.
- Persistent configuration and recovery from temporary data-source failures.
- Passwordless access restricted to explicitly allowed local networks and hosts.

## Quick start

Install Docker with Docker Compose, then:

```sh
git clone https://github.com/Niklas-s04/aoostar-openscreen.git
cd aoostar-openscreen
docker compose up -d --build
```

Open **http://127.0.0.1:8080**. No login is required. The initial deployment uses
local runtime metrics and does not access the display, host files, or Docker socket.

The default port binds only to loopback. Compose uses the subnet 172.30.87.0/24;
if it conflicts with an existing network, change both the subnet and the allowed
gateway address in compose.yaml.

For step-by-step NAS setup, see the [TrueNAS installation guide](TRUENAS.md).
For TrueNAS SCALE 25.10, build and transfer the image using docker image save
and docker image load, then use **Apps → Discover Apps → Install via YAML**.
Start from [deploy/truenas-custom-app.yaml](deploy/truenas-custom-app.yaml),
replace every YOUR_* placeholder, and create the data directory with write access
for UID 10001 before installing. Verify the serial device and group as described
below. The example uses a locally imported image, not a published registry image.

## Connect the display

### Automatic discovery through the optional broker (Linux)

The broker discovers USB serial devices and reconnects after unplug/replug without
changing the Compose file or restarting containers. The web application receives
only a local Unix socket; the separate broker owns serial access. The default
deployment remains WebUI-only. This requires a Linux Docker host with the physical
USB device available; Docker Desktop alone does not expose the host's USB ports.

Identify the display's serial node and verify its numeric group as shown below,
then start the broker overlay:

```sh
export OPENSCREEN_DEVICE_GID=YOUR_VERIFIED_GROUP_ID
docker compose -f compose.yaml -f compose.broker.yaml up -d --build
```

Do not combine this overlay with `compose.hardware.yaml`. In **Einstellungen**,
choose the broker output (`broker`), refresh discovery, select a confirmed device
or `auto`, enable output, and save. Automatic selection requires an unambiguous
compatible display. Only devices with supported metadata and a successful protocol
ACK are offered as confirmed displays. Unknown candidates are reported as unsupported
and receive no active protocol probes. Currently the only adapter is AOOSTAR/Synwit
USB **0416:90a1**, with fixed **960 × 376** dimensions. An ACK establishes operational
protocol compatibility; the physical image, colors, orientation, and reconnect
behavior still need testing on the actual display.

The broker binds host `/dev` and `/sys` read-only for hotplug discovery and has
character-device read/write rules only for USB ACM/serial majors 166 and 188.
A read-only device-directory mount does **not** prevent writes to character
devices. Device cgroup rules, Unix permissions, and the adapter allowlist control
access. The broker can see host device metadata and may access other USB serial
devices permitted by the same group; it is a security-sensitive component. USB
identities can be spoofed and are not cryptographic authentication. The web
container has no device mounts or device permissions from this overlay.

Both containers run as UID/GID 10001 with dropped capabilities and a read-only
root filesystem. The broker has no network access, published port, Docker socket,
or host service installation. Its socket directory is mode 0700 and the socket
mode 0600; the web mounts the shared volume read-only, which still permits Unix
socket connections. The image supplies the directory owner for a fresh Docker
named volume. Stop the broker to revoke device access; disable broker output or
switch to browser output before removing the overlay. Preserve the data volume.

See [Docker device rules](https://docs.docker.com/reference/compose-file/services/#device_cgroup_rules)
and the [TrueNAS broker installation](TRUENAS.md) for deployment details.

### Direct mapping of one verified device

The Docker host must have access to the physical display. On Linux, identify the
serial device corresponding to USB vendor/product ID **0416:90a1**. Verify its
device path and numeric group ID rather than assuming a tty name or group.

```sh
ls -l /dev/serial/by-id/
udevadm info --query=property --name=/dev/ttyACM0
stat -Lc '%g' /dev/ttyACM0
```

Replace /dev/ttyACM0 with the device you are inspecting. If no corresponding serial
device exists, investigate driver support before continuing.

```sh
export OPENSCREEN_DEVICE=/dev/serial/by-id/YOUR_VERIFIED_DISPLAY
export OPENSCREEN_DEVICE_GID=YOUR_VERIFIED_GROUP_ID
docker compose -f compose.yaml -f compose.hardware.yaml up -d --build
```

In the web interface, open **Einstellungen** (Settings), select /dev/aoostar,
and enable hardware output. No other process should use the serial port.

The display uses RGB565 at 1,500,000 baud. A full frame takes approximately six
seconds if limited by conventional UART throughput. This is intended for status
pages, not video. Brightness, fan, and power-limit control are not implemented.
With direct mapping, reconnecting USB may require restarting the container.

## Configure data sources

External endpoints must be approved in the container environment before they can
be added through the web interface:

```sh
export OPENSCREEN_ALLOWED_SOURCE_URLS=https://nas.example,https://pve.example:8006
docker compose up -d
```

Each configured URL must exactly match an entry in this comma-separated list.
Existing configurations with unapproved sources fail closed at startup.

| Source | Supported data |
|---|---|
| Local system | CPU, memory, available CPU temperature sensors, network counters, uptime |
| TrueNAS 25.10 | Apps, pool state, and pool capacity through JSON-RPC |
| Docker | Container state; health/restarts for up to 50 containers and CPU/memory for up to 10 |
| Proxmox VE | Cluster nodes, QEMU VMs, and LXC containers with state and resource usage |
| HTTP JSON | Numeric metrics selected through simple dotted paths |

Local metrics describe the container's runtime environment, not necessarily the
NAS host. The TrueNAS adapter does not yet provide system-container, SMART, or
remote CPU/network metrics. Unavailable data is shown as unknown.

### API credentials

Use dedicated accounts with only the required read permissions. Store credentials
outside the repository in an isolated directory readable by container UID 10001.
Do not place unrelated secrets in that directory.

```sh
export OPENSCREEN_SECRETS_DIR=/absolute/path/to/openscreen-api-secrets
docker compose -f compose.yaml -f compose.secrets.yaml up -d
```

Enter only the secret filename in the web interface. A TrueNAS file contains the
API key; a Proxmox file contains user@realm!tokenid=secret. Authenticated endpoints
require HTTPS with certificate validation. An optional CA file may be placed in
the same directory. HTTP redirects are not followed.

### Optional Docker monitoring

```sh
export DOCKER_SOCKET_GID=YOUR_VERIFIED_SOCKET_GROUP_ID
export OPENSCREEN_ALLOWED_SOURCE_URLS=http://docker-proxy:2375
docker compose -f compose.yaml -f compose.docker.yaml up -d
```

Add a Docker source with URL http://docker-proxy:2375 and no secret. The proxy
allows only selected read endpoints and has no published port. The application
never receives the Docker socket. The optional proxy itself has socket access and
is a security-sensitive component; omit it when unnecessary.

## Network access and security

There is no user authentication: **every admitted client can change the dashboard
configuration**. Deploy only on a trusted management network. Do not expose the
service through public port forwarding, tunnels, or public reverse proxies.

| Environment variable | Purpose |
|---|---|
| OPENSCREEN_ALLOWED_NETWORKS | Explicit local/private client CIDRs; application default is loopback only |
| OPENSCREEN_ALLOWED_HOSTS | Exact hostnames or IP addresses without ports; no wildcards |
| OPENSCREEN_ALLOWED_SOURCE_URLS | Exact permitted external source URLs; empty by default |

The application checks the client address and Host header, rejects cross-site
browser requests, and protects configuration writes with origin and request-header
checks. The provided server command ignores forwarded client headers. A proxy or
source NAT can still make external traffic appear local; these checks do not
replace a firewall.

Containers run as UID/GID 10001 with a read-only root filesystem, dropped
capabilities, and no privileged mode. Do not add broad host mounts or weaken these
settings to resolve a device-permission error. Use dedicated read-only API accounts
and mount only the application's own data, isolated credentials, and display device.

## Design your dashboard

Open **Display** in the web interface. Select an element on the canvas or in the
layer list, then drag it, resize it with its handle, or edit its numeric properties.
Arrow keys move the selection by one pixel; Shift increases the step to ten.
Use Undo/Redo, lock or hide layers, and arrange elements with the alignment controls.
Only **Änderungen speichern** applies the draft to the running display.

Choose a template as a starting point, or add an empty page. Templates become normal
editable elements. Changing a page's dimensions proportionally adjusts its elements.
Canvas dimensions and output dimensions are independent: the output can contain,
crop, or stretch the page after rotation. Each side supports 64–3840 pixels, with a
maximum of 8,294,400 pixels per canvas/output. AOOSTAR output remains fixed at 960 × 376.

For a metric or chart, select a source, collection, and field. For example, use
`metrics` / `cpu` / `%`, or `pools` / `percent` with a pool name or ID. Network counters
`download` and `upload` are bytes per second; a factor of `0.000001` displays MB/s.
Pool target `*` with `percent` displays capacity-weighted usage; workload target `*`
with `running` counts running services, excluding nodes. Explicit sources are
recommended when multiple systems expose the same fields, and required for wildcard
collection charts when multiple sources are enabled. Charts retain the last
120 observations in memory; missing samples produce gaps. Histories restart when
the application restarts. Missing or stale readings are never replaced with zero.

Upload PNG, JPEG, WebP, or GIF files through the media library. Uploads are limited
to 10 MiB, 8 million input pixels, 60 frames, and 32 million decoded pixels across
an animation. Media is re-encoded without metadata, at most 1920 pixels per side
and 2,073,600 pixels per frame. The library holds up to 64 assets / 100 MiB.
Referenced assets cannot be deleted until their saved page references are removed.
Serial output sends full frames, so GIFs appear as a slower sequence rather than
video-rate animation. The player and editor also refresh at a bounded rate.

Limits are 20 pages, 48 elements per page, and 128 charts across all pages. Existing
configurations retain their sources, alerts, hardware settings, and pages during
migration. Legacy storage/services pages become editable aggregate views. Back up
the application's data directory before upgrading; old releases cannot read the
new editor configuration. Do not restore an old release against migrated data.

## Other displays and connection types

### Discover devices and determine the output size

In **Einstellungen**, the **Serielles Gerät** field offers detected devices in its
dropdown while still accepting a manually typed path. **Displays suchen** refreshes
the list. Detection uses USB metadata for known AOOSTAR/Synwit candidates and also
includes the explicitly mapped `/dev/aoostar` device. Identical paths/aliases are
deduplicated. An unknown USB serial port is not assumed to be a compatible display.
USB identity is a candidate match, not a successful protocol handshake.

**Ausgabe prüfen / Größe erkennen** checks the selected output without saving.
Saving settings performs the same check. AOOSTAR dimensions come from its known
960 × 376 adapter profile; there is no verified command for querying arbitrary
serial-display dimensions. The check verifies presence and permissions without
sending speculative commands. The normal output connection performs the AOOSTAR
handshake and reports its status separately.

For browser output, first open `/display` on the actual display client. Its short
Player ID appears beside the fullscreen button. Refresh discovery and select that
player under **Browser-Player als Größenreferenz**. With automatic size enabled,
the reported size is applied when settings are saved. Disable automatic size to
keep your manual width and height. Browser reports expire after 90 seconds without
a heartbeat, are kept only in memory, and do not change saved settings on their own.
An offline player leaves the manually specified/last saved size unchanged.
The selection supplies a size reference; all players still mirror the same output.

Browser dimensions are estimates based on screen size and pixel ratio, not EDID
measurements. Browser zoom, OS scaling, and multi-monitor behavior can affect them.
Reports outside the application's supported pixel limits are not registered.

In direct-mapping mode, Docker only exposes devices explicitly passed into the container. Discovery cannot
see arbitrary host USB devices or discover disconnected hardware; no privileged
mode or broad `/dev` mount is required in the web container. The hardware
Compose overlay maps your verified host device to `/dev/aoostar`. For a
different manually specified serial path, pass that device into the container and
set `OPENSCREEN_ALLOWED_DEVICES` to its exact container path. This comma-separated
allowlist supports serial paths such as `/dev/ttyACM0`, `/dev/ttyUSB0`,
`/dev/serial/by-id/...`, or native Windows `COM3`; it does not grant Docker device
permissions or make an unsupported protocol compatible. Block devices, ordinary
files, and network serial URLs are rejected.

### Use a browser display

Under **Einstellungen → Ausgabeziel**, choose **Browser-Display**, set the output
resolution, rotation, fit mode, and refresh interval, then save. Open `/display`
on a device with a browser connected to your screen, such as an HDMI kiosk client.
The player offers fullscreen after a user click and retries connection failures.
It pulls completed PNG frames sequentially, without an accumulating frame queue.
`/api/output.png` also exposes the current rendered output for compatible clients.

The player uses the same network/host access restrictions as the administration UI.
It is not a separate security boundary: admitted clients can still reach the
configuration API. No GPU, framebuffer, USB, or host filesystem mount is needed
for browser output. The browser runs on the display client, not inside this container.

Direct serial support currently covers the AOOSTAR protocol only. A USB or serial
connector alone does not identify a display protocol. Other direct outputs need an
adapter that declares supported dimensions, pixel format, framing, acknowledgement,
and reconnect behavior. Linux framebuffer and DRM/KMS outputs are not implemented;
their device capabilities, pixel layout, and permissions must be verified per driver.
See the [Linux framebuffer API](https://docs.kernel.org/fb/api.html) and
[DRM/KMS documentation](https://docs.kernel.org/gpu/drm-kms.html) for those interfaces.

## Request support for another device

First check the [existing issues](https://github.com/Niklas-s04/aoostar-openscreen/issues)
for your model. If none matches, [open a device-support request](https://github.com/Niklas-s04/aoostar-openscreen/issues/new)
using the template below. Missing information is fine: mark it as unknown rather
than guessing. Feature suggestions can use the same issue tracker; describe the
intended workflow and an example of the expected result.

```text
Title: Device support: <manufacturer> <exact model / hardware revision>

Device and display
- Manufacturer / exact model / hardware revision:
- Product page and official documentation links:
- Display resolution and orientation (or unknown):
- Connection: USB serial / USB HID / HDMI / network / other:
- USB vendor:product ID, if applicable (not the unique serial number):

Environment
- Host OS and version:
- Container platform and OpenScreen version / commit:
- How the display is connected to the host:

Existing software / protocol information
- Official software or driver download links and version:
- Supported Windows/Linux versions:
- Public protocol documentation or relevant open-source projects:
- Known commands, pixel format, refresh limits (or unknown):

Current behavior
- What already works with OpenScreen or the original software:
- Steps tried and actual result:
- Expected result / intended dashboard use:
- Sanitized error messages or relevant log excerpts:

Testing
- Can you test an experimental adapter on this device?
- Can you provide sanitized captures or photos if requested?
```

Issues are public. Remove passwords, API keys, tokens, private URLs, IP addresses,
hostnames, device serial numbers, and unrelated personal data from logs and photos.
Link to official downloads instead of attaching proprietary installers or complete
configuration backups. Do not post credentials or grant remote access. A request
does not guarantee support: a direct adapter needs enough protocol evidence and
testing on the actual hardware. A browser player may already cover the use case.

Discovery polls every three seconds, with bounded exponential backoff for failed
handshakes. Verified connections stay open exclusively. Frame transfers are
serialized per device and rejected when busy rather than queued. Reconnection
changes the connection generation so even an unchanged dashboard is resent.
Device selections survive tty renumbering on the same physical USB port.

## Development

Python 3.13 and uv are required for local development.

```sh
uv sync --frozen
uv run playwright install chromium
uv run pytest -q
```

Set PLAYWRIGHT_EXECUTABLE_PATH to use an existing Chromium installation.
To exercise a disposable Docker stack on a free local port and isolated subnet:

```sh
uv run python scripts/docker_smoke.py
```

To include the broker boundary and restart checks, run
`uv run python scripts/docker_smoke.py --broker`. On Linux, set
`OPENSCREEN_DEVICE_GID` to the verified USB serial group first. The smoke test
uses group 0 by default for Docker Desktop; do not treat that as a production
permission setting. The broker probes supported devices visible to that Docker
host, so use a development machine with no competing display software.
Linux-specific socket, sysfs, and pseudo-terminal checks run with
`uv run pytest tests/test_broker.py tests/test_broker_client.py`.

The integration script removes its own test stack afterward. Pass --keep to leave
a successful stack running. It currently uses Docker socket GID 0 for the tested
Docker Desktop environment; adapt it for other hosts.

A local demo generates sample data without external requests or hardware access:

```sh
OPENSCREEN_DEMO=1 uv run uvicorn openscreen.app:create_app --factory --host 127.0.0.1 --port 8787 --no-proxy-headers
```

Automated coverage includes serial framing, alerts, collectors, configuration
persistence, browser interaction, and access restrictions. Mocked platform API
tests do not establish compatibility with a live installation. Physical display
output, orientation, colors, and reconnection still require hardware validation.
