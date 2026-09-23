
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

# 各表之後要插的圖（先跑 fig_daily_0912_detail.py 產生）。
# ⚠ 圖檔不存在時直接失敗，不要略過——沒有圖的報告外觀完全正常，
#   不會有人發現少了東西。
FIGDIR = os.path.join(REPO, 'docs', 'reports', 'fig_daily_0912')
# 頭條圖（圖 1）不掛在任何一張表底下，直接放在封面之後——它回答的是
# 會議最主要的那個問題，讀者翻開第一頁就該看到。
HEADLINE = ('fig1_多久用掉多少氣體.png',
            '圖 1\u3000會議問「放著不動 1 / 2 / 3 小時各能轉換多少」，這張圖就是答案。左：把 13 個循環對齊平均後，壓力從 1.17 往下掉的樣子；會議說的「掉到 1.1」實際約 2.0 小時就到。右：同樣時間裡總共用掉多少氣體，以及其中最多有多少是二氧化碳（反應式 CO2 + 4H2 → CH4，每 4 分氣體只換到 1 分甲烷，所以 CO2 最多佔四分之一）。')
FIGS = {
    'B': [('fig2_壓力什麼時候掉.png',
           '圖 2\u3000壓力不是整個小時慢慢平均往下掉，而是循環泵一開才掉。三批設定的每小時循環時間是 1、5、10 分鐘，資料上量到的長度就正好是 1、5、10 分鐘（陰影處）。陰影以外壓力幾乎不動。這代表氣體是在泵運轉時才進到水裡，泵開多久直接決定用掉多少。')],
    'E': [('fig4_多少是菌吃掉的.png',
           '圖 4\u3000壓力掉下來的部分，有多少是菌吃掉變成甲烷的。同一段資料用四種不同算法都會得到差不多的答案（菌長起來那段 29 ~ 38%），表示這個數字站得住。氫氣用完那段只有 2 天，四種算法差很多，不能當數字用。沒有 CO2 可用那段全部是負的——負的代表根本沒在產甲烷，反應器裡原有的甲烷正被補進來的新氣體稀釋。')],
    'F': [('fig3_循環時間與用氣量.png',
           '圖 3\u3000循環泵開得越久，氣體用得越快：每小時循環 1 分鐘一天用掉 363 mL，5 分鐘 681 mL，10 分鐘 788 mL。這是可以直接拿來排運轉條件的數字。')],
}
FIGW_PORTRAIT, FIGW_LANDSCAPE = Mm(155), Mm(215)

INTRO = {
    'A': ('期間 2026-07-30 至 08-03。本表列出切出的**每一段**，不做篩選。'
          '「判定」欄由時長與降幅自動分類，不是人工標註。'),
    'B': ('把每一筆與前一筆的壓力差，依「該筆落在小時內的第幾分鐘」分組平均；'
          '補氣（單步跳升 > 0.03）已排除。記號欄：開＝驟降尖峰，停＝回升尖峰，'
          '｜＝泵運轉中。'),
    'C': ('把 13 個自動循環按「循環開始後經過幾小時」對齊再平均，每 30 分鐘'
          '一格。平均之後誤差只剩 0.002 ~ 0.006，單看一個循環看不出來的'
          '東西就顯出來了。這張表就是前面圖 1 左邊那條線的數字版。'),
    'D': '自動化測試批次的逐日彙整。覆蓋率以每日應有 1440 筆計算。',
    'E': ('甲烷濃度不是照直線在漲，是前面漲得快、後面越來越慢，所以「頭尾'
          '各取幾筆來算」會影響答案。這裡把四種算法並列，看結論穩不穩。'),
    'F': '三批對照：每小時循環 1 / 5 / 10 分鐘，差多少。',
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
    'B': ['三批泵開始跑的時刻不同（第 50、25、13 分），但開的長度分別是'
          '1、5、10 分，與各批設定的「每小時循環幾分鐘」完全一致。'
          '所以這個訊號確定就是循環泵造成的，不是別的東西。',
          '泵沒在跑的分鐘，壓力變化幾乎都在 ±0.001 以內，跟誤差同一個量級'
          '——也就是泵不跑的時候壓力幾乎不動。',
          '第二批最極端：泵只佔每小時 8.3% 的時間，卻造成 85% 的壓降。'],
    'C': ['「相對速率」欄一高一低交替：1.71×、1.78×、0.37×、1.36×、0.43× ⋯⋯'
          '這就是表 B 那個泵的節奏——有泵在跑的那半小時掉得快，沒泵的那'
          '半小時掉得慢。一個循環裡面，壓力不是等速往下掉的。'],
    'D': ['建立期（8/11 ~ 8/23）：甲烷逐日上升，日增幅由 +10.2 收斂到 +0.3，'
          '是典型的快要飽和；二氧化碳同步由 4.20% 一路降到 0.30%。',
          '8/24 當日只補氣 1 次（平時 11 ~ 13 次），壓力掉到 0.69，'
          '甲烷跌 16.6 個百分點，與現場照片「氫氣功能中斷」吻合。',
          '衰退期（8/26 起）：二氧化碳維持 0.00%，甲烷由 42.63% 降到 31.27%，'
          '補氣次數與消耗量同步下滑。8/31 覆蓋率僅 38%，該日數值不宜單獨引用。'],
    'E': ['只取頭尾各一筆最省事，但給不出誤差範圍。頭尾各平均 6 小時是建議'
          '值：足夠把雜訊平均掉，又不會取太寬。取 12 / 24 小時則會把還在'
          '往上漲的那段也平均進去，算出來偏小。',
          '菌長起來那段四種算法都落在 29 ~ 38%，結論一致，可以用；'
          '氫氣用完那段只有 2 天，四種差到 +29% / +39% / +67%，不要引用。'],
    'F': ['循環開得越久，壓力掉得越快：0.0173 → 0.0325 → 0.0377 kg/cm²/hr，'
          '泵開的長度同步是 1 → 5 → 10 分鐘。兩者一起變，道理很單純：'
          '泵跑多久，氣體就跟水接觸多久。',
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


def add_figure(doc, fname, caption, landscape):
    """插圖 + 圖說。圖不存在就直接失敗。"""
    path = os.path.join(FIGDIR, fname)
    if not os.path.isfile(path):
        raise SystemExit('找不到圖檔：%s\n請先執行 fig_daily_0912_detail.py'
                         % path)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(path,
                            width=FIGW_LANDSCAPE if landscape
                            else FIGW_PORTRAIT)
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(2)
    c = doc.add_paragraph()
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    style_run(c.add_run(caption), 9.5, False)
    c.paragraph_format.space_after = Pt(8)


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

    add_figure(doc, HEADLINE[0], HEADLINE[1], False)

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
            ('C', '一個循環裡壓力掉的速度（13 段對齊平均）',
             '循環裡面掉得快慢怎麼變'),
            ('D', '自動化批次逐日明細（21 天）', '二十天裡每天發生什麼'),
            ('E', '各階段轉換了多少（四種算法對照）', '轉換了多少、誤差多大'),
            ('F', '三批對照', '循環開多久差多少')]
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
        for fname, cap in FIGS.get(key, []):
            add_figure(doc, fname, cap, key in LANDSCAPE)

    # ── 綜合判讀與待辦 ────────────────────────────────
    new_section(doc, False)
    para(doc, '綜合判讀', 12, True, after=4)
    for ln in ['自動循環的一致性很高。13 段的降幅標準差只有 0.009'
               '（佔均值 3.6%），時長標準差 0.76 小時。設備運轉穩定，'
               '資料品質足以支撐分析。',
               '壓力是泵在跑的時候才掉的，不是整個小時平均掉。泵只佔每小時的 '
               '1.7 ~ 17% 時間，卻造成 37 ~ 85% 的壓降。這對論文有影響：'
               '我們擬合的那條平滑曲線其實是一連串脈衝的外框，'
               '不是底層真正的變化過程。',
               '濃度錨點不足仍是主要瓶頸。三批合計只有 3 個 CH4 峰值。'
               '會議規劃的「3 ~ 4 小時排一次氣」正是為了解決這一點。']:
        para(doc, '・' + ln, 11, indent=6, after=4)

    para(doc, '待辦事項', 12, True, before=10, after=4)
    for ln in ['確認二氧化碳供應狀況（延續前報，仍為最優先）。自 8/23 起'
               '頭空二氧化碳為 0.00%，8/26 之後甲烷持續下降。',
               '排氣期間記錄頻率提高到每 10 秒。實測排氣只橫跨 3 ~ 4 筆資料。',
               '更正週報的逐日消耗欄（本報告已列出正確值）。',
               '論文的模型假設段落要補一句：所擬合的平滑曲線是一連串脈衝的外框。']:
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
