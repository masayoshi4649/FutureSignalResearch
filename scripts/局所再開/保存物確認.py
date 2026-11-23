"""50の新P0/P1保存物を独立検査する。入口・指標・全tick運用は再生しない。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
from urllib.parse import urlencode, urljoin

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00050_15分定時の局所再開"
WORK = ROOT / "work/局所再開/00050"
OLD = ROOT / "study/00049_15分定時の序盤帯反応"
OLDWORK = ROOT / "work/定時帯反応/00049"
POLICIES = ("P0", "P1")
PERIODS = ("学習", "条件選択", "後続検査")
BINDING_FIELDS = ("slot_id", "session", "policy", "scheduled", "time", "line", "side", "role")
SOURCE_FIELDS = ("index", "minutes", "start", "end", "confirm", "confirm_line", "publish", "missing", "open", "high", "low", "close")
CONTROL_HASHES = {
    "study/00049_15分定時の序盤帯反応/結果.json": "01eb65eed125e083c78d7c122d132598131cb60f9c40283f28873e906d08c281",
    "work/定時帯反応/00049/定時判断と運用.jsonl.gz": "393179a81549d4162aacf0669823882cce122d89db9eae7f7b22972574cceb28",
    "work/定時帯反応/00049/入口先着.jsonl.gz": "f2d20e135de8b8265f15d7d15016da3b99d0cbf4b791326bd14b7a21571d7ecd",
    "study/00049_15分定時の序盤帯反応/保存物確認.json": "0d5390ce9d1cfd6cfaa49bd87ec409f05c3408a7831707d1b601a6696a9bbc40",
    "study/00049_15分定時の序盤帯反応/期限同秒確認.json": "d5cf64cd1ee645810e28188fc03fa849dc9d9d96746fa6a66a6470bd14a8bac3",
    "scripts/定時帯反応/保存物確認.py": "7efb6b8f4367f7d24cb0320fd8b8e40d9f17447ce5e4d7a6bbb99c3829ed9e85",
    "scripts/定時帯反応/期限同秒確認.py": "1898ce6c0f6ccac8f7b3ea46e11813b28dcaf1dcba1b9a22b0400b9ae28e5681",
}


def load(path: Path, name: str):
    """固定補助を固有名で読み、呼出し先の大域値を変更しない。

    引数: path(Path)はPython、name(str)は読込名。
    返り値: ModuleTypeは読込結果。主モデルのrunは呼ばない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def helpers() -> tuple:
    """旧監査の純検査と、期限初行を含む先着期待値を取得する。

    引数: なし。
    返り値: tupleはA49/L49モジュール。既知の旧saved_label_expectedは呼ばない。
    """
    return (load(ROOT / "scripts/定時帯反応/保存物確認.py", "局所再開_固定監査49"),
            load(ROOT / "scripts/定時帯反応/期限同秒確認.py", "局所再開_固定期限49"))


def check_sources(value: object, slot: dict, audit, path: str = "出典") -> int:
    """保存された足の場・予定終了・公開keyを再帰的に検査する。

    引数: value(object)は保存特徴、slot(dict)は現在判断、audit(Audit)は記録、path(str)は識別。
    返り値: intは足出典の検査件数。価格パターン・指標・イベント採否は再計算しない。
    """
    count = 0
    if isinstance(value, dict):
        if set(SOURCE_FIELDS) <= set(value):
            count += 1
            key = (value["confirm"], value["confirm_line"])
            request = (slot["time"], slot["line"] if slot["line"] is not None else -1)
            audit.check(path + ":当場", value.get("session"), slot["session"])
            audit.check(path + ":予定終了以前", value["end"] <= slot["scheduled"], True)
            audit.check(path + ":公開済", value["publish"], True)
            audit.check(path + ":終了後公開", value["confirm"] >= value["end"], True)
            audit.check(path + ":判断key以前", key <= request, True)
        if {"trigger_end", "trigger_key"} <= set(value):
            end, key = value["trigger_end"], tuple(value["trigger_key"])
            audit.check(path + ":発動終了は予定以前", end <= slot["scheduled"], True)
            audit.check(path + ":発動公開は判断以前", key <= (slot["time"], slot["line"] if slot["line"] is not None else -1), True)
            trigger = value.get("trigger")
            if isinstance(trigger, dict) and set(SOURCE_FIELDS) <= set(trigger):
                audit.check(path + ":発動出典時計", (trigger["end"], trigger["confirm"], trigger["confirm_line"]), (end, *key))
            di = value.get("DI出典", value.get("DI"))
            if isinstance(di, dict) and "source" in di:
                di = di["source"]
            if isinstance(di, dict) and set(SOURCE_FIELDS) <= set(di):
                audit.check(path + ":発動時のDI終了", di["end"] <= end, True)
                audit.check(path + ":発動時のDI公開", (di["confirm"], di["confirm_line"]) <= key, True)
        for prefix in ("origin", "failure", "trigger"):
            foot, di = value.get(prefix), value.get(prefix + "_di")
            upper = di.get("source") if isinstance(di, dict) else None
            if isinstance(foot, dict) and isinstance(upper, dict) and set(SOURCE_FIELDS) <= set(foot) and set(SOURCE_FIELDS) <= set(upper):
                audit.check(path + ":" + prefix + "の当時上位終了", upper["end"] <= foot["end"], True)
                audit.check(path + ":" + prefix + "の当時上位公開", (upper["confirm"], upper["confirm_line"]) <= (foot["confirm"], foot["confirm_line"]), True)
        for name, child in value.items():
            count += check_sources(child, slot, audit, path + "/" + name)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            count += check_sources(child, slot, audit, path + "/" + str(index))
    return count


def operation_summary(rows: list[dict], target: str, source) -> dict:
    """検算済み現金と保存判断から、期間の費用・活動を別集計する。

    引数: rows(list[dict])は一候補の独立会計、target(str)は期間、source(ModuleType)は固定暦補助。
    返り値: dictは予定分母・活動・支持・品質・現金・役割等。未解消元本は利益へ算入しない。
    """
    chosen = [row for row in rows if source.span(row["session"]) == target]
    decisions = [decision for row in chosen for decision in row["decisions"]]
    closed = [{**position, "session": row["session"]} for row in chosen for position in row["closed"]]
    counts = Counter(decision["action"] for decision in decisions)
    n, waiting, invalid = len(decisions), counts["待ち"], counts["判定不能"]
    ledger = {str(fee): float(sum(Decimal(str(row["ledger"][str(fee)])) for row in chosen)) for fee in (0, 5, 10)}
    observed = {str(fee): float(sum(Decimal(str(row["observed"][str(fee)])) for row in chosen)) for fee in (0, 5, 10)}
    cautions = [row["session"] for row in chosen if row["caution"]]
    days, sessions = len({p["session"][:10] for p in closed}), len({p["session"] for p in closed})
    buys = sum(position["side"] == 1 for position in closed)
    minimum = (20, 6, 10, 5, 5) if target == "学習" else (10, 3, 6, 3, 3)
    support = all(a >= b for a, b in zip((len(closed), days, sessions, buys, len(closed) - buys), minimum))
    active = bool(n) and 2 * (waiting + invalid) <= n
    flat = [decision for decision in decisions if not decision["holding"] and decision["pending_kind"] is None]
    equity, peak, drawdown = Decimal(0), Decimal(0), Decimal(0)
    for position in sorted(closed, key=lambda row: (row["exit_time"], row["exit_line"])):
        equity += Decimal(str(position["pnl5"]))
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {"予定枠": n, "判断別": dict(counts), "待ち数": waiting, "主待ち率": waiting / n if n else None,
            "判定不能": invalid, "待ち率保守上限": (waiting + invalid) / n if n else None,
            "全枠判定可能": invalid == 0, "活動適格": active, "完結数": len(closed),
            "空き枠待ち率": waiting / len(flat) if flat else None,
            "買い": buys, "売り": len(closed) - buys, "日数": days, "場数": sessions,
            "品質注意場": cautions, "未解消": sum(row["unresolved"] for row in chosen),
            "完結観測額円": observed, "台帳観測額円": ledger,
            "全体確定額円": {key: None if cautions else amount for key, amount in ledger.items()},
            "費用支持": support, "費用適格": support and not cautions and ledger["5"] > 0,
            "役割別完結": {role: {"件数": sum(p["role"] == role for p in closed),
                           "観測純額5": sum(p["pnl5"] for p in closed if p["role"] == role)} for role in ("順行", "反転")},
            "起動後赤字件数5": sum(bool(p["arm"]) and p["pnl5"] < 0 for p in closed),
            "利益起動件数": sum(bool(p["arm"]) for p in closed), "実250到達件数": sum(p["mfe"] >= 250 for p in closed),
            "返済理由": dict(Counter(p["exit_reason"] for p in closed)),
            "定時外返済件数": sum(p["exit_time"] not in {d["time"] for d in decisions} for p in closed),
            "平均保有秒": sum(p["exit_time"] - p["entry_time"] for p in closed) / len(closed) if closed else None,
            "完結確定系列最大DD5円": float(drawdown),
            "完結黒字率5": sum(p["pnl5"] > 0 for p in closed) / len(closed) if closed else None,
            "売買別損益5": {"買い": sum(p["pnl5"] for p in closed if p["side"] == 1),
                        "売り": sum(p["pnl5"] for p in closed if p["side"] == -1)}}


def coverage_summary(slots: list[dict], decisions: list[dict]) -> dict:
    """保存された機会段階・遷移・消費の表示を集計する。

    引数: slots(list[dict])は一候補一期間の保存判断、decisions(list[dict])は実判断。
    返り値: dictは排他的な段階等。同時計基準は別関数で照合し、監視機械を再生しない。
    """
    selected = [slot for slot in slots if slot["ready"] and slot["side"]]
    actions = [action for slot in slots for action in slot["diagnostic"]["actions"]]
    consumed = [event for slot in slots for event in slot["diagnostic"]["consumed_events"]]
    ages = [event["age_seconds"] for event in consumed]
    stages = Counter()
    for slot in slots:
        diagnostic = slot["diagnostic"]
        current, upper, band = slot.get("current"), slot.get("upper", {}), slot.get("OR")
        background = False
        if current and band and band.get("ready") and upper.get("ready"):
            direction = upper["direction"]
            if direction in (-1, 1):
                edge = band["high"] if direction == 1 else band["low"]
                background = direction * (Fraction(current["close"]) - Fraction(edge)) > 5
        if not slot["ready"]:
            stage = "判定不能"
        elif slot["side"]:
            stage = "純入口"
        elif slot["reason"] == "同枠複数発動WAIT":
            stage = "同枠競合"
        elif diagnostic["consumed_events"]:
            stage = "発動済みだが失効"
        elif diagnostic["T_watch"]:
            stage = "T再開監視中"
        elif slot["policy"] == "P1" and diagnostic["R_watch"]:
            stage = "R復帰又は確認監視中"
        else:
            stage = "T背景あり調整待ち" if background else "T背景不成立かつ発動なし"
        stages[stage] += 1
    return {"予定枠": len(slots), "入口理由": dict(Counter(slot["reason"] for slot in slots)),
            "純入口": len(selected), "純入口役割": dict(Counter(slot["role"] for slot in selected)),
            "実判断": dict(Counter(row["action"] for row in decisions)), "機会段階": dict(stages),
            "足遷移": dict(Counter(action["action"] for action in actions)), "消費発動数": len(consumed),
            "消費時有効発動数": sum(bool(event["active"]) for event in consumed),
            "消費時失効理由": dict(Counter(event["cancel_reason"] for event in consumed if not event["active"])),
            "消費発動の古さ秒": {"件数": len(ages), "平均": sum(ages) / len(ages) if ages else None, "最大": max(ages) if ages else None}}


def check_slot_sources(slot: dict, audit) -> int:
    """新特徴の公開出典、現足固定D、保存発動の古さを確認する。

    引数: slot(dict)は保存された一予定枠、audit(Audit)は照合先。
    返り値: intは検査した足出典の個数。新入口の採否機械や数値銀行は再現しない。
    """
    count = check_sources(slot, slot, audit, slot["session"] + slot["policy"] + str(slot["scheduled"]))
    if slot["D"] is not None:
        units = Fraction(float(slot["atr"])) / 5
        rounded = -(-units.numerator // units.denominator) * 5
        audit.check("入口ATRの5pt切上固定D", slot["D"], min(125, max(5, rounded)))
    if slot["ready"]:
        current, previous = slot["current"], slot["previous"]
        audit.check("準備済み3分の鮮度と幅", (current["minutes"], current["end"] - current["start"], current["missing"], slot["scheduled"] - current["end"] <= 180), (3, 180, 0, True))
        audit.check("現前3分の隣接", (previous["index"] + 1, previous["end"]), (current["index"], current["start"]))
        audit.check("現前3分公開key順", (previous["confirm"], previous["confirm_line"]) < (current["confirm"], current["confirm_line"]), True)
        upper = slot["upper"]["source"]
        audit.check("準備済み上位の鮮度と幅", (upper["minutes"], upper["end"] - upper["start"], upper["missing"], slot["scheduled"] - upper["end"] <= 900, slot["upper"]["ready"]), (15, 900, 0, True, True))
    for event in slot["diagnostic"]["consumed_events"]:
        audit.check("消費発動の古さ出典", event["age_seconds"], slot["scheduled"] - event["trigger_end"])
    return count


def check_periods(accounts: list[dict], labels: dict, slots: dict, baseline: list[dict], result: dict, source, audit) -> None:
    """新二候補だけの全期間・役割・同時計基準を保存結果へ照合する。

    引数: accounts(list[dict])は独立会計、labels/slots(dict)は候補別保存列、baseline(list[dict])は固定49B±、result(dict)は新結果、source(ModuleType)/audit(Audit)は補助。
    返り値: None。旧S1は別の保存対照一致であり、このループで再評価しない。
    """
    baseline_map = {(row["session"], row["slot_id"], row["side"]): row for row in baseline if row["policy"] in ("B+", "B-")}
    audit.check("旧時刻基準の一意", len(baseline_map), len([r for r in baseline if r["policy"] in ("B+", "B-")]))
    for policy in POLICIES:
        candidate_accounts = [row for row in accounts if row["candidate"] == policy]
        for period in PERIODS:
            expected_entry = source.entry_summary(labels[policy], period)
            actual = result["候補"][policy][period]
            audit.check(policy + period + ":全入口・薄化", actual["入口"], expected_entry)
            expected_operation = operation_summary(candidate_accounts, period, source)
            audit.check(policy + period + ":全運用集計属性", actual["運用"], expected_operation)
            for key, value in expected_operation.items():
                audit.check(policy + period + ":費用・活動" + key, actual["運用"][key], value)
            audit.check(policy + period + ":同時適格", actual["同時適格"], expected_entry["70目標"] and expected_operation["活動適格"] and expected_operation["費用適格"])
            for role in ("順行", "反転"):
                expected_role = source.entry_summary([r for r in labels[policy] if r["role"] == role], period)
                audit.check(policy + period + role + ":役割別入口", result["役割別入口"][policy][period][role], expected_role)
            chosen = [s for s in slots[policy] if source.span(s["session"]) == period]
            selected = [s for s in chosen if s["ready"] and s["side"]]
            decisions = [d for row in candidate_accounts if source.span(row["session"]) == period for d in row["decisions"]]
            coverage = coverage_summary(chosen, decisions)
            audit.check(policy + period + ":被覆全属性集合", set(result["被覆診断"][policy][period]), {*coverage, "同時刻基準"})
            audit.check(policy + period + ":機会段階の排他全分母", sum(coverage["機会段階"].values()), len(chosen))
            for key, value in coverage.items():
                audit.check(policy + period + ":被覆" + key, result["被覆診断"][policy][period][key], value)
            for direction, sign in (("実方向", 1), ("逆方向", -1)):
                paired = []
                for slot in selected:
                    row = baseline_map.get((slot["session"], slot["slot_id"], sign * slot["side"]))
                    audit.check(policy + ":同時計基準存在", row is not None, True)
                    if row is not None:
                        audit.check(policy + ":同時計の価格出典", (row["time"], row["line"], row["scheduled"]), (slot["time"], slot["line"], slot["scheduled"]))
                        paired.append(row)
                audit.check(policy + period + direction + ":同時計基準集計", result["被覆診断"][policy][period]["同時刻基準"][direction], source.entry_summary(paired, period))
    expected_adopted = [p for p in POLICIES if all(result["候補"][p][period]["同時適格"] for period in PERIODS[:2])]
    audit.check("新候補だけの採用", result["採用"], expected_adopted)


def check_control(result: dict, source, audit) -> dict:
    """旧S1と期限補足を、再計算せず保存値・既知SHAへ結ぶ。

    引数: result(dict)は新結果、source(ModuleType)はJSON/SHA読取、audit(Audit)は記録。
    返り値: dictは旧正本のSHA。旧詳細・S1先着の戦略再生はしない。
    """
    current = {}
    for name, digest in CONTROL_HASHES.items():
        current[name] = source.sha(ROOT / name)
        audit.check("旧保存対照SHA:" + name, current[name], digest)
    old_result = source.read(OLD / "結果.json")
    audit.check("旧S1全結果strictコピー", result["候補"]["S1"], old_result["候補"]["S1"])
    audit.check("旧S1役割入口strictコピー", result["役割別入口"]["S1"], old_result["役割別入口"]["S1"])
    expected_reference = {"候補": "S1", "結果": "study/00049_15分定時の序盤帯反応/結果.json", "結果SHA256": CONTROL_HASHES["study/00049_15分定時の序盤帯反応/結果.json"], "再計算": False}
    audit.check("旧S1参照出典", result["対照参照"], expected_reference)
    return current


def check_api(base: str | None, resources: list[dict], accounts: list[dict], source, audit) -> dict:
    """Viewer全資源と新候補各一代表を、保存約定と独立現金へ照合する。

    引数: base(str|None)は任意のAPI、resources(list[dict])は新旧198資源、accounts(list[dict])は新会計、source(ModuleType)/audit(Audit)は補助。
    返り値: dictは実行範囲。未接続は保存物検査と分けて明記する。
    """
    if not base:
        return {"実行": False, "理由": "--viewer-url未指定。APIは未検証、新132保存約定は全件照合"}
    query = {"catalog_path": (STUDY / "一覧.resources.json").relative_to(ROOT).as_posix()}
    listed, _, _ = source.fetch_json(base + "/api/resources?" + urlencode(query))
    audit.check("API全198集合", {r["id"] for r in listed["resources"]}, {r["id"] for r in resources})
    audit.check("API198一意", len(listed["resources"]), 198)
    representatives = []
    for policy in POLICIES:
        account = sorted([r for r in accounts if r["candidate"] == policy], key=lambda r: (-abs(r["ledger"]["5"]), r["session"]))[0]
        resource = next(r for r in resources if r["session"] == account["session"] and r["method_id"] == policy)
        params = {**query, "resource": resource["id"], "interval": "5", "price": "last", "width": 1000, "height": 700}
        meta, _, _ = source.fetch_json(base + "/api/chart?" + urlencode(params))
        data, raw, headers = source.fetch_json(urljoin(base + "/", meta["data_url"]))
        audit.check("API本文SHA", hashlib.sha256(raw).hexdigest(), meta["data_sha256"])
        audit.check("APIヘッダSHA", headers.get("x-chart-data-sha256"), meta["data_sha256"])
        audit.check("API数値集計", data["summary"], meta["summary"])
        audit.check("API独立台帳円5", Decimal(str(data["summary"]["realized_pnl_yen"])), Decimal(str(account["ledger"]["5"])))
        trades = list(source.json_rows(ROOT / resource["pnl_path"]))
        audit.check("API片数", len(data["events"]), len(trades))
        for seq, (fill, event) in enumerate(zip(trades, data["events"]), 1):
            for key in ("type", "qty", "position_id", "method_id", "price"):
                audit.check("API約定" + key, event[key], fill[key])
            audit.check("API物理行", event["sequence"], seq)
            audit.check("API約定時計", abs(event["timestamp_ms"] - datetime.fromisoformat(fill["timestamp"]).timestamp() * 1000) <= .001, True)
        representatives.append({"候補": policy, "場": account["session"], "資源ID": resource["id"], "台帳観測額5円": account["ledger"]["5"], "数値SHA256": meta["data_sha256"]})
    return {"実行": True, "接続先": base, "全資源数": len(listed["resources"]), "新候補代表": representatives,
            "代表規約": "候補別の最大絶対台帳額場。売買条件へ不使用。旧S1の再評価なし"}


# ----------------------------------------
# rootの市場実行後に限り、新P0/P1の保存物を一度検査する。

def run(viewer_url: str | None = None) -> dict:
    """固定された新二候補を原BBO・現金・純先着へ照合し一度保存する。

    引数: viewer_url(str|None)は任意のViewer API。
    返り値: dictは合否と範囲。モデル・指標・全tick運用は呼ばず、不一致でも原証明を上書きしない。
    """
    destination = STUDY / "保存物確認.json"
    if destination.exists():
        raise FileExistsError("保存物確認.jsonを上書きしません")
    source, label_helper = helpers()
    audit = source.Audit()
    paths = [STUDY / n for n in ("結果.json", "固定.json", "条件.json", "入力台帳.json", "一覧.resources.json")]
    paths += [WORK / "定時判断と運用.jsonl.gz", WORK / "入口先着.jsonl.gz", source.MANIFEST, Path(__file__)]
    paths += [ROOT / name for name in CONTROL_HASHES]
    before = {path.relative_to(ROOT).as_posix(): source.sha(path) for path in paths}
    fixed, result = source.read(STUDY / "固定.json"), source.read(STUDY / "結果.json")
    for name, digest in fixed["ファイルSHA256"].items():
        audit.check("固定出典:" + name, source.sha(ROOT / name), digest)
    audit.check("監査自身の固定包含", Path(__file__).relative_to(ROOT).as_posix() in fixed["ファイルSHA256"], True)
    audit.check("結果の固定bind", result["固定SHA256"], source.sha(STUDY / "固定.json"))
    audit.check("試行", result["試行"], 50)
    audit.check("保存候補3群", set(result["候補"]), {"S1", *POLICIES})
    control = check_control(result, source, audit)
    pointer = source.read(STUDY / "入力台帳.json")
    audit.check("入力台帳参照", (STUDY / pointer["参照"]).resolve(), source.MANIFEST.resolve())
    audit.check("入力台帳SHA", source.sha(source.MANIFEST), pointer["SHA256"])
    manifest = source.read(source.MANIFEST)
    entries = {row["session"]: row for row in manifest["entries"]}
    audit.check("予約66場", len(entries), 66)
    catalog = source.read(STUDY / "一覧.resources.json")
    resources = catalog["resources"]
    resource_map = {(row["session"], row["method_id"]): row for row in resources}
    audit.check("全198保存資源", set(resource_map), {(s, p) for s in entries for p in ("S1", *POLICIES)})
    audit.check("全198一意", len(resources), 198)
    audit.check("資源ID一意", len({r["id"] for r in resources}), 198)
    old_catalog = source.read(OLD / "一覧.resources.json")
    for resource in old_catalog["resources"]:
        if resource["method_id"] == "S1":
            expected = {**resource, "pnl_path": (OLD / resource["pnl_path"]).resolve().relative_to(ROOT.resolve()).as_posix(), "title": resource["session"] + " S1 固定49対照"}
            audit.check("旧S1資源strict参照", resource_map[resource["session"], "S1"], expected)
            path = ROOT / expected["pnl_path"]
            audit.check("旧S1約定の固定包含", expected["pnl_path"] in fixed["ファイルSHA256"], True)
            audit.check("旧S1約定SHA", source.sha(path), fixed["ファイルSHA256"][expected["pnl_path"]])
    for resource in resources:
        audit.check("資源の商品と費用基準", (resource["symbol"], resource["product"], resource["point_value"], resource["pnl_basis"]), ("NK225", "NK225micro", 10, "net"))
    labels, slots = {p: [] for p in POLICIES}, {p: [] for p in POLICIES}
    by_session = defaultdict(list)
    for row in source.json_rows(WORK / "入口先着.jsonl.gz"):
        audit.check("新先着候補のみ", row["policy"] in POLICIES, True)
        if row["policy"] in labels:
            labels[row["policy"]].append(row)
            by_session[row["session"]].append(row)
    detail_rows = defaultdict(list)
    for block in source.json_rows(WORK / "定時判断と運用.jsonl.gz"):
        detail_rows[block["session"]].append(block)
    audit.check("新詳細全66場", set(detail_rows), set(entries))
    audit.check("新先着は予約場のみ", set(by_session) <= set(entries), True)
    cache_pins, viewer_pins, accounts, source_count = {}, {}, [], 0
    for session, entry in entries.items():
        tape, path, digest = source.load_tape(entry, audit)
        cache_pins[path] = digest
        blocks = detail_rows[session]
        audit.check(session + ":新二候補のみ", [b["policy"] for b in blocks], list(POLICIES))
        bindings = {}
        for block in blocks:
            policy, op = block["policy"], block["operation"]
            audit.check("詳細候補と運用ID", op["candidate_id"], policy)
            audit.check("詳細場と運用場", op["session"], session)
            audit.check("品質確定旗と理由", op["quality"]["損益確定可能"], not bool(op["quality"]["損益注意理由"]))
            source.check_decisions(block, tape, audit)
            source.check_orders(op, tape, audit)
            source.check_trail(op, tape, audit)
            path = ROOT / resource_map[session, policy]["pnl_path"]
            audit.check("新約定保存先", path.resolve(), (STUDY / "viewer" / f"{policy}_{session}.trades.jsonl").resolve())
            viewer_pins[path.relative_to(ROOT).as_posix()] = source.sha(path)
            accounts.append(source.check_cash(op, list(source.json_rows(path)), tape, audit))
            slots[policy].extend(block["slots"])
            for slot in block["slots"]:
                audit.check("枠候補と場", (slot["policy"], slot["session"]), (policy, session))
                source_count += check_slot_sources(slot, audit)
                if slot["ready"] and slot["side"]:
                    bindings[policy, slot["slot_id"]] = {key: slot[key] for key in BINDING_FIELDS}
        actual = by_session[session]
        audit.check(session + ":全新先着集合", {(r["policy"], r["slot_id"]) for r in actual}, set(bindings))
        audit.check(session + ":全新先着一意", len(actual), len(bindings))
        _, force, _, _ = source.calendar(session)
        for row in actual:
            binding = bindings.get((row["policy"], row["slot_id"]))
            if binding is None:
                continue
            expected = {**binding, **label_helper.first_force_expected(tape, binding, force, source)}
            audit.check(session + row["policy"] + row["slot_id"] + ":全先着属性", row, expected)
        print(session + " 新二候補の保存物確認", flush=True)
    baseline = [row for row in source.json_rows(OLDWORK / "入口先着.jsonl.gz") if row["policy"] in ("B+", "B-")]
    check_periods(accounts, labels, slots, baseline, result, source, audit)
    audit.check("新詳細2gzip集合", set(result["詳細"]), {"定時判断と運用.jsonl.gz", "入口先着.jsonl.gz"})
    for name, digest in result["詳細"].items():
        audit.check("新詳細SHA:" + name, source.sha(WORK / name), digest)
    api = check_api(viewer_url, resources, accounts, source, audit)
    for name, digest in before.items():
        audit.check("実行中不変:" + name, source.sha(ROOT / name), digest)
    payload = {"試行": 50, "確認日時": datetime.now(source.JST).isoformat(), "全件一致": audit.bad == 0,
               "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples,
               "市場戦略再生": False, "主モデルimport": False, "旧S1再生": False,
               "検証範囲": "新P0/P1の全予定・公開出典時計・注文・原正常BBO約定・現金・保存追尾変化点・先着・期間活動/費用・同時計基準。旧S1は保存値strict参照。",
               "検証対象外": "新入口パターン・局所監視・指標bankの再生成、変化しない全tickの保護更新、旧S1の再計算。",
               "期限境界": "固定49補足のfirst_force_expectedを使用。force同秒最初正常行inclusive。既知誤りの旧saved_label_expectedは不使用。",
               "対象場数": len(entries), "新運用数": len(accounts), "新先着件数": {p: len(v) for p, v in labels.items()},
               "公開足出典検査数": source_count, "旧対照参照SHA256": control, "参照SHA256": before,
               "キャッシュSHA256": cache_pins, "新Viewer約定SHA256": viewer_pins, "ViewerAPI": api}
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


# ----------------------------------------
# 架空BBOだけで、候補ID・費用・分母・期限境界の接続を確認する。

def self_test() -> dict:
    """新IDの買売四経路と期限人工を、明示期待値で検査する。

    引数: なし。市場入力・既存結果・旧先着は読まない。
    返り値: dictは人工比較数と合否。固定モデルの純replayは人工入力だけに使う。
    """
    source, label_helper = helpers()
    audit, distinctions = label_helper.self_test(source)
    engine = load(ROOT / "scripts/定時帯反応/運用.py", "局所再開_人工固定運用49")
    session = "2026-09-25_Day"
    start, force, end, times = source.calendar(session)
    audit.check("Day予定25", len(times), 25)
    audit.check("Night予定49", len(source.calendar("2026-09-25_Night")[3]), 49)
    paths = 0
    for policy in POLICIES:
        for side in (1, -1):
            t = times[0]
            bid, ask = np.array([95, 95, 115, 100, 100, 100], dtype=float), np.array([100, 100, 120, 105, 105, 105], dtype=float)
            if side == -1:
                bid, ask = 1000 - ask, 1000 - bid
            data = {"now": np.array([t, t + 1, t + 2, t + 3, t + 4, force + 1]), "line": np.arange(1, 7),
                    "bid": bid, "ask": ask, "valid": np.ones(6, dtype=bool)}
            events = [{"now": float(data["now"][i]), "line": int(data["line"][i]), "last": float((bid[i] + ask[i]) / 2),
                       "bid": float(bid[i]), "ask": float(ask[i]), "valid": True} for i in range(6)]
            slots = [{"scheduled": moment, "time": moment, "line": 1 if i == 0 else None,
                      "slot_id": session + "_" + str(int(moment)), "session": session, "policy": policy,
                      "side": side if i == 0 else 0, "role": "順行" if i == 0 else "待機", "atr": 20.0 if i == 0 else None,
                      "D": 20.0 if i == 0 else None, "ready": i == 0, "reason": "人工採用" if i == 0 else "価格イベントなし"} for i, moment in enumerate(times)]
            op = engine.replay(events, [{key: row[key] for key in engine.SLOT_FIELDS} for row in slots], session, policy)
            tape = source.tape_from_arrays(data, session, audit)
            source.check_decisions({"session": session, "policy": policy, "slots": slots, "operation": op}, tape, audit)
            source.check_orders(op, tape, audit)
            source.check_trail(op, tape, audit)
            failed_normal = {**data, "valid": data["valid"].copy()}
            failed_normal["valid"][1] = False
            rejected = source.Audit()
            bad_tape = source.tape_from_arrays(failed_normal, session, rejected)
            source.check_orders(op, bad_tape, rejected)
            audit.check("約定行の正常旗破壊を拒否", rejected.bad > 0, True)
            request_index = next(i for i, log in enumerate(op["trail"]) if log["action"] == "返済要求")
            retained = deepcopy(op["trail"][:request_index + 1])
            extra = {"action": "人工の保留観測", "time": t + 3.5, "line": 4,
                     "state": deepcopy(retained[-1]["state"])}
            retained.append(extra)
            source.check_trail({"trail": retained}, tape, audit)
            broken = deepcopy(retained)
            broken[-1]["state"]["position"]["L"] -= 5
            rejected = source.Audit()
            source.check_trail({"trail": broken}, tape, rejected)
            audit.check("pending設定線の緩和を拒否", rejected.bad > 0, True)
            account = source.check_cash(op, op["trades"], tape, audit)
            summary = operation_summary([account], "学習", source)
            audit.check("人工完結と費用", (len(op["closed"]), account["ledger"], account["caution"]), (1, {"0": -22.0, "5": -122.0, "10": -222.0}, False))
            audit.check("人工現在利益起動", (op["closed"][0]["arm_r"], op["closed"][0]["arm_net"]), (15.0, 28.0))
            audit.check("人工全予定と保守上限", (summary["予定枠"], summary["判定不能"], summary["待ち数"], summary["待ち率保守上限"], summary["活動適格"]), (25, 24, 0, 24 / 25, False))
            audit.check("人工支持不足と費用不適格", (summary["費用支持"], summary["費用適格"]), (False, False))
            paths += 1
    row = {"session": session, "policy": "P0", "slot_id": "a", "filled": True, "entry_time": 10, "entry_line": 1,
           "end_time": 20, "end_line": 5, "outcome": "250", "role": "順行"}
    other = {**row, "slot_id": "b", "entry_time": 20, "entry_line": 6, "outcome": "125"}
    summary = source.entry_summary([row, other], "学習")
    audit.check("同秒後行は薄化適格", (summary["約定"], summary["250"], summary["間引き約定"], summary["率"]), (2, 1, 2, .5))
    other["entry_line"] = 5
    audit.check("同keyは薄化不適格", source.entry_summary([row, other], "学習")["間引き約定"], 1)
    source_row = {"session": session, "index": 1, "minutes": 3, "start": times[0] - 360, "end": times[0] - 180,
                  "confirm": times[0] - 179, "confirm_line": 5, "publish": True, "missing": 0,
                  "open": 100, "high": 105, "low": 95, "close": 100}
    slot = {"session": session, "scheduled": times[0], "time": times[0], "line": 10}
    check_sources({"current": source_row}, slot, audit)
    rejected = source.Audit()
    check_sources({"current": {**source_row, "end": times[0] + 180, "confirm": times[0] + 181}}, slot, rejected)
    audit.check("未来足出典を拒否", rejected.bad > 0, True)
    previous = {**source_row, "index": 0, "start": times[0] - 540, "end": times[0] - 360, "confirm": times[0] - 359, "confirm_line": 4}
    upper = {**source_row, "minutes": 15, "start": times[0] - 1800, "end": times[0] - 900, "confirm": times[0] - 899, "confirm_line": 1}
    diagnostic = {"actions": [], "consumed_events": [], "T_watch": None, "R_watch": None}
    feature = {**slot, "policy": "P0", "side": 0, "role": "待機", "ready": True, "reason": "人工待機", "atr": 20., "D": 20.,
               "current": source_row, "previous": previous, "upper": {"ready": True, "source": upper}, "diagnostic": diagnostic}
    audit.check("新特徴の準備済み3出典", check_slot_sources(feature, audit), 3)
    rejected = source.Audit()
    check_slot_sources({**feature, "D": 15.}, rejected)
    audit.check("現ATR固定Dの破壊拒否", rejected.bad > 0, True)
    late_upper = {**upper, "start": times[0] - 900, "end": times[0], "confirm": times[0], "confirm_line": 6}
    rejected = source.Audit()
    check_sources({"trigger": source_row, "trigger_di": {"source": late_upper}}, slot, rejected)
    audit.check("定時には既知でも発動当時未来の上位を拒否", rejected.bad > 0, True)
    base = {"policy": "P1", "ready": True, "side": 0, "role": "待機", "reason": "人工", "current": {"close": 110},
            "upper": {"ready": True, "direction": 1}, "OR": {"ready": True, "high": 100, "low": 90}, "diagnostic": diagnostic}
    stages = [deepcopy(base) for _ in range(8)]
    stages[0]["ready"] = False
    stages[1].update(side=1, role="順行")
    stages[1]["diagnostic"]["consumed_events"] = [{"age_seconds": 30, "active": True, "cancel_reason": ""}]
    stages[1]["diagnostic"]["actions"] = [{"action": "初発動固定"}]
    stages[2]["reason"] = "同枠複数発動WAIT"
    stages[3]["diagnostic"]["consumed_events"] = [{"age_seconds": 60, "active": False, "cancel_reason": "否定"}]
    stages[4]["diagnostic"]["T_watch"] = {"人工監視": True}
    stages[5]["diagnostic"]["R_watch"] = {"人工監視": True}
    stages[7]["current"]["close"] = 100
    coverage = coverage_summary(stages, [])
    expected_stages = {name: 1 for name in ("判定不能", "純入口", "同枠競合", "発動済みだが失効", "T再開監視中", "R復帰又は確認監視中", "T背景あり調整待ち", "T背景不成立かつ発動なし")}
    audit.check("機会8段階は排他", coverage["機会段階"], expected_stages)
    audit.check("消費・有効・失効・古さ", (coverage["消費発動数"], coverage["消費時有効発動数"], coverage["消費時失効理由"], coverage["消費発動の古さ秒"]),
                (2, 1, {"否定": 1}, {"件数": 2, "平均": 45., "最大": 60}))
    return {"人工成功": audit.bad == 0, "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples,
            "新候補買売経路": paths, "期限が一般には異なる人工例": len(distinctions), "市場入力読取": False}


def main() -> None:
    """人工又はroot実行後の一度の保存物検査を明示選択する。

    引数: なし。CLIの--self-test/--run/--viewer-urlを読む。
    返り値: None。不一致は保存した上で非零終了し、既存証明を上書きしない。
    """
    parser = argparse.ArgumentParser(description="試行50保存物の独立検査。市場戦略再生なし")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--run", action="store_true")
    parser.add_argument("--viewer-url")
    args = parser.parse_args()
    result = self_test() if args.self_test else run(args.viewer_url)
    print(json.dumps({key: result[key] for key in ("全件一致", "人工成功", "照合項目数", "不一致数", "新候補買売経路") if key in result}, ensure_ascii=False))
    if result.get("全件一致", result.get("人工成功")) is False:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
