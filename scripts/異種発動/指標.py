"""固定W系列へMACDとSMA型ストキャスを追加する。"""

from __future__ import annotations

from collections import deque
import importlib.util
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("異種発動の固定W", ROOT/"scripts/広域研究/検証.py")
W = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = W
SPEC.loader.exec_module(W)


class Indicators(W.Indicators):
    """同限月carry/resetを共有する二つの新指標銀行。"""

    def __init__(self) -> None:
        """算術seedのEMAと連続有効Kの平均窓を空にする。

        引数: なし。
        返り値: None。親の欠枠resetからも全系列を初期化する。
        """
        super().__init__()
        average = W.OLD.shared.legacy.Average
        self.fast, self.slow, self.signal = average(12, 2/13), average(26, 2/27), average(9, 2/10)
        self.ohlc14, self.raw3, self.slow3 = deque(maxlen=14), deque(maxlen=3), deque(maxlen=3)

    def update(self, bar: dict) -> dict:
        """一足の終値MACDと当足を含む高安Stochを計算する。

        引数: bar (dict) は確定幅OHLC。公開可否は入口で制限する。
        返り値: dict は旧W値と新列。ゼロrangeはKを補わず平滑窓を切る。
        """
        result = super().update(bar)
        fast, slow = self.fast.update(bar["close"]), self.slow.update(bar["close"])
        macd = fast-slow if fast is not None and slow is not None else None
        signal = self.signal.update(macd) if macd is not None else None
        hist = macd-signal if macd is not None and signal is not None else None
        self.ohlc14.append((bar["high"], bar["low"]))
        raw, k, d = None, None, None
        if len(self.ohlc14) == 14:
            high, low = max(h for h, _ in self.ohlc14), min(l for _, l in self.ohlc14)
            if high > low:
                raw = 100*(bar["close"]-low)/(high-low)
        if raw is None or not math.isfinite(raw):
            self.raw3.clear()
            self.slow3.clear()
        else:
            self.raw3.append(raw)
            if len(self.raw3) == 3:
                k = sum(self.raw3)/3
                self.slow3.append(k)
                if len(self.slow3) == 3:
                    d = sum(self.slow3)/3
        mean, sd = result["bb_mean"], result["bb_sd"]
        width = 4*sd/mean if mean is not None and sd is not None and mean > 0 and sd > 0 else None
        result.update(macd=macd, macd_signal=signal, macd_hist=hist,
                      stoch_raw=raw, stoch_k=k, stoch_d=d, bandwidth=width)
        return result


def features(bars: list[dict], bank: Indicators, start: float) -> list[dict]:
    """旧Wの欠枠初期化と全完全幅足更新をそのまま使う。

    引数: bars (list[dict]) は半開足、bank (Indicators) は同限月銀行、start (float) は場開始。
    返り値: list[dict] は新指標付き足。非公開足も数値更新し発動では除外する。
    """
    return W.features(bars, bank, start)
