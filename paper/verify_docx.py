
# -*- coding: utf-8 -*-
"""
.docx 交付前驗證：向量圖是否內嵌、版面是否合規、頁數是否 ≤ 11
════════════════════════════════════════════════════════════════════════

本機沒有 Word / LibreOffice，**無法真正算繪頁數**，所以頁數只能是估算。
估算方式明說如下，避免把估計值當成量測值：

  · LNCS 文字區 122 × 193 mm；10 pt Times 單行間距 ≈ 4.1 mm 行高
    ⇒ 每頁約 47 行
  · 122 mm 寬、10 pt Times 每行約 82 個字元
  · 圖片高度由 PNG 的實際長寬比換算（寬度固定 122 mm）
  · 表格、圖說、演算法各自以其字級估行數

⚠ 估計值有誤差，最終仍須在 Word 開啟確認。若估算超過 11 頁就一定要處理。
"""
import os
import re
import sys
import zipfile
from xml.etree import ElementTree as ET

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from PIL import Image                                              # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
# 與 tex_to_docx.py 用同一個出口，Word 開著時仍可驗證暫存版。
DOCX = os.environ.get('ICEA_OUT') or os.path.join(HERE, 'ICEA2026_Li_et_al.docx')
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'

TEXT_W_MM, TEXT_H_MM = 122.0, 193.0
LINE_MM = 4.10                     # 10 pt Times 單行
CPL_10 = 82                        # 每行字元數 @10 pt
PAGE_LINES = TEXT_H_MM/LINE_MM


def main():
    print('══ .docx 交付前驗證 ══\n')
    if not os.path.exists(DOCX):
        print('   ✘ 找不到檔案'); return 1
    z = zipfile.ZipFile(DOCX)
    names = z.namelist()

    # ── 向量圖 ──────────────────────────────────────────
    svgs = [n for n in names if n.lower().endswith('.svg')]
    pngs = [n for n in names if n.lower().endswith('.png')]
    doc_xml = z.read('word/document.xml').decode('utf-8')
    ct = z.read('[Content_Types].xml').decode('utf-8')
    nblip = doc_xml.count('svgBlip')
    print('── 向量圖內嵌 ──')
    print(f'   SVG 影像組件      {len(svgs)}')
    print(f'   PNG 後備圖        {len(pngs)}')
    print(f'   svgBlip 參照      {nblip}')
    print(f'   Content_Types 宣告 svg+xml   '
          f'{"✓" if "image/svg+xml" in ct else "✘"}')
    # ⚠ 圖數不可寫死 4。加入階梯式分壓設備圖後變成 5 張，寫死的檢查會
    #   誤報失敗。條件應該是「每張圖都有 SVG＋svgBlip＋PNG 後備」。
    ok_vec = (len(svgs) > 0 and len(svgs) == nblip == len(pngs))
    print(f'   → {f"✓ {len(svgs)} 張圖都是向量（附點陣後備）" if ok_vec else "✘ 向量內嵌不完整"}')

    # ── 字型與字級 ──────────────────────────────────────
    root = ET.fromstring(doc_xml)
    fonts, sizes = {}, {}
    for r in root.iter(f'{{{W}}}rPr'):
        f = r.find(f'{{{W}}}rFonts')
        if f is not None:
            v = f.get(f'{{{W}}}ascii')
            if v:
                fonts[v] = fonts.get(v, 0)+1
        s = r.find(f'{{{W}}}sz')
        if s is not None:
            v = int(s.get(f'{{{W}}}val'))/2
            sizes[v] = sizes.get(v, 0)+1
    print('\n── 字型與字級 ──')
    for k, v in sorted(fonts.items(), key=lambda x: -x[1]):
        print(f'   {k:<20}{v:>6} runs')
    for k, v in sorted(sizes.items()):
        print(f'   {k:>4.0f} pt{"":<14}{v:>6} runs')
    bad = [k for k in fonts if k not in ('Times New Roman', 'Courier New')]
    print(f'   → {"✓ 僅用允許的字型" if not bad else f"✘ 非預期字型 {bad}"}')

    # ── 頁數估算 ────────────────────────────────────────
    paras = list(root.iter(f'{{{W}}}p'))
    lines = 0.0
    for p in paras:
        txt = ''.join(t.text or '' for t in p.iter(f'{{{W}}}t'))
        sz = 10.0
        s = p.find(f'.//{{{W}}}sz')
        if s is not None:
            sz = int(s.get(f'{{{W}}}val'))/2
        cpl = CPL_10*(10.0/sz)
        n = max(1, int(len(txt)/cpl)+(1 if len(txt) % cpl else 0)) if txt \
            else 0.35
        lines += n*(sz/10.0)
    img_mm = 0.0
    for n in pngs:
        with z.open(n) as fh:
            w, h = Image.open(fh).size
        img_mm += TEXT_W_MM*h/w
    lines += img_mm/LINE_MM
    est = lines/PAGE_LINES
    print('\n── 頁數估算（非量測，須在 Word 覆核）──')
    print(f'   段落 {len(paras)}   估計文字行數 {lines-img_mm/LINE_MM:.0f}')
    print(f'   圖片總高 {img_mm:.0f} mm  =  {img_mm/LINE_MM:.0f} 行')
    print(f'   估計頁數 ≈ {est:.1f} / 11')
    # 上限 11 頁（2026-08-12 定案；使用者實測 10.3 頁時判定可接受，
    # 並要求把空間用到 10.8–10.9）。這裡的 est 是粗估，實測校準後的
    # 換算是「版面模擬值 + 0.49」，最終仍以 Word 為準。
    ok_pg = est <= 11.0
    print(f'   → {"✓ 在上限內" if ok_pg else "✘ **超過 11 頁，必須刪減**"}')

    # ── 記號稽核 ────────────────────────────────────────
    #   內文、公式、演算法、圖說、表格必須用**同一套**排法。
    #   會出現在成品裡就是錯的：未展開的標記、殘留的 LaTeX、
    #   以及冒充下標的上標字元（Unicode 沒有下標 b）。
    print('\n── 記號稽核 ──')
    # ⚠ 大括號在演算法裡是**集合符號**（{0.01, ...}、{C, L, S}），不是殘留。
    #   只稽核內文（Times）的 run，程式碼（Courier）的 run 略過。
    # ⚠ 演算法區塊要整段排除，不能只排除 Courier 的 run：
    #   `Input:／Parameter:／Output:` 與行號行是用 Times 排的，而其中的
    #   `K = {0.01, …}`、`F = {C, L, S}` 是**集合符號**不是殘留大括號。
    ALG = re.compile(r'^(Input|Parameter|Output)\s*:|^\s*\d+:\t')
    skip = set()
    for p in root.iter(f'{{{W}}}p'):
        t = ''.join(x.text or '' for x in p.iter(f'{{{W}}}t'))
        if ALG.match(t):
            for r in p.iter(f'{{{W}}}r'):
                skip.add(id(r))
    txt = ''
    for r in root.iter(f'{{{W}}}r'):
        if id(r) in skip:
            continue
        pr = r.find(f'{{{W}}}rPr')
        fn = None
        if pr is not None and pr.find(f'{{{W}}}rFonts') is not None:
            fn = pr.find(f'{{{W}}}rFonts').get(f'{{{W}}}ascii')
        if fn == 'Courier New':
            continue
        txt += ''.join(t.text or '' for t in r.iter(f'{{{W}}}t'))
    BADCH = {'ᵇ': '上標 b 冒充下標', 'ⁱ': '上標 i 冒充下標',
             '⟦': '未展開的 ⟦ 標記', '⟧': '未展開的 ⟧ 標記',
             '⟨': '未展開的 ⟨ 數學標記', '⟩': '未展開的 ⟩ 數學標記',
             '\\': '殘留的 LaTeX 反斜線', '{': '殘留大括號',
             '}': '殘留大括號'}
    hits = {c: txt.count(c) for c in BADCH if c in txt}
    # 真下標／真上標的 run 數（rich_runs 與 math_runs 產出的）
    nsub = sum(1 for r in root.iter(f'{{{W}}}rPr')
               if r.find(f'{{{W}}}vertAlign') is not None and
               r.find(f'{{{W}}}vertAlign').get(f'{{{W}}}val') == 'subscript')
    nsup = sum(1 for r in root.iter(f'{{{W}}}rPr')
               if r.find(f'{{{W}}}vertAlign') is not None and
               r.find(f'{{{W}}}vertAlign').get(f'{{{W}}}val') == 'superscript')
    print(f'   真下標 run  {nsub}      真上標 run  {nsup}')
    for c, n2 in hits.items():
        print(f'   ✘ {BADCH[c]}：{n2} 處  ({c!r})')
    ok_sym = not hits
    print(f'   → {"✓ 未發現冒充字元或殘留標記" if ok_sym else "✘ 記號有問題"}')

    allok = ok_vec and not bad and ok_pg and ok_sym
    print(f'\n══ {"✓ 通過" if allok else "✘ 有問題"} ══')
    return 0 if allok else 1


if __name__ == '__main__':
    sys.exit(main())
