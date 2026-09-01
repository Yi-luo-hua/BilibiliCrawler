"""Namespace identity and installed-layout paths, without user data or network."""
import importlib
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from importlib.resources import files
from pathlib import Path
from unittest.mock import patch

from bilibili_crawler.processor.analysis_processor import LLMAnalysisProcessor
from bilibili_crawler.service import credentials, paths

ROOT = Path(__file__).resolve().parents[1]


class PackageBoundaryTests(unittest.TestCase):
    def test_legacy_imports_share_modules_and_state_with_canonical_namespace(self):
        modules = [(f"src.{folder}.{path.stem}", f"bilibili_crawler.{folder}.{path.stem}")
                   for folder in ("api", "crawler", "exporter", "processor", "service")
                   for path in (ROOT / "src" / folder).glob("*.py") if path.stem != "__init__"]
        modules += [("config.config", "bilibili_crawler.config.config"),
                    ("utils.helpers", "bilibili_crawler.utils.helpers"),
                    ("backend.agent", "bilibili_crawler.agent"),
                    ("backend.sidecar", "bilibili_crawler.sidecar")]
        if importlib.util.find_spec("mcp"):
            modules.append(("backend.mcp_server", "bilibili_crawler.mcp_server"))
        for legacy, canonical in modules:
            with self.subTest(legacy=legacy):
                self.assertIs(importlib.import_module(legacy), importlib.import_module(canonical))
        from src.service.credentials import _KNOWN_SECRETS
        self.assertIs(_KNOWN_SECRETS, credentials._KNOWN_SECRETS)

    def test_installed_layout_never_probes_site_packages_or_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(paths, "SOURCE_CHECKOUT", False), patch.object(paths, "ROOT", root / "site-packages"), \
                    patch.object(paths.sys, "platform", "win32"), patch.object(paths.Path, "home", return_value=root / "home"), \
                    patch.dict(os.environ, {"LOCALAPPDATA": str(root / "local")}, clear=True), \
                    patch.object(paths, "_is_writable", return_value=True) as probe:
                self.assertEqual(paths.agent_runs_root(), root / "local" / "BilibiliCrawler" / "analysis-runs")
                self.assertEqual(probe.call_args.args, (root / "local" / "BilibiliCrawler" / "analysis-runs",))
                self.assertEqual(paths.user_config_dir(), root / "local" / "BilibiliCrawler" / "config")
            self.assertEqual(list(root.iterdir()), [])

    def test_platform_paths_ignore_relative_environment_and_do_not_create_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with patch.object(paths.Path, "home", return_value=home), patch.object(paths.sys, "platform", "linux"), \
                    patch.dict(os.environ, {"XDG_DATA_HOME": "relative", "XDG_CONFIG_HOME": "relative",
                                            "XDG_CACHE_HOME": "relative"}, clear=True):
                self.assertEqual(paths.user_data_bases(), [home / ".local" / "share" / "bilibili-crawler"])
                self.assertEqual(paths.user_config_dir(), home / ".config" / "bilibili-crawler")
                self.assertEqual(paths.user_cache_dir(), home / ".cache" / "bilibili-crawler")
            with patch.object(paths.Path, "home", return_value=home), patch.object(paths.sys, "platform", "darwin"):
                self.assertEqual(paths.user_data_bases(), [home / "Library" / "Application Support" / "BilibiliCrawler"])
                self.assertEqual(paths.user_cache_dir(), home / "Library" / "Caches" / "BilibiliCrawler")
            self.assertEqual(list(home.iterdir()), [])

    def test_installed_profiles_skip_checkout_and_preserve_explicit_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(credentials, "SOURCE_CHECKOUT", False), \
                    patch.object(credentials, "_DEV_CREDENTIALS", root / "dev.json"), \
                    patch.object(credentials, "user_config_dir", return_value=root / "config"), \
                    patch.object(credentials, "_installed_credential_paths", return_value=[root / "desktop.json"]), \
                    patch.dict(os.environ, {}, clear=True):
                self.assertEqual(credentials.credential_file_candidates(), [root / "config" / "credentials.json", root / "desktop.json"])
                with patch.dict(os.environ, {credentials.ENV_CREDENTIALS_FILE: str(root / "explicit.json")}):
                    self.assertEqual(credentials.credential_file_candidates(), [root / "explicit.json"])
            self.assertEqual(list(root.iterdir()), [])

    def test_packaged_stopwords_are_read_through_resources(self):
        words = set(files("bilibili_crawler.resources").joinpath("stopwords.txt").read_text(encoding="utf-8").splitlines())
        self.assertEqual(len(words), 32)
        self.assertEqual(LLMAnalysisProcessor.STOP_WORDS, words)
        self.assertEqual(LLMAnalysisProcessor._clean_word_token("转发抽奖"), "")
        self.assertEqual(LLMAnalysisProcessor._clean_word_token("机器学习"), "机器学习")

    def test_matplotlib_cache_respects_explicit_override_without_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache"
            with patch.object(paths, "user_cache_dir", return_value=cache), patch.dict(os.environ, {}, clear=True):
                paths.configure_matplotlib_cache()
                self.assertEqual(os.environ["MPLCONFIGDIR"], str(cache / "matplotlib"))
                os.environ["MPLCONFIGDIR"] = "explicit-location"
                paths.configure_matplotlib_cache()
                self.assertEqual(os.environ["MPLCONFIGDIR"], "explicit-location")
            self.assertFalse(cache.exists())

    def test_module_entrypoints_work_outside_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            for module in ("backend.agent", "bilibili_crawler", "bilibili_crawler.agent"):
                result = subprocess.run([sys.executable, "-X", "utf8", "-m", module, "--help"], cwd=directory,
                                        env={**os.environ, "PYTHONPATH": str(ROOT)}, capture_output=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(b"bilibili-crawler", result.stdout)
