"""Headless profile resolution must never silently choose another provider."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.service import credentials as creds
from src.service.models import ServiceError


KEY = "sk-profile-test-canary-12345"


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = self.root / "credentials.json"
        self.ui = self.root / "ui.json"
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.candidates = patch.object(creds, "credential_file_candidates", return_value=[self.profile])
        self.candidates.start()
        self.addCleanup(self.candidates.stop)

    def write(self, path, payload):
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def desktop(self):
        self.write(self.profile, {"api_key": KEY})
        self.write(self.ui, {"llm_base_url": "https://provider.example/v1/", "llm_model": "desktop-model"})

    def test_key_and_provider_are_loaded_from_one_desktop_profile(self):
        self.desktop()
        resolved = creds.resolve_llm_credentials()
        self.assertEqual(resolved.to_llm_config(), {
            "api_key": KEY, "base_url": "https://provider.example/v1", "model": "desktop-model",
        })

    def test_environment_overrides_each_field_without_losing_other_profile_fields(self):
        self.desktop()
        for variable, field, value in (
            (creds.ENV_API_KEY, "api_key", "sk-environment-canary-67890"),
            (creds.ENV_BASE_URL, "base_url", "https://override.example/v1"),
            (creds.ENV_MODEL, "model", "override-model"),
        ):
            with self.subTest(field=field), patch.dict(os.environ, {variable: value}):
                result = creds.resolve_llm_credentials().to_llm_config()
                expected = {"api_key": KEY, "base_url": "https://provider.example/v1", "model": "desktop-model"}
                expected[field] = value
                self.assertEqual(result, expected)

    def test_missing_ui_preserves_openai_defaults(self):
        from src.processor.analysis_processor import LLMAnalysisProcessor
        self.write(self.profile, {"api_key": KEY})
        result = creds.resolve_llm_credentials()
        self.assertEqual(result.base_url, LLMAnalysisProcessor.DEFAULT_BASE_URL)
        self.assertEqual(result.model, LLMAnalysisProcessor.DEFAULT_MODEL)

    def test_complete_environment_does_not_read_any_profile(self):
        with patch.dict(os.environ, {
            creds.ENV_API_KEY: KEY, creds.ENV_BASE_URL: "https://env.example/v1", creds.ENV_MODEL: "env-model",
        }), patch.object(Path, "read_text", side_effect=AssertionError("profile must not be read")):
            self.assertEqual(creds.resolve_llm_credentials().model, "env-model")

    def test_broken_ui_is_a_safe_configuration_error_not_default_fallback(self):
        self.write(self.profile, {"api_key": KEY})
        self.ui.write_text('{"secret": "' + KEY, encoding="utf-8")
        with self.assertRaises(ServiceError) as caught:
            creds.resolve_llm_credentials()
        self.assertEqual(caught.exception.code, "CONFIG_INVALID")
        self.assertIn("ui.json", str(caught.exception))
        self.assertNotIn(KEY, str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_bad_field_types_duplicate_keys_and_unsafe_urls_are_rejected(self):
        self.write(self.profile, {"api_key": KEY})
        cases = [
            '{"llm_model": ["bad"]}',
            '{"llm_model": "a", "llm_model": "b"}',
            '{"llm_base_url": "file:///tmp/endpoint"}',
            '{"llm_base_url": "https://user:pass@example.com/v1"}',
            '{"llm_base_url": "https://example.com/v1?api_key=hidden"}',
            '{"llm_base_url": "https://example.com:bad/v1"}',
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                self.ui.write_text(raw, encoding="utf-8")
                with self.assertRaises(ServiceError) as caught:
                    creds.resolve_llm_credentials()
                self.assertEqual(caught.exception.code, "CONFIG_INVALID")

    def test_conflicting_file_fields_require_explicit_override(self):
        self.desktop()
        self.write(self.profile, {"api_key": KEY, "base_url": "https://old.example/v1"})
        with self.assertRaises(ServiceError):
            creds.resolve_llm_credentials()
        with patch.dict(os.environ, {creds.ENV_BASE_URL: "https://override.example/v1"}):
            self.assertEqual(creds.resolve_llm_credentials().base_url, "https://override.example/v1")

    def test_profiles_from_different_installs_are_never_combined(self):
        self.write(self.profile, {"api_key": KEY})
        other = self.root / "other"
        other.mkdir()
        self.write(other / "credentials.json", {"api_key": "sk-other-install-123456"})
        self.write(other / "ui.json", {"llm_model": "wrong-install"})
        with patch.object(creds, "credential_file_candidates", return_value=[self.profile, other / "credentials.json"]):
            self.assertNotEqual(creds.resolve_llm_credentials().model, "wrong-install")

    def test_explicit_missing_or_empty_profile_does_not_fall_back(self):
        self.desktop()
        missing = self.root / "missing.json"
        self.candidates.stop()
        with patch.dict(os.environ, {creds.ENV_CREDENTIALS_FILE: str(missing)}):
            with self.assertRaises(ServiceError) as caught:
                creds.resolve_llm_credentials()
            self.assertEqual(caught.exception.code, "CONFIG_INVALID")
            self.write(missing, {})
            with self.assertRaises(ServiceError) as caught:
                creds.resolve_llm_credentials()
            self.assertEqual(caught.exception.code, "NO_CREDENTIALS")

    def test_environment_key_can_use_adjacent_ui_without_a_file_key(self):
        self.desktop()
        self.write(self.profile, {})
        with patch.dict(os.environ, {creds.ENV_API_KEY: KEY}):
            self.assertEqual(creds.resolve_llm_credentials().model, "desktop-model")

    def test_missing_key_remains_no_credentials(self):
        with self.assertRaises(ServiceError) as caught:
            creds.resolve_llm_credentials()
        self.assertEqual(caught.exception.code, "NO_CREDENTIALS")

    def test_invalid_overridden_field_is_ignored_but_other_fields_are_used(self):
        self.desktop()
        self.write(self.ui, {"llm_base_url": ["invalid"], "llm_model": "desktop-model"})
        with patch.dict(os.environ, {creds.ENV_BASE_URL: "https://explicit.example/v1"}):
            result = creds.resolve_llm_credentials()
        self.assertEqual(result.base_url, "https://explicit.example/v1")
        self.assertEqual(result.model, "desktop-model")

    def test_empty_environment_fields_fall_back_and_bom_is_supported(self):
        self.desktop()
        self.profile.write_text(json.dumps({"api_key": KEY}), encoding="utf-8-sig")
        with patch.dict(os.environ, {creds.ENV_BASE_URL: "  ", creds.ENV_MODEL: ""}):
            self.assertEqual(creds.resolve_llm_credentials().model, "desktop-model")

    def test_selected_broken_credentials_file_does_not_fall_back(self):
        self.profile.write_text('{"api_key":"' + KEY, encoding="utf-8")
        with self.assertRaises(ServiceError) as caught:
            creds.resolve_llm_credentials()
        self.assertEqual(caught.exception.code, "CONFIG_INVALID")
        self.assertNotIn(KEY, str(caught.exception))

    def test_missing_discovered_profile_is_skipped(self):
        self.desktop()
        with patch.object(creds, "credential_file_candidates", return_value=[self.root / "absent" / "credentials.json", self.profile]):
            resolved = creds.resolve_llm_profile()
        self.assertEqual(resolved.credentials.api_key, KEY)
        self.assertEqual(resolved.credentials.model, "desktop-model")
        self.assertEqual(resolved.field_sources["api_key"], "discovered_file")

    def test_repr_masks_credential_echo_before_string_escaping(self):
        key = "sk-quote-'and-backslash-\\-canary"
        resolved = creds.LLMCredentials(api_key=key, model=key, base_url="https://example.invalid/v1")
        self.assertNotIn("canary", repr(resolved))

    def test_whitespace_only_environment_fields_fall_back_to_profile(self):
        self.desktop()
        for whitespace in (" \t ", "\r\n", "\u3000"):
            with self.subTest(whitespace=repr(whitespace)), patch.dict(os.environ, {
                creds.ENV_API_KEY: whitespace, creds.ENV_BASE_URL: whitespace, creds.ENV_MODEL: whitespace,
            }):
                self.assertEqual(creds.resolve_llm_credentials().to_llm_config(), {
                    "api_key": KEY, "base_url": "https://provider.example/v1", "model": "desktop-model",
                })

    def test_control_characters_inside_nonempty_environment_fields_are_rejected(self):
        self.desktop()
        with patch.dict(os.environ, {creds.ENV_MODEL: "model\nwrong"}):
            with self.assertRaises(ServiceError) as caught:
                creds.resolve_llm_credentials()
        self.assertEqual(caught.exception.code, "CONFIG_INVALID")


if __name__ == "__main__":
    unittest.main()
