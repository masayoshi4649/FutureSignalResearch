"""00024の固定30窓と、最初の終値内復帰/外回復を原価格から別に構成する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00024_終値の内復帰と外回復による順行反転"
WORK = ROOT / "work/終値切替/00024"
INPUT = ROOT / "study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
PRICE_HELPER = ROOT / "scripts/高安再開/状態独立確認.py"
OLD_WORK = ROOT / "work/高安再開/00023"
POLICIES = ("E0", "E1")


def helper(path: Path, name: str) -> Any:
    """既存の独立価格/数量/窓だけを読み取る。

    引数: path (Path) は独立補助、name (str) は識別名。
    返り値: Any は補助。24主の指標/入口/driver/運用をimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


B = helper(PRICE_HELPER, "終値切替の独立価格と固定窓")
P, Q, S, V, Indicators = B.P, B.Q, B.S, B.V, B.Indicators
SOURCE_FIELDS = B.SOURCE_FIELDS


# ----------------------------------------
# 主の銀行ではなく、検算済みの独立半開足とWilder/MACDを一度ずつ更新する。

def price_blocks(manifest: dict, config: dict, audit: Any) -> Any:
    """全65場の原価格/数量から、独立価格足と15分S2・凍結元30窓を作る。

    引数: manifest/config (dict) は固定台帳/24条件、audit (Any) は比較記録。
    返り値: Any は場別の価格基礎を渡すiterator。ラベルや損益を読まない/計算しない。
    """
    banks, contract, channels = {n: Indicators() for n in (3, 15)}, None, B.ChannelHistory()
    previous = V.read(OLD_WORK / "状態独立確認.json")
    audit.check("固定23独立状態成功", previous["全件一致"], True)
    audit.check("固定23独立コード指紋", previous["コードSHA256"], V.sha(PRICE_HELPER))
    for entry in manifest["entries"]:
        session, codes = entry["session"], tuple(entry["in_session_contract_codes"])
        if len(codes) != 1:
            raise ValueError("固定入力の場内限月が一意でない")
        if contract is not None and codes != contract:
            banks = {n: Indicators() for n in banks}
        contract = codes
        period = "後続検査" if session[:10] >= config["分割"]["後続開始日"] else (
            "条件選択" if session[:10] >= config["分割"]["選択開始日"] else "学習")
        data = Q.observed(entry, Path(manifest["source_root"]))
        formed = {n: S.S.bars(data, session, n, bank) for n, bank in banks.items()}
        raw30 = S.S.bars(data, session, 30, Indicators())
        formed[30] = [{key: row[key] for key in SOURCE_FIELDS} for row in raw30]
        start, finish, cutoff, deadline = S.S.G.times(session)
        tail = max(0, int((finish - start) // 1800) - 1 - (raw30[-1]["index"] if raw30 else -1))
        snapshots, channel_quality = channels.build(formed[30], session, codes, tail)
        quantities, quantity_quality = Q.independent_quantity(data, formed[3], start, finish, 3)
        regimes, regime_quality = P.pair_states(formed[15], session)
        yield {"場": session, "期間": period, "価格足": formed, "30窓": snapshots,
            "30窓品質": channel_quality, "数量": quantities, "数量診断品質": quantity_quality,
            "局面": regimes, "局面品質": regime_quality, "新規停止": cutoff, "期限": deadline}


def upper_features(frame: dict, regimes: list[dict]) -> dict:
    """最新公開15分だけを原行/終了時点で直接列挙する。

    引数: frame (dict) は判断足、regimes (list[dict]) は独立15分S2。
    返り値: dict は最新asof。単点/ペア未準備の最新足から古正常へfallbackしない。
    """
    return P.assign(frame, regimes)


# ----------------------------------------
# 指標・局面・建玉とは切り離し、凍結された価格設定ごとに後続区間を走査する。

def structural_paths(frames: list[dict], channels: list[dict], session: str,
                     cutoff: float, deadline: float) -> tuple[list[dict], list[dict]]:
    """価格だけの登録候補と、最初の内復帰/外回復の区間経路を独立に列挙する。

    引数: frames/channels (list[dict]) は同場独立3分足/30窓、session (str) は場、
    cutoff/deadline (float) は新規停止/返済期限。
    返り値: tuple[list[dict],list[dict]] は全登録候補/登録済episode。指標・数量・新ラベル・損益を使わない。
    """
    assigned = B.assign_channels(frames, channels)
    candidates, by_position = [], defaultdict(list)
    for position, f in enumerate(frames):
        p = frames[position - 1] if position else None
        window = assigned[f["index"]]["30窓参照"]
        price_ready = bool(p is not None and f["index"] == p["index"] + 1 and f["publish"] and p["publish"]
            and not f["missing"] and S.S.finite(f["close"], p["close"], f["atr"])
            and f["close"] > 0 and p["close"] > 0 and f["atr"] > 0 and window is not None
            and window["30窓準備済"] and window["30窓本数"] == 6 and S.S.finite(window["R"], window["L"])
            and 0 < window["L"] < window["R"])
        if not price_ready:
            continue
        epsilon = max(5, math.ceil(.25 * f["atr"] / 5) * 5)
        for side, boundary in ((1, window["R"]), (-1, window["L"])):
            threshold = boundary + side * epsilon
            if side * (p["close"] - threshold) <= 0 < side * (f["close"] - threshold):
                row = {"位置": position, "設定足": deepcopy(f), "前足": deepcopy(p), "side": side,
                    "境界": boundary, "R": window["R"], "L": window["L"], "ε": epsilon,
                    "30窓出典": deepcopy(window), "時間可": f["confirm"] < cutoff and deadline - f["confirm"] >= 3600}
                candidates.append(row)
                by_position[position].append(row)
    episodes, used, cursor = [], set(), 0
    while cursor < len(frames):
        chosen = None
        for row in by_position[cursor]:
            if row["時間可"] and (row["side"], row["境界"]) not in used:
                chosen = row
                break
        if chosen is None:
            cursor += 1
            continue
        side = chosen["side"]
        used.add((side, chosen["境界"]))
        b = frames[cursor]
        episode = {"場": session, "開始位置": cursor, "登録候補": deepcopy(chosen),
            "内復帰位置": None, "外回復位置": None, "終了位置": len(frames) - 1,
            "終了理由": "場末尾監視終了", "訪問": []}
        anchor = b
        for position in range(cursor + 1, len(frames)):
            f = frames[position]
            inner = episode["内復帰位置"] is not None
            age, limit = f["index"] - anchor["index"], 3 if inner else 6
            valid = bool(f["publish"] and not f["missing"] and f["index"] == frames[position - 1]["index"] + 1
                and S.S.finite(f["close"]) and f["close"] > 0)
            eligible = f["end"] > anchor["confirm"] and (f["confirm"], f["confirm_line"]) > (
                anchor["confirm"], anchor["confirm_line"])
            visit = {"位置": position, "段階": "内側" if inner else "外側", "経過本数": age,
                "時点対象": eligible, "動作": "継続"}
            reason = None
            if not valid:
                reason = "公開価格連続性失効"
            elif f["confirm"] >= deadline:
                reason = "返済期限"
            elif age > limit:
                reason = "外回復三足満了" if inner else "内復帰六足満了"
            elif not eligible:
                visit["動作"] = "時点対象外"
            elif f["close"] <= chosen["L"] if side == 1 else f["close"] >= chosen["R"]:
                reason = "反対端到達"
            elif not inner and chosen["L"] < f["close"] < chosen["R"]:
                episode["内復帰位置"] = position
                anchor = f
                visit["動作"] = "内復帰価格消費"
            elif inner and side * (f["close"] - chosen["境界"]) > 0:
                episode["外回復位置"] = position
                reason = "外回復価格消費"
                visit["動作"] = reason
            if reason is not None:
                visit["動作"] = reason
            episode["訪問"].append(visit)
            if reason is not None:
                episode["終了理由"], episode["終了位置"] = reason, position
                break
        episodes.append(episode)
        cursor = episode["終了位置"] + 1
    return candidates, episodes


def source_valid(source: dict | None) -> bool:
    """凍結された登録元30窓だけの数値有効性を調べる。

    引数: source (dict|None) は固定窓。
    返り値: bool は準備済み六本かつ有限正境界か。後発窓の変化を混入させない。
    """
    return bool(source and source.get("30窓準備済") and source.get("30窓本数") == 6
        and S.S.finite(source.get("L"), source.get("R")) and 0 < source["L"] < source["R"])


def episode_seed(episode: dict, position: int, contexts: dict, number: int) -> dict:
    """独立区間経路の指定時点までの監視snapshotを作る。

    引数: episode (dict) は独立経路、position/number (int) は判断位置/診断番号、contexts (dict) は準備。
    返り値: dict は当時既知の設定だけ。将来のf/g/終了属性を入れない。
    """
    candidate = episode["登録候補"]
    setup = candidate["設定足"]
    ctx = contexts[setup["index"]]
    side = candidate["side"]
    change = ctx["MACDヒスト変化"]
    ready_old = bool(ctx["S2局面"] == "トレンド" and ctx["S2方向"] == side and change is not None and side * change > 0)
    inner = episode["内復帰位置"]
    f = episode.get("内復帰足") if inner is not None and position > inner else None
    return {"エピソードID": f"NK225_{episode['場']}_3分_設定{setup['index']:04d}_{side}",
        "段階": "外回復待ち" if f is not None else "内復帰待ち", "side": side, "境界": candidate["境界"],
        "R": candidate["R"], "L": candidate["L"], "ε": candidate["ε"],
        "30窓出典": deepcopy(candidate["30窓出典"]),
        "設定": {k: setup[k] for k in ("index", "start", "end", "confirm", "confirm_line", "close", "atr")},
        "内復帰": {k: f[k] for k in ("index", "end", "confirm", "confirm_line", "close", "atr")} if f else None,
        "登録S2理由": ctx["S2理由"], "登録旧23方向勢い資格": ready_old,
        "登録確認遅延秒": setup["confirm"] - setup["end"], "診断番号": number}


def build_contexts(frames: list[dict], regimes: list[dict], channels: list[dict], quantity: dict | None,
                   episodes: list[dict], session: str, cutoff: float, deadline: float) -> dict:
    """価格経路を先に固定し、各時点の数値準備と15分公開状態を別に付ける。

    引数: frames/regimes/channels/episodes (list[dict]) は足/局面/窓/独立経路、quantity (dict|None) は診断、
    session (str) は場、cutoff/deadline (float) は時限。
    返り値: dict は足番号別M24。下位BB/Kと最新30窓準備を既存episodeへ追加しない。
    """
    assigned, output, active_sources = B.assign_channels(frames, channels), {}, {}
    for episode in episodes:
        for position in range(episode["開始位置"] + 1, episode["終了位置"] + 1):
            active_sources[position] = episode["登録候補"]["30窓出典"]
    for position, f in enumerate(frames):
        prior = frames[position - 1] if position else None
        prior = prior if prior and prior["publish"] and f["index"] == prior["index"] + 1 and S.S.finite(prior["close"]) and prior["close"] > 0 else None
        sequential = position == 0 or f["index"] == frames[position - 1]["index"] + 1
        price_valid = bool(f["publish"] and not f["missing"] and sequential and S.S.finite(f["close"]) and f["close"] > 0)
        prior_close = bool(prior and S.S.finite(prior["close"]) and prior["close"] > 0)
        atr_valid = S.S.finite(f["atr"]) and f["atr"] > 0
        change = f["macd_hist"] - prior["macd_hist"] if prior and S.S.finite(f["macd_hist"], prior["macd_hist"]) else None
        ch, upper = assigned[f["index"]], upper_features(f, regimes)
        source = active_sources.get(position, ch["30窓参照"])
        delayed = f["confirm"] - f["end"] > 30
        reasons = []
        for condition, reason in ((not price_valid or not prior_close, "同場隣接公開価格未準備"),
            (change is None, "現在前MACD未準備"), (not atr_valid, "現在ATR未準備"),
            (not upper["ペア準備済"], "同場隣接公開15分ペア未準備"),
            (not source_valid(source), "固定登録30窓未準備"), (delayed, "足確定確認遅延30秒超")):
            if condition:
                reasons.append(reason)
        output[f["index"]] = {**deepcopy(f), **upper, **ch, "場": session, "時間足分": 3,
            "前3分参照": {k: prior.get(k) for k in ("index", "end", "confirm", "confirm_line", "close", "macd_hist")} if prior else None,
            "登録30窓参照": deepcopy(source), "固定30窓有効": source_valid(source), "MACDヒスト変化": change,
            "共通M24準備": not reasons, "共通M準備": not reasons, "M除外理由": reasons,
            "価格連続準備": price_valid and prior_close,
            "登録価格準備": price_valid and prior_close and atr_valid and source_valid(ch["30窓参照"]),
            "時間条件可": f["confirm"] < cutoff and deadline - f["confirm"] >= 3600,
            "確認遅延条件可": not delayed, "数量診断": deepcopy(quantity.get(f["index"])) if quantity is not None else None}
    return output


def decisions(context: dict, family: str, side: int) -> dict:
    """同じ価格/勢い対照にだけ上位追加を施して採否を別計算する。

    引数: context (dict) は当時準備、family (str) はR内復帰/T外回復、side (int) は実方向。
    返り値: dict はE0/E1の当時採否。ADX非上昇には横ばいを含める。
    """
    change = context["MACDヒスト変化"]
    momentum = S.S.finite(change) and side * change > 0
    reasons = list(context["M除外理由"])
    if not context["時間条件可"]:
        reasons.append("要求時間条件外")
    if not momentum:
        reasons.append("実方向MACD勢い不成立")
    trend = context["S2局面"] == "トレンド" and context["S2方向"] == side
    if trend:
        upper, upper_reason = True, "実方向S2T"
    elif family == "R内復帰" and S.S.finite(context["ADX変化"]) and context["ADX変化"] < 0:
        upper, upper_reason = True, "上位ADX弱まり"
    elif family == "R内復帰" and S.S.finite(context["ADX変化"]) and context["ADX変化"] == 0:
        upper, upper_reason = True, "上位ADX横ばい"
    else:
        upper, upper_reason = False, "上位切替対象外"
    choices = {}
    for policy in POLICIES:
        local = list(reasons)
        choices[policy] = {"採用": not local and (policy == "E0" or upper),
            "理由": (local or ["価格と実方向MACD採用"]) + ([upper_reason] if policy == "E1" else []), "同時競合": False}
    return choices


def make_signal(frame: dict, context: dict, session: str, deadline: float, family: str,
                side: int, watch: dict) -> dict:
    """最初の終値eventを、確定した役割・条件・当時snapshotへ投影する。

    引数: frame/context/watch (dict) は現在足/準備/監視、session/family (str) は場/系統、
    deadline (float) は期限、side (int) は実方向。
    返り値: dict はラベル未計算の発動。fの反転sideと元突破sideを別に保持する。
    """
    event = watch["エピソードID"] + ("_内復帰" if family == "R内復帰" else "_外回復")
    return {**deepcopy(frame), **deepcopy(context), "場": session, "時間足分": 3, "入口系統": family,
        "役割": "反転" if family == "R内復帰" else "順行", "side": side, "方向": "買い" if side == 1 else "売り",
        "発動ID": event, "QイベントID": event, "イベントID": event, "入口ID": "3分_" + family,
        "要求時計秒": frame["confirm"], "要求原板行": frame["confirm_line"], "確認遅延秒": frame["confirm"] - frame["end"],
        "足終了時計秒": frame["end"], "期限時計秒": deadline, "残り分_判断時": (deadline - frame["confirm"]) / 60,
        "先着評価対象": bool(context["時間条件可"] and context["確認遅延条件可"]),
        "戦略判定": decisions(context, family, side), "固定設定": deepcopy(watch),
        "元突破side": watch["side"], "エピソードID": watch["エピソードID"]}


def price_plan(frames: list[dict], regimes: list[dict], channels: list[dict], quantity: dict | None,
               session: str, cutoff: float, deadline: float) -> tuple[dict, dict, dict, list, list]:
    """価格区間走査の結果を全足context・全発動・全監視・診断へ独立に変換する。

    引数: frames/regimes/channels (list[dict]) は原価格足/局面/窓、quantity (dict|None) は診断、
    session (str) は場、cutoff/deadline (float) は時限。
    返り値: tuple[dict,dict,dict,list,list] はcontext/raw/cases/trace/episodes。主の逐足watchclassを使わない。
    """
    candidates, paths = structural_paths(frames, channels, session, cutoff, deadline)
    for path in paths:
        inner = path["内復帰位置"]
        path["内復帰足"] = frames[inner] if inner is not None else None
    contexts = build_contexts(frames, regimes, channels, quantity, paths, session, cutoff, deadline)
    raw, cases, trace, diagnostics = {}, {}, [], []
    before, after, events, starts, candidates_by_position, consumed_keys = {}, {}, defaultdict(list), {}, defaultdict(list), set()
    for candidate in candidates:
        candidates_by_position[candidate["位置"]].append(candidate)
    for number, path in enumerate(paths):
        begin, end = path["開始位置"], path["終了位置"]
        seed = episode_seed(path, begin, contexts, number)
        starts[begin] = seed
        after[begin] = deepcopy(seed)
        diagnostic = {"エピソードID": seed["エピソードID"], "設定": deepcopy(seed["設定"]), "side": seed["side"],
            "境界": seed["境界"], "登録旧23方向勢い資格": seed["登録旧23方向勢い資格"],
            "最初内復帰": None, "最初外回復": None, "反対端到達": None, "終了理由": path["終了理由"]}
        for visit in path["訪問"]:
            position = visit["位置"]
            f, ctx = frames[position], contexts[frames[position]["index"]]
            watch = episode_seed(path, position, contexts, number)
            before[position] = deepcopy(watch)
            action = visit["動作"]
            stop = position == end and path["終了理由"] != "場末尾監視終了"
            after[position] = None if stop else episode_seed(path, position + 1, contexts, number)
            if action == "時点対象外":
                events[position].append({"動作": "価格時点対象外", "段階": watch["段階"],
                    "理由": "end又はkeyが前段公開より後でない", "経過本数": visit["経過本数"]})
            elif action in ("内復帰価格消費", "外回復価格消費"):
                family = "R内復帰" if action == "内復帰価格消費" else "T外回復"
                side = -watch["side"] if family == "R内復帰" else watch["side"]
                row = make_signal(f, ctx, session, deadline, family, side, watch)
                raw[row["発動ID"]] = row
                events[position].append({"動作": action, "発動ID": row["発動ID"], "戦略採否": deepcopy(row["戦略判定"])})
                diagnostic["最初内復帰" if family == "R内復帰" else "最初外回復"] = {
                    k: f[k] for k in ("index", "end", "confirm", "confirm_line", "close", "atr")}
            if stop:
                reason = path["終了理由"]
                events[position].append({"動作": "監視満了" if reason.endswith("満了") else "監視終了", "理由": reason})
                diagnostic.update(終了時計秒=f["confirm"], 終了原板行=f["confirm_line"])
                if reason == "反対端到達":
                    diagnostic["反対端到達"] = {k: f[k] for k in ("index", "end", "confirm", "confirm_line", "close")}
        diagnostics.append(diagnostic)
    for position, f in enumerate(frames):
        ctx = contexts[f["index"]]
        blocked = position in before
        reasons = ["旧監視あり・同足新設定禁止"] if blocked else []
        if not ctx["登録価格準備"]:
            reasons.append("登録価格準備不可")
        if not ctx["時間条件可"]:
            reasons.append("新登録時間不可")
        for candidate in candidates_by_position[position]:
            key = candidate["side"], candidate["境界"]
            local = reasons + (["当場同方向境界使用済み"] if key in consumed_keys else [])
            events[position].append({"動作": "価格突破登録見送り" if local else "価格突破登録", "side": candidate["side"],
                "境界": candidate["境界"], "ε": candidate["ε"], "理由": local,
                "登録遅延秒": f["confirm"] - f["end"]})
            if not local:
                consumed_keys.add(key)
                break
        trace.append({"場": session, "index": f["index"], "時計秒": f["confirm"], "原板行": f["confirm_line"],
            "監視前": deepcopy(before.get(position)), "動作": events[position], "新設定除外理由": reasons,
            "監視後": deepcopy(after.get(position))})
    groups = defaultdict(list)
    for row in raw.values():
        for policy in POLICIES:
            if row["戦略判定"][policy]["採用"]:
                groups[policy, row["要求時計秒"], row["要求原板行"]].append(row)
    for (policy, _, _), rows in groups.items():
        if len(rows) > 1:
            for row in rows:
                row["戦略判定"][policy] = {"採用": False, "理由": ["同判断複数信号見送り"], "同時競合": True}
    for row in raw.values():
        for policy in POLICIES:
            if row["戦略判定"][policy]["採用"]:
                event = row["発動ID"] + "_" + policy
                cases[event] = {**deepcopy(row), "入口ID": "3分_" + policy, "戦略": policy,
                    "複合判定": deepcopy(row["戦略判定"][policy]), "イベントID": event}
    return contexts, raw, cases, trace, diagnostics


# ----------------------------------------
# 準備件数と正式全属性の比較は同じ独立経路を使い、先着・会計は呼ばない。

def stage_counts(frames: list[dict], contexts: dict, raw: dict, cases: dict,
                 trace: list[dict], episodes: list[dict], session: str, period: str) -> dict:
    """価格登録からMACD/上位採用までの全段階と理由を独立集計する。

    引数: frames/trace/episodes (list[dict]) は足/監視/診断、contexts/raw/cases (dict) は独立集合、
    session/period (str) は場/既使用区分。
    返り値: dict は源値・採否だけの件数。ラベルや売買結果を参照しない。
    """
    actions = Counter(a["動作"] for t in trace for a in t["動作"])
    stages = []
    for role in ("反転", "順行"):
        local = [r for r in raw.values() if r["役割"] == role]
        stages.append({"役割": role, "原価格イベント数": len(local),
            "時間可数": sum(r["時間条件可"] for r in local), "確認遅延可数": sum(r["確認遅延条件可"] for r in local),
            "先着評価対象数": sum(r["先着評価対象"] for r in local),
            "M時間通過数": sum(r["共通M準備"] and r["時間条件可"] for r in local),
            "勢い通過E0数": sum(r["戦略判定"]["E0"]["採用"] for r in local),
            "上位通過E1数": sum(r["戦略判定"]["E1"]["採用"] for r in local)})
    return {"場": session, "時間足分": 3, "期間": period, "足数": len(frames),
        "共通M準備足数": sum(r["共通M準備"] for r in contexts.values()), "設定数": len(episodes),
        "内復帰価格消費数": actions["内復帰価格消費"], "外回復価格消費数": actions["外回復価格消費"],
        "対象外足数": actions["価格時点対象外"], "先着評価対象外数": sum(not r["先着評価対象"] for r in raw.values()),
        "登録遅延超数": sum(e["設定"]["confirm"] - e["設定"]["end"] > 30 for e in episodes),
        "監視動作別": dict(actions), "終了理由別": dict(Counter(e["終了理由"] for e in episodes)),
        "新設定除外理由別": dict(Counter(z for t in trace for z in t["新設定除外理由"])),
        "登録候補数": actions["価格突破登録"] + actions["価格突破登録見送り"],
        "登録見送り理由別": dict(Counter(z for t in trace for a in t["動作"] if a["動作"] == "価格突破登録見送り" for z in a["理由"])),
        "イベント段階": stages, "イベントM除外理由別": dict(Counter(z for r in raw.values() for z in r["M除外理由"])),
        "戦略採否理由別": {p: dict(Counter(z for r in raw.values() for z in r["戦略判定"][p]["理由"])) for p in POLICIES},
        "戦略別役割発動数": {"3分_" + p: dict(Counter(r["役割"] for r in cases.values() if r["戦略"] == p)) for p in POLICIES},
        "戦略別発動数": {"3分_" + p: sum(r["戦略"] == p for r in cases.values()) for p in POLICIES}}


def reconstruct(manifest: dict, config: dict, audit: Any) -> Any:
    """独立価格基礎へ新M24と全内復帰/外回復を組み合わせる。

    引数: manifest/config (dict) は固定入力/条件、audit (Any) は比較記録。
    返り値: Any は全価格・監視・採用を場ごとに返すiterator。新先着/PnLの値は一切使わない。
    """
    for block in price_blocks(manifest, config, audit):
        current, raw, cases, trace, episodes = price_plan(block["価格足"][3], block["局面"], block["30窓"],
            block["数量"], block["場"], block["新規停止"], block["期限"])
        block.update(全context=current, 全raw=raw, 全採用=cases, 監視=trace, 監視終了診断=episodes)
        block["段階件数"] = stage_counts(block["価格足"][3], current, raw, cases, trace, episodes, block["場"], block["期間"])
        yield block


def prepare(study: Path, work: Path) -> dict:
    """全65場を原cacheから別計算し、主のラベルなし準備だけへ比較する。

    引数: study/work (Path) は24正式先/作業先。
    返り値: dict は準備件数/理由の明示合否と指紋。正式状態proofや会計proofの代わりにしない。
    """
    audit, config, manifest = V.Audit(), V.read(study / "条件.json"), V.read(INPUT)
    source = V.read(work / "準備点検.json")
    audit.check("主準備ラベル未計算", source["ラベル計算"], False)
    audit.check("主準備損益未計算", source["損益計算"], False)
    audit.check("主準備入力指紋", source["入力台帳SHA256"], V.sha(INPUT))
    audit.check("主準備条件指紋", source["条件SHA256"], V.sha(study / "条件.json"))
    for name, digest in source["コードSHA256"].items():
        audit.check("主準備code:" + name, digest, V.sha(ROOT / name))
    stages = {r["場"]: r for r in source["準備"]}
    channels = {r["場"]: r for r in source["30窓品質"]}
    quantities = {r["場"]: r for r in source["数量診断品質"]}
    phases, summary, rows = Counter(), Counter(), []
    for block in reconstruct(manifest, config, audit):
        session, period, counts = block["場"], block["期間"], block["段階件数"]
        audit.check(session + ":全段階件数", stages[session], counts)
        audit.check(session + ":30窓品質", {k: v for k, v in channels[session].items() if k not in ("場", "期間")}, block["30窓品質"])
        actual_quantity = {k: v for k, v in quantities[session].items() if k not in ("場", "期間")}
        expected_quantity = block["数量診断品質"]
        for key in actual_quantity.keys() | expected_quantity.keys():
            audit.check(session + ":数量品質:" + key, actual_quantity.get(key, 0), expected_quantity.get(key, 0))
        for policy in POLICIES:
            selected = [r for r in block["全採用"].values() if r["戦略"] == policy]
            row = {"場": session, "期間": period, "入口ID": "3分_" + policy, "発動数": len(selected),
                "買い発動数": sum(r["side"] == 1 for r in selected), "売り発動数": sum(r["side"] == -1 for r in selected)}
            actual = next(r for r in source["場別発動"] if r["場"] == session and r["入口ID"] == row["入口ID"])
            audit.check(session + ":採用集合件数:" + policy, actual, row)
        rows.append(counts)
        phases[period] += 1
        for key in ("設定数", "内復帰価格消費数", "外回復価格消費数", "先着評価対象外数", "登録遅延超数"):
            summary[period + ":" + key] += counts[key]
        for p, role_counts in counts["戦略別役割発動数"].items():
            for role, count in role_counts.items():
                summary[period + ":" + p + ":" + role] += count
        print(json.dumps({"場": session, "独立準備点検": "原価格/凍結窓/全f・g/理由/二集合件数のみ",
            "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("既使用65場", dict(phases), {"学習": 40, "条件選択": 24, "後続検査": 1})
    proof = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches, "不一致": audit.errors,
        "ラベル計算": False, "損益計算": False, "期間場数": dict(phases), "段階集計": dict(summary), "場別段階": rows,
        "コードSHA256": V.sha(Path(__file__)), "入力台帳SHA256": V.sha(INPUT), "条件SHA256": V.sha(study / "条件.json"),
        "主準備SHA256": V.sha(work / "準備点検.json"), "独立価格窓補助SHA256": V.sha(PRICE_HELPER),
        "検証範囲": "独立23価格/Wilder/MACD/公開窓の読取補助から全3/15/30足・15分S2・登録p時点30窓を形成。価格/ATR/時刻だけの登録候補を先列挙し、登録毎の後続区間走査から全最初f/g・優先失効・end/key対象外・6/3寿命・固定出典・使用済み境界・同足新登録禁止を別計算。M24・E0価格MACD/E1上位・全理由段階と主prepareの全65場件数を比較。新先着ラベル/新損益は読取も計算もしない。",
        "限界": "主24指標/入口/driver/運用classの自己再生ではない。保存全source/trace/eventIDの一致は正式完了後のstateproofで検査する。数量品質の省略された0カウンタは0に正規化。原板全本文や主W未使用パターンの数式再検査は対象外。"}
    (work / "独立準備点検.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: proof[k] for k in ("全件一致", "照合項目数", "不一致数", "ラベル計算", "損益計算")}, ensure_ascii=False))
    return proof


compare_row = B.compare_row


def run(study: Path, work: Path) -> dict:
    """正式完了後だけ原価格から凍結30窓・全f/g・全監視と全二集合を検算する。

    引数: study/work (Path) は24正式先/作業先。
    返り値: dict は全独立計算列・全保存監視・全集合の明示合否と指紋。先着数値と会計は別監査。
    """
    if not (study / "結果.json").exists() or not (study / "固定.json").exists():
        raise ValueError("正式結果完了通知後だけ実行します")
    audit, config, manifest = V.Audit(), V.read(study / "条件.json"), V.read(INPUT)
    pins = V.read(study / "固定.json")["ファイルSHA256"]
    for name in ("検証.py", "入口.py", "指標.py", "運用.py", "合成検証.py"):
        path = Path(__file__).with_name(name)
        audit.check("正式固定コード:" + name, V.sha(path), pins[path.relative_to(ROOT).as_posix()])
    audit.check("正式固定条件", V.sha(study / "条件.json"), pins[(study / "条件.json").relative_to(ROOT).as_posix()])
    rows_by_name, hashes = {}, {}
    for name in ("全複合context", "全局面", "上位足", "全複合shadow", "入口事例", "30分窓", "監視",
                 "全運用詳細", "追尾"):
        rows_by_name[name], hashes[name] = S.compressed_rows(work / (name + ".jsonl.gz"))
    key_functions = {
        "全複合context": lambda r: (r["場"], r["時間足分"], r["index"]),
        "全局面": lambda r: (r["場"], r["index"]),
        "上位足": lambda r: (r["場"], r["minutes"], r["index"]),
        "全複合shadow": lambda r: r["発動ID"], "入口事例": lambda r: r["イベントID"],
        "30分窓": lambda r: (r["場"], r["種別"]),
        "監視": lambda r: (r["種別"], r["場"], r["index"] if r["種別"] == "足監視" else r["エピソードID"])}
    saved, expected_ids = {}, {name: set() for name in key_functions}
    for name, key_of in key_functions.items():
        saved[name] = {key_of(r): r for r in rows_by_name[name]}
        audit.check(name + ":キー一意", len(saved[name]), len(rows_by_name[name]))
    regime_quality = {r["場"]: r for r in V.read(study / "局面品質.json")}
    entry_quality = {r["場"]: r for r in V.read(study / "入口品質.json")}
    channel_quality = {r["場"]: r for r in V.read(study / "30窓品質.json")}
    quantity_quality = {r["場"]: r for r in V.read(study / "数量診断品質.json")}
    old_proof = V.read(OLD_WORK / "状態独立確認.json")
    for name in ("30分窓", "全局面", "上位足"):
        audit.check("固定23と保存同値:" + name, hashes[name], old_proof[name + "展開SHA256"])
    label_numbers = ("新規価格", "新規時計秒", "新規原板行", "判定時計秒", "判定原板行", "判定気配",
                     "最大順行pt", "最大逆行pt", "所要分")
    phases, totals, stages, entries, raw_families = Counter(), Counter(), [], Counter(), Counter()
    for block in reconstruct(manifest, config, audit):
        session, period = block["場"], block["期間"]
        phases[period] += 1
        stage = block["段階件数"]
        stages.append(stage)
        audit.check(session + ":全段階件数", entry_quality[session], stage)
        for name, actual, expected in (("局面品質", regime_quality[session], block["局面品質"]),
                                       ("30窓品質", channel_quality[session], block["30窓品質"])):
            audit.check(session + ":" + name, {k: v for k, v in actual.items() if k not in ("場", "期間")}, expected)
        quantity_actual = {k: v for k, v in quantity_quality[session].items() if k not in ("場", "期間")}
        quantity_expected = block["数量診断品質"]
        for key in quantity_actual.keys() | quantity_expected.keys():
            audit.check(session + ":数量品質:" + key, quantity_actual.get(key, 0), quantity_expected.get(key, 0))
        expected = {
            "全複合context": [{"期間": period, **r} for r in block["全context"].values()],
            "全局面": [{"期間": period, **r} for r in block["局面"]],
            "上位足": [{"場": session, "期間": period, **r} for size in (15, 30) for r in block["価格足"][size]],
            "全複合shadow": [{"期間": period, **r} for r in block["全raw"].values()],
            "入口事例": [{"期間": period, **r} for r in block["全採用"].values()],
            "30分窓": [{"期間": period, **r} for r in block["30窓"]],
            "監視": ([{"種別": "足監視", "期間": period, **r} for r in block["監視"]] +
                [{"種別": "監視終了診断", "場": session, "期間": period, **r} for r in block["監視終了診断"]])}
        for name, local in expected.items():
            local_keys = {key_functions[name](r) for r in local}
            actual_keys = {key for key, r in saved[name].items() if r["場"] == session}
            S.compare_keys(audit, session + ":" + name + ":全集合", actual_keys, local_keys)
            expected_ids[name].update(local_keys)
            for row in local:
                key = key_functions[name](row)
                if key not in saved[name]:
                    continue
                actual = saved[name][key]
                compare_row(audit, name + ":" + str(key), actual, row)
                if name in ("全複合shadow", "入口事例"):
                    requested = row["要求時計秒"]
                    time_ok = requested < block["新規停止"] and block["期限"] - requested >= 3600
                    delay_ok = row["確認遅延秒"] <= 30
                    eligible = time_ok and delay_ok
                    audit.check(str(key) + ":先着対象は時間と遅延条件", actual["先着評価対象"], eligible)
                    if name == "入口事例":
                        audit.check(str(key) + ":全case先着対象", actual["先着評価対象"], True)
                    if not eligible:
                        audit.check(str(key) + ":対象外label", actual["ラベル"], "対象外")
                        audit.check(str(key) + ":対象外理由", actual["理由"], "要求時間条件外" if not time_ok else "足確定確認遅延30秒超")
                        for field in label_numbers:
                            audit.check(str(key) + ":対象外数値None:" + field, actual[field], None)
        for r in block["全採用"].values():
            entries[r["入口ID"]] += 1
        for r in block["全raw"].values():
            raw_families[r["入口系統"]] += 1
        for size, rows in block["価格足"].items():
            totals[str(size)] += len(rows)
        print(json.dumps({"場": session, "独立確認": "原価格・凍結窓・全f/g監視・二集合・全保存採否",
            "現時点不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("全65場", len(manifest["entries"]), 65)
    audit.check("既使用40/24/1", dict(phases), {"学習": 40, "条件選択": 24, "後続検査": 1})
    for name in key_functions:
        S.compare_keys(audit, name + ":全65合集", set(saved[name]), expected_ids[name])
    canonical = saved["全複合shadow"]
    verdict_errors = []
    for case in rows_by_name["入口事例"]:
        shadow = canonical.get(case["発動ID"])
        if shadow is None:
            verdict_errors.append(case["イベントID"])
            audit.check(case["イベントID"] + ":元canonical存在", False, True)
            continue
        audit.check(case["イベントID"] + ":全二採否canonical一致", case["戦略判定"], shadow["戦略判定"])
        audit.check(case["イベントID"] + ":自己複合判定", case["複合判定"], shadow["戦略判定"][case["戦略"]])
        if case["戦略判定"] != shadow["戦略判定"]:
            verdict_errors.append(case["イベントID"])
    proof = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches,
        "不一致": audit.errors, "表示属性注意": bool(verdict_errors), "case内canonical判定不一致数": len(verdict_errors),
        "入力場数": len(manifest["entries"]), "期間場数": dict(phases), "独立足数": dict(totals),
        "保存context数": len(rows_by_name["全複合context"]), "保存局面数": len(rows_by_name["全局面"]),
        "保存上位足数": len(rows_by_name["上位足"]), "保存発動候補数": len(rows_by_name["全複合shadow"]),
        "保存shadow数": len(rows_by_name["全複合shadow"]), "保存入口数": len(rows_by_name["入口事例"]),
        "保存30分窓数": len(rows_by_name["30分窓"]), "保存監視数": len(rows_by_name["監視"]),
        "保存運用詳細数": len(rows_by_name["全運用詳細"]), "保存追尾数": len(rows_by_name["追尾"]),
        "入口系統別raw数": dict(raw_families), "戦略別入口数": dict(entries),
        "監視段階": stages, "コードSHA256": V.sha(Path(__file__)), "入力台帳SHA256": V.sha(INPUT),
        "条件SHA256": V.sha(study / "条件.json"), "結果SHA256": V.sha(study / "結果.json"),
        "独立価格発動補助SHA256": V.sha(PRICE_HELPER), "独立数量補助SHA256": V.sha(B.QUANTITY_HELPER),
        "固定23状態proofSHA256": V.sha(OLD_WORK / "状態独立確認.json"),
        "全複合context展開SHA256": hashes["全複合context"], "全局面展開SHA256": hashes["全局面"],
        "上位足展開SHA256": hashes["上位足"], "発動候補展開SHA256": hashes["全複合shadow"],
        "全複合shadow展開SHA256": hashes["全複合shadow"], "入口事例展開SHA256": hashes["入口事例"],
        "30分窓展開SHA256": hashes["30分窓"], "監視展開SHA256": hashes["監視"],
        "全運用詳細展開SHA256": hashes["全運用詳細"], "追尾展開SHA256": hashes["追尾"],
        "検証範囲": "原cacheから全3/15/30分半開OHLC・最初確認原行・欠枠・同限月carry/reset、固定21独立MACD/BB/Stoch/Wilderを再計算。30窓は固定23独立切断位置方式、前3分p時点public-only asof/NP内部clear/持越しを再用し、30窓/15局面/上位足は固定23保存全文展開SHAとも一致比較。24の価格登録候補を先列挙し、各登録の後続区間走査で最初のstrict内復帰/外回復・end/key対象外・6/3寿命・優先失効・使用済み境界・同足禁止を別計算。元突破sideと反転side/現在ATR、登録後は凍結出典を保持してM24/E0価格MACD/E1上位非上昇又は実方向T・全理由/段階を照合。数量Q11は診断だけとして独立比較。全二採用集合とcase全二verdictcanonical一致、先着対象timeかつ遅延・二対象外理由の時間優先と9数値Noneまで検査。",
        "限界": "24主指標/入口/driver/運用をimportして自己再生しない。旧21/22/23の独立価格/局面/窓・旧14独立数量補助を読取再用する。主Wの未使用パターン診断列は数式再計算対象外。通常先着数値/新規受入/会計/一建玉/追尾は別監査。原板全本文は再抽出しない。全65場は既使用で将来収益性の証明ではない。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: proof[k] for k in ("全件一致", "照合項目数", "不一致数", "保存shadow数", "保存入口数",
        "保存30分窓数", "保存監視数", "case内canonical判定不一致数")}, ensure_ascii=False))
    return proof



def main() -> None:
    """許可済みのラベルなし準備又は正式完了後の全属性監査を開始する。

    引数: なし。--study/--work/--prepare/--実行許可を読む。
    返り値: None。無許可では実入力を開かず、不一致なら非0終了する。
    """
    parser = argparse.ArgumentParser(description="00024終値切替の独立状態確認")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--実行許可", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        proof = prepare(args.study.resolve(), args.work.resolve())
    elif args.実行許可:
        proof = run(args.study.resolve(), args.work.resolve())
    else:
        parser.error("準備点検は --prepare、正式完了通知後は --実行許可 を指定してください")
    if not proof["全件一致"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
