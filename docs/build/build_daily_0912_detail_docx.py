
# -*- coding: utf-8 -*-
"""2026-09-12 明細版日報 → Word（真正的 Word 表格，不是等寬文字塊）。

⚠ 表格資料直接取自 research/cycles/detail_tables.py 的 `DATA`，與文字版
  **共用同一份計算**。不解析文字輸出——那很脆弱，欄位一改就靜默錯位。

⚠ 表 A（12 欄）與表 B（13 欄 × 60 列）在直向 A4 上塞不下，各自放進**橫向
  區段**。python-docx 可以在同一份文件裡切換方向，但必須是「新 section」，
  不能只改當前 section 的 orientation——那會把前面的頁面一起轉向。

輸出 → docs/reports/日報_2026-09-12_明細表_李承育.docx
"""
import os
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(REPO, 'docs', 'reports', '日報_2026-09-12_明細表_李承育.docx')

sys.path.insert(0, os.path.join(REPO, 'research', 'cycles'))
from detail_tables import DATA                                   # noqa: E402

CN, EN = '標楷體', 'Times New Roman'

# 每張表的欄寬（mm）。直向可用 160 mm、橫向可用 247 mm。
# ⚠ 每列的合計不可超過該區段的可用寬度，否則 Word 會讓表格溢出版面。
#   直向 A4 扣掉左右邊界 25 mm 後可用 160 mm；橫向為 247 mm。
#   （第一版 D/E/F 分別做成 168/181/168 mm，全部超出，已修。）
COLW = {
    'A': [7, 21, 21, 12, 11, 11, 13, 16, 15, 12, 12, 20],          # 橫向 171
    'B': [7, 17, 14, 10, 7, 17, 14, 10, 7, 17, 14, 10, 7],         # 橫向 151
    'C': [30, 30, 24, 26, 24],                                     # 直向 134
    'D': [20, 10, 10, 21, 15, 13, 15, 11, 17, 20],                 # 直向 152
    # ⚠ 不要做到剛好等於可用寬。儲存格本身有內距，160/160 仍會溢出。留餘裕。
    'E': [24, 10, 12, 19, 19, 24, 20, 11, 10],                     # 直向 149
    'F': [12, 8, 20, 10, 10, 15, 15, 15, 22, 12, 11],              # 直向 150
}
LANDSCAPE = ('A', 'B')

INTRO = {
    'A': ('期間 2026-07-30 至 08-03。本表列出切出的**每一段**，不做篩選。'
          '「判定」欄由時長與降幅自動分類，不是人工標註。'),
    'B': ('把每一筆與前一筆的壓力差，依「該筆落在小時內的第幾分鐘」分組平均；'
          '補氣（單步跳升 > 0.03）已排除。記號欄：開＝驟降尖峰，停＝回升尖峰，'
          '｜＝泵運轉中。'),
    'C': ('把 13 個自動循環按「循環內經過幾小時」對齊後疊加，每 30 分鐘一格。'
          '疊加後標準誤僅 0.002 ~ 0.006，可看出單一循環看不見的結構。'),
    'D': '自動化測試批次的逐日彙整。覆蓋率以每日應有 1440 筆計算。',
    'E': ('同一段資料用不同估計量會得到不同數字，差異來自 CH4 軌跡是**飽和'
          '曲線**而非直線。'),
    'F': '三個循環時間批次的整體對照。',
}

READ = {
    'A': ['R² 是「這段下降有多接近一條直線」。自動循環都在 0.96 以上，'
          '人工排氣掉到 0.44 ~ 0.48——兩者形狀差異極大，可據此自動區分，'
          '不必仰賴人工標註。',
          '第 18 段是真正的排氣動作：5 分鐘內壓力由 0.77 掉到 0.18，'
          '速率 8.85 kg/cm²/hr，是自動循環的 236 倍。',
          '與會議設想的對照：會議說「1.2 開始下降到 1.1」，實測自動循環是'
          '1.17 → 0.92、降幅 0.252 ± 0.009，耗時 6.83 ± 0.76 小時，'
          '降幅為設想的 2.5 倍。若改成「掉 0.1 就排氣」，依實測速率推算'
          '節奏約為 2.7 小時一次。'],
    'B': ['三批的泵窗位置不同（第 50、25、13 分），但長度分別是 1、5、10 分，'
          '與各批宣稱的 τ 完全一致。τ 的定義就是每小時循環幾分鐘，'
          '故此訊號確認來自循環泵。',
          '泵窗以外的分鐘，壓降幾乎都在 ±0.001 以內且標準誤同量級——'
          '亦即泵不運轉時壓力幾乎不動。',
          'tau5 的對比最極端：泵只佔每小時的 8.3% 時間，卻造成 85% 的壓降。'],
    'C': ['「相對速率」欄明顯交替：1.71×、1.78×、0.37×、1.36×、0.43× ⋯⋯'
          '這是表 B 的泵節奏在循環內部的呈現——含泵窗的那半小時速率高，'
          '不含的那半小時速率低。循環內的下降不是等速的。'],
    'D': ['建立期（8/11 ~ 8/23）：甲烷逐日上升，日增幅由 +10.2 收斂到 +0.3，'
          '是典型的接近飽和；二氧化碳同步由 4.20% 單調降到 0.30%。',
          '8/24 當日只補氣 1 次（平時 11 ~ 13 次），壓力掉到 0.69，'
          '甲烷跌 16.6 個百分點，與現場照片「氫氣功能中斷」吻合。',
          '衰退期（8/26 起）：二氧化碳維持 0.00%，甲烷由 42.63% 降到 31.27%，'
          '補氣次數與消耗量同步下滑。8/31 覆蓋率僅 38%，該日數值不宜單獨引用。'],
    'E': ['單筆端點只用頭尾各一筆，給不出誤差。兩端各 6 hr 是建議值：'
          '夠平均掉雜訊，又不會取太寬而咬到曲率。取 12 / 24 hr 則會把仍在'
          '上升的曲線拉低，估計值系統性偏小。'],
    'F': ['下降速率隨 τ 單調上升：0.0173 → 0.0325 → 0.0377 kg/cm²/hr，'
          '泵窗長度同步為 1 → 5 → 10 分鐘。兩者的對應說明了 τ 這個槓桿的'
          '機制：泵運轉時間直接決定氣液接觸時間。',
          'CH4 峰欄顯示可用的濃度錨點極少：tau1 只有 1 個、tau5 一個都沒有、'
          'tau10 有 2 個。沒有錨點就無法做化學計量歸因——這是目前最大的限制。'],
}


def style_run(r, size=11, bold=False):
    r.font.size = Pt(size)
    r.bold = bold
    r.font.name = EN
    r._element.rPr.rFonts.set(qn('w:eastAsia'), CN)


def para(doc, text='', size=11, bold=False, before=0, after=3, indent=0,
         align=None):
    p = doc.add_paragraph()
    if text:
        style_run(p.add_run(text), size, bold)
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.left_indent = Mm(indent)
    pf.line_spacing = Pt(16)
    if align is not None:
        p.alignment = align
    return p


def borders(tbl, sz=4):
    el = tbl._tbl.tblPr
    b = OxmlElement('w:tblBorders')
    for k in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        e = OxmlElement('w:' + k)
        e.set(qn('w:val'), 'single')
        e.set(qn('w:sz'), str(sz))
        e.set(qn('w:color'), '808080')
        b.append(e)
    el.append(b)


def shade(cell, hexcolor):
    tcPr = cell._tc.get_or_add_tcPr()
    sh = OxmlElement('w:shd')
    sh.set(qn('w:val'), 'clear')
    sh.set(qn('w:fill'), hexcolor)
    tcPr.append(sh)


def add_table(doc, d, key, fs=7.5):
    head, rows, widths = d['header'], d['rows'], COLW[key]
    t = doc.add_table(rows=len(rows) + 1, cols=len(head))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    borders(t)
    for j, htxt in enumerate(head):
        c = t.cell(0, j)
        c.text = ''
        p = c.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(0)
        style_run(p.add_run(str(htxt)), fs, True)
        shade(c, 'E8E8E8')
    for i, row in enumerate(rows, 1):
        for j, v in enumerate(row):
            c = t.cell(i, j)
            c.text = ''
            p = c.paragraphs[0]
            p.alignment = (WD_ALIGN_PARAGRAPH.LEFT if j == 0
                           else WD_ALIGN_PARAGRAPH.CENTER)
            p.paragraph_format.space_after = Pt(0)
            style_run(p.add_run(str(v)), fs, False)
        # ⚠ 用底色標出需要注意的列，比在文字裡寫「請看第 18 列」有效得多
        flag = ' '.join(str(x) for x in row)
        if '★' in flag:
            for j in range(len(row)):
                shade(t.cell(i, j), 'FBEAEA')
    for r in t.rows:
        for j, w in enumerate(widths):
            r.cells[j].width = Mm(w)
    return t


def new_section(doc, landscape):
    s = doc.add_section(WD_SECTION.NEW_PAGE)
    if landscape:
        s.orientation = WD_ORIENT.LANDSCAPE
        s.page_width, s.page_height = Mm(297), Mm(210)
        s.left_margin = s.right_margin = Mm(25)
        s.top_margin = s.bottom_margin = Mm(18)
    else:
        s.orientation = WD_ORIENT.PORTRAIT
        s.page_width, s.page_height = Mm(210), Mm(297)
        s.left_margin = s.right_margin = Mm(25)
        s.top_margin = s.bottom_margin = Mm(20)
    return s


def main():
    doc = Document()
    s = doc.sections[0]
    s.page_width, s.page_height = Mm(210), Mm(297)
    s.left_margin = s.right_margin = Mm(25)
    s.top_margin = s.bottom_margin = Mm(20)

    # ── 封面與說明 ────────────────────────────────────
    t = doc.add_table(rows=3, cols=4)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    borders(t, 8)
    cells = [('國立高雄科技大學_金屬中心_日報（明細表）', None),
             ('時間', '2026/09/12', '學生', '李承育'),
             ('地點', '金屬中心（全部分析重跑，逐段／逐分鐘／逐日明細）', None)]
    a = t.cell(0, 0).merge(t.cell(0, 3))
    a.text = ''
    style_run(a.paragraphs[0].add_run(cells[0][0]), 13, True)
    a.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    for j, v in enumerate(cells[1]):
        c = t.cell(1, j)
        c.text = ''
        style_run(c.paragraphs[0].add_run(v), 11, False)
        c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    c = t.cell(2, 0)
    c.text = ''
    style_run(c.paragraphs[0].add_run('地點'), 11, False)
    c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    c = t.cell(2, 1).merge(t.cell(2, 3))
    c.text = ''
    style_run(c.paragraphs[0].add_run(cells[2][1]), 11, False)
    c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

    para(doc, '本份為同日另一份日報的明細版。所有分析重新跑過一次，表格數字'
              '由 research/cycles/detail_tables.py 直接產生，未經手抄。',
         11, before=10, after=4)

    para(doc, '⚠ 先更正一個先前報告的錯誤', 11, True, before=8, after=3)
    para(doc, '2026-09-11 週報逐日表的「當日消耗」欄是錯的。該欄先前以'
              '「所有負的相鄰壓力差加總」計算，把感測器 ±0.01 的抖動也算成'
              '消耗，數值被灌水約四倍（報成 2.0 ~ 3.3，實際是 0.42 ~ 0.89）。'
              '證據是它與同一份報告的總量對不起來：舊值加總約 50，'
              '而全期總消耗是 13.47。本份表 D 改用「以補氣為界切段、'
              '段首減段尾」計算，逐日加總正好 13.47。受影響的只有該欄，'
              '份額、CH4 產量、總消耗等均以正確方式計算，不受影響。',
         11, indent=6, after=6)

    para(doc, '表目錄', 11, True, before=8, after=3)
    idx = doc.add_table(rows=7, cols=3)
    borders(idx)
    for j, v in enumerate(('表', '內容', '回答什麼問題')):
        c = idx.cell(0, j)
        c.text = ''
        style_run(c.paragraphs[0].add_run(v), 10, True)
        shade(c, 'E8E8E8')
    rows = [('A', 'τ=10 每一段下降的完整明細', '每個循環各降多少、多久、有多直'),
            ('B', '循環泵：小時內逐分鐘壓降（三批）', '泵什麼時候開、開多久'),
            ('C', '自動循環的內部剖面（13 段疊加）', '循環內部速率怎麼變化'),
            ('D', '自動化批次逐日明細（21 天）', '二十天裡每天發生什麼'),
            ('E', '化學計量：分階段 × 四種估計量', '轉換了多少、誤差多大'),
            ('F', '三批次總表', 'τ 槓桿的整體效果')]
    for i, r in enumerate(rows, 1):
        for j, v in enumerate(r):
            c = idx.cell(i, j)
            c.text = ''
            style_run(c.paragraphs[0].add_run(v), 10, False)
    for r in idx.rows:
        for j, w in enumerate((14, 66, 76)):
            r.cells[j].width = Mm(w)

    # ── 六張表 ────────────────────────────────────────
    for key in 'ABCDEF':
        d = DATA[key]()
        new_section(doc, key in LANDSCAPE)
        para(doc, d['title'], 12, True, after=3)
        para(doc, INTRO[key], 10.5, after=5, indent=2)
        add_table(doc, d, key, fs=6.5 if key == 'B' else 7.5)
        para(doc, '', 6, after=0)
        for ln in d['foot'].split('\n'):
            para(doc, ln, 10, indent=2, after=2)
        para(doc, '怎麼看這張表', 10.5, True, before=6, after=3, indent=2)
        for ln in READ[key]:
            para(doc, '・' + ln, 10, indent=6, after=3)

    # ── 綜合判讀與待辦 ────────────────────────────────
    new_section(doc, False)
    para(doc, '綜合判讀', 12, True, after=4)
    for ln in ['自動循環的一致性很高。13 段的降幅標準差只有 0.009'
               '（佔均值 3.6%），時長標準差 0.76 小時。設備運轉穩定，'
               '資料品質足以支撐分析。',
               '循環內的下降不是等速的，由泵主導。泵只佔每小時的 1.7 ~ 17% '
               '時間，卻造成 37 ~ 85% 的壓降。此點對論文的模型假設有影響：'
               '估計器擬合的是脈衝序列的包絡線，而非連續的底層動力學。',
               '濃度錨點不足仍是主要瓶頸。三批合計只有 3 個 CH4 峰值。'
               '會議規劃的「3 ~ 4 小時排一次氣」正是為了解決這一點。']:
        para(doc, '・' + ln, 11, indent=6, after=4)

    para(doc, '待辦事項', 12, True, before=10, after=4)
    for ln in ['確認二氧化碳供應狀況（延續前報，仍為最優先）。自 8/23 起'
               '頭空二氧化碳為 0.00%，8/26 之後甲烷持續下降。',
               '排氣期間記錄頻率提高到每 10 秒。實測排氣只橫跨 3 ~ 4 筆資料。',
               '更正週報的逐日消耗欄（本報告已列出正確值）。',
               '論文模型假設段落建議補充「所擬合者為脈衝序列之包絡線」。']:
        para(doc, '・' + ln, 11, indent=6, after=4)

    para(doc, '待確認事項', 12, True, before=10, after=4)
    for ln in ['循環泵的啟動時刻三批各不相同（第 50、25、13 分）。'
               '此為控制程式設定，或由開機時刻決定？若為後者，'
               '該時刻應併入實驗紀錄。',
               'tau5 批次期間完全沒有可用的 CH4 濃度峰值，'
               '是否該期間未曾排氣？',
               '延續前報：資料夾標示之「補氣 0.15 / 0.2 kg」對應之量測值；'
               '8/31 覆蓋率 38% 之資料是否可用。']:
        para(doc, '・' + ln, 11, indent=6, after=4)

    para(doc, '附註', 12, True, before=10, after=4)
    for ln in ['分析腳本：research/cycles/detail_tables.py（本報告全部表格）、'
               'pump_rhythm.py（泵節奏與 τ 驗證）、'
               'hourly_resolution.py（小時尺度可量測界線）。',
               '壓力單位皆為 kg/cm²（錶壓）；絕對壓 = 錶壓 + 1.033。',
               '體積換算以頭空 1.00 L、30 °C 計。'
               '⚠ 溫度欄全期恆為 30.00，非實測值。']:
        para(doc, '・' + ln, 10.5, indent=6, after=3)

    doc.save(OUT)
    print('OK', OUT)
    print('  段落 %d　表格 %d　區段 %d'
          % (len(doc.paragraphs), len(doc.tables), len(doc.sections)))


if __name__ == '__main__':
    main()
