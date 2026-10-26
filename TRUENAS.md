# TrueNAS installation

This guide targets TrueNAS SCALE 25.10 with an Apps pool configured. The NAS must
have physical access to the display, either directly or through USB passthrough
when TrueNAS runs in a virtual machine.

The application is experimental. Physical frame output still needs validation.

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
Paste [deploy/truenas-custom-app.yaml](deploy/truenas-custom-app.yaml).

Replace every placeholder before saving:

| Placeholder | Value |
|---|---|
| YOUR_NAS_IP | NAS LAN IPv4 address |
| YOUR_LAN_CIDR | Trusted management subnet, or a single client address with /32 |
| YOUR_POOL | Pool name; adjust the entire data path if necessary |
| YOUR_DISPLAY_ID | Verified filename under /dev/serial/by-id |
| YOUR_DEVICE_GID | Verified numeric serial-device group ID |

The directory must already exist. Port 8088 must be free. For a WebUI-only first
start, remove both devices and group_add until the device has been identified.

Official instructions:
[Installing Custom Apps](https://apps.truenas.com/managing-apps/installing-custom-apps/).

Open http://YOUR_NAS_IP:8088. There is no login. Every allowed client can change
the configuration. Keep loopback in the allowed networks/hosts for the healthcheck.
Do not use public proxies, tunnels, or router port forwarding. Source NAT can make
external traffic appear local; separate guest and IoT networks at the router.

## 4. Enable the display

In **Einstellungen** (Settings), set the device to /dev/aoostar and enable hardware
output. Start with the system page and a 20-second rotation interval. Compare the
preview, connection status, last-frame timestamp, and actual physical image.

The container path is /dev/aoostar regardless of the host device name. Resolution
and baud rate are implemented by the driver. Stop any manufacturer software that
uses the same serial port. USB reconnection may require restarting the app.

For permission errors, check the device mapping and numeric group. Do not enable
privileged mode. A failed handshake requires hardware/protocol investigation.

## 5. Optional monitoring credentials

Display output does not require NAS API access. To show TrueNAS apps and pools,
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
adapter currently provides apps and pools, not system-container, SMART, or
remote CPU/network metrics. A Docker socket mount is not required for this setup.

Only mount the app data directory, optional isolated API credentials, and the
single display device. Do not mount host root, pools, host proc/sys, or Docker
socket into the application. To stop using the display, disable hardware output
or stop the Custom App; keep the data directory for later use.
