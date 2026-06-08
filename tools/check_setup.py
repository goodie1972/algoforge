"""
系统自检脚本 - 验证环境是否就绪
用法: python tools/check_setup.py
"""

import os
import sys
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check_python():
    print(f"{'='*50}")
    print(f"Python: {sys.version}")
    print(f"路径: {sys.executable}")
    return True


def check_dependencies():
    print(f"\n{'='*50}")
    print("依赖检查:")
    deps = {
        "pandas": "回测框架",
        "numpy": "数值计算",
    }
    optional = {
        "metaapi_cloud_sdk": "MetaApi 云端桥接（可选）",
    }

    all_ok = True
    for pkg, desc in {**deps, **optional}.items():
        try:
            mod = __import__(pkg)
            ver = getattr(mod, "__version__", "unknown")
            status = "OK" if pkg in deps else "OPTIONAL"
            print(f"  [{status}] {pkg} {ver}  ({desc})")
        except ImportError:
            if pkg in deps:
                print(f"  [FAIL] {pkg} 未安装 ({desc})")
                all_ok = False
            else:
                print(f"  [SKIP] {pkg} 未安装 ({desc})")
    return all_ok


def check_project_files():
    print(f"\n{'='*50}")
    print("项目文件:")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    required = [
        "main.py",
        "run.py",
        "config/settings.py",
        "core/bridge.py",
        "core/freemt4_bridge.py",
        "strategies/v6_hybrid.py",
        "backtest/run_backtest.py",
    ]
    all_ok = True
    for f in required:
        path = os.path.join(root, f)
        exists = os.path.exists(path)
        size = os.path.getsize(path) if exists else 0
        status = "OK" if exists else "MISSING"
        print(f"  [{status}] {f} ({size} bytes)")
        if not exists:
            all_ok = False
    return all_ok


def check_mt4():
    print(f"\n{'='*50}")
    print("MT4 检测:")
    # 检查常见安装路径
    paths = [
        r"C:\Program Files (x86)\MetaTrader 4",
        r"C:\Program Files\MetaTrader 4",
        r"C:\Program Files (x86)\Hantec",
        r"C:\Program Files\Hantec",
    ]
    for p in paths:
        if os.path.exists(p):
            print(f"  [FOUND] {p}")
            terminal = os.path.join(p, "terminal.exe")
            if os.path.exists(terminal):
                print(f"          terminal.exe 存在")
            return True

    print("  [NOT FOUND] 未检测到 MT4 安装")
    print("  请手动安装:")
    print("    1. 从 https://www.metatrader4.com/en/download 下载")
    print("    2. 或从亨达官网下载定制版 MT4")
    print("    3. 安装后重启此脚本重新检测")
    return False


def check_freemt4_ea():
    print(f"\n{'='*50}")
    print("FreeMT4 Bridge EA 检测:")
    import socket
    from config.settings import FREEMT4_HOST, FREEMT4_PORT
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((FREEMT4_HOST, FREEMT4_PORT))
        s.close()
        print(f"  [OK] FreeMT4 EA 正在监听 {FREEMT4_HOST}:{FREEMT4_PORT}")
        return True
    except Exception:
        print(f"  [NOT RUNNING] 无法连接 {FREEMT4_HOST}:{FREEMT4_PORT}")
        print("  请确认:")
        print("    1. MT4 已运行")
        print("    2. FreeMT4Bridge EA 已加载到图表上")
        print("    3. EA 端口配置与 config/settings.py 一致 (默认 23232)")
        return False


def check_backtest_data():
    print(f"\n{'='*50}")
    print("回测数据:")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(root, "data")
    if os.path.exists(data_dir):
        files = os.listdir(data_dir)
        if files:
            for f in files:
                path = os.path.join(data_dir, f)
                size = os.path.getsize(path)
                print(f"  [FOUND] {f} ({size:,} bytes)")
            return True
    print("  [EMPTY] data/ 目录无数据文件")
    print("  运行 python backtest/generate_sample_data.py 生成示例数据")
    return False


def main():
    print("\n" + "=" * 50)
    print("  XAUUSD 量化系统 - 环境自检")
    print("=" * 50)

    results = {
        "Python 环境": check_python(),
        "依赖包": check_dependencies(),
        "项目文件": check_project_files(),
        "MT4 终端": check_mt4(),
        "FreeMT4 Bridge EA": check_freemt4_ea(),
        "回测数据": check_backtest_data(),
    }

    print(f"\n{'='*50}")
    print("  总览")
    print(f"{'='*50}")
    for name, ok in results.items():
        status = "PASS" if ok else "NEED ATTENTION"
        print(f"  [{status}] {name}")

    # 给出下一步建议
    mt4_ok = results.get("MT4 终端", False)
    freemt4_ok = results.get("FreeMT4 Bridge EA", False)
    data_ok = results.get("回测数据", False)

    print(f"\n{'='*50}")
    if not mt4_ok:
        print("  下一步: 请先安装 MT4 终端")
    elif not freemt4_ok:
        print("  下一步: 请在 MT4 中加载 FreeMT4Bridge EA")
    elif not data_ok:
        print("  下一步: 从 MT4 导出历史数据到 data/ 目录")
    else:
        print("  一切就绪! 运行 python run.py 启动交易引擎")
        print("  默认策略: V6 Hybrid（双向网格 + ATR 止损）")
        print("  也可通过 python main.py --strategy 选择其他策略")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
