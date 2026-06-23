# MTF 共振 H1 策略 (mtf_resonance_h1)

## 概述

- **策略名称：** `mtf_resonance_h1`
- **类名：** `MTFResonanceStrategy`
- **Magic Number：** `660801`
- **运行周期：** H1（1 小时）
- **策略类型：** 多周期共振

## 入场逻辑

H1 K 线收盘后检测 TA-Lib 形态，同窗口 M15 有同向信号时开仓。

- 使用 TA-Lib 的 CDL 形态识别函数
- 形态质量过滤器确保信号可靠性
- H1 形态 + M15 同向信号 = 共振确认

## 出场逻辑

三层退出机制，标准趋势感知乘数。
