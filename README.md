# Zigbee2MQTT OTA Manager

A small Flask app for hosting custom Zigbee OTA firmware images for Zigbee2MQTT.

It provides:

- a simple web UI for uploading `.ota` / `.zigbee` files
- automatic parsing of Zigbee OTA headers
- a Zigbee2MQTT-compatible override index at `/api/index.json`
- local login for the admin UI
- two deployment paths:
  - local build with Docker Compose
  - GitHub Actions build to GitHub Container Registry (GHCR) for pull-only deployment hosts

## Why this layout

Zigbee2MQTT supports a remote OTA override index via `ota.zigbee_ota_override_index_location`, including URLs served over HTTP(S).

That means you can run this app anywhere reachable by your Zigbee2MQTT instance, upload OTA images through the UI, and let Zigbee2MQTT fetch the generated `index.json` plus the firmware files it references. Hosted OTA entries need `url`, `manufacturerCode`, `imageType`, and `fileVersion`, which this app extracts from the OTA header and emits automatically.

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

`compose.yaml` is the local build file.

`compose.ghcr.yaml` is the deployment file for hosts that should only pull a published image from GHCR.

## Requirements

- Docker with the Compose plugin installed
- a Zigbee2MQTT instance running somewhere on your network
- a GitHub repository if you want automatic image publishing

## 1) Local development or LAN-only deployment

Clone the repository, then create your environment file:

```bash
cp .env.example .env
```

Edit `.env` and set at least:

```env
OTA_MANAGER_USERNAME=admin
OTA_MANAGER_PASSWORD=change-this-password
OTA_MANAGER_SECRET_KEY=replace-with-a-random-secret-key
OTA_MANAGER_PUBLIC_BASE_URL=
```

Leave `OTA_MANAGER_PUBLIC_BASE_URL` empty if you want the app to derive its base URL from the current request automatically. Set it only if you want a fixed hostname or a reverse-proxy URL.

Build and start locally:

```bash
docker compose up --build -d
```

Open the UI in your browser:

```text
http://YOUR-HOSTNAME-OR-IP:8099
```

The app exposes a health endpoint at:

```text
http://YOUR-HOSTNAME-OR-IP:8099/health
```

## 2) Push to GitHub and publish images to GHCR

Create a GitHub repository and upload the project.

The included workflow in `.github/workflows/publish-ghcr.yml` will:

- run on pushes to `main`
- log in to `ghcr.io`
- build the container image
- publish both:
  - `latest`
  - `sha-<commit>`

### Optional: make the container package public

If you want your deployment host to pull the image without a registry login, make the GHCR package public.

If you keep the package private, the deployment host will need `docker login ghcr.io` with a token that has package read access.

## 3) Pull-only deployment on a Docker host or LXC

On the deployment host, copy only these files:

- `compose.ghcr.yaml`
- `.env` based on `.env.example`

Then set your deployment values in `.env`, for example:

```env
IMAGE_NAME=ghcr.io/your-account/your-repository
CONTAINER_NAME=z2m-ota-manager
OTA_MANAGER_PORT=8099
OTA_MANAGER_DATA_PATH=/srv/ota-manager/data
OTA_MANAGER_FILES_PATH=/srv/ota-manager/files
OTA_MANAGER_USERNAME=admin
OTA_MANAGER_PASSWORD=change-this-password
OTA_MANAGER_SECRET_KEY=replace-with-a-random-secret-key
OTA_MANAGER_PUBLIC_BASE_URL=
```

Create the bind-mount directories:

```bash
mkdir -p /srv/ota-manager/data
mkdir -p /srv/ota-manager/files
```

Start the service:

```bash
docker compose -f compose.ghcr.yaml pull
docker compose -f compose.ghcr.yaml up -d
```

To update later after pushing new code to `main`:

```bash
docker compose -f compose.ghcr.yaml pull
docker compose -f compose.ghcr.yaml up -d
```

## 4) Zigbee2MQTT configuration

In your Zigbee2MQTT `configuration.yaml`, point the OTA override index to this app:

```yaml
ota:
  zigbee_ota_override_index_location: http://YOUR-HOSTNAME-OR-IP:8099/api/index.json
  disable_automatic_update_check: false
  update_check_interval: 1440
```

If your app is exposed through a reverse proxy or hostname, use that URL instead:

```yaml
ota:
  zigbee_ota_override_index_location: https://ota.example.invalid/api/index.json
```

## 5) Upload flow

1. Build your firmware OTA image.
2. Sign in to the web UI.
3. Upload the OTA image.
4. The app parses the header and adds the image to the generated index.
5. Zigbee2MQTT sees the image on the next OTA check.

## Security notes

- The admin UI is protected by a basic app login if `OTA_MANAGER_PASSWORD` is set.
- `/api/index.json` and `/files/...` stay publicly readable by design so Zigbee2MQTT can fetch them.
- For LAN-only use, keep the service on your local network.
- If you later publish it behind a reverse proxy, consider protecting only the UI routes and leaving the machine-consumed endpoints reachable without interactive login.

## Backups

Back up these directories on the deployment host:

- `data/`
- `files/`

`data/catalog.json` keeps the app’s metadata, while `files/` contains the actual OTA images.

## Notes for VS Code

Recommended extensions are listed in `.vscode/extensions.json`:

- Python
- Container Tools

## Suggested first commit flow

```bash
git init
git add .
git commit -m "Initial OTA manager import"
git branch -M main
git remote add origin https://github.com/your-account/your-repository.git
git push -u origin main
```

Once the first push completes, the workflow will publish the container image to GHCR.

## Troubleshooting

### `env file .env not found`
Create it first:

```bash
cp .env.example .env
```

### `docker compose pull` asks for login
Your GHCR package is probably private. Either:

- make the package public, or
- run `docker login ghcr.io` on the deployment host with a token that can read packages.

### Uploaded file is rejected
This app expects a Zigbee OTA image with the standard OTA header (`0x0BEEF11E`). A raw firmware `.bin` without a Zigbee OTA wrapper will be rejected.

## Customization ideas

- split the admin UI and the public file/index endpoints behind different auth policies
- add release notes per firmware file
- add hardware-version filtering in your upload workflow
- add per-device views or JSON export endpoints
