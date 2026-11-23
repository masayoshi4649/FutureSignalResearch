"""91の旧89対照全文と利確完了後の複数実参加・公開機会を監査する。"""

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
FIXED89_PATH = ROOT / "scripts/FAR利益床と収穫配分の比較/基準と保存判断の照合.py"
FIXED89_SHA = "604602263965696407dfc8906e10c71ff51841115f1ba37b9a97fe207859437b"
KEYS = tuple(f"{mode}_D{delay}" for delay in (0, 1) for mode in ("R0", "R1"))
MODES = {"R0": "S0G1", "R1": "S0G1"}
TOP_FIELDS = {"session", "quality", "reference_counts", "books", "grid_decisions", "source_events", "source_equivalence", "entry_observations", "entry_bindings", "technical_equivalence", "seed_view", "input_end", "profit_contexts", "entry_opportunities"}
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


FIXED90_PATH = ROOT / "scripts/FAR押戻し確定終値の固定床/基準と保存判断の照合.py"
FIXED90_SHA = "239201498d4302554eb1bd41103a1e5a61b9bd365d4b78545268cffae2a7fdf5"
assert sha(FIXED90_PATH) == FIXED90_SHA, "固定90保存監査の変更"
assert sha(FIXED89_PATH) == FIXED89_SHA, "固定89保存監査の変更"
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
        strict(set(grid["policies"]) == {"E1"}, "外政策E1集合")
        for policy in ("E1",):
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
    expected_mode = MODES[key.split('_D')[0]]
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
        for policy in ("E1",):
            for mode in ("R0", "R1"):
                for delay in (0, 1):
                    key = f"{mode}_D{delay}"
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


integer=OLD.integer
flatten_events=OLD.flatten_events
filled_before=OLD.filled_before


def before_cut(at: float, line: int, time: float, source_line: int) -> bool:
    """
    機能: 当定時の直前原行までの経済事象か確認する。
    引数: at/time(float)、line/source_line(int)は定時境界と事象の時計/物理行。
    返り値: boolは現在境界以前なら真。
    """
    return time<=at and source_line<=line


def pending_at91(order: dict, book: dict, session: str, at: float, line: int, effects: list | None = None) -> int:
    """
    機能: 現在世代の要求後通知だけから過去の未約定量を再構成する。
    引数: order/book(dict)、session(str)、at(float)、line(int)、effects(list|None)は対象境界。
    返り値: intは当時残量。前世代の取消を引かない。
    """
    if order['request_time']>=at or order['request_line']>line or filled_before(order,at,line):return 0
    if order['kind']=='exit':return order['quantity']
    if any(order['request_time']<t<=at for t in OLD.force_times(session)):return 0
    earlier=book['source_effects'] if effects is None else effects
    cancelled=sum(e['cancelled'] for e in earlier if e['reference_id']==order['reference_id'] and OLD.event_before(e,at,line) and
      (e['at']>order['request_time'] or e['at']==order['request_time'] and e['origin']=='quote' and e['quote_line']>order['request_line']))
    strict(0<=cancelled<=order['quantity'],'現在要求以後の取消量')
    return order['quantity']-cancelled


def inspect_opportunities(current: dict, audit: object, where: str) -> dict:
    """
    機能: E1供給順に候補機会と全点公開recordを独立に結合する。
    引数: current(dict)、audit(object)、where(str)は一場保存と台帳。
    返り値: dictは(at,ref)別level。履歴資格は金融からの入力としない。
    """
    records={r['id']:r for r in current['entry_observations']};strict(len(records)==len(current['entry_observations']),'公開recordのID重複')
    expected=[];levels={}
    stored={(r['at'],r['reference_id']):r for r in current['entry_opportunities']}
    strict(len(stored)==len(current['entry_opportunities']),'機会levelの重複')
    for grid in current['grid_decisions']:
        raw={r['reference']['id']:r['reference'] for r in grid['source']['lots']};pool={r['reference_id']:r for r in grid['policies']['E1']['pool']}
        q=grid['c0']['base']['quote']
        for rank,ref in enumerate(grid['policies']['E1']['supplied_ids'],1):
            row=raw[ref];evaluation=pool[ref];direction=next(d for d in grid['entry']['directions'] if d['side']==row['side']);event=direction['event']
            strict(grid['clock_allowed'] and direction['e1_allowed'] and direction['event_valid'] and event is not None and evaluation['allowed'] and evaluation['supplied_rank']==rank,'現在E1と機会候補の結合')
            publications=[];seen=set();last_ordinal=0
            for name in ('impulse','pullback','recovery','confirmation'):
                point=event[name];identity=point['observation_id']
                if identity in seen:continue
                strict(identity in records,'機会の公開record欠落');record=records[identity];x=record['input'];source=x['quote']
                strict(x['at']==point['published_at'] and x['technical']['bar3_end']==point['bar_end'] and x['at']<=grid['at'] and x['window']==event['window'] and x['epoch_start']==event['epoch_start'] and not x['after_eof'],'機会の同窓/公開時計')
                strict(x['ordinal']>last_ordinal and 0<source['time']<=x['at'] and source['time']<=q['time'] and 0<=source['index']<=q['index'] and 0<source['line']<=q['line'] and source['last']>0,'機会のordinal/当時原行')
                publications.append({'observation_id':identity,'ordinal':x['ordinal'],'at':x['at'],'bar_end':x['technical']['bar3_end'],'origin':x['origin'],'quote':deepcopy(source)})
                seen.add(identity);last_ordinal=x['ordinal']
            opportunity={'known':True,'kind':'E1順行再開機会','rule_version':1,'at':grid['at'],'reference_id':ref,'side':row['side'],
              'opportunity_id':{'session':current['session'],'reference_id':ref,'event_id':event['id']},'event':deepcopy(event),'publications':publications,'reason':'現在E1の公開event出典を固定'}
            token=grid['at'],ref;strict(token in stored,'機会levelの保存欠落');actual=stored[token]
            strict(set(actual)=={'at','reference_id','raw_rank','supplied_rank','opportunity','assessments'} and set(actual['assessments'])=={'R1_D0','R1_D1'},'機会level6tag/遅延別assessment')
            target={'at':grid['at'],'reference_id':ref,'raw_rank':evaluation['raw_rank'],'supplied_rank':rank,'opportunity':opportunity}
            BASE.compare({n:actual[n] for n in target},target,audit,where,'機会10tag/公開6tagの独立構成')
            levels[token]=actual;expected.append(token)
    audit.check([(r['at'],r['reference_id']) for r in current['entry_opportunities']]==expected,'全機会候補の実供給順',where)
    return levels


def at_state(book: dict, session: str, at: float, line: int) -> tuple[list, list]:
    """
    機能: 全世代の実取得済み玉と当時までの返済片を抽出する。
    引数: book(dict)、session(str)、at(float)、line(int)は一会計と過去境界。
    返り値: tuple[list,list]は実玉と返済片。終局のQuantityを過去へ流用しない。
    """
    lots=[p for p in book['lots'] if before_cut(at,line,p['entry_time'],p['entry_line'])]
    pieces=[p for p in book['closed'] if before_cut(at,line,p['exit_time'],p['exit_line'])]
    return lots,pieces


def chrono(name: str, pub: dict, done: dict) -> dict:
    """
    機能: 公開が実全返済より後かを同時計の両原行番号まで検査する。
    引数: name(str)、pub/done(dict)は点名・公開値・完結stamp。
    返り値: dictは既知性と後条件。保存Index精密値はSource原板依存。
    """
    item={'point':name,'known':True,'after':False,'reason':''};q=pub['quote']
    if pub['at']>done['at']:item.update(after=True,reason='実全返済より後の公開時計')
    elif pub['at']<done['at']:item['reason']='実全返済より前の公開時計'
    elif q['time']==done['at'] and q['index']>done['quote_index'] and q['line']>done['quote_line']:item.update(after=True,reason='同時計の別原行で両番号が実全返済より後')
    elif q['time']==done['at'] and q['index']==done['quote_index'] and q['line']==done['quote_line']:item['reason']='同原行は公開が金融fillより先'
    elif q['time']<=done['at'] and q['index']<=done['quote_index'] and q['line']<=done['quote_line']:item['reason']='同時計の公開原行が実全返済より前'
    else:item.update(known=False,reason='同時計の公開原行の前後を両番号で証明できない')
    return item


def model_reentry(current: dict, book: dict, key: str, levels: dict, audit: object, where: str) -> dict:
    """
    機能: R1の当時所有・直近実参加・機会消費から全資格/選定を別計算する。
    引数: current/book(dict)、key(str)、levels(dict)、audit(object)、where(str)は一場と会計。
    返り値: dictはentryOrderID別の受理出典。Index厳密値は原板証拠へ分担する。
    """
    seen=set();used=set();accepted={};by_position={};serial=0
    orders_by_position={o['position_id']:o for o in book['orders'] if o['kind']=='entry'}
    strict(len(orders_by_position)==sum(o['kind']=='entry' for o in book['orders']),'受理position IDの一意性')
    for grid,decision in zip(current['grid_decisions'],book['decisions'],strict=True):
        at=grid['at'];q=grid['c0']['base']['quote'];line=q['line'];session=current['session'];supply=supplied_grids({'grid_decisions':[grid]},'E1')[0];source=supply['source'];pool=OLD.sorted_pool(source,at) if grid['clock_allowed'] else []
        lots,pieces=at_state(book,session,at,line)
        remaining={p['id']:p['initial_quantity']-sum(c['quantity'] for c in pieces if c['position_id']==p['id']) for p in lots}
        owned=any(n>0 for n in remaining.values());pending=any(pending_at91(o,book,session,at,line)>0 for o in book['orders'] if o['kind']=='entry');occupied=owned or pending
        quality=q['valid'] and q['last']>0 and 0<q['bid']<q['ask'] and q['time']<=at and at-q['time']<=15 and q['index']>=0 and source['started'] and source['at']==q['time']
        assessments=[];candidates=[];role_ranks=Counter();before_count=len(seen)
        for rank,row in enumerate(pool,1):
            ref=row['reference'];identity=ref['id'];level=levels[at,identity];op=level['opportunity'];opkey=(session,identity,op['event']['id']);was_seen=identity in seen;role='利確後再参加' if was_seen else '初参加';role_ranks[role]+=1
            a={'at':at,'reference_id':identity,'side':ref['side'],'opportunity_id':deepcopy(op['opportunity_id']),'role':role,'supplied_rank':rank,'role_rank':role_ranks[role],'selection_rank':0,'source_seen':was_seen,'opportunity_seen':opkey in used,'previous_actual':None,'chronology':[],'known':True,'required_unknown':False,'eligible':False,'selected':False,'consumed':False,'reason':'','entry_order_id':'','position_id':'','accepted_serial':0}
            history=not was_seen
            if not was_seen:a['reason']='未参加のfresh参照'
            else:
                prior=[p for p in lots if p['reference_id']==identity]
                if not prior:a['reason']='受理履歴だけで実取得した参加がない'
                else:
                    p=max(prior,key=lambda p:(p['entry_time'],p['entry_index'],p['entry_line'],p['id']));pid=p['id'];entry=orders_by_position[pid];strict(pid in by_position,'過去実玉の機会受理元')
                    closed=[c for c in pieces if c['position_id']==pid];qty=sum(c['quantity'] for c in closed);net=sum(10*c['side']*(c['exit_price']-c['entry_price'])*c['quantity']-122*c['quantity'] for c in closed)
                    strict(all(c['entry_price']==p['entry_price'] and c['side']==p['side'] for c in closed),'過去実片の建値/方向')
                    audit.check(net==sum(c['pnl5'] for c in closed),'過去実fill価格からの純額',where)
                    pend_entry=pending_at91(entry,book,session,at,line);pend_exit=sum(pending_at91(o,book,session,at,line) for o in book['orders'] if o['kind']=='exit' and o['position_id']==pid)
                    previous={'position_id':pid,'entry_order_id':entry['id'],'opportunity_id':deepcopy(by_position[pid]['opportunity_id']),'initial_quantity':p['initial_quantity'],'quantity':p['initial_quantity']-qty,'reserved_exit':pend_exit,'closed_quantity':qty,'net_pnl':net,'pending_entry':pend_entry,'pending_exit':pend_exit,'completion':None}
                    if qty==p['initial_quantity']:
                        last=max(closed,key=lambda c:c['exit_line']);observed=level['assessments'][key]['previous_actual'];strict(observed is not None and observed['completion'] is not None,'完結出典の保存欠落')
                        index=observed['completion']['quote_index'];strict(type(index) is int and p['entry_index']<=index<=q['index'],'完結Indexの型/過去境界・精密値はSource原板')
                        previous['completion']={'position_id':pid,'entry_order_id':entry['id'],'at':last['exit_time'],'quote_index':index,'quote_line':last['exit_line'],'initial_quantity':p['initial_quantity'],'closed_quantity':qty,'net_pnl':net}
                    a['previous_actual']=previous
                    if previous['quantity']!=0 or qty!=p['initial_quantity'] or pend_entry or pend_exit or previous['completion'] is None:a['reason']='直近実参加の全返済又は未約定残0が未完了'
                    elif net<=0:a['reason']='直近実参加の費用後実確定額がstrict正でない'
                    elif a['opportunity_seen'] or previous['opportunity_id']['event_id']==op['event']['id']:a['reason']='同じ再開eventは取消後も再利用しない'
                    else:
                        publications={r['observation_id']:r for r in op['publications']}
                        a['chronology']=[chrono(name,publications[op['event'][point]['observation_id']],previous['completion']) for name,point in (('p','pullback'),('r','recovery'),('k','confirmation'))]
                        history=True
                        for c in a['chronology']:
                            if not c['known']:a.update(known=False,required_unknown=True,reason='新p/r/kの公開前後が未知');history=False;break
                            if not c['after']:a['reason']='p/r/kの全点が前回実全返済より後でない';history=False;break
                        if history:a['reason']='直近利確完了後の別eventを確認'
            if ref['closing']:a['reason']='参照返済予約あり'
            elif occupied:a['reason']='実保有又は注文で占有'
            elif not quality:a.update(known=False,required_unknown=True,reason='Source又は気配品質が未知')
            elif history:a['eligible']=True
            assessments.append(a);candidates.append({'reference_id':identity,'source_quantity':ref['quantity'],'requested_quantity':0,'side':ref['side'],'role':ref['kind'],'reason':'','source_check':{'rank':rank,'seen':was_seen,'eligible':False,'c0_passed':grid['c0']['allowed'] and grid['c0']['side']==ref['side'],'required_unknown':False,'selected':False,'real_entry_stage':'利確後再参加候補' if was_seen else '初参加候補','reason':''}})
        priority=sorted(range(len(pool)),key=lambda i:(assessments[i]['source_seen'],i));selected=''
        action,reason=('保有継続','同時一建玉を維持') if owned else ('処理中','既存注文の約定待ち') if occupied else ('待ち','有効な参照玉なし')
        entries=[o for o in book['orders'] if o['kind']=='entry' and o['request_time']==at]
        for selection_rank,i in enumerate(priority,1):
            a=assessments[i];a['selection_rank']=selection_rank
            if not a['eligible']:continue
            if selected:a['reason']='同枠の優先候補を採用済み';continue
            strict(len(entries)==1,'必要な再参加/初参加要求が未保存');o=entries[0];ref=pool[i]['reference'];quantity=min(100,ref['quantity']);serial+=1
            strict(o['reference_id']==ref['id'] and o['position_id']==f'{session}_S0G1_P{serial:06d}','fresh優先/世代採番/参照選定')
            binding=OLD.binding_value('S',supply,pool[i],i+1,quantity)
            metadata={'binding':binding,'entry_role':a['role'],'opportunity_id':deepcopy(a['opportunity_id']),'accepted_serial':serial,'position_id':o['position_id'],'quantity':quantity}
            accepted[o['id']]=metadata;by_position[o['position_id']]=metadata;seen.add(ref['id']);used.add((session,ref['id'],a['opportunity_id']['event_id']));selected=ref['id']
            a.update(selected=True,consumed=True,entry_order_id=o['id'],position_id=o['position_id'],accepted_serial=serial,reason='E1現在機会で'+a['role']+'要求');candidates[i]['requested_quantity']=quantity;action,reason='新規要求',a['reason']
        strict(len(entries)==int(bool(selected)),'不要な受理要求又は必要要求の欠落')
        for i,a in enumerate(assessments):
            c=candidates[i];c['reason']=a['reason'];c['source_check'].update(selected=a['selected'],eligible=a['eligible'],required_unknown=a['required_unknown'],reason=a['reason'])
            BASE.compare(levels[at,a['reference_id']]['assessments'][key],a,audit,where+str(at),'全候補の履歴/消費/公開順/選定21tag')
        unknown=any(a['required_unknown'] for a in assessments)
        if action=='待ち' and unknown:action,reason='判定不能','再参加の必要出典が未知'
        context={'policy':'S','method':source['method'],'snapshot_at':source['at'],'snapshot_index':source['source_index'],'started':source['started'],'occupied':occupied,'seen_before_count':before_count,'seen_after_count':len(seen),'selected_id':selected,'required_unknown':unknown,'c0_used':False}
        BASE.compare(decision,{'at':at,'quote_time':q['time'],'quote_index':q['index'],'action':action,'reason':reason,'candidates':candidates,'source_context':context},audit,where,'全候補と金融判断の別計算')
    strict(set(accepted)=={o['id'] for o in book['orders'] if o['kind']=='entry'},'受理要求全件と履歴出典')
    return accepted


def bind_entries91(book: dict, metadata: dict, grids: list, audit: object, where: str) -> None:
    """
    機能: 要求時出典をposition世代別に全注文/玉/返済へ不変継承させる。
    引数: book/metadata(dict)、grids(list)、audit(object)、where(str)は対象と期待受理。
    返り値: None。ref一件化せず取消要求も全件確認する。
    """
    by_time={g['at']:g for g in grids};entries={o['position_id']:o for o in book['orders'] if o['kind']=='entry'}
    strict(len(entries)==sum(o['kind']=='entry' for o in book['orders']),'entry position IDの重複')
    for position,o in entries.items():
        meta=metadata[o['id']];binding=meta['binding'];grid=by_time[o['request_time']];q=grid['c0']['base']['quote'];ref=binding['read_lot']['reference']
        BASE.compare(o['source'],ref,audit,where,'受理Source参照の不変コピー')
        audit.check(o['quantity']==meta['quantity'] and o['side']==ref['side'] and o['role']==ref['kind'] and o['request_index']==q['index'] and o['request_line']==q['line'],'受理量/元段階/要求原行',where)
        audit.check(o['filled_quantity']+o['cancelled_quantity']+o['remaining']==o['quantity'] and o['structure_anchor']==grid['structure_anchor'],'受理量保存/EMA出典',where)
    for container,name in BASE.CONTAINERS.items():
        for row in book[container]:
            position=row['id'] if name=='ActualLot' else row['position_id'];strict(position in entries,'実世代の新規要求元');entry=entries[position];meta=metadata[entry['id']]
            BASE.compare(row['source_entry'],meta['binding'],audit,where+container,'SourceEntryを他世代や後の量で上書きしない')
            stage=('利確後再参加要求' if meta['entry_role']=='利確後再参加' else '初参加要求') if name=='ActualOrder' and row['kind']=='entry' else ('利確後再参加' if meta['entry_role']=='利確後再参加' else '実初参加')
            audit.check(row['real_entry_stage']==stage,'元Kindと実世代役割を分離',where)
    for lot in book['lots']:
        entry=entries[lot['id']];pieces=[c for c in book['closed'] if c['position_id']==lot['id']]
        audit.check(0<lot['initial_quantity']==entry['filled_quantity']<=entry['quantity']<=100 and lot['initial_quantity']==lot['quantity']+lot['closed_quantity'] and lot['closed_quantity']==sum(c['quantity'] for c in pieces),'世代別の実取得/残量/返済保存',where)
        audit.check(lot['net_pnl']==sum(c['pnl5'] for c in pieces) and all(c['entry_price']==lot['entry_price'] and c['entry_time']==lot['entry_time'] for c in pieces),'世代別の建値と実確定額',where)
    qty=sum(o['filled_quantity'] for o in entries.values());exit_qty=sum(c['quantity'] for c in book['closed'])
    for name,wanted in (('entry_quantity',qty),('exit_quantity',exit_qty),('commission_yen',11*(qty+exit_qty)),('slippage_yen',50*(qty+exit_qty)),('total_cost_yen',61*(qty+exit_qty))):audit.check(book['metrics'][name]==wanted,'実世代の数量費用',where+name)


def diagnostic_rows91(session: str, key: str, book: dict, metadata: dict) -> list:
    """
    機能: 全positionの旧玉診断へ受理時の実役割/機会/serial3tagを結ぶ。
    引数: session/key(str)、book/metadata(dict)は金融と受理出典。
    返り値: listはref重複を失わない正式玉診断。
    """
    output=OLD.diagnostic_rows(session,key,book)
    for row in output:
        if key.startswith('R0_'):row.update(entry_role='初参加',opportunity_id=None,accepted_serial=None)
        else:
            meta=metadata[row['entry_order']['id']];row.update(entry_role=meta['entry_role'],opportunity_id=deepcopy(meta['opportunity_id']),accepted_serial=meta['accepted_serial'])
    return output


def policy_actions91(current: dict, key: str) -> dict:
    """
    機能: 金融待ちだけにE1外側の必要未知を履歴候補別に分類する。
    引数: current(dict)、key(str)は一場保存と会計。
    返り値: dictは金融/政策二判断。占有/処理中/新規を変えない。
    """
    book=current['books'][key];financial=Counter();policy=Counter()
    for d,g in zip(book['decisions'],current['grid_decisions'],strict=True):
        action=d['action'];financial[action]+=1
        if action=='待ち' and g['clock_allowed'] and not d['source_context']['occupied']:
            q=g['c0']['base']['quote'];at=g['at'];line=q['line'];seen={o['reference_id'] for o in book['orders'] if o['kind']=='entry' and o['request_time']<at};lots,pieces=at_state(book,current['session'],at,line);eligible=set()
            for row in g['source']['lots']:
                ref=row['reference'];identity=ref['id']
                if ref['closing']:continue
                if identity not in seen:eligible.add(identity);continue
                if key.startswith('R0_'):continue
                prior=[p for p in lots if p['reference_id']==identity]
                if not prior:continue
                p=max(prior,key=lambda p:(p['entry_time'],p['entry_index'],p['entry_line'],p['id']));closed=[c for c in pieces if c['position_id']==p['id']]
                if sum(c['quantity'] for c in closed)==p['initial_quantity'] and sum(c['pnl5'] for c in closed)>0:eligible.add(identity)
            quality=q['valid'] and q['last']>0 and 0<q['bid']<q['ask'] and 0<=at-q['time']<=15 and q['index']>=0 and q['line']>0 and g['source']['started'] and g['source']['at']==q['time']
            if eligible and (not quality or any(p['required_unknown'] for p in g['policies']['E1']['pool'] if p['reference_id'] in eligible)):action='判定不能'
        policy[action]+=1
    return {'金融判断':dict(financial),'方針判断':dict(policy)}


def audit_scene(current: dict, baseline: dict, session: str, times: list, audit: object) -> dict:
    """
    機能: 対照132全文と新4会計の全世代/機会/初回利益を保存値から検査する。
    引数: current/baseline(dict)、session(str)、times(list)、audit(object)は91/89と台帳。
    返り値: dictは共有/Source/全世代のcanonicalと小型証拠。
    """
    BASE.inspect_finite(current,audit,session+'.91');BASE.inspect_finite(baseline,audit,session+'.89');strict(set(current)==TOP_FIELDS and set(current['books'])==set(KEYS),'91本文14項/4会計集合')
    audit.check(current['session']==baseline['session']==session,'場ID',session)
    for name in ('quality','reference_counts','source_events','source_equivalence','entry_observations','technical_equivalence','seed_view','input_end'):BASE.compare(current[name],baseline[name],audit,session,'旧89共有'+name+'全文同値')
    audit.check([g['at'] for g in current['grid_decisions']]==[g['at'] for g in baseline['grid_decisions']]==times,'全2442定時順',session)
    for grid,old in zip(current['grid_decisions'],baseline['grid_decisions'],strict=True):
        strict(set(grid)==GRID_FIELDS,'共有定時11tag')
        for name in GRID_FIELDS-{'policies'}:BASE.compare(grid[name],old[name],audit,session+str(grid['at']),'旧89共有'+name)
        BASE.compare(grid['policies'],{'E1':old['policies']['E1']},audit,session,'旧89 E1供給全文')
    eq=OLD.verify_equivalence(current,times,audit,session);tech=current['technical_equivalence'];audit.check(tech['mismatches']==0 and tech['actual_sha256']==tech['event_sha256'] and len(tech['actual_sha256'])==64,'Technical二指紋一致',session)
    inspect_events(current,audit,session);levels=inspect_opportunities(current,audit,session);actions=[];effects={};diagnostics={};accepted_counts={}
    for key in KEYS:
        book=current['books'][key];delay=key[-1];OLD.validate_book_schema(book,audit,session+key);audit.check(book['mode']=='S0G1' and book['source_policy']=='S' and book['fill_delay_seconds']==int(delay),'金融mode/遅延',session+key);supplied=supplied_grids(current,'E1')
        if key.startswith('R0_'):
            BASE.compare(book,baseline['books']['E1G1_D'+delay],audit,session+key,'旧89 E1G1 control全JSON全文')
            by_ref=bind_decisions(book,supplied,session,key,audit);metadata={o['id']:{'binding':by_ref[o['reference_id']],'entry_role':'初参加','opportunity_id':None,'accepted_serial':None,'quantity':o['quantity']} for o in book['orders'] if o['kind']=='entry'}
        else:metadata=model_reentry(current,book,key,levels,audit,session+key)
        bind_entries91(book,metadata,supplied,audit,session+key);effects[key]=bind_effects91(book,current['source_events'],session,audit,session+key);diagnostics[key]=diagnostic_rows91(session,key,book,metadata)
        accepted_counts[key]=dict(Counter(m['entry_role'] for m in metadata.values()));actions.append({'session':session,'key':key,**policy_actions91(current,key)})
    inspect_entry_bindings(current,audit,session);profit=inspect_profit_contexts(current,audit,session)
    shared={n:current[n] for n in ('grid_decisions','source_events','source_equivalence','entry_observations','technical_equivalence','seed_view','input_end','profit_contexts','entry_opportunities')}
    source={'session':session,'books':{key:{n:current['books'][key][n] for n in ('source_policy','decisions','source_effects')} for key in KEYS},'entry_bindings':current['entry_bindings']}
    return {'場':session,'予定枠':len(times),'基準C0枠':len(times),'基準会計':2,'保存会計':4,'Source互換':eq,'Technical互換':tech,'イベント入力':len(current['entry_observations']),'再参加機会候補':len(levels),'外新規binding':len(current['entry_bindings']),'受理役割':accepted_counts,'初回利益観測':profit,'Source通知適用':effects,'方針判断':actions,'共有判断SHA256':canonical_sha(shared),'参照判断と通知効果SHA256':canonical_sha(source),'玉診断SHA256':{k:canonical_sha(v) for k,v in diagnostics.items()},'完結Indexの限定':'保存は型/範囲と時刻/Line/数量/価格純額を検査、Index精密値は同じJSONを読んだSource原板証拠へ分担'}


EFFECT_FIELDS = OLD.EFFECT_FIELDS


def bind_effects91(book: dict, events: list[dict], session: str, audit: object, where: str) -> dict:
    """
    機能: 全通知の比例取消/未予約返済・0丸め・要求時刻を保存注文片から別式で検査する。
    引数: book (dict)、events (list[dict])、session (str)、audit (Audit)、where (str) は保存値。
    返り値: dict は通知/0作用/取消/返済量。全原行順序は別Source通知原板監査と分担する。
    """
    flattened=flatten_events(events,audit,where); effects=book['source_effects']; prior=[]; totals=Counter()
    audit.check(len(effects)==len(flattened),'全Source通知を全会計へ一度配送',where)
    previous_orders=0
    for effect,(event,close) in zip(effects,flattened,strict=True):
        strict(set(effect)==EFFECT_FIELDS,'SourceEffect18tag集合')
        quote=event['quote']; at=event['at']; line=quote['line']
        wanted={'id':close['id'],'reference_id':close['reference_id'],'at':at,'quote_time':quote['time'],'quote_index':quote['index'],'quote_line':line,'origin':event['origin'],'before':close['before'],'quantity':close['quantity'],'reason':close['reason']}
        BASE.compare({name:effect[name] for name in wanted},wanted,audit,where,'通知18欄の原共有イベント出典')
        for name in ('pending_before','cancelled','unreserved_before','exit_requested','unreserved_after','orders_before_count','orders_after_count'):
            strict(integer(effect[name]),'SourceEffect非負整数')
        before=effect['orders_before_count']; after=effect['orders_after_count']
        audit.check(previous_orders<=before<=after<=len(book['orders']),'SourceEffect当時の注文prefix',where); previous_orders=after
        prefix=book['orders'][:before]; identity=close['reference_id']
        pending=sum(pending_at91(order,book,session,at,line,prior) for order in prefix if order['kind']=='entry' and order['reference_id']==identity)
        quantity=reserved=0
        for lot in book['lots']:
            if lot['reference_id']!=identity or lot['entry_time']>at or lot['entry_line']>line: continue
            quantity+=lot['initial_quantity']-sum(piece['quantity'] for piece in book['closed'] if piece['position_id']==lot['id'] and piece['exit_time']<=at and piece['exit_line']<=line)
        for order in prefix:
            if order['kind']=='exit' and order['reference_id']==identity and not filled_before(order,at,line): reserved+=order['quantity']
        available=max(0,quantity-reserved)
        cancel=pending if close['quantity']==close['before'] else pending*close['quantity']//close['before']
        requested=available if close['quantity']==close['before'] else available*close['quantity']//close['before']
        expected={'pending_before':pending,'cancelled':cancel,'unreserved_before':available,'exit_requested':requested,'unreserved_after':available-requested}
        BASE.compare({name:effect[name] for name in expected},expected,audit,where,'Source比例・floor0と全量末尾の別式')
        audit.check(after==before+int(requested>0),'Source返済注文追加件数',where)
        if requested:
            order=book['orders'][before]
            audit.check(effect['exit_order_id']==order['id'] and order['kind']=='exit' and order['reference_id']==identity and order['quantity']==requested and order['request_time']==at and order['request_line']==line and order['request_index']==quote['index'] and order['reason']=='参照返済:'+close['reason'],'Source返済要求と注文全対応',where)
        else: audit.check(effect['exit_order_id']=='','Source0丸めで注文非創作',where)
        prior.append(effect); totals['通知']+=1; totals['0作用']+=cancel==requested==0; totals['取消枚']+=cancel; totals['返済要求枚']+=requested; totals['timer通知']+=event['origin']=='timer'
    return dict(totals)


def audit_directories(source: Path, baseline: Path, sessions: list[str], pinned: dict, audit: object) -> dict:
    """
    機能: 全66場の旧R0基準132・C02442枠・保存264会計と前後指紋を確認する。
    引数: source/baseline(Path)、sessions(list[str])、pinned(dict)、audit(object)は91/89入力。
    返り値: dictは全場処理と小型正本。原板本文は読まない。
    """
    roots = {"91": source, "89": baseline}
    before = {name: BASE.inventory(path) for name, path in roots.items()}
    wanted = {s + ".json" for s in sessions}
    strict(len(sessions) == len(set(sessions)) == 66, "固定66場")
    for name, values in before.items():
        audit.check(set(values) == wanted, "保存全場集合", name)
    audit.check(before["89"] == pinned, "旧89正式本文指紋", "全体")
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
    audit.check((len(rows), frames, accounts, old_accounts) == (66, 2442, 264, 132), "66場2442枠264保存132基準金融", "全体")
    return {"処理完了": complete and (len(rows), frames, accounts, old_accounts) == (66, 2442, 264, 132),
            "場数": len(rows), "予定枠": frames, "基準C0枠": frames, "基準会計": old_accounts, "保存会計": accounts,
            "入力不変": before == after, "入力SHA256前": before, "入力SHA256後": after,
            "Source互換件数": {name: sum(r["Source互換"][name] for r in rows) for name in ("step_frames", "force_frames", "grid_frames", "mismatches")},
            "イベント入力": sum(r["イベント入力"] for r in rows), "外新規binding": sum(r["外新規binding"] for r in rows),
            "対象場": rows, "方針判断": [action for row in rows for action in row["方針判断"]]}


def main() -> None:
    """
    機能: 明示91/89入力を全66場照合し、新規監査正本を保存する。
    引数: --input/--baseline/--out(Path)は全必須。
    返り値: None。未完・不一致は非0終了し、既存証拠を上書きしない。
    """
    parser = argparse.ArgumentParser(description="91の旧89対照と複数実世代/機会の保存照合")
    for name in ("input", "baseline", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    strict(not args.out.exists() and not any(args.out.resolve().is_relative_to(p.resolve()) for p in (args.input, args.baseline)), "新規証拠は入力外へ保存")
    audit, small = BASE.Audit(), {}
    code_before, event_before = sha(Path(__file__)), sha(EVENT_PATH)
    data = {"処理完了": False, "場数": 0, "基準C0枠": 0, "基準会計": 0, "保存会計": 0, "入力不変": False}
    try:
        manifest = ROOT / "study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json"
        result89 = ROOT / "study/00089_最低建値床を共通にした収穫配分の比較/成果物/結果.json"
        condition91 = ROOT / "study/00091_利確完了後の新しい再開へ再参加/条件.json"
        condition89 = ROOT / "study/00089_最低建値床を共通にした収穫配分の比較/条件.json"
        for p in (manifest, result89, condition91, condition89, OLD_PATH, EVENT_PATH, FIXED88_PATH, FIXED89_PATH, FIXED90_PATH):
            small[p.relative_to(ROOT).as_posix()] = sha(p)
        for path in (condition91, condition89):
            condition = BASE.read_json(path)
            groups = [condition["コードと依存SHA256"]] + [value for name, value in condition.items() if name.startswith("固定") and name.endswith("依存") and type(value) is dict]
            groups.append({condition["実行ファイル"]: condition["実行ファイルSHA256"]})
            for group in groups:
                for name, wanted in group.items():
                    audit.check(sha(ROOT / name) == wanted, "新旧固定依存不変", name)
        sessions = [row["id"] for row in BASE.read_json(manifest)["sessions"]]
        data = audit_directories(args.input.resolve(), args.baseline.resolve(), sessions, BASE.read_json(result89)["再生結果SHA256"], audit)
        audit.check({name: sha(ROOT / name) for name in small} == small, "小型依存の前後不変", "全体")
        audit.check(sha(Path(__file__)) == code_before and sha(EVENT_PATH) == event_before and sha(OLD_PATH) == OLD_SHA and sha(FIXED88_PATH) == FIXED88_SHA and sha(FIXED89_PATH) == FIXED89_SHA and sha(FIXED90_PATH) == FIXED90_SHA, "照合コードの前後不変", "全体")
    except Exception as error:
        audit.check(False, "全体処理未完", "全体", type(error).__name__ + ":" + str(error), "完了")
    success = data["処理完了"] and audit.bad == 0
    output = {"試行": 91, "成功": success, **data, "照合項目数": audit.count, "不一致数": audit.bad,
              "不一致": audit.examples, "項目別比較数": dict(audit.scope), "固定小型入力SHA256": small,
              "照合コードSHA256": code_before, "イベント照合コードSHA256": event_before, "読取helperSHA256": OLD_SHA, "固定88保存監査SHA256": FIXED88_SHA, "固定89保存監査SHA256": FIXED89_SHA, "固定90保存監査SHA256": FIXED90_SHA,
              "本処理の新売買再生": 0, "本物原板読取": 0,
              "範囲外": ["元指標数値器とFAR生成の独立した別実装", "全原行G1/Sourceと完結Index精密値・公開出典の原板結合（別原板監査）", "利益Current抜粋の未保存Windows等を含む全文独立再計算"]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({n: output[n] for n in ("成功", "場数", "基準C0枠", "基準会計", "保存会計", "照合項目数", "不一致数")}, ensure_ascii=False))
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
