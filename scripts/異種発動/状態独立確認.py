"""00021のMACD・SlowK・BBと発動切替を原価格から独立に再構成する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from copy import deepcopy
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00021_BBとMACDとストキャスの発動切替"
WORK = ROOT / "work/異種発動/00021"
INPUT = ROOT / "study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
PRICE_HELPER = ROOT / "scripts/局面切替/状態独立確認.py"
POLICIES = ("T0", "R0", "A0", "S1")


def helper(path: Path, name: str) -> Any:
    """独立価格足・Wilder・比較の補助だけを読む。

    引数: path (Path) は補助、name (str) はモジュール識別名。
    返り値: Any は補助。21指標/入口/driverはimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


P = helper(PRICE_HELPER, "異種発動の独立価格")
S, V = P.S, P.V


class Exponential:
    """有効入力だけの算術種からEMAを独立計算する。"""

    def __init__(self, length: int) -> None:
        """固定期間の未準備状態を作る。

        引数: length (int) は正の期間。
        返り値: None。
        """
        self.length, self.seed, self.value = length, [], None

    def add(self, value: float) -> float | None:
        """有効な一値を初期算術平均またはEMAへ加える。

        引数: value (float) は現在入力。
        返り値: float|None はEMA値または初期化未完了。
        """
        if self.value is None:
            self.seed.append(value)
            if len(self.seed) == self.length:
                self.value = sum(self.seed) / self.length
        else:
            self.value += 2 / (self.length + 1) * (value - self.value)
        return self.value


class Indicators(P.Indicators):
    """独立Wilder/BBへMACD12/26/9・Stoch14/3/3を加える。"""

    def __init__(self) -> None:
        """欠枠・尾部欠枠・限月変更にも使う全指標状態を作る。

        引数: なし。
        返り値: None。場開始だけでは呼び直さず同限月carryする。
        """
        super().__init__()
        self.fast, self.slow, self.signal = Exponential(12), Exponential(26), Exponential(9)
        self.range14, self.raw3, self.k3 = deque(maxlen=14), deque(maxlen=3), deque(maxlen=3)

    def add(self, bar: dict) -> dict:
        """完全幅足の終値/高安から新指標を別計算する。

        引数: bar (dict) は独立OHLC。公開False終端足も数値更新へ使う。
        返り値: dict は価格指標とMACD/Signal/Histogram・SlowK/SlowD・正帯幅。
        """
        row = super().add(bar)
        fast, slow = self.fast.add(bar["close"]), self.slow.add(bar["close"])
        macd = fast - slow if fast is not None and slow is not None else None
        signal = self.signal.add(macd) if macd is not None else None
        histogram = macd - signal if macd is not None and signal is not None else None
        self.range14.append((bar["high"], bar["low"]))
        raw = None
        if len(self.range14) == 14:
            highest, lowest = max(v[0] for v in self.range14), min(v[1] for v in self.range14)
            if highest > lowest:
                raw = 100 * (bar["close"] - lowest) / (highest - lowest)
        slow_k = slow_d = None
        if raw is None:
            self.raw3.clear()
            self.k3.clear()
        else:
            self.raw3.append(raw)
            if len(self.raw3) == 3:
                slow_k = sum(self.raw3) / 3
                self.k3.append(slow_k)
                if len(self.k3) == 3:
                    slow_d = sum(self.k3) / 3
        width = 4 * row["bb_sd"] / row["bb_mean"] if S.S.finite(row["bb_mean"], row["bb_sd"]) and row["bb_mean"] > 0 and row["bb_sd"] > 0 else None
        return {**row, "macd": macd, "macd_signal": signal, "macd_hist": histogram, "stoch_raw": raw,
            "stoch_k": slow_k, "stoch_d": slow_d, "bandwidth": width}


# ----------------------------------------
# 局面と共通準備を別計算し、全発動を先に残してから四規則を適用する。

def classify(higher: list[dict], session: str) -> tuple[list[dict], dict]:
    """EMAを使わず、独立15分ADX/DIから全局面を分類する。

    引数: higher (list[dict]) は独立15分足、session (str) は場。
    返り値: tuple[list[dict],dict] は全分類行と局面別足数。
    """
    rows, counts = [], Counter()
    for f in higher:
        ready = bool(f["publish"] and S.S.finite(f["adx"], f["plus_di"], f["minus_di"]))
        direction = (1 if f["plus_di"] > f["minus_di"] else -1 if f["plus_di"] < f["minus_di"] else 0) if ready else 0
        state = "未準備" if not ready else "レンジ" if f["adx"] <= 20 else (
            "トレンド" if f["adx"] >= 25 and direction != 0 else "待機")
        rows.append({"場": session, "局面ID": f"NK225_{session}_15分_{f['index']:04d}",
            **{k: f[k] for k in ("index", "minutes", "start", "end", "confirm", "confirm_line", "publish", "missing")},
            "上位準備済": ready, "ADX14": f["adx"], "+DI14": f["plus_di"], "-DI14": f["minus_di"],
            "局面": state, "DI方向": direction})
        counts[state] += 1
    return rows, dict(counts)


def single_ready(frame: dict) -> bool:
    """同場比較窓に積める必要数値だけを判定する。

    引数: frame (dict) は独立価格足。
    返り値: bool はBB正幅/正ATR/H/Kが有効か。SlowDやEMAは要求しない。
    """
    return bool(S.S.finite(*(frame[k] for k in ("bb_mean", "bb_sd", "bandwidth", "atr", "macd_hist", "stoch_k"))) and
        frame["bb_mean"] > 0 and frame["bb_sd"] > 0 and frame["atr"] > 0)


def contexts(frames: list[dict], states: list[dict], cutoff: float, deadline: float) -> dict[int, dict]:
    """局所連続三足と、公開キー/終了時計以下の最新公開15分を直接結合する。

    引数: frames/states (list[dict]) は独立下位足/15分局面、cutoff/deadline (float) は停止/期限。
    返り値: dict[int,dict] は全足context。過去二足遅延や上位EMAを追加しない。
    """
    result, segment = {}, []
    for f in frames:
        if not f["publish"] or not single_ready(f) or f["missing"] or segment and f["index"] != segment[-1]["index"] + 1:
            segment = []
        if f["publish"] and single_ready(f):
            segment.append(f)
        upper = P.available(f, states, True)
        base = {"上位準備済": bool(upper and upper["上位準備済"]),
            "局面参照ID": upper["局面ID"] if upper else None,
            "局面公開秒": upper["confirm"] if upper else None,
            "局面公開原行": upper["confirm_line"] if upper else None,
            "局面足終了秒": upper["end"] if upper else None,
            **{k: upper[k] if upper else "未準備" if k == "局面" else 0 if k == "DI方向" else None
                for k in ("局面", "DI方向", "ADX14", "+DI14", "-DI14")}}
        reasons = []
        if len(segment) < 3:
            reasons.append("同場連続公開三足未準備")
        if not base["上位準備済"]:
            reasons.append("公開15分ADX_DI未準備")
        if not f["publish"]:
            reasons.append("非公開足")
        if f["confirm"] - f["end"] > 30:
            reasons.append("確認遅延30秒超")
        result[f["index"]] = {**base, "共通M準備": not reasons, "M除外理由": reasons,
            "局所三足番号": [r["index"] for r in segment[-3:]],
            "時間条件可": bool(f["confirm"] < cutoff and deadline - f["confirm"] >= 3600)}
    return result


def decision(policy: str, family: str, side: int, context: dict) -> dict:
    """固定二系統・混合・当時局面切替の採否を別に求める。

    引数: policy/family (str) は規則/系統、side (int) は売買、context (dict) は当時の共通準備と局面。
    返り値: dict は採否/理由/競合初期値。将来ラベルは引数へ渡さない。
    """
    if not context["共通M準備"]:
        ok, reason = False, "共通M未準備"
    elif policy in ("T0", "R0", "A0"):
        ok = policy == "A0" or family == ("T1" if policy == "T0" else "R1")
        reason = "固定手法選択" if ok else "固定手法対象外"
    elif context["局面"] == "トレンド":
        ok = family == "T1" and side == context["DI方向"]
        reason = "トレンド同DI方向の継続" if ok else "トレンドで対象外発動"
    elif context["局面"] == "レンジ":
        ok = family == "R1"
        reason = "レンジの反転" if ok else "レンジで継続見送り"
    else:
        ok, reason = False, "転換待機"
    return {"採用": bool(ok), "理由": [reason], "同時競合": False}


def generate(frames: list[dict], context_by_index: dict, session: str, period: str,
             deadline: float) -> tuple[dict, dict]:
    """独立三足から全T1/R1発動を列挙し、その後四戦略を選ぶ。

    引数: frames (list[dict]) は独立足、context_by_index (dict) は全準備、
    session/period (str) は場/期間、deadline (float) は期限。
    返り値: tuple[dict,dict] は全shadow/全12入口。旧Q・sweep条件を加えない。
    """
    by_index = {f["index"]: f for f in frames}
    shadow, selected, groups = {}, {}, defaultdict(list)
    for f in frames:
        context = context_by_index[f["index"]]
        if not context["共通M準備"] or not context["時間条件可"]:
            continue
        older, previous, current = [by_index[i] for i in context["局所三足番号"]]
        for side in (1, -1):
            hist_now = side * (current["macd_hist"] - previous["macd_hist"])
            hist_before = side * (previous["macd_hist"] - older["macd_hist"])
            k_before = previous["stoch_k"] if side == 1 else 100 - previous["stoch_k"]
            k_current = current["stoch_k"] if side == 1 else 100 - current["stoch_k"]
            t1 = bool(side * (f["close"] - f["bb_mean"]) > 0 and f["bandwidth"] > previous["bandwidth"] and hist_before <= 0 and hist_now > 0)
            r1 = bool(side * (f["bb_mean"] - f["close"]) > 0 and k_before <= 20 < k_current)
            for family, found in (("T1", t1), ("R1", r1)):
                if not found:
                    continue
                size = f["minutes"]
                identity = f"NK225_{session}_{size}分_{family}_{f['index']:04d}_{side}"
                verdicts = {p: decision(p, family, side, context) for p in POLICIES}
                signal = {**f, **context, "場": session, "期間": period, "時間足分": size, "入口系統": family,
                    "役割": "順行" if family == "T1" else "反転", "side": side, "方向": "買い" if side == 1 else "売り",
                    "QイベントID": identity, "発動ID": identity, "イベントID": identity, "入口ID": f"{size}分_{family}",
                    "戦略判定": verdicts, "要求時計秒": f["confirm"], "要求原板行": f["confirm_line"],
                    "確認遅延秒": f["confirm"] - f["end"], "足終了時計秒": f["end"], "期限時計秒": deadline,
                    "残り分_判断時": (deadline - f["confirm"]) / 60,
                    "直前足": {k: previous[k] for k in ("index", "confirm", "confirm_line", "close", "bb_mean", "bb_sd", "bandwidth", "macd_hist", "stoch_k")},
                    "二足前": {k: older[k] for k in ("index", "confirm", "confirm_line", "macd_hist")}}
                shadow[identity] = signal
                for policy in POLICIES:
                    if verdicts[policy]["採用"]:
                        groups[policy, f["confirm"], f["confirm_line"]].append(signal)
    for (policy, _, _), rows in groups.items():
        if len(rows) > 1:
            for row in rows:
                row["戦略判定"][policy].update(採用=False, 同時競合=True, 理由=["同判断複数信号見送り"])
            continue
        row = rows[0]
        identity = row["発動ID"] + "_" + policy
        selected[identity] = {**deepcopy(row), "入口ID": f"{row['minutes']}分_{policy}", "戦略": policy,
            "複合判定": deepcopy(row["戦略判定"][policy]), "イベントID": identity}
    return shadow, selected


# ----------------------------------------
# 保存された発動が正しいと仮定せず、全足から全発動を列挙して集合を比較する。

def compare_fields(audit: Any, name: str, actual: dict, expected: dict) -> None:
    """独立に計算した各列の存在と値を保存行へ比較する。

    引数: audit (Any) は比較先、name (str) は根拠名、actual/expected (dict) は保存/独立行。
    返り値: None。主Wの未使用診断列が保存側に多い場合は削除しない。
    """
    for key, value in expected.items():
        audit.check(name + ":" + key + ":列存在", key in actual, True)
        if key in actual:
            audit.check(name + ":" + key, actual[key], value)


def run(study: Path, work: Path) -> dict:
    """正式完了後だけ全65場の新指標・発動・全採否を独立に照合する。

    引数: study/work (Path) は21正式先/作業先。
    返り値: dict は明示合否・件数・指紋。準備点検中に本関数を呼ばない。
    """
    if not (study / "結果.json").exists() or not (study / "固定.json").exists():
        raise ValueError("正式再生完了前は実行しません")
    audit, manifest, config = V.Audit(), V.read(INPUT), V.read(study / "条件.json")
    context_rows, context_sha = S.compressed_rows(work / "全複合context.jsonl.gz")
    state_rows, state_sha = S.compressed_rows(work / "全局面.jsonl.gz")
    upper_rows, upper_sha = S.compressed_rows(work / "上位足.jsonl.gz")
    shadow_rows, shadow_sha = S.compressed_rows(work / "全複合shadow.jsonl.gz")
    case_rows, case_sha = S.compressed_rows(work / "入口事例.jsonl.gz")
    saved_context = {(r["場"], r["時間足分"], r["index"]): r for r in context_rows}
    saved_state = {(r["場"], r["index"]): r for r in state_rows}
    saved_upper = {(r["場"], r["minutes"], r["index"]): r for r in upper_rows}
    saved_shadow = {r["発動ID"]: r for r in shadow_rows}
    saved_cases = {r["イベントID"]: r for r in case_rows}
    for name, mapping, values in (("context", saved_context, context_rows), ("局面", saved_state, state_rows),
                                 ("上位足", saved_upper, upper_rows), ("shadow", saved_shadow, shadow_rows),
                                 ("入口", saved_cases, case_rows)):
        audit.check(name + ":保存キー一意", len(mapping), len(values))
    saved_quality = {r["場"]: r for r in V.read(study / "局面品質.json")}
    saved_entry_quality = {(r["場"], r["時間足分"]): r for r in V.read(study / "入口品質.json")}
    banks, contract, phases, totals = {n: Indicators() for n in (1, 3, 5, 15)}, None, Counter(), Counter()
    expected_context, expected_state, expected_upper, expected_shadow, expected_cases = {}, {}, {}, {}, {}
    for entry in manifest["entries"]:
        session, codes = entry["session"], tuple(entry["in_session_contract_codes"])
        if len(codes) != 1:
            raise ValueError("限月一意性不成立")
        if contract is not None and codes != contract:
            banks = {n: Indicators() for n in banks}
        contract = codes
        period = "後続検査" if session[:10] >= config["分割"]["後続開始日"] else (
            "条件選択" if session[:10] >= config["分割"]["選択開始日"] else "学習")
        phases[period] += 1
        data = S.S.observed(entry)
        formed = {n: S.S.bars(data, session, n, bank) for n, bank in banks.items()}
        states, quality = classify(formed[15], session)
        audit.check(session + ":全15局面足数", {k: v for k, v in saved_quality[session].items() if k not in ("場", "期間")}, quality)
        expected_state.update({(session, r["index"]): {"期間": period, **r} for r in states})
        expected_upper.update({(session, 15, f["index"]): {"場": session, "期間": period, **f} for f in formed[15]})
        _, _, cutoff, deadline = S.S.G.times(session)
        for size in (1, 3, 5):
            local = contexts(formed[size], states, cutoff, deadline)
            expected_context.update({(session, size, f["index"]): {"場": session, "期間": period, "時間足分": size,
                **f, **local[f["index"]]} for f in formed[size]})
            shadow, cases = generate(formed[size], local, session, period, deadline)
            expected_shadow.update(shadow)
            expected_cases.update(cases)
            quality_row = saved_entry_quality[session, size]
            audit.check(f"{session}:{size}:全足数", quality_row["足数"], len(formed[size]))
            audit.check(f"{session}:{size}:共通M足数", quality_row["共通M準備足数"], sum(r["共通M準備"] for r in local.values()))
            for policy in POLICIES:
                audit.check(f"{session}:{size}:{policy}:全採用数", quality_row["戦略別発動数"][f"{size}分_{policy}"],
                    sum(r["戦略"] == policy for r in cases.values()))
            totals[str(size)] += len(formed[size])
        totals["15"] += len(formed[15])
        print(json.dumps({"場": session, "独立確認": "MACD/SlowK/BB・全局面・全発動/採否",
            "現時点不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("全65場", len(manifest["entries"]), 65)
    audit.check("既使用40/24/1", dict(phases), {"学習": 40, "条件選択": 24, "後続検査": 1})
    for name, saved, expected in (("全局面", saved_state, expected_state), ("全15分特徴", saved_upper, expected_upper),
                                 ("全下位特徴context", saved_context, expected_context), ("全発動shadow", saved_shadow, expected_shadow),
                                 ("全12入口", saved_cases, expected_cases)):
        S.compare_keys(audit, name + ":全集合", set(saved), set(expected))
        for key in saved.keys() & expected.keys():
            if name == "全12入口":
                compare_fields(audit, f"{name}:{key}", saved[key], {k: v for k, v in expected[key].items() if k != "戦略判定"})
                chosen = expected[key]["戦略"]
                audit.check(f"{name}:{key}:実選択戦略の判定",
                    saved[key]["戦略判定"][chosen], expected[key]["複合判定"])
            else:
                compare_fields(audit, f"{name}:{key}", saved[key], expected[key])
    snapshot_differences = []
    for key in saved_cases.keys() & expected_cases.keys():
        for policy in POLICIES:
            for field in ("採用", "理由", "同時競合"):
                actual = saved_cases[key]["戦略判定"][policy][field]
                expected = expected_cases[key]["戦略判定"][policy][field]
                if actual != expected:
                    snapshot_differences.append({"イベントID": key, "実選択戦略": saved_cases[key]["戦略"],
                        "表示戦略": policy, "属性": field, "保存": actual, "独立group順snapshot": expected})
                    audit.check(key + ":初回snapshot比較差は他戦略A0だけ",
                        policy == "A0" and policy != saved_cases[key]["戦略"], True)
    display_differences = []
    for case in case_rows:
        canonical = saved_shadow[case["発動ID"]]["戦略判定"]
        audit.check(case["イベントID"] + ":実選択判定は最終shadowと同値",
            case["戦略判定"][case["戦略"]], canonical[case["戦略"]])
        audit.check(case["イベントID"] + ":実選択複合判定は最終shadowと同値",
            case["複合判定"], canonical[case["戦略"]])
        for policy, verdict in case["戦略判定"].items():
            if verdict != canonical[policy]:
                display_differences.append({"イベントID": case["イベントID"], "実選択戦略": case["戦略"], "表示戦略": policy,
                    "採用case内表示": verdict, "shadow最終採否": canonical[policy]})
                audit.check(case["イベントID"] + ":他戦略表示差だけ", policy != case["戦略"], True)
                audit.check(case["イベントID"] + ":A0後発競合の表示差", policy, "A0")
    display = {"既知表示エラー": bool(display_differences), "実選択判定一致": audit.mismatches == 0,
        "他戦略表示差件数": len(display_differences),
        "他戦略表示差": display_differences, "全複合shadow展開SHA256": shadow_sha, "入口事例展開SHA256": case_sha,
        "初回独立group順比較の属性差数": len(snapshot_differences), "初回独立group順比較差": snapshot_differences,
        "検証定義の違い": "初回126属性差は保存caseと独立group順snapshotの比較。実表示エラー43行は保存caseとcanonical shadowの比較であり、同じ分母/比較先ではない。独立側も他戦略snapshotを途中複写したため初回件数を実表示エラー数とはしない。",
        "意味": "採用caseはgroup走査途中のdeepcopyなので、後続A0競合更新前の他戦略表示が残る既知表示エラー。全戦略採否の正本はshadow最終判定で、caseは実選択戦略の複合判定を正本とする。主core/結果/生caseを修正しない。次実装は全競合確定後のcase複写という2passが必要。"}
    display_path = work / "入口内他戦略表示差.json"
    display_path.write_text(json.dumps(display, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    proof = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches, "不一致": audit.errors,
        "判定対象": "機能照合。採用case内の他戦略表示差は別掲し、全保存列一致とはしない",
        "表示属性注意": bool(display_differences), "既知表示エラー": bool(display_differences),
        "他戦略表示差件数": len(display_differences), "初回独立group順比較の属性差数": len(snapshot_differences),
        "表示差の比較定義": display["検証定義の違い"],
        "保存入口内他戦略表示差件数": len(display_differences), "入口内他戦略表示差SHA256": V.sha(display_path),
        "入力場数": len(manifest["entries"]), "期間場数": dict(phases), "独立足数": dict(totals),
        "保存context数": len(context_rows), "保存局面数": len(state_rows), "保存上位足数": len(upper_rows),
        "保存発動候補数": len(shadow_rows), "保存shadow数": len(shadow_rows), "保存入口数": len(case_rows),
        "独立発動候補数": len(expected_shadow), "独立入口数": len(expected_cases),
        "戦略別入口数": dict(Counter(r["入口ID"] for r in expected_cases.values())),
        "コードSHA256": V.sha(Path(__file__)), "入力台帳SHA256": V.sha(INPUT), "独立価格補助SHA256": V.sha(PRICE_HELPER),
        "全複合context展開SHA256": context_sha, "全局面展開SHA256": state_sha, "上位足展開SHA256": upper_sha,
        "発動候補展開SHA256": shadow_sha, "全複合shadow展開SHA256": shadow_sha, "入口事例展開SHA256": case_sha,
        "検証範囲": "原価格cacheから1/3/5/15分半開足・確認原行・欠枠/尾部/限月resetと同限月carryを独立計算。非公開末尾を含む全価格足のEMA/BB母σ/WilderATR/ADX/DI、MACD12/26/9算術seed、rawK14→SMA3→SMA3とゼロrange時平滑履歴切断を別計算。全15分類/公開as-of、同場三公開足HKBBATR共通M、全T1再加速/R1領域復帰、全shadow四規則採否・理由・競合と12発動全集合を照合。採用caseでは実選択戦略の判定/複合判定と指標/時点を照合し、他戦略表示はcanonical shadowとの差を全件別掲。",
        "限界": "21主指標/入口/driverをimportしない。既存独立Wilder/価格足helperは再利用する。採用case内には後続A0競合更新前の他戦略表示が43件残り、全保存列一致とはしない。実選択採否・集合・shadow最終採否への影響はないことを全件確認する。主Wの未使用パターン診断列の全再計算、先着ラベル/新規受入/会計/追尾は別監査。原板本文の全再抽出や価格時計の受信時計化はしない。全65場は既使用であり、照合成功は将来収益性の証明ではない。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: proof[k] for k in ("全件一致", "照合項目数", "不一致数", "保存context数", "保存shadow数", "保存入口数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """正式再生完了通知後だけ独立監査を開始する。

    引数: なし。--study/--work/--実行許可を読む。
    返り値: None。不一致時は非0終了。
    """
    parser = argparse.ArgumentParser(description="00021新指標と発動切替の独立再構成")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--実行許可", action="store_true")
    args = parser.parse_args()
    if not args.実行許可:
        parser.error("正式再生完了通知後に --実行許可 を指定してください")
    if not run(args.study.resolve(), args.work.resolve())["全件一致"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
