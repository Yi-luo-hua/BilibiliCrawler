"""Fail-closed identity and publication checks for Python release artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python 3.10
    import tomli as tomllib


class ReleaseCheckError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseCheckError(message)


def load_identity(root: Path) -> dict[str, str]:
    with (root / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]
    with (root / "desktop" / "src-tauri" / "Cargo.toml").open("rb") as stream:
        cargo = tomllib.load(stream)["package"]
    name = project["name"]
    version = cargo["version"]
    require(name == "bilibili-crawler", "unexpected public distribution name")
    require(project.get("dynamic") == ["version"], "package version must remain Cargo-derived")
    require(re.fullmatch(r"\d+\.\d+\.\d+(?:[a-zA-Z0-9.]+)?", version) is not None,
            "invalid Cargo package version")
    stem = name.replace("-", "_")
    return {
        "name": name,
        "version": version,
        "wheel": f"{stem}-{version}-py3-none-any.whl",
        "sdist": f"{stem}-{version}.tar.gz",
        "source_commit": git("rev-parse", "HEAD", cwd=root),
    }


def git(*args: str, cwd: Path) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def verify_tag(root: Path, tag: str, version: str, require_head: bool) -> None:
    require(tag == f"v{version}", "tag must exactly match the Cargo/package version")
    tag_ref = f"refs/tags/{tag}"
    require(git("cat-file", "-t", tag_ref, cwd=root) == "tag", "release tag must be annotated")
    if require_head:
        require(git("rev-parse", f"{tag_ref}^{{}}", cwd=root) == git("rev-parse", "HEAD", cwd=root),
                "release tag does not point at the checked-out commit")


def verify_ancestor(root: Path, ref: str) -> None:
    result = subprocess.run(["git", "merge-base", "--is-ancestor", "HEAD", ref], cwd=root,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    require(result.returncode == 0, "release commit is not reachable from the required branch")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_records(paths: tuple[Path, Path]) -> list[dict[str, object]]:
    records = []
    for path in paths:
        path = path.resolve(strict=True)
        records.append({"name": path.name, "size": path.stat().st_size, "sha256": sha256(path)})
    return records


def verify_repository_payload(payload: dict, records: list[dict[str, object]]) -> None:
    urls = payload.get("urls")
    require(isinstance(urls, list), "package repository response has no artifact list")
    remote: dict[str, str] = {}
    for item in urls:
        if not isinstance(item, dict) or not isinstance(item.get("filename"), str):
            continue
        digest = item.get("digests", {}).get("sha256") if isinstance(item.get("digests"), dict) else None
        require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
                "package repository artifact has no valid SHA-256")
        require(item["filename"] not in remote, "package repository returned duplicate artifact names")
        remote[item["filename"]] = digest
    expected = {record["name"]: record["sha256"] for record in records}
    require(expected.items() <= remote.items(), "package repository artifacts do not match local SHA-256")


def verify_repository(repository: str, name: str, version: str,
                      records: list[dict[str, object]]) -> None:
    url = f"{repository.rstrip('/')}/{name}/{version}/json"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        require(response.status == 200, "package repository lookup failed")
        payload = json.load(response)
    require(isinstance(payload, dict), "package repository returned invalid JSON")
    verify_repository_payload(payload, records)


def write_release_files(root: Path, identity: dict[str, str], records: list[dict[str, object]],
                        manifest: Path | None, checksums: Path | None) -> None:
    if manifest:
        document = {
            "schema": 1,
            "distribution": identity["name"],
            "version": identity["version"],
            "source_commit": identity["source_commit"],
            "artifacts": records,
        }
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if checksums:
        checksums.parent.mkdir(parents=True, exist_ok=True)
        checksums.write_text("".join(f"{record['sha256']}  {record['name']}\n" for record in records),
                             encoding="ascii")


def verify_release_files(root: Path, identity: dict[str, str], records: list[dict[str, object]],
                         manifest: Path | None, checksums: Path | None) -> None:
    require(manifest is not None and checksums is not None,
            "release evidence verification requires --manifest and --checksums")
    document = json.loads(manifest.read_text(encoding="utf-8"))
    expected = {
        "schema": 1,
        "distribution": identity["name"],
        "version": identity["version"],
        "source_commit": identity["source_commit"],
        "artifacts": records,
    }
    require(document == expected, "release manifest does not match the tagged artifacts")
    expected_checksums = "".join(f"{record['sha256']}  {record['name']}\n" for record in records)
    require(checksums.read_text(encoding="ascii") == expected_checksums,
            "release checksum file does not match the tagged artifacts")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--tag")
    parser.add_argument("--require-head-tag", action="store_true")
    parser.add_argument("--require-ancestor-of",
                        help="require HEAD to be reachable from this trusted branch, such as origin/main")
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--sdist", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--checksums", type=Path)
    parser.add_argument("--verify-release-files", action="store_true",
                        help="verify manifest/checksums instead of writing them")
    parser.add_argument("--verify-repository",
                        help="JSON API base, for example https://test.pypi.org/pypi")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    identity = load_identity(root)
    require(not args.require_head_tag or args.tag, "--require-head-tag requires --tag")
    if args.tag:
        verify_tag(root, args.tag, identity["version"], args.require_head_tag)
    if args.require_ancestor_of:
        verify_ancestor(root, args.require_ancestor_of)
    require(bool(args.wheel) == bool(args.sdist), "--wheel and --sdist must be provided together")
    records = artifact_records((args.wheel, args.sdist)) if args.wheel else []
    if records:
        require({record["name"] for record in records} == {identity["wheel"], identity["sdist"]},
                "artifact filenames do not match the distribution identity")
        if args.verify_release_files:
            verify_release_files(root, identity, records, args.manifest, args.checksums)
        else:
            write_release_files(root, identity, records, args.manifest, args.checksums)
    else:
        require(not any((args.manifest, args.checksums, args.verify_repository,
                         args.verify_release_files)),
                "artifact operation requires --wheel and --sdist")
    if args.verify_repository:
        verify_repository(args.verify_repository, identity["name"], identity["version"], records)
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as stream:
            for key in ("name", "version", "wheel", "sdist", "source_commit"):
                stream.write(f"{key}={identity[key]}\n")
    print(json.dumps({**identity, "artifacts": records}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ReleaseCheckError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(f"release check failed: {error}", file=sys.stderr)
        raise SystemExit(1)
