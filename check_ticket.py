import json, sys
with open(sys.argv[1], 'r', encoding='utf-8') as f:
    data = json.load(f)
for t in data:
    if t['ticket'] == 90116635:
        print(json.dumps(t, indent=2, ensure_ascii=False))
        break
