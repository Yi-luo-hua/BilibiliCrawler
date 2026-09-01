import hashlib
import tempfile
import unittest
import subprocess
from pathlib import Path

from scripts.check_package_release import (
    ReleaseCheckError,
    artifact_records,
    load_identity,
    verify_release_files,
    verify_ancestor,
    verify_repository_payload,
    write_release_files,
)


class PackageReleaseTests(unittest.TestCase):
    def test_identity_is_derived_from_public_metadata_and_cargo(self):
        root = Path(__file__).resolve().parents[1]
        identity = load_identity(root)
        self.assertEqual("bilibili-crawler", identity["name"])
        self.assertRegex(identity["version"], r"^\d+\.\d+\.\d+")
        self.assertEqual(
            f"bilibili_crawler-{identity['version']}-py3-none-any.whl", identity["wheel"]
        )

    def test_repository_requires_both_exact_artifact_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "package.whl"
            sdist = Path(directory) / "package.tar.gz"
            wheel.write_bytes(b"wheel")
            sdist.write_bytes(b"sdist")
            records = artifact_records((wheel, sdist))
            payload = {"urls": [
                {"filename": path.name, "digests": {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}
                for path in (wheel, sdist)
            ]}
            verify_repository_payload(payload, records)
            payload["urls"][1]["digests"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ReleaseCheckError, "do not match"):
                verify_repository_payload(payload, records)

    def test_release_evidence_binds_artifacts_and_source_commit(self):
        root = Path(__file__).resolve().parents[1]
        identity = load_identity(root)
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            wheel = directory / identity["wheel"]
            sdist = directory / identity["sdist"]
            manifest = directory / "manifest.json"
            checksums = directory / "SHA256SUMS"
            wheel.write_bytes(b"wheel")
            sdist.write_bytes(b"sdist")
            records = artifact_records((wheel, sdist))
            write_release_files(root, identity, records, manifest, checksums)
            verify_release_files(root, identity, records, manifest, checksums)
            document = manifest.read_text(encoding="utf-8").replace(
                subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
                "0" * 40,
            )
            manifest.write_text(document, encoding="utf-8")
            with self.assertRaisesRegex(ReleaseCheckError, "manifest does not match"):
                verify_release_files(root, identity, records, manifest, checksums)

    def test_release_commit_must_be_reachable_from_trusted_ref(self):
        root = Path(__file__).resolve().parents[1]
        verify_ancestor(root, "HEAD")
        with self.assertRaisesRegex(ReleaseCheckError, "not reachable"):
            verify_ancestor(root, "HEAD~999999")


if __name__ == "__main__":
    unittest.main()
