"""固定30分高安への最初の終値内復帰と外回復を因果順に切り替える。"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("終値切替の固定23入口補助", ROOT/"scripts/高安再開/入口.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
OLD_CONFIG = json.loads((ROOT/"study/00023_上位高安の再テストと順行再開/条件.json").read_text(encoding="utf-8"))
POLICIES = ("E0", "E1")
finite, width, trend, assign_channel = BASE.finite, BASE.width, BASE.trend, BASE.assign_channel
RULES = {"チャネル足分": 30, "チャネル本数": 6, "ε_ATR倍率": 0.25, "内復帰上限本数": 6, "外回復上限本数": 3}


def validate_config(config: dict) -> None:
    """新二規則と固定23から実際に継承する数値条件を照合する。

    引数: config (dict) は24条件。
    返り値: None。不一致は例外。
    """
    if config["時間足分"] != [3] or config["戦略"] != list(POLICIES) or config["終値切替"] != RULES:
        raise ValueError("固定3分・E0/E1・終値状態条件だけ")
    inherited = ("対象", "全65場既使用", "運用", "必須追尾", "発動条件", "指標", "局面改訂", "逆行pt", "順行pt",
                 "残り時間下限分", "確認遅延上限秒", "入口支持", "費用支持", "目標確認率", "間引き必要件数", "分割", "出口")
    if any(config.get(k) != OLD_CONFIG.get(k) for k in inherited):
        raise ValueError("固定23の実数値と設定表示が不一致")


def classify(higher: list[dict], session: str, config: dict) -> tuple[list[dict], dict]:
    """固定23が使用した15分現前ペアとS2を読取再用する。

    引数: higher (list[dict]) は15足、session (str) は場、config (dict) は24条件。
    返り値: tuple[list[dict],dict] は固定15分類と品質。
    """
    validate_config(config)
    return BASE.classify(higher, session, OLD_CONFIG)


def source_valid(source: dict | None) -> bool:
    """登録時に固定した30窓が六本の有効な境界かを検査する。

    引数: source (dict|None) は固定又は登録前の30窓。
    返り値: bool は六本・正の高安・R>Lか。後続の最新窓へ置換しない。
    """
    return bool(source and source.get("30窓準備済") and source.get("30窓本数") == 6
                and finite(source.get("R"), source.get("L")) and source["R"] > source["L"] > 0)


def verdict(ok: bool, reasons: list[str]) -> dict:
    """採否を二戦略共通の形式へ整える。

    引数: ok (bool) は可否、reasons (list[str]) は当時理由。
    返り値: dict は正本採否。事後ラベルは含めない。
    """
    return {"採用": bool(ok), "理由": reasons, "同時競合": False}


def decisions(context: dict, family: str, side: int) -> dict:
    """同じ価格と勢いの発動へ、E1だけ上位選別を加える。

    引数: context (dict) は当時準備、family (str) はR内復帰/T外回復、side (int) は実方向。
    返り値: dict はE0/E1の採否。指標数値準備だけを複数手法と数えない。
    """
    momentum = finite(context.get("MACDヒスト変化")) and side*context["MACDヒスト変化"] > 0
    reasons = list(context["M除外理由"])
    if not context["時間条件可"]:
        reasons.append("要求時間条件外")
    if not momentum:
        reasons.append("実方向MACD勢い不成立")
    common = not reasons
    upper = trend(context, side)
    upper_reason = "実方向S2T" if upper else "上位切替対象外"
    if family == "R内復帰" and not upper and finite(context.get("ADX変化")):
        if context["ADX変化"] < 0:
            upper, upper_reason = True, "上位ADX弱まり"
        elif context["ADX変化"] == 0:
            upper, upper_reason = True, "上位ADX横ばい"
    return {"E0": verdict(common, reasons or ["価格と実方向MACD採用"]),
            "E1": verdict(common and upper, (reasons or ["価格と実方向MACD採用"])+[upper_reason])}


def signal(frame: dict, context: dict, session: str, deadline: float,
           family: str, side: int, watch: dict) -> dict:
    """新時計の発動を既存先着・運用・会計形式へ変換する。

    引数: frame/context/watch (dict) は現足/当時準備/固定設定、session/family (str) は場/役割系統、
    deadline (float) は返済期限、side (int) は今回新規方向。
    返り値: dict は全二採否付き発動。後の監視情報は深複写で混入を防ぐ。
    """
    event = watch["エピソードID"]+("_内復帰" if family == "R内復帰" else "_外回復")
    return {**deepcopy(frame), **deepcopy(context), "場": session, "時間足分": 3, "入口系統": family,
            "役割": "反転" if family == "R内復帰" else "順行", "side": side, "方向": "買い" if side == 1 else "売り",
            "発動ID": event, "QイベントID": event, "イベントID": event, "入口ID": "3分_"+family,
            "要求時計秒": frame["confirm"], "要求原板行": frame["confirm_line"],
            "確認遅延秒": frame["confirm"]-frame["end"], "足終了時計秒": frame["end"],
            "期限時計秒": deadline, "残り分_判断時": (deadline-frame["confirm"])/60,
            "先着評価対象": bool(context["時間条件可"] and context["確認遅延条件可"]),
            "戦略判定": decisions(context, family, side), "固定設定": deepcopy(watch),
            "元突破side": watch["side"], "エピソードID": watch["エピソードID"]}


# ----------------------------------------
# 価格監視を注文状態・指標の採否・事後先着から分離する。

def generate(frames: list[dict], higher: list[dict], session: str, cutoff: float, deadline: float,
             config: dict, states: list[dict] | None = None, channels: list[dict] | None = None,
             quantity: dict | None = None) -> tuple[dict, dict]:
    """価格だけで広く登録し、最初の終値内復帰/外回復を一度ずつ消費する。

    引数: frames/higher (list[dict]) は3/15足、session (str) は場、cutoff/deadline (float) は時限、
    config (dict) は条件、states/channels (list[dict]|None) は分類/30窓、quantity (dict|None) は診断だけ。
    返り値: tuple[dict,dict] は二採用集合と全価格状態・全発動・全足準備。
    """
    validate_config(config)
    if not frames or any(f["minutes"] != 3 for f in frames):
        raise ValueError("同場3分足が必要")
    if states is None:
        states, _ = classify(higher, session, config)
    uppers = BASE.BASE.assign(frames, states)
    assigned = assign_channel(frames, channels or [])
    records, contexts, trace, episodes = [], [], [], []
    watch, previous, previous_index, previous_key, used = None, None, None, None, set()
    counts = Counter()
    for frame in frames:
        index, now, line = frame["index"], frame["confirm"], frame["confirm_line"]
        key = now, line
        if previous_index is not None and index <= previous_index:
            raise ValueError("3分番号重複/後退")
        if frame["publish"] and (now < frame["end"] or previous_key is not None and key < previous_key):
            raise ValueError("公開前足又は公開key後退")
        sequential = previous_index is None or index == previous_index+1
        price_valid = bool(frame["publish"] and not frame["missing"] and sequential
                           and finite(frame.get("close")) and frame["close"] > 0)
        prior = previous if previous is not None and previous["publish"] and index == previous["index"]+1 else None
        prior_close = bool(prior and finite(prior.get("close")) and prior["close"] > 0)
        atr_valid = finite(frame.get("atr")) and frame["atr"] > 0
        delta = frame["macd_hist"]-prior["macd_hist"] if prior and finite(frame.get("macd_hist"), prior.get("macd_hist")) else None
        ch, upper = assigned[index], uppers[index]
        ref = watch["30窓出典"] if watch is not None else ch["30窓参照"]
        delayed = now-frame["end"] > config["確認遅延上限秒"]
        time_ok = now < cutoff and deadline-now >= config["残り時間下限分"]*60
        reasons = []
        if not price_valid or not prior_close:
            reasons.append("同場隣接公開価格未準備")
        if delta is None:
            reasons.append("現在前MACD未準備")
        if not atr_valid:
            reasons.append("現在ATR未準備")
        if not upper["ペア準備済"]:
            reasons.append("同場隣接公開15分ペア未準備")
        if not source_valid(ref):
            reasons.append("固定登録30窓未準備")
        if delayed:
            reasons.append("足確定確認遅延30秒超")
        context = {**deepcopy(frame), **deepcopy(upper), **deepcopy(ch), "場": session, "時間足分": 3,
            "前3分参照": {k: prior.get(k) for k in ("index", "end", "confirm", "confirm_line", "close", "macd_hist")} if prior else None,
            "登録30窓参照": deepcopy(ref), "固定30窓有効": source_valid(ref), "MACDヒスト変化": delta,
            "共通M24準備": not reasons, "共通M準備": not reasons, "M除外理由": reasons,
            "価格連続準備": price_valid and prior_close, "登録価格準備": price_valid and prior_close and atr_valid and source_valid(ch["30窓参照"]),
            "時間条件可": time_ok, "確認遅延条件可": not delayed,
            "数量診断": deepcopy(quantity.get(index)) if quantity is not None else None}
        contexts.append(context)
        counts["足数"] += 1
        counts["共通M準備足数"] += not reasons
        actions, before, blocked = [], deepcopy(watch), watch is not None
        if watch is not None:
            origin = watch["設定"] if watch["段階"] == "内復帰待ち" else watch["内復帰"]
            age, limit = index-origin["index"], 6 if watch["段階"] == "内復帰待ち" else 3
            end_reason = None
            if not price_valid:
                end_reason = "公開価格連続性失効"
            elif now >= deadline:
                end_reason = "返済期限"
            elif age > limit:
                end_reason = "内復帰六足満了" if limit == 6 else "外回復三足満了"
            elif frame["end"] <= origin["confirm"] or key <= (origin["confirm"], origin["confirm_line"]):
                actions.append({"動作": "価格時点対象外", "段階": watch["段階"], "理由": "end又はkeyが前段公開より後でない", "経過本数": age})
            elif (frame["close"] <= watch["L"] if watch["side"] == 1 else frame["close"] >= watch["R"]):
                end_reason = "反対端到達"
                episodes[watch["診断番号"]]["反対端到達"] = {k: frame[k] for k in ("index", "end", "confirm", "confirm_line", "close")}
            elif watch["段階"] == "内復帰待ち" and watch["L"] < frame["close"] < watch["R"]:
                record = signal(frame, context, session, deadline, "R内復帰", -watch["side"], watch)
                records.append(record)
                watch["内復帰"] = {k: frame[k] for k in ("index", "end", "confirm", "confirm_line", "close", "atr")}
                watch["段階"] = "外回復待ち"
                episodes[watch["診断番号"]]["最初内復帰"] = deepcopy(watch["内復帰"])
                actions.append({"動作": "内復帰価格消費", "発動ID": record["発動ID"], "戦略採否": deepcopy(record["戦略判定"])})
            elif watch["段階"] == "外回復待ち" and watch["side"]*(frame["close"]-watch["境界"]) > 0:
                record = signal(frame, context, session, deadline, "T外回復", watch["side"], watch)
                records.append(record)
                episodes[watch["診断番号"]]["最初外回復"] = {k: frame[k] for k in ("index", "end", "confirm", "confirm_line", "close", "atr")}
                actions.append({"動作": "外回復価格消費", "発動ID": record["発動ID"], "戦略採否": deepcopy(record["戦略判定"])})
                end_reason = "外回復価格消費"
            if end_reason is not None:
                actions.append({"動作": "監視満了" if end_reason.endswith("満了") else "監視終了", "理由": end_reason})
                episodes[watch["診断番号"]].update(終了理由=end_reason, 終了時計秒=now, 終了原板行=line)
                watch = None
        # ----------------------------------------
        # 登録は価格と時刻だけ。MACD/S2/確認遅延の符号gateは入れない。
        setup_reasons = []
        if blocked:
            setup_reasons.append("旧監視あり・同足新設定禁止")
        if not context["登録価格準備"]:
            setup_reasons.append("登録価格準備不可")
        if not time_ok:
            setup_reasons.append("新登録時間不可")
        if context["登録価格準備"]:
            eps = width(frame["atr"])
            for side, boundary in ((1, ch["30窓参照"]["R"]), (-1, ch["30窓参照"]["L"])):
                level = boundary+side*eps
                if not side*(prior["close"]-level) <= 0 < side*(frame["close"]-level):
                    continue
                rejection = list(setup_reasons)
                if (side, boundary) in used:
                    rejection.append("当場同方向境界使用済み")
                actions.append({"動作": "価格突破登録見送り" if rejection else "価格突破登録", "side": side,
                    "境界": boundary, "ε": eps, "理由": rejection, "登録遅延秒": now-frame["end"]})
                if rejection:
                    continue
                used.add((side, boundary))
                setup = {k: frame[k] for k in ("index", "start", "end", "confirm", "confirm_line", "close", "atr")}
                episode = f"NK225_{session}_3分_設定{index:04d}_{side}"
                watch = {"エピソードID": episode, "段階": "内復帰待ち", "side": side, "境界": boundary,
                    "R": ch["30窓参照"]["R"], "L": ch["30窓参照"]["L"], "ε": eps,
                    "30窓出典": deepcopy(ch["30窓参照"]), "設定": setup, "内復帰": None,
                    "登録S2理由": context["S2理由"], "登録旧23方向勢い資格": trend(context, side) and delta is not None and side*delta > 0,
                    "登録確認遅延秒": now-frame["end"], "診断番号": len(episodes)}
                episodes.append({"エピソードID": episode, "設定": deepcopy(setup), "side": side, "境界": boundary,
                    "登録旧23方向勢い資格": watch["登録旧23方向勢い資格"], "最初内復帰": None,
                    "最初外回復": None, "反対端到達": None, "終了理由": None})
                break
        trace.append({"場": session, "index": index, "時計秒": now, "原板行": line, "監視前": before,
            "動作": actions, "新設定除外理由": setup_reasons, "監視後": deepcopy(watch)})
        previous = frame if frame["publish"] and finite(frame.get("close")) and frame["close"] > 0 else None
        previous_index = index
        if frame["publish"]:
            previous_key = key
    if watch is not None:
        episodes[watch["診断番号"]]["終了理由"] = "場末尾監視終了"
    # ----------------------------------------
    # 全採否の競合を確定してから、正本snapshotを各caseへ深複写する。
    output = {"3分_"+p: [] for p in POLICIES}
    selected = defaultdict(list)
    for row in records:
        for p in POLICIES:
            if row["戦略判定"][p]["採用"]:
                selected[p, row["要求時計秒"], row["要求原板行"]].append(row)
    for (p, _, _), rows in selected.items():
        if len(rows) > 1:
            for row in rows:
                row["戦略判定"][p] = {"採用": False, "理由": ["同判断複数信号見送り"], "同時競合": True}
    for (p, _, _), rows in selected.items():
        if len(rows) == 1:
            row, source = rows[0], "3分_"+p
            output[source].append({**deepcopy(row), "入口ID": source, "戦略": p,
                "複合判定": deepcopy(row["戦略判定"][p]), "イベントID": row["発動ID"]+"_"+p})
    actions = Counter(a["動作"] for t in trace for a in t["動作"])
    stages = []
    for role in ("反転", "順行"):
        local = [r for r in records if r["役割"] == role]
        stages.append({"役割": role, "原価格イベント数": len(local),
            "時間可数": sum(r["時間条件可"] for r in local),
            "確認遅延可数": sum(r["確認遅延条件可"] for r in local),
            "先着評価対象数": sum(r["先着評価対象"] for r in local),
            "M時間通過数": sum(r["共通M準備"] and r["時間条件可"] for r in local),
            "勢い通過E0数": sum(r["戦略判定"]["E0"]["採用"] for r in local),
            "上位通過E1数": sum(r["戦略判定"]["E1"]["採用"] for r in local)})
    return output, {"場": session, "時間足分": 3, **dict(counts), "全Q発動記録": records,
        "複合context記録": contexts, "監視trace": trace, "エピソード診断": episodes, "設定数": len(episodes),
        "内復帰価格消費数": actions["内復帰価格消費"], "外回復価格消費数": actions["外回復価格消費"],
        "対象外足数": actions["価格時点対象外"], "先着評価対象外数": sum(not r["先着評価対象"] for r in records),
        "登録遅延超数": sum(e["設定"]["confirm"]-e["設定"]["end"] > config["確認遅延上限秒"] for e in episodes),
        "監視動作別": dict(actions), "終了理由別": dict(Counter(e["終了理由"] for e in episodes)),
        "新設定除外理由別": dict(Counter(z for t in trace for z in t["新設定除外理由"])),
        "登録候補数": actions["価格突破登録"]+actions["価格突破登録見送り"],
        "登録見送り理由別": dict(Counter(z for t in trace for a in t["動作"] if a["動作"] == "価格突破登録見送り" for z in a["理由"])),
        "イベント段階": stages, "イベントM除外理由別": dict(Counter(z for r in records for z in r["M除外理由"])),
        "戦略採否理由別": {p: dict(Counter(z for r in records for z in r["戦略判定"][p]["理由"])) for p in POLICIES},
        "戦略別役割発動数": {p: dict(Counter(r["役割"] for r in v)) for p, v in output.items()},
        "戦略別発動数": {p: len(v) for p, v in output.items()}}
