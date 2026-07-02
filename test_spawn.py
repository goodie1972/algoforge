#!/usr/bin/env python3
import sys, subprocess, os, json

# Parent process info (venv pythonw.exe)
print("PARENT:", json.dumps({
    'exe': sys.executable,
    'prefix': sys.prefix,
    'base_prefix': sys.base_prefix,
    'pid': os.getpid(),
    'VIRTUAL_ENV': os.environ.get('VIRTUAL_ENV', 'NOT SET'),
}))

# Base uv python path
base_python = r'C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe'

# Test 1: spawn base Python with the same env (no VIRTUAL_ENV)
result = subprocess.run(
    [base_python, '-c', 
     'import sys, os, json; print(json.dumps({"exe": sys.executable, "prefix": sys.prefix, "base_prefix": sys.base_prefix, "pid": os.getpid(), "VIRTUAL_ENV": os.environ.get("VIRTUAL_ENV", "NOT SET"), "PYTHONPATH": os.environ.get("PYTHONPATH", "NOT SET"), "aiohttp": "OK" if __import__("aiohttp") else "FAIL"}))'],
    capture_output=True, text=True,
    env={**os.environ},
)
print("CHILD_DIRECT:", result.stdout.strip())
print("CHILD_ERR:", result.stderr.strip()[:200] if result.stderr else "(none)")

# Test 2: spawn base Python with VIRTUAL_ENV set
result2 = subprocess.run(
    [base_python, '-c',
     'import sys, os, json; print(json.dumps({"VIRTUAL_ENV": os.environ.get("VIRTUAL_ENV", "NOT SET"), "PYTHONPATH": os.environ.get("PYTHONPATH", "NOT SET"), "prefix": sys.prefix, "aiohttp": "OK" if __import__("aiohttp") else "FAIL"}))'],
    capture_output=True, text=True,
    env={**os.environ, 'VIRTUAL_ENV': r'C:\Users\Administrator\AppData\Local\hermes\hermes-agent\venv'},
)
print("CHILD_WITH_VENV:", result2.stdout.strip())

# Test 3: spawn base Python with PYTHONPATH set to venv site-packages
venv_site = r'C:\Users\Administrator\AppData\Local\hermes\hermes-agent\venv\Lib\site-packages'
result3 = subprocess.run(
    [base_python, '-c',
     'import sys, os, json; print(json.dumps({"PYTHONPATH": os.environ.get("PYTHONPATH", "NOT SET"), "prefix": sys.prefix, "aiohttp": "OK" if __import__("aiohttp") else "FAIL"}))'],
    capture_output=True, text=True,
    env={**os.environ, 'PYTHONPATH': venv_site},
)
print("CHILD_WITH_PYTHONPATH:", result3.stdout.strip())
