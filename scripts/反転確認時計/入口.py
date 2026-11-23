"""固定25の価格状態に、反転fから初めてSAR方向を確認する時計を加える。"""

from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("反転確認時計の固定25価格入口", ROOT/"scripts/SAR持続/入口.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
OLD_CONFIG = json.loads((ROOT/"study/00025_価格イベントとSAR方向持続/条件.json").read_text(encoding="utf-8"))
POLICIES = ("N0", "N1", "N2")
finite = BASE.finite
RULES = {"後続上限本数": 3,
    "即時": "f現在公開SARがrならfを確認hとして一回消費、別raw重複なし",
    "後続": "f次1..3、end>f.confirm/keystrictの最初現公開SARdir=rを新hとしてconsume。strict L<C<RはN2採否",
    "取消優先": "親価格監視取消/失効・g外回復・反対端・期限→age>3→後続時点対象外(寿命のみ)→初現公開SARrをhconsume→strict帯内/M/時間等を採否",
    "採否分離": "最初のSARrはM/時間/遅延/保有不可でもconsumeし後足へ取り直さない",
    "g継続": "h消費後も親価格gの判定を維持。実建玉roleはfill固定、自動ドテンなし",
    "M26": "M25同値、SAR方向の値選別は別",
    "生集合": "原f/gは固定25同値。後続hはN2だけ対象、N0N1は対象外。N1原採用はN2部分集合",
    "元端等号": "C=元境界でも初SARrをhraw保存/消費、strict帯内不成立でN2不採用、後足へ取り直さない"}
PREPARE_FIELDS = ("発動ID", "入口系統", "役割", "side", "要求時計秒", "要求原板行", "足終了時計秒", "期限時計秒",
    "close", "atr", "共通M26準備", "M除外理由", "時間条件可", "確認遅延条件可", "先着評価対象",
    "f起点参照", "f起点発動ID", "反転確認種別", "h価格条件可", "固定設定", "戦略判定")


def atr_ticks(value: object) -> dict:
    """ATRから売買に使う二つの呼値丸め整数を診断用に作る。

    引数: value(object)はATR原値又は欠測。
    返り値: dictは正有効可否とε/Dのpt整数。売買の入力値や計算を変更しない。
    """
    valid = finite(value) and value > 0
    return {"ATR正有効": bool(valid), "登録εpt整数": max(5, math.ceil(0.25*value/5)*5) if valid else None,
        "追尾Dpt整数": max(5, math.ceil(value/5)*5) if valid else None}


def canonical_projection(value: object) -> object:
    """準備比較だけでATR浮動値を丸め後の整数へ置き換える。

    引数: value(object)は配列・辞書・末端値。
    返り値: objectはatr列だけを投影した新しい構造。他の価格/時点/SAR/採否は保持する。
    """
    if isinstance(value, dict):
        return {k: atr_ticks(v) if k == "atr" else canonical_projection(v) for k, v in value.items()}
    if isinstance(value, list):
        return [canonical_projection(v) for v in value]
    return value


def atr_leaves(value: object, path: str) -> list[dict]:
    """全atr末端の経路と原値を独立の数値照合へ保存する。

    引数: value(object)は検算対象配列等、path(str)は配列識別からの経路。
    返り値: list[dict]は辞書整列/配列順の経路・値・丸め整数。生の浮動値を保持する。
    """
    rows = []
    if isinstance(value, dict):
        for k in sorted(value):
            if k == "atr":
                rows.append({"経路": path+"/"+k, "値": value[k], **atr_ticks(value[k])})
            else:
                rows.extend(atr_leaves(value[k], path+"/"+k))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            rows.extend(atr_leaves(item, path+"/"+str(index)))
    return rows


def canonical_sha(rows: list[dict]) -> str:
    """ATR丸め整数と、それ以外の厳密な状態構造を指紋化する。

    引数: rows(list[dict])は時点順の記録配列。ATR原値は別の全leaf検算列に残す。
    返り値: strは日本語UTF-8・辞書キー整列JSON投影配列のSHA256。
    """
    return hashlib.sha256(json.dumps(canonical_projection(rows), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def validate_config(config: dict) -> None:
    """三案と固定25から継承する数値・SAR規約を検査する。

    引数: config(dict)は26条件。
    返り値: None。不一致は例外。後続上限は三本に固定する。
    """
    if config["時間足分"] != [3] or config["戦略"] != list(POLICIES):
        raise ValueError("固定3分・N0/N1/N2だけ")
    inherited = ("対象", "全65場既使用", "運用", "必須追尾", "発動条件", "指標", "局面改訂", "逆行pt", "順行pt",
        "残り時間下限分", "確認遅延上限秒", "入口支持", "費用支持", "目標確認率", "間引き必要件数", "分割", "出口", "終値切替", "SAR")
    if any(config.get(k) != OLD_CONFIG.get(k) for k in inherited):
        raise ValueError("固定25の数値/SAR規約と設定表示が不一致")
    if config["反転確認"] != RULES:
        raise ValueError("固定の反転確認三本/時点/消費規約だけ")


def classify(higher: list[dict], session: str, config: dict) -> tuple[list[dict], dict]:
    """固定25の上位準備だけを読み取り再用する。

    引数: higher(list[dict])は15足、session(str)は場、config(dict)は26条件。
    返り値: tuple[list[dict],dict]は同じ分類と品質。N採否で上位値を選別しない。
    """
    validate_config(config)
    return BASE.classify(higher, session, OLD_CONFIG)


def current_sar(context: dict, side: int) -> bool:
    """現在の公開SARが実新規方向か調べ、他のM条件とは分ける。

    引数: context(dict)は当時情報、side(int)は実方向。
    返り値: boolは現在公開SAR方向の一致。M不成立でも価格確認を消費できる。
    """
    return bool(context["SAR現在有効"] and context["SAR現方向"] == side)


def verdicts(context: dict, family: str, side: int, inside: bool = True) -> dict:
    """同じM26で反転の値条件/確認時計と共通順行を判定する。

    引数: context(dict)はM26、family(str)はf/g/後続h、side(int)は実方向、inside(bool)はhのstrict帯内。
    返り値: dictは全N正本採否。h対象外、数値準備、時間、値を分離する。
    """
    common = list(context["M除外理由"])
    if not context["時間条件可"]:
        common.append("要求時間条件外")
    now_sar = current_sar(context, side)
    momentum = finite(context.get("MACDヒスト変化")) and side*context["MACDヒスト変化"] > 0
    persistent = context["SAR現前準備"] and context["SAR現方向"] == context["SAR前方向"] == side
    output = {}
    for p in POLICIES:
        reasons = list(common)
        if family == "T外回復":
            if not persistent:
                reasons.append("実方向SAR二本持続不成立")
            success = "価格外回復と実方向SAR二本持続採用"
        elif family == "R内復帰":
            if p == "N0":
                if not momentum:
                    reasons.append("実方向MACD勢い不成立")
                success = "価格内復帰と実方向MACD採用"
            else:
                if not now_sar:
                    reasons.append("現在公開SAR実方向不成立")
                success = "価格内復帰と現在公開SAR採用"
        elif family == "R方向確認":
            if p != "N2":
                reasons.append("後続hは当案対象外")
            if not inside:
                reasons.append("SAR確認時の終値が固定範囲内でない")
            if not now_sar:
                reasons.append("現在公開SAR実方向不成立")
            success = "内復帰後の公開SAR方向確認採用"
        else:
            raise ValueError("未知の価格/方向確認系統")
        output[p] = BASE.BASE.verdict(not reasons, reasons or [success])
    return output


def foot_reference(row: dict) -> dict:
    """f又はhの価格と公開時点を小さな出典へ固定する。

    引数: row(dict)は当時足又は原イベント。
    返り値: dictは足番号/価格/ATR/キー。将来値やラベルを持たない。
    """
    return {k: row[k] for k in ("index", "start", "end", "confirm", "confirm_line", "close", "atr")}


def h_signal(context: dict, watch: dict, session: str, deadline: float) -> dict:
    """後続最初SAR一致を新時計の技術イベントとして保存する。

    引数: context/watch(dict)は現在とf固定情報、session(str)は場、deadline(float)は返済期限。
    返り値: dictは全N採否付きh。元端等号は保存してstrict帯内不採用へ分ける。
    """
    event = watch["f発動ID"]+"_後続SAR確認"
    side = watch["r"]
    inside = watch["L"] < context["close"] < watch["R"]
    fixed = deepcopy(watch["価格設定"])
    fixed.update(段階="外回復待ち", 内復帰=deepcopy(watch["f"]))
    return {**deepcopy(context), "場": session, "時間足分": 3, "入口系統": "R方向確認", "役割": "反転",
        "side": side, "方向": "買い" if side == 1 else "売り", "発動ID": event, "QイベントID": event,
        "イベントID": event, "入口ID": "3分_R方向確認", "要求時計秒": context["confirm"],
        "要求原板行": context["confirm_line"], "確認遅延秒": context["confirm"]-context["end"],
        "足終了時計秒": context["end"], "期限時計秒": deadline, "残り分_判断時": (deadline-context["confirm"])/60,
        "先着評価対象": bool(context["時間条件可"] and context["確認遅延条件可"]),
        "元突破side": -side, "エピソードID": watch["エピソードID"], "固定設定": fixed,
        "f起点参照": deepcopy(watch["f"]), "f起点発動ID": watch["f発動ID"],
        "反転確認種別": "後続h", "h価格条件可": inside, "旧25戦略判定": None,
        "戦略判定": verdicts(context, "R方向確認", side, inside)}


# ----------------------------------------
# 親の価格監視は不変。反転確認だけを独立した一回消費の状態で追う。

def generate(frames: list[dict], higher: list[dict], session: str, cutoff: float, deadline: float,
             config: dict, states: list[dict] | None = None, channels: list[dict] | None = None,
             quantity: dict | None = None, sar_rows: list[dict] | None = None) -> tuple[dict, dict]:
    """固定25の全価格状態を再用し、最初SAR確認hと三案を追加する。

    引数: frames/higher/sar_rows(list[dict]|None)は3/15足と固定25SAR、session(str)は場、
    cutoff/deadline(float)は時限、config(dict)は26条件、states/channels/quantityは固定25入力。
    返り値: tuple[dict,dict]は三純入口、全原f/g/h・親監視・反転監視・段階品質。未来値は使わない。
    """
    validate_config(config)
    _, old = BASE.generate(frames, higher, session, cutoff, deadline, OLD_CONFIG, states, channels, quantity, sar_rows)
    quality = deepcopy(old)
    contexts = [{**deepcopy(c), "共通M26準備": c["共通M25準備"]} for c in old["複合context記録"]]
    parent = {r["index"]: r for r in old["監視trace"]}
    prices = {r["index"]: r for r in old["全Q発動記録"]}
    if len(prices) != len(old["全Q発動記録"]):
        raise ValueError("固定25の一足に複数価格イベント")
    records, trace, diagnostics, watch = [], [], [], None
    for context in contexts:
        index, now, line = context["index"], context["confirm"], context["confirm_line"]
        price = prices.get(index)
        actions, before = [], deepcopy(watch)
        if watch is not None:
            age = index-watch["f"]["index"]
            endings = [a for a in parent[index]["動作"] if a["動作"] in ("監視終了", "監視満了")]
            reason = "価格外回復先着" if price and price["入口系統"] == "T外回復" else endings[0]["理由"] if endings else None
            if reason is None and now >= deadline:
                reason = "返済期限"
            if reason is None and age > 3:
                reason = "後続三足満了"
            if reason is not None:
                actions.append({"動作": "反転監視取消", "理由": reason})
                diagnostics[watch["診断番号"]].update(終了理由=reason, 終了時計秒=now, 終了原板行=line)
                watch = None
            elif context["end"] <= watch["f"]["confirm"] or (now, line) <= (watch["f"]["confirm"], watch["f"]["confirm_line"]):
                actions.append({"動作": "後続確認時点対象外", "理由": "end又はkeyがf公開より後でない", "経過本数": age})
            elif current_sar(context, watch["r"]):
                row = h_signal(context, watch, session, deadline)
                records.append(row)
                actions.append({"動作": "後続SAR確認消費", "発動ID": row["発動ID"], "h価格条件可": row["h価格条件可"],
                    "戦略採否": deepcopy(row["戦略判定"])})
                diagnostics[watch["診断番号"]].update(確認種別="後続h", 確認発動ID=row["発動ID"],
                    確認足=foot_reference(context), h価格条件可=row["h価格条件可"], 終了理由="後続SAR確認消費", 終了時計秒=now, 終了原板行=line)
                watch = None
        # ----------------------------------------
        # f即時確認は明示分岐し、同fraw以外の重複イベントを作らない。
        if price is not None:
            row = {**deepcopy(price), **deepcopy(context)}
            row["旧25戦略判定"] = deepcopy(price["戦略判定"])
            row["戦略判定"] = verdicts(row, row["入口系統"], row["side"])
            row.update(反転確認種別="f即時" if row["入口系統"] == "R内復帰" and current_sar(row, row["side"]) else None,
                h価格条件可=True if row["入口系統"] == "R内復帰" else None)
            records.append(row)
            if row["入口系統"] == "R内復帰":
                if watch is not None:
                    raise ValueError("親価格と反転監視のepisodeが重複")
                f = foot_reference(row)
                watch = {"エピソードID": row["エピソードID"], "f発動ID": row["発動ID"], "r": row["side"],
                    "R": row["固定設定"]["R"], "L": row["固定設定"]["L"], "f": f,
                    "価格設定": deepcopy(row["固定設定"]), "診断番号": len(diagnostics)}
                diagnostics.append({"エピソードID": watch["エピソードID"], "f発動ID": watch["f発動ID"],
                    "r": watch["r"], "f": deepcopy(f), "確認種別": None, "確認発動ID": None, "確認足": None,
                    "h価格条件可": None, "終了理由": None, "終了時計秒": None, "終了原板行": None})
                actions.append({"動作": "反転候補登録", "f発動ID": row["発動ID"]})
                if current_sar(context, watch["r"]):
                    actions.append({"動作": "f即時SAR確認消費", "発動ID": row["発動ID"], "戦略採否": deepcopy(row["戦略判定"])})
                    diagnostics[-1].update(確認種別="f即時", 確認発動ID=row["発動ID"], 確認足=deepcopy(f),
                        h価格条件可=True, 終了理由="f即時SAR確認消費", 終了時計秒=now, 終了原板行=line)
                    watch = None
                else:
                    actions.append({"動作": "後続SAR確認待ち"})
        trace.append({"場": session, "index": index, "時計秒": now, "原板行": line,
            "反転監視前": before, "動作": actions, "反転監視後": deepcopy(watch)})
    if watch is not None:
        diagnostics[watch["診断番号"]]["終了理由"] = "場末尾反転監視終了"
    # ----------------------------------------
    # 全Nの競合を確定後、正本から各caseへ深複写する。
    chosen = defaultdict(list)
    for row in records:
        for p in POLICIES:
            if row["戦略判定"][p]["採用"]:
                chosen[p, row["要求時計秒"], row["要求原板行"]].append(row)
    for (p, _, _), values in chosen.items():
        if len(values) > 1:
            for row in values:
                row["戦略判定"][p] = {"採用": False, "理由": ["同判断複数信号見送り"], "同時競合": True}
    output = {"3分_"+p: [] for p in POLICIES}
    for (p, _, _), values in chosen.items():
        if len(values) == 1:
            row, source = values[0], "3分_"+p
            output[source].append({**deepcopy(row), "入口ID": source, "戦略": p,
                "複合判定": deepcopy(row["戦略判定"][p]), "イベントID": row["発動ID"]+"_"+p})
    canonical = {r["発動ID"]: r for r in records}
    for t in quality["監視trace"]+trace:
        for a in t["動作"]:
            if "戦略採否" in a:
                a["戦略採否"] = deepcopy(canonical[a["発動ID"]]["戦略判定"])
    counts = Counter(a["動作"] for t in trace for a in t["動作"])
    quality.update(全Q発動記録=records, 複合context記録=contexts, 反転監視trace=trace, 反転監視診断=diagnostics,
        固定25価格イベント数=len(prices), 後続h原イベント数=sum(r["入口系統"] == "R方向確認" for r in records),
        反転候補登録数=len(diagnostics), f即時SAR確認数=counts["f即時SAR確認消費"],
        後続SAR待機開始数=counts["後続SAR確認待ち"], 後続SAR確認消費数=counts["後続SAR確認消費"],
        後続確認時点対象外足数=counts["後続確認時点対象外"],
        h元端等号不採用数=sum(r["入口系統"] == "R方向確認" and not r["h価格条件可"] for r in records),
        反転監視動作別=dict(counts), 反転監視終了理由別=dict(Counter(d["終了理由"] for d in diagnostics)),
        イベントM除外理由別=dict(Counter(z for r in records for z in r["M除外理由"])),
        戦略採否理由別={p: dict(Counter(z for r in records for z in r["戦略判定"][p]["理由"])) for p in POLICIES},
        戦略別役割発動数={p: dict(Counter(r["役割"] for r in v)) for p, v in output.items()},
        戦略別発動数={p: len(v) for p, v in output.items()})
    quality["イベント段階"] = [{"系統": family, "役割": "順行" if family == "T外回復" else "反転",
        "原イベント数": sum(r["入口系統"] == family for r in records),
        "時間可数": sum(r["入口系統"] == family and r["時間条件可"] for r in records),
        "確認遅延可数": sum(r["入口系統"] == family and r["確認遅延条件可"] for r in records),
        "先着評価対象数": sum(r["入口系統"] == family and r["先着評価対象"] for r in records),
        "M26時間通過数": sum(r["入口系統"] == family and r["共通M26準備"] and r["時間条件可"] for r in records),
        **{p+"採用数": sum(r["入口系統"] == family and r["戦略判定"][p]["採用"] for r in records) for p in POLICIES}}
        for family in ("R内復帰", "T外回復", "R方向確認")]
    quality["先着評価対象外数"] = sum(not r["先着評価対象"] for r in records)
    projected = [{k: r.get(k) for k in PREPARE_FIELDS} for r in records]
    quality["全原発動投影内容SHA256"] = canonical_sha(projected)
    quality["反転監視内容SHA256"] = canonical_sha(trace)
    quality["反転診断内容SHA256"] = canonical_sha(diagnostics)
    quality["ATR検算列"] = atr_leaves(projected, "原発動")+atr_leaves(trace, "反転監視")+atr_leaves(diagnostics, "反転診断")
    quality["ATR全足検算列"] = [{"index": f["index"], "値": f.get("atr"), **atr_ticks(f.get("atr"))} for f in frames]
    return output, quality
