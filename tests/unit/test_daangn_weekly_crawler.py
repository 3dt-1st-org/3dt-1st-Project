import importlib.util
import os
import sys
import types
import unittest
import base64
from datetime import datetime, timezone
from pathlib import Path


def _load_module():
    azure_mod = types.ModuleType("azure")
    azure_functions_mod = types.ModuleType("azure.functions")

    class TimerRequest:
        pass

    class QueueMessage:
        def __init__(self, body: bytes):
            self._body = body

        def get_body(self):
            return self._body

    class FunctionApp:
        def schedule(self, **_kwargs):
            def decorator(func):
                return func

            return decorator

        def queue_trigger(self, **_kwargs):
            def decorator(func):
                return func

            return decorator

    azure_functions_mod.TimerRequest = TimerRequest
    azure_functions_mod.QueueMessage = QueueMessage
    azure_functions_mod.FunctionApp = FunctionApp
    azure_mod.functions = azure_functions_mod

    psycopg_mod = types.ModuleType("psycopg")
    psycopg_mod.Connection = object

    requests_mod = types.ModuleType("requests")
    requests_mod.Session = object

    bs4_mod = types.ModuleType("bs4")

    class DummyBeautifulSoup:
        def __init__(self, html: str, _parser: str):
            self.html = html

        def select(self, selector: str):
            if selector == "a[href]":
                result = []
                html = self.html
                idx = 0
                while True:
                    pos = html.find("href=\"", idx)
                    if pos == -1:
                        break
                    start = pos + len("href=\"")
                    end = html.find("\"", start)
                    href = html[start:end]
                    node = types.SimpleNamespace(get=lambda k, default="", v=href: v if k == "href" else default)
                    result.append(node)
                    idx = end + 1
                return result

            return []

        def select_one(self, selector: str):
            mapping = {
                "h1": "맛집 추천",
                "[data-qa-id='article-content']": "망포 먹자골목 어풍당당 추천",
            }
            text = mapping.get(selector)
            if not text:
                return None

            return types.SimpleNamespace(get_text=lambda sep=" ", strip=True, t=text: t)

    bs4_mod.BeautifulSoup = DummyBeautifulSoup

    sys.modules["azure"] = azure_mod
    sys.modules["azure.functions"] = azure_functions_mod
    sys.modules["psycopg"] = psycopg_mod
    sys.modules["requests"] = requests_mod
    sys.modules["bs4"] = bs4_mod

    module_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "functions"
        / "daangn_weekly_crawler"
        / "function_app.py"
    )
    spec = importlib.util.spec_from_file_location("daangn_function_app", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestDaangnWeeklyCrawler(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_normalize_url_removes_query_and_trailing_slash(self):
        raw = "https://www.daangn.com/kr/community/posts/abc/?foo=1"
        normalized = self.module._normalize_url(raw)
        self.assertEqual(normalized, "https://www.daangn.com/kr/community/posts/abc")

    def test_hash_key_is_deterministic(self):
        key1 = self.module._hash_key("sample")
        key2 = self.module._hash_key("sample")
        self.assertEqual(key1, key2)
        self.assertEqual(len(key1), 64)

    def test_noise_comment_filter(self):
        self.assertTrue(self.module._is_noise_comment(","))
        self.assertTrue(self.module._is_noise_comment("ㅋㅋ"))
        self.assertTrue(self.module._is_noise_comment("   "))
        self.assertFalse(self.module._is_noise_comment("어풍당당 추천해요"))

    def test_get_keywords_from_env(self):
        os.environ["DAANGN_KEYWORDS"] = "맛집, 명소 , 행사"
        keywords = self.module._get_keywords()
        self.assertEqual(keywords, ["맛집", "명소", "행사"])

    def test_extract_post_links_filters_search_page(self):
        html = """
        <html><body>
          <a href="/kr/community/">root</a>
          <a href="/kr/community/posts/1">p1</a>
          <a href="/kr/community/s/?in=망포동-4534&search=맛집">search</a>
          <a href="https://www.daangn.com/kr/community/posts/2?foo=1">p2</a>
        </body></html>
        """
        links = self.module._extract_post_links(html)
        self.assertEqual(
            links,
            [
                "https://www.daangn.com/kr/community/posts/1",
                "https://www.daangn.com/kr/community/posts/2",
            ],
        )

    def test_extract_post_links_from_inline_json_pattern(self):
        html = """
        <script>
        {"items":[{"url":"\\/kr\\/community\\/articles\\/12345"},{"url":"\\/kr\\/community\\/s\\/?in=test&search=x"}]}
        </script>
        """
        links = self.module._extract_post_links(html)
        self.assertIn("https://www.daangn.com/kr/community/articles/12345", links)

    def test_extract_post_links_from_absolute_inline_url(self):
        html = """
        <script>
        {"items":[{"url":"https:\\/\\/www.daangn.com\\/kr\\/community\\/abc-post-123"}]}
        </script>
        """
        links = self.module._extract_post_links(html)
        self.assertIn("https://www.daangn.com/kr/community/abc-post-123", links)

    def test_extract_post_payload_returns_title_body(self):
        html = "<html><body><h1>맛집 추천</h1><div data-qa-id='article-content'>망포 먹자골목 어풍당당 추천</div></body></html>"
        title, body, post_created_at, comments = self.module._extract_post_payload(html)
        self.assertEqual(title, "맛집 추천")
        self.assertEqual(body, "망포 먹자골목 어풍당당 추천")
        self.assertIsNone(post_created_at)
        self.assertEqual(comments, [])

    def test_extract_post_payload_from_inline_json(self):
        html = """
        <script>
        {"subject":"맛집","title":"곡반정동 삼겹살 가성비 맛집 추천","content":"친구한테 추천받아 방문했어요\\n가성비가 좋아요","status":"NORMAL","createdAt":"2026-02-11T11:37:20.051+00:00","createdSortedComments":[{"id":"123","content":"어풍당당 추천해요","createdAt":"2026-01-01T00:00:00.000+00:00","subComments":[]}],"recentSortedComments":[]}
        </script>
        """
        title, body, post_created_at, comments = self.module._extract_post_payload(html)
        self.assertEqual(title, "곡반정동 삼겹살 가성비 맛집 추천")
        self.assertIn("가성비가 좋아요", body)
        self.assertEqual(post_created_at, "2026-02-11T11:37:20.051+00:00")
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0]["comment_id"], "123")
        self.assertEqual(comments[0]["content"], "어풍당당 추천해요")

    def test_decode_queue_body(self):
        msg = self.module.func.QueueMessage(b'{"task_id":"abc","run_id":"def"}')
        payload = self.module._decode_queue_body(msg)
        self.assertEqual(payload["task_id"], "abc")
        self.assertEqual(payload["run_id"], "def")

    def test_decode_queue_body_base64(self):
        encoded = base64.b64encode(b'{"task_id":"abc","run_id":"def"}')
        msg = self.module.func.QueueMessage(encoded)
        payload = self.module._decode_queue_body(msg)
        self.assertEqual(payload["task_id"], "abc")
        self.assertEqual(payload["run_id"], "def")

    def test_extract_places_from_text(self):
        text = "망포 먹자골목에 어풍당당 이라는 횟집있어요"
        places = self.module._extract_places_from_text(text)
        self.assertIn("어풍당당", places)

    def test_categorize_text(self):
        self.assertEqual(self.module._categorize_text("오늘 축제 다녀왔어요", ""), "행사")
        self.assertEqual(self.module._categorize_text("망포 맛집 추천해요", ""), "맛집")
        self.assertEqual(self.module._categorize_text("동네 산책 명소", ""), "명소")

    def test_get_week_start_utc(self):
        now = datetime(2026, 3, 4, 12, 0, 0, tzinfo=timezone.utc)
        week_start = self.module._get_week_start_utc(now)
        self.assertEqual(str(week_start), "2026-03-02")

    def test_aggregate_place_mentions(self):
        rows = [
            self.module.CommunityText(city_name="수원시", text="어풍당당 맛집 추천", category_hint="맛집"),
            self.module.CommunityText(city_name="수원시", text="어풍당당 맛집", category_hint=""),
        ]
        counter = self.module._aggregate_place_mentions_rule_based(rows)
        self.assertEqual(counter[("어풍당당", "맛집", "수원시")], 2)


if __name__ == "__main__":
    unittest.main()
