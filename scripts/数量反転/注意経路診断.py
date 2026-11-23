"""00014全12候補の注意場と注意取引の寄与を分け、指定3場の正常BBOを直接診断する。"""

from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00014_反転入口と観測差分量"
WORK = ROOT / "work/数量反転/00014"
SOURCE = ROOT / "study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
HELPER = ROOT / "scripts/利益回収/出口独立確認.py"
FOCUS = "3分_R2_RVOL1.2以上_X0"
PERIODS = ("学習", "条件選択", "後続検査")
JST = timezone(timedelta(hours=9))


def read(path: Path) -> Any:
    """日本語JSONを読む。

    引数: path (Path) は資料。
    返り値: Any はJSONの値。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path: Path) -> str:
    """原板以外の資料とcacheを指紋化する。

    引数: path (Path) は対象。
    返り値: str はSHA256。
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def helper() -> Any:
    """過去の独立した正常BBO抽出補助だけを読み込む。

    引数: なし。
    返り値: Any は固定cacheの読取補助。戦略・運用・入口の再生は呼ばない。
    """
    spec = importlib.util.spec_from_file_location("数量反転注意経路の独立読取", HELPER)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


B = helper()


class Audit:
    """局所原気配と集計の照合を保持する。"""

    def __init__(self) -> None:
        """空の記録を作る。

        引数: なし。
        返り値: None。
        """
        self.count, self.errors = 0, []

    def check(self, name: str, actual: Any, expected: Any) -> None:
        """数値または非数値を比較する。

        引数: name (str) は項目、actual/expected (Any) は保存値と独立値。
        返り値: None。不一致は先頭100件まで記録する。
        """
        self.count += 1
        same = math.isclose(float(actual), float(expected), rel_tol=0, abs_tol=1e-7) if (
            isinstance(actual, (int, float)) and isinstance(expected, (int, float))) else actual == expected
        if not same and len(self.errors) < 100:
            self.errors.append({"項目": name, "保存": actual, "独立": expected})


def total(rows: list[dict], key: str) -> Decimal:
    """金額の合計をDecimalで求める。

    引数: rows (list[dict]) は行、key (str) は数値列。
    返り値: Decimal は合計。空列は0。
    """
    return sum((Decimal(str(row[key])) for row in rows), Decimal(0))


def iso(now: float) -> str:
    """価格時計を日本時間表記へ変換する。

    引数: now (float) はUnix秒。
    返り値: str は時差付き表記。受信時計という意味を付けない。
    """
    return datetime.fromtimestamp(now, JST).isoformat()


def attention_reasons(info: dict) -> list[str]:
    """保存品質の注意理由を取引・待機・末尾へ分ける。

    引数: info (dict) は保存場別品質。
    返り値: list[str] は成立した理由。場内空白だけでは注意場と断定しない。
    """
    tests = (("注意完結取引", info["観測経路注意取引数"] > 0),
             ("保有中正常板空白", info["保有中空白区間数"] > 0),
             ("新規待機区間と正常板空白の重複", info["新規待機中空白区間数"] > 0),
             ("期限までの正常板観測不足", info["EOF期限未達"]),
             ("未解消建玉", info["終了建玉"] > 0))
    return [name for name, active in tests if active]


# ----------------------------------------
# 注意場の全取引と、取引自身が空白に触れた部分の金額を混同しない。

def summarize(method: str, period: str, details: list[dict], reported: dict, audit: Audit) -> dict:
    """一候補一期間を全体・注意場・注意取引・その他の金額へ分解する。

    引数: method/period (str) は候補と期間、details (list[dict]) は全場詳細、
    reported (dict) は変更しない正式運用集計、audit (Audit) は照合先。
    返り値: dict は金額寄与と事後参考。除外後の別戦略成績を作らない。
    """
    infos = [d["品質"] for d in details]
    trades = [t for d in details for t in d["取引"]]
    attention = [d for d in details if d["品質"]["観測経路注意"]]
    clean = [d for d in details if not d["品質"]["観測経路注意"]]
    flagged = [t for t in trades if t["観測経路注意"]]
    attention_clean = [t for d in attention for t in d["取引"] if not t["観測経路注意"]]
    clean_trades = [t for d in clean for t in d["取引"]]
    cash = total(infos, "観測現金増減円")
    trade_net = total(trades, "基準純損益円")
    attention_cash = total([d["品質"] for d in attention], "観測現金増減円")
    clean_cash = total([d["品質"] for d in clean], "観測現金増減円")
    flagged_net = total(flagged, "基準純損益円")
    other_in_attention = total(attention_clean, "基準純損益円")
    clean_trade_net = total(clean_trades, "基準純損益円")
    residual = cash - trade_net
    name = method + ":" + period
    audit.check(name + ":入力場数", reported["入力場数"], len(details))
    audit.check(name + ":完結数", reported["完結取引数"], len(trades))
    audit.check(name + ":注意場数", reported["品質注意場数"], len(attention))
    audit.check(name + ":未解消数", reported["未解消場数"], sum(i["終了建玉"] for i in infos))
    audit.check(name + ":場の金額分解", float(cash), float(attention_cash + clean_cash))
    audit.check(name + ":取引の金額分解", float(trade_net), float(flagged_net + other_in_attention + clean_trade_net))
    for d in details:
        info = d["品質"]
        flagged_local = [t for t in d["取引"] if t["観測経路注意"]]
        audit.check(name + ":" + d["場"] + ":場の注意フラグ", info["観測経路注意"], bool(attention_reasons(info)))
        audit.check(name + ":" + d["場"] + ":注意取引数", info["観測経路注意取引数"], len(flagged_local))
        audit.check(name + ":" + d["場"] + ":注意取引純額", info["経路注意取引純損益円"], float(total(flagged_local, "基準純損益円")))
        audit.check(name + ":" + d["場"] + ":確定額維持", info["確定対象純損益円"], None if info["観測経路注意"] else info["観測現金増減円"])
    sensitivity = []
    for slip in (0, 5, 10):
        key = f"追加滑り{slip}pt純損益円"
        all_amount, flagged_amount = total(trades, key), total(flagged, key)
        attention_amount = total([t for d in attention for t in d["取引"]], key)
        clean_amount = total(clean_trades, key)
        audit.check(name + f":追加{slip}pt全体額", reported[f"追加{slip}pt純損益円"], float(all_amount))
        audit.check(name + f":追加{slip}pt全体確定額", reported[f"追加{slip}pt確定対象円"], None if attention else float(all_amount))
        sensitivity.append({"片道追加滑りpt": slip, "全体観測完結取引純額円": float(all_amount),
            "注意場内の全完結取引純額円": float(attention_amount), "注意取引の観測純額円": float(flagged_amount),
            "注意場内の注意なし完結取引純額円": float(attention_amount - flagged_amount),
            "事後_注意場除外の完結取引参考円": float(clean_amount),
            "事後_注意取引だけ除外の完結取引参考円": float(all_amount - flagged_amount),
            "全体確定対象純額円": None if attention else float(all_amount)})
    reasons = Counter(reason for d in attention for reason in attention_reasons(d["品質"]))
    return {"候補ID": method, "期間": period, "場数": len(details), "完結取引数": len(trades),
        "注意場数": len(attention), "注意取引数": len(flagged), "注意場内の注意なし取引数": len(attention_clean),
        "全体観測現金増減円": float(cash), "全体観測完結取引純額円": float(trade_net),
        "注意場の観測現金増減円": float(attention_cash), "注意取引の観測純額円": float(flagged_net),
        "注意場内の注意なし完結取引純額円": float(other_in_attention),
        "注意なし場の完結取引純額円": float(clean_trade_net),
        "現金と完結取引の差円": float(residual),
        "事後_注意場除外参考円": float(clean_cash),
        "事後_注意取引だけ除外の完結取引参考円": float(trade_net - flagged_net),
        "注意場純額の全観測額比": float(attention_cash / cash) if cash else None,
        "注意取引純額の全観測額比": float(flagged_net / cash) if cash else None,
        "注意取引黒字額円": float(sum((max(Decimal(0), Decimal(str(t["基準純損益円"]))) for t in flagged), Decimal(0))),
        "注意取引赤字額円": float(sum((min(Decimal(0), Decimal(str(t["基準純損益円"]))) for t in flagged), Decimal(0))),
        "全体確定対象純額円": None if attention else float(trade_net),
        "未解消場数": sum(i["終了建玉"] for i in infos), "注意理由別場数_重複あり": dict(reasons),
        "費用感度": sensitivity,
        "注意場": [{"場": d["場"], "観測現金増減円": d["品質"]["観測現金増減円"],
                   "完結取引数": len(d["取引"]), "注意取引数": d["品質"]["観測経路注意取引数"],
                   "注意取引純額円": d["品質"]["経路注意取引純損益円"], "理由": attention_reasons(d["品質"])} for d in attention]}


def point(row: dict | None, trade: dict | None = None) -> dict | None:
    """正常BBO点を原行・価格時計と取引からの距離で表現する。

    引数: row (dict|None) は正常板、trade (dict|None) は任意の対象取引。
    返り値: dict|None は少数点の記録。空白内の価格は補わない。
    """
    if row is None:
        return None
    result = {"価格時計秒": row["now"], "価格時計JST": iso(row["now"]), "原板行": row["line"],
              "Bid": row["bid"], "Ask": row["ask"]}
    if trade is not None:
        side = 1 if trade["方向"] == "買い" else -1
        mark = row["bid"] if side == 1 else row["ask"]
        distance = side * (mark - trade["新規価格"])
        result.update(返済側BBO=mark, 新規比返済差pt=distance, 仮想往復手数料込み円=distance * 10 - 22)
    return result


# ----------------------------------------
# 指定候補の注意3場だけcacheを直接読み、空白と要求・保有の因果位置を確認する。

def local_trade(trade: dict, quotes: list[dict], gaps: list[dict], force: float, audit: Audit) -> dict:
    """注意取引の原BBO・最初の返済要求・待機と全関連空白を独立照合する。

    引数: trade (dict) は保存取引、quotes/gaps (list[dict]) は正常板/全空白、
    force (float) は期限時計、audit (Audit) は照合先。
    返り値: dict は要求と約定を区別した局所経路。未知の空白内順序は判定しない。
    """
    keys = [(q["now"], q["line"]) for q in quotes]
    times = [q["now"] for q in quotes]
    entry_key, exit_key = (trade["新規時計秒"], trade["新規原板行"]), (trade["返済時計秒"], trade["返済原板行"])
    entry_request = trade["新規要求時計秒"], trade["新規要求原板行"]
    exit_request = trade["返済要求時計秒"], trade["返済要求原板行"]
    begin, after = bisect_left(keys, entry_key), bisect_right(keys, exit_key)
    held = quotes[begin:after]
    name = trade["場"] + ":" + trade["建玉ID"]
    audit.check(name + ":新規正常板原行", keys[begin], entry_key)
    audit.check(name + ":返済正常板原行", keys[after - 1], exit_key)
    side = 1 if trade["方向"] == "買い" else -1
    entry_price = held[0]["ask"] if side == 1 else held[0]["bid"]
    exit_price = held[-1]["bid"] if side == 1 else held[-1]["ask"]
    audit.check(name + ":新規BBO", trade["新規価格"], entry_price)
    audit.check(name + ":返済BBO", trade["返済価格"], exit_price)
    distances = [side * ((q["bid"] if side == 1 else q["ask"]) - entry_price) for q in held]
    mfe, mae = max(0.0, max(distances)), max(0.0, -min(distances))
    audit.check(name + ":MFE", trade["観測最大順行pt"], mfe)
    audit.check(name + ":MAE", trade["観測最大逆行pt"], mae)
    trigger = next(((q, distance) for q, distance in zip(held, distances)
                    if q["now"] < force and (distance <= -125 or distance >= 250)), None)
    expected_request = (trigger[0]["now"], trigger[0]["line"]) if trigger else (force, 0)
    expected_reason = ("保護" if trigger[1] <= -125 else "利確") if trigger else "期限"
    audit.check(name + ":要求時計原行", exit_request, expected_request)
    audit.check(name + ":要求理由", trade["返済理由"], expected_reason)
    first_entry = quotes[bisect_left(times, entry_request[0] + 1)]
    first_exit = quotes[bisect_left(times, exit_request[0] + 1)]
    audit.check(name + ":1秒後最初新規板", (first_entry["now"], first_entry["line"]), entry_key)
    audit.check(name + ":1秒後最初返済板", (first_exit["now"], first_exit["line"]), exit_key)
    gross = Decimal(side) * (Decimal(str(exit_price)) - Decimal(str(entry_price))) * 10
    net = gross - 22
    audit.check(name + ":粗額", trade["粗損益円"], float(gross))
    audit.check(name + ":純額", trade["基準純損益円"], float(net))
    audit.check(name + ":往復fee", trade["手数料円"], 22)
    for slip in (0, 5, 10):
        audit.check(name + f":追加{slip}pt額", trade[f"追加滑り{slip}pt純損益円"], float(net) - 20 * slip)
    request_ref_at = bisect_left(times, force) - 1 if trade["返済要求原板行"] == 0 else bisect_right(keys, exit_request) - 1
    entry_ref_at = bisect_right(keys, entry_request) - 1
    related = []
    for gap in gaps:
        right_key = gap["right"]["now"], gap["right"]["line"]
        in_position = entry_key < right_key <= exit_key
        entry_wait = entry_request < right_key <= entry_key
        exit_wait = exit_request < right_key <= exit_key and entry_key < right_key
        if not (in_position or entry_wait or exit_wait):
            continue
        request_position = "要求前" if right_key <= exit_request else (
            "要求時点をまたぐ" if gap["left_clock"] < exit_request[0] <= gap["right"]["now"] else "要求以後")
        related.append({"空白番号": gap["番号"], "空白秒": gap["seconds"],
            "区分": {"新規待機": entry_wait, "保有": in_position, "返済待機": exit_wait},
            "返済要求との位置": request_position,
            "直前正常BBO": point(gap["left"], trade), "直後正常BBO": point(gap["right"], trade)})
    audit.check(name + ":保有空白フラグ", trade["保有経路空白"], any(g["区分"]["保有"] for g in related))
    audit.check(name + ":新規待機空白フラグ", trade["新規待機空白"], any(g["区分"]["新規待機"] for g in related))
    return {"建玉ID": trade["建玉ID"], "入口イベントID": trade["入口イベントID"], "方向": trade["方向"],
        "新規要求時計秒": entry_request[0], "新規要求時計JST": iso(entry_request[0]), "新規要求原板行": entry_request[1],
        "返済要求時計秒": exit_request[0], "返済要求時計JST": iso(exit_request[0]), "返済要求原板行": exit_request[1],
        "新規要求時の既知最終正常BBO": point(quotes[entry_ref_at], trade) if entry_ref_at >= 0 else None,
        "返済要求時の既知最終正常BBO": point(quotes[request_ref_at], trade) if request_ref_at >= 0 else None,
        "要求を発動した正常BBO": point(trigger[0], trade) if trigger else None,
        "新規約定BBO": point(held[0], trade), "返済約定BBO": point(held[-1], trade),
        "新規要求から約定秒": entry_key[0] - entry_request[0], "返済要求から約定秒": exit_key[0] - exit_request[0],
        "返済理由": trade["返済理由"], "粗額円": float(gross), "往復手数料円": 22,
        "観測純額円": float(net), "追加5pt後観測純額円": float(net) - 100, "追加10pt後観測純額円": float(net) - 200,
        "MFEpt": mfe, "MAEpt": mae, "保護価格": trade["保護価格"], "利確価格": trade["利確価格"],
        "新規待機空白": trade["新規待機空白"], "保有経路空白": trade["保有経路空白"], "関連空白": related,
        "空白内は不明": True, "確定対象純額円": None,
        "注記": "返済要求と約定を分離。期限の原行0は予約であり、参照BBOは期限strict直前。観測点のMFE/MAEは空白内の峰・底を含まない。"}


def local_session(detail: dict, entry: dict, source_root: Path, audit: Audit) -> dict:
    """指定注意場の全空白と保有・待機との関係を直接確認する。

    引数: detail (dict) は一候補一場の正本、entry (dict) は固定入力、
    source_root (Path) は共通入力ルート、audit (Audit) は照合先。
    返り値: dict は全空白と注意取引。注意なし取引も場全額に含まれることを記録する。
    """
    source = source_root / entry["source_path"]
    stat = source.stat()
    if (stat.st_size, stat.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]):
        raise ValueError("原板statが固定後変更")
    _, quotes = B.load(entry)
    session, info = detail["場"], detail["品質"]
    start, finish, force = B.bounds(session)
    gaps, previous = [], None
    for row in quotes:
        left_clock = previous["now"] if previous else start
        if row["now"] - left_clock > 300:
            gaps.append({"番号": len(gaps) + 1, "left": previous, "right": row,
                         "left_clock": left_clock, "seconds": row["now"] - left_clock})
        previous = row
    audit.check(session + ":全正常板空白数", info["場内正常板空白区間数"], len(gaps))
    audit.check(session + ":正常板数", info["正常板数"], len(quotes))
    audit.check(session + ":最後正常板時計", info["正常板最終時計秒"], quotes[-1]["now"] if quotes else None)
    audit.check(session + ":場全体の確定額None", info["確定対象純損益円"], None)
    diagnosed = [local_trade(t, quotes, gaps, force, audit) for t in detail["取引"] if t["観測経路注意"]]
    held_count = sum(g["区分"]["保有"] for t in diagnosed for g in t["関連空白"])
    wait_count = sum(o["要求時計秒"] < g["right"]["now"] and (
        o["約定時計秒"] if o["約定時計秒"] is not None else min(o["要求時計秒"] + 30, force - 600, force)
        ) > g["left_clock"] for g in gaps for o in detail["注文"] if o["区分"] == "新規")
    audit.check(session + ":保有空白数", info["保有中空白区間数"], held_count)
    audit.check(session + ":新規待機重複空白数", info["新規待機中空白区間数"], wait_count)
    audit.check(session + ":注意取引数", info["観測経路注意取引数"], len(diagnosed))
    audit.check(session + ":注意取引額", info["経路注意取引純損益円"], sum(t["観測純額円"] for t in diagnosed))
    return {"場": session, "場全体観測純額円": info["観測現金増減円"], "場の完結取引数": len(detail["取引"]),
        "注意取引数": len(diagnosed), "注意取引観測純額円": sum(t["観測純額円"] for t in diagnosed),
        "注意なし取引観測純額円": float(total([t for t in detail["取引"] if not t["観測経路注意"]], "基準純損益円")),
        "注意理由": attention_reasons(info), "全体確定対象純額円": None,
        "正常板空白数": len(gaps), "正常板空白": [{"空白番号": g["番号"], "空白秒": g["seconds"],
            "直前正常BBO": point(g["left"]), "直後正常BBO": point(g["right"]),
            "保有取引": [t["建玉ID"] for t in diagnosed if any(a["空白番号"] == g["番号"] and a["区分"]["保有"] for a in t["関連空白"])],
            "新規待機取引": [t["建玉ID"] for t in diagnosed if any(a["空白番号"] == g["番号"] and a["区分"]["新規待機"] for a in t["関連空白"])]} for g in gaps],
        "注意取引の局所経路": diagnosed,
        "場の全取引の参考一覧": [{"建玉ID": t["建玉ID"], "観測純額円": t["基準純損益円"],
            "観測経路注意": t["観測経路注意"], "返済理由": t["返済理由"]} for t in detail["取引"]],
        "cacheパス": entry["cache_path"], "cacheSHA256": entry["sha256_cache"],
        "原板stat確認": True, "ザラバ終了時計秒": finish}


def write_markdown(study: Path, result: dict) -> None:
    """全36群の寄与と指定3場の要点を小さいMarkdownへ保存する。

    引数: study (Path) は正式保存先、result (dict) は診断結果。
    返り値: None。既存README・結果・条件は変更しない。
    """
    focus = result["注目候補"]["学習寄与"]
    lines = ["# 注意場と注意取引の寄与", "",
        "00014の固定12候補×3期間を事後に診断した。全65場は既使用。集計の正本は[注意経路診断.json](注意経路診断.json)。",
        "", "品質注意は場全体のフラグ、注意取引はその取引が保有中または新規待機中の正常板空白に触れたフラグで、分母が違う。注意場には注意なし取引もある。原結果・候補・条件を変更していない。",
        "", "注意場や注意取引を除いた金額は事後参考であり、欠測を避けて稼働できる戦略の成績ではない。空白内のTP/SL到達・執行と、それで変わる一建玉の抑止/再参加は不明。注意を含む全体の確定額はnullを維持する。",
        "", "## 指定候補の学習3場", "",
        f"{FOCUS} の学習全体観測純額は {focus['全体観測現金増減円']:,.0f}円。注意3場の全取引は {focus['注意場の観測現金増減円']:,.0f}円、そのうち注意取引は {focus['注意取引の観測純額円']:,.0f}円、注意場内の注意なし取引は {focus['注意場内の注意なし完結取引純額円']:,.0f}円だった。",
        f"注意場を丸ごと除いた参考額は {focus['事後_注意場除外参考円']:,.0f}円、注意取引だけ除いた完結取引の参考額は {focus['事後_注意取引だけ除外の完結取引参考円']:,.0f}円。どちらも全体成績の代用にしない。",
        "", "| 場 | 場全額円 | 注意取引円 | その他取引円 | 場内空白数 | 注意取引の返済 |", "|---|---:|---:|---:|---:|---|"]
    for session in result["注目候補"]["学習注意3場の局所経路"]:
        reasons = "、".join(f"{t['返済理由']}（待機{t['返済要求から約定秒']:g}秒）" for t in session["注意取引の局所経路"])
        lines.append(f"| {session['場']} | {session['場全体観測純額円']:,.0f} | {session['注意取引観測純額円']:,.0f} | {session['注意なし取引観測純額円']:,.0f} | {session['正常板空白数']} | {reasons} |")
    lines += ["", "JSONには全空白の隣接正常BBO・原板行・価格時計、保有/新規待機/返済待機との位置、実際の要求と約定、MFE/MAEの直接照合を保存した。価格時計はCurrentPriceTimeで、秒差は実受信断や実注文応答の遅延を測った値ではない。期限予約の原行0は実原行ではなく、参照板は期限strict直前とした。",
        "", "## 全12候補×3期間", "",
        "金額はmicro1枚の代理模型・倍率10円/pt・片道11円、追加滑り0。ここでの注意場除外は場全体を除いた現金参考額。追加5/10ptの感度と注意取引だけの分解はJSONに残す。",
        "", "| 候補 | 期間 | 全体観測円 | 注意場数 | 注意場円 | 注意取引数 | 注意取引円 | 注意場除外参考円 | 全体確定円 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in result["全12候補3期間"]:
        definite = "null" if row["全体確定対象純額円"] is None else f"{row['全体確定対象純額円']:,.0f}"
        lines.append(f"| {row['候補ID']} | {row['期間']} | {row['全体観測現金増減円']:,.0f} | {row['注意場数']} | {row['注意場の観測現金増減円']:,.0f} | {row['注意取引数']} | {row['注意取引の観測純額円']:,.0f} | {row['事後_注意場除外参考円']:,.0f} | {definite} |")
    lines += ["", "## 照合と再現", "",
        f"照合{result['照合項目数']:,}項目、不一致{result['不一致数']}。固定結果・詳細展開SHA・入力台帳SHA・局所cache SHAをJSONに記録した。固定core/条件/result・原板は変更しない。正常板抽出だけ既存の独立読取補助を使い、運用模型を再実行して答えを作ってはいない。",
        "", "再現：プロジェクトルートから Python のUTF-8モードで scripts/数量反転/注意経路診断.py を実行する。既存の完成したwork詳細と固定cacheが必要。", ""]
    (study / "注意経路診断.md").write_text("\n".join(lines), encoding="utf-8")


def run(study: Path, work: Path) -> dict:
    """全固定候補の寄与を分解し、指定候補の学習注意3場だけ原気配を直接診断する。

    引数: study/work (Path) は正式試行と作業先。
    返り値: dict は集計・局所経路・明示合否・指紋。候補選び直しや補間はしない。
    """
    report, manifest = read(study / "結果.json"), read(SOURCE)
    detail_path = work / "全運用詳細.jsonl.gz"
    groups, digest = defaultdict(list), hashlib.sha256()
    with gzip.open(detail_path, "rb") as stream:
        for raw in stream:
            digest.update(raw)
            row = json.loads(raw)
            groups[row["候補ID"], row["品質"]["期間"]].append(row)
    artifacts = read(study / "作業成果物.json")["ファイル"]
    expected_sha = next(r["展開内容SHA256"] for r in artifacts if Path(r["パス"]).name == detail_path.name)
    if digest.hexdigest() != expected_sha:
        raise ValueError("全運用詳細の展開SHAが正本と不一致")
    before = {p.name: sha(p) for p in (study / "結果.json", study / "条件.json", study / "固定.json")}
    audit = Audit()
    summaries, expected_keys = [], set()
    for row in report["結果"]:
        for period in PERIODS:
            method = row["候補ID"]
            expected_keys.add((method, period))
            summaries.append(summarize(method, period, groups[method, period], row[period]["運用"], audit))
    audit.check("固定12候補", len(report["結果"]), 12)
    audit.check("全36群", set(groups), expected_keys)
    attention = [d for d in groups[FOCUS, "学習"] if d["品質"]["観測経路注意"]]
    audit.check("注目候補学習注意3場", len(attention), 3)
    entries = {e["session"]: e for e in manifest["entries"]}
    local = [local_session(d, entries[d["場"]], Path(manifest["source_root"]), audit) for d in attention]
    focus = next(r for r in summaries if (r["候補ID"], r["期間"]) == (FOCUS, "学習"))
    audit.check("指定注意場寄与との接合", focus["注意場の観測現金増減円"], sum(s["場全体観測純額円"] for s in local))
    audit.check("指定注意取引寄与との接合", focus["注意取引の観測純額円"], sum(s["注意取引観測純額円"] for s in local))
    for name, value in before.items():
        audit.check("固定資料を変更しない:" + name, sha(study / name), value)
    result = {"全件一致": not audit.errors, "照合項目数": audit.count, "不一致数": len(audit.errors), "不一致": audit.errors,
        "全65場既使用": True, "候補選び直し": False, "全12候補3期間": summaries,
        "注目候補": {"候補ID": FOCUS, "学習寄与": focus, "学習注意3場の局所経路": local},
        "定義": {"注意場": "infoの観測経路注意。注意取引に加え新規待機重複・EOF・未解消等を含み得る。",
                 "注意取引": "tradeの観測経路注意。保有中または新規待機中の300秒超正常板空白に触れた保存フラグ。",
                 "事後除外": "注意場全体または注意取引だけを事後に差し引いた参考。空白を避けられる実運用や、経路を再生し直した別戦略の成績ではない。",
                 "全体確定額": "注意場がある候補・期間はnullを維持。観測の部分和を確定収益としない。",
                 "金額比": "注意額/全体観測現金増減の符号付き算術比。損失・相殺や分母0の影響があり、勝率や因果的利益依存率ではない。"},
        "検証範囲": "全12候補×3期間の場別現金/完結取引/注意取引・注意場の分解と保存結果の費用感度。指定候補の学習注意3場を原cacheから読み、全300秒超正常BBO空白と保有/待機、初着の固定TP/SL・期限要求と1秒後の最初正常BBO約定、MFE/MAEを直接照合。",
        "限界": "正常板空白はCurrentPriceTime上の観測差で実受信断や市場の無約定を断定しない。空白内の価格・板・SL/TP到達と執行は不明で、補間しない。注意経路での別の返済は後続の建玉抑止や再参加も変える。原板本文は再読/複製しない。",
        "再現コマンド": "python -X utf8 scripts/数量反転/注意経路診断.py",
        "コードSHA256": sha(Path(__file__)), "独立正常板抽出補助SHA256": sha(HELPER),
        "入力台帳パス": SOURCE.relative_to(ROOT).as_posix(), "入力台帳SHA256": sha(SOURCE),
        "原結果SHA256": before["結果.json"], "条件SHA256": before["条件.json"], "固定資料SHA256": before["固定.json"],
        "全運用詳細パス": detail_path.relative_to(ROOT).as_posix(), "全運用詳細展開SHA256": digest.hexdigest(),
        "局所cache": [{"場": s["場"], "パス": s["cacheパス"], "SHA256": s["cacheSHA256"]} for s in local]}
    body = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    (work / "注意経路診断.json").write_text(body, encoding="utf-8")
    (study / "注意経路診断.json").write_text(body, encoding="utf-8")
    write_markdown(study, result)
    print(json.dumps({"全件一致": result["全件一致"], "照合項目数": audit.count, "不一致数": len(audit.errors),
        "注目候補学習": {key: focus[key] for key in ("全体観測現金増減円", "注意場の観測現金増減円",
        "注意取引の観測純額円", "注意場内の注意なし完結取引純額円", "事後_注意場除外参考円")},
        "不一致": audit.errors}, ensure_ascii=False))
    return result


def main() -> None:
    """完成済み00014の診断先だけを指定して実行する。

    引数: なし。--study/--workを読む。
    返り値: None。不一致は非0で終了する。
    """
    parser = argparse.ArgumentParser(description="00014注意経路の事後診断")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    args = parser.parse_args()
    if not run(args.study.resolve(), args.work.resolve())["全件一致"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
