# -*- coding: utf-8 -*-
"""
报警通道统一发送器 — 邮件(SMTP) + 企业微信(群机器人 webhook)
==============================================================
被 status_monitor.py / patrol_daemon.py 调用，在引擎异常/修复时主动推送。

配置来源（优先级：环境变量 > tools/alert_config.json > 无则安全 no-op）：
  ALERT_SMTP_HOST / ALERT_SMTP_PORT / ALERT_SMTP_USER / ALERT_SMTP_PASS / ALERT_SMTP_TO
  ALERT_WECOM_WEBHOOK
  alert_config.json 结构：
    {
      "smtp": {"host":"smtp.xxx.com","port":465,"user":"a@b.com","pass":"***","to":"c@d.com,e@f.com"},
      "wecom": {"webhook":"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=XXX"}
    }

防刷屏：同一 title 10 分钟内只推送一次（引擎持续异常不会每分钟轰炸）。
"""
import json
import os
import time
import logging
import smtplib
import urllib.request
from email.mime.text import MIMEText

logger = logging.getLogger("alert_sender")

_COOLDOWN_SEC = 600  # 同一告警 10 分钟内只发一次
_cooldown: dict[str, float] = {}

_CONFIG_CACHE: dict | None = None


def _load_config() -> dict:
    """合并 env + tools/alert_config.json，env 优先。"""
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE
    cfg: dict = {"smtp": {}, "wecom": {}}
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "alert_config.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                file_cfg = json.load(f)
            cfg["smtp"].update(file_cfg.get("smtp", {}))
            cfg["wecom"].update(file_cfg.get("wecom", {}))
    except Exception as e:
        logger.warning(f"[alert] 读取 alert_config.json 失败: {e}")

    # env 覆盖
    if os.environ.get("ALERT_SMTP_HOST"):
        cfg["smtp"]["host"] = os.environ["ALERT_SMTP_HOST"]
    if os.environ.get("ALERT_SMTP_PORT"):
        try:
            cfg["smtp"]["port"] = int(os.environ["ALERT_SMTP_PORT"])
        except ValueError:
            pass
    if os.environ.get("ALERT_SMTP_USER"):
        cfg["smtp"]["user"] = os.environ["ALERT_SMTP_USER"]
    if os.environ.get("ALERT_SMTP_PASS"):
        cfg["smtp"]["pass"] = os.environ["ALERT_SMTP_PASS"]
    if os.environ.get("ALERT_SMTP_TO"):
        cfg["smtp"]["to"] = os.environ["ALERT_SMTP_TO"]
    if os.environ.get("ALERT_WECOM_WEBHOOK"):
        cfg["wecom"]["webhook"] = os.environ["ALERT_WECOM_WEBHOOK"]

    _CONFIG_CACHE = cfg
    return cfg


def _ready_channels() -> tuple[dict, dict]:
    cfg = _load_config()
    smtp = cfg.get("smtp", {})
    wecom = cfg.get("wecom", {})
    smtp_ok = bool(smtp.get("host") and smtp.get("user") and smtp.get("pass") and smtp.get("to"))
    wecom_ok = bool(wecom.get("webhook"))
    return (smtp if smtp_ok else {}), (wecom if wecom_ok else {})


def send_email(smtp: dict, title: str, msg: str) -> bool:
    try:
        body = f"{msg}\n\n时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        m = MIMEText(body, "plain", "utf-8")
        m["Subject"] = f"[XAUUSD告警] {title}"
        m["From"] = smtp["user"]
        to_list = [x.strip() for x in str(smtp["to"]).split(",") if x.strip()]
        m["To"] = ", ".join(to_list)
        port = int(smtp.get("port", 465))
        # 465 用 SSL，其他端口用 STARTTLS
        if port == 465:
            with smtplib.SMTP_SSL(smtp["host"], port, timeout=10) as s:
                s.login(smtp["user"], smtp["pass"])
                s.sendmail(smtp["user"], to_list, m.as_string())
        else:
            with smtplib.SMTP(smtp["host"], port, timeout=10) as s:
                s.ehlo()
                s.starttls()
                s.login(smtp["user"], smtp["pass"])
                s.sendmail(smtp["user"], to_list, m.as_string())
        logger.info(f"[alert] 邮件已发: {title} -> {to_list}")
        return True
    except Exception as e:
        logger.warning(f"[alert] 邮件发送失败: {e}")
        return False


def send_wecom(wecom: dict, title: str, msg: str) -> bool:
    try:
        content = f"[XAUUSD告警] {title}\n{msg}"
        payload = {"msgtype": "text", "text": {"content": content}}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            wecom["webhook"],
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        if result.get("errcode", 0) != 0:
            logger.warning(f"[alert] 企微返回错误: {result}")
            return False
        logger.info(f"[alert] 企微已发: {title}")
        return True
    except Exception as e:
        logger.warning(f"[alert] 企微发送失败: {e}")
        return False


def send_alert(title: str, msg: str, force: bool = False) -> bool:
    """统一入口。返回是否有任一通道真正发出。no-op 当无配置。"""
    key = str(title).strip()[:40]
    now = time.time()
    if not force:
        last = _cooldown.get(key, 0.0)
        if now - last < _COOLDOWN_SEC:
            return False
    _cooldown[key] = now

    smtp, wecom = _ready_channels()
    sent = False
    if smtp:
        sent = send_email(smtp, title, msg) or sent
    if wecom:
        sent = send_wecom(wecom, title, msg) or sent
    if not smtp and not wecom:
        logger.debug("[alert] 未配置任何通道，跳过推送（仅本地日志）")
    return sent


def self_test() -> dict:
    """自检：打印各通道配置就绪状态（不实际发送）。"""
    smtp, wecom = _ready_channels()
    return {
        "email_ready": bool(smtp),
        "wecom_ready": bool(wecom),
        "email_to": smtp.get("to", "") if smtp else "",
        "wecom_configured": bool(wecom.get("webhook")),
    }


if __name__ == "__main__":
    print("alert_sender 自检:", self_test())
    # 测试发送（需先配置）
    ok = send_alert("自检测试", "这是一条来自 alert_sender 的测试告警", force=True)
    print("测试发送结果:", ok)
