# Zigbee2MQTT OTA Manager

A small Flask app for hosting custom Zigbee OTA firmware images for Zigbee2MQTT.

It provides:

- a simple web UI for uploading `.ota` / `.zigbee` files
- automatic parsing of Zigbee OTA headers
- a Zigbee2MQTT-compatible override index at `/api/index.json`
- local login for the admin UI
- a pull-only deployment path for Portainer and Docker hosts

## What this is for

This app is meant to be the place where you upload your custom Zigbee OTA files.

Zigbee2MQTT can then fetch:

- the generated OTA index from `/api/index.json`
- the hosted firmware files from `/files/...`

That lets you keep Zigbee2MQTT on one host and run this OTA Manager somewhere else on your LAN.

## Recommended first implementation

For a first deployment, use this layout:

- Zigbee2MQTT stays where it already runs
- this OTA Manager runs as a Portainer stack on your Docker host or Docker-enabled LXC
- Zigbee2MQTT points to this app with `ota.zigbee_ota_override_index_location`

This is the simplest setup because the app only needs to serve HTTP on your LAN.

## Project layout

```text
.
├── .github/workflows/publish-ghcr.yml
├── .vscode/extensions.json
├── app.py
├── compose.yaml
├── compose.ghcr.yaml
├── Dockerfile
├── requirements.txt
├── templates/
├── static/
├── data/
└── files/
```

Use these files for deployment:

- `compose.ghcr.yaml` for Portainer or a pull-only Docker host
- `.env.example` as the starting point for your `.env`

## Requirements

You need:

- a Zigbee2MQTT instance already running on your network
- a Docker host or Docker-enabled LXC for Portainer
- a published image in GHCR, for example `ghcr.io/<your-user>/zigbee-ota-manager:latest`

## First Portainer deployment

### 1) Create persistent folders on the Docker host

On the Docker host or LXC where Portainer runs:

```bash
mkdir -p /srv/ota-manager/data
mkdir -p /srv/ota-manager/files
mkdir -p /opt/stacks/zigbee-ota-manager
```

These folders are used for:

- `/srv/ota-manager/data` → app metadata such as the catalog
- `/srv/ota-manager/files` → uploaded OTA images
- `/opt/stacks/zigbee-ota-manager` → your stack files

### 2) Create the environment file

Copy `.env.example` to `.env` and edit it.

Example:

```env
# Application
OTA_MANAGER_APP_NAME=Zigbee2MQTT OTA Manager
OTA_MANAGER_PORT=8099
OTA_MANAGER_BIND=0.0.0.0
OTA_MANAGER_PUBLIC_BASE_URL=

# Login
OTA_MANAGER_USERNAME=admin
OTA_MANAGER_PASSWORD=change-this-password
OTA_MANAGER_SECRET_KEY=replace-with-a-random-secret-key

# Optional
OTA_MANAGER_MAX_CONTENT_LENGTH=16777216
OTA_MANAGER_TRUST_PROXY=0

# Deployment-only variables for compose.ghcr.yaml
IMAGE_NAME=ghcr.io/your-account/zigbee-ota-manager
CONTAINER_NAME=z2m-ota-manager
OTA_MANAGER_DATA_PATH=/srv/ota-manager/data
OTA_MANAGER_FILES_PATH=/srv/ota-manager/files
```

Notes:

- Leave `OTA_MANAGER_PUBLIC_BASE_URL` empty for a simple LAN-only setup.
- Set `IMAGE_NAME` to the GHCR image you want Portainer to pull.
- Use a long random value for `OTA_MANAGER_SECRET_KEY`.

### 3) Create the Portainer stack

In Portainer:

1. Go to **Stacks**
2. Click **Add stack**
3. Name it something like `zigbee-ota-manager`
4. Paste the contents of `compose.ghcr.yaml`
5. Either:
   - paste the values from your `.env` into Portainer environment variables, or
   - place the `.env` file beside the compose file on the host and deploy from that location

The stack file is:

```yaml
services:
  ota-manager:
    image: ${IMAGE_NAME:-ghcr.io/example-owner/example-repo}:latest
    container_name: ${CONTAINER_NAME:-z2m-ota-manager}
    restart: unless-stopped
    ports:
      - "${OTA_MANAGER_PORT:-8099}:8099"
    env_file:
      - .env
    environment:
      OTA_MANAGER_DATA_DIR: /data
      OTA_MANAGER_FILES_DIR: /files
    volumes:
      - ${OTA_MANAGER_DATA_PATH:-/srv/ota-manager/data}:/data
      - ${OTA_MANAGER_FILES_PATH:-/srv/ota-manager/files}:/files
```

### 4) Deploy and test

After Portainer deploys the stack, open the app in your browser:

```text
http://YOUR-DOCKER-HOST:8099
```

Health endpoint:

```text
http://YOUR-DOCKER-HOST:8099/health
```

If the app is running, sign in and make sure the UI loads.

## Zigbee2MQTT configuration

In your Zigbee2MQTT `configuration.yaml`, add:

```yaml
ota:
  zigbee_ota_override_index_location: http://YOUR-DOCKER-HOST:8099/api/index.json
  disable_automatic_update_check: false
  update_check_interval: 1440
```

Then restart Zigbee2MQTT.

For a LAN-only setup, plain HTTP is fine.

## First OTA upload flow

1. Build your Zigbee OTA image.
2. Open the OTA Manager web UI.
3. Sign in.
4. Upload the OTA file.
5. The app parses the OTA header and updates the catalog.
6. Zigbee2MQTT can now see the image at `/api/index.json`.

## Updating the container later

When you publish a newer image to GHCR, update the Portainer stack by pulling the latest image and redeploying.

Typical flow:

1. Open the stack in Portainer
2. Click **Pull and redeploy** if available, or redeploy the stack after pulling the latest image

If you prefer the CLI on the Docker host:

```bash
docker compose -f compose.ghcr.yaml pull
docker compose -f compose.ghcr.yaml up -d
```

## Backups

Back up these folders on the Docker host:

- `/srv/ota-manager/data`
- `/srv/ota-manager/files`

These contain:

- the generated catalog and metadata
- the uploaded OTA firmware files

## Security notes

For LAN-only use:

- keep the service on your local network
- use a strong app password
- do not expose Portainer to the internet
- do not forward port `8099` on your router

## Troubleshooting

### `env file .env not found`

Create the file first from the example:

```bash
cp .env.example .env
```

### Portainer cannot pull the image

Check:

- the GHCR image name in `IMAGE_NAME`
- whether the image is public
- whether Portainer or the Docker host needs `docker login ghcr.io`

### Uploaded file is rejected

This app expects a Zigbee OTA image with the standard OTA header (`0x0BEEF11E`).
A raw firmware `.bin` file without a Zigbee OTA wrapper will be rejected.

## Optional next steps

Once the first deployment works, you can later add:

- a reverse proxy
- HTTPS
- a public hostname
- stronger access control for the admin UI

But for the first implementation, the simplest approach is:

- Portainer stack
- LAN-only access
- Zigbee2MQTT pointing to `http://YOUR-DOCKER-HOST:8099/api/index.json`
