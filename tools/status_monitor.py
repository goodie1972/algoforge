"""
系统状态监控 + 自动修复 — 每5分钟检查一次
发现问题时自动尝试恢复，记录到 logs/status_check.log
"""
import json
import os
import subprocess
import sys as _sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
API = "http://127.0.0.1:1783"
LOG = BASE / "logs" / "status_check.log"
CSV_SIGNAL = BASE / "logs" / "signal_analysis.csv"
CSV_PAPER = BASE / "logs" / "paper_trades.csv"
BACKEND_SCRIPT = BASE / "dashboard" / "backend" / "main.py"

def fetch(url):
    try:
        r = urllib.request.urlopen(url, timeout=10)
        return json.loads(r.read().decode())
    except Exception as e:
        return {"_error": str(e)}

def log_msg(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().strftime('%m-%d %H:%M')} {msg}\n")
    _sys.stderr.write(f"[监控] {msg}\n")
    _sys.stderr.flush()

def restart_engine():
    """重启后端引擎"""
    log_msg("[修复] 开始重启引擎...")
    # 杀旧进程
    os.system('wmic process where "commandline like \'%backend/main.py%\'" delete 2>/dev/null')
    time.sleep(5)
    # 启动新引擎
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BASE)
    proc = subprocess.Popen(
        [_sys.executable, str(BACKEND_SCRIPT)],
        cwd=str(BASE), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    log_msg(f"[修复] 引擎已启动 PID={proc.pid}")
    time.sleep(5)

def restart_process(name, script, logfile):
    """重启辅助进程"""
    log_msg(f"[修复] 重启{name}...")
    try:
        subprocess.Popen(
            [_sys.executable, str(script)],
            cwd=str(BASE),
            stdout=open(logfile, "a"), stderr=subprocess.STDOUT,
        )
    except Exception as e:
        log_msg(f"[修复] 重启{name}失败: {e}")

def check_and_heal():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    issues = []
    fixed = []

    # ── 1. 引擎状态 ──
    eng = fetch(f"{API}/api/engine/status")
    engine_ok = False
    if "_error" in eng:
        issues.append("引擎API不可达")
        log_msg("[警报] 引擎API不可达，尝试重启...")
        restart_engine()
        fixed.append("已重启引擎")
    elif eng.get("status") == "running":
        if eng.get("bridge_connected"):
            engine_ok = True
        else:
            issues.append("桥接未连接")
            # 等30秒看桥接能不能自动重连
            log_msg("[警报] 桥接断连，等待10秒...")
            time.sleep(10)
            eng2 = fetch(f"{API}/api/engine/status")
            if eng2.get("_error") or not eng2.get("bridge_connected"):
                log_msg("[修复] 桥接未恢复，重启引擎")
                restart_engine()
                fixed.append("已重启引擎以恢复桥接")
            else:
                fixed.append("桥接自动恢复")
    else:
        issues.append(f"引擎状态异常: {eng.get('status')}")
        log_msg(f"[警报] 引擎状态异常，重启...")
        restart_engine()
        fixed.append("已重启引擎")

    # ── 2. 数据工厂缓存 ──
    if engine_ok:
        ind = fetch(f"{API}/api/data/indicators?timeframe=M30")
        if "_error" in ind or "error" in ind:
            err = ind.get("error", ind.get("_error", "未知"))
            issues.append(f"数据工厂异常: {err}")
            log_msg(f"[警报] 数据工厂异常: {err}")
        time.sleep(1)

    # ── 3. 信号CSV是否在更新 ──
    if CSV_SIGNAL.exists():
        mtime = CSV_SIGNAL.stat().st_mtime
        age_min = (time.time() - mtime) / 60
        if age_min > 30:
            issues.append(f"信号CSV已{age_min:.0f}分钟未更新")
            log_msg(f"[警报] 信号CSV已{age_min:.0f}分钟未更新")
    else:
        issues.append("信号CSV不存在")

    # ── 4. 纸面交易CSV ──
    if CSV_PAPER.exists():
        mtime2 = CSV_PAPER.stat().st_mtime
        age2 = (time.time() - mtime2) / 60
        if age2 > 30:
            issues.append(f"纸面CSV已{age2:.0f}分钟未更新")
            log_msg(f"[警报] 纸面CSV已{age2:.0f}分钟未更新")

    # ── 5. 检查是否有主循环异常 ──
    try:
        err_logs = fetch(f"{API}/api/logs?level=ERROR&limit=5")
        if isinstance(err_logs, dict): err_logs = err_logs.get("logs", [])
        for l in (err_logs or []):
            msg = l.get("message", "") if isinstance(l, dict) else str(l)
            if "主循环异常" in msg:
                log_msg(f"[警报] 检测到引擎主循环异常: {msg[:100]}")
                if "主循环异常" in msg:
                    log_msg("[修复] 主循环异常，重启引擎")
                    restart_engine()
                    fixed.append("已重启引擎(主循环异常)")
                    break
    except:
        pass

    # ── 输出报告 ──
    status = "OK" if not issues else f"异常({len(issues)}个问题)"
    summary_parts = [f"[{status}]"]
    if fixed:
        summary_parts.append(f"已修复: {';'.join(fixed)}")
    if issues:
        summary_parts.append(f"未解决: {';'.join(issues)}")

    # 获取基本状态
    eng_status = f"运行{eng.get('uptime_seconds',0)/60:.0f}分" if engine_ok else "异常"
    price = fetch(f"{API}/api/market/price")
    price_str = f"Bid={price.get('bid')} Ask={price.get('ask')}" if "_error" not in price else "?"
    csv_lines = len(CSV_SIGNAL.read_text(encoding="utf-8").splitlines()) if CSV_SIGNAL.exists() else 0
    paper_lines = len(CSV_PAPER.read_text(encoding="utf-8").splitlines()) if CSV_PAPER.exists() else 0

    report = (
        f"\n{'='*60}\n"
        f"  [{now}] {'⚠' if issues else 'OK'}\n"
        f"  引擎={eng_status} 行情={price_str}\n"
        f"  信号={csv_lines}条 纸面={paper_lines}笔\n"
        f"  {'; '.join(summary_parts)}\n"
        f"{'='*60}"
    )
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(report + "\n")
    _sys.stderr.write(report + "\n")
    _sys.stderr.flush()

    return issues, fixed

if __name__ == "__main__":
    log_msg("状态监控+自修复 启动")
    while True:
        try:
            check_and_heal()
        except Exception as e:
            log_msg(f"[错误] 监控自身异常: {e}")
        time.sleep(300)  # 5分钟
