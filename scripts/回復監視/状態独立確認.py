"""00035の登録・接触・回復・実監視を元価格列から別手順で確認する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import importlib.util
import heapq
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00035_CCI突破の到達後回復"
WORK = ROOT / "work/回復監視/00035"
CONTROL_STUDY = ROOT / "study/00034_CCI突破の水準指値"
CONTROL_WORK = ROOT / "work/突破指値/00034"
POLICIES = ("E1", "E2", "E3")
OPERATIONS = tuple("3分_" + policy + "_XF" for policy in POLICIES)
CONTROL_LOCK_SHA = "f4351a3a5cc43a223641bc4c321135c402075266d1e8e3158d101cc6ba8ed879"
ENTRY_STUDY = ROOT / "study/00031_CCI持続と上位BB幅"


def helper(path: Path, name: str) -> Any:
    """固定済みの独立補助だけを読み込む。

    引数: path(Path)は旧独立コード、name(str)はモジュール名。
    返り値: Anyは補助モジュール。35主入口・運用をimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


Y = helper(ROOT / "scripts/突破指値/状態独立確認.py", "回復監視の固定34独立補助")
G, B, S, V, Audit = Y.G, Y.B, Y.S, Y.V, Y.Audit
BASE_FIELDS = Y.BASE_FIELDS
SIGNAL_FIELDS = {policy: Y.SIGNAL_FIELDS["E1"] for policy in POLICIES}
RESULT_NUMBERS = Y.RESULT_NUMBERS
canonical_sha, registration, decision_signal = Y.canonical_sha, Y.registration, Y.decision_signal
raw_projection, normal_columns = Y.raw_projection, Y.normal_columns


def pure_signal(row: dict, policy: str | None = None) -> dict:
    """登録時情報の明示15列を深複写する。

    引数: row(dict)は当時情報又は保存case、policy(str|None)は方針確認用。
    返り値: dictは未来接触/回復/仮約定/先着を含まない純信号。
    """
    if policy is not None and policy not in POLICIES:
        raise ValueError("事前に定めたE1/E2/E3だけです")
    return {key: deepcopy(row.get(key)) if key == "bb_mean" else deepcopy(row[key]) for key in SIGNAL_FIELDS["E1"]}


def select(block: dict) -> dict:
    """独立31のC0を固定34と同じ15列から三方針へ写す。

    引数: block(dict)は固定31独立のquality/signalsを持つ材料。
    返り値: dictは同じ全登録と三純集合。登録価格・ATRを後から改訂しない。
    """
    old = Y.select(block)
    selected = {"3分_" + policy: [] for policy in POLICIES}
    for row in old["signals"]["3分_E1"]:
        for policy in POLICIES:
            item = pure_signal(row)
            item.update(イベントID=row["イベントID"][:-3] + "_" + policy, 入口ID="3分_" + policy)
            selected["3分_" + policy].append(item)
    old["signals"] = selected
    return old


# ----------------------------------------
# 仮観測は登録ごとに独立。新規fill/125250/実保有の抑止は準備で計算しない。


def scan_observation(quotes: dict, signal: dict, cutoff: float, deadline: float, policy: str) -> dict:
    """原正常BBOを順走査し、初回接触とstrict後keyの初回回復だけを求める。

    引数: quotes(dict)はnow/line/bid/ask列、signal(dict)は登録、cutoff/deadline(float)は停止/強制、policy(str)は方針。
    返り値: dictは位置・要求key・時間可否の独立内部表現。仮新規fillは選ばない。
    """
    if policy not in POLICIES or signal["side"] not in (-1, 1):
        raise ValueError("三方針と鏡像の方向だけを扱います")
    registered = float(signal["要求時計秒"])
    expires = registered + (30 if policy == "E1" else 180)
    side, level = signal["side"], signal["新規指値価格"]
    output = {"接触位置": None, "回復位置": None, "絶対期限": expires,
        "新規要求key": (registered, int(signal["要求原板行"])) if policy != "E3" else None,
        "回復時間可": None, "回復時間除外理由": []}
    touch_key = None
    first_index = int(S.np.searchsorted(quotes["now"], registered + 1, side="left"))
    for index in range(first_index, len(quotes["now"])):
        clock, line = float(quotes["now"][index]), int(quotes["line"][index])
        if clock > expires or clock >= cutoff or clock >= deadline:
            break
        bid, ask = float(quotes["bid"][index]), float(quotes["ask"][index])
        if not all(math.isfinite(value) for value in (clock, bid, ask)) or not 0 < bid <= ask:
            raise ValueError("原正常BBOの条件が崩れています")
        key = clock, line
        if touch_key is None:
            if (ask <= level if side == 1 else bid >= level):
                output["接触位置"] = index
                touch_key = key
                if policy != "E3":
                    break
            continue
        if key <= touch_key or not (bid > level if side == 1 else ask < level):
            continue
        output["回復位置"] = index
        reasons = []
        if deadline - clock < 60 * 60:
            reasons.append("回復時残り60分未満")
        if clock + 1 > expires:
            reasons.append("回復後1秒が元期限外")
        output["回復時間除外理由"] = reasons
        output["回復時間可"] = not reasons
        if not reasons:
            output["新規要求key"] = key
        break
    return output


def observation(quotes: dict, signal: dict, cutoff: float, deadline: float, policy: str = "E3") -> dict:
    """独立の位置走査を出典付きの公開観測辞書へ写す。

    引数: quotes/signal(dict)は原正常列/登録、cutoff/deadline(float)は時刻境界、policy(str)は方針。
    返り値: dictは初回到達/回復/新規要求key。純signalへ後から混ぜない診断用の観測。
    """
    result = scan_observation(quotes, signal, cutoff, deadline, policy)
    snapshots = []
    for key in ("接触位置", "回復位置"):
        index = result[key]
        snapshots.append(None if index is None else {"時計秒": float(quotes["now"][index]),
            "原板行": int(quotes["line"][index]), "bid": float(quotes["bid"][index]), "ask": float(quotes["ask"][index])})
    requested = result["新規要求key"]
    return {"絶対失効時計秒": result["絶対期限"], "初回到達出典": snapshots[0], "初回回復出典": snapshots[1],
        "回復時間可": result["回復時間可"], "回復時間除外理由": result["回復時間除外理由"],
        "新規要求時計秒": None if requested is None else requested[0],
        "新規要求原板行": None if requested is None else requested[1]}


def entry_index(quotes: dict, signal: dict, cutoff: float, deadline: float, policy: str) -> int | None:
    """正式時だけ、観測から元絶対期限内の最初の新規BBOを直接選ぶ。

    引数: quotes/signal(dict)は正常列/登録、cutoff/deadline(float)は停止/強制、policy(str)は方針。
    返り値: int|Noneは実在する仮新規位置。回復時点からTTLを延ばさない。
    """
    observed = scan_observation(quotes, signal, cutoff, deadline, policy)
    if policy != "E3":
        return observed["接触位置"]
    requested = observed["新規要求key"]
    if requested is None:
        return None
    first_index = int(S.np.searchsorted(quotes["now"], requested[0] + 1, side="left"))
    for index in range(first_index, len(quotes["now"])):
        clock = float(quotes["now"][index])
        if clock > observed["絶対期限"] or clock >= cutoff or clock >= deadline:
            return None
        return index
    return None


def label_from_index(quotes: dict, side: int, first: int, deadline: float) -> dict:
    """選ばれた新規以降の原価格列だけで125/250・空白・期限を評価する。

    引数: quotes(dict)は正常気配、side(int)は実方向、first(int)は仮新規位置、deadline(float)は強制期限。
    返り値: dictはラベル/理由/九数値。成立前の順行逆行を算入しない。
    """
    now = S.np.asarray(quotes["now"])
    if deadline < now[first]:
        raise ValueError("仮新規より前の評価期限")
    entered = float(quotes["ask"][first] if side == 1 else quotes["bid"][first])
    marks = S.np.asarray(quotes["bid"] if side == 1 else quotes["ask"])
    in_time = S.np.flatnonzero(now[first:] <= deadline)
    last = first + int(in_time[-1])
    distances = side * (marks[first:last + 1] - entered)
    crossing = S.np.flatnonzero((distances <= -125) | (distances >= 250))
    hit = first + int(crossing[0]) if len(crossing) else None
    gaps = S.np.flatnonzero((S.np.diff(now[first:]) > 300) & (now[first:-1] + 300 < deadline))
    gap_left = first + int(gaps[0]) if len(gaps) else None
    if hit is not None and (gap_left is None or hit <= gap_left):
        last = hit
        label = "順行先着" if side * (float(marks[last]) - entered) >= 250 else "逆行先着"
        reason = "返済気配の閾値初着"
    else:
        if gap_left is not None:
            last = gap_left
        stale = deadline - now[last] > 300
        if gap_left is not None or stale:
            label, reason = "観測不足", "正常板価格時計300秒超空白"
        elif now[-1] < deadline:
            label, reason = "観測不足", "入力末尾不足"
        else:
            label, reason = "期限未達", "期限内どちらも未到達"
    observed = side * (marks[first:last + 1] - entered)
    return {"ラベル": label, "理由": reason, "新規価格": entered,
        "新規時計秒": float(now[first]), "新規原板行": int(quotes["line"][first]),
        "判定時計秒": float(now[last]), "判定原板行": int(quotes["line"][last]), "判定気配": float(marks[last]),
        "最大順行pt": float(max(0, S.np.max(observed))), "最大逆行pt": float(max(0, -S.np.min(observed))),
        "所要分": float((now[last] - now[first]) / 60)}


def label_direct(quotes: dict, signal: dict, cutoff: float, deadline: float, policy: str) -> dict:
    """正式時だけ全登録の新先着を元正常価格列で直接判定する。

    引数: quotes/signal(dict)は正常列/登録、cutoff/deadline(float)は境界、policy(str)は三方針。
    返り値: dictはラベル/理由/九数値。未約定は仮価格や架空の経路を補わない。
    """
    first = entry_index(quotes, signal, cutoff, deadline, policy)
    if first is not None:
        return label_from_index(quotes, signal["side"], first, deadline)
    if policy == "E1":
        reason = "30秒内に指値成立正常BBOなし"
    elif policy == "E2":
        reason = "180秒内に指値成立正常BBOなし"
    else:
        result = scan_observation(quotes, signal, cutoff, deadline, policy)
        reason = "180秒内に水準到達なし" if result["接触位置"] is None else (
            "到達後に水準回復なし" if result["回復位置"] is None else
            "・".join(result["回復時間除外理由"]) if not result["回復時間可"] else
            "回復要求後に元期限内の正常BBOなし")
    return {"ラベル": "未約定", "理由": reason, **{name: None for name in RESULT_NUMBERS}}


# ----------------------------------------
# 非損益準備は当時信号と仮監視観測まで。旧ラベル/損益はliveへ渡さない。


def dependency_pins() -> dict:
    """推移的な旧独立補助の現在指紋を列挙する。

    引数: なし。
    返り値: dict[str,str]はROOT相対pathとSHA。主35の数値/入口/運用は読み込まない。
    """
    paths = ("scripts/突破指値/状態独立確認.py", "scripts/突破指値/追尾独立確認.py")
    return dict(sorted({**Y.dependency_pins(), **{path: V.sha(ROOT / path) for path in paths}}.items()))


def control_reference(study: Path, audit: Audit) -> dict:
    """旧34E1の正本・完了証明・三圧縮明細を入力cache前に検査する。

    引数: study(Path)は35保存先、audit(Audit)は比較先。
    返り値: dictは対照参照。旧損益を再計算しない。
    """
    pointer = V.read(study / "対照参照.json")
    for key, expected in {"参照試行": "00034", "候補ID": "3分_E1_XF", "全66場既使用": True,
            "大明細複製": False, "旧固定SHA256": CONTROL_LOCK_SHA}.items():
        audit.check("対照参照:" + key, pointer[key], expected)
    audit.check("旧34固定anchor", V.sha(CONTROL_STUDY / "固定.json"), CONTROL_LOCK_SHA)
    names = {"固定.json", "条件.json", "結果.json", "作業成果物.json", "独立監査.json", "状態独立確認.json", "追尾独立確認.json", "入力台帳.json"}
    audit.check("旧34全証明集合", set(pointer["文書と証明"]), names)
    for name, item in pointer["文書と証明"].items():
        path = CONTROL_STUDY / name
        audit.check("旧34証明正本:" + name, (ROOT / item["パス"]).resolve(), path.resolve())
        audit.check("旧34証明SHA:" + name, item["SHA256"], V.sha(path))
    for name, digest in V.read(CONTROL_STUDY / "固定.json")["ファイルSHA256"].items():
        audit.check("旧34固定現在:" + name, V.sha(ROOT / name), digest)
    expected = V.read(CONTROL_STUDY / "作業成果物.json")["ファイル"]
    audit.check("旧34三明細宣言", pointer["共有明細"], expected)
    audit.check("旧34三明細数", len(expected), 3)
    for item in expected:
        path = ROOT / item["パス"]
        audit.check("旧34明細範囲:" + path.name, path.resolve().parent, CONTROL_WORK.resolve())
        audit.check("旧34明細圧縮SHA:" + path.name, V.sha(path), item["圧縮SHA256参考"])
        audit.check("旧34明細bytes:" + path.name, path.stat().st_size, item["圧縮バイト"])
    for name in ("独立監査.json", "状態独立確認.json", "追尾独立確認.json"):
        proof = V.read(CONTROL_STUDY / name)
        audit.check("旧34完了:" + name, proof["全件一致"], True)
        audit.check("旧34差0:" + name, proof["不一致数"], 0)
    return pointer


def guarded_inputs(study: Path, work: Path, audit: Audit) -> tuple[dict, dict, dict, Path]:
    """現準備・台帳・三方針と旧固定の継承値を入力cache前に検査する。

    引数: study/work(Path)は保存先、audit(Audit)は比較先。
    返り値: tuple[dict,dict,dict,Path]は条件/実台帳/主準備/実台帳path。差は入力前に拒否。
    """
    config = V.read(study / "条件.json")
    manifest, resolved = G.resolved_manifest(study)
    Y.entry_reference(study, audit)
    control_reference(study, audit)
    previous = V.read(CONTROL_STUDY / "条件.json")
    for key in ("対象", "時間足分", "逆行pt", "順行pt", "残り時間下限分", "確認遅延上限秒", "運用",
            "入口支持", "費用支持", "目標確認率", "間引き必要件数", "分割", "必須追尾"):
        audit.check("固定34共通継承:" + key, config[key], previous[key])
    audit.check("事前三方針", config["戦略"], list(POLICIES))
    audit.check("XF一出口", config["出口"], [{"出口ID": "XF"}])
    master = V.read(work / "準備点検.json")
    expected = {"ラベル計算": False, "損益計算": False, "全66場既使用": True, "旧31C0純登録同値": True,
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照台帳SHA256": V.sha(resolved), "入口参照SHA256": V.sha(study / "入口参照.json"),
        "対照参照SHA256": V.sha(study / "対照参照.json"),
        "純信号whitelist": {policy: list(names) for policy, names in SIGNAL_FIELDS.items()}}
    for name, value in expected.items():
        audit.check("主準備:" + name, master[name], value)
    paths = {"scripts/回復監視/" + name for name in ("検証.py", "入口.py", "運用.py")}
    audit.check("主三コード集合", set(master["コードSHA256"]), paths)
    for name, digest in master["コードSHA256"].items():
        audit.check("主準備現在:" + name, V.sha(ROOT / name), digest)
    audit.check("主準備66場順", [row["場"] for row in master["準備"]], [row["session"] for row in manifest["entries"]])
    if audit.mismatches:
        raise ValueError("主/共有/対照の不一致によりcache前停止")
    return config, manifest, master, resolved


def reconstruct(manifest: dict) -> Any:
    """元8列から固定C0と独立仮監視だけを場順に再構成する。

    引数: manifest(dict)は既使用66場の固定台帳。
    返り値: Anyは非損益の場別iterator。private列は監査内だけで使い保存しない。
    """
    old = V.read(ENTRY_STUDY / "条件.json")
    inputs = {row["session"]: row for row in manifest["entries"]}
    for block in G.reconstruct(manifest, old):
        selected = select({"quality": block["入口品質"], "signals": block["純入口"]})
        signals = [row for policy in POLICIES for row in selected["signals"]["3分_" + policy]]
        quotes = normal_columns(inputs[block["場"]], manifest)
        watched = [{"イベントID": row["イベントID"], "入口ID": row["入口ID"],
            "回復観測": observation(quotes, row, block["新規停止"], block["期限"])} for row in selected["signals"]["3分_E3"]]
        anchors = selected["registrations"]
        yield {"場": block["場"], "期間": block["期間"], "純信号": signals,
            "純信号内容SHA256": canonical_sha(signals), "純信号判断SHA256": canonical_sha([decision_signal(row) for row in signals]),
            "登録台帳": anchors, "登録内容SHA256": canonical_sha(anchors),
            "原P判定SHA256": canonical_sha(raw_projection(block["入口品質"]["全Q発動記録"])), "入力品質": block["入力品質"],
            "仮監視観測": watched, "仮監視観測SHA256": canonical_sha(watched),
            "_正常気配": quotes, "_公開足": [{key: row[key] for key in ("publish", "confirm", "confirm_line", "end", "index")}
                for row in block["価格足"][3] if row["publish"]]}


def compare_preparation(main: dict, block: dict, saved: dict, audit: Audit) -> dict:
    """全登録・仮観測・純信号と厳密判断SHAを比較する。

    引数: main/block(dict)は主/独立の場別準備、saved(dict)は旧34E1の当時15列、audit(Audit)は比較先。
    返り値: dictは場別の小型検算記録。ATRだけ既定許容/D整数へ分離する。
    """
    session = block["場"]
    independent = {key: value for key, value in block.items() if not key.startswith("_") and key != "純信号内容SHA256"}
    audit.check(session + ":全登録/仮観測/判断/入力/純leaf", {key: value for key, value in main.items() if key != "純信号内容SHA256"}, independent)
    audit.check(session + ":主生pureSHA", main["純信号内容SHA256"], canonical_sha(main["純信号"]))
    ids = {policy: set() for policy in POLICIES}
    for row in main["純信号"]:
        policy = row["入口ID"].removeprefix("3分_")
        audit.check(row["イベントID"] + ":事前方針", policy in POLICIES, True)
        if policy not in POLICIES:
            continue
        audit.check(row["イベントID"] + ":whitelist", set(row), set(SIGNAL_FIELDS[policy]))
        original = Y.rename(pure_signal(row), "_" + policy, "_E1")
        expected = saved.get(original["イベントID"])
        audit.leaf(row["イベントID"] + ":旧34E1純15列完全同値", original, expected, original == expected)
        ids[policy].add(original["イベントID"])
    target = {key for key, row in saved.items() if row["場"] == session}
    for policy in POLICIES:
        audit.check(session + ":" + policy + "元登録全集合", ids[policy], target)
    return {"場": session, "期間": block["期間"], "原C0登録数": len(block["登録台帳"]),
        **{policy + "純信号数": len(ids[policy]) for policy in POLICIES},
        "主生純信号内容SHA256": main["純信号内容SHA256"], "独立純信号判断SHA256": block["純信号判断SHA256"],
        "仮監視観測SHA256": block["仮監視観測SHA256"], "登録内容SHA256": block["登録内容SHA256"], "原P判定SHA256": block["原P判定SHA256"]}


def proof_base(study: Path, work: Path, resolved: Path, master: dict, audit: Audit) -> dict:
    """版・入力・対照とATR限定許容を証明の共通字段へ保存する。

    引数: study/work/resolved(Path)は保存先/実台帳、master(dict)は主準備、audit(Audit)は照合記録。
    返り値: dictは主/独立/出典を現在SHAへ接続する証明骨格。
    """
    return {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches, "不一致": audit.errors,
        "入力場数": 66, "全66場既使用": True, "コードSHA256": V.sha(Path(__file__)),
        "追尾コードSHA256": V.sha(Path(__file__).with_name("追尾独立確認.py")), "依存コードSHA256": dependency_pins(),
        "主準備SHA256": V.sha(work / "準備点検.json"), "主コードSHA256": master["コードSHA256"],
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照入力台帳SHA256": V.sha(resolved), "解決入力台帳SHA256": V.sha(resolved),
        "入口参照SHA256": V.sha(study / "入口参照.json"), "対照参照SHA256": V.sha(study / "対照参照.json"),
        "旧31固定SHA256": Y.OLD_LOCK_SHA, "旧34固定SHA256": CONTROL_LOCK_SHA,
        "ATR照合": {"leaf数": audit.atr_count, "表現差数": audit.atr_repr_diff, "最大絶対差": audit.atr_max_abs,
            "追尾D整数差数": audit.atr_tick_diff, "許容": "abs1e-10/rel0と正有効/D整数厳密"},
        "厳密範囲": "原登録/純15列の非ATR/前20窓/公開key/side/全採否/接触回復snapshot/絶対期限は厳密。ATR全leafは限定許容とD整数を別照合し判断SHAへ射影。主生pure旧34完全同値を別確認。"}


def prepare(study: Path, work: Path) -> dict:
    """root許可後に純登録と仮技術観測だけを主準備へ照合する。

    引数: study/work(Path)は正式先/作業先。
    返り値: dictは独立準備証明。entry_index/先着/運用/PnLを呼ばない。
    """
    audit, initial = Audit(), V.sha(Path(__file__))
    _, manifest, master, resolved = guarded_inputs(study, work, audit)
    old = V.read(CONTROL_WORK / "準備点検.json")
    previous = [row for block in old["準備"] for row in block["純信号"] if row["入口ID"] == "3分_E1"]
    saved = {row["イベントID"]: row for row in previous}
    audit.check("旧E1純当時属性一意", len(saved), len(previous))
    stages = []
    for main, block in zip(master["準備"], reconstruct(manifest), strict=True):
        stages.append(compare_preparation(main, block, saved, audit))
        print(Y.json.dumps({"場": block["場"], "独立準備": "原C0/三同登録/接触初回復", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    total = sum(row["原C0登録数"] for row in stages)
    audit.check("元C0全登録数", total, len(saved))
    audit.check("主全登録数", master["原C0登録数"], total)
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, master, audit), "ラベル計算": False, "損益計算": False,
        "旧31C0純登録同値": audit.mismatches == 0, "原C0登録数": total, "場別準備": stages,
        "検証範囲": "独立31原8列からC0とR/L/公開を再構成。E1旧34pure15列とE2/E3識別子以外同値、全仮監視の原順初回接触/strict後key回復/残60分/元期限を別走査。仮fill/125250/PnLは禁止。",
        "限界": "仮監視は純登録ごとに独立した技術観測で実監視受理/保有/注文抑止を混ぜない。全66場は既使用の開発内確認。"}
    (work / "独立準備点検.json").write_text(Y.json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(Y.json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "原C0登録数")}, ensure_ascii=False))
    return proof


# ----------------------------------------
# 実新規の受付・監視・約定は別機械。返済keyだけを他proofへbindする解放入力とする。


def entry_replay(detail: dict, quotes: dict, signals: list[dict], frames: list[dict],
                 audit: Audit, bounds: tuple | None = None) -> dict:
    """原順のquote/bar/signalを合流し、実新規全集合とE3予約を独立構築する。

    引数: detail(dict)は保存一場、quotes(dict)は原正常列、signals/frames(list[dict])は純登録/公開足、audit(Audit)は比較、bounds(tuple|None)は人工時計。
    返り値: dictは独立入口取扱・新規注文/約定・監視記録。保存新規や監視を受理判定へ使わない。
    """
    session, method = detail["場"], detail["候補ID"]
    policy = method.removeprefix("3分_").removesuffix("_XF")
    if policy not in POLICIES:
        raise ValueError("事前三方針だけです")
    start, end, cutoff, force = bounds or S.G.times(session)
    sources = {row["イベントID"]: row for row in signals}
    audit.check(method + session + ":純登録一意", len(sources), len(signals))
    returns = [row for row in detail["約定"] if row["type"].endswith("R")]
    closings = {(row["price_clock"], row["source_line"]): row for row in returns}
    audit.check(method + session + ":返済key一意", len(closings), len(returns))
    return_request_keys = sorted((row["要求時計秒"], row["要求原板行"]) for row in detail["注文"] if row["区分"] == "返済")
    records, orders, openings, watches = [], [], [], []
    watch_counts, watch_reasons = Counter(), Counter()
    held, pending, watch, watch_signal = None, None, None, None
    position_number, canceled = 0, 0

    def iso(now: float) -> str:
        """価格時計を旧固定と同じJST表示へ写す。

        引数: now(float)は価格時計秒。
        返り値: strはISO8601。受信時計へ置き換えない。
        """
        return Y.datetime.fromtimestamp(now, Y.timezone(Y.timedelta(hours=9))).isoformat()

    def watch_log(action: str, now: float, line: int, **data: Any) -> None:
        """独立予約の当時snapshotを全属性保存する。

        引数: action(str)は動作、now/line(float/int)は検出key、data(Any)は終了理由等。
        返り値: None。後続更新で過去の監視記録を変えない。
        """
        watches.append(deepcopy({"場": session, "候補ID": method, "順序": len(watches) + 1,
            "動作": action, "時計秒": now, "原板行": line, "監視": watch, **data}))

    def close_watch(now: float, line: int, reason: str, **data: Any) -> None:
        """予約を一度消費し、実注文への移行又は不可を区別する。

        引数: now/line(float/int)は検出key、reason(str)は理由、data(Any)は補足。
        返り値: None。注文がない満了を新規取消数へ加えない。
        """
        nonlocal watch, watch_signal
        if watch is None:
            return
        if reason != "回復新規要求":
            watch_signal["取扱"] = reason
        watch_counts["監視終了数"] += 1
        watch_reasons[reason] += 1
        watch_log("監視終了", now, line, 終了理由=reason, **data)
        watch, watch_signal = None, None

    def cancel_new(reason: str) -> None:
        """独立に生成した新規待機だけを取り消す。

        引数: reason(str)は寿命又は停止の理由。
        返り値: None。保存orderの状態や存在は判断根拠へ使わない。
        """
        nonlocal pending, canceled
        if pending is None:
            return
        pending["注文"]["状態"] = reason
        pending["取扱"]["取扱"] = reason
        pending = None
        canceled += 1

    def before(now: float, line: int) -> None:
        """新しい価格/足/登録より先に絶対期限と停止を適用する。

        引数: now/line(float/int)は次イベント又はEOFの検出key。
        返り値: None。回復要求から180秒へ寿命を延ばさない。
        """
        if watch is not None:
            reason = "強制期限で監視終了" if now >= force else "新規停止で監視終了" if now >= cutoff else (
                ("未到達で180秒失効" if watch["初回到達出典"] is None else "未回復で180秒失効")
                if now > watch["絶対失効時計秒"] else None)
            if reason is not None:
                close_watch(now, line, reason)
        if pending is not None and (now >= cutoff or now > pending["絶対期限"]):
            cancel_new("新規停止または30秒失効" if policy == "E1" else
                "新規停止または180秒失効" if policy == "E2" else "新規停止または元登録180秒失効")
        if now >= force:
            cancel_new("期限で新規取消")

    def new_request(source: dict, record: dict, now: float, line: int, context: dict | None = None) -> str:
        """独立受付又は初回復から実新規要求を一つ構築する。

        引数: source/record(dict)は登録/取扱、now/line(float/int)は実要求key、context(dict|None)は回復出典。
        返り値: strは独立に計番した注文ID。返済要求keyだけを外部の解放proofへ接続する。
        """
        nonlocal pending
        number = len(orders) + sum(key <= (now, line) for key in return_request_keys) + 1
        order_id = f"{session}_注文{number:04d}"
        reason = "到達後の旧水準回復" if policy == "E3" else "固定入口"
        order = {"注文ID": order_id, "場": session, "入口イベントID": source["イベントID"],
            "区分": "新規", "方向": "買い" if source["side"] == 1 else "売り", "理由": reason,
            "要求時計秒": now, "要求時計JST": iso(now), "要求原板行": line,
            "状態": "待機", "約定時計秒": None, "約定原板行": None}
        if policy == "E3":
            order.update(deepcopy(context))
        else:
            order.update(新規指値価格=source["新規指値価格"], 指値根拠=deepcopy(source["指値根拠"]))
        orders.append(order)
        pending = {"注文": order, "取扱": record, "元登録": source,
            "絶対期限": source["要求時計秒"] + (30 if policy == "E1" else 180)}
        return order_id

    grouped = defaultdict(list)
    for row in signals:
        grouped[(row["要求時計秒"], row["要求原板行"])].append(row)
    quote_stream = ((float(now), int(quotes["line"][index]), 0, index) for index, now in enumerate(quotes["now"]) if start <= now < end)
    bar_stream = sorted(((row["confirm"], row["confirm_line"], 1, row) for row in frames if row["publish"] and start <= row["confirm"] < end), key=lambda row: row[:3])
    signal_stream = sorted((now, line, 2, rows) for (now, line), rows in grouped.items())
    timeline = heapq.merge(quote_stream, bar_stream, signal_stream, key=lambda row: row[:3])
    for now, line, kind, value in timeline:
        before(now, line)
        if kind == 1:
            continue
        if kind == 2:
            both = {row["side"] for row in value} == {1, -1}
            for source in value:
                record = {"イベントID": source["イベントID"], "場": session, "方向": source["方向"],
                    "side": source["side"], "要求時計秒": now, "要求時計JST": iso(now), "要求原板行": line,
                    "確認遅延秒": float(source["確認遅延秒"]), "取扱": "監視受付" if policy == "E3" else "受付"}
                if policy == "E3":
                    record.update(新規要求時計秒=None, 新規要求原板行=None)
                records.append(record)
                if policy == "E3" and len(value) != 1:
                    record["取扱"] = "同判断複数信号見送り"
                elif both:
                    record["取扱"] = "同時両方向見送り"
                elif source["確認遅延秒"] > 30:
                    record["取扱"] = "足確定確認遅延30秒超"
                elif now < start or now >= cutoff or (policy == "E3" and now >= force):
                    record["取扱"] = "新規停止時刻外"
                elif held is not None:
                    record["取扱"] = "建玉中抑止"
                elif pending is not None:
                    record["取扱"] = "注文待機中抑止"
                elif watch is not None:
                    record["取扱"] = "監視中抑止"
                    watch_counts["監視中抑止数"] += 1
                    watch_log("監視中抑止", now, line, 被抑止イベントID=source["イベントID"])
                elif policy == "E3":
                    watch = {"元登録イベントID": source["イベントID"], "side": source["side"],
                        "元登録時計秒": now, "元登録原板行": line, "絶対失効時計秒": now + 180,
                        "監視水準価格": source["新規指値価格"], "監視登録出典": deepcopy(source["指値根拠"]),
                        "初回到達出典": None, "初回回復出典": None}
                    watch_signal = record
                    watch_counts["監視予約数"] += 1
                    watch_log("監視受理", now, line)
                else:
                    new_request(source, record, now, line)
            continue
        bid, ask = float(quotes["bid"][value]), float(quotes["ask"][value])
        closing = closings.get((now, line))
        if closing is not None:
            audit.check(method + str((now, line)) + ":返済解放元", None if held is None else held["イベントID"], closing["entry_event_id"])
            held = None
        if pending is not None and now >= pending["注文"]["要求時計秒"] + 1:
            source, order = pending["元登録"], pending["注文"]
            side = source["side"]
            price = ask if side == 1 else bid
            if policy == "E3" or side * (price - source["新規指値価格"]) <= 0:
                audit.check(method + source["イベントID"] + ":新規時一建玉", held is None, True)
                position_number += 1
                position_id = f"{session}_建玉{position_number:04d}"
                number = len(openings) + sum((row["price_clock"], row["source_line"]) <= (now, line) for row in returns) + 1
                openings.append({"id": f"{session}_約定{number:04d}", "timestamp": iso(now),
                    "type": ("Long" if side == 1 else "Short") + "N", "position_id": position_id,
                    "price": price, "qty": 1, "fee_yen": 11, "method_id": method, "source_line": line,
                    "price_clock": now, "request_timestamp": iso(order["要求時計秒"]),
                    "request_clock": order["要求時計秒"], "request_source_line": order["要求原板行"],
                    "reason": order["理由"], "entry_event_id": source["イベントID"], "order_id": order["注文ID"]})
                pending["取扱"].update(取扱="新規約定", 建玉ID=position_id, 新規時計秒=now, 新規原板行=line)
                order.update(状態="約定", 約定時計秒=now, 約定原板行=line, 約定価格=price, 手数料円=11)
                held = {"イベントID": source["イベントID"], "建玉ID": position_id}
                pending = None
        if watch is None or held is not None or pending is not None or now < watch["元登録時計秒"] + 1:
            continue
        side, level = watch["side"], watch["監視水準価格"]
        current = {"時計秒": now, "原板行": line, "bid": bid, "ask": ask}
        touch = watch["初回到達出典"]
        if touch is None:
            if ask <= level if side == 1 else bid >= level:
                watch["初回到達出典"] = current
                watch_counts["監視初回到達数"] += 1
                watch_log("初回到達", now, line)
            continue
        if (now, line) <= (touch["時計秒"], touch["原板行"]) or not (bid > level if side == 1 else ask < level):
            continue
        watch["初回回復出典"] = current
        watch_counts["監視初回回復数"] += 1
        watch_log("初回回復", now, line)
        reasons = []
        if force - now < 3600:
            reasons.append("回復時残り60分未満")
        if now + 1 > watch["絶対失効時計秒"]:
            reasons.append("回復後1秒が元期限外")
        if reasons:
            close_watch(now, line, "回復時刻不可", 除外理由=reasons)
            continue
        context = {key: deepcopy(watch[key]) for key in ("元登録時計秒", "元登録原板行", "絶対失効時計秒", "監視水準価格", "監視登録出典", "初回到達出典", "初回回復出典")}
        context["新規実効TTL秒"] = watch["絶対失効時計秒"] - now
        watch_signal.update(取扱="回復新規要求", 新規要求時計秒=now, 新規要求原板行=line)
        order_id = new_request(sources[watch["元登録イベントID"]], watch_signal, now, line, context)
        close_watch(now, line, "回復新規要求", 注文ID=order_id)
    before(end, 0)
    cancel_new("EOF新規未約定")
    return {"入口取扱": records, "新規注文": orders, "新規約定": openings, "監視記録": watches,
        "監視件数": {key: watch_counts[key] for key in ("監視予約数", "監視初回到達数", "監視初回回復数", "監視終了数", "監視中抑止数")},
        "監視終了理由数": dict(watch_reasons), "終了監視": int(watch is not None), "終了建玉": int(held is not None), "新規取消数": canceled}


def compare_entry_replay(detail: dict, result: dict, audit: Audit) -> None:
    """独立生成した実受付・全新規・E3監視を保存全属性と照合する。

    引数: detail/result(dict)は保存/独立一場、audit(Audit)は比較先。
    返り値: None。新規欠落があっても集合差を保存し、保存新規を正本へ戻さない。
    """
    name = detail["候補ID"] + detail["場"]
    audit.check(name + ":全入口取扱", detail["入口取扱"], result["入口取扱"])
    audit.check(name + ":全新規注文", [row for row in detail["注文"] if row["区分"] == "新規"], result["新規注文"])
    audit.check(name + ":全新規約定", [row for row in detail["約定"] if row["type"].endswith("N")], result["新規約定"])
    for key, expected in (("新規約定数", len(result["新規約定"])), ("新規取消数", result["新規取消数"]), ("終了建玉", result["終了建玉"])):
        audit.check(name + ":品質:" + key, detail["品質"][key], expected)
    if detail["候補ID"] == "3分_E3_XF":
        audit.check(name + ":全監視記録", detail["監視記録"], result["監視記録"])
        for key, expected in {**result["監視件数"], "監視終了理由数": result["監視終了理由数"], "終了監視": result["終了監視"]}.items():
            audit.check(name + ":品質:" + key, detail["品質"][key], expected)
    else:
        audit.check(name + ":監視記録非追加", "監視記録" in detail, False)


# ----------------------------------------
# 固定後の全case・実新規監視・旧E1全属性を結び、返済と会計は別proofへ分ける。


def check_prepared(study: Path, work: Path, resolved: Path, master: dict, audit: Audit) -> None:
    """成功済み独立準備と固定出典の現版一致を原価格走査前に確認する。

    引数: study/work/resolved(Path)は保存先/実台帳、master(dict)は主準備、audit(Audit)は比較先。
    返り値: None。古版・未完・変更はcacheへ進む前に拒否する。
    """
    proof = V.read(work / "独立準備点検.json")
    expected = {"全件一致": True, "不一致数": 0, "不一致": [], "ラベル計算": False, "損益計算": False,
        "主準備SHA256": V.sha(work / "準備点検.json"), "主コードSHA256": master["コードSHA256"],
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照入力台帳SHA256": V.sha(resolved), "入口参照SHA256": V.sha(study / "入口参照.json"),
        "対照参照SHA256": V.sha(study / "対照参照.json"), "コードSHA256": V.sha(Path(__file__)),
        "追尾コードSHA256": V.sha(Path(__file__).with_name("追尾独立確認.py")), "依存コードSHA256": dependency_pins()}
    for name, value in expected.items():
        audit.check("独立準備bind:" + name, proof[name], value)
    for name, digest in V.read(study / "固定.json")["ファイルSHA256"].items():
        audit.check("正式固定現在:" + name, V.sha(ROOT / name), digest)
    if audit.mismatches:
        raise ValueError("準備/固定/現版の不一致によりcache前停止")


def run(study: Path, work: Path) -> dict:
    """正式完了後に全新先着・実新規監視と旧E1の全属性を検算する。

    引数: study/work(Path)は35正式先/作業先。
    返り値: dictは状態証明。返済解放keyは独立追尾/財務へbindする保存入力と明示する。
    """
    if not (study / "固定.json").exists() or not (study / "結果.json").exists():
        raise ValueError("root固定・正式完了後だけ起動できます")
    audit, initial = Audit(), V.sha(Path(__file__))
    _, manifest, master, resolved = guarded_inputs(study, work, audit)
    check_prepared(study, work, resolved, master, audit)
    old_prepare = V.read(CONTROL_WORK / "準備点検.json")
    old_pure = {row["イベントID"]: row for block in old_prepare["準備"] for row in block["純信号"] if row["入口ID"] == "3分_E1"}
    names = ("入口事例", "全運用詳細", "追尾")
    records, hashes = {}, {}
    artifacts = {Path(row["パス"]).name: row for row in V.read(study / "作業成果物.json")["ファイル"]}
    audit.check("新三成果物集合", set(artifacts), {name + ".jsonl.gz" for name in names})
    grouped = {name: defaultdict(list) for name in names}
    for name in names:
        path = work / (name + ".jsonl.gz")
        records[name], hashes[name] = B.compressed_rows(path)
        artifact = artifacts[path.name]
        audit.check(name + ":宣言path", (ROOT / artifact["パス"]).resolve(), path.resolve())
        audit.check(name + ":圧縮SHA", artifact["圧縮SHA256参考"], V.sha(path))
        audit.check(name + ":圧縮bytes", artifact["圧縮バイト"], path.stat().st_size)
        audit.check(name + ":展開SHA", artifact["展開内容SHA256"], hashes[name])
        for row in records[name]:
            grouped[name][row["場"]].append(row)
    previous_cases, previous_case_sha = B.compressed_rows(CONTROL_WORK / "入口事例.jsonl.gz")
    previous_details, _ = B.compressed_rows(CONTROL_WORK / "全運用詳細.jsonl.gz")
    previous_logs, _ = B.compressed_rows(CONTROL_WORK / "追尾.jsonl.gz")
    old_cases = {row["イベントID"]: row for row in previous_cases if row["入口ID"] == "3分_E1"}
    old_details = {row["場"]: row for row in previous_details if row["候補ID"] == "3分_E1_XF"}
    old_trace = defaultdict(list)
    for row in previous_logs:
        if row["候補ID"] == "3分_E1_XF":
            old_trace[row["場"]].append(row)
    case_ids = [(row["入口ID"], row["イベントID"]) for row in records["入口事例"]]
    audit.check("新case全一意", len(case_ids), len(set(case_ids)))
    detail_pairs = [(row["場"], row["候補ID"]) for row in records["全運用詳細"]]
    audit.check("正式場候補一意", len(detail_pairs), len(set(detail_pairs)))
    audit.check("全3x66場候補集合", set(detail_pairs), {(row["session"], cid) for row in manifest["entries"] for cid in OPERATIONS})
    stages, controls, fsm_summaries = [], [], []
    label_counts = {policy: 0 for policy in POLICIES}
    paired = {"E1約定E2未約定数": 0, "E1E2約定key価格相違数": 0, "E3約定E2未約定数": 0}
    for main, block in zip(master["準備"], reconstruct(manifest), strict=True):
        stages.append(compare_preparation(main, block, old_pure, audit))
        session, period = block["場"], block["期間"]
        quotes = block["_正常気配"]
        _, _, cutoff, deadline = S.G.times(session)
        anchors = {row["旧C0イベントID"]: row for row in block["登録台帳"]}
        saved_cases = {row["イベントID"]: row for row in grouped["入口事例"][session]}
        audit.check(session + ":全登録ID集合", set(saved_cases), {row["イベントID"] for row in block["純信号"]})
        labels = defaultdict(dict)
        policy_signals = {policy: [] for policy in POLICIES}
        for signal in block["純信号"]:
            policy = signal["入口ID"].removeprefix("3分_")
            policy_signals[policy].append(signal)
            original = signal["イベントID"][:-3] + "_C0"
            label = label_direct(quotes, signal, cutoff, deadline, policy)
            labels[original][policy] = label
            expected = {**deepcopy(signal), "期間": period,
                "要求時計JST": Y.datetime.fromtimestamp(signal["要求時計秒"], Y.timezone(Y.timedelta(hours=9))).isoformat(),
                "旧C0イベントID": original, "登録出典": deepcopy(anchors[original]), **label}
            if policy == "E3":
                observed = observation(quotes, signal, cutoff, deadline)
                expected.update(回復観測=observed, 新規要求時計秒=observed["新規要求時計秒"], 新規要求原板行=observed["新規要求原板行"])
            case = saved_cases.get(signal["イベントID"])
            audit.check(signal["イベントID"] + ":全case原列直接先着", case, expected)
            if policy == "E1":
                previous = old_cases.get(signal["イベントID"])
                audit.leaf(signal["イベントID"] + ":旧34E1全case完全同値", case, previous, case == previous)
            label_counts[policy] += 1
        for original, triple in labels.items():
            first, second, third = (triple[policy] for policy in POLICIES)
            f1, f2, f3 = (row["新規価格"] is not None for row in (first, second, third))
            paired["E1約定E2未約定数"] += int(f1 and not f2)
            paired["E3約定E2未約定数"] += int(f3 and not f2)
            audit.check(original + ":純E1subsetE2", not f1 or f2, True)
            audit.check(original + ":純E3subsetE2", not f3 or f2, True)
            if f1 and f2:
                left = first["新規時計秒"], first["新規原板行"], first["新規価格"]
                right = second["新規時計秒"], second["新規原板行"], second["新規価格"]
                paired["E1E2約定key価格相違数"] += int(left != right)
                audit.check(original + ":E1成立時E2同key価格", left, right)
        for detail in grouped["全運用詳細"][session]:
            cid = detail["候補ID"]
            policy = cid.removeprefix("3分_").removesuffix("_XF")
            audit.check(cid + session + ":期間", detail["品質"]["期間"], period)
            fsm = entry_replay(detail, quotes, policy_signals[policy], block["_公開足"], audit)
            compare_entry_replay(detail, fsm, audit)
            fsm_summaries.append({"場": session, "候補ID": cid, "純登録数": len(policy_signals[policy]),
                "実新規注文数": len(fsm["新規注文"]), "実新規約定数": len(fsm["新規約定"]),
                "監視記録数": len(fsm["監視記録"]), "監視記録内容SHA256": canonical_sha(fsm["監視記録"]),
                "終了監視": fsm["終了監視"], "終了建玉": fsm["終了建玉"]})
            if policy == "E1":
                trace = [row for row in grouped["追尾"][session] if row["候補ID"] == cid]
                audit.leaf(session + ":旧34E1全運用完全同値", detail, old_details[session], detail == old_details[session])
                audit.leaf(session + ":旧34E1全追尾完全同値", trace, old_trace[session], trace == old_trace[session])
                controls.append({"場": session, "候補ID": cid, "全運用同値": detail == old_details[session],
                    "全追尾同値": trace == old_trace[session], "旧識別子全運用内容SHA256": canonical_sha(detail),
                    "旧識別子追尾内容SHA256": canonical_sha(trace)})
        print(Y.json.dumps({"場": session, "独立状態": "全登録/新直接先着/実監視新規/旧E1対照", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    total = sum(row["原C0登録数"] for row in stages)
    audit.check("新全3case数", len(records["入口事例"]), total * 3)
    for policy in POLICIES:
        audit.check(policy + ":全原登録先着数", label_counts[policy], total)
    result = V.read(study / "結果.json")
    for name, expected in {"全66場既使用": True, "入口評価数": 3, "運用候補数": 3, "現方針運用候補数": 3,
            "入口125250評価の変更": True, "表示固定ID": list(OPERATIONS)}.items():
        audit.check("正式結果:" + name, result[name], expected)
    audit.check("E1保存対照証明", V.read(study / "E1対照同値.json"), {"全件一致": True, "旧先着全件同値": True,
        "場候補数": len(controls), "照合": controls, "対照参照SHA256": V.sha(study / "対照参照.json")})
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, master, audit), "場別準備": stages,
        "原C0登録数": total, "全先着直接照合件数": sum(label_counts.values()), "方針別先着直接照合件数": label_counts,
        "仮新規対応不変条件": paired, "旧E1全case同値数": label_counts["E1"], "旧34全属性同値場数": len(controls),
        "実新規監視照合": {"場候補数": len(fsm_summaries), "独立実新規注文数": sum(row["実新規注文数"] for row in fsm_summaries),
            "独立実新規約定数": sum(row["実新規約定数"] for row in fsm_summaries), "監視記録数": sum(row["監視記録数"] for row in fsm_summaries),
            "保存返済keyは解放入力": True, "場候補別": fsm_summaries},
        "保存入口事例数": len(records["入口事例"]), "保存運用詳細数": len(records["全運用詳細"]), "保存追尾数": len(records["追尾"]),
        "成果物照合": {name + ".jsonl.gz": {"展開内容SHA256": hashes[name], "行数": len(records[name])} for name in names},
        **{name + "展開SHA256": value for name, value in hashes.items()}, "旧34入口事例展開SHA256": previous_case_sha,
        "共有入口事例展開SHA256": V.read(CONTROL_STUDY / "状態独立確認.json")["共有入口事例展開SHA256"],
        "結果SHA256": V.sha(study / "結果.json"), "固定SHA256": V.sha(study / "固定.json"),
        "独立準備SHA256": V.sha(work / "独立準備点検.json"),
        "検証範囲": "元8列から独立31の原足/CCI/M/C0/固定水準/公開を再構成。全2403caseの仮新規と125250を原正常価格列で直接走査。実新規はquote/bar/signal別機械で監視受理/抑止/初到達/初回復/時間不可の一回消費/絶対期限/初回fillを独立生成し全新規注文・約定・取扱・監視記録を照合。旧E1全case/全66ledger/traceは全属性同値。",
        "限界": "実新規受理機械の位置解放は保存返済fill keyが入力。全返済の最初要求・全保有XF線は独立追尾、最初+1秒返済BBOとDecimal/品質は独立財務へSHA接続する。仮先着の独立参加に実監視抑止を混ぜず、既使用66場を未見評価としない。"}
    (work / "状態独立確認.json").write_text(Y.json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(Y.json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "全先着直接照合件数", "旧34全属性同値場数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """root許可後の非損益準備又は固定後正式監査だけを起動する。

    引数: なし。CLIの--study/--work/--prepare/--実行許可を読む。
    返り値: None。不一致又は無指定は非0終了。
    """
    parser = argparse.ArgumentParser(description="00035原順到達回復と実監視の独立確認")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--実行許可", action="store_true")
    args = parser.parse_args()
    proof = prepare(args.study.resolve(), args.work.resolve()) if args.prepare else run(args.study.resolve(), args.work.resolve())
    if not proof["全件一致"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
