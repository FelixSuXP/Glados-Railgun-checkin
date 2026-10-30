import os
import re
import sys
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union

import requests
from pypushdeer import PushDeer
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from logging_config import init_logger


class CheckinStatus(Enum):
    """签到状态"""

    SUCCESS = 0
    REPEAT = 1
    FAILURE = -2


class ExchangePlan(Enum):
    """兑换计划"""

    PLAN100 = "plan100"
    PLAN200 = "plan200"
    PLAN500 = "plan500"


class APIEndpoint(Enum):
    """API端点"""

    CHECKIN = "/api/user/checkin"
    STATUS = "/api/user/status"
    POINTS = "/api/user/points"
    EXCHANGE = "/api/user/exchange"


class LogEmoji:
    """日志 Emoji 常量"""

    SUCCESS = "✅"
    FAIL = "❌"
    REPEAT = "🔄"
    PENDING = "⏳"
    CHECKIN = "🎫"
    STATUS = "📊"
    POINTS = "💰"
    EXCHANGE = "🎁"
    START = "🚀"
    END = "🏁"
    COOKIE = "🍪"
    DOMAIN = "🌐"
    WARNING = "⚠️"
    ERROR = "🔴"
    INFO = "ℹ️"


def log_method(func):
    """日志装饰器"""

    def wrapper(self, *args, **kwargs):
        method_name = func.__name__
        emoji_map = {
            "checkin": LogEmoji.CHECKIN,
            "get_status": LogEmoji.STATUS,
            "get_points": LogEmoji.POINTS,
            "exchange": LogEmoji.EXCHANGE,
        }
        emoji = emoji_map.get(method_name, LogEmoji.INFO)
        try:
            result = func(self, *args, **kwargs)
            return result
        except Exception as e:
            logger.error(f"{LogEmoji.COOKIE}[{self.cookie_index}] {LogEmoji.DOMAIN}[{self.domain}] {LogEmoji.ERROR} {method_name} 执行失败: {e}")

            DEFAULT_ERRORS = {
                "checkin": {"status": "签到失败", "points": "0", "message": ""},
                "get_status": ("None 天", -2),
                "get_points": ("None 积分", 0),
                "exchange": "",
            }

            if method_name in DEFAULT_ERRORS:
                error_template = DEFAULT_ERRORS[method_name]
                if isinstance(error_template, dict):
                    error_result = error_template.copy()
                    error_result["message"] = f"执行失败: {e}"
                    return error_result
                return error_template
            raise

    return wrapper


class Config:
    """应用配置"""

    ENV_PUSH_KEY = "PUSHDEER_SENDKEY"
    ENV_SERVERCHAN_KEY = "SERVERCHAN_SENDKEY"
    ENV_WECOM_WEBHOOK_URL = "WECOM_WEBHOOK_URL"
    ENV_COOKIES = "GLADOS_COOKIES"
    ENV_EXCHANGE_PLAN = "GLADOS_EXCHANGE_PLAN"
    ENV_VERBOSE = "GLADOS_VERBOSE"

    """默认兑换计划（none 表示不自动兑换）"""
    DEFAULT_EXCHANGE_PLAN = "none"

    """默认是否输出详细响应"""
    DEFAULT_VERBOSE = False

    """默认域名"""
    DOMAINS = ["glados.cloud", "railgun.info"]

    """兑换计划列表"""
    EXCHANGE_PLANS = {
        ExchangePlan.PLAN100.value: 100,
        ExchangePlan.PLAN200.value: 200,
        ExchangePlan.PLAN500.value: 500,
    }

    def __init__(self):
        self.push_key: str = ""
        self.serverchan_key: str = ""
        self.wecom_webhook_url: str = ""
        self.cookies_list: List[str] = []
        self.exchange_plan: str = self.DEFAULT_EXCHANGE_PLAN
        self.verbose: bool = self.DEFAULT_VERBOSE
        self._load_config()

    def _load_config(self) -> None:
        """加载配置"""
        push_key_env: Optional[str] = os.environ.get(self.ENV_PUSH_KEY)
        serverchan_key_env: Optional[str] = os.environ.get(self.ENV_SERVERCHAN_KEY)
        self.wecom_webhook_url = os.environ.get(self.ENV_WECOM_WEBHOOK_URL, "").strip()
        raw_cookies_env: Optional[str] = os.environ.get(self.ENV_COOKIES)
        exchange_plan_env: Optional[str] = os.environ.get(self.ENV_EXCHANGE_PLAN)
        verbose_env: Optional[str] = os.environ.get(self.ENV_VERBOSE)

        if not push_key_env:
            logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_PUSH_KEY}' 未设置。")
            self.push_key = ""
        else:
            self.push_key = push_key_env

        if not serverchan_key_env:
            logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_SERVERCHAN_KEY}' 未设置。")
            self.serverchan_key = ""
        else:
            self.serverchan_key = serverchan_key_env

        if not raw_cookies_env:
            logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_COOKIES}' 未设置。")
            self.cookies_list = []
        else:
            self.cookies_list = [cookie.strip() for cookie in raw_cookies_env.split("&") if cookie.strip()]
            if not self.cookies_list:
                raise ValueError(f"环境变量 '{self.ENV_COOKIES}' 已设置，但未包含任何有效的 Cookie。")

        if not exchange_plan_env:
            logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_EXCHANGE_PLAN}' 未设置，将使用默认设置（不自动兑换）。")
            self.exchange_plan = self.DEFAULT_EXCHANGE_PLAN
        else:
            if exchange_plan_env in self.EXCHANGE_PLANS:
                self.exchange_plan = exchange_plan_env
                logger.info(f"{LogEmoji.SUCCESS} 使用指定的兑换计划: {self.exchange_plan}")
            else:
                logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_EXCHANGE_PLAN}' 的值 '{exchange_plan_env}' 无效，将跳过自动兑换。")
                self.exchange_plan = self.DEFAULT_EXCHANGE_PLAN

        logger.info(f"{LogEmoji.INFO} 共加载了 {len(self.cookies_list)} 个 Cookie 用于签到。")
        logger.info(f"{LogEmoji.INFO} 当前 {self.ENV_PUSH_KEY} {'已设置' if push_key_env else '未设置'}，{self.ENV_SERVERCHAN_KEY} {'已设置' if serverchan_key_env else '未设置'}。")
        logger.info(f"{LogEmoji.INFO} 当前 {self.ENV_WECOM_WEBHOOK_URL} {'已设置' if self.wecom_webhook_url else '未设置'}。")
        logger.info(f"{LogEmoji.INFO} 当前 {self.ENV_EXCHANGE_PLAN}: {self.exchange_plan}。")

        if verbose_env is not None:
            verbose_env_lower = verbose_env.lower()
            if verbose_env_lower in ["true", "1", "yes", "y"]:
                self.verbose = True
            elif verbose_env_lower in ["false", "0", "no", "n"]:
                self.verbose = False
            else:
                logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_VERBOSE}' 的值 '{verbose_env}' 无效，将使用默认值 {self.DEFAULT_VERBOSE}。")

        logger.info(f"{LogEmoji.INFO} 当前 {self.ENV_VERBOSE}: {self.verbose}。")


# 各平台合法 User-Agent（版本号无关，仅平台 token 关键）
PLATFORM_UA = {
    "Windows": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "macOS": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Linux": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "iPhone": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    "Android": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
}


class API:
    """API 调用"""

    CHECKIN_URL = APIEndpoint.CHECKIN.value
    STATUS_URL = APIEndpoint.STATUS.value
    POINTS_URL = APIEndpoint.POINTS.value
    EXCHANGE_URL = APIEndpoint.EXCHANGE.value

    def __init__(self, domain: str, cookie_index: int = 0, verbose: bool = False):
        self.domain: str = domain
        self.cookie_index: int = cookie_index
        self.verbose: bool = verbose
        self.headers: Dict[str, str] = self._get_headers()
        self._device_ua_cache: Dict[str, str] = {}
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        # 网络抖动时自动重试（指数退避），避免误报失败
        retry_strategy = Retry(
            total=3,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST"),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def __del__(self):
        """关闭 session"""
        self.close()

    def close(self) -> None:
        """关闭 session"""
        if hasattr(self, "session"):
            try:
                self.session.close()
            except Exception as e:
                logger.error(f"{LogEmoji.ERROR} 关闭 session 时发生错误: {e}")

    def __enter__(self):
        """进入上下文管理器"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文管理器"""
        self.close()
        return False

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "origin": f"https://{self.domain}",
            "user-agent": PLATFORM_UA["Windows"],
        }

    def _log(self, level: str, emoji: str, message: str, force: bool = False) -> None:
        """统一日志输出方法"""

        prefix = f"{LogEmoji.COOKIE}[{self.cookie_index}] {LogEmoji.DOMAIN}[{self.domain}]"
        log_message = f"{prefix} {emoji} {message}"

        if force or self.verbose:
            if level == "info":
                logger.info(log_message)
            elif level == "warning":
                logger.warning(log_message)
            elif level == "error":
                logger.error(log_message)

    def _get_full_url(self, path: str) -> str:
        """获取完整 URL"""
        return f"https://{self.domain}{path}"

    def _make_request(self, url: str, method: str, data: Optional[Dict] = None, cookies: str = "", user_agent: Optional[str] = None) -> Optional[requests.Response]:
        """发送 HTTP 请求"""
        session_headers = self.headers.copy()
        if user_agent:
            session_headers["user-agent"] = user_agent
        session_headers["cookie"] = cookies

        try:
            if method.upper() == "POST":
                response = self.session.post(url, headers=session_headers, data=data, timeout=(60, 120))
            elif method.upper() == "GET":
                response = self.session.get(url, headers=session_headers, timeout=(60, 120))
            else:
                self._log("error", LogEmoji.ERROR, f"不支持的 HTTP 方法: {method}", force=True)
                return None

            if not response.ok:
                self._log("warning", LogEmoji.WARNING, f"向 {url} 发起的请求失败，状态码 {response.status_code}。响应内容: {response.text}", force=True)
                return None
            return response
        except requests.exceptions.RequestException as e:
            self._log("error", LogEmoji.ERROR, f"向 {url} 发起请求时发生网络错误: {e}", force=True)
            return None

    def _get_checkin_data(self) -> Dict[str, str]:
        """获取签到数据"""
        return {"token": self.domain}

    @log_method
    def checkin(self, cookies: str) -> Dict[str, Union[str, CheckinStatus]]:
        """执行签到，含设备平台自适应重试"""
        url = self._get_full_url(self.CHECKIN_URL)
        checkin_data = self._get_checkin_data()

        # 起始 UA 优先复用已学得的设备 UA，否则用会话默认 UA
        start_ua = self._device_ua_cache.get("_last") or self.headers.get("user-agent")

        raw = self._checkin_attempt(url, checkin_data, cookies, start_ua)

        # 设备不匹配(code 4)时按服务端 loginDevice 切换 UA 重试一次
        if raw is not None and raw.get("code") == 4 and raw.get("reason") == "device-mismatch":
            login_device = raw.get("loginDevice")
            recover_ua = self._device_ua_cache.get(login_device) or PLATFORM_UA.get(login_device)
            if recover_ua and recover_ua != start_ua:
                self._log("warning", LogEmoji.WARNING, f"设备平台不匹配 (loginDevice={login_device})，切换 UA 重试", force=True)
                raw = self._checkin_attempt(url, checkin_data, cookies, recover_ua)

        return self._parse_checkin(raw)

    def _checkin_attempt(self, url: str, data: Dict, cookies: str, user_agent: str) -> Optional[Dict]:
        """发起一次签到请求并返回解析后的响应体（失败返回 None）"""
        response = self._make_request(url, "POST", data, cookies, user_agent=user_agent)
        if not response:
            return None
        try:
            raw = response.json()
        except ValueError:
            self._log("error", LogEmoji.ERROR, "签到响应解析失败", force=True)
            return None

        # 缓存学得的设备 UA，供本次运行后续请求复用
        if raw.get("code") == 4 and raw.get("reason") == "device-mismatch":
            login_device = raw.get("loginDevice")
            if login_device in PLATFORM_UA:
                self._device_ua_cache[login_device] = PLATFORM_UA[login_device]
        elif raw.get("code") in (CheckinStatus.SUCCESS.value, CheckinStatus.REPEAT.value):
            self._device_ua_cache["_last"] = user_agent

        return raw

    def _parse_checkin(self, raw: Optional[Dict]) -> Dict[str, Union[str, bool, CheckinStatus]]:
        """解析签到响应为结果字典"""
        result: Dict[str, Union[str, bool, CheckinStatus]] = {
            "status": "签到失败",
            "points": "0",
            "message": "",
            "code": CheckinStatus.FAILURE,
            "permission_denied": False,
        }

        if not raw:
            result["message"] = "网络请求失败"
            return result

        code = raw.get("code", -2)
        # 不能用通用 FAILURE 枚举判断无权限，网络/设备等错误也使用该枚举。
        result["permission_denied"] = raw.get("code") == -2
        message = raw.get("message", "无消息字段")
        points = str(raw.get("points", 0))

        if code == CheckinStatus.SUCCESS.value:
            self._log("info", LogEmoji.SUCCESS, f"{{ code : {code}, points : {points}, message : {message} }}")
            result["code"] = CheckinStatus.SUCCESS
            result["status"] = "签到成功"
            result["points"] = points
            result["message"] = message
        elif code == CheckinStatus.REPEAT.value:
            self._log("info", LogEmoji.REPEAT, f"{{ code : {code}, message : {message} }}", force=True)
            result["code"] = CheckinStatus.REPEAT
            result["status"] = "重复签到"
            result["points"] = "0"
            result["message"] = message
        else:
            # 失败分支：按 code 细分诊断，便于快速定位根因
            if code == 4:
                reason = raw.get("reason")
                if reason == "device-mismatch":
                    login_device = raw.get("loginDevice") or "未知"
                    if login_device in PLATFORM_UA:
                        self._log("error", LogEmoji.ERROR, f"设备平台不匹配(loginDevice={login_device})，重试后仍失败，请确认登录设备平台", force=True)
                    else:
                        self._log("error", LogEmoji.ERROR, f"设备平台不匹配(loginDevice={login_device} 不在支持列表)，无法自动切换 UA；请提交相关截图到本项目 issue 以便作者更新设备列表", force=True)
                else:
                    self._log("error", LogEmoji.ERROR, f"服务端拒绝签到(code=4, reason={reason})，请检查账户风控状态", force=True)
            elif code == -2:
                self._log("error", LogEmoji.ERROR, f"无权限(code=-2)：Cookie 可能不适用于 {self.domain} 或已失效，请检查环境变量 GLADOS_COOKIES", force=True)
            else:
                self._log("error", LogEmoji.ERROR, f"未预期响应(code={code}, message={message})，请检查 GLaDOS 服务状态或 Cookie", force=True)
            result["code"] = CheckinStatus.FAILURE
            result["status"] = "签到失败"
            result["points"] = "0"
            result["message"] = message

        return result

    @log_method
    def get_status(self, cookies: str) -> Tuple[str, int]:
        """获取状态"""

        url = self._get_full_url(self.STATUS_URL)
        response = self._make_request(url, "GET", cookies=cookies)

        if response:
            data = response.json()
            code = data.get("code", -2)
            left_days = data.get("data", {}).get("leftDays", None)

            if left_days is not None:
                left_days_int = int(float(left_days))
                self._log("info", LogEmoji.SUCCESS, f"{{ code : {code}, leftDays : {left_days_int} 天}}")
                return f"{left_days_int} 天", code
            else:
                self._log("info", LogEmoji.FAIL, f"{{ code : {code}, leftDays : {left_days} 天}}")
                return "None 天", code
        else:
            self._log("warning", LogEmoji.WARNING, "获取状态失败")
            return "None 天", -2

    @log_method
    def get_points(self, cookies: str) -> Tuple[str, int]:
        """获取积分"""
        url = self._get_full_url(self.POINTS_URL)
        response = self._make_request(url, "GET", cookies=cookies)

        if response:
            data = response.json()
            code = data.get("code", -2)
            points = data.get("points", None)

            if points is not None:
                points_int = int(float(points))
                self._log("info", LogEmoji.SUCCESS, f"{{ code : {code}, points : {points_int} 积分}}")
                points_str = f"{points_int} 积分"
                points_num = points_int
                return points_str, points_num
            else:
                self._log("info", LogEmoji.FAIL, f"{{ code : {code}, points : {points} 积分}}")
                return "None 积分", 0
        else:
            self._log("warning", LogEmoji.WARNING, "获取积分失败")
            return "None 积分", 0

    @log_method
    def exchange(self, cookies: str, plan: str, required_points: int) -> str:
        """执行兑换"""
        url = self._get_full_url(self.EXCHANGE_URL)
        response = self._make_request(url, "POST", {"planType": plan}, cookies)

        if response:
            data = response.json()
            code = data.get("code", -2)
            message = data.get("message", "未知错误")

            if code == 0:
                self._log("info", LogEmoji.SUCCESS, f"{{ code : {code}, message : {message} }}")
                return f"兑换成功: {plan}"
            else:
                self._log("info", LogEmoji.FAIL, f"{{ code : {code}, message : {message} }}", force=True)
                return f"兑换失败: {message}"
        else:
            self._log("warning", LogEmoji.WARNING, "兑换失败", force=True)
            return "兑换失败"


@dataclass()
class CheckinResult:
    """签到结果"""

    cookie_index: int
    domain: str
    status: str = "签到失败"
    points: str = "0"
    days: str = "None"
    points_total: str = "None"
    exchange: str = "未兑换"
    code: CheckinStatus = CheckinStatus.FAILURE  # 0: 成功, 1: 重复, -2: 失败
    message: str = ""
    permission_denied: bool = False

    def to_dict(self) -> Dict[str, Union[str, CheckinStatus]]:
        result_dict = asdict(self)
        return result_dict


def display_metric(value, unit: str) -> str:
    """隐藏接口缺失值，统一单位，避免出现 None 天/None 积分。"""
    text = str(value).strip()
    if text.endswith(unit):
        text = text[:-len(unit)].strip()
    if text.lower() in ("", "none", "null"):
        return "未获取"
    return f"{text} {unit}"


def display_exchange(value: str) -> str:
    """翻译常见兑换提示，保留其他错误的具体原因。"""
    text = str(value or "").strip()
    insufficient = re.search(
        r"Not enough points\.\s*Need\s+(\d+(?:\.\d+)?),\s*have\s+(\d+(?:\.\d+)?)",
        text, re.IGNORECASE,
    )
    if insufficient:
        need, have = insufficient.groups()
        need, have = (n.rstrip("0").rstrip(".") if "." in n else n for n in (need, have))
        return f"积分不足，暂未兑换（当前 {have}，需要 {need}）"
    if text.lower() in ("兑换失败: no permission", "兑换失败: 没有权限"):
        return "无访问权限，无法兑换"
    if text == "未配置兑换计划，跳过自动兑换":
        return "未配置自动兑换"
    return text


def render_payload(payload: dict, line_sep: str = "\n") -> str:
    """按账号和站点分块展示；Server酱通过 line_sep 使用 Markdown 硬换行。"""
    blocks = []
    cross_site = []
    for r in payload.get("rows", []):
        account = r.get("cookie_index", r["index"])
        site = {"glados.cloud": "GLaDOS", "railgun.info": "Railgun"}.get(r["domain"], r["domain"])
        if r.get("cross_site"):
            cross_site.append(f"账号 {account} → {site}")
            continue
        status = "今日已签到" if r["status"] == "重复签到" else r["status"]
        lines = [f"{r['emoji']} {site} · 账号 {account} · {status}"]
        failed = r["status"] == "签到失败"
        if failed:
            message = r.get("message") or "原因未返回，请查看任务日志"
            if r.get("permission_denied") or message.lower() in ("no permission", "没有权限"):
                message = "无访问权限，请检查该站点 Cookie 是否有效"
            lines.append(f"原因：{message}")
        metrics = []
        if not failed and status != "今日已签到":
            points = display_metric(r.get("points"), "积分")
            metrics.append(f"本次 +{points}" if points != "未获取" else "本次积分未获取")
        for label, key, unit in (("剩余", "days", "天"), ("总积分", "points_total", "积分")):
            value = display_metric(r.get(key), unit)
            if not failed or value != "未获取":
                metrics.append(f"{label} {value}")
        if metrics:
            lines.append("｜".join(metrics))
        exchange = display_exchange(r.get("exchange", ""))
        if exchange and not r.get("permission_denied"):
            lines.append(f"兑换：{exchange}")
        blocks.append(line_sep.join(lines))
    if cross_site:
        blocks.append(f"ℹ️ 跨站无权限 {len(cross_site)} 项：{'；'.join(cross_site)}。同一账号已在其他站点签到，不计入签到失败。")
    note = payload.get("note")
    if note:
        blocks.append(note)
    return (line_sep * 2).join(blocks)


class PushBackend:
    """推送后端抽象基类（策略模式）"""

    name: str = "base"

    def send(self, title: str, payload: dict) -> bool:
        """发送推送，返回是否成功（由子类实现）"""
        raise NotImplementedError

    def _render(self, payload: dict) -> str:
        """将结构化结果渲染为本后端适用的文本（子类可重写行分隔方式）"""
        return render_payload(payload, "\n")


class PushDeerBackend(PushBackend):
    """PushDeer 后端（官方 pypushdeer 库）"""

    name = "PushDeer"

    def __init__(self, push_key: str):
        self.push_key = push_key

    def send(self, title: str, payload: dict) -> bool:
        try:
            PushDeer(pushkey=self.push_key).send_text(title, desp=self._render(payload))
            return True
        except Exception as e:
            logger.error(f"{LogEmoji.ERROR} [{self.name}] 推送失败: {e}")
            return False


class ServerChanBackend(PushBackend):
    """Server酱 后端（官方 serverchan_sdk）"""

    name = "Server酱"

    def __init__(self, send_key: str):
        self.send_key = send_key

    def _render(self, payload: dict) -> str:
        # Server酱 按 Markdown 渲染，单 \n 不换行；用行尾两空格+\n 做硬换行，避免段间空行
        return render_payload(payload, "  \n")

    def send(self, title: str, payload: dict) -> bool:
        # 延迟导入：未安装 SDK 时不阻断其他后端（如 PushDeer）
        try:
            from serverchan_sdk import sc_send
        except ImportError:
            logger.error(f"{LogEmoji.ERROR} [{self.name}] 推送失败: 未安装 serverchan_sdk，请先执行 pip install serverchan-sdk。")
            return False
        try:
            resp = sc_send(sendkey=self.send_key, title=title, desp=self._render(payload))
            if isinstance(resp, dict) and resp.get("code") == 0:
                return True
            logger.error(f"{LogEmoji.ERROR} [{self.name}] 推送失败: 接口返回 {resp}")
            return False
        except Exception as e:
            logger.error(f"{LogEmoji.ERROR} [{self.name}] 推送失败: {e}")
            return False


class WeComBackend(PushBackend):
    """企业微信群机器人 Webhook 后端。"""

    name = "企业微信"
    MAX_CONTENT_BYTES = 2048

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, title: str, payload: dict) -> bool:
        content = f"{title}\n\n{self._render(payload)}"
        encoded = content.encode("utf-8")
        if len(encoded) > self.MAX_CONTENT_BYTES:
            suffix = "\n…（内容已截断，完整结果见任务日志）"
            limit = self.MAX_CONTENT_BYTES - len(suffix.encode("utf-8"))
            content = encoded[:limit].decode("utf-8", "ignore") + suffix

        try:
            response = requests.post(
                self.webhook_url,
                json={"msgtype": "text", "text": {"content": content}},
                timeout=(10, 30),
            )
            response.raise_for_status()
            result = response.json()
            errcode = result.get("errcode") if isinstance(result, dict) else None
            if type(errcode) is int and errcode == 0:
                return True

            # 只记录数字错误码，不输出可能包含 Webhook 密钥的响应或异常详情。
            safe_code = errcode if type(errcode) is int else "未知"
            logger.error(f"{LogEmoji.ERROR} [{self.name}] 推送失败，errcode={safe_code}")
        except (requests.RequestException, ValueError) as exc:
            logger.error(f"{LogEmoji.ERROR} [{self.name}] 推送失败: {type(exc).__name__}")
        return False


class PushService:
    """推送服务：聚合多个后端，向全部已配置后端发送（都发）"""

    def __init__(self, config: Config):
        self.backends: List[PushBackend] = []
        if config:
            if getattr(config, "push_key", ""):
                self.backends.append(PushDeerBackend(config.push_key))
            if getattr(config, "serverchan_key", ""):
                self.backends.append(ServerChanBackend(config.serverchan_key))
            if getattr(config, "wecom_webhook_url", ""):
                self.backends.append(WeComBackend(config.wecom_webhook_url))

    def send(self, title: str, payload: dict) -> bool:
        """向所有已配置后端发送推送，只要有一个成功即视为成功"""
        if not self.backends:
            logger.info(f"{LogEmoji.WARNING} 未配置推送通道，跳过。")
            return False

        backend_names = "、".join(b.name for b in self.backends)
        logger.info(f"{LogEmoji.INFO} 已配置 {len(self.backends)} 个后端（{backend_names}），开始发送")
        results = [backend.send(title, payload) for backend in self.backends]
        if any(results):
            logger.info(f"{LogEmoji.SUCCESS} 发送完成：{sum(results)}/{len(results)} 个后端成功")
            return True
        logger.error(f"{LogEmoji.ERROR} 全部后端发送失败")
        return False


class Checker:
    """签到"""

    def __init__(self, config: Config):
        self.config = config
        self.results = []

    def _log(self, cookie_idx: int, domain: str, emoji: str, message: str, force: bool = False) -> None:
        """统一日志输出方法"""

        if self.config.verbose or force:
            logger.info(f"{LogEmoji.COOKIE}[{cookie_idx}] {LogEmoji.DOMAIN}[{domain}] {emoji} {message}")

    def checkin_all(self):
        """执行所有签到任务"""
        cookie_count = len(self.config.cookies_list)
        domain_count = len(self.config.DOMAINS)
        total_tasks = cookie_count * domain_count
        task_idx = 0

        logger.info(f"{LogEmoji.INFO} 共 {cookie_count} 个 Cookie, {domain_count} 个域名, 共 {total_tasks} 个任务")

        for cookie_idx, cookie in enumerate(self.config.cookies_list, 1):
            logger.info(f"{LogEmoji.START} ========== 开始处理 Cookie {cookie_idx} ==========")

            for domain in self.config.DOMAINS:
                task_idx += 1
                logger.info(f"{LogEmoji.INFO} ----- 任务 {task_idx}/{total_tasks}: {LogEmoji.COOKIE}[{cookie_idx}] on {LogEmoji.DOMAIN}[{domain}] -----")

                result = self._checkin_on_domain(cookie, cookie_idx, domain)
                self.results.append(result)

                result_message = f"结果: {result.status}"
                if result.code == CheckinStatus.SUCCESS:
                    if self.config.verbose:
                        result_message = f"结果: {result.status}, 获得 {result.points} 积分, 剩余 {result.days}, 总 {result.points_total}, {result.exchange}"
                    self._log(cookie_idx, domain, LogEmoji.SUCCESS, result_message, force=True)
                else:
                    self._log(cookie_idx, domain, LogEmoji.WARNING, result_message, force=True)

    def _checkin_on_domain(self, cookie: str, cookie_idx: int, domain: str) -> CheckinResult:
        result = CheckinResult(cookie_idx, domain)

        with API(domain, cookie_idx, verbose=self.config.verbose) as api:
            self._log(cookie_idx, domain, LogEmoji.STATUS, "查询剩余天数")
            days_str, status_code = api.get_status(cookie)
            result.days = days_str

            self._log(cookie_idx, domain, LogEmoji.CHECKIN, "执行签到")
            checkin_result = api.checkin(cookie)
            result.status = checkin_result["status"]
            result.code = checkin_result.get("code", CheckinStatus.FAILURE)
            result.points = checkin_result.get("points", "0")
            result.message = checkin_result.get("message", "")
            result.permission_denied = checkin_result.get("permission_denied", False)

            self._log(cookie_idx, domain, LogEmoji.POINTS, "查询总积分")
            points_str, points_num = api.get_points(cookie)
            result.points_total = points_str

            if self.config.exchange_plan in self.config.EXCHANGE_PLANS:
                required_points = self.config.EXCHANGE_PLANS[self.config.exchange_plan]
                self._log(
                    cookie_idx,
                    domain,
                    LogEmoji.EXCHANGE,
                    f"开始兑换 {self.config.exchange_plan} (需要 {required_points} 积分)",
                )
                result.exchange = api.exchange(cookie, self.config.exchange_plan, required_points)
            else:
                result.exchange = "未配置兑换计划，跳过自动兑换"
                self._log(cookie_idx, domain, LogEmoji.INFO, "未配置兑换计划，跳过自动兑换")

        return result

    def get_results(self) -> List[Dict[str, str]]:
        """获取所有结果"""
        return [result.to_dict() for result in self.results]

    def format_results(self) -> dict:
        """格式化结果为结构化 payload（表现交给各推送后端/日志各自渲染）"""
        results = self.get_results()

        success_count = sum(1 for r in results if r["code"] == CheckinStatus.SUCCESS)
        repeat_count = sum(1 for r in results if r["code"] == CheckinStatus.REPEAT)
        raw_fail_count = sum(1 for r in results if r["code"] == CheckinStatus.FAILURE)
        working_sites = {}
        for r in results:
            if r["code"] in (CheckinStatus.SUCCESS, CheckinStatus.REPEAT):
                working_sites.setdefault(r["cookie_index"], set()).add(r["domain"])

        status_emoji_map = {
            CheckinStatus.SUCCESS: LogEmoji.SUCCESS,
            CheckinStatus.REPEAT: LogEmoji.REPEAT,
            CheckinStatus.FAILURE: LogEmoji.ERROR,
        }
        rows = []
        for i, res in enumerate(results, 1):
            cross_site = (
                res["code"] == CheckinStatus.FAILURE and res["permission_denied"]
                and bool(working_sites.get(res["cookie_index"], set()) - {res["domain"]})
            )
            rows.append({
                "index": i,
                "cookie_index": res["cookie_index"],
                "emoji": status_emoji_map.get(res["code"], LogEmoji.ERROR),
                "status": res["status"],
                "domain": res["domain"],
                "points": res["points"],
                "days": res["days"],
                "points_total": res["points_total"],
                "exchange": res["exchange"],
                "message": res["message"],
                "permission_denied": res["permission_denied"],
                "cross_site": cross_site,
            })

        cross_site_count = sum(1 for r in rows if r["cross_site"])
        fail_count = raw_fail_count - cross_site_count
        title = f"GLaDOS / Railgun 签到 · 成功 {success_count} · 已签到 {repeat_count} · 失败 {fail_count}"
        if cross_site_count:
            title += f" · 跨站无权限 {cross_site_count}"
        return {
            "title": title,
            "rows": rows,
            "success": success_count,
            "fail": fail_count,
            "repeat": repeat_count,
            "cross_site": cross_site_count,
            "raw_fail": raw_fail_count,
        }


logger = init_logger()


def main():
    """主函数"""
    exit_code = 0
    try:
        logger.info(f"{LogEmoji.START} 步骤 1: 加载配置")
        config = Config()

        if not config.cookies_list:
            logger.error(f"{LogEmoji.ERROR} 未找到有效的 Cookie, 退出程序。")
            payload = {"title": "# 未找到 cookies!", "rows": []}
        else:
            logger.info(f"{LogEmoji.START} 步骤 2: 执行签到")
            checker = Checker(config)
            checker.checkin_all()

            logger.info(f"{LogEmoji.START} 步骤 3: 格式化结果")
            payload = checker.format_results()
            logger.info(f"\n{LogEmoji.END} ========== 签到总结 ==========\n{payload['title']}\n{render_payload(payload)}")

    except Exception as e:
        logger.error(f"{LogEmoji.ERROR} 主程序执行过程中发生未预期的错误: {e}")
        payload = {"title": "# 脚本执行出错", "rows": [], "note": str(e)}
        exit_code = 1

    logger.info(f"{LogEmoji.START} 步骤 4: 发送推送")
    push_service = PushService(config if "config" in locals() else None)
    push_service.send(payload["title"], payload)
    logger.info(f"{LogEmoji.END} 签到完成")

    if exit_code != 0:
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
