"""89の旧88入口/G1同値と二配分の要求・通知・初回利益出典を保存値から監査する。"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OLD_PATH = ROOT / "scripts/FAR参照玉と可変数量の比較/基準と保存判断の照合.py"
OLD_SHA = "6763c012e0a3a9e03f9272555f6e40f80426074ea71fd380cc5f6877a5769df0"
FIXED88_PATH = ROOT / "scripts/FAR背景維持と押戻し再開/基準と保存判断の照合.py"
FIXED88_SHA = "c893834f2b27ec7b3b806fc6906586740b22f08131f9c601e72708b0e0a090e4"
EVENT_PATH = FIXED88_PATH.with_name("イベント保存照合.py")
KEYS = tuple(f"{policy}{guard}_D{delay}" for delay in (0, 1) for policy in ("E0", "E1") for guard in ("G1", "G2"))
TOP_FIELDS = {"session", "quality", "reference_counts", "books", "grid_decisions", "source_events", "source_equivalence", "entry_observations", "entry_bindings", "technical_equivalence", "seed_view", "input_end", "profit_contexts"}
GRID_FIELDS = {"at", "window", "clock_allowed", "block_reason", "c0", "source", "source_line", "structure_anchor", "entry", "events", "policies"}
ENTRY_BIND_FIELDS = {"book_key", "policy", "delay_seconds", "entry_order_id", "position_id", "reference_id", "at", "requested_quantity", "raw_rank", "supplied_rank", "source_method", "source_at", "source_index", "pool_evaluation", "current_qualification"}
PROFIT_FIELDS = {"id", "quote", "technical", "current_available", "current", "triggered_by"}
TRIGGER_FIELDS = {"book_key", "position_id", "reference_id", "flag_kind", "remaining_after_fill", "closed_net_after_fill"}
CURRENT_FIELDS = {"reference", "time", "received", "source_index", "source_line", "short", "night", "buy", "sell"}
SUPPORT_FIELDS = {"known", "reason", "ofi_known", "ofi30", "ofi_reason", "m", "t", "opp", "own_at"}


def sha(path: Path) -> str:
    """
    機能: 明示されたファイルの本文SHA256を取得する。
    引数: path(Path)は既存入力又はコード。
    返り値: strはSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load(path: Path, name: str) -> object:
    """
    機能: 明示されたPython読取helperを独立名で読み込む。
    引数: path(Path)、name(str)は既存コードと名前。
    返り値: objectは監査APIで、新売買や原板走査を起動しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


assert sha(FIXED88_PATH) == FIXED88_SHA, "固定88保存監査の変更"
assert sha(OLD_PATH) == OLD_SHA, "固定87保存監査の変更"
OLD = load(OLD_PATH, "saved87_for88")
EVENT = load(EVENT_PATH, "event88_for_saved")
BASE = OLD.BASE
strict = OLD.strict
canonical_sha = OLD.canonical_sha


def shape(actual: object, template: object, audit: object, where: str) -> None:
    """
    機能: 固定Current抜粋の入れ子schemaを既存保存型と比較する。
    引数: actual/template(object)、audit(object)、where(str)は値・型見本・台帳・位置。
    返り値: None。数値表記差は許すがboolと数値は混同しない。
    """
    if isinstance(template, dict):
        audit.check(isinstance(actual, dict) and set(actual) == set(template), "Current抜粋の入れ子field集合", where)
        if isinstance(actual, dict) and set(actual) == set(template):
            for key in template:
                shape(actual[key], template[key], audit, where + "." + key)
    elif isinstance(template, list):
        audit.check(isinstance(actual, list) and len(actual) == len(template), "Current抜粋の配列型", where)
        if isinstance(actual, list) and len(actual) == len(template):
            for i, (a, b) in enumerate(zip(actual, template, strict=True)):
                shape(a, b, audit, where + str(i))
    elif type(template) is bool:
        audit.check(type(actual) is bool, "Current抜粋のbool型", where)
    elif type(template) in (int, float):
        audit.check(EVENT.finite(actual), "Current抜粋の有限数値", where)
    else:
        audit.check(type(actual) is type(template), "Current抜粋の文字/null型", where)


def inspect_events(current: dict, audit: object, where: str) -> None:
    """
    機能: 疎な入力列から全定時の状態・期限・現在資格・供給部分列を再構成する。
    引数: current(dict)、audit(object)、where(str)は一場・台帳・場名。
    返り値: None。未成立/未知/期限切れも正本へ比較する。
    """
    records = current["entry_observations"]
    strict(isinstance(records, list) and len(records) > 0, "イベント入力が未計測")
    end = current["input_end"]
    strict(end is None or set(end) == {"time", "reference", "source_line"}, "統合入力終端3field/null")
    if end is not None:
        strict(EVENT.finite(end["time"]) and end["reference"] in ("NK225", "TOPIX") and type(end["source_line"]) is int and end["source_line"] > 0, "統合入力終端の時計/出典")
    for record in records:
        x = record["input"]
        audit.check(x["after_eof"] == (end is None or x["at"] > end["time"]), "統合入力終端とevent EOF旗", where)
    tracker, cursor = EVENT.Sequence(), 0
    for grid in current["grid_decisions"]:
        at = grid["at"]
        while cursor < len(records):
            x = records[cursor]["input"]
            if x["at"] > at or x["at"] == at and x["origin"] == "quote":
                break
            tracker.feed(records[cursor])
            cursor += 1
        expected = tracker.snapshot(at)
        BASE.compare(grid["events"], expected, audit, where + str(at), "疎入力から順序・失効・期限を独立再構成")
        base = grid["c0"]["base"]
        evaluation = EVENT.evaluate(at, base["quote"], base["technical"], base["chart_pair"], expected)
        BASE.compare(grid["entry"], evaluation, audit, where + str(at), "E0/E1共通現在資格と順序資格の別式")
        strict(set(grid["policies"]) == {"E0", "E1"}, "外政策2集合")
        for policy in ("E0", "E1"):
            supplied, pool = EVENT.filter_pool(policy, grid["source"], evaluation)
            if not grid["clock_allowed"]:
                supplied["lots"] = []
                for row in pool:
                    row["supplied_rank"] = None
            expected_supply = {"policy": policy, "supplied_ids": [r["reference"]["id"] for r in supplied["lots"]], "pool": pool}
            BASE.compare(grid["policies"][policy], expected_supply, audit, where + policy + str(at), "全元pool・供給部分列・二順位の独立照合")
    for record in records[cursor:]:
        tracker.feed(record)
    audit.check(tracker.count == len(records), "全イベント入力を順序どおり処理", where)


def supplied_grids(current: dict, policy: str) -> list[dict]:
    """
    機能: 全元ReadLotを変更せず、実際に旧S金融へ供給した定時列を作る。
    引数: current(dict)、policy(str)は一場と外政策。
    返り値: list[dict]は旧87保存helperへ渡せる8field定時。
    """
    output = []
    for grid in current["grid_decisions"]:
        projected = {name: deepcopy(grid[name]) for name in OLD.GRID_FIELDS}
        by_id = {row["reference"]["id"]: row for row in grid["source"]["lots"]}
        projected["source"]["lots"] = [deepcopy(by_id[identity]) for identity in grid["policies"][policy]["supplied_ids"]]
        output.append(projected)
    return output


def bind_decisions(book: dict, grids: list[dict], session: str, key: str, audit: object) -> dict:
    """
    機能: 全poolのstable順・seen・占有・同方向C0・一枠一IDと実要求を再計算する。
    引数: book (dict)、grids (list[dict])、session/key (str)、audit (Audit) は保存値。
    返り値: dict は要求参照ID別の期待Binding。元指標生成は再実装しない。
    """
    policy = 'S'; seen = set(); bindings = {}
    expected_mode = 'S0' + key.split('_D')[0][-2:]
    audit.check(book['source_policy'] == policy and book['mode'] == expected_mode and book['side_cap'] == 100 and book['fill_delay_seconds'] == int(key[-1]), 'Source政策・金融mode・上限・遅延',session+key)
    audit.check([row['at'] for row in book['decisions']] == [g['at'] for g in grids], 'Source全定時順序',session+key)
    for decision,grid in zip(book['decisions'],grids,strict=True):
        at=grid['at']; source=grid['source']; c0=grid['c0']; quote=c0['base']['quote']; place=session+key+str(at)
        pool=OLD.sorted_pool(source,at) if grid['clock_allowed'] else []
        occupied,owned=OLD.ownership_at(book,session,at,quote['line'])
        quality=quote['valid'] and OLD.finite(quote['last']) and quote['last']>0 and OLD.finite(quote['time']) and quote['time']<=at and 0<=at-quote['time']<=15 and OLD.finite(quote['bid']) and OLD.finite(quote['ask']) and 0<quote['bid']<quote['ask'] and quote['index']>=0 and source['started'] and source['at']==quote['time']
        context={'policy':policy,'method':source['method'],'snapshot_at':source['at'],'snapshot_index':source['source_index'],'started':source['started'],'occupied':occupied,'seen_before_count':len(seen),'seen_after_count':len(seen),'selected_id':'','required_unknown':bool(pool and not quality and not occupied),'c0_used':policy=='SC'}
        action,reason=('保有継続','同時一建玉を維持') if owned else ('処理中','既存注文の約定待ち') if occupied else ('判定不能','直前Source・正常気配の当時性が不成立') if pool and not quality else ('待ち','有効な参照玉なし')
        candidates=[]
        for index,row in enumerate(pool):
            reference=row['reference']; identity=reference['id']; passed=c0['allowed'] and c0['side']==reference['side']
            check={'rank':index+1,'seen':identity in seen,'eligible':False,'c0_passed':passed,'required_unknown':False,'selected':False,'real_entry_stage':'初参加候補','reason':''}
            candidate={'reference_id':identity,'source_quantity':reference['quantity'],'requested_quantity':0,'side':reference['side'],'role':reference['kind'],'reason':'','source_check':check}
            if reference['closing']: text='参照返済予約あり'
            elif identity in seen: text='同じ参照HoldIDへ再参加しない'
            elif occupied: text='実保有又は注文で占有'
            elif not quality: text='Source又は気配品質が未知'; check['required_unknown']=True
            elif policy=='SC' and not passed: text='同方向の最終C0許可なし'; check['required_unknown']=c0['required_unknown']
            else:
                check['eligible']=True
                if context['selected_id']: text='同枠の先行参照玉を採用済み'
                else:
                    quantity=min(100,reference['quantity']); text='参照現在量以内の初参加要求'; check['selected']=True; candidate['requested_quantity']=quantity
                    bindings[identity]=OLD.binding_value(policy,grid,row,index+1,quantity); seen.add(identity); context['selected_id']=identity; action,reason='新規要求','15分定時の参照玉を変数量で初参加'
            candidate['reason']=text; check['reason']=text; context['required_unknown']=context['required_unknown'] or check['required_unknown']; candidates.append(candidate)
        if action=='待ち' and context['required_unknown']: action,reason='判定不能','必要な最終C0許可が未知'
        context['seen_after_count']=len(seen)
        expected={'at':at,'quote_time':quote['time'],'quote_index':quote['index'],'action':action,'reason':reason,'candidates':candidates,'source_context':context}
        BASE.compare(decision,expected,audit,place,'全pool・seen・占有からの純選別')
    entries=[order for order in book['orders'] if order['kind']=='entry']
    audit.check(len(entries)==len(bindings) and {order['reference_id'] for order in entries}==set(bindings), '受理要求と永久seen集合',session+key)
    return bindings


def inspect_entry_bindings(current: dict, audit: object, where: str) -> None:
    """
    機能: 新規要求の外政策出典を元順位・供給順位・当時資格へ結ぶ。
    引数: current(dict)、audit(object)、where(str)は一場・台帳・位置。
    返り値: None。取消後やfill後の量で要求証拠を上書きしない。
    """
    grids = {g["at"]: g for g in current["grid_decisions"]}
    expected = []
    for grid in current["grid_decisions"]:
        for policy in ("E0", "E1"):
            for guard in ("G1", "G2"):
                for delay in (0, 1):
                    key = f"{policy}{guard}_D{delay}"
                    book = current["books"][key]
                    decisions = [d for d in book["decisions"] if d["at"] == grid["at"]]
                    strict(len(decisions) == 1, "受理元定時の一意性")
                    if decisions[0]["action"] != "新規要求":
                        continue
                    orders = [o for o in book["orders"] if o["kind"] == "entry" and o["request_time"] == grid["at"]]
                    strict(len(orders) == 1, "外bindingの一枠一新規")
                    order = orders[0]
                    rows = [r for r in grid["policies"][policy]["pool"] if r["reference_id"] == order["reference_id"]]
                    strict(len(rows) == 1, "要求と原poolの一意性")
                    row = rows[0]
                    direction = next(d for d in grid["entry"]["directions"] if d["side"] == order["side"])
                    audit.check(grid["clock_allowed"] and row["allowed"] and row["supplied_rank"] is not None, "受理要求に当時の外供給あり", where + key)
                    expected.append({"book_key": key, "policy": policy, "delay_seconds": delay, "entry_order_id": order["id"],
                                     "position_id": order["position_id"], "reference_id": order["reference_id"], "at": grid["at"],
                                     "requested_quantity": order["quantity"], "raw_rank": row["raw_rank"], "supplied_rank": row["supplied_rank"],
                                     "source_method": grid["source"]["method"], "source_at": grid["source"]["at"], "source_index": grid["source"]["source_index"],
                                     "pool_evaluation": deepcopy(row), "current_qualification": deepcopy(direction)})
    for row in current["entry_bindings"]:
        strict(set(row) == ENTRY_BIND_FIELDS and row["at"] in grids, "外新規binding15field/定時")
    BASE.compare(current["entry_bindings"], expected, audit, where, "外新規bindingの受理順・全field・凍結出典")


def inspect_profit_contexts(current: dict, audit: object, where: str) -> dict:
    """
    機能: 初回残玉/全玉旗を当時原行・当時までの返済片へ結合する。
    引数: current(dict)、audit(object)、where(str)は一場・台帳・位置。
    返り値: dictはcontext/残玉旗/全玉旗件数。Current全再計算は主張しない。
    """
    expected, observed = {}, {}
    for key in KEYS:
        book = current["books"][key]
        for lot in book["lots"]:
            for kind, flag, index, at in (("residual", lot["flag"], lot["flag_index"], lot["flag_time"]),
                                         ("whole", lot["whole_flag"], lot["whole_flag_index"], lot["whole_flag_time"])):
                if flag:
                    strict(type(index) is int and index >= 0 and EVENT.finite(at), "利益旗の原行/時計")
                    token = key, lot["id"], kind
                    strict(token not in expected, "利益旗の重複")
                    expected[token] = (index, at, lot, book)
    previous = -1
    template = current["grid_decisions"][0]["c0"]["base"]["evidence"]
    for number, row in enumerate(current["profit_contexts"], 1):
        strict(set(row) == PROFIT_FIELDS and row["id"] == f"P{number:06d}", "利益contextのschema/連番")
        q = row["quote"]
        strict(set(q) == EVENT.QUOTE_FIELDS and type(q["index"]) is int and q["index"] > previous and q["valid"] is True and q["last"] > 0 and 0 < q["bid"] < q["ask"], "利益contextの正常原行/順序")
        previous = q["index"]
        EVENT.validate_technical(q["time"], row["technical"])
        strict(type(row["current_available"]) is bool and row["current_available"] == (row["current"] is not None), "利益Current可用性とnull")
        if row["current"] is not None:
            c = row["current"]
            strict(set(c) == CURRENT_FIELDS and c["reference"] == "NK225" and c["time"] == q["time"] and c["source_line"] == q["line"] and c["time"] <= c["received"] <= q["time"], "利益Currentの当時時計/物理行")
            strict(type(c["source_index"]) is int and c["source_index"] >= 0, "利益Currentの別の源Index型")
            for side in ("buy", "sell"):
                strict(set(c[side]) == SUPPORT_FIELDS, "利益Current支持抜粋9field")
                shape(c[side], {name: template[side][name] for name in SUPPORT_FIELDS}, audit, where + side)
            shape(c["night"], template["night"], audit, where + ".night")
            shape(c["short"], template["short"], audit, where + ".short")
        strict(isinstance(row["triggered_by"], list) and len(row["triggered_by"]) > 0, "利益contextは旗出典あり")
        for trigger in row["triggered_by"]:
            strict(set(trigger) == TRIGGER_FIELDS and trigger["flag_kind"] in ("residual", "whole"), "利益trigger7field/種類")
            token = trigger["book_key"], trigger["position_id"], trigger["flag_kind"]
            strict(token in expected and token not in observed, "初回利益旗の完全一意対応")
            index, at, lot, book = expected[token]
            audit.check(index == q["index"] and at == q["time"] and trigger["reference_id"] == lot["reference_id"], "利益旗の原行/玉/参照ID", where)
            if trigger["flag_kind"] == "whole":
                audit.check(lot["whole_flag_line"] == q["line"], "全玉旗の物理行", where)
            pieces = [p for p in book["closed"] if p["position_id"] == lot["id"] and p["exit_line"] <= q["line"]]
            strict(all(p["exit_time"] <= q["time"] for p in pieces), "利益旗へ未来の返済片混入")
            remaining = lot["initial_quantity"] - sum(p["quantity"] for p in pieces)
            net = sum(p["pnl5"] for p in pieces)
            audit.check(remaining >= 0 and trigger["remaining_after_fill"] == remaining, "初回旗原行までの返済後残量", where)
            audit.check(trigger["closed_net_after_fill"] == net, "初回旗原行までの確定純益", where)
            observed[token] = q["index"]
    audit.check(set(observed) == set(expected), "残玉/全玉の全初回利益旗を観測", where)
    return {"context": len(current["profit_contexts"]), "残玉旗": sum(k[2] == "residual" for k in expected), "全玉旗": sum(k[2] == "whole" for k in expected)}


def policy_actions(book: dict, grids: list[dict], policy: str) -> dict:
    """
    機能: 金融判断を保持し、外filterで隠れた必要未知だけを別政策判断へ分ける。
    引数: book/grids(dict/list[dict])、policy(str)は一会計と全定時。
    返り値: dictは金融/政策の二つのaction件数。
    """
    financial, decisions = Counter(), Counter()
    for decision, grid in zip(book["decisions"], grids, strict=True):
        seen = {o["reference_id"] for o in book["orders"] if o["kind"] == "entry" and o["request_time"] < grid["at"]}
        action = decision["action"]
        financial[action] += 1
        if action == "待ち" and grid["clock_allowed"] and not decision["source_context"]["occupied"]:
            q = grid["c0"]["base"]["quote"]
            quality = q["valid"] and q["last"] > 0 and 0 < q["bid"] < q["ask"] and q["index"] >= 0 and 0 <= grid["at"]-q["time"] <= 15 and grid["source"]["started"] and grid["source"]["at"] == q["time"]
            raw = {r["reference"]["id"]: r["reference"] for r in grid["source"]["lots"]}
            if any(not raw[p["reference_id"]]["closing"] and p["reference_id"] not in seen and (not quality or p["required_unknown"]) for p in grid["policies"][policy]["pool"]):
                action = "判定不能"
        decisions[action] += 1
    return {"金融判断": dict(financial), "方針判断": dict(decisions)}


def guard_empty(value: object, audit: object, where: str) -> None:
    """
    機能: G2で使わない収穫/cash床/funding欄だけが型通り空であることを確認する。
    引数: value(object)、audit(object)、where(str)は保存値と台帳。
    返り値: None。cash_yen等の実確定金額や利益旗は対象外。
    """
    if isinstance(value, dict):
        for name, item in value.items():
            if name.startswith(("harvest", "cash_floor", "funding_fail")):
                audit.check(item is None or type(item) in (int, float) and item == 0 or item is False or item == "", "G2部分収穫/cash床/fundingは未使用", where + "." + name)
            else:
                guard_empty(item, audit, where + "." + name)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            guard_empty(item, audit, where + str(i))


def audit_scene(current: dict, baseline: dict, session: str, times: list[float], audit: object) -> dict:
    """
    機能: 旧88入口/全G1同値と8会計のSource要求・通知・初回利益出典を検査する。
    引数: current/baseline(dict)、session(str)、times(list[float])、audit(object)は89/88と台帳。
    返り値: dictは正本canonicalと比較数。G2価格保護の再計算は別原板へ委譲する。
    """
    BASE.inspect_finite(current, audit, session + ".89")
    BASE.inspect_finite(baseline, audit, session + ".88")
    strict(set(current) == TOP_FIELDS and set(current["books"]) == set(KEYS), "89場本文/8会計集合")
    audit.check(current["session"] == baseline["session"] == session, "場ID", session)
    for name in ("quality", "reference_counts", "source_events", "source_equivalence", "entry_observations", "technical_equivalence", "seed_view", "input_end"):
        BASE.compare(current[name], baseline[name], audit, session, "旧88の" + name + "全文同値")
    grids, old_grids = current["grid_decisions"], baseline["grid_decisions"]
    audit.check([g["at"] for g in grids] == [g["at"] for g in old_grids] == times, "旧C0全定時順序", session)
    EVENT.validate_technical(times[0]-1800, current["seed_view"])
    for grid, old in zip(grids, old_grids, strict=True):
        strict(set(grid) == GRID_FIELDS, "89共有定時11field")
        for name in GRID_FIELDS - {"policies"}:
            BASE.compare(grid[name], old[name], audit, session + str(grid["at"]), "旧88共有" + name + "全文同値")
        BASE.compare(grid["policies"], {p: old["policies"][p] for p in ("E0", "E1")}, audit, session, "旧88のE0/E1供給全文同値")
        OLD.sorted_pool(grid["source"], grid["at"])
    eq = OLD.verify_equivalence(current, times, audit, session)
    tech = current["technical_equivalence"]
    strict(set(tech) == {"core_calls", "quote_calls", "mismatches", "actual_sha256", "event_sha256"}, "Technical同値5field")
    audit.check(all(type(tech[n]) is int and tech[n] >= 0 for n in ("core_calls", "quote_calls", "mismatches")) and tech["core_calls"] >= len(times) and tech["quote_calls"] == current["quality"]["NK225"]["accepted"] and tech["mismatches"] == 0, "旧呼出後の全Technical比較件数", session)
    audit.check(type(tech["actual_sha256"]) is str and len(tech["actual_sha256"]) == 64 and tech["actual_sha256"] == tech["event_sha256"], "独立eventBankの全Technical二指紋一致", session)
    inspect_events(current, audit, session)
    effects, actions = {}, []
    for key in KEYS:
        mode, delay = key.rsplit("_D", 1)
        policy, guard = mode[:-2], mode[-2:]
        book = current["books"][key]
        OLD.validate_book_schema(book, audit, session + key)
        supplied = supplied_grids(current, policy)
        bindings = bind_decisions(book, supplied, session, key, audit)
        OLD.bind_entries(book, bindings, supplied, audit, session + key)
        effects[key] = OLD.bind_effects(book, current["source_events"], session, audit, session + key)
        actions.append({"session": session, "key": key, **policy_actions(book, grids, policy)})
        if guard == "G1":
            BASE.compare(book, baseline["books"][f"{policy}_D{delay}"], audit, session + key, "旧88G1金融全field全文同値")
        else:
            guard_empty(book, audit, session + key)
    inspect_entry_bindings(current, audit, session)
    profit = inspect_profit_contexts(current, audit, session)
    shared = {name: current[name] for name in ("grid_decisions", "source_events", "source_equivalence", "entry_observations", "technical_equivalence", "seed_view", "input_end", "profit_contexts")}
    source = {"session": session, "books": {key: {name: current["books"][key][name] for name in ("source_policy", "decisions", "source_effects")} for key in KEYS}, "entry_bindings": current["entry_bindings"]}
    return {"場": session, "予定枠": len(times), "基準C0枠": len(times), "基準会計": 4, "保存会計": 8,
            "Source互換": eq, "Technical互換": tech, "イベント入力": len(current["entry_observations"]), "外新規binding": len(current["entry_bindings"]),
            "初回利益観測": profit, "Source通知適用": effects, "方針判断": actions,
            "共有判断SHA256": canonical_sha(shared), "参照判断と通知効果SHA256": canonical_sha(source),
            "玉診断SHA256": {key: canonical_sha(OLD.diagnostic_rows(session, key, current["books"][key])) for key in KEYS}}

def audit_directories(source: Path, baseline: Path, sessions: list[str], pinned: dict, audit: object) -> dict:
    """
    機能: 全66場の旧G1264・C02442枠・保存528会計と前後指紋を確認する。
    引数: source/baseline(Path)、sessions(list[str])、pinned(dict)、audit(object)は89/88入力。
    返り値: dictは全場処理と小型正本。原板本文は読まない。
    """
    roots = {"89": source, "88": baseline}
    before = {name: BASE.inventory(path) for name, path in roots.items()}
    wanted = {s + ".json" for s in sessions}
    strict(len(sessions) == len(set(sessions)) == 66, "固定66場")
    for name, values in before.items():
        audit.check(set(values) == wanted, "保存全場集合", name)
    audit.check(before["88"] == pinned, "旧88正式本文指紋", "全体")
    rows, complete = [], True
    try:
        for session in sessions:
            if all(session + ".json" in before[n] for n in roots):
                rows.append(audit_scene(BASE.read_json(source / (session + ".json")), BASE.read_json(baseline / (session + ".json")), session, BASE.scheduled(session), audit))
    except Exception as error:
        complete = False
        audit.check(False, "保存処理未完", "全体", type(error).__name__ + ":" + str(error), "全場完了")
    after = {name: BASE.inventory(path) for name, path in roots.items()}
    audit.check(before == after, "保存入力の前後不変", "全体")
    frames, accounts, old_accounts = (sum(r[name] for r in rows) for name in ("基準C0枠", "保存会計", "基準会計"))
    audit.check((len(rows), frames, accounts, old_accounts) == (66, 2442, 528, 264), "66場2442枠528保存264基準金融", "全体")
    return {"処理完了": complete and (len(rows), frames, accounts, old_accounts) == (66, 2442, 528, 264),
            "場数": len(rows), "予定枠": frames, "基準C0枠": frames, "基準会計": old_accounts, "保存会計": accounts,
            "入力不変": before == after, "入力SHA256前": before, "入力SHA256後": after,
            "Source互換件数": {name: sum(r["Source互換"][name] for r in rows) for name in ("step_frames", "force_frames", "grid_frames", "mismatches")},
            "イベント入力": sum(r["イベント入力"] for r in rows), "外新規binding": sum(r["外新規binding"] for r in rows),
            "対象場": rows, "方針判断": [action for row in rows for action in row["方針判断"]]}


def main() -> None:
    """
    機能: 明示89/88入力を全66場照合し、新規監査正本を保存する。
    引数: --input/--baseline/--out(Path)は全必須。
    返り値: None。未完・不一致は非0終了し、既存証拠を上書きしない。
    """
    parser = argparse.ArgumentParser(description="89の旧88G1・入口同値と二配分の保存出典照合")
    for name in ("input", "baseline", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    strict(not args.out.exists() and not any(args.out.resolve().is_relative_to(p.resolve()) for p in (args.input, args.baseline)), "新規証拠は入力外へ保存")
    audit, small = BASE.Audit(), {}
    code_before, event_before = sha(Path(__file__)), sha(EVENT_PATH)
    data = {"処理完了": False, "場数": 0, "基準C0枠": 0, "基準会計": 0, "保存会計": 0, "入力不変": False}
    try:
        manifest = ROOT / "study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json"
        result88 = ROOT / "study/00088_背景維持と押戻し再開の時系列比較/成果物/結果.json"
        condition89 = ROOT / "study/00089_最低建値床を共通にした収穫配分の比較/条件.json"
        condition88 = ROOT / "study/00088_背景維持と押戻し再開の時系列比較/条件.json"
        for p in (manifest, result88, condition89, condition88, OLD_PATH, EVENT_PATH, FIXED88_PATH):
            small[p.relative_to(ROOT).as_posix()] = sha(p)
        for path in (condition89, condition88):
            condition = BASE.read_json(path)
            groups = [condition["コードと依存SHA256"]] + [value for name, value in condition.items() if name.startswith("固定") and name.endswith("依存") and type(value) is dict]
            groups.append({condition["実行ファイル"]: condition["実行ファイルSHA256"]})
            for group in groups:
                for name, wanted in group.items():
                    audit.check(sha(ROOT / name) == wanted, "新旧固定依存不変", name)
        sessions = [row["id"] for row in BASE.read_json(manifest)["sessions"]]
        data = audit_directories(args.input.resolve(), args.baseline.resolve(), sessions, BASE.read_json(result88)["再生結果SHA256"], audit)
        audit.check({name: sha(ROOT / name) for name in small} == small, "小型依存の前後不変", "全体")
        audit.check(sha(Path(__file__)) == code_before and sha(EVENT_PATH) == event_before and sha(OLD_PATH) == OLD_SHA and sha(FIXED88_PATH) == FIXED88_SHA, "照合コードの前後不変", "全体")
    except Exception as error:
        audit.check(False, "全体処理未完", "全体", type(error).__name__ + ":" + str(error), "完了")
    success = data["処理完了"] and audit.bad == 0
    output = {"試行": 89, "成功": success, **data, "照合項目数": audit.count, "不一致数": audit.bad,
              "不一致": audit.examples, "項目別比較数": dict(audit.scope), "固定小型入力SHA256": small,
              "照合コードSHA256": code_before, "イベント照合コードSHA256": event_before, "読取helperSHA256": OLD_SHA, "固定88保存監査SHA256": FIXED88_SHA,
              "本処理の新売買再生": 0, "本物原板読取": 0,
              "範囲外": ["元指標数値器とFAR生成の独立した別実装", "全原行のG1/Source通知とClose/TR/Last0の原板結合（別原板監査）", "利益Current抜粋の未保存Windows等を含む全文独立再計算"]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({n: output[n] for n in ("成功", "場数", "基準C0枠", "基準会計", "保存会計", "照合項目数", "不一致数")}, ensure_ascii=False))
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
