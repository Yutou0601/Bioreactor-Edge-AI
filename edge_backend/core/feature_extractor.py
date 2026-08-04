"""
ORP 特徵分析器（第二階段）
===========================
基於乾淨 EMA 訊號，進行：
1. 穩態判定  — 滑動視窗標準差 σ < threshold 且均值在合理區間
2. 基準漂移分析 — 對穩態區間做線性迴歸，輸出 β₁（mV/hr）

設計依據：基於邊緣運算之生物反應器即時 ORP 變化分析（李承育）
"""

from __future__ import annotations
import math
from dataclasses import dataclass


@dataclass
class AnalysisResult:
    is_steady: bool
    sigma: float          # 當前視窗標準差 (mV)
    orp_mean: float       # 當前視窗平均 EMA (mV)
    drift_rate: float     # 基準漂移率 (mV/hr)，正=上升 負=下降
    steady_minutes: int   # 從末尾往回算，連續穩態的分鐘數
    window_size: int      # 實際使用的視窗大小
    message: str          # 人類可讀狀態描述


class ORPFeatureExtractor:
    def __init__(
        self,
        window: int = 30,
        sigma_threshold: float = 5.0,
        orp_low: float = 480.0,
        orp_high: float = 650.0,
        drift_window: int = 120,
    ):
        """
        Parameters
        ----------
        window          : 穩態判定滑動視窗（分鐘數，1筆=1分鐘）
        sigma_threshold : 標準差上限，低於此值才算穩態
        orp_low/high    : 合理 ORP 區間（超出 = 非穩態）
        drift_window    : 用於線性迴歸的最大回看筆數
        """
        self.window = window
        self.sigma_threshold = sigma_threshold
        self.orp_low = orp_low
        self.orp_high = orp_high
        self.drift_window = drift_window

    def analyze(self, records: list[dict]) -> AnalysisResult:
        """
        輸入所有感測器記錄，回傳特徵分析結果。
        records 每筆需含 'orp'（EMA 平滑值）。
        """
        n = len(records)
        if n < 5:
            return AnalysisResult(False, 0.0, 0.0, 0.0, 0, n, '資料不足（需至少 5 筆）')

        # ── 穩態判定 ──────────────────────────────────
        win = min(self.window, n)
        recent_ema = [r['orp'] for r in records[-win:]]
        mean_val, sigma = self._mean_std(recent_ema)
        in_range = self.orp_low <= mean_val <= self.orp_high
        is_steady = (sigma < self.sigma_threshold) and in_range

        # ── 基準漂移率 ────────────────────────────────
        drift_rate = self._linear_slope_mV_hr(records)

        # ── 連續穩態持續時間 ──────────────────────────
        steady_min = self._count_tail_steady(records)

        # ── 狀態描述 ──────────────────────────────────
        if n < self.window:
            msg = f'累積資料中（{n}/{self.window} 筆）'
        elif not in_range:
            msg = f'ORP 超出正常區間 [{self.orp_low:.0f}, {self.orp_high:.0f}] mV'
        elif not is_steady:
            msg = f'擾動中（σ={sigma:.1f} mV，閾值 {self.sigma_threshold}）'
        else:
            drift_desc = '下降' if drift_rate < -0.05 else ('上升' if drift_rate > 0.05 else '持平')
            msg = f'穩態運行中，基線{drift_desc} {drift_rate:+.2f} mV/hr'

        return AnalysisResult(
            is_steady=is_steady,
            sigma=round(sigma, 2),
            orp_mean=round(mean_val, 1),
            drift_rate=round(drift_rate, 3),
            steady_minutes=steady_min,
            window_size=win,
            message=msg,
        )

    # ------------------------------------------------------------------
    # 私有工具
    # ------------------------------------------------------------------

    @staticmethod
    def _mean_std(vals: list[float]) -> tuple[float, float]:
        n = len(vals)
        if n == 0:
            return 0.0, 0.0
        m = sum(vals) / n
        if n == 1:
            return m, 0.0
        var = sum((x - m) ** 2 for x in vals) / (n - 1)
        return m, math.sqrt(var)

    def _linear_slope_mV_hr(self, records: list[dict]) -> float:
        """對最近 drift_window 筆 EMA 值做最小平方線性迴歸，回傳 mV/hr"""
        data = records[-self.drift_window:]
        n = len(data)
        if n < 5:
            return 0.0

        # 每筆間隔 1 分鐘，t 單位為分鐘
        t = list(range(n))
        y = [r['orp'] for r in data]
        t_m = sum(t) / n
        y_m = sum(y) / n

        # 將每筆 t[i] 減掉 t 的差值，y[i] 減掉 y 的差值，計算斜率
        num = sum((t[i] - t_m) * (y[i] - y_m) for i in range(n))
        den = sum((t[i] - t_m) ** 2 for i in range(n))
        if den == 0:
            return 0.0

        slope_per_min = num / den
        return slope_per_min * 60  # mV/min → mV/hr

    def _count_tail_steady(self, records: list[dict]) -> int:
        """從最新一筆往回數，連續 ORP 在正常區間的筆數（分鐘數）"""
        count = 0
        for r in reversed(records):
            if self.orp_low <= r['orp'] <= self.orp_high:
                count += 1
            else:
                break
        return count
