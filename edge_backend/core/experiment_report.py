"""
實驗報表匯出
============
把批次（experiment_runs）產生的量測結果，輸出成洪博熟悉的批次表格式：
  - Excel（.xlsx，綠底表格，可直接交付）
  - CSV（純文字，供後續分析）

只用可信訊號的量測結果；CH4% 欄標明「參考」。
"""

import csv
import io

# 報表欄位（對應洪博 2026-07-17 批次表）
COLUMNS = [
    ("run_id",             "批次實驗"),
    ("gas_ratio",          "氣體比例(H2:CO2)"),
    ("intake_pressure",    "進氣至壓力(kg/cm²)"),
    ("n_minutes",          "循環時間(每時幾分)"),
    ("vent_pressure",      "排氣至壓力(kg/cm²)"),
    ("total_hours",        "總時間(hrs)"),
    ("pressure_drop_rate", "下降壓力速率(kg/cm²/hr)"),
    ("vent_ph",            "pH"),
    ("vent_orp",           "ORP(mV)"),
    ("vent_ch4_peak_ref",  "CH4%(排氣峰值·參考)"),
    ("status",             "狀態"),
]


def _flatten(run: dict) -> dict:
    """把 run + run['results'] 攤平成單層 dict，方便取欄位。"""
    flat = {k: v for k, v in run.items() if k != "results"}
    flat.update(run.get("results", {}))
    # 狀態中文化
    flat["status"] = {"running": "進行中", "done": "已完成"}.get(flat.get("status"), flat.get("status", ""))
    return flat


def _cell(flat: dict, key: str):
    v = flat.get(key)
    if v is None:
        return ""
    if key == "n_minutes":
        return f"{v:g} 分"
    return v


def to_csv(runs: list) -> str:
    """輸出 CSV 字串（utf-8-sig 由呼叫端加 BOM）。"""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([zh for _, zh in COLUMNS])
    for run in runs:
        flat = _flatten(run)
        w.writerow([_cell(flat, key) for key, _ in COLUMNS])
    return buf.getvalue()


def to_xlsx_bytes(runs: list) -> bytes:
    """輸出 .xlsx 位元組（綠底表格，比照洪博格式）。"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    GREEN = PatternFill("solid", fgColor="92D050")
    GREY = PatternFill("solid", fgColor="F2F2F2")
    HFONT = Font(name="微軟正黑體", size=11, bold=True, color="000000")
    BFONT = Font(name="微軟正黑體", size=11)
    NOTE = Font(name="微軟正黑體", size=9, italic=True, color="595959")
    THIN = Side(style="thin", color="000000")
    BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
    CEN = Alignment(horizontal="center", vertical="center", wrap_text=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "實驗批次結果"

    ws.cell(1, 1, "生物甲烷化 — 循環時間實驗批次結果").font = Font(name="微軟正黑體", size=13, bold=True)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(COLUMNS))

    hr = 3
    for j, (_, zh) in enumerate(COLUMNS, 1):
        c = ws.cell(hr, j, zh)
        c.font = HFONT
        c.fill = GREY if j <= 5 else GREEN   # 前5欄=設定條件(灰), 其餘=量測結果(綠)
        c.alignment = CEN
        c.border = BORDER

    for i, run in enumerate(runs):
        flat = _flatten(run)
        for j, (key, _) in enumerate(COLUMNS, 1):
            c = ws.cell(hr + 1 + i, j, _cell(flat, key))
            c.font = BFONT
            c.alignment = CEN
            c.border = BORDER

    widths = [10, 14, 13, 13, 13, 11, 16, 8, 10, 15, 9]
    for j, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.row_dimensions[hr].height = 34

    note_row = hr + 1 + len(runs) + 1
    ws.cell(note_row, 1, "※ 灰底＝設定條件，綠底＝量測結果（由感測訊號自動計算）。"
            "CH4% 僅取排氣峰值當參考，不作為證據。").font = NOTE
    ws.merge_cells(start_row=note_row, start_column=1, end_row=note_row, end_column=len(COLUMNS))

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
