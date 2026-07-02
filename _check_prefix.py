import sys, os
with open("D:\\backup\\baobao\\pythonprogram\\xauusd\\_test_prefix2.txt", "w") as f:
    f.write(f"EXE={sys.executable}\n")
    f.write(f"PREFIX={sys.prefix}\n")
    f.write(f"BASE={sys.base_prefix}\n")
    f.write(f"Has aiohttp: {__import__('aiohttp').__version__}\n")
    f.write(f"PYTHONPATH={os.environ.get('PYTHONPATH', 'NOT SET')}\n")
os._exit(0)
