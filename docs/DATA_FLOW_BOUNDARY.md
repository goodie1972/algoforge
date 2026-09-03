# 数据流分工边界（bar1 判定 / bar0 成交价 / forming 蜡烛仅展示）

> 本文档固化 AlgoForge XAUUSD 系统的**指标与报价数据分工边界**，作为 `CODE_REVIEW_STANDARD.md` 🔴 A 节"确认性指标只源自已闭合 K 线"的配套图示。
> 任何 PR 改动信号/运动员/数据层时，都必须遵守此边界。

---

## 0. 一句话结论

- **策略**：只用 `get_cache(tf)`（已闭合 bar1）做买卖判定。
- **运动员（athlete）**：用 `get_cache(tf)`（bar1）做 `_verify_entry` 复核 + 用 `get_tick()`（bar0 实时 ask/bid）做成交价。
- **DF 的 `candles[-1]`（forming bar）**：仅用于看板展示 + 策略合法的"价格/量触发"，**不在任何买卖判定路径上**。
- 运动员**不需要、也不应该**读 DF 的 forming 蜡烛。

---

## 1. 数据流图

```
                        MT4 终端 (FreeMT4Bridge EA)
                        ┌─────────────────────────────────────────┐
                        │  F042 取 K线(OHLCV)   → offset=0/1        │
                        │  F043 取指标           → shift=1(已闭合)   │
                        │  F020 取实时报价(ask/bid)                  │
                        └───────────┬───────────────┬───────────────┘
                                    │               │
                     ┌──────────────┴──────┐        │
                     │  DataFactory (DF)    │        │  bridge.get_tick_price()
                     │  ── 指标计算总线 ──   │        │  (独立 live quote 流)
                     │  get_cache(tf) 顶层  │        │
                     │   = 已闭合 bar1 指标 │        │
                     │                     │        │
                     │  candles[-1]         │        │
                     │   = forming bar0     │        │
                     │   (仅展示/价格触发)  │        │
                     └───┬─────────────┬────┘        │
                         │             │             │
          ┌──────────────┘             └────────┐     │
          │ 读取指标(bar1)                       │     │ 读取 ask/bid
          ▼                                      ▼     ▼
   ┌──────────────┐                    ┌──────────────────────┐
   │  策略 generate │                    │   运动员 athlete       │
   │  _signal      │                    │   _verify  → latest(bar1)│
   │  读 get_cache │                    │   _execute → tick ask/bid│
   │  (bar1 判定)  │                    │   (bar1 复核+bar0 成交价) │
   └──────┬───────┘                    └───────────┬──────────┘
          │ 信号(signal 对象)                       │ OrderSend
          └───────────────> 门票分发 ─────────────>│
                                                     ▼
                                                 MT4 下单 (F070/F071)
```

---

## 2. 各层读取来源表

| 角色 | 读什么 | 来源 | 用途 | 能否用 forming bar 指标 |
|---|---|---|---|---|
| **策略 generate_signal** | 指标 | `get_cache(tf)` 顶层 (= bar1) | 买卖判定 | ❌ 禁止 |
| **策略 价格/量触发** | OHLCV | `self.candles[-1]` forming | 阴阳线/振幅/放量触发 | 仅 OHLV 派生，❌ 指标 |
| **运动员 _verify** | 指标 | `get_cache(tf)` 顶层 (= bar1) | `_verify_entry` 复核 | ❌ 禁止 |
| **运动员 _execute** | 实时价 | `get_tick()` / `tick[ask/bid]` | 成交价 + 点差校验 | — (本就是 bar0 报价) |
| **DF candles[-1]** | forming 蜡烛 | `get_candles(offset=0)` | 看板 live candle | 仅展示，不参与判定 |
| **看板** | 实时 | `candles[-1]` | 行情展示 | 仅展示 |

---

## 3. 运动员入场数据流（精确到行）

```
athlete._verify  (L62–87)
  ├─ latest = get_cache(tf)                    # L74  bar1 已闭合指标
  ├─ tick["ask"]/tick["bid"] 仅做：
  │     ├─ 有效性检查 ask<=0 / ask<=bid 拒单     # L67–70
  │     └─ tick_price 触发价                     # L72
  └─ cls._verify_entry(signal, tick_price, latest, item)  # L82  指标复核用 latest(bar1)

athlete._execute (L91–135)
  ├─ price = tick["ask"] if BUY else tick["bid"]  # L106  bar0 实时成交价
  ├─ SL/TP 优先用信号里的(生成于 bar1 时刻)
  │     兜底用 signal["indicator_values"]["atr"]   # L113  bar1 ATR 快照
  └─ 新闻黑盒二次复查                              # L94–100  防竞态
```

**关键点**：运动员手里的 `tick` 来自 `get_tick()`（实时报价流），**不是 DF 的 `candles[-1]`**。它比 forming 蜡烛收盘价更实时、还带 spread（ask/bid），下单就该用这个。

---

## 4. 禁止路径（🔴 阻断）

- ❌ 策略在 `self.candles[-1]`（forming）上读取/自算任何指标做买卖判定。
- ❌ 运动员 `_verify_entry` 绕过传入的 `latest`，回读 `self.candles[-1]` 指标。
- ❌ 运动员用 forming 蜡烛的 `.close` 当成交价（必须用 `get_tick()` 的 ask/bid）。
- ❌ 策略内 `import talib/numpy` 自算买卖指标（见 `STRATEGY_SELF_COMPUTED_INDICATORS_AUDIT.md`）。

**允许（forming bar）**：OHLCV 及其派生（振幅、实体、阴阳、量比）做价格/量触发。

---

## 5. 边界检查清单（提交前）

- [ ] 策略买卖判定只调 `get_indicator()` / `get_cache` 顶层（bar1）
- [ ] 运动员 `_verify` 只传 `latest`（bar1），未回读 `candles[-1]`
- [ ] 运动员 `_execute` 成交价来自 `get_tick()` 的 ask/bid
- [ ] `candles[-1]` 仅用于 OHLV 触发/展示，未在其上做指标判定
