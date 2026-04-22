# Zigbee2MQTT OTA Manager

A small Flask app for hosting custom Zigbee OTA firmware images for Zigbee2MQTT.

It provides:
- a web UI for uploading `.ota` / `.zigbee` files
- automatic parsing of Zigbee OTA headers
- a Zigbee2MQTT-compatible override index at `/api/index.json`
- local login for the admin UI
- a Portainer-friendly deployment path for LAN-only setups

## Recommended use

This repo is aimed at a simple first deployment:
- Zigbee2MQTT stays where it already runs
- this OTA Manager runs as a stack on a separate Docker host or Docker-enabled LXC
- Zigbee2MQTT points to this app with `ota.zigbee_ota_override_index_location`

For most installations, the only file you need in Portainer is:
- `compose.portainer.yaml`

## What changed in this simplified repo

The repo has been trimmed down to match the current Portainer-first workflow:
- `compose.ghcr.yaml` was removed because it duplicated `compose.yaml`
- `.vscode/` was removed because it is editor metadata, not part of the app
- `data/` and `files/` were removed because they are runtime storage paths on the Docker host, not source files

## Repo layout

```text
.
├── .github/workflows/publish-ghcr.yml
├── .dockerignore
├── .env.example
├── .gitignore
├── app.py
├── compose.portainer.yaml
├── compose.yaml
├── Dockerfile
├── LICENSE
├── README.md
├── requirements.txt
├── static/
└── templates/
```

## Which compose file should you use?

### `compose.portainer.yaml`
Use this for the first deployment in Portainer.

It is intentionally minimal and only requires a few variables in Portainer:
- `IMAGE_REF`
- `OTA_MANAGER_PASSWORD`
- `OTA_MANAGER_SECRET_KEY`
- `OTA_MANAGER_DATA_PATH`
- `OTA_MANAGER_FILES_PATH`

### `compose.yaml`
Use this only if you want a more configurable stack with separate image name/tag variables and a few more optional overrides.

For a normal Portainer deployment, `compose.portainer.yaml` is the better choice.

## Requirements

You need:
- a Zigbee2MQTT instance already running on your network
- a Docker host or Docker-enabled LXC running Portainer
- a published container image, for example `ghcr.io/<your-user>/zigbee-ota-manager:latest`

## First implementation in Portainer

### 1) Create persistent folders on the Docker host

On the Docker host or Docker-enabled LXC:

```bash
mkdir -p /srv/ota-manager/data
mkdir -p /srv/ota-manager/files
```

These folders are used for:
- `/srv/ota-manager/data` → generated catalog and metadata
- `/srv/ota-manager/files` → uploaded OTA firmware files

### 2) Create a strong secret key

Generate a random secret key, for example:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 3) Create the stack in Portainer

In Portainer:
1. Go to **Stacks**
2. Click **Add stack**
3. Name it something like `zigbee-ota-manager`
4. Paste the contents of `compose.portainer.yaml`
5. Add these environment variables in Portainer:

```text
IMAGE_REF=ghcr.io/<your-user>/zigbee-ota-manager:latest
OTA_MANAGER_PASSWORD=change-this-password
OTA_MANAGER_SECRET_KEY=<your-random-secret>
OTA_MANAGER_DATA_PATH=/srv/ota-manager/data
OTA_MANAGER_FILES_PATH=/srv/ota-manager/files
```

Optional variables:

```text
HOST_PORT=8099
OTA_MANAGER_USERNAME=admin
CONTAINER_NAME=z2m-ota-manager
OTA_MANAGER_PUBLIC_BASE_URL=
OTA_MANAGER_MAX_CONTENT_LENGTH=16777216
OTA_MANAGER_TRUST_PROXY=0
LOG_MAX_SIZE=10m
LOG_MAX_FILE=3
```

### 4) Deploy and test

After Portainer deploys the stack, open:

```text
http://YOUR-DOCKER-HOST:8099
```

Health endpoint:

```text
http://YOUR-DOCKER-HOST:8099/health
```

Sign in with the username and password you configured.

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

1. Build your Zigbee OTA image
2. Open the OTA Manager web UI
3. Sign in
4. Upload the OTA file
5. The app parses the OTA header and updates the catalog
6. Zigbee2MQTT can now see the image at `/api/index.json`

## Updating the container later

If the image tag in Portainer is `:latest`, your normal update flow is:
1. Open the stack in Portainer
2. Pull the latest image
3. Redeploy the stack

If you prefer the CLI on the Docker host:

```bash
docker compose -f compose.portainer.yaml pull
docker compose -f compose.portainer.yaml up -d
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
- use a strong random secret key
- do not expose Portainer to the internet
- do not forward port `8099` on your router unless you intentionally want external access

## Troubleshooting

### Portainer cannot pull the image

Check:
- that `IMAGE_REF` points to the correct GHCR image
- whether the image is public
- whether the Docker host needs `docker login ghcr.io`

### Uploaded file is rejected

This app expects a Zigbee OTA image with the standard OTA header (`0x0BEEF11E`). A raw firmware `.bin` file without a Zigbee OTA wrapper will be rejected.

## License

MIT
