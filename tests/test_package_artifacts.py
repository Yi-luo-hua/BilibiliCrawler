"""Adversarial release-gate cases; synthetic archives never contain user data."""
import base64
import csv
import hashlib
import io
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.check_package_artifacts import (
    AuditError, EGG_FILES, PACKAGE_FILES, SOURCE_FILES, audit, read_archive,
)

VERSION = "3.3.0"
ROOT = "bilibili_crawler-" + VERSION
DIST = ROOT + ".dist-info/"
METADATA = b'''Metadata-Version: 2.4
Name: bilibili-crawler
Version: 3.3.0
Requires-Python: >=3.10
Requires-Dist: requests>=2.31.0
Requires-Dist: Pillow>=10.0
Requires-Dist: mcp==2.1.0; extra == "mcp"
Requires-Dist: jieba>=0.42.1; extra == "analysis"
Requires-Dist: wordcloud>=1.9.3; extra == "analysis"
Requires-Dist: qrcode>=7.4; extra == "desktop"
Requires-Dist: jieba>=0.42.1; extra == "desktop"
Requires-Dist: wordcloud>=1.9.3; extra == "desktop"
Provides-Extra: mcp
Provides-Extra: analysis
Provides-Extra: desktop

Synthetic readme https://example.invalid
'''


class PackageArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.wheel = self.root / (ROOT + "-py3-none-any.whl")
        self.sdist = self.root / (ROOT + ".tar.gz")
        self.runtime = {name: b"# synthetic runtime\n" for name in PACKAGE_FILES}

    def archives(self, *, wheel_extra=None, source_extra=None, metadata=METADATA, payload=None, bad_record=False):
        runtime = dict(self.runtime)
        if payload:
            runtime["bilibili_crawler/agent.py"] = payload
        wheel_files = {**runtime, DIST + "METADATA": metadata, DIST + "WHEEL": b"Wheel-Version: 1.0\n",
                       DIST + "licenses/LICENSE": b"MIT", DIST + "top_level.txt": b"bilibili_crawler\n",
                       DIST + "entry_points.txt": b"[console_scripts]\nbilibili-crawler = bilibili_crawler.agent:main\nbilibili-crawler-mcp = bilibili_crawler.agent:mcp_main\n"}
        wheel_files.update(wheel_extra or {})
        record = io.StringIO(newline="")
        writer = csv.writer(record)
        for name, body in wheel_files.items():
            digest = base64.urlsafe_b64encode(hashlib.sha256(body).digest()).rstrip(b"=").decode()
            writer.writerow([name, "sha256=" + ("invalid" if bad_record else digest), len(body)])
        writer.writerow([DIST + "RECORD", "", ""])
        wheel_files[DIST + "RECORD"] = record.getvalue().encode()
        with zipfile.ZipFile(self.wheel, "w") as archive:
            for name, body in wheel_files.items():
                archive.writestr(name, body)
        source_files = {name: b"" for name in SOURCE_FILES}
        source_files.update({"bilibili_crawler.egg-info/" + name: b"" for name in EGG_FILES})
        source_files.update(runtime)
        source_files.update({"PKG-INFO": metadata, "LICENSE": b"MIT"})
        source_files.update(source_extra or {})
        with tarfile.open(self.sdist, "w:gz") as archive:
            for name, body in source_files.items():
                item = tarfile.TarInfo(ROOT + "/" + name)
                item.size = len(body)
                archive.addfile(item, io.BytesIO(body))

    def test_valid_inventory_and_public_path_examples(self):
        self.archives(payload=b"# https://api.bilibili.com and C:/Windows/Fonts/simhei.ttf and C:\\path\\python.exe\n")
        result = audit(self.wheel, self.sdist, VERSION)
        self.assertTrue(result["ok"])
        self.assertEqual(result["runtime_files"], 30)
        self.assertEqual(result["artifacts"][0]["sha256"], hashlib.sha256(self.wheel.read_bytes()).hexdigest())

    def test_rejects_sensitive_or_unplanned_members_in_both_artifacts(self):
        for name in ("credentials.json", "cookies.txt", "analysis-runs/run/manifest.json",
                     "tests/fixtures/comments.json", "src/service/agent_service.py",
                     "bilibili_crawler/__pycache__/agent.pyc", "bilibili_crawler/new_unreviewed.py"):
            for target in ("wheel_extra", "source_extra"):
                with self.subTest(name=name, target=target):
                    self.archives(**{target: {name: b"unwanted"}})
                    with self.assertRaisesRegex(AuditError, "unexpected or missing"):
                        audit(self.wheel, self.sdist, VERSION)

    def test_rejects_credentials_and_machine_paths_without_echoing_values(self):
        for content in ("sk-synthetic-credential-1234567890", "SESSDATA='abcdef0123456789'",
                        "bili_jct = 'abcdef0123456789'", "-----BEGIN PRIVATE KEY-----",
                        'cookie="SESSDATA=abcdef0123456789; bili_jct=abcdef0123456789"',
                        "E:/workspace/private/project", "C:\\Users\\private\\project", "/home/private/project"):
            with self.subTest(kind=content.split(":")[0][:8]):
                self.archives(payload=content.encode())
                with self.assertRaises(AuditError) as error:
                    audit(self.wheel, self.sdist, VERSION)
                self.assertNotIn(content, str(error.exception))

    def test_missing_core_dependency_and_wrong_version_fail(self):
        for metadata in (METADATA.replace(b"Requires-Dist: Pillow>=10.0\n", b""),
                         METADATA.replace(b'Requires-Dist: jieba>=0.42.1; extra == "analysis"\n', b""),
                         METADATA.replace(b"Requires-Python:", b"Requires-Dist: jieba>=0.42.1\nRequires-Python:"),
                         METADATA.replace(b"Version: 3.3.0", b"Version: 3.3.1")):
            self.archives(metadata=metadata)
            with self.assertRaises(AuditError):
                audit(self.wheel, self.sdist, VERSION)

    def test_record_tampering_and_runtime_drift_fail(self):
        self.archives(bad_record=True)
        with self.assertRaisesRegex(AuditError, "RECORD mismatch"):
            audit(self.wheel, self.sdist, VERSION)
        self.archives(source_extra={"bilibili_crawler/agent.py": b"different runtime"})
        with self.assertRaisesRegex(AuditError, "content mismatch"):
            audit(self.wheel, self.sdist, VERSION)

    def test_archive_traversal_duplicates_links_and_limits_fail(self):
        for name in ("../escape", "/absolute", "C:/absolute", "a/../escape", "a\\escape"):
            with self.subTest(name=name):
                with zipfile.ZipFile(self.wheel, "w") as archive:
                    item = zipfile.ZipInfo("placeholder")
                    item.filename = name  # retain raw Windows separators in the fixture
                    archive.writestr(item, b"content")
                with self.assertRaisesRegex(AuditError, "unsafe"):
                    read_archive(self.wheel)
        with zipfile.ZipFile(self.wheel, "w") as archive:
            archive.writestr("Case", b"one")
            archive.writestr("case", b"two")
        with self.assertRaisesRegex(AuditError, "duplicate"):
            read_archive(self.wheel)
        for kind in (0o010000, 0o020000, 0o060000, 0o120000):
            with zipfile.ZipFile(self.wheel, "w") as archive:
                item = zipfile.ZipInfo("special")
                item.external_attr = (kind | 0o600) << 16
                archive.writestr(item, b"content")
            with self.assertRaisesRegex(AuditError, "non-regular"):
                read_archive(self.wheel)
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
            with tarfile.open(self.sdist, "w:gz") as archive:
                item = tarfile.TarInfo("linked")
                item.type, item.linkname = kind, "../secret"
                archive.addfile(item)
            with self.assertRaisesRegex(AuditError, "non-regular"):
                read_archive(self.sdist)
        with zipfile.ZipFile(self.wheel, "w") as archive:
            archive.writestr("large", b"x" * (2 * 1024 * 1024 + 1))
        with self.assertRaisesRegex(AuditError, "size limit"):
            read_archive(self.wheel)
