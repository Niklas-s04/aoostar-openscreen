# TrueNAS installation

This guide targets TrueNAS SCALE 25.10 with an Apps pool configured. The NAS must
have physical access to the display, either directly or through USB passthrough
when TrueNAS runs in a virtual machine.

This guide covers release 1.0.0. Physical frame output still needs validation.

The optional display broker handles USB serial discovery and reconnects within
the Custom App. No host Python packages, `apt` commands, systemd units, custom
udev rules, or developer mode are required. TrueNAS is an appliance: keep the
software inside the app image and use supported Apps management. See the
[TrueNAS developer-mode guidance](https://www.truenas.com/docs/scale/scaletutorials/systemsettings/advanced/developermode/).

## 1. Build and transfer the image

Build on a machine running Docker:

```sh
docker build -t aoostar-openscreen:local .
docker image save -o aoostar-openscreen.tar aoostar-openscreen:local
```

Copy the archive to an existing NAS share. In the NAS administration shell, replace
the example path and import it:

```sh
sudo docker image load -i /mnt/POOL/transfer/aoostar-openscreen.tar
sudo docker image inspect aoostar-openscreen:local --format '{{.Os}}/{{.Architecture}}'
```

Expected platform for the WTR Max 8845: linux/amd64. The import does not start
a container. Keep app lifecycle management in TrueNAS rather than starting a
separate Compose stack from the shell. If the local image is removed, import it
again before redeployment.

## 2. Prepare storage and identify the device

Create a dedicated data directory, for example /mnt/POOL/apps/openscreen/data.
Grant container UID 10001 read, write, and directory traversal access, including
traversal through parent directories. Use the TrueNAS storage/permissions UI.
Do not modify internal TrueNAS app datasets or replace existing ACLs blindly.

No password file or secret mount is required for the base deployment.

Identify the serial device with USB vendor/product ID 0416:90a1:

```sh
ls -l /dev/serial/by-id/
udevadm info --query=property --name=/dev/ttyACM0
stat -Lc '%g' /dev/ttyACM0
```

Use the actual device path on your host. The tty name and numeric group must be
verified. A USB device without a serial node is not sufficient for this driver.

## 3. Install the Custom App

Go to **Apps → Discover Apps → ⋮ → Install via YAML** and name the app openscreen.
For automatic USB discovery, paste
[deploy/truenas-broker-app.yaml](deploy/truenas-broker-app.yaml).
For direct mapping of one device, use the alternative
[deploy/truenas-custom-app.yaml](deploy/truenas-custom-app.yaml). Choose one template.

Replace every placeholder before saving:

| Placeholder | Value |
|---|---|
| YOUR_NAS_IP | NAS LAN IPv4 address |
| YOUR_LAN_CIDR | Trusted management subnet, or a single client address with /32 |
| YOUR_POOL | Pool name; adjust the entire data path if necessary |
| YOUR_DISPLAY_ID | Direct-mapping template only: verified filename under /dev/serial/by-id |
| YOUR_DEVICE_GID | Verified numeric serial-device group ID |

The directory must already exist. Port 8088 must be free. The broker template uses
the same locally imported image for both services and a dedicated named volume for
its Unix socket. Both services run as UID/GID 10001. The image initializes the
socket directory with owner 10001 and mode 0700; a fresh named volume inherits it.
The web service mounts this volume read-only and receives no host devices.

For a WebUI-only first start, use the direct-mapping template and remove both
`devices` and `group_add` until the device has been identified.

Official instructions:
[Installing Custom Apps](https://apps.truenas.com/managing-apps/installing-custom-apps/).

Open http://YOUR_NAS_IP:8088. There is no login. Every allowed client can change
the configuration. Keep loopback in the allowed networks/hosts for the healthcheck.
Do not use public proxies, tunnels, or router port forwarding. Source NAT can make
external traffic appear local; separate guest and IoT networks at the router.

## 4. Enable the display

With the broker template, open **Einstellungen** (Settings), choose output kind
`broker`, refresh device discovery, select a confirmed display or `auto`, enable
output, and save. `auto` requires an unambiguous compatible device. Unknown USB
serial candidates are shown as unsupported and are not actively probed. Currently
only USB **0416:90a1** with a successful AOOSTAR protocol ACK is selectable. The
adapter profile fixes the size at **960 × 376**; it does not query arbitrary display
dimensions. Metadata and ACK confirmation do not validate the physical image.

With the direct-mapping template, set the device to `/dev/aoostar` and enable
hardware output. Start with a 20-second rotation interval. Compare the preview,
connection status, last-frame timestamp, and actual physical image.

Stop any manufacturer software that uses the same serial port. The broker watches
the host device directories so USB reconnection does not require container
recreation or a new device mapping. Direct mapping may require an app restart.

The broker has no network, published port, Docker socket, or extra capabilities.
It binds `/dev` and `/sys` read-only for discovery and permits read/write access
only to USB ACM/serial character-device classes (major 166/188), subject to Unix
permissions. These wildcard minor rules allow replacement device nodes after
hotplug. They do not grant disk access or permission to create device nodes. A
read-only `/dev` mount still allows character-device I/O. The broker can inspect
host device metadata and may access other USB serial ports in the permitted group;
the adapter whitelist restricts normal application use. USB identities are
spoofable. The web service only connects to the mode-0600 Unix socket through its
read-only shared volume. See [Docker device cgroup rules](https://docs.docker.com/reference/compose-file/services/#device_cgroup_rules).

For permission errors, check the device mapping or broker mounts and numeric group. Do not enable
privileged mode. A failed handshake requires hardware/protocol investigation.
If the broker cannot create its socket, inspect the dedicated socket volume's
owner and ensure the current image was imported; do not grant root privileges or
change the data dataset's permissions as a workaround. The broker healthcheck
checks the Unix API, not the physical screen.

## 5. Optional monitoring credentials

Display output does not require NAS API access. To show TrueNAS host data, apps and pools,
create a separate API key with the necessary read permissions.

Create an isolated secrets directory containing only that key and, if needed,
a CA certificate. Files must be readable by UID 10001. Add an optional volume:

```yaml
      - type: bind
        source: /mnt/YOUR_POOL/apps/openscreen/secrets
        target: /run/secrets
        read_only: true
        bind:
          create_host_path: false
```

Set OPENSCREEN_ALLOWED_SOURCE_URLS to the exact HTTPS base URL of your NAS.
In the web interface add a TrueNAS source with that URL, the API-key filename,
and optionally the CA filename. The TLS certificate must match the hostname or IP.
Test the connection, then assign the source to display pages.

For additional sources, add their exact base URLs to the comma-separated
allowlist and redeploy. The web interface cannot change that allowlist.
Existing sources not present in it prevent startup.

Local runtime metrics do not necessarily describe the NAS host. The TrueNAS
adapter uses a persistent versioned WebSocket for host CPU, RAM, temperature and
network/disk rates. Apps, pools and system containers depend on available read
methods and permissions; unavailable or stale features remain unknown and are
identified in the source details. System containers remain distinct from apps.
Set `network_interface=eth0` in the source field/options area to select exactly
one interface; absent a selection, multiple interfaces are not summed. SMART is
not implemented. A Docker socket mount is not required for this setup.

Browser size references measure the player rendering area, not native
panel resolution. Broker modes are checked against adapter capabilities; unknown
protocols remain unsupported. Use the temporary settings test image to inspect
the actual screen: confirm or cancel within 60 seconds; cancellation or timeout
restores prior output. A successful protocol ACK alone does not validate colors,
cropping or orientation. These changes require a separately authorized app update;
development and automated tests do not deploy anything to the NAS.

Only mount app data and optional isolated API credentials into the web service,
plus either the broker socket volume or the single directly mapped display.
Keep host root, pools, host proc/sys, and the Docker socket out of the web service.
The broker's documented `/dev` and `/sys` mounts are confined to its separate
container. To stop using the display, disable hardware output or stop the Custom
App; keep the data directory for later use. Removing the broker service and its
socket mount/environment revokes broker access without deleting app data.
