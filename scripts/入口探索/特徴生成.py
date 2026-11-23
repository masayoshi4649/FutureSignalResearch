"""旧入口フレームを変えず、要求時点で利用可能な価格構造の特徴だけを作る。"""

from __future__ import annotations

import argparse
from collections import deque
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STUDY = ROOT / "study/00004_逆行200ptと順行400ptの入口分析"
DEFAULT_OUTPUT = ROOT / "work/入口探索"
SIZES = (5, 15, 30)
WINDOWS = (6, 12, 24)


def load_old() -> Any:
    """旧入口の足形成・準備判定を、そのまま参照できる形で読み込む。

    引数: なし。
    返り値: Any は旧分析モジュール。将来ラベルの計算処理は呼び出さない。
    """
    path = ROOT / "scripts/入口分析/分析.py"
    spec = importlib.util.spec_from_file_location("特徴生成用の固定入口", path)
    if spec is None or spec.loader is None:
        raise ImportError("旧入口分析を読み込めない")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


OLD = load_old()


# ----------------------------------------
# すべての出力列と、モデルに渡してよい列を先に固定する。

def feature_definitions() -> dict[str, dict[str, Any]]:
    """列名・式・欠測・モデル許可を定義する。

    引数: なし。
    返り値: dict[str, dict[str, Any]] は順序付きの特徴定義。日付・原行・ラベルは含めない。
    """
    result = {}

    def add(name: str, expression: str, model: bool = True) -> None:
        """特徴定義を一つ登録する。

        引数: name (str) は列、expression (str) は式・説明、model (bool) はモデル許可。
        返り値: None。欠測をゼロへ変換せず空欄にする定義も付ける。
        """
        result[name] = {"説明": expression, "型": "数値または欠測", "モデル許可": model,
                        "欠測": "未準備または分母0はCSV空欄。未来値・前値で補わない"}

    add("売買符号", "s。買い+1、売り−1")
    for size in SIZES:
        suffix = f"_{size}分"
        for field in ("始値", "高値", "安値", "終値"):
            add(field + suffix, f"最後に確定した{size}分足の{field}。価格水準は監査用", False)
        add("値幅pt" + suffix, "H−L。価格差であり円損益ではない")
        add("値幅ATR" + suffix, "(H−L)/当5分ATR14")
        add("実体pt" + suffix, "C−O。符号は通常の上昇/下落", False)
        add("方向実体pt" + suffix, "s×(C−O)")
        add("方向実体比" + suffix, "s×(C−O)/(H−L)")
        add("上ヒゲ比" + suffix, "(H−max(O,C))/(H−L)")
        add("下ヒゲ比" + suffix, "(min(O,C)−L)/(H−L)")
        add("反対ヒゲ比" + suffix, "買いは下ヒゲ比、売りは上ヒゲ比", size != 5)
        add("方向終値位置" + suffix, "買い(C−L)/(H−L)、売り(H−C)/(H−L)")
        add("EMA" + suffix, f"最後に確定した{size}分足のEMA20。価格水準は監査用", False)
        add("方向EMA距離pt" + suffix, f"s×(当5分終値−{size}分EMA20)")
        add("方向EMA距離ATR" + suffix, f"s×(当5分終値−{size}分EMA20)/当5分ATR14")
        add("方向EMA傾き" + suffix, f"s×({size}分EMA20−その足幅の前EMA20)。絶対値幅は監査用", False)
        add("方向EMA傾きATR" + suffix, f"s×({size}分EMA20−その足幅の前EMA20)/当5分ATR14")
        add("方向一致" + suffix, f"s×旧{size}分direction。方向内+1、逆方向−1、方向なし0")
        if size in (5, 15):
            add("方向RSI" + suffix, f"買いは{size}分RSI14、売りは100−同RSI")
    add("発動足の反対ヒゲ比", "反対ヒゲ比_5分と同値。モデルは重複する元列を除き本列だけ許可")
    for length in (1, 3, 6):
        add(f"方向変化pt_{length}本", f"s×(当5分終値−{length}本前の同場5分終値)")
        add(f"方向変化ATR_{length}本", f"方向変化pt_{length}本/当5分ATR14")
    for length in WINDOWS:
        suffix = f"_{length}本"
        add("過去高値" + suffix, f"当足除外・同場直前{length}本の最高値。監査用", False)
        add("過去安値" + suffix, f"当足除外・同場直前{length}本の最安値。監査用", False)
        add("過去幅pt" + suffix, "過去最高値−過去最安値")
        add("反対端距離pt" + suffix, "買いC−過去安値、売り過去高値−C。負値も保持")
        add("順方向端距離pt" + suffix, "買い過去高値−C、売りC−過去安値。突破後は負値")
        add("方向レンジ位置" + suffix, "反対端距離/過去幅。0〜1外へ出てもクリップしない")
        add("反対端内125" + suffix, "0<反対端距離pt<=125なら1。125pt損失の保証ではない")
        add("反対端復帰" + suffix, "買いは当足L<=過去L<C<=過去H、売りは過去L<=C<過去H<=当足Hなら1")
        add("方向端突破" + suffix, "順方向端距離pt<0なら1。等号は突破ではない")
    for name, explanation in {
        "上位足整合": "15・30分の旧方向が両方sなら1",
        "上位足相互整合": "15・30分の旧方向が等しく、かつ0でないなら1。売買side非依存",
        "全足整合": "5・15・30分の旧方向が全てsなら1",
        "押し戻り復帰": "旧recoveryがsなら1。前足時点でも当場15/30分が利用可能",
        "旧整合突破": "全足整合かつ旧sideがsなら1",
        "旧収縮拡大突破": "旧整合突破かつ前足収縮かつ当足拡大なら1",
        "ATR_5分": "確定5分足のWilder ATR14。絶対価格でなく値幅の尺度",
        "250ptのATR倍": "250/当5分ATR14",
        "125ptのATR倍": "125/当5分ATR14",
        "TR前ATR比": "当足TR/前5分ATR14",
        "前足収縮": "旧previous_squeeze。前足ATR/close<=前足より前60比の中央値",
        "当足拡大": "当足TR>前5分ATR14なら1",
        "観測数量比": "当足の観測累積差分量/同場直前20有効足の平均。量は完全約定数量ではない",
        "残り分_判断時": "旧要求時点から固定評価期限までの分数。所要分や到達時計を使わない",
        "セッション経過分": "(旧要求時計−当セッション開始時計)/60。日付・時計値自体はモデルへ渡さない",
        "再テスト_6本": "過去1〜3足の6本高安突破の固定水準に今足が触れ、終値が方向側へ戻れば1。今足の突破は未登録",
        "再テスト水準距離pt": "s×(当5分C−固定突破水準)。最新の接触成立水準、なければ最新の有効水準から測る",
        "再テスト経過本数_6本": "採用固定突破水準の登録足から1〜3本。水準がなければ欠測",
    }.items():
        add(name, explanation)
    add("再テスト元価格_6本", "再テストの参照突破水準。将来更新せず登録時に固定。価格水準は監査用", False)
    return result


DEFINITIONS = feature_definitions()


def features_for_side(bar: dict[str, Any], values: dict[str, Any], history: list[dict[str, Any]],
                      candles: dict[int, dict[str, Any]], channels: dict[int, dict[str, Any]],
                      breaks: list[dict[str, Any]], side: int) -> dict[str, Any]:
    """確定済みの状態だけから、買い/売りで向きを揃えた特徴を作る。

    引数: bar/values (dict[str, Any]) は当5分足と旧指標、history (list[dict[str, Any]]) は当足を含まない同場履歴、
    candles/channels (dict[int, dict[str, Any]]) は各確定足と指標、breaks (list[dict[str, Any]]) は過去の固定突破、side (int) は+1/−1。
    返り値: dict[str, Any] はラベルを持たない特徴。未来の新規価格を参照しない。
    """
    assert side in (1, -1)
    result = {name: None for name in DEFINITIONS}
    close, atr = bar["close"], values["atr"]
    denominator = atr if atr is not None and atr > 0 else None
    result["売買符号"] = side
    for size in SIZES:
        candle, state = candles.get(size), channels.get(size)
        if candle is None or state is None:
            continue
        suffix = f"_{size}分"
        opening, high, low, ending = (candle[key] for key in ("open", "high", "low", "close"))
        width = high - low
        for name, value in zip(("始値", "高値", "安値", "終値"), (opening, high, low, ending)):
            result[name + suffix] = value
        result["値幅pt" + suffix] = width
        result["値幅ATR" + suffix] = width / denominator if denominator else None
        result["実体pt" + suffix] = ending - opening
        result["方向実体pt" + suffix] = side * (ending - opening)
        result["方向実体比" + suffix] = side * (ending - opening) / width if width else None
        upper_wick = (high - max(opening, ending)) / width if width else None
        lower_wick = (min(opening, ending) - low) / width if width else None
        result["上ヒゲ比" + suffix], result["下ヒゲ比" + suffix] = upper_wick, lower_wick
        result["反対ヒゲ比" + suffix] = lower_wick if side == 1 else upper_wick
        result["方向終値位置" + suffix] = ((ending - low) if side == 1 else (high - ending)) / width if width else None
        ema, previous_ema = state["ema"], state["ema_previous"]
        result["EMA" + suffix] = ema
        distance = side * (close - ema) if ema is not None else None
        slope = side * (ema - previous_ema) if ema is not None and previous_ema is not None else None
        result["方向EMA距離pt" + suffix] = distance
        result["方向EMA距離ATR" + suffix] = distance / denominator if distance is not None and denominator else None
        result["方向EMA傾き" + suffix] = slope
        result["方向EMA傾きATR" + suffix] = slope / denominator if slope is not None and denominator else None
        result["方向一致" + suffix] = side * state["direction"]
        if size in (5, 15):
            result["方向RSI" + suffix] = (state["rsi"] if side == 1 else 100 - state["rsi"]) if state["rsi"] is not None else None
    result["発動足の反対ヒゲ比"] = result["反対ヒゲ比_5分"]
    for length in (1, 3, 6):
        change = side * (close - history[-length]["close"]) if len(history) >= length else None
        result[f"方向変化pt_{length}本"] = change
        result[f"方向変化ATR_{length}本"] = change / denominator if change is not None and denominator else None
    for length in WINDOWS:
        if len(history) < length:
            continue
        suffix = f"_{length}本"
        high = max(item["high"] for item in history[-length:])
        low = min(item["low"] for item in history[-length:])
        opposite = close - low if side == 1 else high - close
        forward = high - close if side == 1 else close - low
        result["過去高値" + suffix], result["過去安値" + suffix] = high, low
        result["過去幅pt" + suffix] = high - low
        result["反対端距離pt" + suffix], result["順方向端距離pt" + suffix] = opposite, forward
        result["方向レンジ位置" + suffix] = opposite / (high - low) if high > low else None
        result["反対端内125" + suffix] = int(0 < opposite <= 125)
        returned = bar["low"] <= low < close <= high if side == 1 else low <= close < high <= bar["high"]
        result["反対端復帰" + suffix] = int(returned)
        result["方向端突破" + suffix] = int(forward < 0)
    d5, d15, d30 = (values[key] for key in ("direction5", "direction15", "direction30"))
    aligned = all(direction == side for direction in (d5, d15, d30))
    breakout = aligned and values["side"] == side
    result.update({"上位足整合": int(d15 == d30 == side),
                   "上位足相互整合": int(d15 == d30 and d15 in (-1, 1)), "全足整合": int(aligned),
                   "押し戻り復帰": int(values["recovery"] == side), "旧整合突破": int(breakout),
                   "旧収縮拡大突破": int(breakout and values["previous_squeeze"] and values["expansion"]),
                   "ATR_5分": atr, "250ptのATR倍": 250 / denominator if denominator else None,
                   "125ptのATR倍": 125 / denominator if denominator else None,
                   "TR前ATR比": values["tr_previous_atr"], "前足収縮": int(values["previous_squeeze"]),
                   "当足拡大": int(values["expansion"]), "観測数量比": values["relative_volume"]})
    candidates = [item for item in breaks if item["side"] == side and 1 <= bar["index"] - item["index"] <= 3]
    touched = [item for item in candidates if (bar["low"] <= item["level"] < close if side == 1
                                               else bar["high"] >= item["level"] > close)]
    result["再テスト_6本"] = int(bool(touched))
    if candidates:
        anchor = (touched or candidates)[-1]
        result.update({"再テスト元価格_6本": anchor["level"], "再テスト水準距離pt": side * (close - anchor["level"]),
                       "再テスト経過本数_6本": bar["index"] - anchor["index"]})
    return result


# ----------------------------------------
# 旧足形成へ観測を加える。旧準備判定や入口の発生時点は変更しない。

class 価格構造特徴(OLD.入口特徴):
    """旧指標更新と同時に、同場の価格窓と固定突破水準を記録する。"""

    def __init__(self) -> None:
        """欠枠再初期化でも既に記録した特徴を保持して状態だけ消去する。

        引数: なし。
        返り値: None。recorded (dict) は足終了時計をキーとする記録。
        """
        saved = getattr(self, "recorded", {})
        super().__init__()
        self.recorded = saved
        self.history = deque(maxlen=24)
        self.candles, self.parts, self.breaks = {}, {}, []

    def start_session(self, start: float) -> None:
        """共通指標の継続を保ち、追加した同場の窓と水準だけを消す。

        引数: start (float) はセッション開始Unix秒。
        返り値: None。過去に記録済みのイベント特徴は消さない。
        """
        super().start_session(start)
        self.history.clear()
        self.candles.clear()
        self.parts.clear()
        self.breaks.clear()

    def update_candles(self, bar: dict[str, Any]) -> None:
        """旧と同じ場内区間でOHLCを集約し、完全な上位足だけ保存する。

        引数: bar (dict[str, Any]) は確定5分足。
        返り値: None。EMAやラベルを独自に計算し直さない。
        """
        self.candles[5] = dict(bar)
        for size in (15, 30):
            factor = size // 5
            if bar["index"] % factor == 0:
                self.parts[size] = {key: bar[key] for key in ("open", "high", "low", "close")}
                self.parts[size]["count"] = 1
            elif size in self.parts:
                part = self.parts[size]
                part.update({"high": max(part["high"], bar["high"]), "low": min(part["low"], bar["low"]),
                             "close": bar["close"], "count": part["count"] + 1})
            if bar["index"] % factor == factor - 1:
                part = self.parts.pop(size, None)
                if part and part["count"] == factor:
                    self.candles[size] = part

    def update(self, bar: dict[str, Any]) -> dict[str, Any]:
        """当足の特徴を保存してから、新しい突破水準と価格履歴を登録する。

        引数: bar (dict[str, Any]) は確定5分足。
        返り値: dict[str, Any] は変更していない旧入口の判定値。
        """
        values = super().update(bar)
        self.update_candles(bar)
        history = list(self.history)
        channels = {size: self.bank.channels[size].result for size in SIZES}
        for size, candle in self.candles.items():
            assert candle["close"] == channels[size]["close"], "追加OHLCと旧指標の終値が不一致"
        self.breaks = [item for item in self.breaks if bar["index"] - item["index"] <= 3]
        if values["ready"]:
            self.recorded[bar["end"]] = {side: features_for_side(bar, values, history, self.candles, channels, self.breaks, side)
                                          for side in (1, -1)}
        if len(history) >= 6:
            high, low = max(item["high"] for item in history[-6:]), min(item["low"] for item in history[-6:])
            if bar["close"] > high:
                self.breaks.append({"side": 1, "level": high, "index": bar["index"]})
            elif bar["close"] < low:
                self.breaks.append({"side": -1, "level": low, "index": bar["index"]})
        self.history.append(dict(bar))
        return values


# ----------------------------------------
# 合成値による式・向き・同場窓・再テスト時点の検証

def synthetic_tests() -> list[dict[str, Any]]:
    """既知の小例で方向反転、窓の除外、分母0、再初期化を確認する。

    引数: なし。
    返り値: list[dict[str, Any]] は合格した検査名。不一致ならAssertionErrorにする。
    """
    bar = {"index": 7, "open": 105.0, "high": 120.0, "low": 90.0, "close": 115.0}
    history = [{"open": 105.0, "high": 110.0, "low": 100.0, "close": 105.0} for _ in range(6)]
    state = {"ema": 110.0, "ema_previous": 108.0, "direction": 1, "rsi": 65.0, "close": 115.0}
    channels = {size: dict(state) for size in SIZES}
    candles = {size: dict(bar) for size in SIZES}
    values = {"atr": 10.0, "direction5": 1, "direction15": 1, "direction30": 1, "side": 1,
              "recovery": 1, "previous_squeeze": True, "expansion": True, "tr_previous_atr": 3.0,
              "relative_volume": None}
    buy = features_for_side(bar, values, history, candles, channels, [], 1)
    sell = features_for_side(bar, values, history, candles, channels, [], -1)
    assert buy["方向実体pt_5分"] == 10 and sell["方向実体pt_5分"] == -10
    assert buy["方向RSI_5分"] == 65 and sell["方向RSI_5分"] == 35
    assert buy["方向EMA傾きATR_15分"] == 0.2 and sell["方向EMA傾きATR_15分"] == -0.2
    assert buy["過去高値_6本"] == 110 and buy["順方向端距離pt_6本"] == -5
    assert buy["方向レンジ位置_6本"] == 1.5 and buy["過去高値_12本"] is None
    assert buy["発動足の反対ヒゲ比"] == 0.5 and sell["発動足の反対ヒゲ比"] == 1 / 6
    prior = [{"side": 1, "index": 6, "level": 110.0}]
    retest = features_for_side(bar, values, history, candles, channels, prior, 1)
    assert buy["再テスト_6本"] == 0 and retest["再テスト_6本"] == 1
    assert retest["再テスト水準距離pt"] == 5 and retest["再テスト経過本数_6本"] == 1
    current_only = features_for_side(bar, values, history, candles, channels,
                                      [{"side": 1, "index": 7, "level": 110.0}], 1)
    assert current_only["再テスト_6本"] == 0
    expired = features_for_side(bar, values, history, candles, channels,
                                 [{"side": 1, "index": 3, "level": 110.0}], 1)
    assert expired["再テスト_6本"] == 0
    short_bar = {**bar, "open": 115.0, "close": 105.0}
    short_values = {**values, "direction5": -1, "direction15": -1, "direction30": -1, "side": -1, "recovery": -1}
    short_channels = {size: {**state, "ema_previous": 112.0, "close": 105.0, "direction": -1, "rsi": 35.0} for size in SIZES}
    short = features_for_side(short_bar, short_values, history, {size: short_bar for size in SIZES}, short_channels,
                               [{"side": -1, "index": 6, "level": 110.0}], -1)
    assert short["再テスト_6本"] == 1 and short["再テスト水準距離pt"] == 5
    assert short["方向実体pt_5分"] == 10 and short["方向RSI_5分"] == 65
    flat = {**bar, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}
    flat_values = features_for_side(flat, values, [dict(flat) for _ in range(6)],
                                    {size: dict(flat) for size in SIZES}, channels, [], 1)
    assert flat_values["方向実体比_5分"] is None and flat_values["方向レンジ位置_6本"] is None
    bank = 価格構造特徴()
    bank.recorded[1] = "既記録"
    bank.history.append(bar)
    bank.breaks.append(prior[0])
    bank.start_session(1000)
    assert not bank.history and not bank.breaks
    bank.__init__()
    assert bank.recorded[1] == "既記録" and not bank.history
    names = ("売買の方向化・RSI反転・EMA傾きATR", "当足を除く高安・未準備窓・レンジ外を保持",
             "反対ヒゲの売買変換", "過去突破の固定水準・現在突破不使用・3本失効",
             "売りの再テスト・方向実体・方向RSI", "値幅0の比率は欠測", "場境界・欠足再初期化と既記録の保持")
    return [{"検査": name, "合格": True} for name in names]


# ----------------------------------------
# 旧イベント全件の再計算と自己照合。出力にラベル・時計・原行は渡さない。

def write_json(path: Path, value: Any) -> None:
    """日本語UTF-8で有限値のみのJSONを保存する。

    引数: path (Path) は保存先、value (Any) はJSON化する値。
    返り値: None。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def make_schema(study: Path) -> dict[str, Any]:
    """モデル許可列と、未来情報を使わない計算条件を保存用にまとめる。

    引数: study (Path) は旧10588イベントの参照元。
    返り値: dict[str, Any] は特徴定義。ラベルや期間IDをモデル列へ含めない。
    """
    dependencies = (Path(OLD.__file__), Path(OLD.SHARED_PATH), Path(OLD.shared.LEGACY_PATH),
                    ROOT / "scripts/複合検証/データ準備.py")
    return {"版": 1, "キー": "イベントID", "入力試行": str(study), "NumPy": OLD.np.__version__,
            "columns": ["イベントID", *DEFINITIONS],
            "model_columns": [name for name, definition in DEFINITIONS.items() if definition["モデル許可"]],
            "監査列": [name for name, definition in DEFINITIONS.items() if not definition["モデル許可"]],
            "特徴": DEFINITIONS, "特徴生成コードSHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "依存コードSHA256": {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in dependencies},
            "式の前提": {"s": "買い+1、売り−1", "O/H/L/C": "各足幅の最後に確定した足",
                         "足幅別ATR正規化": "全て現在の確定5分ATR14で割る。15/30分ATRではない",
                         "窓": "同セッション、今足除外。欠5分枠で同場構造をリセット。6/12/24足不足は欠測",
                         "EMA/Wilder履歴": "旧入口と同じ履歴継続。場境界で前足比較・OHLC窓・再テストを消す",
                         "再テスト": "前1〜3本の純粋な終値6本高安突破を保存。最新の接触成立水準、なければ最新有効水準を参照。今足登録は評価後",
                         "距離": "当5分終値基準。未来の新規約定価格から距離を逆算しない"},
            "除外": "開始日・場名・原板行・イベントID・絶対時計・旧新先着ラベルをモデルに使わない。raw OHLC/EMA/絶対傾きもモデル不可",
            "一次資料_2026-11-01確認": {
                "EMAの方向・押し戻り・遅れ": "https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/ema",
                "支持抵抗・過去高安・再接触の一般的説明": "https://www.cmegroup.com/education/courses/technical-analysis/support-and-resistance",
                "OHLC・実体・ヒゲの構成": "https://www.cmegroup.com/education/courses/technical-analysis/chart-types-candlestick-line-bar",
                "収縮・突破・偽突破の一般的説明": "https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/bollinger-band-squeeze"},
            "注意": "旧60場は全て既使用探索。閾値125/250・各特徴が70%の成功を保証するものではない"}


def run(study: Path, output: Path, schema_only: bool = False) -> None:
    """旧フレーム全件の一致を確認してから、特徴だけを作業領域へ保存する。

    引数: study/output (Path) は旧試行と出力先、schema_only (bool) は定義・合成検査だけ作るか。
    返り値: None。不一致時は例外で停止し、特徴CSVを更新しない。
    """
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "特徴定義.json", make_schema(study))
    write_json(output / "合成検証結果.json", synthetic_tests())
    if schema_only:
        print(f"特徴定義を保存: {output / '特徴定義.json'}")
        return
    source = study / "入口事例.csv"
    with source.open(encoding="utf-8-sig", newline="") as stream:
        original = list(csv.DictReader(stream))
    indexed = {row["イベントID"]: row for row in original}
    assert len(original) == len(indexed) == 10588, "旧10588イベントの一意なフレームでない"
    manifest, manifest_path = OLD.shared.read_manifest(study)
    entries = [entry for entry in manifest["entries"] if entry["symbol"] == "NK225"]
    assert len(entries) == 60, "固定NK225入力が60場でない"
    preparation = OLD.shared.load_preparation()
    bank, contract, features, regenerated = 価格構造特徴(), None, [], []
    checked, cache_hashes = 0, {}
    compare_fields = ("足終了時計秒", "要求時計秒", "要求原板行", "確認遅延秒", "終値", "EMA5", "ATR5",
                      "RSI5", "RSI15", "方向5", "方向15", "方向30", "観測数量比")
    for entry in entries:
        bank.recorded.clear()
        cache = ROOT / "work/複合検証" / entry["cache_path"]
        digest = hashlib.sha256(cache.read_bytes()).hexdigest()
        assert digest == entry["sha256_cache"] and cache.stat().st_size == entry["cache_size"], "固定キャッシュ不一致"
        cache_hashes[entry["session"]] = digest
        code = tuple(entry["contract_codes"])
        assert len(code) == 1, "場内限月が一意でない"
        if code != contract:
            bank, contract = 価格構造特徴(), code
        start, end, _, _ = OLD.shared.legacy.session_times(entry["session"])
        events, previous_time = [], None
        for event in preparation.read_events(cache):
            if not math.isfinite(event.now) or not start.timestamp() <= event.now <= end.timestamp():
                continue
            if previous_time is not None and event.now < previous_time:
                continue
            previous_time = event.now
            events.append(event)
        rows, _ = OLD.candidate_rows(events, entry["session"], bank)
        for row in rows:
            identity = row["イベントID"]
            assert identity in indexed, f"旧にない候補が発生: {identity}"
            old_row = indexed[identity]
            assert row["場"] == old_row["場"] and row["方向"] == old_row["方向"], "旧場・方向と不一致"
            for field in compare_fields:
                actual, expected = row[field], old_row[field]
                blank = actual is None or (isinstance(actual, float) and not math.isfinite(actual))
                assert (blank and expected == "") or (not blank and expected != "" and abs(float(actual) - float(expected)) <= 1e-9), f"旧属性と不一致: {identity}/{field}"
                checked += 1
            values = dict(bank.recorded[row["足終了時計秒"]][int(row["side"])])
            values["残り分_判断時"] = row["残り分_判断時"]
            values["セッション経過分"] = (row["要求時計秒"] - start.timestamp()) / 60
            assert set(values) == set(DEFINITIONS), "定義と実装の列が不一致"
            assert all(value is None or (isinstance(value, (int, float)) and math.isfinite(value)) for value in values.values()), "特徴に非数値・非有限値がある"
            features.append({"イベントID": identity, **values})
            regenerated.append(identity)
        print(f"特徴再計算 {entry['session']} {len(rows)}イベント", flush=True)
    assert regenerated == [row["イベントID"] for row in original], "旧フレームの件数・順序と不一致"
    target = output / "特徴.csv"
    with target.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["イベントID", *DEFINITIONS])
        writer.writeheader()
        writer.writerows(features)
    report = {"日時": OLD.shared.legacy.datetime.now(OLD.JST).isoformat(), "Python": platform.python_version(), "NumPy": OLD.np.__version__,
              "フレーム一致": True, "旧イベント数": len(original), "生成イベント数": len(features),
              "旧属性一致検査数": checked, "旧属性参照列": list(compare_fields), "全属性一致": True,
              "特徴列数": len(DEFINITIONS), "モデル許可列数": sum(value["モデル許可"] for value in DEFINITIONS.values()),
              "旧入口CSV_SHA256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "参照台帳SHA256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
              "特徴CSV_SHA256": hashlib.sha256(target.read_bytes()).hexdigest(),
              "特徴生成コードSHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "キャッシュSHA256": cache_hashes, "注意": "ラベルを生成・参照せず特徴だけを再計算。モデルの有効性の証明ではない"}
    write_json(output / "生成照合結果.json", report)
    print(f"全{len(features)}イベント・旧属性{checked}件が一致。特徴{len(DEFINITIONS)}列: {target}")


def main() -> None:
    """参照試行と作業出力先を指定して特徴を生成する。

    引数: なし。argparseで--study/--output (Path)、--schema-only (bool) を読む。
    返り値: None。
    """
    parser = argparse.ArgumentParser(description="旧入口フレームに価格構造特徴を追加し、全件一致を確認")
    parser.add_argument("--study", type=Path, default=DEFAULT_STUDY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--schema-only", action="store_true")
    args = parser.parse_args()
    run(args.study.resolve(), args.output.resolve(), args.schema_only)


if __name__ == "__main__":
    main()
