#!/usr/bin/env python3
import sys, subprocess, os, json

# What does sys.executable return in the child?
venv_python = r'C:\Users\Administrator\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe'

# Test: spawn venv python with same env, what is sys.executable in child?
result = subprocess.run(
    [venv_python, '-c',
     'import sys, os, json; print("EXE:", sys.executable, "PREFIX:", sys.prefix, "BASE:", sys.base_prefix)'],
    capture_output=True, text=True,
    env={**os.environ},
)
print("VENV_PYTHON_CHILD:", result.stdout.strip())

# Same but with pythonw.exe
venv_pythonw = r'C:\Users\Administrator\AppData\Local\hermes\hermes-agent\venv\Scripts\pythonw.exe'
result2 = subprocess.run(
    [venv_pythonw, '-c',
     'import sys, os, json; print("EXE:", sys.executable, "PREFIX:", sys.prefix, "BASE:", sys.base_prefix)'],
    capture_output=True, text=True,
    env={**os.environ},
)
print("VENV_PYTHONW_CHILD:", result2.stdout.strip())
print("VENV_PYTHONW_ERR:", result2.stderr.strip()[:200] if result2.stderr else "(none)")
