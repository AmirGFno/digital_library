#!/usr/bin/env python3
"""Build the small in-place update package for the installed edition.

The installed build is a normal folder, so an update only has to ship the files
whose bytes actually changed. This script compares the freshly built folder with
the manifest of the previous release's update package and writes

    DigitalLibrary-<version>-from-<previous>-windows-x64-update.zip

containing the changed files, an ``install_info.json`` marker with the new
version and ``update.json`` with the full file manifest, the version it upgrades
from and the files that must be removed.

The app chains these per-version packages: an install three releases behind
downloads the three small files instead of one big one.

A release without a previous manifest gets a package that holds every file
(named without the ``from-`` part); it can be applied on any older version.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from typing import Dict, Optional, Tuple

MANIFEST_NAME = "update.json"
INSTALL_MARKER = "install_info.json"
REQUIRED_EXECUTABLE = "DigitalLibrary.exe"
CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_manifest(directory: Path) -> Dict[str, str]:
    """``relative/path`` -> sha256 for every file in ``directory``."""
    root = Path(directory)
    manifest: Dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            manifest[path.relative_to(root).as_posix()] = sha256_file(path)
    return manifest


def _clean_name(name: object) -> str:
    return str(name).replace("\\", "/").lstrip("./")


def manifest_from_payload(payload: object) -> Dict[str, str]:
    """Read the ``files`` map of an ``update.json`` payload."""
    if not isinstance(payload, dict):
        return {}
    files = payload.get("files")
    if not isinstance(files, dict):
        return {}
    return {
        _clean_name(name): str(digest).lower()
        for name, digest in files.items()
        if _clean_name(name)
    }


def read_manifest(archive: Optional[Path]) -> Dict:
    """The ``update.json`` payload of a package (empty dict when missing)."""
    if not archive:
        return {}
    archive = Path(archive)
    if not archive.is_file():
        raise SystemExit(f"update package not found: {archive}")
    with zipfile.ZipFile(archive) as bundle:
        if MANIFEST_NAME not in bundle.namelist():
            return {}
        payload = json.loads(bundle.read(MANIFEST_NAME).decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def previous_manifest(archive: Optional[Path]) -> Dict[str, str]:
    """Manifest of an older update package, or an empty map."""
    files = manifest_from_payload(read_manifest(archive))
    # These two names are generated, never compared as program files.
    files.pop(INSTALL_MARKER, None)
    files.pop(MANIFEST_NAME, None)
    return files


def package_name(version: str, from_version: str = "") -> str:
    """File name of the update package published with a release."""
    if from_version:
        return f"DigitalLibrary-{version}-from-{from_version}-windows-x64-update.zip"
    return f"DigitalLibrary-{version}-windows-x64-update.zip"


def plan_update(
    current: Dict[str, str], previous: Dict[str, str]
) -> Tuple[list, list]:
    """Files to ship and files that disappeared since the old release."""
    changed = sorted(
        name for name, digest in current.items() if previous.get(name) != digest
    )
    removed = sorted(name for name in previous if name not in current)
    return changed, removed


def _write_bytes(bundle: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    bundle.writestr(info, data)


def _write_file(bundle: zipfile.ZipFile, name: str, path: Path) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    with open(path, "rb") as source, bundle.open(info, "w") as target:
        for chunk in iter(lambda: source.read(CHUNK), b""):
            target.write(chunk)


def marker_payload(version: str) -> bytes:
    payload = {"installed": True, "version": str(version), "installer": "update"}
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def build_package(
    dist: Path,
    version: str,
    output: Path,
    previous: Optional[Path] = None,
    from_version: str = "",
) -> dict:
    """Write the update package and return a summary dictionary."""
    dist = Path(dist)
    output = Path(output)
    current = tree_manifest(dist)
    if REQUIRED_EXECUTABLE not in current:
        raise SystemExit(f"{REQUIRED_EXECUTABLE} is missing in {dist}")
    if not current:
        raise SystemExit(f"the build folder is empty: {dist}")

    previous_files = previous_manifest(previous)
    changed, removed = plan_update(current, previous_files)
    files_total = len(current)
    if previous_files and from_version:
        recorded = str((read_manifest(previous) or {}).get("version") or "")
        if recorded and recorded != str(from_version):
            raise SystemExit(
                f"the previous package is {recorded}, not {from_version}"
            )

    marker = marker_payload(version)
    current[INSTALL_MARKER] = hashlib.sha256(marker).hexdigest()
    if INSTALL_MARKER not in changed:
        changed.append(INSTALL_MARKER)
    changed.sort()

    manifest = {
        "version": str(version),
        "from_version": str(from_version) if previous_files else "",
        "files": current,
        "removed": removed,
        "created": changed,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for name in changed:
            if name == INSTALL_MARKER:
                _write_bytes(bundle, name, marker)
            else:
                _write_file(bundle, name, dist / name)
        _write_bytes(
            bundle,
            MANIFEST_NAME,
            (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode("utf-8"),
        )

    return {
        "version": str(version),
        "from_version": str(from_version) if previous_files else "",
        "output": str(output),
        "size": output.stat().st_size,
        "files_total": files_total,
        "files_shipped": len(changed),
        "files_removed": len(removed),
        "full_payload": not previous_files,
    }


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", required=True, help="installed build folder")
    parser.add_argument("--version", required=True, help="version being built")
    parser.add_argument("--output", required=True, help="update zip to write")
    parser.add_argument(
        "--previous",
        default="",
        help="update package of the previous release (optional)",
    )
    parser.add_argument(
        "--from-version",
        default="",
        help="version this package upgrades from (recorded in update.json)",
    )
    parser.add_argument("--json", action="store_true", help="print a JSON summary")
    args = parser.parse_args(argv)

    summary = build_package(
        Path(args.dist),
        args.version,
        Path(args.output),
        Path(args.previous) if args.previous else None,
        from_version=args.from_version,
    )
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(
            "update package: {files_shipped} of {files_total} file(s), "
            "{files_removed} removed, {size} bytes -> {output}".format(**summary)
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
