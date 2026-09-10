
# -*- coding: utf-8 -*-
"""
組裝 .docx 並執行三項規範驗證
════════════════════════════════════════════════════════════════════════
用法：python paper/make_docx.py

V1  每個 Fig./Table 都在內文被交叉引用（Springer：圖表必須在內文 cross-refer）
V2  每筆文獻都被引用，且每個引用都有對應文獻
    ——直接對應使用者要求：「不能出現沒有這篇 paper，或這篇 paper 沒有這個內容引用」
V3  引用編號嚴格依首次出現順序（Springer：sequential by order of citation）
V4  摘要字數 15–250（Springer 明文規定）
任一失敗即不產出檔案。
"""
import os
import re
import sys

from docx import Document

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import build_docx as B                                             # noqa: E402
import docx_body as B1                                             # noqa: E402
import docx_body2 as B2                                            # noqa: E402
import docx_body3 as B3                                            # noqa: E402


def main():
    doc = Document()
    B.setup(doc)

    B1.front_matter(doc)
    B1.sec_intro(doc)
    B1.sec_related(doc)
    B1.sec_data(doc)
    B2.sec_pipeline(doc)
    B3.sec_results(doc)
    B3.sec_edge(doc)
    B3.sec_limits(doc)
    B3.sec_conclusion(doc)
    B3.sec_refs(doc)

    print('══ Springer 規範驗證 ══\n')
    bad = 0

    # ── V1 圖表交叉引用 ──────────────────────────────────
    print('── V1  圖表必須在內文交叉引用 ──')
    xr = set(B.XREFS)
    for item in B.FIGS_DEFINED + B.TABLES_DEFINED:
        if item in xr:
            print(f'   ✓ {item} 有交叉引用')
        else:
            print(f'   ✘ {item} **未在內文引用**')
            bad += 1
    ghost = xr - set(B.FIGS_DEFINED) - set(B.TABLES_DEFINED)
    if ghost:
        print(f'   ✘ 內文引用了不存在的圖表：{sorted(ghost)}')
        bad += 1

    # ── V2 文獻 ↔ 引用 ───────────────────────────────────
    print('\n── V2  文獻與引用必須一一對應 ──')
    keys = {k for k, _ in B.REFS}
    used = set(B.CITED)
    if used - keys:
        print(f'   ✘ 引用了不存在的文獻：{sorted(used-keys)}'); bad += 1
    else:
        print(f'   ✓ 全部 {len(used)} 個被引用的 key 都有對應文獻')
    if keys - used:
        print(f'   ✘ 文獻表有未被引用的條目：{sorted(keys-used)}'); bad += 1
    else:
        print(f'   ✓ 文獻表 {len(keys)} 筆全部在內文被引用')

    # ── V3 引用順序 ──────────────────────────────────────
    print('\n── V3  引用編號須依首次出現順序 ──')
    first, seen = [], set()
    for k in B.CITED:
        if k not in seen:
            seen.add(k); first.append(k)
    expect = [k for k, _ in B.REFS]
    if first == expect:
        print(f'   ✓ {len(first)} 筆文獻的編號與首次出現順序一致')
    else:
        print('   ✘ 編號與首次出現順序不符')
        for i, (a, b) in enumerate(zip(first, expect), 1):
            if a != b:
                print(f'      位置 {i}：首次出現的是 {a}，但編號給了 {b}')
        bad += 1

    # ── V4 摘要字數 ──────────────────────────────────────
    print('\n── V4  摘要 15–250 字 ──')
    n = len(re.findall(r'\S+', B1.ABSTRACT))
    print(f'   摘要 {n} 字   → {"✓ 合規" if 15 <= n <= 250 else "✘ 超出範圍"}')
    if not (15 <= n <= 250):
        bad += 1

    print()
    if bad:
        print(f'✘ 發現 {bad} 個問題，**未產出檔案**')
        return 1

    doc.save(B.OUT)
    sz = os.path.getsize(B.OUT)/1048576
    print(f'✓ 全部通過\n\n輸出 → {B.OUT}  ({sz:.1f} MB)')
    print(f'   圖 {len(B.FIGS_DEFINED)} 張   表 {len(B.TABLES_DEFINED)} 個   '
          f'文獻 {len(B.REFS)} 筆')
    return 0


if __name__ == '__main__':
    sys.exit(main())
