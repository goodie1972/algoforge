"""
生成示例回测数据（用于测试回测框架）
实际使用时请从 MT4 导出真实数据
"""

import os
import random
from datetime import datetime, timedelta

import pandas as pd


def generate_sample_xauusd_data(
    start: str = "2024-01-01",
    end: str = "2025-01-01",
    timeframe_hours: int = 1,
    initial_price: float = 2060.0,
    output_path: str = "data/XAUUSD_H1.csv",
):
    """生成模拟 XAUUSD H1 K线数据"""
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")

    records = []
    price = initial_price
    current = start_dt

    while current < end_dt:
        # 跳过周末
        if current.weekday() >= 5:
            current += timedelta(hours=timeframe_hours)
            continue

        # 随机波动（简化模型）
        volatility = random.gauss(0, 0.001)
        trend = 0.00002  # 轻微上升趋势
        change = price * (volatility + trend)

        open_price = price
        close_price = price + change
        high_price = max(open_price, close_price) + abs(random.gauss(0, 0.5))
        low_price = min(open_price, close_price) - abs(random.gauss(0, 0.5))
        volume = random.randint(100, 1000)

        records.append({
            "time": current.strftime("%Y-%m-%d %H:%M:%S"),
            "open": round(open_price, 2),
            "high": round(high_price, 2),
            "low": round(low_price, 2),
            "close": round(close_price, 2),
            "volume": volume,
        })

        price = close_price
        current += timedelta(hours=timeframe_hours)

    df = pd.DataFrame(records)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"已生成 {len(df)} 条模拟K线数据 -> {output_path}")
    print(f"价格范围: {df['close'].min():.2f} ~ {df['close'].max():.2f}")


if __name__ == "__main__":
    generate_sample_xauusd_data()
