"""
纸面交易模拟器 — 记录信号入场，模拟出场
输出完整交易记录表：编号|时间|策略|方向|评分|入场价|出场价|收益|出场原因
"""
import csv, json, time, math
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
API = "http://127.0.0.1:1783"
CSV_IN = BASE / "logs" / "signal_analysis.csv"
CSV_OUT = BASE / "logs" / "paper_trades.csv"
CSV_HEADERS = ["编号","时间","策略","方向","评分","入场价格","出场价格","收益","出场原因","因子"]

def fetch(url):
    try:
        r = urllib.request.urlopen(url, timeout=8)
        return json.loads(r.read())
    except: return None

def get_indicator(tf):
    d = fetch(f"{API}/api/data/indicators?timeframe={tf}")
    return d if d and "error" not in d else None

def get_price():
    return fetch(f"{API}/api/market/price")

class PaperTrader:
    def __init__(self):
        self.positions = {}  # signal_id -> position dict
        self.load_positions()

    def load_positions(self):
        """从CSV恢复已有持仓"""
        if not CSV_OUT.exists(): return
        with open(CSV_OUT, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                entry = r.get("入场价格", "")
                if not entry:  # 跳过损坏行
                    continue
                try:
                    entry_price = float(entry)
                except (ValueError, TypeError):
                    continue
                if not r.get("出场价格"):  # 未平仓
                    self.positions[r["编号"]] = {
                        "signal_id": r["编号"], "strategy": r["策略"],
                        "direction": r["方向"], "entry_price": entry_price,
                        "score": r["评分"], "factors": r.get("因子",""),
                        "time": r["时间"], "tf": "M30",
                    }

    def save_trade(self, row):
        exists = CSV_OUT.exists()
        with open(CSV_OUT, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, CSV_HEADERS)
            if not exists: w.writeheader()
            w.writerow(row)

    def open_position(self, signal):
        """根据信号开纸面仓位"""
        sid = str(signal["signal_id"])
        if sid in self.positions: return
        iv = signal.get("all_indicators_json", "{}")
        try: iv = json.loads(iv)
        except: iv = {}
        price = float(signal.get("close", 0) or iv.get("close", 0))
        if price <= 0: price = float(iv.get("_mid", 0))
        if price <= 0: price = float(iv.get("_bid", 0))

        tf = signal.get("timeframe", "M30")
        self.positions[sid] = {
            "signal_id": sid, "strategy": signal["strategy"],
            "direction": signal["signal"], "entry_price": price,
            "score": f"{signal.get('score_long','?')}/{signal.get('score_short','?')}",
            "factors": signal.get("factors_long","") or signal.get("factors_short",""),
            "time": signal.get("record_time",""), "tf": tf,
            "entry_bb": None, "status": "open",
        }
        print(f"[开仓] #{sid} {signal['strategy']} {signal['signal']} @ {price:.2f}")

    def check_exits(self):
        """检查所有持仓是否需要平仓"""
        to_close = []
        for sid, pos in list(self.positions.items()):
            if pos.get("status") != "open": continue
            strat = pos["strategy"]
            direction = pos["direction"]
            entry = pos["entry_price"]
            tf = pos.get("tf", "M30")

            # 获取最新行情
            p = get_price()
            if not p: continue
            bid, ask = p.get("bid",0), p.get("ask",0)
            if bid <= 0: continue
            mid = (bid + ask) / 2
            current = bid if direction == "SELL" else ask

            # 获取最新指标
            ind = get_indicator(tf)
            if not ind: continue

            # --- 策略专属出场逻辑 ---
            exit_price = None
            reason = None

            if "mfi_bb" in strat:
                exit_price, reason = self._exit_mfi_bb(pos, ind, current, mid, entry)
            elif "viprasol" in strat:
                exit_price, reason = self._exit_atr_based(pos, ind, current, direction, entry, trail_atr=1.5, hard_atr=3.0)
            elif "sanqing" in strat:
                exit_price, reason = self._exit_atr_based(pos, ind, current, direction, entry, trail_atr=2.5, hard_atr=4.0)
            elif "stoch" in strat:
                exit_price, reason = self._exit_atr_based(pos, ind, current, direction, entry, trail_atr=1.5, hard_atr=2.5)
            elif "m30_bb_deepreturn" in strat:
                exit_price, reason = self._exit_atr_based(pos, ind, current, direction, entry, trail_atr=1.0, hard_atr=2.0)
            elif "rsi_grading" in strat:
                exit_price, reason = self._exit_atr_based(pos, ind, current, direction, entry, trail_atr=1.0, hard_atr=2.0)
            elif "gold_auto" in strat:
                exit_price, reason = self._exit_atr_based(pos, ind, current, direction, entry, trail_atr=1.5, hard_atr=3.0)
            elif "bakome" in strat:
                exit_price, reason = self._exit_atr_based(pos, ind, current, direction, entry, trail_atr=2.0, hard_atr=3.0)
            else:
                # 通用：2%止损
                loss = (entry - current) / entry * 100
                if (direction == "BUY" and loss < -2) or (direction == "SELL" and loss < -2):
                    exit_price, reason = current, "通用止损2%"

            if exit_price:
                pnl = (exit_price - entry) if direction == "BUY" else (entry - exit_price)
                pos["status"] = "closed"
                pos["exit_price"] = exit_price
                pos["pnl"] = round(pnl, 2)
                pos["reason"] = reason
                to_close.append(pos)

        # 写入平仓记录（追加模式，同一个信号可能有多次更新，
        # 分析时取每个signal_id的最后一条记录即为最终结果）
        for pos in to_close:
            print(f"[平仓] #{pos['signal_id']} {pos['strategy']} {pos['direction']} "
                  f"入场={pos['entry_price']:.2f} 出场={pos['exit_price']:.2f} "
                  f"收益={pos['pnl']:.2f} 原因={pos.get('reason','')}")
            self.save_trade({
                "编号": pos["signal_id"], "时间": pos["time"],
                "策略": pos["strategy"], "方向": pos["direction"],
                "评分": pos["score"], "入场价格": f"{pos['entry_price']:.2f}",
                "出场价格": f"{pos.get('exit_price',0):.2f}",
                "收益": f"{pos.get('pnl',0):.2f}",
                "出场原因": pos.get("reason",""),
                "因子": pos.get("factors","")[:100],
            })

    def _exit_mfi_bb(self, pos, ind, current, mid, entry):
        """MFI-BB v5 出场逻辑"""
        bb = ind.get("bb")
        mfi = ind.get("mfi", 50)
        direction = pos["direction"]
        if not bb: return None, None

        # 存开仓时的BB宽度
        if not pos.get("entry_bb"):
            pos["entry_bb"] = {"width": bb["upper"] - bb["lower"], "mid": bb["mid"]}

        # ① 中轴平
        if direction == "BUY" and current >= bb["mid"]:
            return current, "BB中轴平"
        if direction == "SELL" and current <= bb["mid"]:
            return current, "BB中轴平"

        # ② 半宽平
        half = pos["entry_bb"]["width"] / 2
        if direction == "BUY" and current >= entry + half:
            return current, "BB半宽平"
        if direction == "SELL" and current <= entry - half:
            return current, "BB半宽平"

        # ③ 顺势平（另一极端+另一轨）
        if direction == "BUY" and mfi <= 20 and current <= bb["lower"]:
            return current, f"顺势平(MFI={mfi:.0f}穿下轨)"
        if direction == "SELL" and mfi >= 80 and current >= bb["upper"]:
            return current, f"顺势平(MFI={mfi:.0f}穿上轨)"

        return None, None

    def _exit_atr_based(self, pos, ind, current, direction, entry, trail_atr=1.5, hard_atr=3.0):
        """基于ATR的通用出场逻辑（大多数策略使用）"""
        atr = ind.get("atr") or ind.get("atr_20") or 10
        if direction == "BUY":
            profit = current - entry
            loss = entry - current
        else:
            profit = entry - current
            loss = current - entry

        # 追踪止盈（有盈利后回撤）
        if profit > atr * trail_atr * 0.5:
            key = "high" if direction == "BUY" else "low"
            pos.setdefault("peak", entry if direction == "BUY" else entry)
            if direction == "BUY":
                pos["peak"] = max(pos["peak"], current)
                dd = pos["peak"] - current
                if dd > atr * trail_atr:
                    return current, f"ATR追踪止盈(dd={dd:.1f})"
            else:
                pos["peak"] = min(pos["peak"], current)
                dd = current - pos["peak"]
                if dd > atr * trail_atr:
                    return current, f"ATR追踪止盈(dd={dd:.1f})"

        # 硬止损
        if loss > atr * hard_atr:
            return current, f"ATR硬止损(loss={loss:.1f})"

        # 利润回撤止盈（peak profit跌25%）
        if profit > atr * 0.5:
            pos.setdefault("peak_profit", profit)
            pos["peak_profit"] = max(pos["peak_profit"], profit)
            ratio = profit / pos["peak_profit"] if pos["peak_profit"] > 0 else 1
            if ratio < 0.75:
                return current, f"利润回撤止盈({profit:.1f}/{pos['peak_profit']:.1f})"

        return None, None

def main():
    trader = PaperTrader()
    print(f"纸面交易模拟器启动")
    print(f"当前持仓: {len(trader.positions)}")

    last_signal_count = 0
    while True:
        # 读取CSV获取新信号
        if not CSV_IN.exists():
            time.sleep(10)
            continue

        rows = []
        with open(CSV_IN, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                if r.get("signal_id") and r["signal_id"].isdigit():
                    rows.append(r)

        # 去重（取每个signal_id第一次出现）
        seen = set()
        for r in rows:
            sid = r["signal_id"]
            if sid not in seen:
                seen.add(sid)
                if sid not in trader.positions:
                    trader.open_position(r)

        # 检查出场
        trader.check_exits()

        now = datetime.now().strftime("%H:%M:%S")
        if len(seen) != last_signal_count:
            last_signal_count = len(seen)
            open_count = sum(1 for p in trader.positions.values() if p.get("status")=="open")
            closed_count = sum(1 for p in trader.positions.values() if p.get("status")=="closed")
            print(f"[{now}] 总信号={len(seen)} 持仓={open_count} 已平={closed_count}")

        time.sleep(30)

if __name__ == "__main__":
    main()
