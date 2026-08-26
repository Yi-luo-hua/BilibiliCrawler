"""
Stage 2 of docs/SIDECAR_MIGRATION.md: caller policy vs per-request parameters.

AgentService was written for one caller, so its limits were constants. The
desktop needs the opposite of several of them, and the migration must not
discover that by silently changing desktop behaviour. This pins the split:

- static, per-caller limits live on CallerPolicy;
- chart_keys, batch_size and the LLM credentials are per-request, because a key
  belongs to one call and must never sit on a long-lived object.

No wiring yet -- backend/sidecar.py is untouched at this stage.
"""
import dataclasses
import tempfile
import unittest
from pathlib import Path

from src.service.agent_service import AgentService
from src.service.credentials import LLMCredentials
from src.service.models import (
    AGENT_CHART_KEYS,
    AGENT_POLICY,
    DESKTOP_POLICY,
    MAX_PAGES_CEILING,
    CallerPolicy,
    ErrorCode,
    ServiceError,
)
from src.service.run_store import RunStore

SECRET_KEY = "sk-POLICY-CANARY-abcdef"

COMMENT = {
    "comment_id": 1,
    "is_reply": False,
    "username": "用户A",
    "user_level": 5,
    "content": "一条评论",
    "like_count": 1,
    "reply_count": 0,
    "ctime": 1735660800,
    "ctime_text": "2025-01-01 00:00:00",
    "ip_location": "广东",
}


class RecordingCrawler:
    def __init__(self, progress):
        self.progress = progress
        self.calls: list[dict] = []

    def stop(self):
        pass

    def crawl_comments(self, url_or_id, include_replies=True, max_pages=100, mode=3):
        self.calls.append({"max_pages": max_pages, "mode": mode,
                           "include_replies": include_replies})
        return [dict(COMMENT)]


class RecordingProcessor:
    def __init__(self):
        self.params: list[dict] = []

    def analyze(self, comments, dynamics, params, progress=None, cancel_event=None):
        self.params.append(dict(params))
        return {
            "summary": "ok",
            "report_markdown": "# r",
            "meta": {"analyzed_records": len(comments), "total_records": len(comments)},
        }


class PolicyTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = RunStore(Path(self._tmp.name))
        self.processor = RecordingProcessor()
        self.crawlers: list[RecordingCrawler] = []
        self.services: list[AgentService] = []
        self.addCleanup(self._drain)

    def _drain(self) -> None:
        # Ask first, then join, then insist: a thread still running when the
        # TemporaryDirectory is destroyed races the next test through a
        # directory that no longer exists.
        stragglers = []
        for service in self.services:
            for task in list(service._tasks.values()):
                if task.thread is None or not task.thread.is_alive():
                    continue
                try:
                    service.stop(task.task_id)
                except Exception:  # noqa: BLE001 - cleanup must not mask failures
                    pass
                task.thread.join(timeout=5)
                if task.thread.is_alive():
                    stragglers.append(task.task_id)
        assert not stragglers, f'tasks still running at teardown: {stragglers}'

    def make(self, policy=None, resolver=None) -> AgentService:
        def factory(progress):
            crawler = RecordingCrawler(progress)
            self.crawlers.append(crawler)
            return crawler

        service = AgentService(
            store=self.store,
            api=object(),
            crawler_factory=factory,
            analysis_processor=self.processor,
            credentials_resolver=resolver or (lambda: LLMCredentials(api_key=SECRET_KEY)),
            policy=policy,
        )
        self.services.append(service)
        return service

    def finish(self, service, snapshot):
        final = service.wait(snapshot.task_id, 5)
        self.assertTrue(final.done, f"{final.status}: {final.error}")
        return final


class PolicyValueTests(unittest.TestCase):
    def test_the_default_policy_is_the_agent_policy(self) -> None:
        self.assertEqual(CallerPolicy(), AGENT_POLICY)
        self.assertEqual(AGENT_POLICY.max_pages_ceiling, MAX_PAGES_CEILING)
        self.assertEqual(list(AGENT_POLICY.default_chart_keys), list(AGENT_CHART_KEYS))
        self.assertNotIn("word_cloud", AGENT_POLICY.default_chart_keys)

    def test_agent_policy_clamps_pages_and_desktop_policy_does_not(self) -> None:
        self.assertEqual(AGENT_POLICY.resolve_max_pages(99999), MAX_PAGES_CEILING)
        self.assertEqual(DESKTOP_POLICY.resolve_max_pages(99999), 99999)

    def test_each_policy_has_its_own_page_default(self) -> None:
        # The desktop default is 100; AgentService's is deliberately far lower.
        self.assertEqual(DESKTOP_POLICY.resolve_max_pages(None), 100)
        self.assertEqual(AGENT_POLICY.resolve_max_pages(None), 5)
        for junk in ("", "abc", None, [], {}):
            with self.subTest(value=junk):
                self.assertEqual(AGENT_POLICY.resolve_max_pages(junk), 5)

    def test_pages_never_go_below_one(self) -> None:
        for policy in (AGENT_POLICY, DESKTOP_POLICY):
            with self.subTest(policy=policy):
                self.assertEqual(policy.resolve_max_pages(0), 1)
                self.assertEqual(policy.resolve_max_pages(-7), 1)

    def test_a_request_chart_set_beats_the_policy_default(self) -> None:
        self.assertEqual(
            AGENT_POLICY.resolve_chart_keys(["word_cloud", "topic_ranking"]),
            ["word_cloud", "topic_ranking"],
        )

    def test_an_empty_request_falls_back_rather_than_forcing_every_chart(self) -> None:
        # An empty list handed to _normalize_chart_keys would re-enable the full
        # set, word cloud included, so it must never reach the processor.
        self.assertEqual(AGENT_POLICY.resolve_chart_keys([]), list(AGENT_CHART_KEYS))
        self.assertEqual(AGENT_POLICY.resolve_chart_keys(None), list(AGENT_CHART_KEYS))

    def test_the_desktop_policy_forces_no_chart_set(self) -> None:
        # None means "omit the key"; the processor then applies its own default,
        # which is what the desktop has always had.
        self.assertIsNone(DESKTOP_POLICY.resolve_chart_keys(None))
        self.assertIsNone(DESKTOP_POLICY.resolve_chart_keys([]))
        self.assertEqual(DESKTOP_POLICY.resolve_chart_keys(["word_cloud"]), ["word_cloud"])

    def test_the_policy_is_frozen_and_holds_nothing_credential_shaped(self) -> None:
        names = {field.name for field in dataclasses.fields(CallerPolicy)}
        for banned in ("api_key", "key", "token", "secret", "password", "credentials", "llm_config"):
            self.assertNotIn(banned, names)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            AGENT_POLICY.max_pages_ceiling = 999  # type: ignore[misc]


class PolicyValidationTests(unittest.TestCase):
    def test_a_policy_that_would_yield_a_non_positive_page_count_is_rejected(self) -> None:
        # Both of these used to construct happily and then hand the crawler 0
        # or -2 pages, which nothing downstream checks.
        with self.assertRaises(ValueError):
            CallerPolicy(max_pages_default=0)
        with self.assertRaises(ValueError):
            CallerPolicy(max_pages_ceiling=-2)

    def test_a_ceiling_below_the_default_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CallerPolicy(max_pages_default=10, max_pages_ceiling=2)

    def test_an_empty_default_chart_set_is_rejected(self) -> None:
        # Empty would mean "every chart" downstream, word cloud included.
        with self.assertRaises(ValueError):
            CallerPolicy(default_chart_keys=())

    def test_the_shipped_policies_are_valid(self) -> None:
        self.assertEqual(AGENT_POLICY, CallerPolicy(**dataclasses.asdict(AGENT_POLICY)))
        self.assertEqual(DESKTOP_POLICY, CallerPolicy(**dataclasses.asdict(DESKTOP_POLICY)))


class PolicyReachesTheCrawlerTests(PolicyTestCase):
    def test_the_agent_ceiling_still_applies_by_default(self) -> None:
        service = self.make()
        self.finish(service, service.start_crawl("BV1xx411c7mD", max_pages=99999))
        self.assertEqual(self.crawlers[0].calls[0]["max_pages"], MAX_PAGES_CEILING)

    def test_the_desktop_policy_forwards_the_requested_page_count(self) -> None:
        service = self.make(policy=DESKTOP_POLICY)
        self.finish(service, service.start_crawl("BV1xx411c7mD", max_pages=250))
        self.assertEqual(self.crawlers[0].calls[0]["max_pages"], 250)

    def test_the_desktop_policy_defaults_to_a_hundred_pages(self) -> None:
        service = self.make(policy=DESKTOP_POLICY)
        self.finish(service, service.start_crawl("BV1xx411c7mD"))
        self.assertEqual(self.crawlers[0].calls[0]["max_pages"], 100)


class PerRequestParameterTests(PolicyTestCase):
    def seed(self, service):
        return self.finish(service, service.start_crawl("BV1xx411c7mD")).run_id

    def test_the_agent_chart_set_still_excludes_the_word_cloud(self) -> None:
        service = self.make()
        run_id = self.seed(service)
        self.finish(service, service.start_analyze(run_id))

        keys = self.processor.params[0]["chart_keys"]
        self.assertTrue(keys)
        self.assertNotIn("word_cloud", keys)

    def test_a_requested_chart_set_reaches_the_processor(self) -> None:
        service = self.make(policy=DESKTOP_POLICY)
        run_id = self.seed(service)
        self.finish(service, service.start_analyze(run_id, chart_keys=["word_cloud", "region_map"]))

        self.assertEqual(self.processor.params[0]["chart_keys"], ["word_cloud", "region_map"])

    def test_the_desktop_policy_omits_chart_keys_when_none_were_ticked(self) -> None:
        service = self.make(policy=DESKTOP_POLICY)
        run_id = self.seed(service)
        self.finish(service, service.start_analyze(run_id))

        # Absent, not empty: an empty list would re-enable every chart.
        self.assertNotIn("chart_keys", self.processor.params[0])

    def test_batch_size_is_forwarded_only_when_asked_for(self) -> None:
        service = self.make()
        run_id = self.seed(service)

        self.finish(service, service.start_analyze(run_id))
        self.assertNotIn("batch_size", self.processor.params[0])

        self.finish(service, service.start_analyze(run_id, batch_size=45))
        self.assertEqual(self.processor.params[1]["batch_size"], 45)

    def test_batch_size_is_clamped_to_the_processor_range(self) -> None:
        service = self.make()
        run_id = self.seed(service)
        self.finish(service, service.start_analyze(run_id, batch_size=9999))
        self.assertEqual(self.processor.params[0]["batch_size"], 200)


class InjectionPointTests(PolicyTestCase):
    """Stage 4 hands AgentService the objects SidecarServices already holds.

    crawler_factory and analysis_processor are substituted by every test in this
    file, so they are covered implicitly. data_processor and api were not, and a
    desktop path silently using a different DataProcessor would report different
    stats to the UI.
    """

    def test_an_injected_data_processor_is_the_one_that_runs(self) -> None:
        calls: list[str] = []

        class RecordingDataProcessor:
            @staticmethod
            def clean_comments(comments):
                calls.append("clean_comments")
                return [dict(row, content="cleaned by the injected processor") for row in comments]

            @staticmethod
            def get_statistics(comments):
                calls.append("get_statistics")
                # Values no real DataProcessor would produce for one comment, so
                # the assertions below fail if production ignores this return.
                return {
                    "total": len(comments),
                    "main_comments": 41,
                    "replies": 42,
                    "sentinel": "from the injected processor",
                }

        def factory(progress):
            crawler = RecordingCrawler(progress)
            self.crawlers.append(crawler)
            return crawler

        service = AgentService(
            store=self.store,
            api=object(),
            crawler_factory=factory,
            analysis_processor=self.processor,
            data_processor=RecordingDataProcessor,
            credentials_resolver=lambda: LLMCredentials(api_key=SECRET_KEY),
        )
        self.services.append(service)

        snapshot = self.finish(service, service.start_crawl("BV1xx411c7mD"))

        self.assertEqual(calls, ["clean_comments", "get_statistics"])

        # Counted: the snapshot's numbers come from this processor's statistics,
        # not from a default's view of the same comment.
        self.assertEqual(snapshot.counts["main_comments"], 41)
        self.assertEqual(snapshot.counts["replies"], 42)

        # Persisted: and its cleaned rows are what landed on disk.
        manifest = self.store.read_manifest(snapshot.run_id)
        self.assertEqual(manifest["counts"]["main_comments"], 41)
        stored = self.store.load_comments(snapshot.run_id)
        self.assertEqual(stored[0]["content"], "cleaned by the injected processor")

    def test_the_injected_api_is_used_by_a_real_start_crawl(self) -> None:
        # No crawler_factory, so the service builds a real CommentCrawler and
        # drives it through start_crawl. Calling _crawler_factory directly would
        # prove only that the lambda is wired, not that the run path uses it.
        class RecordingAPI:
            def __init__(self):
                self.calls: list[str] = []

            def get_video_info(self, bvid):
                self.calls.append("get_video_info")
                return {"data": {"aid": 12345}}

            def get_comments(self, *args, **kwargs):
                self.calls.append("get_comments")
                return {"data": {"replies": [{
                    "rpid": 1,
                    "member": {"uname": "u", "mid": 1, "level_info": {"current_level": 1}},
                    "content": {"message": "hi"},
                    "like": 0, "rcount": 0, "ctime": 1735660800,
                    "reply_control": {"location": "IP属地：广东"},
                }], "cursor": {"is_end": True}}}

            def get_replies(self, *args, **kwargs):
                self.calls.append("get_replies")
                return {"data": {"replies": []}}

        api = RecordingAPI()
        service = AgentService(
            store=self.store,
            api=api,
            analysis_processor=self.processor,
            credentials_resolver=lambda: LLMCredentials(api_key=SECRET_KEY),
        )
        self.services.append(service)

        snapshot = self.finish(service, service.start_crawl("BV1xx411c7mD", max_pages=1))

        self.assertIn("get_video_info", api.calls)
        self.assertIn("get_comments", api.calls)
        self.assertEqual(snapshot.counts["comments"], 1)


class CredentialsStayPerRequestTests(PolicyTestCase):
    def test_supplied_credentials_are_used_instead_of_the_resolver(self) -> None:
        def explode():
            raise AssertionError("the resolver must not be consulted")

        service = self.make(resolver=explode)
        # The crawl needs no credentials, so the resolver stays untouched there.
        run_id = self.finish(service, service.start_crawl("BV1xx411c7mD")).run_id

        supplied = LLMCredentials(api_key="sk-FROM-THE-REQUEST-123456",
                                  base_url="https://desktop/v1", model="ui-model")
        self.finish(service, service.start_analyze(run_id, credentials=supplied))

        config = self.processor.params[0]["llm_config"]
        self.assertEqual(config["api_key"], "sk-FROM-THE-REQUEST-123456")
        self.assertEqual(config["base_url"], "https://desktop/v1")
        self.assertEqual(config["model"], "ui-model")

    def test_the_resolver_is_still_the_fallback(self) -> None:
        service = self.make()
        run_id = self.finish(service, service.start_crawl("BV1xx411c7mD")).run_id
        self.finish(service, service.start_analyze(run_id))
        self.assertEqual(self.processor.params[0]["llm_config"]["api_key"], SECRET_KEY)

    def test_the_service_does_not_retain_the_key_after_the_call(self) -> None:
        service = self.make()
        run_id = self.finish(service, service.start_crawl("BV1xx411c7mD")).run_id
        supplied = LLMCredentials(api_key="sk-SHOULD-NOT-STICK-9876")
        self.finish(service, service.start_analyze(run_id, credentials=supplied))

        # repr() is not enough on its own: LLMCredentials masks the key, so a
        # retained credentials object would still print as '***'. Look for the
        # object itself, and for the raw string, separately.
        retained = [name for name, value in vars(service).items()
                    if isinstance(value, LLMCredentials)]
        self.assertEqual(retained, [], f"credentials object survived on {retained}")

        for attribute, value in vars(service).items():
            if isinstance(value, LLMCredentials):
                continue
            self.assertNotIn("sk-SHOULD-NOT-STICK-9876", repr(value),
                             f"the key survived on {attribute}")
        self.assertNotIn("sk-SHOULD-NOT-STICK-9876", repr(service.policy))
        self.assertFalse(
            [f for f in dataclasses.fields(type(service.policy))
             if isinstance(getattr(service.policy, f.name), LLMCredentials)],
            "the policy must never carry credentials",
        )

    def test_the_key_never_reaches_the_manifest(self) -> None:
        # start_crawl_and_analyze is the entry point that writes analysis params
        # into a manifest, so it is the one _public() has to strip. start_analyze
        # never calls create_run, which made the earlier version of this test
        # pass without exercising the stripping at all.
        service = self.make()
        supplied = LLMCredentials(api_key="sk-MANIFEST-CANARY-5555",
                                  base_url="https://x/v1", model="m")
        snapshot = self.finish(
            service,
            service.start_crawl_and_analyze("BV1xx411c7mD", credentials=supplied),
        )

        manifest = self.store.read_manifest(snapshot.run_id)
        self.assertNotIn("llm_config", manifest["params"])
        self.assertNotIn("api_key", manifest["params"])
        # The crawl params it does keep are still there.
        self.assertIn("url", manifest["params"])

        for path in self.store.run_dir(snapshot.run_id).rglob("*"):
            if path.is_file():
                self.assertNotIn(b"sk-MANIFEST-CANARY-5555", path.read_bytes(),
                                 f"the key leaked into {path.name}")

    def test_the_combined_entry_point_forwards_every_request_parameter(self) -> None:
        # The highest-level MCP tool routes through here, so its pass-through
        # deserves the same coverage as the standalone analyse entry point.
        service = self.make(policy=DESKTOP_POLICY)
        supplied = LLMCredentials(api_key="sk-COMBINED-1234567",
                                  base_url="https://combined/v1", model="combined-model")

        self.finish(service, service.start_crawl_and_analyze(
            "BV1xx411c7mD",
            max_pages=250,
            sample_size=321,
            chart_keys=["word_cloud", "region_map"],
            batch_size=45,
            credentials=supplied,
        ))

        self.assertEqual(self.crawlers[0].calls[0]["max_pages"], 250)
        params = self.processor.params[0]
        self.assertEqual(params["chart_keys"], ["word_cloud", "region_map"])
        self.assertEqual(params["batch_size"], 45)
        self.assertEqual(params["sample_size"], 321)
        self.assertEqual(params["llm_config"], {
            "api_key": "sk-COMBINED-1234567",
            "base_url": "https://combined/v1",
            "model": "combined-model",
        })

    def test_a_raw_llm_config_dict_is_rejected_with_a_readable_error(self) -> None:
        # The desktop holds {api_key, base_url, model} from its RPC. Passing it
        # straight in used to reach .to_llm_config() and raise AttributeError.
        service = self.make()
        run_id = self.finish(service, service.start_crawl("BV1xx411c7mD")).run_id

        with self.assertRaises(ServiceError) as ctx:
            service.start_analyze(run_id, credentials={"api_key": "sk-dict-form-123"})
        self.assertEqual(ctx.exception.code, ErrorCode.INVALID_INPUT)
        self.assertIn("from_config", str(ctx.exception))

    def test_from_config_converts_the_rpc_shape(self) -> None:
        credentials = LLMCredentials.from_config(
            {"api_key": " sk-from-dict-9876 ", "base_url": "https://x/v1", "model": "m"}
        )
        self.assertEqual(credentials.to_llm_config(), {
            "api_key": "sk-from-dict-9876", "base_url": "https://x/v1", "model": "m",
        })
        self.assertNotIn("sk-from-dict-9876", repr(credentials))


if __name__ == "__main__":
    unittest.main()
