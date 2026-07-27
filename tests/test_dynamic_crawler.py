import unittest

from src.crawler.dynamic_crawler import DynamicCrawler


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


if __name__ == "__main__":
    unittest.main()
