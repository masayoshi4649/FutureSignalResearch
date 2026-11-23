"""5分_R2_X0の学習注意2場について、観測純額と正常板空白の位置を診断する。"""

from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00011_順行と反転のチャート構造と利益回収"
WORK = ROOT / "work/テクニカル循環/00011"
DETAIL = WORK / "全運用詳細.jsonl.gz"
SOURCE = ROOT / "study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
HELPER = ROOT / "scripts/利益回収/出口独立確認.py"
METHOD = "5分_R2_X0"
JST = timezone(timedelta(hours=9))


def helper() -> Any:
    """独立正常板抽出の補助だけを読む。

    引数: なし。
    返り値: Any は汎用抽出。運用・入口・検証の数値処理は呼ばない。
    """
    spec = importlib.util.spec_from_file_location("注意経路の独立正常板", HELPER)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


B = helper()


class Audit:
    """照合件数と不一致を保持する。"""

    def __init__(self) -> None:
        """空の照合を作る。

        引数: なし。
        返り値: None。
        """
        self.count, self.errors = 0, []

    def check(self, name: str, actual: Any, expected: Any) -> None:
        """独立数値と保存値を比較する。

        引数: name (str) は項目、actual/expected (Any) は値。
        返り値: None。不一致を記録する。
        """
        self.count += 1
        equal = abs(float(actual) - float(expected)) <= 1e-8 if isinstance(actual, (int, float)) and isinstance(expected, (int, float)) else actual == expected
        if not equal:
            self.errors.append({"項目": name, "独立": actual, "保存": expected})


def point(row: dict | None, trade: dict) -> dict | None:
    """元cacheの正常気配を少数点の診断表記へ変換する。

    引数: row (dict|None) は正常板、trade (dict) は対象取引。
    返り値: dict|None は時計・原行・BBO・返済差と費用込み参考額。
    """
    if row is None:
        return None
    side = 1 if trade["方向"] == "買い" else -1
    mark = row["bid"] if side == 1 else row["ask"]
    distance = side * (mark - trade["新規価格"])
    return {"価格時計秒": row["now"], "価格時計JST": datetime.fromtimestamp(row["now"], JST).isoformat(),
            "原板行": row["line"], "Bid": row["bid"], "Ask": row["ask"], "返済側BBO": mark,
            "新規比返済差pt": distance, "仮想往復費用込み円": distance * 10 - 22}


# ----------------------------------------
# 空白の前後を直接取り出し、入口待機・保有・返済待機を区別する。

def session_diagnosis(detail: dict, entry: dict, audit: Audit) -> dict:
    """注意場の取引と全300秒超空白を原順で確認する。

    引数: detail (dict) は対象場の正本、entry (dict) は固定入力、audit (Audit) は照合先。
    返り値: dict は取引・空白の位置・少数BBO点。原板本文は読まない。
    """
    _, quotes = B.load(entry)
    session, info = detail["場"], detail["品質"]
    begin, _, _ = B.bounds(session)
    gaps, previous = [], {"now": begin, "line": 0, "bid": None, "ask": None}
    for index, row in enumerate(quotes):
        if row["now"] - previous["now"] > 300:
            gaps.append({"left": previous if previous["line"] else None, "right": row,
                         "left_clock": previous["now"], "seconds": row["now"] - previous["now"], "right_index": index})
        previous = row
    audit.check(session + ":場内空白数", len(gaps), info["場内正常板空白区間数"])
    audit.check(session + ":全体確定額None", info["確定対象純損益円"], None)
    flagged = [t for t in detail["取引"] if t["観測経路注意"]]
    audit.check(session + ":注意取引数", len(flagged), info["観測経路注意取引数"])
    diagnosed = []
    for trade in flagged:
        side, price = (1 if trade["方向"] == "買い" else -1), trade["新規価格"]
        held = [q for q in quotes if trade["新規原板行"] <= q["line"] <= trade["返済原板行"]]
        distances = [side * ((q["bid"] if side == 1 else q["ask"]) - price) for q in held]
        mfe, mae = max(0, max(distances)), max(0, -min(distances))
        audit.check(session + ":MFE", mfe, trade["観測最大順行pt"])
        audit.check(session + ":MAE", mae, trade["観測最大逆行pt"])
        entry_quote = next(q for q in quotes if q["line"] == trade["新規原板行"])
        exit_quote = next(q for q in quotes if q["line"] == trade["返済原板行"])
        expected_entry = entry_quote["ask"] if side == 1 else entry_quote["bid"]
        expected_exit = exit_quote["bid"] if side == 1 else exit_quote["ask"]
        audit.check(session + ":新規BBO", price, expected_entry)
        audit.check(session + ":返済BBO", trade["返済価格"], expected_exit)
        first_return = next(q for q in quotes if q["now"] >= trade["返済要求時計秒"] + 1)
        audit.check(session + ":1秒後最初返済原行", first_return["line"], trade["返済原板行"])
        audit.check(session + ":1秒後最初返済時計", first_return["now"], trade["返済時計秒"])
        gross = side * (Decimal(str(expected_exit)) - Decimal(str(expected_entry))) * 10
        net = gross - 22
        audit.check(session + ":粗額", float(gross), trade["粗損益円"])
        audit.check(session + ":純額", float(net), trade["基準純損益円"])
        for slip in (0, 5, 10):
            audit.check(session + f":追加{slip}pt", float(net) - 20 * slip, trade[f"追加滑り{slip}pt純損益円"])
        audit.check(session + ":観測されたTP_SLなし", all(-125 < d < 250 for d in distances), True)
        request = trade["返済要求時計秒"]
        request_reference = next((q for q in reversed(quotes) if q["now"] < request), None) if trade["返済要求原板行"] == 0 else next(q for q in quotes if q["line"] == trade["返済要求原板行"])
        if trade["返済要求原板行"] == 0:
            audit.check(session + ":期限直前板strict", request_reference["now"] < request, True)
        related = []
        for gap in gaps:
            left, right = gap["left_clock"], gap["right"]["now"]
            entry_wait = trade["新規要求時計秒"] < right and trade["新規時計秒"] > left
            held_gap = trade["新規時計秒"] < right <= trade["返済時計秒"]
            exit_wait = trade["返済要求時計秒"] < right and trade["返済時計秒"] > left
            if not (entry_wait or held_gap or exit_wait):
                continue
            related.append({"空白秒": gap["seconds"], "区分": {"入口待機": entry_wait, "保有": held_gap, "返済待機": exit_wait},
                            "直前正常板": point(gap["left"], trade), "直後正常板": point(gap["right"], trade),
                            "返済要求との位置": "要求前" if right <= request else "要求時点をまたぐ" if left < request < right else "要求以後"})
        audit.check(session + ":注意の保有空白", any(r["区分"]["保有"] for r in related), trade["保有経路空白"])
        audit.check(session + ":注意の新規待機空白", any(r["区分"]["入口待機"] for r in related), trade["新規待機空白"])
        diagnosed.append({"建玉ID": trade["建玉ID"], "方向": trade["方向"], "入口イベントID": trade["入口イベントID"],
                          "新規時計JST": trade["新規時計JST"], "返済時計JST": trade["返済時計JST"], "返済理由": trade["返済理由"],
                          "粗額円": float(gross), "往復手数料円": trade["手数料円"], "基準純額円": float(net),
                          "追加5pt後純額円": float(net) - 100, "追加10pt後純額円": float(net) - 200,
                          "MFEpt": mfe, "MAEpt": mae, "TPpt": 250, "SLpt": -125,
                          "返済待機秒": trade["返済時計秒"] - request, "要求原板行": trade["返済要求原板行"],
                          "新規正常板": point(entry_quote, trade), "期限要求直前参照板": point(request_reference, trade),
                          "返済正常板": point(exit_quote, trade), "空白": related,
                          "観測経路注意": True, "確定対象純額円": None,
                          "注記": "閾値は正常な観測点では未到達。空白内の到達・指値や逆指値の執行可能性は分からない。期限要求の原行0は予約であり、strict直前板は参考。"})
    return {"場": session, "場の観測純額円": info["観測現金増減円"], "場の完結取引数": len(detail["取引"]),
            "場内300秒超空白数": len(gaps), "注意取引": diagnosed,
            "cacheSHA256": entry["sha256_cache"], "全体確定対象純額円": None}


def run() -> dict:
    """学習注意2場の損益寄与と4空白の正常BBOを確認する。

    引数: なし。完成した00011詳細と既存cacheだけを使う。
    返り値: dict は明示合否・件数・事後参考・注意経路の証跡。
    """
    if not (STUDY / "結果.json").is_file():
        raise ValueError("完成結果を確認できない")
    digest, groups = hashlib.sha256(), []
    with gzip.open(DETAIL, "rb") as stream:
        for raw in stream:
            digest.update(raw)
            value = json.loads(raw)
            if value["候補ID"] == METHOD and value["品質"]["期間"] == "学習":
                groups.append(value)
    fixed_artifacts = json.loads((STUDY / "作業成果物.json").read_text(encoding="utf-8"))["ファイル"]
    expected = next(f["展開内容SHA256"] for f in fixed_artifacts if Path(f["パス"]).name == DETAIL.name)
    if digest.hexdigest() != expected:
        raise ValueError("詳細の展開SHAが不一致")
    audit = Audit()
    attention = [d for d in groups if d["品質"]["観測経路注意"]]
    clean = [d for d in groups if not d["品質"]["観測経路注意"]]
    audit.check("学習場数", len(groups), 40)
    audit.check("注意場数", len(attention), 2)
    entries = {e["session"]: e for e in json.loads(SOURCE.read_text(encoding="utf-8"))["entries"]}
    diagnosed = [session_diagnosis(d, entries[d["場"]], audit) for d in attention]
    trades = [t for d in groups for t in d["取引"]]
    flagged = [t for t in trades if t["観測経路注意"]]
    total = sum(Decimal(str(d["品質"]["観測現金増減円"])) for d in groups)
    attention_net = sum(Decimal(str(d["品質"]["観測現金増減円"])) for d in attention)
    clean_net = sum(Decimal(str(d["品質"]["観測現金増減円"])) for d in clean)
    audit.check("全体と注意除外の接合", float(total), float(attention_net + clean_net))
    audit.check("注意取引と注意場の額", sum(t["基準純損益円"] for t in flagged), float(attention_net))
    audit.check("未解消場数", sum(d["品質"]["終了建玉"] for d in groups), 0)
    comparison = []
    for slip in (0, 5, 10):
        comparison.append({"片道追加滑りpt": slip, "全学習観測純額円": float(total) - 20 * slip * len(trades),
                           "注意2場観測純額円": float(attention_net) - 20 * slip * len(flagged),
                           "事後注意除外38場参考円": float(clean_net) - 20 * slip * (len(trades) - len(flagged)),
                           "全体確定対象純額円": None})
    output = {"全件一致": not audit.errors, "照合項目数": audit.count, "不一致数": len(audit.errors), "不一致": audit.errors,
              "対象": {"候補ID": METHOD, "期間": "学習", "場数": len(groups), "完結取引数": len(trades),
                       "注意場数": len(attention), "注意取引数": len(flagged), "全体確定対象純額円": None},
              "期間別純額": comparison,
              "寄与": {"全学習観測純額円": float(total), "注意2場観測純額円": float(attention_net),
                       "注意赤字取引純額円": sum(t["基準純損益円"] for t in flagged if t["基準純損益円"] < 0),
                       "注意黒字取引純額円": sum(t["基準純損益円"] for t in flagged if t["基準純損益円"] > 0),
                       "注意純額の全観測額比": float(attention_net / total) if total else None,
                       "事後注意除外38場参考円": float(clean_net), "事後除外を採用した成績ではない": True},
              "注意2場": diagnosed, "コードSHA256": B.sha(Path(__file__)), "独立正常板補助SHA256": B.sha(HELPER),
              "入力台帳SHA256": B.sha(SOURCE), "詳細展開内容SHA256": digest.hexdigest(),
              "時計の意味": "価格時計はCurrentPriceTime。空白秒・返済待機秒はその時計の差で、実受信空白や実注文応答の遅延を測ったものではない。",
              "結論": "注意2場の観測純額寄与は+56円で、観測9706円の大部分が注意2取引の純額に由来する形ではない。ただし空白内SL/TPの到達と執行、その後の一建玉の抑止/再参加経路は未知。全体確定額Noneを維持する。",
              "限界": "注意2場だけの事後診断。正常板空白はCurrentPriceTimeでの観測間隔であり、実受信断や取引所の無約定を断定しない。空白を補間せず、別条件へ選び直さない。"}
    target = WORK / "注意経路診断.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"全件一致": not audit.errors, "照合項目数": audit.count, "不一致数": len(audit.errors),
                      "不一致": audit.errors, "寄与": output["寄与"]}, ensure_ascii=False))
    return output


if __name__ == "__main__":
    if not run()["全件一致"]:
        raise SystemExit(1)
