# AOOSTAR OpenScreen

A self-hosted display dashboard for the AOOSTAR WTR Max 8845. OpenScreen runs in
Docker, collects monitoring data from your homelab, and renders it for the built-in
960 × 376 display. A web interface provides configuration and a live preview.

This is an independent project, not an official AOOSTAR application.

**Status: experimental.** Container operation and automated tests have been
verified. Physical display output and live TrueNAS/Proxmox integration still need
validation. The current web interface is in German.

## Features

- System, storage, services, and network pages with configurable rotation.
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
After reconnecting USB, restarting the container may be necessary.

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

## Development

Python 3.13 and uv are required for local development.

```sh
uv sync --frozen
uv run playwright install chromium
uv run pytest -q
```

Set PLAYWRIGHT_EXECUTABLE_PATH to use an existing Chromium installation.
To exercise a real Docker stack with port 8080 available:

```sh
uv run python scripts/docker_smoke.py
```

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
