from __future__ import annotations

import hashlib
import json
import os
import secrets
import struct
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

APP_NAME = os.environ.get("OTA_MANAGER_APP_NAME", "Zigbee2MQTT OTA Manager")
DATA_DIR = Path(os.environ.get("OTA_MANAGER_DATA_DIR", "/data"))
UPLOAD_DIR = Path(os.environ.get("OTA_MANAGER_FILES_DIR", "/files"))
CATALOG_PATH = DATA_DIR / "catalog.json"
ALLOWED_EXTENSIONS = {"ota", "zigbee", "bin"}
MAX_CONTENT_LENGTH = int(os.environ.get("OTA_MANAGER_MAX_CONTENT_LENGTH", str(16 * 1024 * 1024)))
PUBLIC_BASE_URL = os.environ.get("OTA_MANAGER_PUBLIC_BASE_URL", "").strip().rstrip("/")
ADMIN_USERNAME = os.environ.get("OTA_MANAGER_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("OTA_MANAGER_PASSWORD", "")
BIND = os.environ.get("OTA_MANAGER_BIND", "0.0.0.0")
PORT = int(os.environ.get("OTA_MANAGER_PORT", "8099"))
TRUST_PROXY = os.environ.get("OTA_MANAGER_TRUST_PROXY", "0").lower() in {"1", "true", "yes"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
app.secret_key = os.environ.get("OTA_MANAGER_SECRET_KEY", secrets.token_hex(32))

if TRUST_PROXY:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)


@dataclass
class OtaEntry:
    filename: str
    manufacturerCode: int
    imageType: int
    fileVersion: int
    fileSize: int
    otaHeaderString: str
    sha512: str
    uploadedAt: str
    force: bool = False
    minimumHardwareVersion: int | None = None
    maximumHardwareVersion: int | None = None
    notes: str = ""


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def sanitize_filename(filename: str) -> str:
    safe = secure_filename(filename)
    if not safe:
        safe = f"upload-{secrets.token_hex(4)}.ota"
    return safe


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def display_hex(value: int) -> str:
    return f"0x{value:04X}" if value <= 0xFFFF else f"0x{value:08X}"


def get_public_base_url() -> str:
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL
    return request.url_root.rstrip("/")


def parse_ota_file(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if len(data) < 56:
        raise ValueError("File is too small to be a valid Zigbee OTA image.")

    file_identifier = struct.unpack_from("<I", data, 0)[0]
    if file_identifier != 0x0BEEF11E:
        raise ValueError(
            f"Unexpected OTA file identifier: 0x{file_identifier:08X}. "
            "Expected a Zigbee OTA image starting with 0x0BEEF11E."
        )

    header_version, header_length, field_control = struct.unpack_from("<HHH", data, 4)
    manufacturer_code, image_type = struct.unpack_from("<HH", data, 10)
    file_version = struct.unpack_from("<I", data, 14)[0]
    zigbee_stack_version = struct.unpack_from("<H", data, 18)[0]
    ota_header_string = data[20:52].split(b"\\x00", 1)[0].decode("utf-8", errors="replace").strip()
    total_image_size = struct.unpack_from("<I", data, 52)[0]

    offset = 56
    minimum_hw = None
    maximum_hw = None
    if field_control & 0x01:
        offset += 1
    if field_control & 0x02:
        offset += 8
    if field_control & 0x04:
        if len(data) < offset + 4:
            raise ValueError("OTA header indicates hardware versions, but the file ended early.")
        minimum_hw, maximum_hw = struct.unpack_from("<HH", data, offset)

    sha512_hex = hashlib.sha512(data).hexdigest()

    return {
        "headerVersion": header_version,
        "headerLength": header_length,
        "fieldControl": field_control,
        "manufacturerCode": manufacturer_code,
        "imageType": image_type,
        "fileVersion": file_version,
        "zigbeeStackVersion": zigbee_stack_version,
        "otaHeaderString": ota_header_string,
        "fileSize": len(data),
        "totalImageSize": total_image_size,
        "minimumHardwareVersion": minimum_hw,
        "maximumHardwareVersion": maximum_hw,
        "sha512": sha512_hex,
    }


def load_catalog() -> list[OtaEntry]:
    if not CATALOG_PATH.exists():
        return []
    try:
        raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        return [OtaEntry(**item) for item in raw]
    except Exception:
        return []


def save_catalog(entries: list[OtaEntry]) -> None:
    entries_sorted = sorted(entries, key=lambda item: (item.manufacturerCode, item.imageType, item.fileVersion), reverse=True)
    CATALOG_PATH.write_text(
        json.dumps([asdict(item) for item in entries_sorted], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def build_index(entries: list[OtaEntry], base_url: str) -> list[dict[str, Any]]:
    index_entries: list[dict[str, Any]] = []
    for item in entries:
        row: dict[str, Any] = {
            "url": f"{base_url}/files/{item.filename}",
            "manufacturerCode": item.manufacturerCode,
            "imageType": item.imageType,
            "fileVersion": item.fileVersion,
            "fileSize": item.fileSize,
            "sha512": item.sha512,
            "otaHeaderString": item.otaHeaderString,
        }
        if item.minimumHardwareVersion is not None:
            row["minimumHardwareVersion"] = item.minimumHardwareVersion
        if item.maximumHardwareVersion is not None:
            row["maximumHardwareVersion"] = item.maximumHardwareVersion
        if item.force:
            row["force"] = True
        index_entries.append(row)
    return index_entries


def rebuild_catalog_from_uploads() -> None:
    existing = {entry.filename: entry for entry in load_catalog()}
    rebuilt: list[OtaEntry] = []

    for path in sorted(UPLOAD_DIR.iterdir()):
        if not path.is_file():
            continue
        try:
            parsed = parse_ota_file(path)
        except ValueError:
            continue

        prior = existing.get(path.name)
        rebuilt.append(
            OtaEntry(
                filename=path.name,
                manufacturerCode=parsed["manufacturerCode"],
                imageType=parsed["imageType"],
                fileVersion=parsed["fileVersion"],
                fileSize=parsed["fileSize"],
                otaHeaderString=parsed["otaHeaderString"],
                sha512=parsed["sha512"],
                uploadedAt=prior.uploadedAt if prior else utc_now(),
                force=prior.force if prior else False,
                minimumHardwareVersion=parsed.get("minimumHardwareVersion"),
                maximumHardwareVersion=parsed.get("maximumHardwareVersion"),
                notes=prior.notes if prior else "",
            )
        )

    save_catalog(rebuilt)


def is_logged_in() -> bool:
    if not ADMIN_PASSWORD:
        return True
    return session.get("auth") is True


def login_required() -> bool:
    return bool(ADMIN_PASSWORD)


@app.before_request
def protect_routes() -> Any:
    public_paths = {"login", "static", "files", "api_index", "api_catalog", "health"}
    if request.endpoint in public_paths:
        return None
    if login_required() and not is_logged_in():
        return redirect(url_for("login", next=request.path))
    return None


@app.route("/health", methods=["GET"])
def health() -> Any:
    return jsonify({"ok": True, "app": APP_NAME})


@app.route("/login", methods=["GET", "POST"])
def login() -> Any:
    if not login_required():
        return redirect(url_for("home"))

    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["auth"] = True
            flash("Signed in.", "success")
            next_url = request.args.get("next") or url_for("home")
            return redirect(next_url)
        flash("Invalid username or password.", "error")

    return render_template("login.html", app_name=APP_NAME)


@app.route("/logout", methods=["POST"])
def logout() -> Any:
    session.clear()
    flash("Signed out.", "success")
    return redirect(url_for("login"))


@app.route("/", methods=["GET"])
def home() -> Any:
    entries = load_catalog()
    groups: dict[tuple[int, int], list[OtaEntry]] = {}
    for entry in entries:
        groups.setdefault((entry.manufacturerCode, entry.imageType), []).append(entry)

    summary = []
    for (manufacturer_code, image_type), group_entries in sorted(groups.items(), reverse=True):
        summary.append(
            {
                "manufacturerCode": manufacturer_code,
                "imageType": image_type,
                "manufacturerHex": display_hex(manufacturer_code),
                "imageTypeHex": display_hex(image_type),
                "count": len(group_entries),
                "latest": max(group_entries, key=lambda item: item.fileVersion),
                "entries": sorted(group_entries, key=lambda item: item.fileVersion, reverse=True),
            }
        )

    base_url = get_public_base_url()
    return render_template(
        "index.html",
        app_name=APP_NAME,
        public_base_url=base_url,
        index_url=f"{base_url}/api/index.json",
        entries=entries,
        groups=summary,
        max_size_mb=MAX_CONTENT_LENGTH // (1024 * 1024),
        login_required=login_required(),
    )


@app.route("/upload", methods=["POST"])
def upload() -> Any:
    file = request.files.get("file")
    notes = request.form.get("notes", "").strip()
    force = request.form.get("force") == "on"

    if not file or not file.filename:
        flash("Choose an OTA file first.", "error")
        return redirect(url_for("home"))

    if not allowed_file(file.filename):
        flash("Only .ota, .zigbee, or .bin files are allowed.", "error")
        return redirect(url_for("home"))

    filename = sanitize_filename(file.filename)
    target = UPLOAD_DIR / filename
    stem = target.stem
    suffix = target.suffix
    counter = 1
    while target.exists():
        target = UPLOAD_DIR / f"{stem}-{counter}{suffix}"
        counter += 1

    file.save(target)

    try:
        parsed = parse_ota_file(target)
    except ValueError as exc:
        target.unlink(missing_ok=True)
        flash(str(exc), "error")
        return redirect(url_for("home"))

    entries = [entry for entry in load_catalog() if entry.filename != target.name]
    entries.append(
        OtaEntry(
            filename=target.name,
            manufacturerCode=parsed["manufacturerCode"],
            imageType=parsed["imageType"],
            fileVersion=parsed["fileVersion"],
            fileSize=parsed["fileSize"],
            otaHeaderString=parsed["otaHeaderString"],
            sha512=parsed["sha512"],
            uploadedAt=utc_now(),
            force=force,
            minimumHardwareVersion=parsed.get("minimumHardwareVersion"),
            maximumHardwareVersion=parsed.get("maximumHardwareVersion"),
            notes=notes,
        )
    )
    save_catalog(entries)

    flash(
        f"Uploaded {target.name} (manufacturer {display_hex(parsed['manufacturerCode'])}, "
        f"image type {display_hex(parsed['imageType'])}, file version {display_hex(parsed['fileVersion'])}).",
        "success",
    )
    return redirect(url_for("home"))


@app.route("/entries/<path:filename>/delete", methods=["POST"])
def delete_entry(filename: str) -> Any:
    entries = load_catalog()
    updated = [entry for entry in entries if entry.filename != filename]
    if len(updated) == len(entries):
        flash("Entry not found.", "error")
        return redirect(url_for("home"))

    (UPLOAD_DIR / filename).unlink(missing_ok=True)
    save_catalog(updated)
    flash(f"Deleted {filename}.", "success")
    return redirect(url_for("home"))


@app.route("/entries/<path:filename>/toggle-force", methods=["POST"])
def toggle_force(filename: str) -> Any:
    entries = load_catalog()
    changed = False
    for entry in entries:
        if entry.filename == filename:
            entry.force = not entry.force
            changed = True
            break
    if changed:
        save_catalog(entries)
        flash(f"Toggled force for {filename}.", "success")
    else:
        flash("Entry not found.", "error")
    return redirect(url_for("home"))


@app.route("/api/index.json", methods=["GET"])
def api_index() -> Any:
    return jsonify(build_index(load_catalog(), get_public_base_url()))


@app.route("/api/catalog", methods=["GET"])
def api_catalog() -> Any:
    return jsonify([asdict(item) for item in load_catalog()])


@app.route("/files/<path:filename>", methods=["GET"])
def files(filename: str) -> Any:
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=False)


@app.template_filter("filesize")
def filesize_filter(value: int) -> str:
    size = float(value)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


@app.template_filter("dt")
def datetime_filter(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return value


@app.template_filter("hexval")
def hex_filter(value: int) -> str:
    return display_hex(value)


ensure_dirs()
rebuild_catalog_from_uploads()


if __name__ == "__main__":
    app.run(host=BIND, port=PORT, debug=True)
