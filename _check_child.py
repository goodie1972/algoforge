import sys, os, subprocess, time, tempfile

"""Check what sys.prefix the UV launcher spawns for the child process."""
import sys, os

# Write a quick script that checks the child's python state
script = r'''import sys, os
with open(r"C:\Users\Administrator\AppData\Local\hermes\_child_check.txt", "w") as f:
    f.write(f"EXE={sys.executable}\n")
    f.write(f"PREFIX={sys.prefix}\n")
    f.write(f"BASE={sys.base_prefix}\n")
    f.write(f"PYTHONPATH={os.environ.get('PYTHONPATH', 'NOT_SET')}\n")
    f.write(f"VIRTUAL_ENV={os.environ.get('VIRTUAL_ENV', 'NOT_SET')}\n")
    for i, p in enumerate(sys.path):
        if 'site-packages' in p:
            f.write(f"  PATH[{i}]={p}\n")
    try:
        import aiohttp
        f.write(f"aiohttp={aiohttp.__version__} FROM={aiohttp.__file__}\n")
    except ImportError as e:
        f.write(f"aiohttp=FAIL {e}\n")
    try:
        import httpx
        f.write(f"httpx={httpx.__version__} FROM={httpx.__file__}\n")
    except ImportError as e:
        f.write(f"httpx=FAIL {e}\n")
'''

# Run it via the launcher
proc = subprocess.Popen(
    [r"C:\Users\Administrator\AppData\Local\hermes\hermes-agent\venv\Scripts\pythonw.exe",
     "-c", script],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)
proc.wait(timeout=10)
time.sleep(2)

# Read result
result_path = r"C:\Users\Administrator\AppData\Local\hermes\_child_check.txt"
if os.path.exists(result_path):
    with open(result_path) as f:
        print(f.read())
else:
    print("No result file")
