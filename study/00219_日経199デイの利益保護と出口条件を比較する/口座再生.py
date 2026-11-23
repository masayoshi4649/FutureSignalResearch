"""日経199_02の口座全体と、元の181建玉に出口だけを適用した結果を再生する。"""
import argparse
from functools import lru_cache
from hashlib import sha256
import json
from math import inf
from pathlib import Path
import runpy

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = runpy.run_path(str(next((ROOT / "study").glob("00217_*/日経/入口を再生する.py"))))
FINANCE = SOURCE["FINANCE"]
ORIGINAL = "IFD"
EXIT_NAMES = {1: "利確先着", 2: "損切先着", 3: "通常期限返済", 4: "事前要求の強制返済"}


def orders(arrays: dict, scene_id: int, scene: dict, index: object) -> tuple:
    """
    機能：213の新規締切までの全候補・予約・取得対応を、同じ原行と時計で準備する。
    引数：arrays・scene（dict）は純入口配列と場定義、scene_id（int）は元の場番号、indexは原板索引。
    返り値：tuple。原行キー、各行の取得又は失効、期限と方向を含む入力配列。
    """
    limit = scene["end"] - 960
    active = (arrays["scene"] == scene_id) & (arrays["time"] < limit)
    a = {k: v[active] for k, v in arrays.items()}
    keys, captures = [], []
    for row in range(len(a["time"])):
        keys.append((float(a["time"][row]), int(a["index"][row]), int(a["line"][row])))
        at = float(a["finish_time"][row])
        found = int(a["q1_index"][row])
        line = int(a["finish_line"][row])
        if at >= limit:
            captures.append({"status": "cancelled", "finish_key": (limit, inf, inf)})
        elif found < 0:
            captures.append({"status": "cancelled", "finish_key": (at, int(a["finish_index"][row]), line)})
        else:
            assert index.times[found] == at and index.rows["source_line"][found] == line
            captures.append({"status": "filled", "fill_key": (at, found, line), "case": found})
    return keys, captures, a


def excursions(index: object, entry: int, end: int, side: int, price: float) -> dict:
    """
    機能：当該建玉の取得から決済又は最後に観測可能だった原行までの清算側含み損益を測る。
    引数：indexは原板索引、entry・end・side（int）は両端と側、price（float）は新規価格。
    返り値：dict。往復費用後の含み損益の両極値と最初の到達日時。決済後の板は含めない。
    """
    start, stop = np.searchsorted(index.normal, [entry, end + 1])
    valid = index.normal[start:stop]
    assert len(valid) and valid[0] == entry and valid[-1] == end
    marks = index.rows["bid" if side == 0 else "ask"][valid]
    if side == 0:
        high, low = valid[marks.argmax()], valid[marks.argmin()]
    else:
        high, low = valid[marks.argmin()], valid[marks.argmax()]
    column, sign = ("bid", 1) if side == 0 else ("ask", -1)
    return {"max_unrealized_net": float((index.rows[column][high] - price) * sign * 100 - 1077),
            "min_unrealized_net": float((index.rows[column][low] - price) * sign * 100 - 1077),
            "max_unrealized_time": float(index.times[high]), "min_unrealized_time": float(index.times[low])}


def exits(index: object, scene: dict, policy: dict) -> object:
    """
    機能：指定場の決済を元のIFDと新条件で評価し、同一の取得・側・幅・期限の結果を共用する。
    引数：indexは原板索引、scene・policy（dict）は場定義と出口モジュールの関数表。
    返り値：callable。引数は候補IDと取得・側・幅・期限、返り値は決済済み又は観測不足の元帳。
    """
    cut = scene["end"] - 900
    forced = FINANCE["closing"](index, cut)
    context = policy["prepare"](index, scene)
    legacy = FINANCE["early179"]

    @lru_cache(maxsize=None)
    def original(entry: int, side: int, width: float, horizon: str) -> tuple:
        """
        機能：元IFDを再生し、共通の期限と欠測終端を決める。
        引数：entry・side（int）は原行と側、width（float）とhorizon（str）は値幅と期限。
        返り値：tuple。213の元帳と179の期限結果。
        """
        nominal = inf if horizon == "SESSION" else float(index.times[entry]) + int(horizon[1:])*60
        term = legacy.terminal(index, entry, nominal, cut, forced)
        return FINANCE["settle"](index, entry, side, width, horizon, cut, forced, "NK225"), term

    @lru_cache(maxsize=None)
    def at(code: str, entry: int, side: int, width: float, horizon: str) -> dict:
        """
        機能：出口の決定原行を実際の返済側価格と時刻に引き直し、未知を区別する。
        引数：code（str）は方策ID、entry・side（int）は取得と側、width（float）とhorizon（str）は元注文。
        返り値：dict。新規・決済原行、費用後損益、保有中の最大・最小含み損益を含む。
        """
        base, term = original(entry, side, width, horizon)
        t = dict(base)
        if code == ORIGINAL:
            end = t["exit_index"]
            reason = EXIT_NAMES.get(t["status"], legacy.STATUS[t["status"]])
        else:
            changed = policy["decide"](code, context, index, entry, side, width, horizon, term)
            end = int(changed["exit_index"])
            assert end == -1 or (entry < end < term["touch_end"] or end == term["exit"])
            reason = str(changed["reason"])
            t.update({k: v for k, v in changed.items() if k not in ("reason", "exit_index", "status")})
            status = int(changed.get("status", base["status"] if end == base["exit_index"] else 5))
            t.update(exit_index=end, status=status)
            if end < 0:
                assert term["exit"] == -1 and status >= 10
                t.update(exit_time=None, exit_line=-1, exit_price=None, gross=None, net=None, label=2,
                         confirmed_until=term["lower"])
            else:
                assert index.rows["normal"][end] and index.times[end] <= cut
                price = float(index.rows["bid" if side == 0 else "ask"][end])
                gross = (price - t["entry_price"]) * (100 if side == 0 else -100)
                assert status in (1, 2, 3, 4, 5)
                t.update(exit_time=float(index.times[end]), exit_line=int(index.rows["source_line"][end]),
                         exit_price=price, gross=gross, net=gross-1077,
                         label={1: 1, 2: -1}.get(status, 0), confirmed_until=float(index.times[end]))
        last = end if end >= 0 else index.last_normal(entry, term["touch_end"])
        t.update(excursions(index, entry, last, side, t["entry_price"]),
                 exit_reason=reason, exit_strategy=code)
        return t

    return at


def replay(stream: tuple, scene: dict, code: str, settle: object) -> tuple:
    """
    機能：固定199の全要求を予約込み1枠で再生し、返済後から次の要求を受ける。
    引数：stream（tuple）は原行キー・取得対応・入口、scene（dict）は場、code（str）とsettleは出口IDと算出関数。
    返り値：tuple。その場の新規・決済明細と元予約エンジンの監査件数。
    """
    keys, captures, a = stream
    trades = {}

    def book(event: int, entry: int, side: int, width: int) -> float | None:
        """
        機能：取得が成立した要求を記帳し、保有枠解放の時計を返す。
        引数：event・entry・side・width（int）は場内要求、原行、注文側、IFD幅。
        返り値：floatまたはNone。返済確定秒又は場末まで未知。
        """
        horizon = FINANCE["HORIZONS"][int(a["hi"][event])] if a["core"][event] != 0 else "H60"
        trade = dict(settle(code, entry, side, width, horizon), scene=scene["session"],
                     request_time=keys[event][0], request_line=keys[event][2],
                     added=bool(a["added"][event]), branch=int(a["branches"][event]))
        trades[event] = trade
        return trade["exit_time"]

    positions = FINANCE["engine173"].replay(keys, np.zeros(len(keys), int), np.array([scene["start"]]),
                                            np.array([scene["end"]-900]), captures,
                                            *(a[k] for k in ("core", "branches", "technical", "tier", "mw", "fw")),
                                            200, book)
    result = [dict(trades[r["event"]], origin=r["origin"]) for r in positions["records"]]
    audit = positions["audits"][0]
    assert audit["peak_global_reserved"] <= 1 and audit["filled"] == len(result)
    assert all(t["exit_time"] is not None and t["exit_time"] < u["request_time"] for t, u in zip(result, result[1:]))
    return result, audit


def calculate(policy: dict, codes: list) -> tuple:
    """
    機能：全45場で元の口座を照合し、各口座の再予約と元181建玉固定の二通りを再現する。
    引数：policy（dict）は出口定義、codes（list）は元IFDを除いて比較する候補ID。
    返り値：tuple。両モードの元帳と基準一致・期間・予約枠の監査。
    """
    dates, originals, _ = SOURCE["SUMMARY"]["sources"]("デイ")
    reference = originals["216:日経199_02"]
    books = {mode: {code: [] for code in [ORIGINAL, *codes]} for mode in ("口座再生", "入口固定")}
    used, observed = set(), {}
    check_keys = ("scene", "side", "width", "horizon", "entry_index", "entry_line", "entry_time", "entry_price",
                  "exit_index", "exit_line", "exit_price", "exit_time", "net", "status", "label", "confirmed_until", "origin")
    for folder, archive, member, manifest in SOURCE["parts"]():
        scenes, arrays, *_ = SOURCE["inputs"](folder, archive, member)
        indices = {s["session"]: s for s in SOURCE["read"](manifest)["scenes"]}
        for i, scene in enumerate(scenes):
            day = scene["session"]
            if day not in dates or day in used:
                continue
            used.add(day)
            index = FINANCE["load_scene"](manifest.parent, indices[day])
            stream = orders(arrays, i, scene, index)
            settle = exits(index, scene, policy)
            baseline, original_audit = replay(stream, scene, ORIGINAL, settle)
            saved = [r for r in reference if r["scene"] == day]
            assert all(all(t[k] == r[k] for k in check_keys) for t, r in zip(baseline, saved, strict=True))
            for mode in books:
                books[mode][ORIGINAL].extend(baseline)
            observed[day] = {ORIGINAL: original_audit["filled"]}
            # ----------------------------------------
            for code in codes:
                account, audit = replay(stream, scene, code, settle)
                books["口座再生"][code].extend(account)
                observed[day][code] = audit["filled"]
                for t in baseline:
                    changed = settle(code, t["entry_index"], t["side"], t["width"], t["horizon"])
                    books["入口固定"][code].append(dict(t, **changed))
    assert used == set(dates) and len(used) == 45 and len(reference) == 181
    assert sum(t["net"] for t in books["口座再生"][ORIGINAL]) == 1020063
    assert all(len(ledger) == 181 for ledger in books["入口固定"].values())
    return books, {"対象場": dates, "照合済み元建玉": 181, "元照合属性": check_keys, "場別の取得数": observed}


def main() -> None:
    """
    機能：出口候補を再生し型付き比較元帳と再現指紋を作業領域に保存する。
    引数：CLIの --出口定義（Path）、--候補（str列、省略は全て）、--出力（Path）。
    返り値：None。指定先に比較元帳.json・再生照合.jsonを作る。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--出口定義", type=Path, default=HERE/"出口候補.py")
    parser.add_argument("--候補", nargs="*")
    parser.add_argument("--出力", type=Path, default=ROOT/"work/219出口")
    args = parser.parse_args()
    module = runpy.run_path(str(args.出口定義))
    codes = list(module["POLICIES"]) if args.候補 is None else args.候補
    assert ORIGINAL not in codes and len(set(codes)) == len(codes) and set(codes) <= set(module["POLICIES"])
    books, report = calculate(module, codes)
    args.出力.mkdir(parents=True, exist_ok=True)
    report.update(再生器SHA256=sha256(Path(__file__).read_bytes()).hexdigest(),
                  出口定義SHA256=sha256(args.出口定義.read_bytes()).hexdigest())
    for name, data in (("比較元帳", books), ("再生照合", report)):
        (args.出力/(name+".json")).write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf8")
    for code in [ORIGINAL, *codes]:
        group = books["口座再生"][code]
        print(code, len(group), sum(t["net"] for t in group if t["net"] is not None), flush=True)


if __name__ == "__main__":
    main()
