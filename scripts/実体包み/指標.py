"""固定29の15列を共有し、当足を除く二つのSMA20を精密計算する。"""

from collections import Counter, deque
from copy import deepcopy
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("実体包みの固定29価格", ROOT/"scripts/OBV反転/指標.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
SOURCE_FIELDS, VALID = BASE.SOURCE_FIELDS, BASE.VALID
FRAME_FIELDS = ("場", *SOURCE_FIELDS, "atr", "macd_hist")
SMA_FIELDS = ("SMA前", "SMA前々", "SMA進行", "終値対前SMA", "SMA準備", "SMA進行符号", "SMA位置符号",
              "SMA前20足番号", "SMA前々20足番号", "SMA過去足数", "SMA最遅公開key", "SMA解除理由")
NUMERIC_FIELDS = (*FRAME_FIELDS, *SMA_FIELDS)
RULES = {
    "共有": "場/SOURCE12/atr/macd_histの固定29正本15列だけをstrictコピー。旧MACD/ATRを更新し直さず、新float銀行や正本blobは作らない",
    "平均": "SMA前=mean(C[j-20..j-1])、SMA前々=mean(C[j-21..j-2])。同場連続公開21過去Cが共通準備、最速j21で現在含22足。当足jを両平均へ入れない",
    "精密": "各元floatCをFraction化。進行=SMA前-SMA前々、位置=Cj-SMA前を既約分数で保存し、符号/採否は分子でstrict比較。表示float/epsilon/割合乖離率を使わない",
    "局所": "同場公開有効完全180秒/missing0。NP/missing>0/OHLC不正はclearして当足不投入。番号/endgap後のmissing0有効当足は新seed可。公開key同値/後退・重複indexは入力拒否",
    "時点": "j公開key時点の観測。p.key<j.key/両confirm>=endで参照し、j.end>p.confirm又はj.start前のp公開を追加要求しない",
}


def finite(value: object) -> bool:
    """欠測・真偽値・非有限を除く実数かを確認する。

    引数: value(object)は観測値。
    返り値: boolは有限の整数又はfloatであること。
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def exact(value: Fraction | None) -> dict:
    """精密値を参考表示と分子分母へ写す。

    引数: value(Fraction|None)は計算値又は未準備。
    返り値: dictは値/分子/分母/有効。未準備を0にしない。
    """
    return {"値": float(value) if value is not None else None,
            "分子": value.numerator if value is not None else None,
            "分母": value.denominator if value is not None else None, "有効": value is not None}


def canonical_sha(value: object) -> str:
    """全属性と配列順を厳密JSONで指紋化する。

    引数: value(object)はJSON互換値。
    返り値: strはSHA256。非有限値は拒否する。
    """
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def frame_projection(row: dict | None) -> dict | None:
    """保存29の価格出典とATR/Hだけを深複写する。

    引数: row(dict|None)は共有足又は参照なし。
    返り値: dict|Noneは15列。数量/DI/Fast/未来labelを含めない。
    """
    return None if row is None else {name: deepcopy(row[name]) for name in FRAME_FIELDS}


def numeric_projection(row: dict) -> dict:
    """共有15列と新SMAだけを正式数値へ写す。

    引数: row(dict)は新計算済み足。
    返り値: dictはNUMERIC_FIELDSの27列。
    """
    return {name: deepcopy(row[name]) for name in NUMERIC_FIELDS}


def price_valid(row: dict) -> bool:
    """公開とは分けて完全3分OHLCを判定する。

    引数: row(dict)は価格足。
    返り値: boolは完全180秒・有効OHLCであること。
    """
    return bool(row["minutes"] == 3 and row["end"]-row["start"] == 180 and VALID(row))


def sma_state(past: list[dict], close: float) -> dict:
    """現在を除く21過去終値から二平均と位置・進行を計算する。

    引数: past(list[dict])は古い順の最大21有効足、close(float)は現終値。
    返り値: dictは精密平均/差/符号/出典。共通準備以前の既知前平均も保存する。
    """
    current = sum(Fraction(row["close"]) for row in past[-20:])/20 if len(past) >= 20 else None
    previous = sum(Fraction(row["close"]) for row in past[-21:-1])/20 if len(past) >= 21 else None
    change = current-previous if current is not None and previous is not None else None
    position = Fraction(close)-current if current is not None and finite(close) else None
    return {"SMA前": exact(current), "SMA前々": exact(previous), "SMA進行": exact(change), "終値対前SMA": exact(position),
        "SMA準備": change is not None and position is not None,
        "SMA進行符号": (change > 0)-(change < 0) if change is not None else None,
        "SMA位置符号": (position > 0)-(position < 0) if position is not None else None,
        "SMA前20足番号": [row["index"] for row in past[-20:]],
        "SMA前々20足番号": [row["index"] for row in past[-21:-1]], "SMA過去足数": len(past),
        "SMA最遅公開key": [past[-1]["confirm"], past[-1]["confirm_line"]] if past else None}


def build(frames: list[dict], session: str) -> tuple[list[dict], dict]:
    """当場の共有15列へ、過去だけのSMA出典を一度付加する。

    引数: frames(list[dict])は固定29の当場3分足、session(str)は場。
    返り値: tuple[list[dict],dict]は新27列と品質。ATR/Hの再計算や市場読取をしない。
    """
    history, rows = deque(maxlen=21), []
    previous, public_key = None, None
    counts = Counter({"局所解除足数": 0})
    for source in frames:
        row = frame_projection(source)
        if row["場"] != session or row["minutes"] != 3:
            raise ValueError("当場の共有3分足だけです")
        key = row["confirm"], row["confirm_line"]
        if previous is not None and row["index"] <= previous["index"]:
            raise ValueError("足番号重複又は後退")
        if row["publish"] and (row["confirm"] < row["end"] or public_key is not None and key <= public_key):
            raise ValueError("公開key同値/後退又は終了前公開")
        reasons = []
        if previous is None and row["index"] != 0 or previous is not None and (
                row["index"] != previous["index"]+1 or row["start"] != previous["end"]):
            reasons.append("番号又は終了非連続")
        if row["missing"]:
            reasons.append("欠枠")
        if not row["publish"]:
            reasons.append("非公開")
        if not price_valid(row):
            reasons.append("完全3分価格不正")
        if reasons:
            history.clear(); counts["局所解除足数"] += 1
        eligible = bool(row["publish"] and not row["missing"] and price_valid(row))
        panel = sma_state(list(history), row["close"]) if eligible else sma_state([], 0.)
        rows.append({**row, **panel, "SMA解除理由": reasons})

        # ----------------------------------------
        # 現在足は自分の平均を作った後で、後続足用の過去窓へ一回だけ入れる。
        if eligible:
            history.append(row)
        previous = row
        if row["publish"]:
            public_key = key
    return rows, {"場": session, "時間足分": 3, "入力足数": len(rows), **dict(counts),
        "SMA共通準備足数": sum(row["SMA準備"] for row in rows),
        "SMA前単独準備足数": sum(row["SMA前"]["有効"] for row in rows)}
