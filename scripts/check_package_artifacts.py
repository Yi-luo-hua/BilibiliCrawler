"""Audit local release candidates without importing code or extracting archives."""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import re
import tarfile
import zipfile
from configparser import ConfigParser
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

# Deliberate inventory: adding runtime files requires updating this review gate.
PACKAGE_FILES = {"bilibili_crawler/" + name for name in """
__init__.py __main__.py agent.py mcp_server.py sidecar.py
api/__init__.py api/bilibili_api.py config/__init__.py config/config.py
crawler/__init__.py crawler/comment_crawler.py crawler/dynamic_crawler.py
exporter/__init__.py exporter/csv_exporter.py
processor/__init__.py processor/analysis_processor.py processor/data_processor.py processor/provider_errors.py
resources/__init__.py resources/stopwords.txt
service/__init__.py service/agent_service.py service/credentials.py service/diagnostics.py
service/models.py service/paths.py service/recovery.py service/run_store.py
utils/__init__.py utils/helpers.py
""".split()}
EGG_FILES = {"PKG-INFO", "SOURCES.txt", "dependency_links.txt", "entry_points.txt", "requires.txt", "top_level.txt"}
SOURCE_FILES = {"LICENSE", "README.md", "MANIFEST.in", "pyproject.toml", "setup.py", "setup.cfg",
                "PKG-INFO", "desktop/src-tauri/Cargo.toml"}
SECRET = re.compile(r"sk-[A-Za-z0-9_-]{16,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
                    r"(?i:SESSDATA|bili_jct)[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9%_-]{8,}")
# Generic font probes and the README's explicit C:\path placeholder are allowed.
MACHINE_PATH = re.compile(r"(?<![\w])[A-Za-z]:[\\/](?!(?:Windows[\\/]Fonts[\\/]|path[\\/]))|"
                          r"/(?:Users|home)/[^\s\"']+")
MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 10 * MAX_FILE


class AuditError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise AuditError(message)


def read_archive(path):
    """Reject links, duplicate names and traversal before reading bounded payloads."""
    result, seen, total = {}, set(), 0

    def validate(name, size):
        nonlocal total
        parts = PurePosixPath(name).parts
        require(name and not name.startswith("/") and "\\" not in name and ":" not in name
                and all(part not in {".", ".."} for part in name.rstrip("/").split("/"))
                and ".." not in parts, "unsafe archive member name")
        require(name.casefold().rstrip("/") not in seen, "duplicate archive member")
        seen.add(name.casefold().rstrip("/"))
        require(len(seen) <= 500, "too many archive members")
        total += size
        require(0 <= size <= MAX_FILE and total <= MAX_TOTAL, "archive size limit exceeded")

    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            for item in archive.infolist():
                require(item.orig_filename == item.filename, "unsafe normalized archive member name")
                validate(item.filename, item.file_size)
                kind = (item.external_attr >> 16) & 0o170000
                require(kind in {0, 0o100000, 0o040000}, "non-regular archive member")
                require(not kind or item.is_dir() == (kind == 0o040000), "archive member type mismatch")
                if not item.is_dir():
                    result[item.filename] = archive.read(item)
    else:
        with tarfile.open(path, "r:gz") as archive:
            for item in archive:
                validate(item.name, item.size)
                require(item.isfile() or item.isdir(), "non-regular archive member")
                if item.isfile():
                    result[item.name] = archive.extractfile(item).read(MAX_FILE + 1)
    require(result, "empty archive")
    return result


def check_metadata(data, version):
    metadata = BytesParser().parsebytes(data)
    require(metadata["Name"] == "bilibili-crawler" and metadata["Version"] == version, "distribution identity mismatch")
    require(metadata["Requires-Python"] == ">=3.10", "Python requirement mismatch")
    requirements = metadata.get_all("Requires-Dist", [])
    normalized = {item.replace(" ", "").replace("'", '"').lower() for item in requirements}
    expected = {"requests>=2.31.0", "pillow>=10.0", 'mcp==2.1.0;extra=="mcp"',
                'jieba>=0.42.1;extra=="analysis"', 'wordcloud>=1.9.3;extra=="analysis"',
                'qrcode>=7.4;extra=="desktop"', 'jieba>=0.42.1;extra=="desktop"',
                'wordcloud>=1.9.3;extra=="desktop"'}
    require(normalized == expected and len(requirements) == len(expected), "dependency or extra mismatch")
    require(set(metadata.get_all("Provides-Extra", [])) == {"mcp", "analysis", "desktop"}, "extras mismatch")
    return requirements


def audit(wheel, sdist, version, forbidden_paths=()):
    require(re.fullmatch(r"\d+\.\d+\.\d+(?:[a-zA-Z0-9.]+)?", version), "invalid expected version")
    wheel_files, source_files = read_archive(wheel), read_archive(sdist)
    prefix = f"bilibili_crawler-{version}"
    require(all(name.startswith(prefix + "/") for name in source_files), "sdist root mismatch")
    source_files = {name[len(prefix) + 1:]: value for name, value in source_files.items()}
    dist = prefix + ".dist-info/"
    expected_wheel = PACKAGE_FILES | {dist + name for name in
        {"METADATA", "WHEEL", "entry_points.txt", "top_level.txt", "RECORD", "licenses/LICENSE"}}
    expected_source = PACKAGE_FILES | SOURCE_FILES | {"bilibili_crawler.egg-info/" + name for name in EGG_FILES}
    require(set(wheel_files) == expected_wheel, "unexpected or missing wheel files")
    require(set(source_files) == expected_source, "unexpected or missing sdist files")
    for name in PACKAGE_FILES:
        require(wheel_files[name] == source_files[name], "wheel/sdist runtime content mismatch: " + name)
    requirements = check_metadata(wheel_files[dist + "METADATA"], version)
    require(check_metadata(source_files["PKG-INFO"], version) == requirements, "wheel/sdist dependencies differ")
    require(wheel_files[dist + "licenses/LICENSE"] == source_files["LICENSE"], "license mismatch")
    for inventory in (wheel_files, source_files):
        for name, payload in inventory.items():
            text = payload.decode("utf-8")
            require(not SECRET.search(text), "possible credential in " + name)
            require(not MACHINE_PATH.search(text), "machine absolute path in " + name)
            for path in forbidden_paths:
                for variant in {str(path), str(path).replace("\\", "/"), str(path).replace("\\", "\\\\")}:
                    require(variant.casefold() not in text.casefold(), "local path in " + name)
    entries = ConfigParser()
    entries.read_string(wheel_files[dist + "entry_points.txt"].decode())
    require(dict(entries["console_scripts"]) == {
        "bilibili-crawler": "bilibili_crawler.agent:main",
        "bilibili-crawler-mcp": "bilibili_crawler.agent:mcp_main"}, "console entries mismatch")
    record = list(csv.reader(io.StringIO(wheel_files[dist + "RECORD"].decode())))
    require(len(record) == len(wheel_files) and {row[0] for row in record} == set(wheel_files), "RECORD inventory mismatch")
    for name, digest, size in record:
        if name == dist + "RECORD":
            require(not digest and not size, "RECORD self hash must be empty")
        else:
            actual = base64.urlsafe_b64encode(hashlib.sha256(wheel_files[name]).digest()).rstrip(b"=").decode()
            require(digest == "sha256=" + actual and size == str(len(wheel_files[name])), "RECORD mismatch: " + name)
    return {"ok": True, "version": version, "runtime_files": len(PACKAGE_FILES),
            "artifacts": [{"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                           "files": sorted(files)} for path, files in ((wheel, wheel_files), (sdist, source_files))]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("sdist", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = audit(args.wheel, args.sdist, args.version, (Path(__file__).resolve().parents[1], Path.home()))
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        args.report.write_text(output + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "artifacts"}))


if __name__ == "__main__":
    main()
