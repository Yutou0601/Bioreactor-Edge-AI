# -*- coding: utf-8 -*-
"""2026-09-21 分析報告的簡報版（14 頁）。

版式函式取自 build_deck.py，與 8 月版模板一致。內容來源為
docs/reports/分析報告_2026-09-21_氫氣流失與壓降歸因.md，此檔只負責挑重點與排版。

  python docs/build/build_deck_0921.py

⚠ 圖檔在 docs/analysis_charts_3batch/，不是 build_deck 預設的 paper_figures/，
  故本檔自備 pic2()。圖一律先量原始長寬比再決定要以寬度還是高度貼齊，
  否則寬高比不同的圖會超出版面。
"""
import os
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pptx import Presentation
from pptx.enum.text import PP_ALIGN
from pptx.util import Cm, Pt

from build_deck import (BLUE, GREY, H, INK, RED, W, bullets, caption, note,
                        page, put, table, textbox)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIGDIR = os.path.join(REPO, 'docs', 'analysis_charts_3batch')
OUT = os.path.join(REPO, 'docs', 'decks', '簡報_2026-09-21_氫氣流失與壓降歸因.pptx')

TOP = Cm(3.0)
BOT = Cm(18.0)          # 底部色帶之上


def pic2(slide, name, x=None, y=None, w=None, h=None):
    """貼圖。只給 w 或 h 其一，另一邊依原圖比例算，避免變形或超版。"""
    from PIL import Image
    p = os.path.join(FIGDIR, name)
    if not os.path.isfile(p):
        raise SystemExit('找不到圖檔：%s' % p)
    iw, ih = Image.open(p).size
    ar = ih / iw
    if w is not None:
        h = Cm(w.cm * ar)
    elif h is not None:
        w = Cm(h.cm / ar)
    if x is None:
        x = Cm((W.cm - w.cm) / 2)
    if y is None:
        y = Cm(TOP.cm + (BOT.cm - TOP.cm - h.cm) / 2)
    slide.shapes.add_picture(p, x, y, width=w, height=h)
    return y.cm + h.cm          # 圖的底緣（cm）；圖說與內文接在這之後


def body(slide, x=Cm(1.6), y=None, w=None, h=Cm(13.5)):
    return textbox(slide, x, y or Cm(3.5), w or (W - Cm(3.2)), h)


def build():
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H

    # ── 1 封面 ──────────────────────────────────────────────
    s = page(prs, '反應器的氣體究竟去了哪裡？',
             '壓降歸因與氫氣質量平衡分析｜2026-09-21｜李承育')
    tf = body(s, y=Cm(5.4), h=Cm(8.0))
    put(tf, [('一句話的結論：', 22, True, INK)], first=True, space_after=14)
    put(tf, [('壓力下降的主要成分，既不是二氧化碳溶解，也不是產甲烷，', 26, True, RED)],
        space_after=6)
    put(tf, [('而是', 26, True, RED), ('氫氣的超量流失', 32, True, RED), ('。', 26, True, RED)],
        space_after=20)
    put(tf, [('證據：35 次排氣量測中有 34 次，殘餘氣體的二氧化碳對氫氣比例'
              '高於進料比，中位為進料比的 2.79 倍（p < 0.0001）。', 17, False, GREY)])
    note(s, '本頁結論的前提是進料確認為 CO₂:H₂ = 1:4。'
            '本分析無法區分洩漏、穿透、或其他耗氫生化反應。')

    # ── 2 問題 ──────────────────────────────────────────────
    s = page(prs, '一、要回答的問題', '壓力一直在掉，那些氣體去了哪裡？')
    tf = body(s, h=Cm(11.4))          # note 佔 15.45~17.85，內文不可越界
    put(tf, [('反應器的運作方式', 20, True, INK)], first=True, space_after=10)
    bullets(tf, [
        '把二氧化碳與氫氣依 1:4 充到約 1.17 kgf/cm²',
        '壓力慢慢下降，降到約 0.92 就自動補滿，如此反覆',
        '每一次「補滿到降低」稱為一個循環',
    ], fs=17, first=False)
    put(tf, [('', 8, False, INK)], space_after=10)
    put(tf, [('壓力下降有三種可能的去向', 20, True, INK)], space_after=10)
    bullets(tf, [
        [('① 被微生物轉換成甲烷', 17, True, INK),
         ('　CO₂ + 4H₂ → CH₄ + 2H₂O，氣相淨少 4 個分子', 17, False, GREY)],
        [('② 溶進液體裡', 17, True, INK),
         ('　二氧化碳的溶解度約為氫氣的 44 倍', 17, False, GREY)],
        [('③ 漏掉了', 17, True, RED),
         ('　本次分析新增的第三個可能', 17, False, GREY)],
    ], fs=17, first=False)
    note(s, '若不能區分這三者，就算不出反應器的真實轉換效率，也判斷不了菌群狀態。',
         color=INK)

    # ── 3 三個矛盾 ──────────────────────────────────────────
    s = page(prs, '二、先前遺留的三個矛盾', '這三件事用「產甲烷主導」解釋不通')
    table(s, Cm(1.6), Cm(4.2), W - Cm(3.2), [
        ['觀察', '若壓降主要來自產甲烷，應該看到', '實際看到'],
        ['切斷碳源（二氧化碳）後', '壓降速率應大幅下降', '幾乎沒變（0.0347 → 0.0367）'],
        ['氣體總收支', '消失的氣體應對應到甲烷產量', '有一大段對不起來'],
        ['壓降曲線形狀', '應呈明顯彎曲（溶解的特徵）', '91% 幾乎是直線'],
    ], widths=[Cm(8.0), Cm(11.5), Cm(11.2)], fs=15, hi_rows=())
    tf = body(s, y=Cm(10.6), h=Cm(6.0))
    put(tf, [('本次分析從解開這三個矛盾出發。結果是：它們有同一個答案。',
              19, True, INK)], first=True)

    # ── 4 資料可信度 ────────────────────────────────────────
    s = page(prs, '三、先確認：氣體讀數什麼時候可信',
             '補氣加入的是二氧化碳與氫氣、不含甲烷，真頂空必定被稀釋')
    yb = pic2(s, 'fig44_sensor_validity.png', w=Cm(26.0), y=Cm(3.3))
    caption(s, Cm(1.7), Cm(yb + 0.15), W - Cm(3.4), 1,
            '(a) 一次排氣的實際讀數　(b) 補氣時甲烷有沒有被稀釋　(c) 單一循環內的斜率')
    tf = body(s, y=Cm(yb + 1.05), h=Cm(3.4))
    put(tf, [('實測斜率 ', 17, False, INK), ('+0.008 ± 0.225', 19, True, RED),
             ('，距「真頂空」應有的 −1 有 4.5 個標準差。', 17, False, INK)],
        first=True, space_after=4)
    put(tf, [('結論：分析儀只有在排氣當下的一至二分鐘可信。'
              '全資料庫符合此條件者共 35 筆，後續所有氣體計算只用這 35 筆。',
              16, False, GREY)])

    # ── 5 核心原理 ──────────────────────────────────────────
    s = page(prs, '四、關鍵原理：進料比剛好等於反應計量比',
             '這讓一個不需要任何校準常數的檢定成為可能')
    tf = body(s, y=Cm(3.8), h=Cm(6.0))
    put(tf, [('產甲烷反應　CO₂ + 4 H₂ → CH₄ + 2 H₂O', 24, True, INK)],
        first=True, align=PP_ALIGN.CENTER, space_after=14)
    put(tf, [('進料也是 1:4 ——', 20, False, INK),
             ('兩者完全相同', 22, True, RED)],
        align=PP_ALIGN.CENTER, space_after=14)
    put(tf, [('所以若系統內只有產甲烷反應：補進去 1:4、消耗掉 1:4，', 19, False, INK)],
        align=PP_ALIGN.CENTER, space_after=6)
    put(tf, [('剩下的必然永遠是 1:4（比值 0.25），與轉換率高低無關。',
              21, True, BLUE)], align=PP_ALIGN.CENTER)
    table(s, Cm(5.6), Cm(11.2), W - Cm(11.2), [
        ['殘餘的 CO₂ ÷ H₂', '代表什麼'],
        ['低於 0.25', '二氧化碳被額外移除 → 溶解'],
        ['等於 0.25', '只有產甲烷反應'],
        ['高於 0.25', '氫氣被額外移除 → 洩漏或其他耗氫反應'],
    ], widths=[Cm(8.0), Cm(14.7)], fs=15, hi_rows=(3,))

    # ── 6 核心結果 ──────────────────────────────────────────
    s = page(prs, '五、結果：34 / 35 次都偏向同一側',
             '紅色虛線 = 只有產甲烷反應時應有的位置')
    yb = pic2(s, 'fig43_feed_ratio.png', w=Cm(26.0), y=Cm(3.3))
    caption(s, Cm(1.7), Cm(yb + 0.15), W - Cm(3.4), 2,
            '(a) 分布　(b) 一整年的時序　(c) 二氧化碳剩餘量對氫氣剩餘量')
    table(s, Cm(6.4), Cm(yb + 1.05), W - Cm(12.8), [
        ['二氧化碳 ÷ 氫氣（中位）', '相對進料比', '高於進料比', '置換檢定'],
        ['0.699', '2.79 倍', '34 / 35（97%）', 'p < 0.0001'],
    ], widths=[Cm(6.2), Cm(4.6), Cm(5.4), Cm(4.9)], fs=15, hi_rows=(1,))

    # ── 7 穩健性 ────────────────────────────────────────────
    s = page(prs, '六、這不是量測誤差造成的', '以 2026-07-30 那次排氣為例')
    tf = body(s, y=Cm(4.0), h=Cm(11.0))
    put(tf, [('量測到：二氧化碳 21.3%、甲烷 34.79%', 20, True, INK)],
        first=True, space_after=14)
    bullets(tf, [
        [('若殘餘氣體真的維持 1:4，扣除甲烷與水蒸氣後，'
          '二氧化碳應該只有 ', 18, False, INK), ('12.6%', 20, True, BLUE)],
        [('即使把甲烷讀數', 18, False, INK), ('全部當成零', 20, True, RED),
         ('（最極端的假設），氫氣上限也只有 78.7%，比值仍為 0.27', 18, False, INK)],
    ], fs=18, first=False, gap=14)
    put(tf, [('', 10, False, INK)], space_after=10)
    put(tf, [('也就是說——二氧化碳的實測值本身，就高到與 1:4 不相容。',
              22, True, RED)], space_after=16)
    put(tf, [('量級換算（保守估計）：要讓比值漂移到實測中位數，'
              '需要額外移除約 2.57 莫耳氫氣，相當於進料氫氣的 64%。',
              16, False, GREY)])
    note(s, '此換算為單次通過的保守估計，實際為連續補氣，數值僅示意量級。')

    # ── 8 三個矛盾一次解開 ──────────────────────────────────
    s = page(prs, '七、三個矛盾，同一個答案', '')
    table(s, Cm(1.6), Cm(4.0), W - Cm(3.2), [
        ['先前的矛盾', '用「氫氣流失」如何解釋'],
        ['切斷碳源後壓降速率不變', '因為消失的主要是氫氣，與碳源有無無關'],
        ['氣體收支對不起來', '缺口就是漏掉的氫氣'],
        ['壓降曲線幾乎是直線', '定速移除才會是直線——洩漏正是定速'],
    ], widths=[Cm(13.0), Cm(17.7)], fs=16)
    tf = body(s, y=Cm(11.4), h=Cm(5.5))
    put(tf, [('甲烷確實在產生', 20, True, INK),
             ('（自動化批次由 9.99% 升至 39.6%），氧化還原電位也落在文獻最適區間。',
              18, False, INK)], first=True, space_after=10)
    put(tf, [('但——以壓降速率作為產甲烷速率的代理量，會嚴重高估。',
              20, True, RED)])

    # ── 9 佐證一：碳源切斷 ──────────────────────────────────
    s = page(prs, '八、佐證一：切斷碳源，壓降照舊',
             '自動化批次 2026-08-11 ~ 08-31')
    pic2(s, 'fig37_co2_story.png', h=Cm(12.6), x=Cm(1.6), y=Cm(3.5))
    tf = textbox(s, Cm(18.6), Cm(4.0), Cm(14.0), Cm(12.0))
    put(tf, [('碳源不存在，產甲烷必然停止。', 18, True, INK)],
        first=True, space_after=12)
    put(tf, [('碳源充足（59 個循環）　0.0347', 17, False, INK)], space_after=6)
    put(tf, [('碳源中斷（31 個循環）　0.0367', 17, True, RED)], space_after=12)
    put(tf, [('差 +0.0020，方向還相反，p = 0.21。', 17, False, INK)], space_after=14)
    put(tf, [('這個「沒有差異」有檢定力', 18, True, BLUE)], space_after=8)
    put(tf, [('若生物途徑真的佔總壓降三分之一（0.0125），'
              '本檢定偵測得到的機率是 100%。結果沒有。', 16, False, GREY)])

    # ── 10 佐證二：形狀 ─────────────────────────────────────
    s = page(prs, '九、佐證二：壓降曲線幾乎是直線',
             '溶解會讓曲線彎，定速移除是直線')
    pic2(s, 'fig36_shape_clusters.png', h=Cm(11.8), y=Cm(3.5))
    caption(s, Cm(1.7), Cm(15.5), W - Cm(3.4), 4,
            '全資料庫 252 條下降曲線正規化後分群：229 條（91%）落在「接近直線」')

    # ── 11 ORP ──────────────────────────────────────────────
    s = page(prs, '十、氧化還原電位（ORP）該怎麼讀',
             '水準健康，但循環內的變化不是生物造成的')
    yb = pic2(s, 'fig41_orp_substrate.png', w=Cm(19.0), y=Cm(3.2))
    tf = body(s, y=Cm(yb + 0.3), h=Cm(15.2 - yb))     # 收在 note（15.45）之上
    put(tf, [('水準：', 17, True, INK),
             ('−357 mV（對標準氫電極）；文獻所報中溫產甲烷相最適為 −335.6 ± 29.0 mV，',
              16, False, INK),
             ('正落在最適區間內', 17, True, BLUE)], first=True, space_after=6)
    put(tf, [('變化：', 17, True, INK),
             ('補氣當下 10 分鐘內跳 +37 mV；氣泵運轉時 +3.5 ~ +10.8 mV/分。',
              16, False, INK)], space_after=6)
    put(tf, [('碳源中斷後每循環位移由 −125.5 變為 −158.8 mV（走更多，p = 0.089）——'
              '產甲烷必須停止的時段，ORP 照常變化。', 16, True, RED)])
    note(s, '文獻將 ORP 當微生物活性指標，其對象是未外加氫氣的系統；'
            '本反應器的氫氣為外部輸入，會直接鉗制電位，該套解讀不能直接移植。')

    # ── 12 試過但不成立的方法 ───────────────────────────────
    s = page(prs, '十一、試過但不成立的兩個方法', '誠實記錄，避免後續重複投入')
    tf = body(s, y=Cm(3.4), h=Cm(6.1))
    put(tf, [('① 以「曲率」分離生物與物理', 20, True, INK)], first=True, space_after=8)
    put(tf, [('前提是生物速率為定值，但生物速率會隨氫氣耗盡而變動。'
              '以已知答案的合成資料驗證：真實物理份額 0%、僅有會衰減的生物時，'
              '該方法報出物理份額 ', 17, False, INK),
             ('101%', 19, True, RED), ('。', 17, False, INK)], space_after=16)
    put(tf, [('② 以物理資訊神經網路（PINN）反推生物速率', 20, True, INK)],
        space_after=8)
    put(tf, [('讓生物速率成為時間的函數是正確的方向，但它可以吸收任何殘差，'
              '結果由平滑設定決定而非由資料決定。', 17, False, INK)])
    yb = pic2(s, 'fig42_pinn_rb.png', w=Cm(19.5), y=Cm(9.7))
    caption(s, Cm(5.0), Cm(yb + 0.15), W - Cm(10.0), 5,
            '交叉驗證選到誤差 87% 的設定，真正最佳者誤差 36%——標準的參數選擇方法在此失效')

    # ── 13 限制 ─────────────────────────────────────────────
    s = page(prs, '十二、本分析的限制', '引用時應一併說明')
    tf = body(s, y=Cm(4.0), h=Cm(12.0))
    bullets(tf, [
        '氫氣濃度為差額推算，非直接量測（分析儀僅量二氧化碳與甲烷）',
        '無法區分氫氣流失的機制：洩漏、穿透、或其他耗氫生化反應',
        '僅 35 筆可用的氣體組成資料，平均每 11 天一筆',
        '碳源中斷時進料組成同時改變，兩時段的差異不僅限於碳源有無',
        '酸鹼值的結果效應量極小（約為儀器刻度的七分之一），屬方向性證據',
    ], fs=18, first=True, gap=16)

    # ── 14 建議 ─────────────────────────────────────────────
    s = page(prs, '十三、建議', '第一項完成前，其餘方向都無法定案')
    tf = body(s, y=Cm(3.6), h=Cm(4.0))
    put(tf, [('最優先：氫氣氣密性檢查', 24, True, RED)], first=True, space_after=8)
    put(tf, [('於無菌或不含微生物的條件下，以氮氣與氫氣分別充壓至相同絕對壓力，'
              '記錄 24 小時的壓力變化。氫氣若衰減顯著較快，即為直接證據。'
              '同時建議檢查彈性體墊片材質是否為氫氣適用。', 17, False, INK)])
    table(s, Cm(1.6), Cm(8.4), W - Cm(3.2), [
        ['項目', '現況', '建議', '可解鎖什麼'],
        ['排氣頻率', '平均每 11 天一次', '每 3.5 小時一次', '一週的資料量超過過去一整年'],
        ['排氣期取樣', '每分鐘一筆', '每 10 秒一筆', '排氣僅橫跨 3~4 筆，容易錯過峰值'],
        ['酸鹼值解析度', '0.01', '0.001', 'pH 是唯一符號相反的判別通道'],
        ['氣體分析', 'CO₂、CH₄', '加測 H₂', '核心結論可由推算改為直接量測'],
        ['排氣氣體量', '未量測', '加裝氣量計', '直接關閉氣體收支的缺口'],
    ], widths=[Cm(5.2), Cm(6.0), Cm(5.6), Cm(13.9)], fs=14, hi_rows=(1,))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    prs.save(OUT)
    print('已輸出 %s' % os.path.relpath(OUT, REPO))
    print('共 %d 頁' % len(prs.slides.__iter__.__self__._sldIdLst))


if __name__ == '__main__':
    build()
