"""Record the installer payload and detect files a new build stops shipping.

Residue on upgrade is exactly the set of paths an older installer shipped and a
newer one does not: Tauri's uninstall section is expanded at build time, so a
new uninstaller cannot remove what it never packaged, and the install section
overwrites in place. Between v3.3.0 and v3.4.0 three api-ms-win forwarder DLLs
were stranded this way *without any declared change* - no lockfile edit, same
pinned PyInstaller - because collection depends on the build machine's state.

That is why this compares real payloads rather than declarations: nothing in
the dependency locks can predict it.

Usage:
    python scripts/check_installer_payload.py --tree <dir> --version X.Y.Z \
        --out payload-manifest.json [--baseline previous-manifest.json]

The manifest carries no timestamp, so two builds of identical content produce
identical manifests and can be compared byte for byte.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

SCHEMA = 1


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(tree: Path, version: str) -> dict:
    if not tree.is_dir():
        raise SystemExit(f"payload tree not found: {tree}")
    files = []
    for path in sorted(tree.rglob("*")):
        if not path.is_file():
            continue
        # Relative, forward-slashed and sorted, so the manifest is stable
        # across machines and directly comparable between releases.
        relative = path.relative_to(tree).as_posix()
        files.append({"path": relative, "size": path.stat().st_size, "sha256": sha256(path)})
    return {"schema": SCHEMA, "version": version, "root": tree.name, "files": files}


def compare(baseline: dict, current: dict) -> tuple[list[str], list[str], list[str]]:
    old = {item["path"]: item for item in baseline.get("files", [])}
    new = {item["path"]: item for item in current.get("files", [])}
    removed = sorted(set(old) - set(new))
    added = sorted(set(new) - set(old))
    changed = sorted(p for p in set(old) & set(new) if old[p]["sha256"] != new[p]["sha256"])
    return removed, added, changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", required=True, type=Path,
                        help="packaged resource tree, e.g. desktop/src-tauri/resources/backend")
    parser.add_argument("--version", required=True, help="release version this payload belongs to")
    parser.add_argument("--out", type=Path, help="write the manifest here")
    parser.add_argument("--baseline", type=Path, help="previous release manifest to compare against")
    parser.add_argument("--allow-removed", action="store_true",
                        help="report removed paths without failing; use when the cleanup hook is known to handle them")
    args = parser.parse_args()

    manifest = build_manifest(args.tree, args.version)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"payload manifest: {args.out} ({len(manifest['files'])} files)")
    else:
        print(f"payload files: {len(manifest['files'])}")

    if not args.baseline:
        return 0

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    removed, added, changed = compare(baseline, manifest)
    print(f"baseline {baseline.get('version', '?')} -> {manifest['version']}: "
          f"{len(removed)} removed, {len(added)} added, {len(changed)} changed")
    for path in added:
        print(f"  + {path}")
    for path in removed:
        print(f"  - {path}")
    if not removed:
        return 0
    # Removed paths are the residue set: an in-place upgrade leaves every one of
    # them behind unless the installer hook clears them.
    print(f"\n{len(removed)} path(s) will be stranded by an in-place upgrade.")
    if args.allow_removed:
        print("Accepted: the PREINSTALL cleanup hook removes them on upgrade.")
        return 0
    print("Confirm the cleanup hook covers them, then re-run with --allow-removed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
