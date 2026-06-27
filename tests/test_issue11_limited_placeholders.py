from __future__ import annotations

import unittest

import nga_feishu_watch


ACCOUNT_LIMITED = "\u5e10\u53f7\u6743\u9650\u4e0d\u8db3"
TIME_LIMITED = "\u5e16\u5b50\u53d1\u5e03\u6216\u56de\u590d\u65f6\u95f4\u8d85\u8fc7\u9650\u5236"


def limited_user_home_payload(tid: int, pid: int, lastmodify: int = 1782477723) -> dict:
    return {
        "data": {
            "__T": {
                "4": {
                    "tid": tid,
                    "fid": tid - 1,
                    "subject": ACCOUNT_LIMITED,
                    "postdate": 0,
                    "lastpost": 0,
                    "lastmodify": lastmodify,
                    "authorid": 0,
                    "denied": "1",
                    "error": ACCOUNT_LIMITED,
                    "__P": {
                        "tid": tid,
                        "pid": pid,
                        "authorid": 41724123,
                        "postdate": "",
                        "subject": "",
                        "content": f"[color=silver][b]{TIME_LIMITED}[/b][/color]",
                        "postdatetimestamp": 0,
                        "denied": "1",
                        "error": "\u672a\u767b\u5f55",
                    },
                }
            }
        }
    }


class Issue11LimitedPlaceholderTests(unittest.TestCase):
    def test_limited_user_home_placeholder_is_not_extracted(self) -> None:
        first_posts = nga_feishu_watch.extract_posts(limited_user_home_payload(761, 762))
        second_posts = nga_feishu_watch.extract_posts(limited_user_home_payload(136, 137))
        changed_time_posts = nga_feishu_watch.extract_posts(limited_user_home_payload(136, 137, 1782478888))

        self.assertEqual(first_posts, [])
        self.assertEqual(second_posts, [])
        self.assertEqual(changed_time_posts, [])

    def test_limited_user_home_placeholder_does_not_hide_normal_replies(self) -> None:
        payload = limited_user_home_payload(761, 762)
        payload["data"]["__T"]["5"] = {
            "tid": 40795363,
            "subject": "\u6b63\u5e38\u5e16\u5b50",
            "__P": {
                "tid": 40795363,
                "pid": 873093075,
                "authorid": 41724123,
                "postdate": "2026-06-27 11:42:42",
                "content": "\u6b63\u5e38\u56de\u590d",
            },
        }

        posts = nga_feishu_watch.extract_posts(payload)

        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].key, "873093075")
        self.assertEqual(posts[0].subject, "\u6b63\u5e38\u5e16\u5b50")
        self.assertEqual(posts[0].content, "\u6b63\u5e38\u56de\u590d")


if __name__ == "__main__":
    unittest.main()
