
# -*- coding: utf-8 -*-
"""
main.tex 靜態檢查
════════════════════════════════════════════════════════════════════════

本機沒有 LaTeX 工具鏈（pdflatex / bibtex 皆未安裝），無法編譯驗證，
所以在送去編譯之前先用這支抓明顯錯誤。**不能取代真正的編譯。**

檢查項目：
  1. \begin / \end 環境配對
  2. 行內數學 $ 成對；不得出現 $$
  3. 大括號平衡
  4. tabular 宣告欄數 vs 各列實際欄數
  5. \ref → \label、\cite → refs.bib 的對應，以及 bib 有無未被引用的條目
     （每筆文獻都必須在正文被引用過）
  6. 殘留的佔位符

用法：python paper/lint_tex.py
"""
import io
import os
import re
import sys
import collections

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
TEX = os.path.join(HERE, 'main.tex')
BIB = os.path.join(HERE, 'refs.bib')

bad = 0


def err(msg):
    global bad
    bad += 1
    print(f'   ✘ {msg}')


def grab_spec(txt, i):
    """取出 \\begin{tabular}{...} 的欄位規格，正確處理巢狀括號 p{3.1cm}。"""
    d, j = 0, i
    while j < len(txt):
        if txt[j] == '{':
            d += 1
        elif txt[j] == '}':
            d -= 1
            if d == 0:
                return txt[i+1:j], j+1
        j += 1
    return '', i


def main():
    L = open(TEX, encoding='utf-8').read().split('\n')
    s = '\n'.join(L)
    print('══ main.tex 靜態檢查 ══\n')

    # 1. 環境配對
    envs = collections.Counter()
    for m in re.finditer(r'\\(begin|end)\{([a-zA-Z*]+)\}', s):
        envs[m.group(2)] += (1 if m.group(1) == 'begin' else -1)
    print('── 環境配對 ──')
    for k, v in sorted(envs.items()):
        if v:
            err(f'環境 {k} 不平衡（begin−end = {v:+d}）')
    if not any(envs.values()):
        print('   ✓ 全部平衡')

    # 2. 數學模式
    print('\n── 數學模式 ──')
    inline = len(re.findall(r'(?<!\\)\$', s.replace('$$', '')))
    if inline % 2:
        err(f'行內 $ 數量為奇數（{inline}）')
    else:
        print(f'   ✓ 行內 $ 成對（{inline} 個）')
    if '$$' in s:
        err('出現 $$（LaTeX 應避免，且常是文字轉換的 bug）')
    else:
        print('   ✓ 無 $$')

    # 3. 大括號
    print('\n── 大括號 ──')
    depth, minline = 0, None
    for i, ln in enumerate(L, 1):
        # ⚠ 順序很重要：必須先移除**所有**跳脫字元（含 \%），再剝註解。
        #   先剝註解會把 \% 當成註解起點，吃掉後面的 )} 造成假的不平衡。
        t = re.sub(r'\\[{}%&_#$]', '', ln)
        t = re.sub(r'(?<!\\)%.*$', '', t)
        depth += t.count('{')-t.count('}')
        if depth < 0 and minline is None:
            minline = i
    if depth:
        err(f'大括號不平衡：淨 {depth:+d}'
            + (f'（第 {minline} 行首度為負）' if minline else ''))
    else:
        print('   ✓ 平衡')

    # 4. 表格欄數
    print('\n── 表格欄數 ──')
    for m in re.finditer(r'\\begin\{tabular\}', s):
        spec, e = grab_spec(s, m.end())
        body = s[e:s.find(r'\end{tabular}', e)]
        # 先移掉 p{...} 再數 lcr，否則 "3.1cm" 裡的 c 會被誤計
        ncol = (len(re.findall(r'p\{[^}]*\}', spec))
                + len(re.findall(r'[lcr]', re.sub(r'p\{[^}]*\}', '', spec))))
        ln0 = s[:m.start()].count('\n')+1
        for row in body.split('\\\\'):
            row = re.sub(r'\\(toprule|midrule|bottomrule)', '', row).strip()
            if not row:
                continue
            n = row.count('&')+1
            if n != ncol:
                err(f'第 {ln0} 行的 tabular 宣告 {ncol} 欄，'
                    f'某列有 {n} 欄 → {row[:60]}')
                break
        else:
            print(f'   ✓ 第 {ln0} 行的 tabular（{ncol} 欄）')

    # 5. 引用／標籤
    print('\n── 引用／標籤 ──')
    labels = set(re.findall(r'\\label\{([^}]*)\}', s))
    refs = set(re.findall(r'\\ref\{([^}]*)\}', s))
    miss = refs-labels
    if miss:
        err(f'\\ref 指向不存在的 label：{sorted(miss)}')
    else:
        print(f'   ✓ 全部 {len(refs)} 個 \\ref 都有對應 label')
    unused = labels-refs
    if unused:
        print(f'   · 未被引用的 label（可接受）：{sorted(unused)}')

    bib = set(re.findall(r'@\w+\{([^,]+),', open(BIB, encoding='utf-8').read()))
    cites = set()
    for m in re.finditer(r'\\cite\{([^}]*)\}', s):
        cites |= {c.strip() for c in m.group(1).replace('%', '').split(',')
                  if c.strip()}
    if cites-bib:
        err(f'\\cite 指向 bib 沒有的 key：{sorted(cites-bib)}')
    else:
        print(f'   ✓ 全部 {len(cites)} 個 cite key 都在 refs.bib')
    if bib-cites:
        err(f'refs.bib 有未被引用的條目：{sorted(bib-cites)}'
            '（每筆文獻都必須在正文被引用）')
    else:
        print(f'   ✓ refs.bib 的 {len(bib)} 筆全部被引用')

    # 6. 殘留
    print('\n── 殘留 ──')
    for pat, nm in ((r'\\SI\{', 'siunitx \\SI'), (r'\\si\{', 'siunitx \\si'),
                    (r'<corresponding', '作者信箱佔位符')):
        k = len(re.findall(pat, s))
        if k:
            print(f'   · {nm}：{k} 處')

    print(f"\n{'✓ 未發現阻斷性問題' if not bad else f'✘ 發現 {bad} 個問題'}")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
