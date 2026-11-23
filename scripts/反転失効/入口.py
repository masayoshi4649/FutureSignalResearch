"""固定00015の反転準備を逆向き対照と第2極値失効後の入口へ移す。"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BASE_CONDITION = ROOT/"study/00015_RSIの山谷と価格構造/条件.json"
FAMILIES = {"単純逆向き": "単純逆向き", "価格失効待ち": "価格失効待ち"}
EXTRAS = ("なし", "15分方向一致")
WATCH_SETTINGS = {"下限本数": 1, "上限本数": 6, "最新一件": True, "同足発動": False}


def shared() -> Any:
    """固定00015の入口を別モジュールとして読み込む。

    引数: なし。
    返り値: Any は旧15入口。旧ファイルは変更せず、生成には旧条件だけを渡す。
    """
    spec = importlib.util.spec_from_file_location("反転失効の固定15入口", ROOT/"scripts/RSI構造/入口.py")
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


BASE = shared()
BASE_CONFIG = json.loads(BASE_CONDITION.read_text(encoding="utf-8"))


def validate_config(config: dict) -> None:
    """固定三尺度・二方式・二上位条件・監視本数を検査する。

    引数: config (dict) は00016の条件。
    返り値: None。不一致ではValueErrorを送出する。
    """
    if config["時間足分"] != [1, 3, 5] or config["入口系統"] != list(FAMILIES) or config["補助"] != list(EXTRAS) or config["監視条件"] != WATCH_SETTINGS:
        raise ValueError("固定三尺度・二方式・二補助・次1〜6本だけを扱う")
    if config["確認遅延上限秒"] != 30:
        raise ValueError("準備/発動の共通30秒上限を変更しない")


def preparation(source: dict) -> dict:
    """準備時点の属性を現在判断足と異なる名前へ固定する。

    引数: source (dict) は旧15反転乖離・なしの一信号。
    返り値: dict は未来ラベルを含まない不変の準備参照。
    """
    return {"元準備イベントID": source["イベントID"], "準備足番号": source["index"],
            "準備時計秒": source["要求時計秒"], "準備原板行": source["要求原板行"],
            "元準備side": source["side"], "実入口側": -source["side"],
            "第2極値価格": source["現極値"]["極値価格"], "第2極値中心番号": source["現極値"]["中心番号"],
            "準備確認遅延秒": source["確認遅延秒"], "準備ATR14": source["atr"], "準備RSI14": source["rsi"],
            "準備上位方向": source["上位方向"], "準備上位確認秒": source["上位確認秒"],
            "準備上位確認行": source["上位確認行"], "準備上位足終了秒": source["上位足終了秒"],
            "前極値": deepcopy(source["前極値"]), "現極値": deepcopy(source["現極値"])}


# ----------------------------------------
# 一足ごとに旧監視の判定を先に済ませ、新準備の登録を最後に行う。

def generate(frames: list[dict], higher: list[dict], session: str, cutoff: float,
             deadline: float, config: dict) -> tuple[dict[str, list[dict]], dict]:
    """最新一件の反転準備を監視し、元側と逆の現在入口を生成する。

    引数: frames/higher (list[dict]) は同場1/3/5分/15分特徴、session (str) は場、
    cutoff/deadline (float) は新規停止/期限秒、config (dict) は00016の固定条件。
    返り値: tuple[dict[str,list[dict]],dict] は当尺度四入口と全準備/監視・品質。
    """
    validate_config(config)
    if not frames:
        raise ValueError("入口尺度を特定できる足がない")
    size = frames[0]["minutes"]
    if size not in (1, 3, 5) or any(f["minutes"] != size for f in frames):
        raise ValueError("当場の同尺度1/3/5分だけを扱う")
    original, original_quality = BASE.generate(frames, higher, session, cutoff, deadline, BASE_CONFIG)
    prepared = original[f"{size}分_反転乖離_なし"]
    source_by_index = {}
    for source in prepared:
        if source["index"] in source_by_index:
            raise ValueError("同じ尺度・同じ足の準備信号が複数ある")
        source_by_index[source["index"]] = source
    output = {f"{size}分_{family}_{extra}": [] for family in FAMILIES for extra in EXTRAS}
    counter, rejected, preparation_records, watch_records = Counter(), Counter(), [], []
    active, pointer, upper, previous_key, previous_index = None, 0, None, None, None

    def log(action: str, row: dict, reference: dict | None, **attributes: Any) -> None:
        """監視の原順と当時の準備参照を追記する。

        引数: action (str) は状態動作、row (dict) は現足、reference (dict|None) は準備、attributes (Any) は判定属性。
        返り値: None。記録を追加し動作件数を数える。
        """
        watch_records.append(deepcopy({"場": session, "時間足分": size, "状態順序": len(watch_records)+1, "動作": action,
                              "判断足番号": row["index"], "判断足終了秒": row["end"], "判断時計秒": row["confirm"],
                              "判断原板行": row["confirm_line"], "判断終値": row["close"], "準備参照": reference, **attributes}))
        counter[action] += 1

    def emit(family: str, row: dict, reference: dict, age: int) -> list[str]:
        """現在足の準備・時間・実入口側の上位方向で発動を選別する。

        引数: family (str) は二方式、row/reference (dict) は現在足/準備参照、age (int) は経過足数。
        返り値: list[str] は発動した入口ID。抑止理由は別に保存する。
        """
        side = reference["実入口側"]
        reasons = []
        if not BASE.CORE.defined(row.get("rsi"), row.get("atr")) or row["atr"] <= 0:
            reasons.append("判断RSI_ATR未準備")
        if not row["上位準備済"]:
            reasons.append("上位未準備")
        if row["confirm"] >= cutoff or deadline-row["confirm"] < config["残り時間下限分"]*60:
            reasons.append("時間条件不成立")
        if row["confirm"]-row["end"] > 30:
            reasons.append("確認遅延30秒超")
        fired, by_extra = [], {}
        for extra in EXTRAS:
            extra_reasons = reasons+(["実入口側と15分方向不一致"] if extra != "なし" and row["上位方向"] != side else [])
            by_extra[extra] = extra_reasons
            source_id = f"{size}分_{family}_{extra}"
            if extra_reasons:
                rejected.update(extra_reasons)
                continue
            signal = {**row, "準備属性": deepcopy(reference), **{k: reference[k] for k in ("元準備イベントID", "第2極値価格", "準備足番号", "準備時計秒", "準備原板行", "元準備side", "実入口側")},
                      "場": session, "時間足分": size, "入口ID": source_id, "入口系統": family, "補助": extra,
                      "役割": "順行", "side": side, "方向": "買い" if side == 1 else "売り", "待機本数": age,
                      "イベントID": f"NK225_{session}_{source_id}_{row['index']:04d}_{side}",
                      "要求時計秒": row["confirm"], "要求原板行": row["confirm_line"],
                      "確認遅延秒": row["confirm"]-row["end"], "期限時計秒": deadline,
                      "足終了時計秒": row["end"], "残り分_判断時": (deadline-row["confirm"])/60,
                      "入口中心まで方向距離pt": side*(row["bb_mean"]-row["close"]) if BASE.CORE.defined(row.get("bb_mean")) else None,
                      "250ptのATR倍": 250/row["atr"]}
            output[source_id].append(signal)
            fired.append(source_id)
        log("入口判定", row, reference, 方式=family, 待機本数=age, 共通除外理由=reasons, 追加確認別除外理由=by_extra,
            方向一致=bool(row["上位方向"] == side), 発動入口ID=fired, 判断ATR14=row["atr"], 判断RSI14=row["rsi"],
            上位準備済=row["上位準備済"], 上位方向=row["上位方向"], 上位確認秒=row["上位確認秒"],
            上位確認行=row["上位確認行"], 上位足終了秒=row["上位足終了秒"], 確認遅延秒=row["confirm"]-row["end"])
        return fired

    for frame in frames:
        key = frame["confirm"], frame["confirm_line"]
        if previous_key is not None and key < previous_key:
            raise ValueError("足の公開キーが後退")
        if previous_index is not None and frame["index"] <= previous_index:
            raise ValueError("足番号が重複または後退")
        gap = previous_index is not None and frame["index"] != previous_index+1
        previous_key, previous_index = key, frame["index"]
        if not frame["publish"] or frame["missing"] or gap:
            log("状態リセット", frame, active, 非公開=not frame["publish"], 欠枠=bool(frame["missing"]), 番号飛越=bool(gap))
            active = None
        if not frame["publish"]:
            continue
        if frame["confirm"] < frame["end"]:
            raise ValueError("足終了前の公開")
        while pointer < len(higher) and (higher[pointer]["confirm"], higher[pointer]["confirm_line"]) <= key and higher[pointer]["end"] <= frame["end"]:
            upper = higher[pointer]
            pointer += 1
        ready, direction = BASE.CORE.upper_state(upper)
        row = {**frame, "上位準備済": ready, "上位方向": direction,
               "上位確認秒": upper["confirm"] if upper is not None else None,
               "上位確認行": upper["confirm_line"] if upper is not None else None,
               "上位足終了秒": upper["end"] if upper is not None else None,
               "上位足番号": upper["index"] if upper is not None else None}
        counter["公開足"] += 1
        if active is not None:
            age = row["index"]-active["準備足番号"]
            if age <= 0:
                raise ValueError("準備足自身での失効判定")
            if age > 6:
                log("監視満了", row, active, 待機本数=age)
                active = None
            else:
                invalid = active["元準備side"]*(row["close"]-active["第2極値価格"]) < 0
                log("監視判定", row, active, 待機本数=age, 厳密失効=bool(invalid),
                    判断ATR14=row["atr"], 判断RSI14=row["rsi"], 上位準備済=ready, 上位方向=direction,
                    上位確認秒=row["上位確認秒"], 上位確認行=row["上位確認行"], 上位足終了秒=row["上位足終了秒"])
                if invalid:
                    consumed = active
                    active = None
                    fired = emit("価格失効待ち", row, consumed, age)
                    log("失効消費", row, consumed, 待機本数=age, 発動入口ID=fired)
        source = source_by_index.get(row["index"])
        if source is None:
            continue
        if (source["要求時計秒"], source["要求原板行"]) != key or source["時間足分"] != size:
            raise ValueError("準備信号と実際の公開足のキーが不一致")
        reference = preparation(source)
        excluded = source["確認遅延秒"] > 30
        preparation_records.append(deepcopy({"場": session, "時間足分": size, **reference,
                                    "共通遅延除外": excluded, "元信号": source}))
        counter["元準備信号数"] += 1
        if excluded:
            counter["準備遅延共通除外数"] += 1
            log("準備遅延除外", row, reference)
            continue
        counter["利用可能準備信号数"] += 1
        emit("単純逆向き", row, reference, 0)
        log("監視置換" if active is not None else "監視登録", row, reference, 旧準備参照=active)
        active = reference
    if active is not None:
        log("場末未消費終了", frames[-1], active, 待機本数=frames[-1]["index"]-active["準備足番号"])
    return output, {"場": session, "時間足分": size, **dict(counter), "発動除外理由_補助別重複あり": dict(rejected),
                    "系統別発動数": {key: len(rows) for key, rows in output.items()},
                    "元15品質": {k: v for k, v in original_quality.items() if isinstance(v, (int, float)) and k != "時間足分"},
                    "全準備記録": preparation_records, "全監視記録": watch_records}
