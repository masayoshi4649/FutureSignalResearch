"""00011の代表6出口を独立正常板・半開足・EMA/ATR/SMAから検算する。"""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00011_順行と反転のチャート構造と利益回収"
SOURCE = ROOT / "study/00008_外部研究を共通尺度へ移して探索"
WORK = ROOT / "work/テクニカル循環/00011"
DETAIL = WORK / "全運用詳細.jsonl.gz"
HELPER = ROOT / "scripts/利益回収/出口独立確認.py"


def independent_helper() -> Any:
    """旧独立監査の汎用足・指標補助だけを読み込む。

    引数: なし。
    返り値: Any は独立正常板/足/平均の補助。運用・検証・入口処理は読み込まない。
    """
    spec = importlib.util.spec_from_file_location("循環出口の独立足補助", HELPER)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


B = independent_helper()


def choose(trades: list[dict]) -> list[dict]:
    """利益額を順位に使わず6種類の実発動を時刻順に選ぶ。

    引数: trades (list[dict]) は全24候補の完結取引。
    返り値: list[dict] は2ATR買売・反転床買売・中心超過・EMAの6例。
    """
    plans = (("順行2ATR買い", "2ATR追尾保護", "買い"),
             ("順行2ATR売り", "2ATR追尾保護", "売り"),
             ("反転ATR床買い", "反転ATR利益床", "買い"),
             ("反転ATR床売り", "反転ATR利益床", "売り"),
             ("中心超過新規", "中心線超過新規", None),
             ("順行確定EMA", "確定足EMA20失効", None))
    selected = []
    for title, reason, side in plans:
        eligible = [t for t in trades if t["返済理由"] == reason and (side is None or t["方向"] == side)]
        if not eligible:
            raise ValueError("予定した発動がない: " + title)
        first = min(eligible, key=lambda t: (t["返済要求時計秒"], t["返済要求原板行"], t["手法"], t["建玉ID"]))
        selected.append({"選択理由": title, **first})
    return selected


# ----------------------------------------
# 元運用を呼ばず、観測気配→同原行の足の順で最初の返済要求を求める。

def direct(trade: dict, quotes: list[dict], frames: list[dict], entry: dict) -> dict:
    """実新規からの最高返済BBOと通常足を順走査する。

    引数: trade (dict) は保存取引、quotes (list[dict]) は正常板、
    frames (list[dict]) は独立同尺度足、entry (dict) は独立入口判断足。
    返り値: dict は初要求・実峰・保護線・+1秒後の最初約定。
    """
    side, price = (1 if trade["方向"] == "買い" else -1), trade["新規価格"]
    role, variant, atr, center = trade["入口役割"], trade["出口ID"], entry["atr"], entry["mean"]
    _, finish, force = B.bounds(trade["場"])
    crossed = role == "反転" and side * (price - center) >= 0
    timeline = [(q["now"], q["line"], 0, q) for q in quotes if q["line"] >= trade["新規原板行"]]
    timeline += [(f["confirm"], f["line"], 1, f) for f in frames
                 if f["publish"] and f["confirm"] < finish and (f["confirm"], f["line"]) >= (trade["新規時計秒"], trade["新規原板行"])]
    timeline.append((force, 0, -1, {}))
    timeline.sort(key=lambda row: row[:3])
    peak, initial_peak, trailing, armed = None, None, price - side * 125, False
    updates, armed_at = [], None
    reason, request, trigger = None, None, None
    for now, line, kind, value in timeline:
        if kind == -1:
            reason = "期限"
        elif kind == 0:
            mark = value["bid"] if side == 1 else value["ask"]
            distance = side * (mark - price)
            if peak is None:
                peak = initial_peak = distance
            else:
                peak = max(peak, distance)
            if distance <= -125:
                reason = "保護"
            elif variant == "X0" and distance >= 250:
                reason = "利確"
            elif variant != "X0" and role == "反転" and (crossed or side * (mark - center) >= 0):
                reason = "中心線超過新規" if crossed else "入口時中心線目標"
            elif variant == "X2" and role == "順行":
                raw = price + side * (peak - 2 * atr)
                ticked = math.floor(raw / 5) * 5 if side == 1 else math.ceil(raw / 5) * 5
                new = max(trailing, ticked) if side == 1 else min(trailing, ticked)
                if new != trailing:
                    updates.append({"時計": now, "原行": line, "実峰pt": peak, "旧線": trailing, "新線": new})
                trailing = new
                if side * (mark - trailing) <= 0:
                    reason = "2ATR追尾保護"
            elif variant == "X2" and role == "反転":
                if max(0, peak) >= atr and not armed:
                    armed, armed_at = True, (now, line)
                if armed:
                    raw = price + side * .5 * atr
                    trailing = math.floor(raw / 5) * 5 if side == 1 else math.ceil(raw / 5) * 5
                    if side * (mark - trailing) <= 0:
                        reason = "反転ATR利益床"
        elif variant != "X0" and role == "順行" and value["end"] > trade["新規時計秒"] and value["confirm"] - value["end"] <= 30:
            if value["ema"] is not None and side * (value["close"] - value["ema"]) <= 0:
                reason = "確定足EMA20失効"
        if reason:
            request = now, line
            trigger = ({"種類": "正常板", "Bid": value["bid"], "Ask": value["ask"],
                        "返済差pt": distance, "実峰pt": peak}
                       if kind == 0 else
                       {"種類": "確定足", "終了時計": value["end"], "公開時計": value["confirm"],
                        "公開原行": value["line"], "終値": value["close"], "EMA20": value["ema"]}
                       if kind == 1 else {"種類": "期限予約"})
            break
    if request is None:
        raise ValueError("独立要求が存在しない")
    fill = next(q for q in quotes if q["now"] >= request[0] + 1)
    return {"要求理由": reason, "要求時計": request[0], "要求原行": request[1],
            "約定時計": fill["now"], "約定原行": fill["line"], "約定価格": fill["bid"] if side == 1 else fill["ask"],
            "入口ATR": atr, "入口中心": center, "中心超過新規": crossed,
            "最初の実返済差pt": initial_peak, "要求までの実峰pt": peak, "要求時保護線": trailing,
            "保護線更新": updates, "利益床起動時計原行": armed_at, "発動観測": trigger,
            "同時計状態変化数": sum(a["now"] == b["now"] for a, b in zip(quotes[:-1], quotes[1:])
                                   if trade["新規原板行"] <= a["line"] <= trade["返済原板行"])}


def run() -> dict:
    """完了した24候補から6例を選び、独立発動と約定を照合する。

    引数: なし。保存結果・固定台帳・小型cacheだけを読む。
    返り値: dict は明示合否・件数・6例・指紋・限界。
    """
    if not (STUDY / "結果.json").is_file():
        raise ValueError("全量実行の完了前には確認しない")
    trades, digest = [], hashlib.sha256()
    with gzip.open(DETAIL, "rb") as stream:
        for raw in stream:
            digest.update(raw)
            trades.extend(json.loads(raw)["取引"])
    expanded_sha = digest.hexdigest()
    artifacts = json.loads((STUDY / "作業成果物.json").read_text(encoding="utf-8"))["ファイル"]
    expected_sha = next(f["展開内容SHA256"] for f in artifacts if Path(f["パス"]).name == DETAIL.name)
    if expanded_sha != expected_sha:
        raise ValueError("詳細gzipの展開正本SHAが不一致")
    selected = choose(trades)
    manifest = json.loads((SOURCE / "入力台帳.json").read_text(encoding="utf-8"))
    last_session = max(t["場"] for t in selected)
    states, frames_by_key, normal_by_session = {3: B.Averages(), 5: B.Averages()}, {}, {}
    previous_contract, fingerprints = None, []
    for entry in manifest["entries"]:
        if entry["session"] > last_session:
            break
        contract = entry["in_session_contract_codes"]
        if previous_contract is not None and contract != previous_contract:
            states = {3: B.Averages(), 5: B.Averages()}
        previous_contract = contract
        raw, normal = B.load(entry)
        normal_by_session[entry["session"]] = normal
        for size in (3, 5):
            frames_by_key[(entry["session"], size)] = B.bars(raw, entry["session"], size, states[size])
        fingerprints.append({"場": entry["session"], "cacheSHA256": entry["sha256_cache"]})
    count, errors, examples = 1, [], []
    for trade in selected:
        size = int(trade["手法"].split("分_", 1)[0])
        frames = frames_by_key[(trade["場"], size)]
        entry_frame = next(f for f in frames if (f["confirm"], f["line"]) == (trade["新規要求時計秒"], trade["新規要求原板行"]))
        actual = direct(trade, normal_by_session[trade["場"]], frames, entry_frame)
        comparisons = {"要求理由": trade["返済理由"], "要求時計": trade["返済要求時計秒"], "要求原行": trade["返済要求原板行"],
                       "約定時計": trade["返済時計秒"], "約定原行": trade["返済原板行"], "約定価格": trade["返済価格"],
                       "入口ATR": trade["入口ATR"], "入口中心": trade["入口中心線目標"], "中心超過新規": trade["中心線超過新規"]}
        for key, expected in comparisons.items():
            count += 1
            equal = abs(actual[key] - expected) <= 1e-7 if isinstance(expected, (int, float)) and actual[key] is not None else actual[key] == expected
            if not equal:
                errors.append({"候補": trade["手法"], "場": trade["場"], "項目": key, "独立": actual[key], "保存": expected})
        for key, actual_value, expected in (("固定利確使用", trade["固定利確使用"], False),
                                             ("利確価格は欠測", trade["利確価格"], None),
                                             ("実負峰から開始", actual["最初の実返済差pt"] <= 0, True)):
            count += 1
            if actual_value != expected:
                errors.append({"候補": trade["手法"], "項目": key, "独立": actual_value, "保存": expected})
        for update in actual["保護線更新"]:
            count += 1
            if (1 if trade["方向"] == "買い" else -1) * (update["新線"] - update["旧線"]) < 0:
                errors.append({"項目": "保護線後退", "更新": update})
        examples.append({"選択理由": trade["選択理由"], "候補ID": trade["手法"], "場": trade["場"], "方向": trade["方向"],
                         "建玉ID": trade["建玉ID"], "入口価格": trade["新規価格"], "入口原行": trade["新規原板行"],
                         "独立診断": actual, "観測経路注意": trade["観測経路注意"], "返済待機秒": trade["要求から返済秒"]})
    result = {"全件一致": not errors, "照合項目数": count, "不一致数": len(errors), "不一致": errors,
              "コードSHA256": B.sha(Path(__file__)), "独立足補助SHA256": B.sha(HELPER),
              "対象運用SHA256": B.sha(ROOT / "scripts/テクニカル循環/運用.py"),
              "詳細展開内容SHA256": expanded_sha, "詳細圧縮SHA256参考": B.sha(DETAIL),
              "入力台帳SHA256": B.sha(SOURCE / "入力台帳.json"), "入力cache": fingerprints,
              "選択規則": "順行2ATR買売、反転ATR床買売、中心超過新規、順行EMAの各要求時計/原行/候補ID/建玉ID順の最初。利益額や最終期間で選ばない。",
              "実例": examples,
              "方法": "運用・検証・入口をimportせず、既存独立監査の汎用正常板/半開足/算術種EMA20・ATR14・SMA20を再利用。実新規原行からquote→bar順で最初の要求、+1秒後最初正常BBOを照合。",
              "限界": "6実例の局所検算であり、全24候補の全発動を独立に全面再実装したものではない。新入口の旧007保存同値を主張しない。全65場は既使用。"}
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "出口独立確認.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"全件一致": not errors, "照合項目数": count, "不一致数": len(errors), "不一致": errors}, ensure_ascii=False))
    return result


if __name__ == "__main__":
    if not run()["全件一致"]:
        raise SystemExit(1)
