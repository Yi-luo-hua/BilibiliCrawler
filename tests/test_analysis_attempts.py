"""A cancelled retry must not invalidate an already committed report."""
import hashlib
import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import patch

from test_agent_service import AgentServiceTestCase, FakeAnalysisProcessor, WordCloudProcessor, fake_credentials
from src.processor.analysis_processor import AnalysisCancelled, AnalysisError
from src.service.agent_service import AgentService
from src.service.models import RunStatus, ServiceError
from src.service.run_store import RunStore, new_run_id


class AttemptTests(AgentServiceTestCase):
    def completed_run(self):
        service = self.make_service(processor=FakeAnalysisProcessor(summary="old report"))
        final = self.run_to_completion(service, service.start_crawl_and_analyze("BV1xx411c7mD"))
        self.assertEqual(final.status, RunStatus.COMPLETED)
        return service, final

    def test_cancelled_retry_preserves_effective_run_and_previous_artifacts(self):
        service, first = self.completed_run()
        original = {key: Path(value).read_bytes() for key, value in first.artifacts.items()}
        entered, release = threading.Event(), threading.Event()
        self._releases.append(release)

        class CancelledProcessor:
            def analyze(self, *args, cancel_event=None, **kwargs):
                entered.set()
                release.wait(5)
                raise AnalysisCancelled("cancel retry")

        service._analysis_processor = CancelledProcessor()
        retry = service.start_analyze(first.run_id)
        self.assertTrue(entered.wait(5))
        service.stop(retry.task_id)
        release.set()
        final = self.run_to_completion(service, retry)
        self.assertEqual(final.status, RunStatus.CANCELLED)
        manifest = self.store.read_manifest(first.run_id)
        self.assertEqual(manifest["status"], RunStatus.COMPLETED)
        self.assertEqual(manifest["current_analysis"]["attempt_id"], first.task_id)
        self.assertEqual(manifest["analysis_attempts"][-1]["status"], RunStatus.CANCELLED)
        self.assertEqual(service.get_status(task_id=retry.task_id).status, RunStatus.CANCELLED)
        self.assertEqual(service.get_status(run_id=first.run_id).status, RunStatus.COMPLETED)
        restarted = AgentService(store=self.store, api=object(), credentials_resolver=fake_credentials)
        self.assertEqual(restarted.get_status(run_id=first.run_id).status, RunStatus.COMPLETED)
        for key, data in original.items():
            self.assertEqual(Path(self.store.artifacts(first.run_id)[key]).read_bytes(), data)

    def test_failed_retry_is_recorded_without_replacing_the_committed_result(self):
        service, first = self.completed_run()
        service._analysis_processor = FakeAnalysisProcessor(fail=AnalysisError("wrong model"))
        final = self.run_to_completion(service, service.start_analyze(first.run_id))
        self.assertEqual(final.status, RunStatus.FAILED)
        manifest = self.store.read_manifest(first.run_id)
        self.assertEqual(manifest["status"], RunStatus.COMPLETED)
        self.assertIsNone(manifest["error"])
        self.assertEqual(manifest["analysis_attempts"][-1]["error"], "wrong model")
        self.assertEqual(self.store.load_analysis(first.run_id)["summary"], "old report")

    def test_cancel_after_result_retains_paid_output_without_promoting_it(self):
        service, first = self.completed_run()

        class CancelOnReturn(FakeAnalysisProcessor):
            def analyze(self, *args, cancel_event=None, **kwargs):
                result = super().analyze(*args, cancel_event=cancel_event, **kwargs)
                cancel_event.set()
                return result

        service._analysis_processor = CancelOnReturn(summary="cancelled new report")
        final = self.run_to_completion(service, service.start_analyze(first.run_id))
        self.assertEqual(final.status, RunStatus.CANCELLED)
        manifest = self.store.read_manifest(first.run_id)
        attempt = manifest["analysis_attempts"][-1]
        saved = self.store.run_dir(first.run_id) / attempt["artifacts"]["analysis_json"]
        self.assertEqual(json.loads(saved.read_text(encoding="utf-8"))["summary"], "cancelled new report")
        self.assertEqual(self.store.load_analysis(first.run_id)["summary"], "old report")
        self.assertEqual(manifest["current_analysis"]["attempt_id"], first.task_id)

    def test_successful_retry_atomically_changes_current_pointer_without_rewriting_comments(self):
        service, first = self.completed_run()
        comment_path = Path(first.artifacts["comments_json"])
        before = hashlib.sha256(comment_path.read_bytes()).hexdigest()
        old_result = Path(first.artifacts["analysis_json"]).read_bytes()
        service._analysis_processor = FakeAnalysisProcessor(summary="new report")
        second = self.run_to_completion(service, service.start_analyze(first.run_id))
        manifest = self.store.read_manifest(first.run_id)
        self.assertEqual(manifest["schema_version"], 2)
        self.assertEqual(manifest["current_analysis"]["attempt_id"], second.task_id)
        self.assertEqual(len(manifest["analysis_attempts"]), 2)
        for attempt in manifest["analysis_attempts"]:
            self.assertTrue(attempt["started_at"])
            self.assertTrue(attempt["finished_at"])
            self.assertEqual(attempt["status"], RunStatus.COMPLETED)
            self.assertFalse(Path(attempt["artifacts"]["analysis_json"]).is_absolute())
        self.assertNotEqual(second.artifacts["analysis_json"], first.artifacts["analysis_json"])
        self.assertEqual(Path(first.artifacts["analysis_json"]).read_bytes(), old_result)
        self.assertEqual(self.store.load_analysis(first.run_id)["summary"], "new report")
        self.assertEqual(hashlib.sha256(comment_path.read_bytes()).hexdigest(), before)

    def test_legacy_completed_report_is_imported_lazily_and_survives_failed_retry(self):
        run_id = self.seed_run()
        self.store.save_analysis(run_id, {"summary": "legacy report", "report_markdown": "# legacy"})
        old_manifest = self.store.read_manifest(run_id)
        self.assertNotIn("current_analysis", old_manifest)
        original_json = (self.store.run_dir(run_id) / "analysis.json").read_bytes()
        service = self.make_service(processor=FakeAnalysisProcessor(fail=AnalysisError("retry failed")))
        final = self.run_to_completion(service, service.start_analyze(run_id))
        self.assertEqual(final.status, RunStatus.FAILED)
        manifest = self.store.read_manifest(run_id)
        self.assertTrue(manifest["current_analysis"]["attempt_id"].startswith("legacy-"))
        self.assertEqual(manifest["status"], RunStatus.COMPLETED)
        self.assertEqual(self.store.load_analysis(run_id)["summary"], "legacy report")
        self.assertEqual((self.store.run_dir(run_id) / "analysis.json").read_bytes(), original_json)

    def test_legacy_cancelled_paid_result_is_not_promoted_to_success(self):
        run_id = self.seed_run()
        self.store.save_analysis(run_id, {"summary": "cancelled legacy", "report_markdown": "# kept"})
        self.store.update_manifest(run_id, status=RunStatus.CANCELLED)
        service = self.make_service(processor=FakeAnalysisProcessor(fail=AnalysisError("bad retry")))
        final = self.run_to_completion(service, service.start_analyze(run_id))
        self.assertEqual(final.status, RunStatus.FAILED)
        manifest = self.store.read_manifest(run_id)
        self.assertIsNone(manifest["current_analysis"])
        self.assertEqual(manifest["status"], RunStatus.FAILED)

    def test_original_save_analysis_call_remains_visible_after_schema_upgrade(self):
        _, first = self.completed_run()
        saved = self.store.save_analysis(first.run_id, {"summary": "direct new value", "report_markdown": "# direct"})
        self.assertEqual(self.store.load_analysis(first.run_id)["summary"], "direct new value")
        self.assertEqual(saved["analysis_json"], self.store.artifacts(first.run_id)["analysis_json"])

    def test_snapshot_metadata_and_artifacts_use_one_manifest_revision(self):
        service, first = self.completed_run()
        old_manifest = self.store.read_manifest(first.run_id)
        service._analysis_processor = FakeAnalysisProcessor(summary="new report")
        self.run_to_completion(service, service.start_analyze(first.run_id))
        real_read = self.store.read_manifest
        read_count = [0]

        def read(run_id):
            read_count[0] += 1
            return old_manifest if read_count[0] == 1 else real_read(run_id)

        with patch.object(self.store, "read_manifest", side_effect=read):
            snapshot = service._snapshot_from_manifest(first.run_id)
        self.assertEqual(read_count[0], 1)
        self.assertEqual(snapshot.summary, "old report")
        self.assertEqual(snapshot.artifacts["analysis_json"], first.artifacts["analysis_json"])

    def test_cancel_after_staging_keeps_old_pointer_and_complete_paid_version(self):
        service, first = self.completed_run()
        service._analysis_processor = FakeAnalysisProcessor(summary="staged new result")
        ready, release = threading.Event(), threading.Event()
        self._releases.append(release)
        original_save = self.store.save_analysis

        def blocked_save(*args, **kwargs):
            result = original_save(*args, **kwargs)
            ready.set()
            release.wait(5)
            return result

        with patch.object(self.store, "save_analysis", side_effect=blocked_save):
            retry = service.start_analyze(first.run_id)
            self.assertTrue(ready.wait(5))
            self.assertEqual(self.store.load_analysis(first.run_id)["summary"], "old report")
            service.stop(retry.task_id)
            release.set()
            final = self.run_to_completion(service, retry)
        self.assertEqual(final.status, RunStatus.CANCELLED)
        manifest = self.store.read_manifest(first.run_id)
        self.assertEqual(manifest["current_analysis"]["attempt_id"], first.task_id)
        self.assertEqual(manifest["analysis_attempts"][-1]["status"], RunStatus.CANCELLED)
        self.assertTrue(manifest["analysis_attempts"][-1]["artifacts"])

    def test_cancel_before_processor_entry_makes_no_provider_call(self):
        service, first = self.completed_run()
        entered, release = threading.Event(), threading.Event()
        self._releases.append(release)
        real_update = self.store.update_analysis_attempt

        def blocked_update(*args, **kwargs):
            result = real_update(*args, **kwargs)
            if not entered.is_set():
                entered.set()
                release.wait(5)
            return result

        with patch.object(self.store, "update_analysis_attempt", side_effect=blocked_update), \
                patch.object(service._analysis_processor, "analyze", side_effect=AssertionError("provider called")):
            retry = service.start_analyze(first.run_id)
            self.assertTrue(entered.wait(5))
            service.stop(retry.task_id)
            release.set()
            final = self.run_to_completion(service, retry)
        self.assertEqual(final.status, RunStatus.CANCELLED)
        self.assertEqual(self.store.load_analysis(first.run_id)["summary"], "old report")

    def test_staging_write_failure_leaves_effective_report_unchanged(self):
        service, first = self.completed_run()
        service._analysis_processor = FakeAnalysisProcessor(summary="bad write")
        with patch("src.service.run_store._atomic_dump_json", side_effect=OSError("disk full")):
            retry = self.run_to_completion(service, service.start_analyze(first.run_id))
        self.assertEqual(retry.status, RunStatus.FAILED)
        self.assertEqual(self.store.load_analysis(first.run_id)["summary"], "old report")
        self.assertFalse(list(self.store.run_dir(first.run_id).glob(".analysis-stage-*")))

    def test_manifest_commit_failure_preserves_old_version_and_reports_saved_candidate(self):
        service, first = self.completed_run()
        service._analysis_processor = FakeAnalysisProcessor(summary="unpublished result")
        real_write = self.store.write_manifest

        def fail_publication(run_id, manifest):
            current = manifest.get("current_analysis") or {}
            if current.get("attempt_id") != first.task_id:
                raise OSError("manifest locked")
            return real_write(run_id, manifest)

        with patch.object(self.store, "write_manifest", side_effect=fail_publication):
            retry = self.run_to_completion(service, service.start_analyze(first.run_id))
        self.assertEqual(retry.status, RunStatus.COMPLETED)
        self.assertTrue(retry.warnings)
        self.assertEqual(self.store.load_analysis(first.run_id)["summary"], "old report")
        self.assertEqual(json.loads(Path(retry.artifacts["analysis_json"]).read_text(encoding="utf-8"))["summary"], "unpublished result")
        self.assertEqual(json.loads((self.store.run_dir(first.run_id) / "analysis.json").read_text(encoding="utf-8"))["summary"], "old report")

    def test_alias_failure_does_not_revert_a_published_version(self):
        service, first = self.completed_run()
        service._analysis_processor = FakeAnalysisProcessor(summary="committed new result")
        with patch.object(self.store, "sync_analysis_aliases", side_effect=OSError("alias locked")):
            retry = self.run_to_completion(service, service.start_analyze(first.run_id))
        self.assertEqual(retry.status, RunStatus.COMPLETED)
        self.assertTrue(retry.warnings)
        self.assertEqual(self.store.load_analysis(first.run_id)["summary"], "committed new result")
        manifest = self.store.read_manifest(first.run_id)
        self.assertEqual(manifest["current_analysis"]["attempt_id"], retry.task_id)
        self.assertEqual(manifest["current_analysis"]["warnings"], retry.warnings)
        self.assertEqual(manifest["analysis_attempts"][-1]["warnings"], retry.warnings)
        restarted = AgentService(store=RunStore(self.store.root), api=object())
        self.assertEqual(restarted.get_status(run_id=first.run_id).warnings, retry.warnings)

    def test_direct_save_alias_failure_returns_committed_version_and_persistent_warning(self):
        _, first = self.completed_run()
        warnings = []
        with patch.object(self.store, "sync_analysis_aliases", side_effect=OSError("alias locked")):
            saved = self.store.save_analysis(first.run_id, {"summary": "direct new result"}, warnings)
        self.assertTrue(warnings)
        self.assertEqual(saved["analysis_json"], self.store.artifacts(first.run_id)["analysis_json"])
        self.assertEqual(self.store.load_analysis(first.run_id)["summary"], "direct new result")
        self.assertEqual(self.store.read_manifest(first.run_id)["warnings"], warnings)

    def test_alias_and_warning_write_failures_do_not_undo_publication(self):
        _, first = self.completed_run()
        real_write = self.store.write_manifest

        def fail_warning_write(run_id, manifest):
            if manifest.get("warnings"):
                raise OSError("warning write locked")
            return real_write(run_id, manifest)

        warnings = []
        with patch.object(self.store, "sync_analysis_aliases", side_effect=OSError("alias locked")), \
                patch.object(self.store, "write_manifest", side_effect=fail_warning_write):
            saved = self.store.save_analysis(first.run_id, {"summary": "direct new result"}, warnings)
        self.assertEqual(len(warnings), 2)
        self.assertEqual(self.store.load_analysis(first.run_id)["summary"], "direct new result")
        self.assertEqual(saved["analysis_json"], self.store.artifacts(first.run_id)["analysis_json"])

    def test_interrupted_staged_version_is_not_selected_by_a_new_process(self):
        _, first = self.completed_run()
        attempt_id = "task-" + new_run_id()
        manifest = self.store.read_manifest(first.run_id)
        manifest["analysis_attempts"].append({"attempt_id": attempt_id, "status": RunStatus.EXPORTING,
                                              "artifacts": {}, "started_at": "now", "finished_at": ""})
        self.store.write_manifest(first.run_id, manifest)
        self.store.save_analysis(first.run_id, {"summary": "uncommitted", "report_markdown": "# unpublished"}, attempt_id=attempt_id)
        script = (
            "import json,sys; from pathlib import Path; from src.service.run_store import RunStore; "
            "from src.service.agent_service import AgentService; s=RunStore(Path(sys.argv[1])); "
            "a=AgentService(store=s,api=object()); "
            "print(json.dumps({'snapshot':a.get_status(run_id=sys.argv[2]).to_dict(),'result':s.load_analysis(sys.argv[2])}))"
        )
        child = subprocess.run([sys.executable, "-X", "utf8", "-c", script, str(self.store.root), first.run_id],
                               cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=15)
        self.assertEqual(child.returncode, 0, child.stderr)
        data = json.loads(child.stdout)
        self.assertEqual(data["snapshot"]["status"], RunStatus.COMPLETED)
        self.assertTrue(data["snapshot"]["warnings"])
        self.assertEqual(data["result"]["summary"], "old report")

    def test_copying_a_run_keeps_version_paths_inside_new_root(self):
        service = self.make_service(processor=WordCloudProcessor(summary="with image"))
        first = self.run_to_completion(service, service.start_crawl_and_analyze("BV1xx411c7mD"))
        original_image = Path(first.artifacts["word_cloud_image"]).read_bytes()
        relocated = self.root / "relocated"
        shutil.copytree(self.store.run_dir(first.run_id), relocated / first.run_id)
        store = RunStore(relocated)
        for path in store.artifacts(first.run_id).values():
            self.assertTrue(Path(path).is_relative_to(relocated))
        result = store.load_analysis(first.run_id)
        self.assertEqual(result["summary"], "with image")
        self.assertTrue(Path(result["word_cloud_image"]).is_relative_to(relocated))
        self.assertEqual(Path(result["word_cloud_image"]).read_bytes(), original_image)

    def test_artifact_traversal_and_missing_version_do_not_fall_back_to_aliases(self):
        _, first = self.completed_run()
        manifest = self.store.read_manifest(first.run_id)
        manifest["current_analysis"]["artifacts"]["analysis_json"] = "../../outside.json"
        self.store.write_manifest(first.run_id, manifest)
        with self.assertRaises(ServiceError):
            self.store.load_analysis(first.run_id)
        manifest["current_analysis"]["artifacts"]["analysis_json"] = "analysis-attempts/missing.json"
        self.store.write_manifest(first.run_id, manifest)
        with self.assertRaises(ServiceError):
            self.store.load_analysis(first.run_id)
