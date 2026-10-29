import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import requests

import checkin


WEBHOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-only-key"


class WeComTests(unittest.TestCase):
    def setUp(self):
        logger_patch = patch.object(checkin, "logger")
        self.logger = logger_patch.start()
        self.addCleanup(logger_patch.stop)
        post_patch = patch.object(checkin.requests, "post")
        self.post = post_patch.start()
        self.addCleanup(post_patch.stop)
        self.response = self.post.return_value
        self.response.json.return_value = {"errcode": 0, "errmsg": "ok"}
        self.backend = checkin.WeComBackend(WEBHOOK)

    def assert_secret_not_logged(self):
        self.assertNotIn("test-only-key", str(self.logger.mock_calls))

    def test_config_enables_only_wecom_and_trims_url(self):
        with patch.dict(os.environ, {"WECOM_WEBHOOK_URL": f"  {WEBHOOK}\n"}, clear=True):
            config = checkin.Config()
        self.assertEqual(config.wecom_webhook_url, WEBHOOK)
        service = checkin.PushService(config)
        self.assertEqual([backend.name for backend in service.backends], ["企业微信"])
        self.assertTrue(service.send("签到结果", {"rows": [], "note": "测试通知"}))
        self.post.assert_called_once()
        self.assert_secret_not_logged()

    def test_missing_or_blank_url_does_not_enable_backend(self):
        for env in ({}, {"WECOM_WEBHOOK_URL": " \n\t"}):
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True):
                config = checkin.Config()
                service = checkin.PushService(config)
                self.assertEqual(service.backends, [])
                self.assertFalse(service.send("签到结果", {"rows": []}))
        self.post.assert_not_called()

    def test_sends_title_and_rendered_results_as_text(self):
        payload = {
            "rows": [{
                "index": 1, "emoji": "✅", "status": "签到成功",
                "domain": "railgun.info", "points": "10", "days": "30 天",
                "points_total": "100 积分", "exchange": "未兑换",
            }],
        }
        self.assertTrue(self.backend.send("签到结果", payload))
        args, kwargs = self.post.call_args
        self.assertEqual(args, (WEBHOOK,))
        self.assertEqual(kwargs["timeout"], (10, 30))
        self.assertEqual(kwargs["json"], {
            "msgtype": "text",
            "text": {"content": "签到结果\n\n" + checkin.render_payload(payload)},
        })
        self.response.raise_for_status.assert_called_once()

    def test_only_integer_zero_errcode_counts_as_success(self):
        responses = (
            {"errcode": 93000, "errmsg": WEBHOOK},
            {"errmsg": "missing errcode"},
            {"errcode": False},
            {"errcode": "0"},
            {"errcode": WEBHOOK},
            [], None,
        )
        for result in responses:
            with self.subTest(result=result):
                self.response.json.return_value = result
                self.assertFalse(self.backend.send("签到结果", {"rows": []}))
        self.assert_secret_not_logged()

    def test_network_failures_do_not_leak_url(self):
        for error_type in (requests.Timeout, requests.ConnectionError, requests.exceptions.InvalidURL):
            with self.subTest(error_type=error_type):
                self.post.side_effect = error_type(f"请求失败: {WEBHOOK}")
                self.assertFalse(self.backend.send("签到结果", {"rows": []}))
        self.assert_secret_not_logged()

    def test_http_failure_does_not_leak_url(self):
        self.response.raise_for_status.side_effect = requests.HTTPError(WEBHOOK)
        self.assertFalse(self.backend.send("签到结果", {"rows": []}))
        self.response.json.assert_not_called()
        self.assert_secret_not_logged()

    def test_non_json_response_is_failure_without_leaking_body(self):
        self.response.json.side_effect = ValueError(WEBHOOK)
        self.assertFalse(self.backend.send("签到结果", {"rows": []}))
        self.assert_secret_not_logged()

    def test_long_unicode_message_is_truncated_with_notice(self):
        self.assertTrue(self.backend.send("签到结果", {"rows": [], "note": "中文😀" * 1000}))
        content = self.post.call_args.kwargs["json"]["text"]["content"]
        self.assertLessEqual(len(content.encode("utf-8")), 2048)
        self.assertNotIn("\ufffd", content)
        self.assertIn("内容已截断", content)
        self.assertTrue(content.startswith("签到结果\n\n"))

    def test_message_at_byte_limit_is_preserved(self):
        note = "a" * (2048 - len("标题\n\n".encode("utf-8")))
        self.assertTrue(self.backend.send("标题", {"rows": [], "note": note}))
        content = self.post.call_args.kwargs["json"]["text"]["content"]
        self.assertEqual(content, "标题\n\n" + note)

    def test_all_backends_run_when_wecom_fails(self):
        config = SimpleNamespace(
            push_key="pushdeer-test", serverchan_key="serverchan-test",
            wecom_webhook_url=WEBHOOK,
        )
        self.response.json.return_value = {"errcode": 93000}
        service = checkin.PushService(config)
        self.assertEqual([backend.name for backend in service.backends], ["PushDeer", "Server酱", "企业微信"])
        payload = {"rows": []}
        with patch.object(checkin.PushDeerBackend, "send", return_value=True) as pushdeer_send:
            with patch.object(checkin.ServerChanBackend, "send", return_value=True) as serverchan_send:
                self.assertTrue(service.send("签到结果", payload))
        pushdeer_send.assert_called_once_with("签到结果", payload)
        serverchan_send.assert_called_once_with("签到结果", payload)
        self.post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
