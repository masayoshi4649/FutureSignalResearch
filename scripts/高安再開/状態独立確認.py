"""00023の公開30分窓と突破・再テスト・再開を原価格から別に列挙する。"""

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
STUDY = ROOT / "study/00023_上位高安の再テストと順行再開"
WORK = ROOT / "work/高安再開/00023"
INPUT = ROOT / "study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
PRICE_HELPER = ROOT / "scripts/局面変化/状態独立確認.py"
QUANTITY_HELPER = ROOT / "scripts/数量反転/数量独立確認.py"
OLD_WORK = ROOT / "work/局面変化/00022"
POLICIES = ("B0", "C0")


def helper(path: Path, name: str) -> Any:
    """固定した独立価格/数量計算だけを読み込む。

    引数: path (Path) は補助、name (str) はモジュール識別名。
    返り値: Any は補助。23主stateや元の指標classを再実行しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


P = helper(PRICE_HELPER, "高安再開の独立価格とS2")
Q = helper(QUANTITY_HELPER, "高安再開の独立数量診断")
S, V, Indicators = P.S, P.V, P.Indicators
SOURCE_FIELDS = ("index", "minutes", "start", "end", "confirm", "confirm_line", "publish", "missing",
    "open", "high", "low", "close")


class ChannelHistory:
    """直近の切断位置から過去公開足を再列挙する独立30分窓。"""

    def __init__(self) -> None:
        """空のcarry候補と未確定限月を作る。

        引数: なし。
        返り値: None。指標bankと別に公開窓だけを保持する。
        """
        self.carry, self.contract = [], None

    def snapshot(self, session: str, sources: list[dict], key: tuple, end: float,
                 published: bool, reasons: list[str], kind: str) -> dict:
        """再列挙した高安窓を不変出典へ変換する。

        引数: session/kind (str) は場/種別、sources (list[dict]) は過去公開足、key (tuple) は公開キー、
        end (float) は終了、published (bool) はasof対象、reasons (list[str]) は切断理由。
        返り値: dict は窓とR/L。未準備で価格を補わない。
        """
        upper = max((f["high"] for f in sources), default=None)
        lower = min((f["low"] for f in sources), default=None)
        ready = bool(len(sources) == 6 and upper > lower)
        return {"場": session, "種別": kind, "参照ID": f"NK225_{session}_30窓_{kind}_{key[0]}_{key[1]}",
            "confirm": key[0], "confirm_line": key[1], "end": end, "publish": published,
            "30窓準備済": ready, "30窓本数": len(sources), "R": upper if ready else None,
            "L": lower if ready else None, "30足出典": deepcopy(sources), "窓解除理由": list(reasons)}

    def build(self, frames: list[dict], session: str, contract: tuple, tail_missing: int = 0) -> tuple[list[dict], dict]:
        """各時点までの最後の切断位置から六本を取り直して窓を作る。

        引数: frames (list[dict]) は独立完全幅30分足、session (str) は場、contract (tuple) は限月、
        tail_missing (int) は末尾完全幅欠枠数。
        返り値: tuple[list[dict],dict] は公開/非公開snapshotと品質。NPはcarryを切り過去snapshotを変えない。
        """
        initial_reasons = []
        if self.contract is not None and contract != self.contract:
            self.carry = []
            initial_reasons.append("限月変更")
        self.contract = contract
        seed = deepcopy(self.carry)
        last = seed[-1] if seed else None
        rows = [self.snapshot(session, seed, (last["confirm"], last["confirm_line"]) if last else (-1.0, 0),
            last["end"] if last else -1.0, True, initial_reasons, "場開始carry")]
        controls, source_rows, clear_count = [], [], int(bool(initial_reasons))
        final_window = seed
        for position, f in enumerate(frames):
            reasons = []
            index_gap = f["index"] != 0 if position == 0 else f["index"] != frames[position - 1]["index"] + 1
            if index_gap:
                reasons.append("30分番号欠枠")
            if f["missing"]:
                reasons.append("30分欠枠")
            if not f["publish"]:
                reasons.append("非公開完全30足")
            valid = S.S.finite(f["high"], f["low"]) and min(f["high"], f["low"]) > 0 and f["high"] >= f["low"]
            if not valid:
                reasons.append("30分高安不正")
            keep = bool(valid and f["publish"])
            source_rows.append({"場": session, **{k: f[k] for k in SOURCE_FIELDS}})
            controls.append((bool(reasons), keep))
            if reasons:
                clear_count += 1
            cuts = [n for n in range(position + 1) if controls[n][0]]
            boundary = cuts[-1] if cuts else None
            local_start = boundary if boundary is not None and controls[boundary][1] else (
                boundary + 1 if boundary is not None else 0)
            candidates = ([] if boundary is not None else seed) + [
                source_rows[n] for n in range(local_start, position + 1) if controls[n][1]]
            final_window = candidates[-6:]
            rows.append(self.snapshot(session, final_window, (f["confirm"], f["confirm_line"]), f["end"],
                f["publish"], reasons, str(f["index"])))
        self.carry = [] if tail_missing else deepcopy(final_window)
        if tail_missing:
            clear_count += 1
        return rows, {"30足数": len(frames), "30窓準備snapshot数": sum(r["30窓準備済"] for r in rows),
            "30窓clear数": clear_count, "30尾部欠枠": tail_missing}


# ----------------------------------------
# 前3分の既知窓だけを用い、旧M22から新価格監視の準備を作る。

def assign_channels(frames: list[dict], channels: list[dict]) -> dict[int, dict]:
    """b自身ではなく直前の公開3分pまでに存在した最後の公開窓を選ぶ。

    引数: frames (list[dict]) は独立3分足、channels (list[dict]) は独立30分snapshot。
    返り値: dict[int,dict] は前3分出典と窓。現在bで新公開した30分足を混ぜない。
    """
    result = {}
    for position, f in enumerate(frames):
        p = frames[position - 1] if position else None
        p = p if p is not None and p["publish"] and f["index"] == p["index"] + 1 else None
        rows = [r for r in channels if p is not None and r["publish"] and r["end"] <= p["end"] and
                (r["confirm"], r["confirm_line"]) <= (p["confirm"], p["confirm_line"])]
        current = rows[-1] if rows else None
        result[f["index"]] = {"30窓準備済": bool(p is not None and current and current["30窓準備済"]),
            "30窓参照": deepcopy(current), "前3分参照": {k: p[k] for k in
                ("index", "end", "confirm", "confirm_line", "close", "macd_hist")} if p is not None else None}
    return result


def contexts(frames: list[dict], prior: dict, channels: list[dict], quantities: dict | None, session: str) -> dict:
    """旧22の数値/公開準備へ30分窓と基本OHLC整合だけを追加する。

    引数: frames (list[dict]) は独立3分足、prior (dict) は旧22context、channels (list[dict]) は独立窓、
    quantities (dict|None) は独立数量診断、session (str) は場。
    返り値: dict は全M23。数量を0/欠測へ変えても準備と価格発動を変えない。
    """
    assigned, output = assign_channels(frames, channels), {}
    for f in frames:
        old, ch = prior[f["index"]], assigned[f["index"]]
        price = S.S.finite(*(f[k] for k in ("open", "high", "low", "close"))) and min(
            f[k] for k in ("open", "high", "low", "close")) > 0 and f["high"] >= max(f["open"], f["close"]) and f["low"] <= min(f["open"], f["close"])
        reasons = list(old["M除外理由"])
        if not ch["30窓準備済"]:
            reasons.append("前3分時点30窓未準備")
        if not price:
            reasons.append("現足OHLC不正")
        ready = bool(old["共通M準備"] and ch["30窓準備済"] and price)
        output[f["index"]] = {"場": session, "時間足分": 3, **f, **deepcopy(old), **ch,
            "旧M22準備": old["共通M準備"], "旧M22除外理由": deepcopy(old["M除外理由"]),
            "共通M23準備": ready, "共通M準備": ready, "M除外理由": reasons,
            "数量診断": deepcopy(quantities.get(f["index"])) if quantities is not None else None}
    return output


def verdict(ok: bool, reason: str) -> dict:
    """独立した採否の小記録を作る。

    引数: ok (bool) は採否、reason (str) は理由。
    返り値: dict はcanonicalの採否/理由/競合初期値。
    """
    return {"採用": bool(ok), "理由": [reason], "同時競合": False}


def make_signal(frame: dict, context: dict, session: str, deadline: float, family: str,
                side: int, identity: str, decisions: dict, setup: dict | None = None) -> dict:
    """独立に確認した現在足と固定設定だけから新しい発動snapshotを作る。

    引数: frame/context (dict) は現在足/準備、session/family/identity (str) は場/系統/ID、
    deadline (float) は期限、side (int) は方向、decisions (dict) は採否、setup (dict|None) は監視。
    返り値: dict は将来ラベルなしの発動。
    """
    return {**deepcopy(frame), **deepcopy(context), "場": session, "時間足分": 3, "入口系統": family,
        "役割": "反転" if family == "R1" else "順行", "side": side, "方向": "買い" if side == 1 else "売り",
        "発動ID": identity, "QイベントID": identity, "イベントID": identity, "入口ID": "3分_" + family,
        "要求時計秒": frame["confirm"], "要求原板行": frame["confirm_line"],
        "確認遅延秒": frame["confirm"] - frame["end"], "足終了時計秒": frame["end"], "期限時計秒": deadline,
        "残り分_判断時": (deadline - frame["confirm"]) / 60,
        "先着評価対象": bool(context["時間条件可"]), "戦略判定": decisions, "固定設定": deepcopy(setup)}


# ----------------------------------------
# 設定を一つ見つけたら後続区間を最後まで走査し、終了足の次から新設定探索へ戻る。

def price_plan(frames: list[dict], context_by_index: dict, old_r: dict[str, dict],
               session: str, cutoff: float, deadline: float) -> tuple[dict, dict, list, list]:
    """全R1と独立episode区間走査からB0/C0の全発動/全監視を列挙する。

    引数: frames (list[dict]) は独立3分足、context_by_index (dict) はM23、old_r (dict) は独立旧22R1、
    session (str) は場、cutoff/deadline (float) は新規停止/期限。
    返り値: tuple[dict,dict,list,list] はraw/採用case/全足trace/episode診断。主の逐足watchを呼ばない。
    """
    raw, cases, episodes, used = {}, {}, [], set()
    trace = [{"場": session, "index": f["index"], "時計秒": f["confirm"], "原板行": f["confirm_line"],
        "監視前": None, "動作": [], "新設定除外理由": [], "監視後": None} for f in frames]

    def permitted(f: dict) -> bool:
        """現在の要求時刻だけで新規時間条件を調べる。

        引数: f (dict) は現在足。
        返り値: bool は停止前かつ期限残60分以上か。
        """
        return bool(f["confirm"] < cutoff and deadline - f["confirm"] >= 3600)

    def same_trend(ctx: dict, side: int) -> bool:
        """当時のS2が固定した方向を維持するか判定する。

        引数: ctx (dict) は現在準備、side (int) は設定方向。
        返り値: bool は同方向Tか。WAITを反転へ置き換えない。
        """
        return ctx["S2局面"] == "トレンド" and ctx["S2方向"] == side

    def momentum(f: dict) -> float | None:
        """前3分pと現在bのH差だけを計算する。

        引数: f (dict) は現在足。
        返り値: float|None はH一差。有限性と方向化を分離する。
        """
        previous = context_by_index[f["index"]]["前3分参照"]
        return f["macd_hist"] - previous["macd_hist"] if previous is not None and S.S.finite(
            f["macd_hist"], previous["macd_hist"]) else None

    def registration_reasons(position: int, blocked: bool) -> list[str]:
        """現在足のT新登録に限った除外理由を作る。

        引数: position (int) は足位置、blocked (bool) は旧監視がこの足の入口に存在したか。
        返り値: list[str] は固定順の理由。R1受付をこの理由で止めない。
        """
        reasons = ["旧監視あり・同足新設定禁止"] if blocked else []
        f = frames[position]
        if not context_by_index[f["index"]]["共通M準備"]:
            reasons.append("共通M23未準備")
        if not permitted(f):
            reasons.append("新登録時間不可")
        return reasons

    def scan_episode(begin: int, seed: dict, summary: dict) -> int:
        """固定された設定の次足から、初eligible再開または優先失効まで区間走査する。

        引数: begin (int) は設定足位置、seed (dict) は固定設定、summary (dict) は診断更新先。
        返り値: int は終了足位置。末尾存続時も最後の足を返しtraceへ未来値を入れない。
        """
        j = None
        for position in range(begin + 1, len(frames)):
            f, t = frames[position], trace[position]
            ctx = context_by_index[f["index"]]
            watch = {**deepcopy(seed), "段階": "再テスト待ち" if j is None else "再開待ち", "再テスト": deepcopy(j)}
            t["監視前"] = deepcopy(watch)
            t["新設定除外理由"] = registration_reasons(position, True)
            age = f["index"] - (seed["設定"]["index"] if j is None else j["index"])
            limit = 6 if j is None else 3
            invalid = (not f["publish"] or bool(f["missing"]) or
                f["index"] != frames[position - 1]["index"] + 1 or not ctx["共通M準備"])
            reason = ("公開数値準備または連続性失効" if invalid else "返済期限" if f["confirm"] >= deadline else
                ("再テスト六足満了" if j is None else "再開三足満了") if age > limit else None)
            if reason is None:
                observed = {k: f[k] for k in ("index", "confirm", "confirm_line", "close")}
                checks = {"最初内側終値": seed["L"] < f["close"] < seed["R"],
                    "最初境界等号": f["close"] in (seed["L"], seed["R"]),
                    "最初反対端到達": f["close"] <= seed["L"] if seed["side"] == 1 else f["close"] >= seed["R"]}
                for field, found in checks.items():
                    if found and summary[field] is None:
                        summary[field] = deepcopy(observed)
                broken = f["start"] > seed["設定"]["confirm"] and (
                    f["low"] < seed["境界"] - seed["ε"] if seed["side"] == 1 else f["high"] > seed["境界"] + seed["ε"])
                if broken:
                    reason = "固定帯を割った構造失敗"
                    summary["最初帯割れ"] = {k: f[k] for k in ("index", "confirm", "confirm_line", "high", "low", "close")}
                elif not same_trend(ctx, seed["side"]):
                    reason = "同方向S2T消失"
            if reason is not None:
                t["動作"].append({"動作": "監視満了" if reason.endswith("満了") else "監視取消", "理由": reason})
                summary["終了理由"] = reason
                return position
            if j is None:
                if f["start"] <= seed["設定"]["confirm"]:
                    t["動作"].append({"動作": "再テスト足対象外", "理由": "足開始が設定公開より後でない", "経過本数": age})
                else:
                    edge = f["low"] if seed["side"] == 1 else f["high"]
                    if 1 <= age <= 6 and seed["境界"] - seed["ε"] <= edge <= seed["境界"] + seed["ε"] and seed["side"] * (f["close"] - seed["境界"]) > 0:
                        j = {k: f[k] for k in ("index", "start", "end", "confirm", "confirm_line", "high", "low")}
                        t["動作"].append({"動作": "再テスト登録"})
            else:
                if f["start"] <= j["confirm"]:
                    t["動作"].append({"動作": "再開足対象外", "理由": "足開始が再テスト公開より後でない", "経過本数": age})
                elif (f["close"] > j["high"] if seed["side"] == 1 else f["close"] < j["low"]):
                    delta = momentum(f)
                    strong = delta is not None and seed["side"] * delta > 0
                    ok = bool(strong and permitted(f))
                    identity = seed["エピソードID"] + "_再開"
                    raw[identity] = make_signal(f, ctx, session, deadline, "T再開", seed["side"], identity,
                        {"B0": verdict(False, "B0は突破時だけ"),
                         "C0": verdict(ok, "再開採用" if ok else "再開価格消費・勢いまたは時間不可")}, watch)
                    t["動作"].append({"動作": "再開価格消費", "採用条件可": ok, "勢い可": bool(strong), "時間可": permitted(f)})
                    summary["終了理由"] = "再開価格消費"
                    return position
            t["監視後"] = {**deepcopy(seed), "段階": "再テスト待ち" if j is None else "再開待ち", "再テスト": deepcopy(j)}
        summary["終了理由"] = "場末尾監視終了"
        return len(frames) - 1

    # R1は監視の終了理由や保有とは独立に、全旧発動を先に保存する。
    frame_map = {f["index"]: f for f in frames}
    for key, original in old_r.items():
        f, ctx = frame_map[original["index"]], context_by_index[original["index"]]
        ok = bool(ctx["共通M準備"] and ctx["S2局面"] == "レンジ" and permitted(f))
        raw[key] = make_signal(f, ctx, session, deadline, "R1", original["side"], key,
            {p: verdict(ok, "固定R1採用" if ok else "R1共通準備または局面対象外") for p in POLICIES})
        raw[key]["旧22R1"] = {k: deepcopy(v) for k, v in original.items() if k != "期間"}
    cursor = 0
    while cursor < len(frames):
        f, t = frames[cursor], trace[cursor]
        ctx = context_by_index[f["index"]]
        t["新設定除外理由"] = registration_reasons(cursor, False)
        registered = False
        if not t["新設定除外理由"]:
            previous, channel = ctx["前3分参照"], ctx["30窓参照"]
            epsilon = max(5, math.ceil(.25 * f["atr"] / 5) * 5)
            delta = momentum(f)
            for side, boundary in ((1, channel["R"]), (-1, channel["L"])):
                threshold = boundary + side * epsilon
                crossed = side * (previous["close"] - threshold) <= 0 < side * (f["close"] - threshold)
                if not crossed:
                    continue
                strong = delta is not None and side * delta > 0
                if not same_trend(ctx, side) or not strong or (side, boundary) in used:
                    t["動作"].append({"動作": "突破登録見送り", "side": side, "境界": boundary,
                        "S2可": same_trend(ctx, side), "勢い可": bool(strong), "使用済み": (side, boundary) in used})
                    continue
                used.add((side, boundary))
                identity = f"NK225_{session}_3分_設定{f['index']:04d}_{side}"
                setup = {k: f[k] for k in ("index", "start", "end", "confirm", "confirm_line", "high", "low", "atr")}
                watch = {"エピソードID": identity, "段階": "再テスト待ち", "side": side, "境界": boundary,
                    "R": channel["R"], "L": channel["L"], "ε": epsilon, "30窓出典": deepcopy(channel), "設定": setup,
                    "登録S2理由": ctx["S2理由"], "再テスト": None, "診断番号": len(episodes)}
                summary = {"エピソードID": identity, "設定": deepcopy(setup), "side": side, "境界": boundary,
                    "最初帯割れ": None, "最初内側終値": None, "最初境界等号": None, "最初反対端到達": None, "終了理由": None}
                episodes.append(summary)
                raw[identity + "_突破"] = make_signal(f, ctx, session, deadline, "T突破", side, identity + "_突破",
                    {"B0": verdict(True, "突破即時採用"), "C0": verdict(False, "再テスト待ち")}, watch)
                t["動作"].append({"動作": "突破設定登録", "エピソードID": identity})
                t["監視後"] = deepcopy(watch)
                cursor = scan_episode(cursor, watch, summary) + 1
                registered = True
                break
        if not registered:
            cursor += 1
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
        for policy, choice in row["戦略判定"].items():
            if choice["採用"]:
                identity = row["発動ID"] + "_" + policy
                cases[identity] = {**deepcopy(row), "入口ID": "3分_" + policy, "戦略": policy,
                    "複合判定": deepcopy(choice), "イベントID": identity}
    return raw, cases, trace, episodes


# ----------------------------------------
# 原cacheを一回ずつ読み、旧価格発動・新窓・全監視を別に再構成する。

def stage_counts(frames: list[dict], prior: dict, current: dict, old_r: dict, raw: dict,
                 cases: dict, trace: list[dict], episodes: list[dict], session: str, period: str) -> dict:
    """独立した足/全監視から保存される段階別件数を集計する。

    引数: frames/trace/episodes (list[dict]) は足/原順監視/診断、prior/current/old_r/raw/cases (dict) は各集合、
    session/period (str) は場/既使用区分。
    返り値: dict は準備・設定・再テスト・消費・採用・除外の件数。損益や先着は算出しない。
    """
    actions = Counter(a["動作"] for row in trace for a in row["動作"])
    return {"場": session, "時間足分": 3, "期間": period, "足数": len(frames),
        "旧M22準備足数": sum(r["共通M準備"] for r in prior.values()),
        "共通M準備足数": sum(r["共通M準備"] for r in current.values()),
        "旧R1発動数": len(old_r), "設定数": len(episodes), "再テスト登録数": actions["再テスト登録"],
        "再開価格消費数": actions["再開価格消費"],
        "再開条件採用数": sum(a["採用条件可"] for row in trace for a in row["動作"] if a["動作"] == "再開価格消費"),
        "再開採用数": sum(r["入口系統"] == "T再開" and r["戦略"] == "C0" for r in cases.values()),
        "再テスト対象外足数": actions["再テスト足対象外"], "再開対象外足数": actions["再開足対象外"],
        "対象外足数": actions["再テスト足対象外"] + actions["再開足対象外"],
        "先着評価対象外数": sum(not r["先着評価対象"] for r in raw.values()),
        "監視動作別": dict(actions), "終了理由別": dict(Counter(r["終了理由"] for r in episodes)),
        "新設定除外理由別": dict(Counter(reason for row in trace for reason in row["新設定除外理由"])),
        "戦略別発動数": {"3分_" + p: sum(r["戦略"] == p for r in cases.values()) for p in POLICIES}}


def reconstruct(manifest: dict, config: dict, audit: Any) -> Any:
    """同限月指標carryと独立30窓から全65場を順に再構成する。

    引数: manifest/config (dict) は固定入力/数値条件、audit (Any) は独立比較記録。
    返り値: Any は場ごとの独立価格/数量/局面/窓/全発動/全監視を渡すiterator。新ラベルや会計を呼ばない。
    """
    banks, contract, channel_history = {n: Indicators() for n in (3, 15)}, None, ChannelHistory()
    old_proof = V.read(OLD_WORK / "状態独立確認.json")
    audit.check("固定22状態独立成功", old_proof["全件一致"], True)
    audit.check("固定22独立code指紋", old_proof["コードSHA256"], V.sha(PRICE_HELPER))
    old_saved, old_sha = S.compressed_rows(OLD_WORK / "全複合shadow.jsonl.gz")
    audit.check("固定22canonical展開指紋", old_sha, old_proof["全複合shadow展開SHA256"])
    canonical = {r["発動ID"]: r for r in old_saved if r["時間足分"] == 3 and r["入口系統"] == "R1"}
    all_old = set()
    for entry in manifest["entries"]:
        session, codes = entry["session"], tuple(entry["in_session_contract_codes"])
        if len(codes) != 1:
            raise ValueError("固定限月が一意でない")
        if contract is not None and codes != contract:
            banks = {n: Indicators() for n in banks}
        contract = codes
        period = "後続検査" if session[:10] >= config["分割"]["後続開始日"] else (
            "条件選択" if session[:10] >= config["分割"]["選択開始日"] else "学習")
        data = Q.observed(entry, Path(manifest["source_root"]))
        frames = {n: S.S.bars(data, session, n, bank) for n, bank in banks.items()}
        full30 = S.S.bars(data, session, 30, Indicators())
        frames[30] = [{k: f[k] for k in SOURCE_FIELDS} for f in full30]
        start, finish, cutoff, deadline = S.S.G.times(session)
        tail30 = max(0, int((finish - start) // 1800) - 1 - (frames[30][-1]["index"] if frames[30] else -1))
        channels, channel_quality = channel_history.build(frames[30], session, codes, tail30)
        quantities, quantity_quality = Q.independent_quantity(data, frames[3], start, finish, 3)
        states, regime_quality = P.pair_states(frames[15], session)
        old21, old22 = P.contexts(frames[3], frames[15], states, cutoff, deadline)
        raw21, _ = P.P.generate(frames[3], old21, session, period, deadline)
        raw22, _ = P.select(raw21, old22)
        old_r = {key: r for key, r in raw22.items() if r["入口系統"] == "R1"}
        saved_ids = {key for key, r in canonical.items() if r["場"] == session}
        S.compare_keys(audit, session + ":固定22全3分R1保持", set(old_r), saved_ids)
        for key in old_r.keys() & canonical.keys():
            P.P.compare_fields(audit, key + ":固定22canonical源値", canonical[key], old_r[key])
        all_old.update(old_r)
        current = contexts(frames[3], old22, channels, quantities, session)
        raw, cases, trace, episodes = price_plan(frames[3], current, old_r, session, cutoff, deadline)
        counts = stage_counts(frames[3], old22, current, old_r, raw, cases, trace, episodes, session, period)
        yield {"場": session, "期間": period, "価格足": frames, "旧R1": old_r, "全raw": raw, "全採用": cases,
            "全context": current, "局面": states, "局面品質": regime_quality, "30窓": channels,
            "30窓品質": channel_quality, "数量診断品質": quantity_quality, "監視": trace,
            "監視終了診断": episodes, "段階件数": counts, "期限": deadline, "新規停止": cutoff}
    S.compare_keys(audit, "固定22全3分R1全集合", all_old, set(canonical))


def prepare(study: Path, work: Path) -> dict:
    """新先着/新損益を開かず原cacheから準備と全発動件数だけを独立検算する。

    引数: study/work (Path) は23正式先/作業先。
    返り値: dict は準備点検の明示合否/件数/出典。正式状態・会計proofの代わりにしない。
    """
    audit, config, manifest = V.Audit(), V.read(study / "条件.json"), V.read(INPUT)
    source = V.read(work / "準備点検.json")
    audit.check("主準備でラベル未計算", source["ラベル計算"], False)
    audit.check("主準備で損益未計算", source["損益計算"], False)
    audit.check("準備入力指紋", source["入力台帳SHA256"], V.sha(INPUT))
    audit.check("準備条件指紋", source["条件SHA256"], V.sha(study / "条件.json"))
    for name, digest in source["コードSHA256"].items():
        audit.check("主準備code:" + name, digest, V.sha(ROOT / name))
    stages = {r["場"]: r for r in source["準備"]}
    channels = {r["場"]: r for r in source["30窓品質"]}
    quantities = {r["場"]: r for r in source["数量診断品質"]}
    summary, phases, rows = Counter(), Counter(), []
    for block in reconstruct(manifest, config, audit):
        session, period = block["場"], block["期間"]
        audit.check(session + ":全段階件数", stages[session], block["段階件数"])
        audit.check(session + ":30窓品質",
            {k: v for k, v in channels[session].items() if k not in ("場", "期間")}, block["30窓品質"])
        quantity_actual = {k: v for k, v in quantities[session].items() if k not in ("場", "期間")}
        quantity_expected = block["数量診断品質"]
        for key in quantity_actual.keys() | quantity_expected.keys():
            audit.check(session + ":数量品質:" + key, quantity_actual.get(key, 0), quantity_expected.get(key, 0))
        for policy in POLICIES:
            selected = [r for r in block["全採用"].values() if r["戦略"] == policy]
            row = {"場": session, "期間": period, "入口ID": "3分_" + policy, "発動数": len(selected),
                "買い発動数": sum(r["side"] == 1 for r in selected), "売り発動数": sum(r["side"] == -1 for r in selected)}
            actual = next(r for r in source["場別発動"] if r["場"] == session and r["入口ID"] == row["入口ID"])
            audit.check(session + ":採用集合件数:" + policy, actual, row)
        counts = block["段階件数"]
        rows.append(counts)
        phases[period] += 1
        for name in ("設定数", "再テスト登録数", "再開価格消費数", "再開条件採用数", "再開採用数", "先着評価対象外数"):
            summary[period + ":" + name] += counts[name]
        print(json.dumps({"場": session, "独立準備点検": "価格指標/30窓/全R1/監視/二集合件数のみ",
            "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("既使用65場", dict(phases), {"学習": 40, "条件選択": 24, "後続検査": 1})
    result = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches,
        "不一致": audit.errors, "ラベル計算": False, "損益計算": False, "期間場数": dict(phases),
        "段階集計": dict(summary), "場別段階": rows, "コードSHA256": V.sha(Path(__file__)),
        "入力台帳SHA256": V.sha(INPUT), "条件SHA256": V.sha(study / "条件.json"),
        "主準備SHA256": V.sha(work / "準備点検.json"),
        "検証範囲": "原cacheから3/15/30価格足・既検証独立MACD/BB/Stoch/Wilderを形成。固定22canonical3分R1と全文計算列を照合し、新30窓は最終切断位置から六本を再列挙、Tは設定毎の区間走査で全監視を独立列挙。主準備の全65場段階件数・二採用集合件数・30窓/数量品質と比較。新ラベル・新損益を計算も読取もしない。",
        "限界": "正式保存trace/source値/全eventID照合は正式完了後の状態proofで行う。主W未使用パターン診断列は数式再計算対象外。将来収益性の検証ではない。"}
    (work / "独立準備点検.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("全件一致", "照合項目数", "不一致数", "ラベル計算", "損益計算")}, ensure_ascii=False))
    return result


def compare_row(audit: Any, name: str, actual: dict, expected: dict) -> None:
    """独立計算列を比較し、元R1の入れ子だけは独立で持つ列へ再帰投影する。

    引数: audit (Any) は比較先、name (str) は根拠名、actual/expected (dict) は保存/独立行。
    返り値: None。主の未使用パターン列は独立数式計算の保証へ含めない。
    """
    for key, value in expected.items():
        audit.check(name + ":列存在:" + key, key in actual, True)
        if key not in actual:
            continue
        if key == "旧22R1":
            compare_row(audit, name + ":旧22R1", actual[key], value)
        else:
            audit.check(name + ":" + key, actual[key], value)


def run(study: Path, work: Path) -> dict:
    """正式完了後だけ原価格から新30窓・全R1・全監視と全二集合を検算する。

    引数: study/work (Path) は23正式先/作業先。
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
    old_rows, old_sha = S.compressed_rows(OLD_WORK / "全複合shadow.jsonl.gz")
    old_r = {r["発動ID"]: r for r in old_rows if r["時間足分"] == 3 and r["入口系統"] == "R1"}
    label_numbers = ("新規価格", "新規時計秒", "新規原板行", "判定時計秒", "判定原板行", "判定気配",
                     "最大順行pt", "最大逆行pt", "所要分")
    label_keys = {"期間", "ラベル", "理由", *label_numbers}
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
                    eligible = requested < block["新規停止"] and block["期限"] - requested >= 3600
                    audit.check(str(key) + ":先着対象は時間条件", actual["先着評価対象"], eligible)
                    if name == "入口事例":
                        audit.check(str(key) + ":全case先着対象", actual["先着評価対象"], True)
                    if not eligible:
                        audit.check(str(key) + ":対象外label", actual["ラベル"], "対象外")
                        audit.check(str(key) + ":対象外理由", actual["理由"], "要求時間条件外")
                        for field in label_numbers:
                            audit.check(str(key) + ":対象外数値None:" + field, actual[field], None)
                    if row["入口系統"] == "R1":
                        canonical = {k: v for k, v in old_r[row["発動ID"]].items() if k not in label_keys}
                        audit.check(str(key) + ":旧R1全保存属性保持", actual["旧22R1"], canonical)
        for r in block["全採用"].values():
            entries[r["入口ID"]] += 1
        for r in block["全raw"].values():
            raw_families[r["入口系統"]] += 1
        for size, rows in block["価格足"].items():
            totals[str(size)] += len(rows)
        print(json.dumps({"場": session, "独立確認": "原価格・30窓・監視原順・二集合・全保存採否",
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
        "固定22旧R1発動数": len(old_r), "入口系統別raw数": dict(raw_families), "戦略別入口数": dict(entries),
        "監視段階": stages, "コードSHA256": V.sha(Path(__file__)), "入力台帳SHA256": V.sha(INPUT),
        "条件SHA256": V.sha(study / "条件.json"), "結果SHA256": V.sha(study / "結果.json"),
        "独立価格発動補助SHA256": V.sha(PRICE_HELPER), "独立数量補助SHA256": V.sha(QUANTITY_HELPER),
        "固定22状態proofSHA256": V.sha(OLD_WORK / "状態独立確認.json"), "旧22canonical展開SHA256": old_sha,
        "全複合context展開SHA256": hashes["全複合context"], "全局面展開SHA256": hashes["全局面"],
        "上位足展開SHA256": hashes["上位足"], "発動候補展開SHA256": hashes["全複合shadow"],
        "全複合shadow展開SHA256": hashes["全複合shadow"], "入口事例展開SHA256": hashes["入口事例"],
        "30分窓展開SHA256": hashes["30分窓"], "監視展開SHA256": hashes["監視"],
        "全運用詳細展開SHA256": hashes["全運用詳細"], "追尾展開SHA256": hashes["追尾"],
        "検証範囲": "原cacheから全3/15/30分半開OHLC・最初確認原行・欠枠・同限月carry/reset、固定21独立MACD/BB/Stoch/Wilderを再計算し固定22全3分R1を比較。新30窓は各時点の最終切断位置から六本を再列挙し、前3分p時点public-only asof/NP内部clear/持越しを照合。Tは主逐足watchとは別の設定単位区間走査で全登録・監視・strictstart対象外・寿命/取消優先・retest/resume初eligiblecross消費・usedkey・同足T禁止とR受付・診断寿命を列挙。数量Q11は固定14独立処理から診断値として比較。全raw保持/全二採用集合・case全二採否canonical一致・時間外先着対象外Noneまで照合。保存元R1の全属性保持は既検証固定22canonicalへの比較を別に行う。",
        "限界": "23主指標/入口/driver/運用をimportして自己再生しない。旧21/22の独立価格/発動補助、旧14の独立数量補助を読み取り再用する。主Wの未使用パターン診断列は数式再計算対象外だが元R1の保存保持を比較する。先着の通常数値/新規受入/会計/一建玉/追尾は別監査。原板全本文の再抽出はしない。全65場は既使用で、将来の収益性や事後条件の有効性を証明しない。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: proof[k] for k in ("全件一致", "照合項目数", "不一致数", "保存shadow数", "保存入口数",
        "保存30分窓数", "保存監視数", "case内canonical判定不一致数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """許可された準備点検または正式完了後の独立監査を選ぶ。

    引数: なし。--study/--work/--prepare/--実行許可を読む。
    返り値: None。不一致なら非0終了し、無許可では価格cacheも開かない。
    """
    parser = argparse.ArgumentParser(description="00023原価格の30分窓と再開監視の独立確認")
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
        parser.error("準備点検は --prepare、正式再生完了通知後は --実行許可 を指定してください")
    if not proof["全件一致"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
