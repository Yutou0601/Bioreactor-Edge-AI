
# -*- coding: utf-8 -*-
"""
論文圖表的共用樣式（單一來源）
════════════════════════════════════════════════════════════════════════

**為什麼要有這支**：五張圖都以 `\\includegraphics[width=\\textwidth]` 放進論文，
在紙上是同樣的 122 mm 寬、**不再縮放**。因此各圖的字級必須一致，否則印出來
會看起來像不同大小的字。先前 Fig. 1 用 6.6 pt、Fig. 2–4 用 8.0 pt、
Fig. 5 用 7.0 pt，三套並存。

**單位寫法**：一律用斜線（kg/cm²、/hr、min/hr），不用負指數（kg cm⁻²、h⁻¹）。
兩者物理上等價，但本文採斜線式以求易讀，且全篇統一。

用法：
    from paper_style import apply, W, C, U
    apply()
    fig, ax = plt.subplots(figsize=(W, 2.6))
    ax.set_ylabel(f'Trigger pressure  ({U["p"]})')
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                                    # noqa: E402

# ── 尺寸 ──────────────────────────────────────────────────────
W = 4.80              # LNCS 單欄文寬 122 mm；**所有圖一律用這個寬度**

# ── 字級（全部圖共用；改這裡就會一起改）─────────────────────
FS_BASE = 7.0         # 內文、標記標籤
FS_LABEL = 7.5        # 軸標籤
FS_TICK = 6.8         # 刻度
FS_LEGEND = 6.6       # 圖例
FS_NOTE = 6.2         # 圖內註腳
FS_SMALL = 5.8        # 密集標註（流程圖方塊內等）

# ── 單位字串（斜線式，全篇統一）───────────────────────────────
U = {
    'p':    'kg/cm$^2$',            # 壓力
    'rate': 'kg/cm$^2$/hr',         # 壓力變化率
    'inv':  '/hr',                  # 一階速率常數（κ）
    'duty': 'min/hr',               # 循環工作比
}

# ── 配色（灰階安全；顏色僅作輔助，不承載資訊）─────────────────
C = {'main': '#1f4e79', 'accent': '#c0392b', 'gap': '#e8e8e8',
     'sec': '#7f8c8d', 'fill': '#aec7e8', 'ink': '#000000'}


def apply():
    """套用共用 rcParams。每支繪圖程式開頭呼叫一次。"""
    plt.rcParams.update({
        # DejaVu Sans 完整涵蓋 U+2212 減號、≤、≥、τ、κ
        'font.family': 'DejaVu Sans',
        'font.size': FS_BASE,
        'axes.labelsize': FS_LABEL,
        'axes.titlesize': FS_LABEL,
        'xtick.labelsize': FS_TICK,
        'ytick.labelsize': FS_TICK,
        'legend.fontsize': FS_LEGEND,
        'axes.linewidth': 0.6,
        'xtick.major.width': 0.6,
        'ytick.major.width': 0.6,
        'lines.linewidth': 1.1,
        'hatch.linewidth': 0.5,
        # Type 42 = TrueType 內嵌，避免期刊端缺字型
        'pdf.fonttype': 42,
        'ps.fonttype': 42,
        'savefig.bbox': 'tight',
        'savefig.pad_inches': 0.02,
    })


PNG_DPI = 1200        # Springer：線稿至少 800 dpi，建議 1200
#                       PNG 在 .docx 裡是**後備圖**（給不支援 SVG 的檢視器），
#                       所以仍須達規範，不能只當校稿用。


def save(fig, name, outdir):
    """三種格式一起存：

      .pdf   真向量 —— LaTeX 投稿用
      .svg   真向量 —— 由 `paper/svg_docx.py` 內嵌進 .docx（Word 2016+）
      .png   1200 dpi 點陣 —— .docx 的後備圖與校稿用

    Word 的向量格式本是 EMF，但本機無 inkscape / libreoffice，
    matplotlib 也寫不出 EMF；SVG 是唯一能同時被 matplotlib 產出、
    又被 Word 原生算繪的向量格式。
    """
    import os
    for ext in ('pdf', 'svg', 'png'):
        fig.savefig(os.path.join(outdir, f'{name}.{ext}'),
                    dpi=(PNG_DPI if ext == 'png' else None))
    plt.close(fig)
    print(f'   ✓ {name}  .pdf / .svg（向量）/ .png（{PNG_DPI} dpi 後備）')
