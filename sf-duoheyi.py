#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sf-duoheyi v2.0.0 (Four-Way Merged Edition)

Merged and deduplicated from the following four plaintext scripts (merge date 2026-10-23):
[Core] ShuiLiZe/QingLong "顺丰速运.py" v1.1.1 (2026-07-26)
-- Daily points tasks, dual-platform sign-in, Member Day, World Cup, CK-expiry detection, proxy system
[Same lineage] Qcby/QcbyScript "RegularScript/顺丰速运.py" v1.2.0 (2026-07-07)
-- Multi-separator account parsing, per-account exception isolation fallback
[Daily] smallfawn/QLScriptPublic "daily/sfsy.py" v1.3.0 (2026-04-09)
-- Older daily-task implementation on the same APIs (kept as reference only, not re-implemented)
[Sign-in] agluo/ql-script-hub "SFSU_checkin.py" (2025-11-21, derived from faintout/Xx1aoy1)
-- Full Honey Harvest API set, Member Day hourly red packets, extra Member Day skip types

Features:
1. Daily sign-in: V2 dual-platform sign-in (App + Mini Program) + legacy sign-in + claiming pending App gift packs
2. Daily points tasks: full task list across 8 channelTypes, per-task isolated execution, points claiming, lifestyle-privilege benefits
3. Honey Harvest (festival/seasonal event slot): task list, honey collection, adventure game, container expansion, coupon claiming
4. Member Day (auto start/stop on the 26th-28th of each month): tasks, rewards, lottery, red-packet merging and withdrawal, hourly red packets
5. World Cup event (2026.07.02-07.20, expired, off by default): kept as a sample festival-event framework

Environment variables:
sfsyUrl [Required] Account CK or login URL; multiple accounts separated by &, English comma, Chinese comma, or newline
Single account format: sessionId=xxx;_login_mobile_=xxx;_login_user_id_=xxx[#proxy]
How to capture (manual packet capture only; never use any third-party "scan-to-get-CK" website):
Open the SF Express Mini Program in WeChat or the App, use a packet-capture tool to find requests to mcs-mimp-web.sf-express.com,
and concatenate sessionId / _login_mobile_ / _login_user_id_ from the request Cookie;
or capture one of these official share links as the login URL:
https://mcs-mimp-web.sf-express.com/mcs-mimp/share/weChat/shareGiftReceiveRedirect
https://mcs-mimp-web.sf-express.com/mcs-mimp/share/app/shareRedirect
SF_DAILY Daily sign-in + points tasks switch, 1 = on (default) / 0 = off
SF_HONEY Honey Harvest switch, 1 = on (default; auto-skipped when the server has no such event) / 0 = off
SF_MEMBER_DAY Member Day switch, 1 = on (default, and only runs on the 26th-28th of each month) / 0 = off
SF_WORLD_CUP World Cup switch, default 0 (event expired); even when set to 1 it only runs inside the event window
SF_WORLD_CUP_BET World Cup random betting (spends coins), default 0
SF_WC_ASSIST_ID World Cup assist target userId (optional; can be overridden via environment variable)
SF_WC_CITY_CODE World Cup daily-gift city code, default 021
SF_CONCURRENT Concurrency 1-20, default 1 (also honors the smallfawn-style SFBF variable)
SFSY_PUSH Push switch, 1 = on (default) / 0 = off; pushes via QingLong's built-in notify.py, otherwise prints only
SF_PROXY_API_URL Dynamic proxy extraction URL (optional, bring your own; the script bundles no proxy service)
SF_PROXY_TYPE Proxy type http / socks5, default socks5

Security notes:
- All requests go only to official *.sf-express.com domains; signatures are computed locally with MD5
- No remote code/dependencies are downloaded, no eval/exec, account tokens are never sent to any third party
- The third-party "scan-to-get-CK" websites recommended in the original scripts' comments have all been removed; capture packets manually

Suggested QingLong schedule (cron): 11 6,18 * * *
For extra Member Day runs on the 26th-28th, add another one: 30 9,14,20 26-28 * *
"""

import hashlib
import json
import os
import random
import re
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import unquote, urlparse, parse_qs, quote as url_encode
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


def env_flag(name: str, default: str = "1") -> bool:
    """Read a boolean environment-variable switch"""
    return os.getenv(name, default).strip() not in ("0", "false", "False", "")


# ==================== Push notifications (optional; unified wrapper for QingLong notify / SendNotify styles) ====================
PUSH_SWITCH = os.getenv("SFSY_PUSH", "1")


def _load_notify():
    """Prefer QingLong's built-in notify.py, then SendNotify.py; return None (log only) if neither exists"""
    try:
        from notify import send as _send
        print("✅ QingLong notify push module loaded")
        return _send
    except ImportError:
        pass
    try:
        from SendNotify import send_push_notification as _send2

        def _wrap(title, content):
            _send2(title, content)

        print("✅ SendNotify push module loaded")
        return _wrap
    except ImportError:
        pass
    print("⚠️ No notification module found, push unavailable (can be ignored for local runs)")
    return None


notify_send = _load_notify()

# ==================== Configuration ====================
# Feature switches (environment variables take precedence; defaults below apply when unset)
ENABLE_DAILY_TASK = env_flag("SF_DAILY", "1")              # Daily sign-in + points tasks
ENABLE_HONEY = env_flag("SF_HONEY", "1")                   # Honey Harvest (from the agluo version)
ENABLE_MEMBER_DAY = env_flag("SF_MEMBER_DAY", "1")         # Member Day event (26th-28th of each month)
ENABLE_WORLD_CUP = env_flag("SF_WORLD_CUP", "0")           # World Cup event [expired, off by default]
ENABLE_WORLD_CUP_BET = env_flag("SF_WORLD_CUP_BET", "0")   # World Cup random betting; enabling it spends coins
WORLD_CUP_BET_COIN = 10                                    # Coins per bet; server minimum is 10
# World Cup assist target userId (default below; overridable via SF_WC_ASSIST_ID)
WORLD_CUP_ASSIST_ID = os.getenv('SF_WC_ASSIST_ID', '03E8BC71394F4B05B254D3F0B7D50351')
try:
    CONCURRENT_NUM = int(os.getenv("SF_CONCURRENT", os.getenv("SFBF", "1")))
except ValueError:
    CONCURRENT_NUM = 1
CONCURRENT_NUM = max(1, min(20, CONCURRENT_NUM))           # Concurrency (1~20)

TOKEN = 'wwesldfs29aniversaryvdld29'
inviteId: List[str] = []
INVITE_LOCK = threading.Lock()
SYS_CODE = 'MCS-MIMP-CORE'

# Daily-task skip list (union; based on the core 2026-07 version, including same-named entries from smallfawn/agluo)
DAILY_SKIP_TASKS = [
    '用行业模板寄件下单', '用积分兑任意礼品', '参与积分活动',
    '每月累计寄件', '完成每月任务', '去使用AI寄件',
    # The tasks below require a real shipment or profile setup in the Mini Program; the script does not fake them (from core v1.1.1)
    '寄一单国际件', '去新增一个收件偏好', '设置你的顺丰ID',
    '去使用AI小丰寄件',
]

# Member Day skip task types (union: core + OPEN_SUPER_CARD added by the agluo version)
MEMBER_DAY_SKIP_TASK_TYPES = [
    'SEND_SUCCESS', 'INVITEFRIENDS_PARTAKE_ACTIVITY', 'OPEN_SVIP',
    'OPEN_NEW_EXPRESS_CARD', 'OPEN_FAMILY_CARD', 'CHARGE_NEW_EXPRESS_CARD',
    'INTEGRAL_EXCHANGE',
    'OPEN_SUPER_CARD',  # Buy supreme membership (from the agluo version, 2025-11)
]

# World Cup event parameters (from core v1.1.1; the event has ended, framework only)
WORLD_CUP_ACTIVITY_CODE = 'WORLD_CUP'
WORLD_CUP_CHANNEL = '26sjbapp'
WORLD_CUP_PLATFORM = 'SFAPP'
WORLD_CUP_CITY_CODE = os.getenv('SF_WC_CITY_CODE', '021')
WORLD_CUP_START = datetime(2026, 7, 2).date()
WORLD_CUP_END = datetime(2026, 7, 20).date()
WORLD_CUP_ENABLE_GAME = True
WORLD_CUP_ENABLE_SETTLE = True
# No fixed taskCodes of unknown origin; only codes returned live by the current task list are used
WORLD_CUP_SAFE_TASK_NAMES = {
    '浏览积分商城',
    '去看看互寄8折权益',
}
CK_INVALID_KEYWORDS = (
    '未登录', '请登录', '请先登录', '登录失效', '登录已失效',
    '登录过期', '会话失效', 'session失效', 'sessionid失效',
    'sessionid已失效', 'token失效', '重新登录', 'not_login',
    'unauthorized', '用户信息失效',
)

# Proxy config (optional; proxies are user-supplied via env vars / account suffix; none built in)
PROXY_API_URL = os.getenv("SF_PROXY_API_URL", "")
PROXY_TYPE = os.getenv("SF_PROXY_TYPE", "socks5")
PROXY_TIMEOUT = 15
MAX_PROXY_RETRIES = 5
REQUEST_RETRY_COUNT = 3
PROXY_RETRY_DELAY = 2
PROXY_CONTEXT = {'last_fetch_ts': 0}
PROXY_LOCK = threading.Lock()
print_lock = Lock()
# =================================================


def world_cup_active(current_date=None) -> bool:
    current_date = current_date or datetime.now().date()
    return WORLD_CUP_START <= current_date <= WORLD_CUP_END


def is_safe_world_cup_task(task: Dict) -> bool:
    task_name = str(task.get('taskName') or '')
    task_code = str(task.get('taskCode') or '')
    return bool(task_code and task_name in WORLD_CUP_SAFE_TASK_NAMES)


# Account parsing: from the Qcby version (supports &, English/Chinese commas, and newlines as separators)
def parse_accounts(raw: str) -> List[str]:
    return [item.strip() for item in re.split(r"[&，,\r\n]+", str(raw or "")) if item.strip()]


def register_invite_id(user_id: str):
    """Register a logged-in account's userId so Member Day / Honey invite-reward flows can pick one across accounts.

    Note: in all four source scripts inviteId was always empty (the invite branch never actually fired);
    the merged version fills it with logged-in accounts' userIds; APIs and parameters are identical to the sources.
    """
    if not user_id:
        return
    with INVITE_LOCK:
        if user_id not in inviteId:
            inviteId.append(user_id)


def pick_invite_id(self_user_id: str) -> str:
    with INVITE_LOCK:
        available = [inv for inv in inviteId if inv != self_user_id]
    return random.choice(available) if available else ''


class Logger:
    def __init__(self):
        self.messages: List[str] = []
        self.lock = Lock()

    def _log(self, icon: str, msg: str):
        line = f"{icon} [{datetime.now().strftime('%H:%M:%S')}] {msg}"
        with print_lock:
            print(line)
        with self.lock:
            self.messages.append(line)

    def info(self, msg): self._log('📝', msg)
    def success(self, msg): self._log('✅', msg)
    def warning(self, msg): self._log('⚠️', msg)
    def error(self, msg): self._log('❌', msg)
    def task(self, msg): self._log('🎯', msg)
    def medal(self, msg): self._log('🏅', msg)
    def points(self, pts, prefix="Current points"): self._log('💰', f"{prefix}: [{pts}]")


# ==================== Proxy manager ====================
def _log_global(msg: str):
    t = datetime.now().strftime("%H:%M:%S")
    print(f"[{t}] {msg}", flush=True)


def _build_proxy_url(ip: str, port: int, username: str = "", password: str = "") -> str:
    """Build a standard proxy URL with credentials URL-encoded automatically"""
    if username and password:
        safe_user = url_encode(username, safe='')
        safe_pass = url_encode(password, safe='')
        return f"{PROXY_TYPE}://{safe_user}:{safe_pass}@{ip}:{port}"
    return f"{PROXY_TYPE}://{ip}:{port}"


def parse_proxy_response(text: str) -> Optional[Tuple[str, str]]:
    """Parse a proxy API response into (proxy URL, display string); supports JSON and plain text"""
    text = text.strip()
    try:
        data = json.loads(text)
        def extract(d: dict) -> Optional[Tuple[str, str]]:
            if 'ip' not in d or 'port' not in d:
                return None
            ip, port = str(d['ip']), int(d['port'])
            user = str(d.get('account', d.get('user', '')) or '')
            pwd = str(d.get('password', d.get('pass', '')) or '')
            url = _build_proxy_url(ip, port, user, pwd)
            display = f"{ip}:{port}" + (" (auth)" if user else "")
            return url, display
        if isinstance(data, dict):
            if 'ip' in data and 'port' in data:
                return extract(data)
            if 'data' in data:
                pd = data['data']
                if isinstance(pd, dict) and 'list' in pd:
                    pl = pd['list']
                    if isinstance(pl, list) and pl:
                        return extract(pl[0])
                if isinstance(pd, list) and pd:
                    return extract(pd[0])
                if isinstance(pd, dict) and 'ip' in pd:
                    return extract(pd)
            if 'result' in data:
                r = data['result']
                if isinstance(r, dict) and 'ip' in r:
                    return extract(r)
    except (json.JSONDecodeError, ValueError):
        pass
    if ':' in text:
        segments = text.split()
        addr_parts = segments[0].split(':')
        if len(addr_parts) == 2 and addr_parts[1].isdigit():
            ip, port = addr_parts[0], int(addr_parts[1])
            user = segments[1] if len(segments) > 1 else ""
            pwd = segments[2] if len(segments) > 2 else ""
            url = _build_proxy_url(ip, port, user, pwd)
            display = f"{ip}:{port}" + (" (auth)" if user else "")
            return url, display
    return None


def get_api_proxy() -> Optional[Tuple[Dict[str, str], str]]:
    """Fetch a proxy from the API; returns (proxy dict, display string)"""
    if not PROXY_API_URL:
        return None
    with PROXY_LOCK:
        elapsed = time.time() - PROXY_CONTEXT['last_fetch_ts']
        if elapsed < 3:
            time.sleep(3 - elapsed)
        for i in range(MAX_PROXY_RETRIES):
            try:
                resp = requests.get(PROXY_API_URL, timeout=10)
                if resp.status_code == 200:
                    result = parse_proxy_response(resp.text)
                    if result:
                        proxy_url, display = result
                        PROXY_CONTEXT['last_fetch_ts'] = time.time()
                        _log_global(f"✅ Proxy fetched: {display}")
                        return {'http': proxy_url, 'https': proxy_url}, display
                _log_global(f"⚠️ Attempt {i+1}: invalid proxy format")
            except Exception as e:
                _log_global(f"⚠️ Attempt {i+1}: proxy fetch error: {str(e)[:80]}")
            if i < MAX_PROXY_RETRIES - 1:
                time.sleep(PROXY_RETRY_DELAY)
        PROXY_CONTEXT['last_fetch_ts'] = time.time()
        _log_global(f"❌ Proxy fetch failed after {MAX_PROXY_RETRIES} retries")
        return None


def parse_fixed_proxy(fixed_proxy: str) -> Optional[Dict[str, str]]:
    """Parse a fixed proxy string into a proxy dict"""
    if not fixed_proxy:
        return None
    if '://' not in fixed_proxy:
        fixed_proxy = f'{PROXY_TYPE}://{fixed_proxy}'
    return {'http': fixed_proxy, 'https': fixed_proxy}


# ==================== HTTP client ====================
class SFHttpClient:
    def __init__(self, fixed_proxy: str = ""):
        self.session = requests.Session()
        self.session.verify = False
        self.proxy_display = 'No proxy'
        self.ck_invalid = False
        self.ck_invalid_message = ''
        self._setup_proxy(fixed_proxy)
        self.headers = {
            'Host': 'mcs-mimp-web.sf-express.com',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf254173b) XWEB/19027',
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json',
            'channel': 'xcxpart',
            'platform': 'MINI_PROGRAM',
            'accept-language': 'zh-CN,zh;q=0.9',
        }

    def _setup_proxy(self, fixed_proxy: str):
        if fixed_proxy:
            proxy_dict = parse_fixed_proxy(fixed_proxy)
            if proxy_dict:
                self.session.proxies = proxy_dict
                display = fixed_proxy
                if '@' in fixed_proxy:
                    parts = fixed_proxy.split('@')
                    display = f"***@{parts[-1]}"
                self.proxy_display = display
                return
        result = get_api_proxy()
        if result:
            self.session.proxies = result[0]
            self.proxy_display = result[1]

    def _generate_sign(self) -> Dict[str, str]:
        timestamp = str(int(round(time.time() * 1000)))
        data = f'token={TOKEN}&timestamp={timestamp}&sysCode={SYS_CODE}'
        signature = hashlib.md5(data.encode()).hexdigest()
        return {'syscode': SYS_CODE, 'timestamp': timestamp, 'signature': signature}

    def _check_ck_invalid(self, result: Dict):
        if not isinstance(result, dict) or result.get('success') is True:
            return
        text = ' '.join(str(result.get(k, '')) for k in ('errorMessage', 'message', 'msg', 'error', 'code', 'errorCode')).lower()
        if any(keyword in text for keyword in CK_INVALID_KEYWORDS):
            self.ck_invalid = True
            self.ck_invalid_message = result.get('errorMessage') or result.get('message') or result.get('msg') or 'CK expired'

    def request(self, url: str, data: Optional[Dict] = None, extra_headers: Optional[Dict[str, str]] = None) -> Optional[Dict]:
        proxy_retry_count = 0
        retry_count = 0
        while proxy_retry_count < MAX_PROXY_RETRIES:
            sign_data = self._generate_sign()
            headers = {**self.headers, **sign_data}
            if extra_headers:
                headers.update(extra_headers)
            try:
                resp = self.session.post(url, headers=headers, json=data or {}, timeout=PROXY_TIMEOUT)
                resp.raise_for_status()
                try:
                    result = resp.json()
                    if result is not None:
                        self._check_ck_invalid(result)
                        return result
                except (json.JSONDecodeError, ValueError):
                    pass
                retry_count += 1
                if retry_count < REQUEST_RETRY_COUNT:
                    time.sleep(2)
                    continue
                return None
            except requests.exceptions.RequestException as e:
                retry_count += 1
                error_str = str(e)
                if 'ProxyError' in error_str or 'SSLError' in error_str or 'ConnectionError' in error_str:
                    proxy_retry_count += 1
                    if proxy_retry_count < MAX_PROXY_RETRIES:
                        result = get_api_proxy()
                        if result:
                            self.session.proxies = result[0]
                            self.proxy_display = result[1]
                        retry_count = 0
                    time.sleep(2)
                    continue
                if retry_count < REQUEST_RETRY_COUNT:
                    time.sleep(2)
                    continue
                return None
            except Exception:
                return None
        return None

    def request_app(self, url: str, data: Optional[Dict] = None) -> Optional[Dict]:
        """App-platform request"""
        original = self.headers.get('platform', 'MINI_PROGRAM')
        self.headers['platform'] = 'SFAPP'
        try:
            return self.request(url, data)
        finally:
            self.headers['platform'] = original

    def login(self, url: str) -> Tuple[bool, str, str]:
        try:
            decoded = unquote(url)
            if decoded.startswith('sessionId=') or '_login_mobile_=' in decoded:
                cookie_dict = {}
                for item in decoded.split(';'):
                    item = item.strip()
                    if '=' in item:
                        k, v = item.split('=', 1)
                        cookie_dict[k] = v
                for k, v in cookie_dict.items():
                    self.session.cookies.set(k, v, domain='mcs-mimp-web.sf-express.com')
                user_id = cookie_dict.get('_login_user_id_', '')
                phone = cookie_dict.get('_login_mobile_', '')
                return (True, user_id, phone) if phone else (False, '', '')
            else:
                self.session.get(decoded, headers=self.headers, timeout=PROXY_TIMEOUT)
                cookies = self.session.cookies.get_dict()
                user_id = cookies.get('_login_user_id_', '')
                phone = cookies.get('_login_mobile_', '')
                return (True, user_id, phone) if phone else (False, '', '')
        except Exception:
            return False, '', ''


# ==================== Daily points task executor (from core v1.1.1, latest 2026-07 implementation) ====================
# Note: the smallfawn and agluo versions use the same daily-task APIs (queryPointTaskAndSignFromES /
# finishTask / fetchIntegral / lifestyle privileges); their implementations are older, so only the core one is kept.
class DailyTaskExecutor:
    def __init__(self, http: SFHttpClient, logger: Logger, user_id: str):
        self.http = http
        self.logger = logger
        self.user_id = user_id
        self.total_points = 0
        self.taskId = ""
        self.taskCode = ""
        self.strategyId = 0
        self.title = ""
        self.point = 0

    @staticmethod
    def generate_device_id() -> str:
        result = ''
        for char in 'xxxxxxxx-xxxx-xxxx':
            result += random.choice('abcdef0123456789') if char == 'x' else char
        return result

    def _extract_task_id_from_url(self, url: str) -> str:
        if not url:
            return ''
        try:
            parsed = urlparse(str(url))
            params = parse_qs(parsed.query)
            if '_ug_view_param' in params:
                ug_params = json.loads(unquote(params['_ug_view_param'][0]))
                for key in ('taskId', 'taskCode', 'task_id'):
                    if ug_params.get(key):
                        return str(ug_params[key])
        except Exception:
            pass
        match = re.search(
            r"[\"'](?:taskId|taskCode|task_id)[\"']\s*:\s*[\"']([^\"']+)[\"']",
            unquote(str(url)),
        )
        if match:
            return match.group(1)
        return ''

    def _resolve_task_code(self, task: Dict) -> str:
        code = str(task.get('taskCode') or '').strip()
        if code:
            return code
        for key in ('buttonRedirect', 'taskJumpAddress', 'redirectUrl'):
            extracted = self._extract_task_id_from_url(task.get(key, ''))
            if extracted:
                return extracted
        return ''

    def _set_task_attrs(self, task: Dict):
        self.taskId = str(task.get('taskId') or '')
        self.taskCode = self._resolve_task_code(task)
        try:
            self.strategyId = int(task.get('strategyId') or 0)
        except (TypeError, ValueError):
            self.strategyId = 0
        self.title = str(task.get('title') or 'Unknown task')
        try:
            self.point = int(task.get('point') or task.get('awardIntegral') or 0)
        except (TypeError, ValueError):
            self.point = 0

    def app_sign_in(self) -> Tuple[bool, str]:
        url = 'https://mcs-mimp-web.sf-express.com/mcs-mimp/commonPost/~memberNonactivity~integralTaskSignPlusService~getUnFetchPointAndDiscount'
        resp = self.http.request_app(url, {})
        if resp and resp.get('success'):
            obj = resp.get('obj', [])
            if obj and isinstance(obj, list) and len(obj) > 0:
                names = [item.get('packetName', 'Unknown') for item in obj]
                self.logger.success(f'[App sign-in] Received [{", ".join(names)}]')
            else:
                self.logger.info('[App sign-in] Already signed in today')
            return True, ''
        error_msg = resp.get('errorMessage', 'Unknown error') if resp else 'Request failed'
        if '没有待领取礼包' in error_msg:
            time.sleep(1)
            resp2 = self.http.request_app(url, {})
            if resp2 and resp2.get('success'):
                obj2 = resp2.get('obj', [])
                if obj2 and isinstance(obj2, list) and len(obj2) > 0:
                    names = [item.get('packetName', 'Unknown') for item in obj2]
                    self.logger.success(f'[App sign-in] Second claim [{", ".join(names)}]')
                else:
                    self.logger.info('[App sign-in] Already signed in today, no pending rewards')
                return True, ''
            self.logger.info('[App sign-in] Already signed in today')
            return True, ''
        self.logger.error(f'[App sign-in] Failed: {error_msg}')
        return False, error_msg

    def sign_in(self) -> Tuple[bool, str]:
        url = 'https://mcs-mimp-web.sf-express.com/mcs-mimp/commonPost/~memberNonactivity~integralTaskSignPlusService~automaticSignFetchPackage'
        resp = self.http.request(url, {"comeFrom": "vioin", "channelFrom": "WEIXIN"})
        if resp and resp.get('success'):
            obj = resp.get('obj', {})
            count_day = obj.get('countDay', 0)
            packets = obj.get('integralTaskSignPackageVOList', [])
            if packets:
                self.logger.success(f'Sign-in succeeded, received [{packets[0].get("packetName", "Unknown")}], {count_day + 1} days in total')
            else:
                self.logger.info(f'Already signed in today, {count_day + 1} days in total')
            return True, ''
        error_msg = resp.get('errorMessage', 'Unknown error') if resp else 'Request failed'
        self.logger.error(f'Sign-in failed: {error_msg}')
        return False, error_msg

    def _format_sign_v2_award(self, obj: Any) -> str:
        if not isinstance(obj, dict):
            return ''
        products = obj.get('award', {}).get('productDTOList', [])
        if isinstance(products, list) and products:
            names = []
            for item in products:
                if not isinstance(item, dict):
                    continue
                name = item.get('productName') or item.get('couponName')
                if name:
                    amount = item.get('amount', 1)
                    names.append(f'{name}x{amount}')
            if names:
                return ', '.join(names)
        award = obj.get('award')
        if isinstance(award, dict):
            return award.get('giftBagName') or award.get('giftBagDesc') or ''
        return obj.get('packetName') or obj.get('giftBagName') or ''

    def _sign_v2(self, platform_type: str) -> bool:
        url = 'https://mcs-mimp-web.sf-express.com/mcs-mimp/commonPost/~memberNonactivity~integralSignV2Service~sign'
        if platform_type == 'SFAPP':
            name = 'APP'
            headers = {
                'User-Agent': 'Mozilla/5.0 (Linux; Android 12; M2011K2C Build/SKQ1.211006.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/144.0.7559.132 Mobile Safari/537.36 mediaCode=SFEXPRESSAPP-Android-ML',
                'channel': 'doudiappwd',
                'platform': 'SFAPP',
                'deviceid': self.generate_device_id(),
            }
        else:
            name = 'Mini Program'
            headers = {
                'User-Agent': 'Mozilla/5.0 (Linux; Android 12; M2011K2C Build/SKQ1.211006.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/146.0.7680.177 Mobile Safari/537.36 XWEB/1460075 MMWEBSDK/20250804 MMWEBID/4850 MicroMessenger/8.0.63.2920(0x28003FA6) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64 miniProgram/wxd4185d00bf7e08ac',
                'channel': 'wxwddoudi',
                'platform': 'MINI_PROGRAM',
            }
        resp = self.http.request(url, {}, headers)
        if resp and resp.get('success'):
            award_text = self._format_sign_v2_award(resp.get('obj'))
            if award_text:
                self.logger.success(f'[{name} sign-in] Succeeded, received [{award_text}]')
            else:
                self.logger.success(f'[{name} sign-in] Succeeded')
            return True
        error_msg = resp.get('errorMessage', 'Unknown error') if resp else 'Request failed'
        if '今日已签到' in error_msg:
            self.logger.info(f'[{name} sign-in] Already signed in today')
            return True
        self.logger.error(f'[{name} sign-in] Failed: {error_msg}')
        return False

    def dual_sign_in(self) -> bool:
        app_ok = self._sign_v2('SFAPP')
        time.sleep(1)
        mini_ok = self._sign_v2('MINI_PROGRAM')
        return app_ok or mini_ok

    def query_balance(self):
        """Current points balance via a single-channel task-list query.

        Channel '1' responses carry totalPoint; one request only, so a
        per-task measurement stays cheap. Returns int or None.
        """
        url = 'https://mcs-mimp-web.sf-express.com/mcs-mimp/commonPost/~memberNonactivity~integralTaskStrategyService~queryPointTaskAndSignFromES'
        try:
            resp = self.http.request(url, {'channelType': '1', 'deviceId': self.generate_device_id()})
            if resp and resp.get('success') and resp.get('obj'):
                return int(resp['obj'].get('totalPoint') or 0)
        except (TypeError, ValueError):
            pass
        return None

    def get_task_list(self) -> List[Dict]:
        url = 'https://mcs-mimp-web.sf-express.com/mcs-mimp/commonPost/~memberNonactivity~integralTaskStrategyService~queryPointTaskAndSignFromES'
        all_tasks = []
        seen = set()
        for ct in ['1', '2', '3', '4', '01', '02', '03', '04']:
            data = {'channelType': ct, 'deviceId': self.generate_device_id()}
            resp = self.http.request(url, data)
            if resp and resp.get('success') and resp.get('obj'):
                obj = resp['obj'] or {}
                if ct in ('1', '01') or not self.total_points:
                    self.total_points = int(obj.get('totalPoint', self.total_points) or self.total_points or 0)
                task_items = obj.get('taskTitleLevels') or obj.get('ESobj') or []
                if not isinstance(task_items, list):
                    continue
                for task in task_items:
                    if not isinstance(task, dict):
                        continue
                    task = dict(task)
                    tc = self._resolve_task_code(task)
                    if tc:
                        task['taskCode'] = tc
                    key = tc or f"{task.get('taskId', '')}|{task.get('title', '')}"
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    all_tasks.append(task)
        return all_tasks

    def execute_task(self) -> bool:
        url = 'https://mcs-mimp-web.sf-express.com/mcs-mimp/commonRoutePost/memberEs/taskRecord/finishTask'
        resp = self.http.request(url, {'taskCode': self.taskCode})
        return bool(resp and resp.get('success'))

    def receive_task_reward(self) -> bool:
        url = 'https://mcs-mimp-web.sf-express.com/mcs-mimp/commonPost/~memberNonactivity~integralTaskStrategyService~fetchIntegral'
        data = {
            "strategyId": self.strategyId, "taskId": self.taskId,
            "taskCode": self.taskCode, "deviceId": self.generate_device_id()
        }
        resp = self.http.request(url, data)
        if resp and resp.get('success'):
            self.logger.success(f'Reward claimed: {self.title}')
            return True
        return False

    def get_welfare_list(self) -> List[Dict]:
        url = 'https://mcs-mimp-web.sf-express.com/mcs-mimp/commonPost/~memberGoods~mallGoodsLifeService~list'
        data = {"memGrade": 3, "categoryCode": "SHTQ", "showCode": "SHTQWNTJ"}
        resp = self.http.request(url, data)
        if resp and resp.get('success'):
            result = []
            for module in resp.get('obj', []):
                for goods in module.get('goodsList', []):
                    if goods.get('exchangeStatus') == 1:
                        result.append({
                            'goodsNo': goods.get('goodsNo'),
                            'goodsName': goods.get('goodsName'),
                            'showName': goods.get('showName', ''),
                        })
            return result
        return []

    def receive_welfare(self, goods_no: str, goods_name: str) -> bool:
        # The single implementation of the points-mall order API (shared by daily benefits and Honey coupon claims)
        url = 'https://mcs-mimp-web.sf-express.com/mcs-mimp/commonPost/~memberGoods~pointMallService~createOrder'
        data = {
            "from": "Point_Mall", "orderSource": "POINT_MALL_EXCHANGE",
            "goodsNo": goods_no, "quantity": 1, "taskCode": self.taskCode
        }
        resp = self.http.request(url, data)
        if resp and resp.get('success'):
            self.logger.success(f'Benefit claimed: {goods_name}')
            return True
        return False

    def handle_welfare_task(self) -> bool:
        welfare_list = self.get_welfare_list()
        if not welfare_list:
            return False
        for w in welfare_list:
            name = f"{w['showName']} - {w['goodsName']}" if w['showName'] else w['goodsName']
            if self.receive_welfare(w['goodsNo'], name):
                return True
            time.sleep(1)
        return False

    def _run_one_task(self, task: Dict):
        """Run a single daily task (split out of run in the merged version: per-task try isolation, one failure does not affect the rest).

        Returns True when the task actually executed an API call
        (finishTask / fetchIntegral), so the caller can measure the
        points balance right after it. Already-done, manual and
        skipped tasks return False.
        """
        title = task.get('title', 'Unknown')
        status = task.get('status')
        try:
            status = int(status)
        except (TypeError, ValueError):
            pass
        if status == 3:
            return False
        if title in DAILY_SKIP_TASKS:
            self._set_task_attrs(task)
            if status == 2 and self.taskCode and self.receive_task_reward():
                return True
            self.logger.info(f'Manual task (must be completed in the Mini Program; auto-complete API not called): {title}')
            return False
        self._set_task_attrs(task)
        if not self.taskCode:
            self.logger.info(f'No task code found, skipping: {title}')
            return False
        self.logger.task(f'Task found: {title} (status: {status})')
        if '领任意生活特权福利' in title:
            welfare_ok = self.handle_welfare_task()
            if welfare_ok:
                time.sleep(2)
                if self.execute_task():
                    time.sleep(2)
                    self.receive_task_reward()
            time.sleep(3)
            return welfare_ok
        if status == 1:
            if '连签7天' in title and 'process' in task:
                cur, tot = map(int, task['process'].split('/'))
                if cur < tot:
                    self.logger.info(f'[{title}] Progress: {task["process"]}')
                    return False
            if self.execute_task():
                self.logger.success(f'[{title}] Submitted successfully')
                time.sleep(2)
                status = 2
            else:
                return False
        if status == 2:
            if self.receive_task_reward():
                return True
            if self.execute_task():
                time.sleep(2)
                self.receive_task_reward()
                time.sleep(3)
                return True
            time.sleep(3)
            return False
        time.sleep(3)
        return False

    def run(self) -> Tuple[int, int]:
        self.logger.info('Fetching daily task list...')
        tasks = self.get_task_list()
        if not tasks:
            self.logger.error('Failed to fetch task list')
            return 0, 0
        points_before = self.total_points
        self.logger.points(points_before, "Points before")
        prev_bal = points_before
        for task in tasks:
            try:
                executed = self._run_one_task(task)
            except Exception as e:
                self.logger.error(f'Task [{task.get("title", "Unknown")}] raised an exception and was skipped: {str(e)[:80]}')
                executed = False
            if executed:
                bal = self.query_balance()
                title = task.get('title', 'Unknown')
                if bal is not None:
                    delta = bal - prev_bal
                    if delta > 0:
                        self.logger.success(f'Task completed: {title}, current points: {bal} (+{delta})')
                    elif delta < 0:
                        self.logger.success(f'Task completed: {title}, current points: {bal} ({delta})')
                    else:
                        self.logger.success(f'Task completed: {title}, current points: {bal}')
                    prev_bal = bal
                else:
                    self.logger.success(f'Task completed: {title}')
        tasks = self.get_task_list()
        points_after = self.total_points if tasks else points_before
        self.logger.points(points_after, "Points after")
        return points_before, points_after


# ==================== Member Day executor (from core; gated by run_account to the 26th-28th of each month) ====================
class MemberDayExecutor:
    MAX_LEVEL = 8

    def __init__(self, http: SFHttpClient, logger: Logger, user_id: str):
        self.http = http
        self.logger = logger
        self.user_id = user_id
        self.black = False
        self.red_packet_map: Dict[int, int] = {}
        self.packet_threshold = 1 << (self.MAX_LEVEL - 1)

    def _check_black(self, error_message: str) -> bool:
        if '没有资格参与活动' in error_message:
            self.black = True
            self.logger.info('Member Day task blocked by risk control')
            return True
        return False

    def get_index(self) -> Optional[Dict]:
        invite_user_id = pick_invite_id(self.user_id)
        url = 'https://mcs-mimp-web.sf-express.com/mcs-mimp/commonPost/~memberNonactivity~memberDayIndexService~index'
        resp = self.http.request(url, {'inviteUserId': invite_user_id})
        if resp and resp.get('success'):
            return resp.get('obj', {})
        error_msg = resp.get('errorMessage', 'No response') if resp else 'Request failed'
        self.logger.info(f'Failed to query Member Day: {error_msg}')
        self._check_black(error_msg)
        return None

    def receive_invite_award(self, invite_user_id: str):
        url = 'https://mcs-mimp-web.sf-express.com/mcs-mimp/commonPost/~memberNonactivity~memberDayIndexService~receiveInviteAward'
        resp = self.http.request(url, {'inviteUserId': invite_user_id})
        if resp and resp.get('success'):
            product_name = resp.get('obj', {}).get('productName', 'Nothing')
            self.logger.success(f'Member Day invite reward: {product_name}')
        else:
            error_msg = resp.get('errorMessage', 'No response') if resp else 'Request failed'
            self.logger.info(f'Failed to claim Member Day invite reward: {error_msg}')
            self._check_black(error_msg)

    def lottery(self) -> Optional[str]:
        url = 'https://mcs-mimp-web.sf-express.com/mcs-mimp/commonPost/~memberNonactivity~memberDayLotteryService~lottery'
        resp = self.http.request(url, {})
        if resp and resp.get('success'):
            product_name = resp.get('obj', {}).get('productName', 'Nothing')
            self.logger.success(f'Member Day lottery: {product_name}')
            return product_name
        error_msg = resp.get('errorMessage', 'No response') if resp else 'Request failed'
        self.logger.info(f'Member Day lottery failed: {error_msg}')
        self._check_black(error_msg)
        return None

    def get_task_list(self) -> Optional[List[Dict]]:
        url = 'https://mcs-mimp-web.sf-express.com/mcs-mimp/commonPost/~memberNonactivity~activityTaskService~taskList'
        resp = self.http.request(url, {'activityCode': 'MEMBER_DAY', 'channelType': 'MINI_PROGRAM'})
        if resp and resp.get('success'):
            return resp.get('obj', [])
        error_msg = resp.get('errorMessage', 'No response') if resp else 'Request failed'
        self.logger.info(f'Failed to query Member Day tasks: {error_msg}')
        self._check_black(error_msg)
        return None

    def finish_task(self, task: Dict) -> bool:
        url = 'https://mcs-mimp-web.sf-express.com/mcs-mimp/commonPost/~memberEs~taskRecord~finishTask'
        # When taskCode is missing, fall back to taskType as the task code (fix logic from the agluo version, 2025-11)
        task_code = task.get('taskCode') or task.get('taskType')
        if not task_code:
            self.logger.info(f'Member Day task [{task.get("taskName", "Unknown")}] has no task code, skipping')
            return False
        resp = self.http.request(url, {'taskCode': task_code})
        if resp and resp.get('success'):
            self.logger.success(f'Member Day task completed [{task["taskName"]}]')
            self.fetch_mix_task_reward(task)
            return True
        error_msg = resp.get('errorMessage', 'No response') if resp else 'Request failed'
        self.logger.info(f'Failed to complete Member Day task [{task["taskName"]}]: {error_msg}')
        self._check_black(error_msg)
        return False

    def fetch_mix_task_reward(self, task: Dict):
        url = 'https://mcs-mimp-web.sf-express.com/mcs-mimp/commonPost/~memberNonactivity~activityTaskService~fetchMixTaskReward'
        data = {'taskType': task['taskType'], 'activityCode': 'MEMBER_DAY', 'channelType': 'MINI_PROGRAM'}
        resp = self.http.request(url, data)
        if resp and resp.get('success'):
            self.logger.success(f'Member Day task reward claimed [{task["taskName"]}]')
        else:
            error_msg = resp.get('errorMessage', 'No response') if resp else 'Request failed'
            self.logger.info(f'Failed to claim Member Day task reward [{task["taskName"]}]: {error_msg}')
            self._check_black(error_msg)

    def do_tasks(self):
        tasks = self.get_task_list()
        if not tasks:
            return
        for task in tasks:
            if self.black:
                return
            if task['status'] == 1:
                self.fetch_mix_task_reward(task)
        for task in tasks:
            if self.black:
                return
            if task['status'] == 2:
                if task['taskType'] in MEMBER_DAY_SKIP_TASK_TYPES:
                    continue
                for _ in range(task.get('restFinishTime', 0)):
                    if self.black:
                        return
                    self.finish_task(task)

    # Hourly red packet: from the agluo version SFSU_checkin.py (defined but never called in the original;
    # the merged version tries once at the end of the Member Day flow for the current hour; failures are logged, never fatal)
    def receive_red_packet(self, hour: int):
        url = 'https://mcs-mimp-web.sf-express.com/mcs-mimp/commonPost/~memberNonactivity~memberDayTaskService~receiveRedPacket'
        resp = self.http.request(url, {'receiveHour': hour})
        if resp and resp.get('success'):
            self.logger.success(f'Member Day hourly red packet for {hour}:00 claimed')
        else:
            error_msg = resp.get('errorMessage', 'No response') if resp else 'Request failed'
            self.logger.info(f'Member Day hourly red packet for {hour}:00: {error_msg}')

    def red_packet_status(self):
        url = 'https://mcs-mimp-web.sf-express.com/mcs-mimp/commonPost/~memberNonactivity~memberDayPacketService~redPacketStatus'
        resp = self.http.request(url, {})
        if not (resp and resp.get('success')):
            error_msg = resp.get('errorMessage', 'No response') if resp else 'Request failed'
            self.logger.info(f'Failed to query Member Day merge status: {error_msg}')
            self._check_black(error_msg)
            return
        for packet in resp.get('obj', {}).get('packetList', []):
            self.red_packet_map[packet['level']] = packet['count']
        for level in range(1, self.MAX_LEVEL):
            count = self.red_packet_map.get(level, 0)
            while count >= 2:
                self.red_packet_merge(level)
                count -= 2
        summary = [f"[Lv{lv}]x{ct}" for lv, ct in self.red_packet_map.items() if ct > 0]
        self.logger.info(f'Member Day merge inventory: {", ".join(summary)}')
        if self.red_packet_map.get(self.MAX_LEVEL):
            self.logger.success(f'Member Day: already own a [Lv{self.MAX_LEVEL}] red packet x{self.red_packet_map[self.MAX_LEVEL]}')
            self.red_packet_draw(self.MAX_LEVEL)
        else:
            remaining_needed = sum(
                1 << (int(lv) - 1) for lv, ct in self.red_packet_map.items()
                if ct > 0 and int(lv) < self.MAX_LEVEL
            )
            remaining = self.packet_threshold - remaining_needed
            self.logger.info(f'Member Day: [Lv1] red packets still needed for a [Lv{self.MAX_LEVEL}] packet: x{remaining}')

    def red_packet_merge(self, level: int):
        url = 'https://mcs-mimp-web.sf-express.com/mcs-mimp/commonPost/~memberNonactivity~memberDayPacketService~redPacketMerge'
        resp = self.http.request(url, {'level': level, 'num': 2})
        if resp and resp.get('success'):
            self.logger.success(f'Member Day merge: [Lv{level}] red packet x2 -> [Lv{level + 1}] red packet')
            self.red_packet_map[level] -= 2
            self.red_packet_map[level + 1] = self.red_packet_map.get(level + 1, 0) + 1
        else:
            error_msg = resp.get('errorMessage', 'No response') if resp else 'Request failed'
            self.logger.info(f'Member Day merge of [Lv{level}] red packet failed: {error_msg}')
            self._check_black(error_msg)

    def red_packet_draw(self, level: int):
        url = 'https://mcs-mimp-web.sf-express.com/mcs-mimp/commonPost/~memberNonactivity~memberDayPacketService~redPacketDraw'
        resp = self.http.request(url, {'level': str(level)})
        if resp and resp.get('success'):
            coupon_names = [item['couponName'] for item in resp.get('obj', [])] or []
            self.logger.success(f'Member Day withdrawal of [Lv{level}] red packet: {", ".join(coupon_names) or "Nothing"}')
        else:
            error_msg = resp.get('errorMessage', '') if resp else 'No response'
            self.logger.info(f'Member Day withdrawal of [Lv{level}] red packet failed: {error_msg}')
            self._check_black(error_msg)

    def run(self) -> Dict[str, Any]:
        result = {'lottery_prizes': [], 'tasks_done': 0}
        index_info = self.get_index()
        if not index_info or self.black:
            return result
        invite_user_id = pick_invite_id(self.user_id)
        if index_info.get('canReceiveInviteAward') and invite_user_id:
            self.receive_invite_award(invite_user_id)
        self.red_packet_status()
        lottery_num = index_info.get('lotteryNum', 0)
        self.logger.info(f'Member Day lottery draws available: {lottery_num} draws')
        for _ in range(lottery_num):
            if self.black:
                break
            prize = self.lottery()
            if prize:
                result['lottery_prizes'].append(prize)
        if not self.black:
            self.do_tasks()
        if not self.black:
            self.red_packet_status()
        if not self.black:
            # Hourly red packet (from the agluo version): try once for the current hour
            try:
                self.receive_red_packet(datetime.now().hour)
            except Exception as e:
                self.logger.info(f'Member Day hourly red packet raised an exception and was skipped: {str(e)[:60]}')
        return result


# ==================== Honey Harvest executor (festival/seasonal event slot) ====================
# All APIs are from the agluo version SFSU_checkin.py (2025-11; its upstream is faintout/Xx1aoy1):
# receiveExchangeIndexService~indexData / ~taskDetail / ~receiveHoney / ~expand
# receiveExchangeGameService~gameReport
# The original ran unconditionally every day, with event data returned by the server indexData; the merged version keeps this behavior:
# when the server has no such event, the API failure is logged and the module is skipped without affecting others.
# Note: this event line keeps the original agluo request header channel=wxwdsj, passed per request via extra_headers.
class HoneyExecutor:
    HEADERS = {'channel': 'wxwdsj'}

    def __init__(self, http: SFHttpClient, logger: Logger, user_id: str):
        self.http = http
        self.logger = logger
        self.user_id = user_id
        # Coupon claiming reuses DailyTaskExecutor's single createOrder implementation, borrowing only its method and taskCode field
        self.daily = DailyTaskExecutor(http, logger, user_id)
        self.task_type = ''
        self.task_code = ''

    def _post(self, path: str, data: Optional[Dict] = None) -> Optional[Dict]:
        url = f'https://mcs-mimp-web.sf-express.com/mcs-mimp/commonPost/{path}'
        return self.http.request(url, data or {}, self.HEADERS)

    def _err(self, resp: Optional[Dict]) -> str:
        return resp.get('errorMessage', 'No response') if resp else 'Request failed'

    def receive_honey_task(self):
        """Collect honey for a single honey task (from agluo receive_honeyTask)"""
        resp = self._post('~memberNonactivity~receiveExchangeIndexService~receiveHoney',
                          {'taskType': self.task_type})
        if resp and resp.get('success'):
            self.logger.success(f'Honey collected for task [{self.task_type}]')
        else:
            self.logger.info(f'Collect honey for task [{self.task_type}]: {self._err(resp)}')

    def finish_honey_task(self):
        """Complete a honey task (from agluo do_honeyTask, via memberEs~taskRecord~finishTask)"""
        url = 'https://mcs-mimp-web.sf-express.com/mcs-mimp/commonPost/~memberEs~taskRecord~finishTask'
        resp = self.http.request(url, {'taskCode': self.task_code}, self.HEADERS)
        if resp and resp.get('success'):
            self.logger.success(f'Honey task [{self.task_type}] completed')
        else:
            self.logger.info(f'Honey task [{self.task_type}]: {self._err(resp)}')

    def get_coupon_list(self):
        """Honey-line coupon claiming (from agluo get_coupom_list).

        Uses the same mallGoodsLifeService~list API as the daily-benefit line, but keeps the original agluo parameters
        memGrade=2 and the exchangeTimesLimit filter (the daily line uses memGrade=3/exchangeStatus;
        these are the original parameters of each product line's source script and were not unified); ordering goes through the single createOrder implementation.
        """
        resp = self._post('~memberGoods~mallGoodsLifeService~list',
                          {"memGrade": 2, "categoryCode": "SHTQ", "showCode": "SHTQWNTJ"})
        if not (resp and resp.get('success')):
            self.logger.info(f'Failed to fetch Honey coupon list: {self._err(resp)}')
            return
        all_goods = []
        for obj in resp.get('obj', []):
            all_goods.extend(obj.get('goodsList', []))
        for goods in all_goods:
            if goods.get('exchangeTimesLimit', 0) >= 1:
                self.daily.taskCode = self.task_code
                if self.daily.receive_welfare(goods.get('goodsNo'), goods.get('goodsName', 'Coupon')):
                    self.logger.success('Honey coupon claimed, task finished')
                    return
        self.logger.info('All Honey coupons tried; none available or all claims failed')

    def honey_game(self):
        """Adventure game (from agluo honey_damaoxian)"""
        self.logger.info('>>> Running Honey adventure game')
        game_num = 5
        for i in range(1, game_num + 1):
            resp = self._post('~memberNonactivity~receiveExchangeGameService~gameReport',
                              {"gatherHoney": 20})
            if resp and resp.get('success'):
                game_num = (resp.get('obj') or {}).get('gameNum', 0)
                self.logger.success(f'> Adventure succeeded! Remaining attempts [{game_num}]')
                time.sleep(2)
            elif resp and resp.get('errorMessage') == '容量不足':
                self.logger.info('> Expansion needed')
                self.honey_expand()
            else:
                self.logger.info(f'> Adventure failed! [{self._err(resp)}]')
                break

    def honey_expand(self):
        """Container expansion (from agluo honey_expand)"""
        resp = self._post('~memberNonactivity~receiveExchangeIndexService~expand', {})
        if resp and resp.get('success'):
            self.logger.success(f'> Expanded capacity to [{resp.get("obj", "Unknown")}]')
        else:
            self.logger.info(f'> Expansion failed! [{self._err(resp)}]')

    def get_task_list_start(self):
        """Honey task list (from agluo get_honeyTaskListStart, via the taskDetail API)"""
        self.logger.info('🍯 Fetching Honey Harvest task list')
        resp = self._post('~memberNonactivity~receiveExchangeIndexService~taskDetail', {})
        if not (resp and resp.get('success')):
            self.logger.info(f'Failed to fetch Honey task list: {self._err(resp)}')
            return
        for item in (resp.get('obj') or {}).get('list', []):
            try:
                self.task_type = item.get('taskType', '')
                status = item.get('status')
                if status == 3:
                    self.logger.info(f'[{self.task_type}] - completed')
                    continue
                if 'taskCode' in item:
                    self.task_code = item['taskCode']
                    if self.task_type == 'DAILY_VIP_TASK_TYPE':
                        self.get_coupon_list()
                    else:
                        self.finish_honey_task()
                if self.task_type == 'BEES_GAME_TASK_TYPE':
                    self.honey_game()
            except Exception as e:
                self.logger.error(f'Honey task [{self.task_type}] raised an exception and was skipped: {str(e)[:60]}')
            time.sleep(2)

    def index_data(self, end: bool = False):
        """Honey index data + collect honey from completed tasks (from agluo honey_indexData)"""
        invite_user_id = pick_invite_id(self.user_id)
        resp = self._post('~memberNonactivity~receiveExchangeIndexService~indexData',
                          {"inviteUserId": invite_user_id})
        if not (resp and resp.get('success')):
            if not end:
                self.logger.info(f'Honey event unavailable or not started: {self._err(resp)}')
            return False
        obj = resp.get('obj') or {}
        usable_honey = obj.get('usableHoney')
        if not end:
            self.logger.info(f"📅 This Honey event ends at [{obj.get('activityEndTime', '')}]")
            self.logger.points(usable_honey, "Honey before")
            for task in obj.get('taskDetail', []):
                self.task_type = task.get('type', '')
                try:
                    self.receive_honey_task()
                except Exception as e:
                    self.logger.error(f'Honey collection [{self.task_type}] raised an exception and was skipped: {str(e)[:60]}')
                time.sleep(2)
        else:
            self.logger.points(usable_honey, "Honey after")
        return True

    def run(self):
        self.logger.info('━━━ Honey Harvest ━━━')
        self.get_task_list_start()
        if self.index_data():
            self.index_data(True)
            end_date = get_quarter_end_date()
            days_left = (end_date - datetime.now()).days
            self.logger.info(f'⏰ Honey event redemption deadline this quarter: {days_left} days left, redeem in time')


def get_quarter_end_date() -> datetime:
    """Compute the end date of the current quarter (from the agluo version)"""
    now = datetime.now()
    quarter_index = (now.month - 1) // 3 + 1
    next_quarter_month = quarter_index * 3 + 1
    if next_quarter_month > 12:
        next_quarter_first_day = datetime(now.year + 1, 1, 1)
    else:
        next_quarter_first_day = datetime(now.year, next_quarter_month, 1)
    return next_quarter_first_day - timedelta(days=1)


# ==================== World Cup executor [expired, off by default] ====================
# From core v1.1.1. The event period 2026.07.02-07.20 has ended and SF_WORLD_CUP is off by default;
# the full code is kept as a sample "date-window-gated festival event" framework that future events can follow.
class WorldCupExecutor:
    BASE = 'https://mcs-mimp-web.sf-express.com/mcs-mimp'
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 mediaCode=SFEXPRESSAPP-iOS-ML',
        'channel': WORLD_CUP_CHANNEL,
        'platform': WORLD_CUP_PLATFORM,
    }

    def __init__(self, http: SFHttpClient, logger: Logger, user_id: str):
        self.http = http
        self.logger = logger
        self.user_id = user_id

    def _post(self, path: str, data: Optional[Dict] = None) -> Optional[Dict]:
        return self.http.request(f'{self.BASE}{path}', data or {}, self.HEADERS)

    def _error(self, action: str, resp: Optional[Dict]):
        message = resp.get('errorMessage', 'No response') if resp else 'No response'
        error_code = resp.get('errorCode') if resp else None
        code_text = f'[{error_code}]' if error_code else ''
        self.logger.info(f'World Cup {action} failed{code_text}: {message}')

    def _assist(self):
        target = WORLD_CUP_ASSIST_ID.strip()
        if not target:
            self.logger.info('World Cup assist ID not configured, skipping')
            return
        if target == self.user_id:
            self.logger.info('World Cup: current account is the assist target, skipping self-assist')
            return
        resp = self._post(
            '/commonPost/~memberNonactivity~worldCupIndexService~index',
            {'inviteType': 1, 'inviteUserId': target},
        )
        if resp and resp.get('success'):
            self.logger.success(f'World Cup assist for main account {target[:8]}... succeeded')
        else:
            self._error('assist', resp)

    def _daily_gift(self, result: Dict[str, Any]):
        data = {'cityCode': WORLD_CUP_CITY_CODE}
        resp = self._post('/commonPost/~memberNonactivity~worldCupDailyService~getDailyGiftStatus', data)
        if not (resp and resp.get('success')):
            self._error('query daily gift', resp)
            return
        status = resp.get('obj') or {}
        if status.get('received'):
            self.logger.info('World Cup daily gift already claimed today')
            return
        if not status.get('canReceive'):
            self.logger.info('World Cup daily gift not claimable right now')
            return
        resp = self._post('/commonPost/~memberNonactivity~worldCupDailyService~receiveDailyGift', data)
        if resp and resp.get('success'):
            result['daily_gift'] = True
            self.logger.success('World Cup daily gift claimed')
        else:
            self._error('claim daily gift', resp)

    def _tasks(self, result: Dict[str, Any]):
        task_data = {'activityCode': WORLD_CUP_ACTIVITY_CODE, 'channelType': WORLD_CUP_PLATFORM}
        resp = self._post('/commonPost/~memberNonactivity~activityTaskService~taskList', task_data)
        if not (resp and resp.get('success')):
            self._error('query tasks', resp)
            return
        tasks = resp.get('obj') or []
        for task in tasks:
            if not isinstance(task, dict):
                continue
            if not is_safe_world_cup_task(task):
                continue
            name = str(task.get('taskName') or 'Unknown task')
            status = task.get('status')
            try:
                status = int(status)
            except (TypeError, ValueError):
                pass
            rest_finish = int(task.get('restFinishTime') or 0)
            if status == 3 or (status == 1 and rest_finish <= 0):
                self.logger.info(f'World Cup task already completed: {name}')
                continue
            finish = self._post(
                '/commonPost/~memberEs~taskRecord~finishTask',
                {'taskCode': task.get('taskCode')},
            )
            if finish and finish.get('success') and finish.get('obj') is not False:
                result['tasks_completed'] += 1
                self.logger.success(f'World Cup task completed: {name}')
            else:
                self._error(f'complete task [{name}]', finish)
            time.sleep(1)

        reward = self._post(
            '/commonPost/~memberNonactivity~worldCupTaskService~fetchTaskReward',
            task_data,
        )
        if not (reward and reward.get('success')):
            self._error('claim task rewards', reward)
            return
        received = (reward.get('obj') or {}).get('receivedAccountList') or []
        if received:
            text = ', '.join(f"{x.get('currency', '')} x{x.get('amount', 0)}" for x in received)
            self.logger.success(f'World Cup task rewards: {text}')
        else:
            self.logger.info('No new World Cup task rewards')

    def _game(self, result: Dict[str, Any]):
        resp = self._post('/commonPost/~memberNonactivity~worldCupGameService~index')
        if not (resp and resp.get('success')):
            self._error('query shooting game', resp)
            return
        game = resp.get('obj') or {}
        current_level = int(game.get('curLevel') or 1)
        reward_levels = [
            level for level in game.get('levelList') or []
            if int(level.get('rewardCoins') or 0) > 0
        ]
        if not reward_levels:
            self.logger.info('World Cup shooting rewards already claimed today')
            return
        for level in reward_levels:
            level_no = int(level.get('level') or 0)
            if not level_no or level_no < current_level:
                continue
            target = int(level.get('target') or 0)
            passed = self._post(
                '/commonPost/~memberNonactivity~worldCupGameService~passReport',
                {'level': level_no, 'shotNum': target},
            )
            if not (passed and passed.get('success')):
                self._error(f'report level {level_no} result', passed)
                break
            coin_num = int((passed.get('obj') or {}).get('coinNum') or 0)
            result['levels_passed'] += 1
            result['game_coins'] += coin_num
            self.logger.success(f'World Cup shooting level {level_no} completed, coins +{coin_num}')
            time.sleep(1)

    def _bet_status(self) -> Optional[Dict]:
        resp = self._post('/commonPost/~memberNonactivity~worldCupMatchService~betStatus')
        if resp and resp.get('success'):
            return resp.get('obj') or {}
        self._error('query betting', resp)
        return None

    def _bet(self, result: Dict[str, Any]):
        status = self._bet_status()
        if status is None:
            return
        balance = int((status.get('currentAccount') or {}).get('balance') or 0)
        bet_coin = max(10, int(WORLD_CUP_BET_COIN))
        pending = [
            match for match in status.get('matchList') or []
            if match.get('matchStatus') == 'Fixture' and match.get('recordStatus', 0) == 0
        ]
        for match in pending:
            if balance < bet_coin:
                break
            bet_result = random.randint(0, 2)
            resp = self._post(
                '/commonPost/~memberNonactivity~worldCupMatchService~placeBet',
                {
                    'matchId': match.get('matchId'),
                    'betResult': bet_result,
                    'betCoin': bet_coin,
                },
            )
            if resp and resp.get('success'):
                balance -= bet_coin
                result['bets_placed'] += 1
                self.logger.success(f"World Cup bet placed: {match.get('teamAName', '?')} vs {match.get('teamBName', '?')}")
            else:
                self._error('place bet', resp)
            time.sleep(1)

    def _settle(self, result: Dict[str, Any]):
        resp = self._post('/commonPost/~memberNonactivity~worldCupMatchService~settleBet')
        if not (resp and resp.get('success')):
            self._error('settle bets', resp)
            return
        settled = resp.get('obj') or []
        result['settle_pnl'] = sum(
            (item.get('betWinCoin') or 0) - (item.get('betCoin') or 0)
            for item in settled
        )
        if settled:
            self.logger.info(f"World Cup bet settlement: {result['settle_pnl']:+}")

    def _refresh_balance(self, result: Dict[str, Any]):
        status = self._bet_status()
        if status is None:
            return
        account = status.get('currentAccount') or {}
        result['balance'] = int(account.get('balance') or 0)
        result['total_amount'] = int(account.get('totalAmount') or 0)
        self.logger.points(result['balance'], 'World Cup coins')

    def run(self) -> Dict[str, Any]:
        result = {
            'daily_gift': False,
            'tasks_completed': 0,
            'levels_passed': 0,
            'game_coins': 0,
            'bets_placed': 0,
            'settle_pnl': 0,
            'balance': 0,
            'total_amount': 0,
        }
        self.logger.info('━━━ World Cup Event ━━━')
        self._assist()
        index = self._post('/commonPost/~memberNonactivity~worldCupIndexService~index')
        if not (index and index.get('success')):
            self._error('query index', index)
            return result
        info = index.get('obj') or {}
        if info.get('acStartTime') or info.get('acEndTime'):
            self.logger.info(f"World Cup event period: {info.get('acStartTime', '')} ~ {info.get('acEndTime', '')}")

        self._daily_gift(result)
        self._tasks(result)
        if WORLD_CUP_ENABLE_GAME:
            self._game(result)
        if ENABLE_WORLD_CUP_BET:
            self._bet(result)
        else:
            self.logger.info('World Cup random betting is off (set ENABLE_WORLD_CUP_BET=True in the config section to enable)')
        if WORLD_CUP_ENABLE_SETTLE:
            self._settle(result)
        self._refresh_balance(result)
        return result


# ==================== Account execution ====================
def run_account_core(account_raw: str, index: int) -> Dict[str, Any]:
    logger = Logger()
    if '#' in account_raw and (':' in account_raw.split('#')[-1]):
        last_hash = account_raw.rfind('#')
        account_url = account_raw[:last_hash].strip()
        fixed_proxy = account_raw[last_hash + 1:].strip()
    else:
        account_url = account_raw
        fixed_proxy = ""
    decoded_account = unquote(account_url)
    http = SFHttpClient(fixed_proxy)
    login_success = False
    phone = ''
    user_id = ''
    for attempt in range(MAX_PROXY_RETRIES):
        if attempt > 0:
            http = SFHttpClient(fixed_proxy)
        success, user_id, phone = http.login(account_url)
        if success:
            login_success = True
            break
        time.sleep(2)
    if not login_success:
        logger.error(f'Account {index + 1} login failed')
        ck_invalid = 'sessionid=' in decoded_account.lower() or '_login_' in decoded_account.lower()
        return {'success': False, 'phone': '', 'index': index,
                'points_before': 0, 'points_after': 0, 'points_earned': 0,
                'member_day_prizes': [], 'world_cup': {},
                'ck_invalid': ck_invalid, 'fail_reason': 'CK expired' if ck_invalid else 'Login failed',
                'error': 'CK expired' if ck_invalid else 'Login failed'}
    # Register the userId so later accounts can pick it in invite-reward flows (see register_invite_id)
    register_invite_id(user_id)
    masked = phone[:3] + "****" + phone[7:] if len(phone) >= 7 else phone
    logger.success(f'Account {index + 1}: [{masked}] login succeeded | 🌐 {http.proxy_display}')
    time.sleep(random.uniform(1, 3))
    result = {
        'success': True, 'phone': phone, 'index': index,
        'points_before': 0, 'points_after': 0, 'points_earned': 0,
        'member_day_prizes': [], 'world_cup': {},
        'ck_invalid': False, 'fail_reason': '', 'error': '',
    }
    # Daily points tasks
    if ENABLE_DAILY_TASK:
        logger.info('━━━ Daily Points Tasks ━━━')
        daily = DailyTaskExecutor(http, logger, user_id)
        daily.dual_sign_in()
        time.sleep(1)
        daily.app_sign_in()
        time.sleep(1)
        sign_ok, sign_err = daily.sign_in()
        if not sign_ok and '活动太火爆' in sign_err:
            for retry in range(3):
                logger.warning(f'Sign-in IP problem, retrying ({retry + 1}/3)...')
                time.sleep(2)
                http = SFHttpClient(fixed_proxy)
                s, user_id, phone = http.login(account_url)
                if s:
                    daily.http = http
                    daily.user_id = user_id
                    sign_ok, sign_err = daily.sign_in()
                    if sign_ok or '活动太火爆' not in sign_err:
                        break
        if not sign_ok and '活动太火爆' in sign_err:
            logger.warning('Sign-in busy after retries: login normal, points on hold until parcel activity resumes [signin_busy_no_parcel]')
        pb, pa = daily.run()
        result['points_before'] = pb
        result['points_after'] = pa
        result['points_earned'] = pa - pb
    # Honey Harvest (festival/seasonal slot, from the agluo version)
    if ENABLE_HONEY:
        try:
            HoneyExecutor(http, logger, user_id).run()
        except Exception as e:
            logger.error(f'Honey module raised an exception and was skipped: {str(e)[:80]}')
    # Member Day event (26th-28th of each month)
    if ENABLE_MEMBER_DAY:
        current_day = datetime.now().day
        if 26 <= current_day <= 28:
            logger.info('━━━ Member Day Event ━━━')
            md = MemberDayExecutor(http, logger, user_id)
            md_result = md.run()
            result['member_day_prizes'] = md_result.get('lottery_prizes', [])
        else:
            logger.info('⏰ Not Member Day yet (26th-28th), skipping')
    if ENABLE_WORLD_CUP:
        if world_cup_active():
            result['world_cup'] = WorldCupExecutor(http, logger, user_id).run()
        else:
            logger.info('⏰ Outside the World Cup event period (2026.07.02-07.20), skipping')
    if http.ck_invalid:
        logger.error(f'Account {index + 1} CK expired')
        result['success'] = False
        result['ck_invalid'] = True
        result['fail_reason'] = http.ck_invalid_message or 'CK expired'
        result['error'] = result['fail_reason']
    return result


def run_account(account_raw: str, index: int) -> Dict[str, Any]:
    """Per-account exception isolation layer (from the Qcby version): an exception in any account never affects the others"""
    try:
        result = run_account_core(account_raw, index)
        if not isinstance(result, dict):
            raise ValueError('Account execution returned no result')
    except Exception as exc:
        result = {
            'success': False, 'phone': '', 'index': index,
            'points_before': 0, 'points_after': 0, 'points_earned': 0,
            'member_day_prizes': [], 'world_cup': {},
            'ck_invalid': False, 'fail_reason': str(exc), 'error': str(exc),
        }
    result.setdefault('points_before', 0)
    result.setdefault('points_after', 0)
    result.setdefault('points_earned', 0)
    result.setdefault('member_day_prizes', [])
    result.setdefault('fail_reason', result.get('error', ''))
    return result


# ==================== Main program ====================
def main():
    env_name = 'sfsyUrl'
    env_value = os.getenv(env_name)
    if not env_value:
        print(f"❌ Environment variable not found: {env_name}")
        return
    account_list = parse_accounts(env_value)
    if not account_list:
        print(f"❌ Environment variable {env_name} is empty")
        return
    random.shuffle(account_list)
    task_map = {
        "Daily tasks": ENABLE_DAILY_TASK,
        "Honey": ENABLE_HONEY,
        "Member Day": ENABLE_MEMBER_DAY,
        "World Cup": ENABLE_WORLD_CUP,
    }
    enabled = [f"{k}✓" for k, v in task_map.items() if v]
    print("=" * 60)
    print("🎉 sf-duoheyi v2.0.0 (Four-Way Merged Edition)")
    print("👨‍💻 Core: ShuiLiZe/YaoHuo8648 | Daily lineage: 爱学习的呆子 | Honey: agluo/faintout")
    print(f"📱 {len(account_list)} account(s) in total")
    print(f"⚙️ Concurrency: {CONCURRENT_NUM} | 📋 {' '.join(enabled)}")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if PROXY_API_URL:
        _log_global(f"🔌 Proxy enabled: {PROXY_API_URL[:40]}...")
    print("=" * 60)
    all_results = []
    if CONCURRENT_NUM <= 1:
        for idx, raw in enumerate(account_list):
            result = run_account(raw, idx)
            all_results.append(result)
            if idx < len(account_list) - 1:
                time.sleep(2)
    else:
        with ThreadPoolExecutor(max_workers=CONCURRENT_NUM) as pool:
            futures = {pool.submit(run_account, raw, idx): idx for idx, raw in enumerate(account_list)}
            for f in as_completed(futures):
                all_results.append(f.result())
    all_results.sort(key=lambda x: x['index'])
    # Summary
    print(f"\n{'='*70}")
    print("📊 Execution Summary")
    print("=" * 70)
    total_earned = 0
    show_world_cup = ENABLE_WORLD_CUP and world_cup_active()
    total_world_cup_balance = 0
    for r in all_results:
        phone = r['phone'][:3] + "****" + r['phone'][7:] if r.get('phone') and len(r['phone']) >= 7 else r.get('phone', 'Not logged in')
        earned = r.get('points_earned', 0)
        total_earned += earned
        world_cup = r.get('world_cup') or {}
        total_world_cup_balance += world_cup.get('balance', 0)
        if r.get('ck_invalid'):
            print(f"❌ {phone}: CK expired")
        elif not r['success']:
            print(f"❌ {phone}: {r.get('fail_reason') or 'Login failed'}")
        else:
            parts = [f"Points +{earned}"]
            md_prizes = r.get('member_day_prizes', [])
            if md_prizes:
                parts.append(f"Member Day: {', '.join(md_prizes)}")
            if show_world_cup:
                parts.append(f"World Cup coins {world_cup.get('balance', 0)}")
                if world_cup.get('game_coins'):
                    parts.append(f"Shooting +{world_cup.get('game_coins')}")
                if world_cup.get('tasks_completed'):
                    parts.append(f"World Cup tasks {world_cup.get('tasks_completed')}")
                if world_cup.get('daily_gift'):
                    parts.append('World Cup gift ✓')
                if world_cup.get('bets_placed'):
                    parts.append(f"Bets placed {world_cup.get('bets_placed')} matches")
            print(f"✅ {phone}: {' | '.join(parts)}")
    print("-" * 70)
    total_parts = [f"📱 Total accounts: {len(all_results)}", f"💰 Total points +{total_earned}"]
    if show_world_cup:
        total_parts.append(f"World Cup coins {total_world_cup_balance}")
    print(" | ".join(total_parts))
    print("=" * 70)
    print("🎊 Execution complete!")
    push_lines = []
    for r in all_results:
        phone = r['phone'][:3] + "****" + r['phone'][7:] if r.get('phone') and len(r['phone']) >= 7 else r.get('phone', 'Not logged in')
        if r.get('ck_invalid'):
            push_lines.append(f"❌ {phone}: CK expired")
        elif not r['success']:
            push_lines.append(f"❌ {phone}: {r.get('fail_reason') or 'Login failed'}")
        else:
            earned = r.get('points_earned', 0)
            parts = [f"Points +{earned}"]
            md_prizes = r.get('member_day_prizes', [])
            if md_prizes:
                parts.append(f"Member Day: {', '.join(md_prizes)}")
            world_cup = r.get('world_cup') or {}
            if show_world_cup:
                parts.append(f"World Cup coins {world_cup.get('balance', 0)}")
                if world_cup.get('game_coins'):
                    parts.append(f"Shooting +{world_cup.get('game_coins')}")
                if world_cup.get('tasks_completed'):
                    parts.append(f"World Cup tasks {world_cup.get('tasks_completed')}")
                if world_cup.get('daily_gift'):
                    parts.append('World Cup gift ✓')
            push_lines.append(f"✅ {phone}: {' | '.join(parts)}")
    push_lines.append(" | ".join(total_parts))
    notify_content = "\n".join(push_lines)
    if PUSH_SWITCH == "1" and notify_content:
        print("📤 Preparing push notification...")
        try:
            if notify_send:
                notify_send("sf-duoheyi", notify_content)
                print("✅ Push sent")
            else:
                print("⚠️ notify module not found, cannot push")
        except Exception as e:
            print(f"❌ Push failed: {e}")
    elif PUSH_SWITCH == "0":
        print("ℹ️ Push switch is off (SFSY_PUSH=0)")


if __name__ == '__main__':
    main()
