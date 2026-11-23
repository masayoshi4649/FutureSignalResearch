"""83の固定B1入口とS0G1を、固定82の保存正本へ全文照合する。市場は再生しない。"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile


ROOT = Path(__file__).resolve().parents[2]
MODES = ("S0G1", "S1G1", "S0G2", "S1G2")
KEYS = tuple(f"{mode}_D{delay}" for delay in (0, 1) for mode in MODES)
BASE_KEYS = {f"{mode}_D{delay}" for delay in (0, 1) for mode in ("B0G1", "B1G1")}
JST = timezone(timedelta(hours=9))
EXTRA = {
    "ActualOrder": {"structure_anchor", "structure_active", "structure_floor"},
    "ActualLot": {"structure_anchor", "structure_active", "structure_floor", "structure_activated_at",
                  "structure_entry_breached", "structure_first_hit_at", "structure_first_hit_index"},
    "ClosedLot": {"structure_anchor", "structure_active", "structure_floor", "structure_activated_at",
                  "structure_entry_breached", "structure_first_hit_at", "structure_first_hit_index"},
    "BookMetrics": {"structure_known_entries", "structure_unknown_entries", "structure_activated_lots",
                    "structure_entry_breached_lots", "structure_hit_lots", "structure_exit_orders"},
    "BookResult": set(),
}
CONTAINERS = {"orders": "ActualOrder", "pending_entries": "ActualOrder", "lots": "ActualLot",
              "positions": "ActualLot", "closed": "ClosedLot"}


class Audit:
    """照合項目・全不一致数と限定した差分例を保持する。"""

    def __init__(self) -> None:
        """
        機能: 比較件数と差分台帳を初期化する。
        引数: なし。
        返り値: None。差分例の上限と総不一致数を別にする。
        """
        self.count = 0
        self.bad = 0
        self.examples = []
        self.scope = Counter()

    def check(self, ok: bool, label: str, where: str, actual=None, expected=None) -> None:
        """
        機能: 検査を数え、不一致時だけ有限長の説明を記録する。
        引数: ok (bool)、label/where (str)、actual/expected (JSON互換値)。
        返り値: None。例が200件を超えても不一致総数を省略しない。
        """
        self.count += 1
        self.scope[label] += 1
        if not ok:
            self.bad += 1
            if len(self.examples) < 200:
                self.examples.append({"項目": label, "場所": where,
                    "実際": repr(actual)[:600], "期待": repr(expected)[:600]})


def sha(path: Path) -> str:
    """
    機能: 保存入力の前後不変を確認する指紋を求める。
    引数: path (Path) はファイル。
    返り値: str はSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def unique_pairs(pairs: list[tuple]) -> dict:
    """
    機能: JSONの同一オブジェクト内の重複キーを拒否する。
    引数: pairs (list[tuple]) はデコーダが受け取ったキーと値。
    返り値: dict。重複時はValueErrorを送出する。
    """
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("JSONキーが重複:" + key)
        value[key] = item
    return value


def reject_constant(value: str) -> None:
    """
    機能: JSONに混入したNaN・Infinityを読み飛ばさず拒否する。
    引数: value (str) は非標準数値の文字列。
    返り値: None。必ずValueErrorを送出する。
    """
    raise ValueError("非有限JSON数値:" + value)


def read_json(path: Path) -> dict:
    """
    機能: キー重複と非標準数値を許さず保存JSONを読む。
    引数: path (Path) は小型保存結果。
    返り値: dict は読み取ったJSON。
    """
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs, parse_constant=reject_constant)


def finite(value) -> bool:
    """
    機能: 真偽値と区別した有限数値かを確認する。
    引数: value (object) はJSON値。
    返り値: bool。巨大整数の変換不能も偽にする。
    """
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def inspect_finite(value, audit: Audit, where: str) -> None:
    """
    機能: 比較対象外の会計も含め、全JSON数値の非有限混入を確認する。
    引数: value (JSON互換値)、audit (Audit)、where (str) は場所。
    返り値: None。数値を丸めず検査する。
    """
    if type(value) in (int, float):
        audit.check(finite(value), "全保存数値の有限性", where, value, "有限値")
    elif isinstance(value, dict):
        for key, item in value.items():
            inspect_finite(item, audit, where + "." + key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            inspect_finite(item, audit, f"{where}[{index}]")


def compare(actual, expected, audit: Audit, where: str, label: str) -> None:
    """
    機能: JSONの全キー・配列順序・末端値を型を区別して比較する。
    引数: actual/expected (JSON互換値)、audit (Audit)、where/label (str)。
    返り値: None。数値1と真偽値trueを同一扱いせず、有限数の等値は厳密比較する。
    """
    if isinstance(expected, dict) and isinstance(actual, dict):
        audit.check(set(actual) == set(expected), label + "キー集合", where, sorted(actual), sorted(expected))
        for key in sorted(set(actual) & set(expected)):
            compare(actual[key], expected[key], audit, where + "." + key, label)
    elif isinstance(expected, list) and isinstance(actual, list):
        audit.check(len(actual) == len(expected), label + "配列長", where, len(actual), len(expected))
        for index, (left, right) in enumerate(zip(actual, expected)):
            compare(left, right, audit, f"{where}[{index}]", label)
    elif type(expected) in (int, float) and type(actual) in (int, float):
        audit.check(finite(actual) and finite(expected) and actual == expected, label + "数値", where, actual, expected)
    else:
        audit.check(type(actual) is type(expected) and actual == expected, label + "値", where, actual, expected)


def schemas() -> dict[str, set[str]]:
    """
    機能: 固定81のJSONタグから旧会計で省略されない全フィールドを得る。
    引数: なし。固定Goソースだけを読み、Goは実行しない。
    返り値: dict[str,set[str]] は旧型の必須キー。想定外のomitemptyは拒否する。
    """
    path = ROOT / "scripts/定時の現在根拠と部分利益保護/actual.go"
    text = path.read_text(encoding="utf-8")
    output = {}
    for name in EXTRA:
        block = re.search(r"type " + name + r" struct\s*\{(.*?)\n\}", text, re.S)
        if not block:
            raise ValueError("旧型の定義がない:" + name)
        tags = re.findall(r'`json:"([^"]+)"`', block.group(1))
        if not tags or any("," in tag for tag in tags):
            raise ValueError("旧型の省略規則が変わった:" + name)
        output[name] = set(tags)
    return output


def scheduled(session: str) -> list[float]:
    """
    機能: 原板とGoへ依存せず、初回除外後のJST予定枠を生成する。
    引数: session (str) はYYYY-MM-DD_Day又はNight。
    返り値: list[float] はDay25／Night49のUnix秒。
    """
    day, kind = session.split("_")
    base = datetime.fromisoformat(day).replace(tzinfo=JST)
    if kind == "Day":
        first, count = base + timedelta(hours=9, minutes=15), 25
    elif kind == "Night":
        first, count = base + timedelta(hours=17, minutes=30), 49
    else:
        raise ValueError("未定義セッション:" + session)
    return [(first + timedelta(minutes=15 * index)).timestamp() for index in range(count)]


def expected_anchor(at: float, technical: dict) -> dict:
    """
    機能: 当時の確定3分EMA8から構造線を独立に算出する。
    引数: at (float) は定時、technical (dict) は保存された現確定足。
    返り値: dict は要求時固定線又は数値0を持つ理由付き未知。
    """
    end, price = technical.get("bar3_end"), technical.get("ema8_3")
    known = technical.get("exit_known") is True and finite(at) and finite(end) and finite(price)
    known = known and price > 0 and end > 0 and end <= at and at - end <= 180
    if known:
        return {"known": True, "price": price, "at": at, "bar_end": end, "reason": "新規要求時点の確定3分EMA8"}
    return {"known": False, "price": 0, "at": 0, "bar_end": 0, "reason": "当時確定3分EMA8が未知"}


def renamed(value):
    """
    機能: mode由来の文字列だけを旧基準の名称へ写す。
    引数: value (JSON互換値) は構造追加欄除去後の会計。
    返り値: JSON互換値。配列順序と数値は一切変えない。
    """
    if isinstance(value, str):
        return value.replace("S0G1", "B1G1")
    if isinstance(value, list):
        return [renamed(item) for item in value]
    if isinstance(value, dict):
        return {key: renamed(item) for key, item in value.items()}
    return value


def project(book: dict) -> dict:
    """
    機能: 宣言済みstructure追加欄だけを除き、S0G1を旧82の型へ投影する。
    引数: book (dict) は83のS0G1会計。
    返り値: dict。未定義の追加キーを都合よく消さない。
    """
    value = deepcopy(book)
    for container, name in CONTAINERS.items():
        for row in value[container]:
            for field in EXTRA[name]:
                row.pop(field, None)
    for field in EXTRA["BookMetrics"]:
        value["metrics"].pop(field, None)
    return renamed(value)


def validate_book(book: dict, expected_keys: dict, current: bool, audit: Audit, where: str) -> None:
    """
    機能: 両側で同じ旧フィールドが消えた場合も、旧Go型の必須集合で検出する。
    引数: book (dict)、expected_keys (dict)、current (bool)、audit (Audit)、where (str)。
    返り値: None。83で許される追加は明示structureフィールドだけとする。
    """
    audit.check(set(book) == expected_keys["BookResult"], "会計旧フィールド", where, sorted(book), sorted(expected_keys["BookResult"]))
    for container, name in CONTAINERS.items():
        for index, row in enumerate(book[container]):
            wanted = expected_keys[name] | (EXTRA[name] if current else set())
            audit.check(set(row) == wanted, "会計内フィールド", f"{where}.{container}[{index}]", sorted(row), sorted(wanted))
    wanted = expected_keys["BookMetrics"] | (EXTRA["BookMetrics"] if current else set())
    audit.check(set(book["metrics"]) == wanted, "集計旧フィールド", where + ".metrics", sorted(book["metrics"]), sorted(wanted))


def audit_scene(current: dict, baseline: dict, session: str, times: list[float], expected_keys: dict, audit: Audit) -> dict:
    """
    機能: 一場の入口全文・全構造線・S0G1両遅延の全旧会計を照合する。
    引数: current/baseline (dict)、session (str)、times (list[float])、expected_keys (dict)、audit (Audit)。
    返り値: dict は一場の小型件数。S1/G2の独立約定再計算は別監査とする。
    """
    inspect_finite(current, audit, session + ".83")
    inspect_finite(baseline, audit, session + ".82")
    for value, side in ((current, "83"), (baseline, "82")):
        audit.check(set(value) == {"session", "quality", "books", "grid_decisions"}, "場本文キー", session + side, sorted(value), "4キー")
        audit.check(value["session"] == session, "場ID", session + side, value["session"], session)
    audit.check(set(current["books"]) == set(KEYS), "83会計集合", session, sorted(current["books"]), sorted(KEYS))
    audit.check(set(baseline["books"]) == BASE_KEYS, "82会計集合", session, sorted(baseline["books"]), sorted(BASE_KEYS))
    compare(current["quality"], baseline["quality"], audit, session + ".quality", "原板品質全文")
    old_grids = [g for g in baseline["grid_decisions"] if g["entry_policy"] == "B1"]
    all_old = baseline["grid_decisions"]
    audit.check(len(all_old) == 2 * len(times), "82全予定数", session, len(all_old), 2 * len(times))
    for policy in ("B0", "B1"):
        selected = [g for g in all_old if g["entry_policy"] == policy]
        audit.check([g["at"] for g in selected] == times, "82政策予定順", session + policy, [g["at"] for g in selected], times)
    grids = current["grid_decisions"]
    audit.check(len(grids) == len(times), "83全予定数", session, len(grids), len(times))
    audit.check([g["at"] for g in grids] == times, "83予定順と重複", session, [g["at"] for g in grids], times)
    by_time = {}
    for index, grid in enumerate(grids):
        where = f"{session}.grid[{index}]"
        at = grid["at"]
        audit.check(finite(at) and at not in by_time, "定時キー重複なし", where, at, "有限・一意")
        by_time[at] = grid
        audit.check(grid["entry_policy"] == "B1", "固定B1入口", where, grid["entry_policy"], "B1")
        anchor = expected_anchor(at, grid["decision"]["technical"])
        compare(grid["structure_anchor"], anchor, audit, where + ".structure_anchor", "当時EMA線")
        projected = {key: value for key, value in grid.items() if key != "structure_anchor"}
        if index < len(old_grids):
            compare(projected, old_grids[index], audit, where, "B1全snapshot")
    for key, book in current["books"].items():
        validate_book(book, expected_keys, True, audit, session + "." + key)
        mode, delay = key.split("_D")
        audit.check(book["mode"] == mode and finite(book["fill_delay_seconds"]) and book["fill_delay_seconds"] == int(delay), "83会計キーと時計", session + key, (book["mode"], book["fill_delay_seconds"]), (mode, int(delay)))
        by_reference = {}
        for order in book["orders"]:
            if order["kind"] != "entry":
                continue
            at = order["request_time"]
            grid = by_time.get(at)
            audit.check(grid is not None and grid["candidate_accepted"], "新規と定時候補", session + key, at, "供給済み定時")
            if grid is None:
                continue
            reference = order["reference_id"]
            audit.check(reference not in by_reference, "候補新規の一意", session + key, reference, "一候補一新規")
            by_reference[reference] = grid["structure_anchor"]
            audit.check(order["source"]["id"] == reference and order["source"]["at"] == at, "新規源IDと定時", session + key, order["source"], reference)
        for container in CONTAINERS:
            for index, row in enumerate(book[container]):
                expected = by_reference.get(row["reference_id"])
                where = f"{session}.{key}.{container}[{index}]"
                audit.check(expected is not None, "構造線の新規源", where, row["reference_id"], "当該新規注文")
                if expected is not None:
                    compare(row["structure_anchor"], expected, audit, where + ".structure_anchor", "新規要求時線の固定")
    for delay in (0, 1):
        new, old = current["books"][f"S0G1_D{delay}"], baseline["books"][f"B1G1_D{delay}"]
        validate_book(old, expected_keys, False, audit, f"{session}.82B1_D{delay}")
        compare(project(new), old, audit, f"{session}.S0G1_D{delay}", "基準全会計")
    return {"session": session, "予定枠": len(grids), "基準会計": 2,
            "新規実枚数": {key: current["books"][key]["metrics"]["entry_quantity"] for key in ("S0G1_D0", "S0G1_D1")}}


def inventory(folder: Path) -> dict[str, str]:
    """
    機能: 対象根の保存JSON集合と本文指紋をまとめる。
    引数: folder (Path) は83又は82の保存根。
    返り値: dict[str,str] はファイル名とSHA256。
    """
    return {path.name: sha(path) for path in sorted(folder.glob("*.json")) if path.is_file()}


def audit_directories(source: Path, baseline: Path, sessions: list[str], pins: dict[str, str] | None, audit: Audit) -> dict:
    """
    機能: 全66場の集合と2442枠を守り、保存会計・入口を前後不変で照合する。
    引数: source/baseline (Path)、sessions (list[str])、pins (dict|None)、audit (Audit)。
    返り値: dict は入力指紋と小型場別証拠。例外も完了扱いしない。
    """
    before = {"83": inventory(source), "82": inventory(baseline)}
    wanted = {session + ".json" for session in sessions}
    audit.check(len(sessions) == len(set(sessions)) == 66, "固定66場", "全体", len(sessions), 66)
    for side in ("83", "82"):
        audit.check(set(before[side]) == wanted, "保存場集合", side, sorted(before[side]), sorted(wanted))
    if pins is not None:
        audit.check(before["82"] == pins, "固定82本文指紋", "82", before["82"], pins)
    rows = []
    complete = True
    try:
        expected_keys = schemas()
        for session in sessions:
            if session + ".json" not in before["83"] or session + ".json" not in before["82"]:
                continue
            row = audit_scene(read_json(source / (session + ".json")), read_json(baseline / (session + ".json")),
                              session, scheduled(session), expected_keys, audit)
            rows.append(row)
    except Exception as error:
        complete = False
        audit.check(False, "読取処理未完", "全体", type(error).__name__ + ":" + str(error), "全場完了")
    after = {"83": inventory(source), "82": inventory(baseline)}
    audit.check(before == after, "入力集合と本文の前後不変", "全体", before, after)
    audit.check(len(rows) == 66, "完了場数", "全体", len(rows), 66)
    frames = sum(row["予定枠"] for row in rows)
    audit.check(frames == 2442, "固定B1全予定2442", "全体", frames, 2442)
    return {"処理完了": complete and len(rows) == 66, "場数": len(rows), "予定枠": frames,
            "基準会計数": sum(row["基準会計"] for row in rows), "入力不変": before == after,
            "入力SHA256前": before, "入力SHA256後": after, "対象場": rows}


def fixture(session: str, at: float, expected_keys: dict) -> tuple[dict, dict]:
    """
    機能: 非0約定と構造線を持つ、原板と無関係な保存JSON人工を作る。
    引数: session (str)、at (float)、expected_keys (dict) は旧フィールド集合。
    返り値: tuple[dict,dict] は83と82の人工保存結果。会計再生そのものではない。
    """
    ref = session + "_B1_人工"
    anchor = expected_anchor(at, {"exit_known": True, "ema8_3": 1000, "bar3_end": at - 60})
    lot = dict.fromkeys(expected_keys["ActualLot"])
    lot.update(id=session + "_B1G1_P000001", reference_id=ref, side=1, quantity=0, initial_quantity=100,
               entry_price=1010, entry_time=at + 1, net_pnl=2800, flag=True)
    order = dict.fromkeys(expected_keys["ActualOrder"])
    order.update(id=session + "_B1G1_O000001", reference_id=ref, position_id=lot["id"], kind="entry",
                 side=1, quantity=100, request_time=at, source={"id": ref, "at": at})
    close = dict.fromkeys(expected_keys["ClosedLot"])
    close.update(reference_id=ref, position_id=lot["id"], quantity=100, entry_price=1010, exit_price=1025, pnl5=2800)
    book = dict.fromkeys(expected_keys["BookResult"])
    book.update(session=session, mode="B1G1", side_cap=100, fill_delay_seconds=0, trades=[{"id": "B1G1_T1", "price": 1010, "qty": 100, "fee_yen": 6100}],
                orders=[order], decisions=[], closed=[close], lots=[lot], positions=[], pending_entries=[],
                quantity_by_side={"-1": 0, "1": 0}, metrics=dict.fromkeys(expected_keys["BookMetrics"], 0), unresolved=False, warnings=[])
    book["metrics"].update(entry_quantity=100, exit_quantity=100, net_pnl_yen=2800)
    decision = {"at": at, "policy": "B1", "allowed": True, "side": 1, "quote": {"last": 1005, "bid": 1000, "ask": 1010},
                "technical": {"exit_known": True, "ema8_3": 1000, "bar3_end": at - 60},
                "chart_pair": {"previous3_known": True}, "evidence": {"source_line": 1}, "directions": [{"side": 1, "allowed": True}]}
    grid = {"at": at, "window": "D164_15", "entry_policy": "B1", "decision": decision,
            "clock_allowed": True, "block_reason": "", "candidate_accepted": True}
    old = {"session": session, "quality": {"NK225": {"accepted": 2}}, "books": {}, "grid_decisions": []}
    for policy in ("B0", "B1"):
        row = deepcopy(grid)
        row["entry_policy"] = policy
        row["decision"]["policy"] = policy
        old["grid_decisions"].append(row)
    for delay in (0, 1):
        for mode in ("B0G1", "B1G1"):
            row = deepcopy(book)
            row["mode"], row["fill_delay_seconds"] = mode, delay
            old["books"][f"{mode}_D{delay}"] = row
    current = {"session": session, "quality": deepcopy(old["quality"]), "books": {}, "grid_decisions": [{**deepcopy(grid), "structure_anchor": anchor}]}
    for key in KEYS:
        mode, delay = key.split("_D")
        row = deepcopy(old["books"][f"B1G1_D{delay}"])
        row = json.loads(json.dumps(row).replace("B1G1", mode))
        row["mode"] = mode
        for container, name in CONTAINERS.items():
            for item in row[container]:
                item.update(dict.fromkeys(EXTRA[name]))
                item["structure_anchor"] = deepcopy(anchor)
        row["metrics"].update(dict.fromkeys(EXTRA["BookMetrics"], 0))
        current["books"][key] = row
    return current, old


def self_test() -> dict:
    """
    機能: 非0保存人工と1値破壊で、全文比較・構造線・不足検出を確かめる。
    引数: なし。
    返り値: dict は人工の結果。正式66場や原板を読まない。
    """
    expected_keys = schemas()
    session, at = "2026-11-02_Day", 1000.0
    current, old = fixture(session, at, expected_keys)
    good = Audit()
    audit_scene(current, old, session, [at], expected_keys, good)
    assert good.bad == 0, good.examples
    results = [{"人工": "非0基準会計と全8構造線", "照合": good.count, "不一致": good.bad}]
    mutations = (
        ("anchor1値", lambda v: v["grid_decisions"][0]["structure_anchor"].update(price=1001)),
        ("価格1pt", lambda v: v["books"]["S0G1_D0"]["trades"][0].update(price=1011)),
        ("数量1枚", lambda v: v["books"]["S0G1_D0"]["lots"][0].update(initial_quantity=99)),
        ("定時時計", lambda v: v["grid_decisions"][0].update(at=1001)),
        ("snapshot1値", lambda v: v["grid_decisions"][0]["decision"]["evidence"].update(source_line=2)),
        ("旧フィールド欠落", lambda v: v["books"]["S0G1_D0"]["metrics"].pop("total_cost_yen")),
        ("余分な旧集計", lambda v: v["books"]["S0G1_D0"]["metrics"].update(unexpected_metric=0)),
        ("非有限", lambda v: v["grid_decisions"][0]["decision"]["quote"].update(last=float("inf"))),
        ("重複定時", lambda v: v["grid_decisions"].append(deepcopy(v["grid_decisions"][0]))),
        ("余分な会計", lambda v: v["books"].update(S9G9_D0=deepcopy(v["books"]["S0G1_D0"]))),
        ("未定義structure欄", lambda v: v["books"]["S0G1_D0"]["orders"][0].update(structure_unknown_field=1)),
        ("玉の構造線変更", lambda v: v["books"]["S1G2_D1"]["lots"][0]["structure_anchor"].update(price=999)),
    )
    for label, mutate in mutations:
        altered = deepcopy(current)
        mutate(altered)
        audit = Audit()
        audit_scene(altered, old, session, [at], expected_keys, audit)
        assert audit.bad > 0, label
        results.append({"人工": label, "検出": audit.bad})
    both, other = deepcopy(current), deepcopy(old)
    both["books"]["S0G1_D0"]["metrics"].pop("total_cost_yen")
    other["books"]["B1G1_D0"]["metrics"].pop("total_cost_yen")
    audit = Audit()
    audit_scene(both, other, session, [at], expected_keys, audit)
    assert audit.bad > 0
    results.append({"人工": "両側同じ旧フィールドを削除", "検出": audit.bad})
    with tempfile.TemporaryDirectory(prefix="83基準照合人工_", dir=ROOT / "work") as temp:
        path = Path(temp) / "重複.json"
        for text in ('{"x":1,"x":2}', '{"x":NaN}'):
            path.write_text(text, encoding="utf-8")
            try:
                read_json(path)
            except ValueError:
                results.append({"人工": "JSON重複又はNaN拒否", "拒否": True})
            else:
                raise AssertionError("不正JSONを読んだ")
    assert len(scheduled("2026-11-02_Day")) == 25 and len(scheduled("2026-11-02_Night")) == 49
    results.append({"人工": "独立JST予定25と49", "成功": True})
    # ----------------------------------------
    # 金融再生をせず、全66保存集合と2442枠のCLI契約も自己完結した値で検査する。
    with tempfile.TemporaryDirectory(prefix="83全予定人工_", dir=ROOT / "work") as temp:
        source, baseline = Path(temp) / "83", Path(temp) / "82"
        source.mkdir()
        baseline.mkdir()
        sessions = []
        first = datetime(2026, 1, 1, tzinfo=JST)
        for day in range(33):
            for kind in ("Day", "Night"):
                session = (first + timedelta(days=day)).date().isoformat() + "_" + kind
                sessions.append(session)
                times = scheduled(session)
                current, old = fixture(session, times[0], expected_keys)
                template = deepcopy(current["grid_decisions"][0])
                for at in times[1:]:
                    grid = deepcopy(template)
                    grid["at"], grid["decision"]["at"] = at, at
                    grid["decision"]["technical"]["bar3_end"] = at - 60
                    grid["structure_anchor"] = expected_anchor(at, grid["decision"]["technical"])
                    current["grid_decisions"].append(grid)
                    for policy in ("B0", "B1"):
                        before = {key: deepcopy(value) for key, value in grid.items() if key != "structure_anchor"}
                        before["entry_policy"], before["decision"]["policy"] = policy, policy
                        old["grid_decisions"].append(before)
                (source / (session + ".json")).write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
                (baseline / (session + ".json")).write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        audit = Audit()
        result = audit_directories(source, baseline, sessions, inventory(baseline), audit)
        assert audit.bad == 0 and result["場数"] == 66 and result["予定枠"] == 2442 and result["基準会計数"] == 132, audit.examples
        results.append({"人工": "全66保存と2442枠と132基準会計", "照合": audit.count, "不一致": 0})
        (source / (sessions[0] + ".json")).unlink()
        (source / "余計な対象.json").write_text("{}", encoding="utf-8")
        altered = Audit()
        result = audit_directories(source, baseline, sessions, inventory(baseline), altered)
        assert altered.bad > 0 and not result["処理完了"]
        results.append({"人工": "保存対象の不足と余計なファイル", "検出": altered.bad})
    return {"成功": True, "人工系列": len(results), "人工": results, "正式保存結果読取": 0, "本物原板読取": 0, "新売買再生": 0}


def main() -> None:
    """
    機能: 明示された全66保存結果を照合し、失敗も未完も新規証拠へ残す。
    引数: --input/--baseline/--out (Path)、--self-test (bool)。
    返り値: None。不一致又は未完なら終了1、人工は正式結果を読まない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        if any((args.input, args.baseline, args.out)):
            raise ValueError("人工と正式入力を同時指定しません")
        print(json.dumps(self_test(), ensure_ascii=False))
        return
    if not all((args.input, args.baseline, args.out)):
        raise ValueError("input/baseline/outを全て明示してください")
    if args.out.exists():
        raise FileExistsError("既存証拠を上書きしません")
    if any(args.out.resolve().is_relative_to(p.resolve()) for p in (args.input, args.baseline)):
        raise ValueError("証拠を入力根へ作成しません")
    audit = Audit()
    data = {"処理完了": False, "場数": 0, "予定枠": 0, "基準会計数": 0, "入力不変": False}
    small = {}
    try:
        manifest = ROOT / "study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json"
        pins_path = ROOT / "study/00082_チャートの現在性と補助確認/成果物/結果.json"
        condition = ROOT / "study/00082_チャートの現在性と補助確認/条件.json"
        old_code = ROOT / "scripts/定時の現在根拠と部分利益保護/actual.go"
        small = {str(p.relative_to(ROOT)): sha(p) for p in (manifest, pins_path, condition, old_code)}
        wanted = read_json(condition)["固定81依存"][old_code.relative_to(ROOT).as_posix()]
        audit.check(sha(old_code) == wanted, "固定旧schema指紋", "旧81actual", sha(old_code), wanted)
        sessions = [s["id"] for s in read_json(manifest)["sessions"]]
        pins = read_json(pins_path)["再生結果SHA256"]
        data = audit_directories(args.input.resolve(), args.baseline.resolve(), sessions, pins, audit)
        after_small = {path: sha(ROOT / path) for path in small}
        audit.check(after_small == small, "固定小型入力不変", "全体", after_small, small)
    except Exception as error:
        audit.check(False, "全体処理未完", "全体", type(error).__name__ + ":" + str(error), "完了")
    success = data["処理完了"] and audit.bad == 0
    output = {"試行": 83, "成功": success, **data, "照合項目数": audit.count, "不一致数": audit.bad,
        "不一致": audit.examples, "項目別比較数": dict(audit.scope), "固定小型入力SHA256": small,
        "照合コードSHA256": sha(Path(__file__)), "新売買再生": 0, "本物原板読取": 0,
        "範囲外": ["元指標系列の独立再計算", "初動構造の全生成", "S1/G2約定と追尾規範の独立再計算（別原板監査）"]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: output[key] for key in ("成功", "場数", "予定枠", "基準会計数", "照合項目数", "不一致数")}, ensure_ascii=False))
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
