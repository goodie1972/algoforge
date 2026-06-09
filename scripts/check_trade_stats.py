"""Compare yesterday vs today trade and market stats"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from data.database import get_conn
conn = get_conn()

# Yesterday trades (June 8)
yest = conn.execute("""
  SELECT strategy, COUNT(*) as cnt,
         ROUND(SUM(pnl),2) as total_pnl,
         ROUND(AVG(pnl),2) as avg_pnl,
         ROUND(AVG(ABS(entry_price-exit_price)),2) as avg_move
  FROM trades
  WHERE close_time >= '2026-06-08' AND close_time < '2026-06-09'
  GROUP BY strategy
""").fetchall()
print('=== 昨日交易统计 (6月8日) ===')
for r in yest:
    print(f'  {r["strategy"]:20s} | {r["cnt"]:2d} 单 | 总盈亏={r["total_pnl"]:>7.2f} | 均盈亏={r["avg_pnl"]:>6.2f} | 均价差={r["avg_move"]:>5.2f}')

# Today trades (June 9)
today = conn.execute("""
  SELECT strategy, COUNT(*) as cnt,
         ROUND(SUM(pnl),2) as total_pnl,
         ROUND(AVG(pnl),2) as avg_pnl
  FROM trades
  WHERE close_time >= '2026-06-09'
  GROUP BY strategy
""").fetchall()
print()
print('=== 今日交易统计 (6月9日) ===')
for r in today:
    print(f'  {r["strategy"]:20s} | {r["cnt"]:2d} 单 | 总盈亏={r["total_pnl"]:>7.2f} | 均盈亏={r["avg_pnl"]:>6.2f}')
if not today:
    print('  (无已平仓交易)')

# Price range comparison
prices_yest = conn.execute("""
  SELECT MIN(low) as min_p, MAX(high) as max_p FROM ohlcv
  WHERE timeframe='H1' AND timestamp >= strftime('%s','2026-06-08') AND timestamp < strftime('%s','2026-06-09')
""").fetchone()
prices_today = conn.execute("""
  SELECT MIN(low) as min_p, MAX(high) as max_p FROM ohlcv
  WHERE timeframe='H1' AND timestamp >= strftime('%s','2026-06-09')
""").fetchone()
print()
print('=== 价格范围对比 (H1周期) ===')
if prices_yest and prices_yest["min_p"]:
    rng = prices_yest["max_p"] - prices_yest["min_p"]
    print(f'  昨日: {prices_yest["min_p"]:.2f} ~ {prices_yest["max_p"]:.2f} (跨度 ${rng:.2f})')
if prices_today and prices_today["min_p"]:
    rng = prices_today["max_p"] - prices_today["min_p"]
    print(f'  今日: {prices_today["min_p"]:.2f} ~ {prices_today["max_p"]:.2f} (跨度 ${rng:.2f})')

# Strategy breakdown for yesterday
print()
print('=== 昨日策略活跃度 ===')
strat_detail = conn.execute("""
  SELECT strategy, order_type, COUNT(*) as cnt, ROUND(SUM(pnl),2) as pnl
  FROM trades WHERE close_time >= '2026-06-08' AND close_time < '2026-06-09'
  GROUP BY strategy, order_type
  ORDER BY strategy
""").fetchall()
for r in strat_detail:
    print(f'  {r["strategy"]:20s} {r["order_type"]:6s} | {r["cnt"]:2d} 单 | 盈亏={r["pnl"]:>7.2f}')

conn.close()
