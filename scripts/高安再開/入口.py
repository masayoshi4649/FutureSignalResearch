"""固定30分水準の突破・再テスト・再開を公開原行順で監視する。"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import importlib.util
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("高安再開の固定22入口", ROOT/"scripts/局面変化/入口.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
OLD_CONFIG = json.loads((ROOT/"study/00022_ADXと上位BB幅の変化による局面切替/条件.json").read_text(encoding="utf-8"))
POLICIES = ("B0", "C0")
finite = BASE.finite
RULES = {"チャネル足分": 30, "チャネル本数": 6, "ε_ATR倍率": 0.25, "再テスト上限本数": 6, "再開上限本数": 3}


def validate_config(config: dict) -> None:
    """単一判断尺度・二運用・固定状態条件を検査する。

    引数: config (dict) は23条件。
    返り値: None。不一致は例外。
    """
    if config["時間足分"] != [3] or config["戦略"] != list(POLICIES) or config["価格再開"] != RULES:
        raise ValueError("固定3分・B0/C0・状態寿命だけ")
    inherited = ("対象", "全65場既使用", "運用", "必須追尾", "発動条件", "指標", "局面改訂", "逆行pt", "順行pt",
                 "残り時間下限分", "確認遅延上限秒", "入口支持", "費用支持", "目標確認率", "間引き必要件数", "分割", "出口")
    if any(config.get(key) != OLD_CONFIG.get(key) for key in inherited):
        raise ValueError("固定22から継承する数値条件と設定表示が一致しない")


def classify(higher: list[dict], session: str, config: dict) -> tuple[list[dict], dict]:
    """15分S2を固定22条件で読み取り再利用する。

    引数: higher (list[dict]) は15分足、session (str) は場、config (dict) は23条件。
    返り値: tuple[list[dict],dict] は固定22の局面と品質。
    """
    validate_config(config)
    return BASE.classify(higher, session, OLD_CONFIG)


def assign_channel(frames: list[dict], channels: list[dict]) -> dict[int, dict]:
    """bの直前公開3分pまでに存在した30分窓だけを割り当てる。

    引数: frames (list[dict]) は同場3分足、channels (list[dict]) はcarryを含む30窓snapshot。
    返り値: dict[int,dict] はb番号別の窓とp出典。未来窓へ検索し直さない。
    """
    published = [r for r in channels if r["publish"]]
    result, pointer, current, previous = {}, 0, None, None
    for frame in frames:
        prior = previous if previous is not None and previous["publish"] and frame["index"] == previous["index"]+1 else None
        if prior is not None:
            while pointer < len(published) and (published[pointer]["confirm"], published[pointer]["confirm_line"]) <= (prior["confirm"], prior["confirm_line"]) and published[pointer]["end"] <= prior["end"]:
                current = published[pointer]
                pointer += 1
        ready = bool(prior is not None and current is not None and current["30窓準備済"])
        result[frame["index"]] = {"30窓準備済": ready, "30窓参照": deepcopy(current) if prior is not None else None,
            "前3分参照": {k: prior[k] for k in ("index", "end", "confirm", "confirm_line", "close", "macd_hist")} if prior is not None else None}
        previous = frame
    return result


def width(atr: float) -> int:
    """突破時ATRだけから帯の半幅を呼値へ切り上げる。

    引数: atr (float) は有限正の突破足ATR。
    返り値: int は固定ε。後のATRで更新しない。
    """
    if not finite(atr) or atr <= 0:
        raise ValueError("突破ATRが不正")
    return max(5, math.ceil(0.25*atr/5)*5)


def trend(context: dict, side: int) -> bool:
    """当時S2が同方向の順行を許可するか調べる。

    引数: context (dict) は当時局面、side (int) は方向。
    返り値: bool は同方向Tか。未準備/WAITは反転へ置き換えない。
    """
    return context.get("S2局面") == "トレンド" and context.get("S2方向") == side


def signal(frame: dict, context: dict, session: str, deadline: float, family: str,
           side: int, event: str, verdicts: dict, setup: dict | None = None) -> dict:
    """既存ラベル/会計へ接続できる発動snapshotを作る。

    引数: frame/context (dict) は現足/準備、session/family/event (str) は場/系統/ID、
    deadline (float) は期限、side (int) は方向、verdicts (dict) は二採否、setup (dict|None) は固定設定。
    返り値: dict は将来値を含まない発動。
    """
    return {**deepcopy(frame), **deepcopy(context), "場": session, "時間足分": 3, "入口系統": family,
        "役割": "反転" if family == "R1" else "順行", "side": side, "方向": "買い" if side == 1 else "売り",
        "発動ID": event, "QイベントID": event, "イベントID": event, "入口ID": "3分_"+family,
        "要求時計秒": frame["confirm"], "要求原板行": frame["confirm_line"],
        "確認遅延秒": frame["confirm"]-frame["end"], "足終了時計秒": frame["end"],
        "期限時計秒": deadline, "残り分_判断時": (deadline-frame["confirm"])/60,
        "先着評価対象": bool(context["時間条件可"]), "戦略判定": verdicts, "固定設定": deepcopy(setup)}


def verdict(ok: bool, reason: str) -> dict:
    """採否の共通小記録を作る。

    引数: ok (bool) は可否、reason (str) は当時理由。
    返り値: dict はcanonical採否。
    """
    return {"採用": bool(ok), "理由": [reason], "同時競合": False}


# ----------------------------------------
# 価格状態は建玉とは独立に一回消費し、数量は付記するだけにする。

def generate(frames: list[dict], higher: list[dict], session: str, cutoff: float, deadline: float,
             config: dict, states: list[dict] | None = None, channels: list[dict] | None = None,
             quantity: dict | None = None) -> tuple[dict, dict]:
    """B0/C0の純入口と全監視・旧R1除外を保存する。

    引数: frames/higher (list[dict]) は3分/15分、session (str) は場、cutoff/deadline (float) は停止/返済期限、
    config (dict) は条件、states/channels (list[dict]|None) は15分類/30窓、quantity (dict|None) は診断だけの量。
    返り値: tuple[dict,dict] は二集合と全shadow/全context/状態trace/事後episode診断。
    """
    validate_config(config)
    if not frames or any(f["minutes"] != 3 for f in frames):
        raise ValueError("同場3分足が必要")
    _, old_quality = BASE.generate(frames, higher, session, cutoff, deadline, OLD_CONFIG, states)
    old_context = {r["index"]: r for r in old_quality["複合context記録"]}
    old_r = defaultdict(list)
    for row in old_quality["全Q発動記録"]:
        if row["入口系統"] == "R1":
            old_r[row["index"]].append(row)
    assigned = assign_channel(frames, channels or [])
    contexts, by_index, counts = [], {}, Counter()
    for frame in frames:
        old, ch = old_context[frame["index"]], assigned[frame["index"]]
        price_valid = finite(*(frame.get(k) for k in ("open", "high", "low", "close"))) and min(frame["open"], frame["high"], frame["low"], frame["close"]) > 0 and frame["high"] >= max(frame["open"], frame["close"]) and frame["low"] <= min(frame["open"], frame["close"])
        ready = bool(old["共通M準備"] and ch["30窓準備済"] and price_valid)
        reasons = list(old["M除外理由"])
        if not ch["30窓準備済"]:
            reasons.append("前3分時点30窓未準備")
        if not price_valid:
            reasons.append("現足OHLC不正")
        row = {**deepcopy(old), **ch, "旧M22準備": old["共通M準備"], "旧M22除外理由": old["M除外理由"],
               "共通M23準備": ready, "共通M準備": ready, "M除外理由": reasons,
               "数量診断": deepcopy(quantity.get(frame["index"])) if quantity is not None else None}
        contexts.append(row)
        by_index[frame["index"]] = row
        counts["足数"] += 1
        counts["旧M22準備足数"] += old["共通M準備"]
        counts["共通M準備足数"] += ready
    records, trace, episodes = [], [], []
    watch, previous_index, used = None, None, set()
    output = {"3分_B0": [], "3分_C0": []}
    for frame in frames:
        index, now, line = frame["index"], frame["confirm"], frame["confirm_line"]
        ctx = by_index[index]
        time_ok = now < cutoff and deadline-now >= 3600
        previous = ctx["前3分参照"]
        delta = frame["macd_hist"]-previous["macd_hist"] if previous and finite(frame.get("macd_hist"), previous.get("macd_hist")) else None
        actions, before = [], deepcopy(watch)
        blocked_registration = watch is not None
        # ----------------------------------------
        # 内側終値は監視終了までの診断だけ。取消後の未来足は追跡しない。
        live_age = index-(watch["設定"]["index"] if watch and watch["段階"] == "再テスト待ち" else watch["再テスト"]["index"] if watch else index)
        age_limit = 6 if watch and watch["段階"] == "再テスト待ち" else 3
        diagnostic_ok = bool(watch is not None and ctx["共通M準備"] and frame["publish"] and not frame["missing"]
                             and (previous_index is None or index == previous_index+1) and now < deadline and live_age <= age_limit)
        if diagnostic_ok:
            summary = episodes[watch["診断番号"]]
            observed = {"index": index, "confirm": now, "confirm_line": line, "close": frame["close"]}
            if summary["最初内側終値"] is None and watch["L"] < frame["close"] < watch["R"]:
                summary["最初内側終値"] = deepcopy(observed)
            if summary["最初境界等号"] is None and frame["close"] in (watch["L"], watch["R"]):
                summary["最初境界等号"] = deepcopy(observed)
            if summary["最初反対端到達"] is None and (frame["close"] <= watch["L"] if watch["side"] == 1 else frame["close"] >= watch["R"]):
                summary["最初反対端到達"] = deepcopy(observed)
        if watch is not None:
            side, boundary, eps = watch["side"], watch["境界"], watch["ε"]
            invalid = not frame["publish"] or bool(frame["missing"]) or previous_index is not None and index != previous_index+1 or not ctx["共通M準備"]
            reason = None
            if invalid:
                reason = "公開数値準備または連続性失効"
            elif now >= deadline:
                reason = "返済期限"
            elif watch["段階"] == "再テスト待ち" and index-watch["設定"]["index"] > 6:
                reason = "再テスト六足満了"
            elif watch["段階"] == "再開待ち" and index-watch["再テスト"]["index"] > 3:
                reason = "再開三足満了"
            elif frame["start"] > watch["設定"]["confirm"] and (frame["low"] < boundary-eps if side == 1 else frame["high"] > boundary+eps):
                reason = "固定帯を割った構造失敗"
                summary = episodes[watch["診断番号"]]
                if summary["最初帯割れ"] is None:
                    summary["最初帯割れ"] = {"index": index, "confirm": now, "confirm_line": line,
                        "high": frame["high"], "low": frame["low"], "close": frame["close"]}
            elif not trend(ctx, side):
                reason = "同方向S2T消失"
            if reason is not None:
                actions.append({"動作": "監視満了" if reason.endswith("満了") else "監視取消", "理由": reason})
                episodes[watch["診断番号"]]["終了理由"] = reason
                watch = None
            elif watch["段階"] == "再テスト待ち":
                age = index-watch["設定"]["index"]
                if frame["start"] <= watch["設定"]["confirm"]:
                    actions.append({"動作": "再テスト足対象外", "理由": "足開始が設定公開より後でない", "経過本数": age})
                else:
                    touch = boundary-eps <= (frame["low"] if side == 1 else frame["high"]) <= boundary+eps
                    recovered = side*(frame["close"]-boundary) > 0
                    if 1 <= age <= 6 and touch and recovered:
                        watch["再テスト"] = {k: frame[k] for k in ("index", "start", "end", "confirm", "confirm_line", "high", "low")}
                        watch["段階"] = "再開待ち"
                        actions.append({"動作": "再テスト登録"})
            else:
                j = watch["再テスト"]
                age = index-j["index"]
                if frame["start"] <= j["confirm"]:
                    actions.append({"動作": "再開足対象外", "理由": "足開始が再テスト公開より後でない", "経過本数": age})
                elif (frame["close"] > j["high"] if side == 1 else frame["close"] < j["low"]):
                    momentum = delta is not None and side*delta > 0
                    ok = momentum and time_ok
                    event = watch["エピソードID"]+"_再開"
                    records.append(signal(frame, ctx, session, deadline, "T再開", side, event,
                        {"B0": verdict(False, "B0は突破時だけ"), "C0": verdict(ok, "再開採用" if ok else "再開価格消費・勢いまたは時間不可")}, watch))
                    actions.append({"動作": "再開価格消費", "採用条件可": ok, "勢い可": momentum, "時間可": time_ok})
                    episodes[watch["診断番号"]]["終了理由"] = "再開価格消費"
                    watch = None
        # ----------------------------------------
        # Rへの局面変化で旧Tが消えても、R1自体の受付は当足で可能。
        for original in old_r[index]:
            ok = bool(ctx["共通M準備"] and ctx["S2局面"] == "レンジ" and time_ok)
            row = signal(frame, ctx, session, deadline, "R1", original["side"], original["発動ID"],
                         {p: verdict(ok, "固定R1採用" if ok else "R1共通準備または局面対象外") for p in POLICIES})
            row["旧22R1"] = deepcopy(original)
            records.append(row)
        setup_reasons = []
        if blocked_registration:
            setup_reasons.append("旧監視あり・同足新設定禁止")
        if not ctx["共通M準備"]:
            setup_reasons.append("共通M23未準備")
        if not time_ok:
            setup_reasons.append("新登録時間不可")
        if not setup_reasons:
            ch = ctx["30窓参照"]
            eps = width(frame["atr"])
            for side, boundary in ((1, ch["R"]), (-1, ch["L"])):
                level = boundary+side*eps
                crossed = side*(previous["close"]-level) <= 0 < side*(frame["close"]-level)
                if not crossed:
                    continue
                key = side, boundary
                if not trend(ctx, side) or delta is None or side*delta <= 0 or key in used:
                    actions.append({"動作": "突破登録見送り", "side": side, "境界": boundary,
                                    "S2可": trend(ctx, side), "勢い可": delta is not None and side*delta > 0, "使用済み": key in used})
                    continue
                used.add(key)
                episode = f"NK225_{session}_3分_設定{index:04d}_{side}"
                setup = {k: frame[k] for k in ("index", "start", "end", "confirm", "confirm_line", "high", "low", "atr")}
                watch = {"エピソードID": episode, "段階": "再テスト待ち", "side": side, "境界": boundary,
                         "R": ch["R"], "L": ch["L"], "ε": eps, "30窓出典": deepcopy(ch),
                         "設定": setup, "登録S2理由": ctx["S2理由"], "再テスト": None, "診断番号": len(episodes)}
                episodes.append({"エピソードID": episode, "設定": deepcopy(setup), "side": side, "境界": boundary,
                                 "最初帯割れ": None, "最初内側終値": None, "最初境界等号": None,
                                 "最初反対端到達": None, "終了理由": None})
                records.append(signal(frame, ctx, session, deadline, "T突破", side, episode+"_突破",
                                      {"B0": verdict(True, "突破即時採用"), "C0": verdict(False, "再テスト待ち")}, watch))
                actions.append({"動作": "突破設定登録", "エピソードID": episode})
                break
        trace.append({"場": session, "index": index, "時計秒": now, "原板行": line, "監視前": before,
                      "動作": actions, "新設定除外理由": setup_reasons, "監視後": deepcopy(watch)})
        previous_index = index
    if watch is not None:
        episodes[watch["診断番号"]]["終了理由"] = "場末尾監視終了"
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
        if len(rows) != 1:
            continue
        row = rows[0]
        source = "3分_"+p
        output[source].append({**deepcopy(row), "入口ID": source, "戦略": p,
                              "複合判定": deepcopy(row["戦略判定"][p]), "イベントID": row["発動ID"]+"_"+p})
    actions = Counter(a["動作"] for r in trace for a in r["動作"])
    end_reasons = Counter(r["終了理由"] for r in episodes)
    counts.update(再テスト登録数=actions["再テスト登録"], 再開価格消費数=actions["再開価格消費"],
                  再開条件採用数=sum(a.get("採用条件可", False) for r in trace for a in r["動作"] if a["動作"] == "再開価格消費"),
                  再開採用数=sum(r["入口系統"] == "T再開" for r in output["3分_C0"]),
                  再テスト対象外足数=actions["再テスト足対象外"], 再開対象外足数=actions["再開足対象外"],
                  対象外足数=actions["再テスト足対象外"]+actions["再開足対象外"],
                  先着評価対象外数=sum(not r["先着評価対象"] for r in records))
    return output, {"場": session, "時間足分": 3, **dict(counts), "全Q発動記録": records,
                    "複合context記録": contexts, "監視trace": trace, "エピソード診断": episodes,
                    "旧R1発動数": sum(len(v) for v in old_r.values()), "設定数": len(episodes),
                    "監視動作別": dict(actions), "終了理由別": dict(end_reasons),
                    "新設定除外理由別": dict(Counter(reason for row in trace for reason in row["新設定除外理由"])),
                    "戦略別発動数": {k: len(v) for k, v in output.items()}}
