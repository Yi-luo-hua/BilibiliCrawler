import threading
import unittest

from src.crawler.dynamic_crawler import DynamicCrawler


def dynamic_item(dynamic_id: str, timestamp: int) -> dict:
    return {
        "id_str": dynamic_id,
        "type": "DYNAMIC_TYPE_WORD",
        "modules": {
            "module_author": {"pub_ts": timestamp, "name": "tester"},
            "module_dynamic": {"desc": {"text": dynamic_id}},
            "module_stat": {},
        },
    }


class DynamicCrawlerTests(unittest.TestCase):
    def test_space_api_failure_is_reported_instead_of_returning_empty_success(self) -> None:
        class FailedApi:
            def get_user_dynamics(self, host_mid: int, offset: str = ""):
                return None

        crawler = DynamicCrawler(api=FailedApi())

        with self.assertRaisesRegex(RuntimeError, "获取用户动态失败"):
            crawler.crawl_dynamics(123, max_pages=1)

    def test_following_api_failure_is_reported_instead_of_returning_empty_success(self) -> None:
        class FailedApi:
            def get_following_feed(self, offset: str = ""):
                return None

        crawler = DynamicCrawler(api=FailedApi())

        with self.assertRaisesRegex(RuntimeError, "获取关注动态失败"):
            crawler.crawl_following_feed(max_pages=1)

    def test_space_feed_continues_when_page_contains_old_and_in_range_items(self) -> None:
        class PagedApi:
            def __init__(self) -> None:
                self.offsets: list[str] = []

            def get_user_dynamics(self, host_mid: int, offset: str = ""):
                self.offsets.append(offset)
                if not offset:
                    return {
                        "data": {
                            "items": [
                                dynamic_item("recent-page-1", 200),
                                dynamic_item("old-page-1", 1),
                            ],
                            "has_more": True,
                            "offset": "next",
                        }
                    }
                return {
                    "data": {
                        "items": [dynamic_item("in-range-page-2", 150)],
                        "has_more": False,
                        "offset": "",
                    }
                }

        api = PagedApi()
        crawler = DynamicCrawler(api=api)

        dynamics = crawler.crawl_dynamics(123, max_pages=2, start_time=100)

        self.assertEqual(api.offsets, ["", "next"])
        self.assertEqual(
            [item["dynamic_id"] for item in dynamics],
            ["recent-page-1", "in-range-page-2"],
        )

    def test_following_feed_continues_when_page_contains_old_and_in_range_items(self) -> None:
        class PagedApi:
            def __init__(self) -> None:
                self.offsets: list[str] = []

            def get_following_feed(self, offset: str = ""):
                self.offsets.append(offset)
                if not offset:
                    return {
                        "data": {
                            "items": [
                                dynamic_item("recent-page-1", 200),
                                dynamic_item("old-page-1", 1),
                            ],
                            "has_more": True,
                            "offset": "next",
                        }
                    }
                return {
                    "data": {
                        "items": [dynamic_item("in-range-page-2", 150)],
                        "has_more": False,
                        "offset": "",
                    }
                }

        api = PagedApi()
        crawler = DynamicCrawler(api=api)

        dynamics = crawler.crawl_following_feed(max_pages=2, start_time=100)

        self.assertEqual(api.offsets, ["", "next"])
        self.assertEqual(
            [item["dynamic_id"] for item in dynamics],
            ["recent-page-1", "in-range-page-2"],
        )

    def test_stop_returns_from_public_crawl_while_opus_request_is_blocked(self) -> None:
        request_started = threading.Event()
        release_request = threading.Event()

        class FakeResponse:
            status_code = 200
            text = "<html></html>"

        class BlockingSession:
            def get(self, *args, **kwargs):
                request_started.set()
                release_request.wait(timeout=2)
                return FakeResponse()

        class Api:
            session = BlockingSession()

            def get_user_dynamics(self, host_mid: int, offset: str = ""):
                item = dynamic_item("image-dynamic", 200)
                item["modules"]["module_dynamic"] = {
                    "major": {
                        "draw": {
                            "items": [{"src": "https://example.test/image.jpg"}],
                        }
                    }
                }
                return {
                    "data": {
                        "items": [item],
                        "has_more": False,
                        "offset": "",
                    }
                }

        crawler = DynamicCrawler(api=Api())
        worker = threading.Thread(
            target=crawler.crawl_dynamics,
            args=(123,),
            kwargs={"max_pages": 1},
        )
        worker.start()
        self.assertTrue(request_started.wait(timeout=1))

        crawler.stop()
        worker.join(timeout=0.5)
        stopped_promptly = not worker.is_alive()

        release_request.set()
        worker.join(timeout=2)

        self.assertTrue(stopped_promptly, "crawl should return promptly after stop()")


if __name__ == "__main__":
    unittest.main()
