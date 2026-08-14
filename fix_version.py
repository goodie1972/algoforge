import re

with open('core/version.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''def check_remote_update() -> dict:
    """��查远程是否有新版本"""
    fetch_remote()
    behind = _git("rev-list", "--count", "HEAD..origin/main")
    count = int(behind) if behind.isdigit() else 0
    return {
        "has_update": count > 0,
        "behind_count": count,
    }'''

new = '''_remote_update_cache: dict | None = None
_remote_update_cache_time: float = 0
_REMOTE_CACHE_TTL = 300  # 5分钟��存


def check_remote_update() -> dict:
    """��查远程是否有新版本（带��存，��免��塞）"""
    global _remote_update_cache, _remote_update_cache_time
    import time
    now = time.time()
    
    # ��存有效则直接返回
    if _remote_update_cache and (now - _remote_update_cache_time) < _REMOTE_CACHE_TTL:
        return _remote_update_cache
    
    # 非��塞��试 fetch，设置极短超时
    try:
        subprocess.run(
            ["git", "-C", str(BASE_DIR), "fetch", "origin", "--quiet"],
            capture_output=True, timeout=3,
        )
    except Exception:
        pass  # ���略网��错误，使用已有的 refs
    
    behind = _git("rev-list", "--count", "HEAD..origin/main")
    count = int(behind) if behind.isdigit() else 0
    
    _remote_update_cache = {
        "has_update": count > 0,
        "behind_count": count,
    }
    _remote_update_cache_time = now
    return _remote_update_cache'''

if old in content:
    content = content.replace(old, new)
    with open('core/version.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('OK: replaced successfully')
else:
    print('NOT FOUND: old text not found')
    idx = content.find('def check_remote_update')
    if idx >= 0:
        print('Actual content around that:')
        print(repr(content[idx:idx+500]))