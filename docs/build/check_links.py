# -*- coding: utf-8 -*-
"""搬完 docs/ 之後的驗收：所有引用都還指得到真實檔案嗎？

兩類：
  a) 任何檔案裡出現的 `docs/<...>` 路徑
  b) docs/ 底下 .md 之間的相對連結 [文字](路徑)

⚠ 這支是搬檔的驗收條件，不是可有可無的檢查。死連結不會報錯、不會有人
  發現，只會在某天有人點下去時安靜地 404。
"""
import io, os, re, sys

# repo 根目錄＝本檔的上上上層（docs/build/ -> docs/ -> repo）
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKIP = ('.git', 'node_modules', 'venv', '__pycache__', 'Testing_data', 'dist')

files = []
for dp, dn, fn in os.walk(ROOT):
    if any(x in dp for x in SKIP):
        continue
    for f in fn:
        if f.endswith(('.md', '.py', '.bat', '.js', '.vue', '.txt')) or f == '.gitignore':
            files.append(os.path.join(dp, f))

bad_a, bad_b, n_a, n_b = [], [], 0, 0
RX_DOCS = re.compile(r'docs/[^\s`"\'\)\],;：、]+\.(?:md|py|pptx|xlsx|docx|png|csv)')
RX_LINK = re.compile(r'\[[^\]]*\]\(([^)\s]+)\)')

for p in files:
    try:
        s = io.open(p, encoding='utf-8').read()
    except (OSError, UnicodeDecodeError):
        continue
    rp = os.path.relpath(p, ROOT)

    for m in RX_DOCS.finditer(s):
        # 誤報排除：萬用字元不是路徑；腳本檔頭寫的是**輸出**位置，
        # 那個檔案還沒被產生出來是正常的。
        if '*' in m.group(0):
            continue
        if p.endswith('.py') and 'analysis_charts' in m.group(0):
            continue
        n_a += 1
        target = os.path.join(ROOT, m.group(0).replace('/', os.sep))
        if not os.path.exists(target):
            bad_a.append('%s  ->  %s' % (rp, m.group(0)))

    if p.endswith('.md'):
        here = os.path.dirname(p)
        for m in RX_LINK.finditer(s):
            t = m.group(1)
            if t.startswith(('http://', 'https://', '#', 'mailto:')):
                continue
            t = t.split('#')[0]
            if not t:
                continue
            n_b += 1
            cand = os.path.normpath(os.path.join(here, t.replace('/', os.sep)))
            if not os.path.exists(cand):
                bad_b.append('%s  ->  %s' % (rp, m.group(1)))

print('檢查 %d 個檔案' % len(files))
print('a) docs/ 路徑引用：%d 個，壞掉 %d 個' % (n_a, len(bad_a)))
for b in sorted(set(bad_a)):
    print('   ★', b)
print('b) markdown 相對連結：%d 個，壞掉 %d 個' % (n_b, len(bad_b)))
for b in sorted(set(bad_b))[:40]:
    print('   ★', b)
sys.exit(1 if (bad_a or bad_b) else 0)
