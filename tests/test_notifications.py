import unittest
from types import SimpleNamespace
from unittest.mock import patch

import checkin


class NotificationTests(unittest.TestCase):
    def setUp(self):
        logger_patch = patch.object(checkin, "logger")
        logger_patch.start()
        self.addCleanup(logger_patch.stop)
        self.checker = checkin.Checker(SimpleNamespace(verbose=False, exchange_plan="", EXCHANGE_PLANS={}))

    def result(self, account, domain, code, **kwargs):
        status = {
            checkin.CheckinStatus.SUCCESS: "签到成功",
            checkin.CheckinStatus.REPEAT: "重复签到",
            checkin.CheckinStatus.FAILURE: "签到失败",
        }[code]
        return checkin.CheckinResult(account, domain, code=code, status=status, **kwargs)

    def test_user_sample_groups_only_cross_site_denials(self):
        self.checker.results = [
            self.result(1, "glados.cloud", checkin.CheckinStatus.FAILURE,
                        permission_denied=True, message="没有权限"),
            self.result(1, "railgun.info", checkin.CheckinStatus.SUCCESS,
                        days="13 天", points_total="2 积分",
                        exchange="兑换失败: Not enough points. Need 100, have 2.0000000000000000"),
            self.result(2, "glados.cloud", checkin.CheckinStatus.SUCCESS,
                        days="13 天", points_total="21 积分",
                        exchange="兑换失败: Not enough points. Need 100, have 21.0000000000000000"),
            self.result(2, "railgun.info", checkin.CheckinStatus.FAILURE,
                        permission_denied=True, message="No permission"),
        ]
        payload = self.checker.format_results()
        text = checkin.render_payload(payload)
        self.assertEqual((payload["success"], payload["fail"], payload["raw_fail"], payload["cross_site"]), (2, 0, 2, 2))
        self.assertEqual(len(payload["rows"]), 4)
        self.assertIn("Railgun · 账号 1 · 签到成功", text)
        self.assertIn("GLaDOS · 账号 2 · 签到成功", text)
        self.assertIn("当前 2，需要 100", text)
        self.assertIn("当前 21，需要 100", text)
        self.assertIn("账号 1 → GLaDOS；账号 2 → Railgun", text)
        for unwanted in ("None", "Not enough points", "No permission", "签到失败", ".000000"):
            self.assertNotIn(unwanted, text.replace("不计入签到失败", ""))

    def test_all_sites_denied_remain_failures(self):
        self.checker.results = [
            self.result(1, domain, checkin.CheckinStatus.FAILURE, permission_denied=True,
                        message="No permission", days="None 天", points_total="None 积分")
            for domain in ("glados.cloud", "railgun.info")
        ]
        payload = self.checker.format_results()
        text = checkin.render_payload(payload)
        self.assertEqual((payload["fail"], payload["cross_site"]), (2, 0))
        self.assertEqual(text.count("签到失败"), 2)
        self.assertIn("请检查该站点 Cookie 是否有效", text)
        self.assertNotIn("None", text)

    def test_another_account_success_does_not_hide_failure(self):
        self.checker.results = [
            self.result(1, "glados.cloud", checkin.CheckinStatus.FAILURE, permission_denied=True),
            self.result(2, "railgun.info", checkin.CheckinStatus.SUCCESS),
        ]
        payload = self.checker.format_results()
        self.assertEqual((payload["fail"], payload["cross_site"]), (1, 0))

    def test_network_and_device_failures_remain_visible_with_other_site_success(self):
        for message in ("网络请求失败", "设备平台不匹配"):
            with self.subTest(message=message):
                self.checker.results = [
                    self.result(1, "glados.cloud", checkin.CheckinStatus.FAILURE, message=message),
                    self.result(1, "railgun.info", checkin.CheckinStatus.SUCCESS),
                ]
                payload = self.checker.format_results()
                self.assertEqual((payload["fail"], payload["cross_site"]), (1, 0))
                self.assertIn(message, checkin.render_payload(payload))

    def test_repeat_is_a_valid_site_and_has_clear_status(self):
        self.checker.results = [
            self.result(1, "glados.cloud", checkin.CheckinStatus.FAILURE, permission_denied=True),
            self.result(1, "railgun.info", checkin.CheckinStatus.REPEAT),
        ]
        payload = self.checker.format_results()
        text = checkin.render_payload(payload)
        self.assertEqual((payload["repeat"], payload["fail"], payload["cross_site"]), (1, 0, 1))
        self.assertIn("今日已签到", text)
        self.assertNotIn("本次 +0", text)

    def test_permission_flag_requires_explicit_api_code(self):
        with checkin.API("glados.cloud", 1, verbose=False) as api:
            for raw, denied in ((None, False), ({"message": "unknown"}, False),
                                ({"code": 4}, False), ({"code": -2}, True)):
                with self.subTest(raw=raw):
                    self.assertEqual(api._parse_checkin(raw)["permission_denied"], denied)

    def test_checker_preserves_earned_points_and_failure_details(self):
        with patch.object(checkin, "API") as api_cls:
            api = api_cls.return_value.__enter__.return_value
            api.get_status.return_value = ("13 天", 0)
            api.get_points.return_value = ("21 积分", 21)
            for data in (
                {"status": "签到成功", "code": checkin.CheckinStatus.SUCCESS,
                 "points": "5", "message": "ok", "permission_denied": False},
                {"status": "签到失败", "code": checkin.CheckinStatus.FAILURE,
                 "points": "0", "message": "没有权限", "permission_denied": True},
            ):
                with self.subTest(data=data):
                    api.checkin.return_value = data
                    result = self.checker._checkin_on_domain("test-cookie", 1, "glados.cloud")
                    self.assertEqual(result.points, data["points"])
                    self.assertEqual(result.message, data["message"])
                    self.assertEqual(result.permission_denied, data["permission_denied"])
            api.exchange.assert_not_called()

    def test_missing_metrics_and_exchange_details_are_readable(self):
        self.checker.results = [self.result(1, "glados.cloud", checkin.CheckinStatus.SUCCESS,
                                           days=None, points_total="None 积分")]
        payload = self.checker.format_results()
        text = checkin.render_payload(payload)
        self.assertIn("剩余 未获取｜总积分 未获取", text)
        self.assertEqual(checkin.display_exchange("兑换失败: Not enough points. Need 100.00, have 21.25000"),
                         "积分不足，暂未兑换（当前 21.25，需要 100）")
        self.assertEqual(checkin.display_exchange("兑换失败: 服务维护中"), "兑换失败: 服务维护中")
        self.assertEqual(checkin.display_exchange("兑换成功: plan100"), "兑换成功: plan100")
        self.assertEqual(checkin.ServerChanBackend("test")._render(payload), text.replace("\n", "  \n"))


if __name__ == "__main__":
    unittest.main()
