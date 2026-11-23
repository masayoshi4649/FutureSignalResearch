"""上位の進行、Force逆行波、初回回復、後続終値の順序を一監視で扱う。"""

from collections import Counter, defaultdict
from copy import deepcopy
from fractions import Fraction
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("Force波の精密数値", Path(__file__).with_name("指標.py"))
J = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = J
SPEC.loader.exec_module(J)
SOURCE_FIELDS, FRAME_FIELDS, UPPER_FIELDS = J.SOURCE_FIELDS, J.FRAME_FIELDS, J.UPPER_FIELDS
finite, exact, fraction_value, canonical_sha = J.finite, J.exact, J.fraction_value, J.canonical_sha
frame_projection, upper_projection = J.frame_projection, J.upper_projection
SIGNAL_FIELDS = ("場", "イベントID", "入口ID", "役割", "side", "方向", "要求時計秒", "要求原板行",
    "確認遅延秒", "low", "high", "atr", "bb_mean")
POLICIES = ("T0", "R0", "S0")
ROLES = {"T0": "順行", "R0": "反転", "S0": "切替"}
ACTIVE_ROLES = {"T0": ("順行",), "R0": ("反転",), "S0": ("順行", "反転")}
METADATA_FIELDS = ("元登録ID", "元価格side", "元登録時計秒", "元登録原板行", "回復足番号", "回復時計秒", "判別種別")
WATCH_FIELDS = ("登録ID", "元価格side", "登録足番号", "登録時計秒", "登録原板行", "初期逆端", "段階",
    "回復足番号", "回復時計秒", "回復原板行", "回復ID", "再開端")
RULES = {
    **deepcopy(J.RULES),
    "上位参照": "当場公開15分uとindex-1を下位end/key両asofで参照。最新はmax(confirm,line,index)、前足は同可視集合から選び不在/NP/未来をNone同理由へ。両完全900/missing0/有効OHLC/H有限/index-end隣接/前key<=現key。最新不良から古正常へ戻らない",
    "背景": "D=sign(H15現-H15前)。ヒスト水準は使わず0は準備済み中立。b直前3分pとbの各当時Dが同じ非0であること。同一上位uを二つの独立確認とはしない",
    "登録": "s*Force前>=0かつs*Force現<0の全crossを候補記録。p/bのD=s、一監視空き、同足終了なし、b.confirm<deadlineで受理。bにcutoff/残60/遅延30/ATRを追加しない",
    "寿命": "age=現index-b.index、1..6を回復と価格の両段階で共有しjでresetしない。年齢7以降先満了、場末終了。同時に別波が来ても置換せず候補不受理を保存",
    "回復": "対象足end>b.confirmかつkey>b.key。回復前の元逆端strict終値失敗を先WAIT消費。最初s*Force>0を一回観測しD=sならj固定、D不一致ならWAIT消費。start>親confirmは要求しない",
    "価格": "j後end>j.confirmかつkey>j.keyの最初終値端だけP。買はC>HjをT/C<LbをR、売鏡像。高安touch順序/過去価格約定を使わず、両端等号は未到達。T実side=s/順行、R=-s/反転",
    "終端": "最初端で実side*D>0かつ実side*Force>0/現ATR正/時間遅延可だけ採用。他はWAIT消費し後端へ復活しない。rawはj後初価格端のみ、回復前失敗/回復D不一致はmonitorWAIT終端",
    "優先": "価格公開不正/番号-endgap/Force又は最新上位未準備/期限→age>6→段階時点対象外(寿命のみ)→回復前逆端失敗→初回回復→回復後初価格端。D0/逆転だけではcancelせずATR不正は終端だけWAIT",
    "比較": "T0=T採用のみ/R0=R採用のみ/S0=T又はRの同一監視。単独と混合の経済共通/占有を分け、RをT不採用の補集合にしない。active4役割、全XF",
    "執行": "終端k/fの現在ATR固定D、現時計+1秒正常BBO/TTL30/125250/費用後現在益122円strict正起動/名目床を継承。先着は全新要求/実sideで直接計算。生存中の実建玉とは純監視を分離",
    "競合": "同判断の候補複数は同方向も全見送り。全採否確定後にenriched深写しpure13化、親/回復/上位/将来labelを実運用へ渡さない",
}


def key_of(row: dict) -> tuple:
    """価格公開の同秒行順を得る。

    引数: row(dict)は価格足。
    返り値: tupleはconfirm/confirm_line。
    """
    return row["confirm"], row["confirm_line"]


def price_source(row: dict) -> dict:
    """価格公開SOURCEだけを深写する。

    引数: row(dict)は当場足。
    返り値: dictは場/SOURCE12。
    """
    return {name: deepcopy(row[name]) for name in ("場", *SOURCE_FIELDS)}


def pair_state(current: dict | None, previous: dict | None, lower: dict) -> dict:
    """最新当場15分の現前ヒスト差と未準備理由を作る。

    引数: current/previous(dict|None)は当時可視の最新/隣接前足、lower(dict)は3分判断足。
    返り値: dictは公開参照/準備/ヒスト現前差/方向。未来前足の有無は露出しない。
    """
    reasons = []
    if current is None: reasons.append("当場公開15分なし")
    elif previous is None: reasons.append("前上位公開参照なし")
    for label, row in (("現", current), ("前", previous)):
        if row is None: continue
        if not row["publish"]: reasons.append(label+"15分非公開")
        if not J.price_valid(row, 15): reasons.append(label+"15分完全価格不正")
        if row["missing"]: reasons.append(label+"15分欠枠")
        if row["confirm"] < row["end"]: reasons.append(label+"15分終了前公開")
        if row["end"] > lower["end"] or key_of(row) > key_of(lower): reasons.append(label+"15分asof不成立")
        if not finite(row["macd_hist"]): reasons.append(label+"15分MACDヒスト未準備")
    if current is not None and previous is not None:
        if previous["index"]+1 != current["index"] or previous["end"] != current["start"]:
            reasons.append("上位現前番号又は終了非隣接")
        if key_of(previous) > key_of(current): reasons.append("上位前後公開順不整合")
    ready = not reasons
    delta = current["macd_hist"]-previous["macd_hist"] if ready else None
    if ready and not finite(delta):
        reasons.append("上位MACDヒスト差非有限"); ready = False; delta = None
    sign = (delta > 0)-(delta < 0) if delta is not None else None
    return {"上位参照": upper_projection(current), "前上位参照": upper_projection(previous),
        "上位現前準備": ready, "上位除外理由": reasons,
        "上位ヒスト現": current["macd_hist"] if current is not None else None,
        "上位ヒスト前": previous["macd_hist"] if previous is not None else None,
        "上位ヒスト差": delta, "上位ヒスト差符号": sign, "上位方向": sign}


def upper_state(higher15: list[dict], lower: dict) -> dict:
    """可視集合だけから上位の最新と隣接前足を選ぶ。

    引数: higher15(list[dict])は当場上位14列、lower(dict)は3分判断足。
    返り値: dictはpair_state。最新未準備を古正常で代替しない。
    """
    visible = [row for row in higher15 if row["publish"] and row["end"] <= lower["end"] and key_of(row) <= key_of(lower)]
    current = max(visible, key=lambda row: (*key_of(row), row["index"]), default=None)
    previous = next((row for row in visible if row["index"] == current["index"]-1), None) if current is not None else None
    return pair_state(current, previous, lower)


def pure_signal(row: dict, policy: str = "S0") -> dict:
    """最初価格端の実side/役割と当時13列だけを実運用へ渡す。

    引数: row(dict)は採用enriched又は判定、policy(str)はT0/R0/S0。
    返り値: dictは純13。上位・登録・回復・将来labelを含めない。
    """
    if policy not in POLICIES or row["side"] not in (-1, 1) or row["役割"] not in ACTIVE_ROLES[policy]:
        raise ValueError("候補の実役割と実方向に差")
    if row["方向"] != ("買い" if row["side"] == 1 else "売り"):
        raise ValueError("実方向と表示に差")
    value = {name: deepcopy(row[name]) for name in SIGNAL_FIELDS if name not in ("イベントID", "入口ID", "bb_mean")}
    value.update(イベントID=row["発動ID"]+"_"+policy, 入口ID="3分_"+policy, bb_mean=None)
    return value


def verdicts(row: dict) -> dict:
    """共通終端の技術/時間と、T/R単独又は混合の採用を確定する。

    引数: row(dict)は最初価格端の全判定。
    返り値: dictは三候補の採否/理由。WAITから反対注文を作らない。
    """
    common = list(row["M除外理由"])
    if not row["技術方向可"]: common.append("初価格端の上位又はForce実方向不一致")
    if not row["時間条件可"]: common.append("新要求時間条件外")
    if not row["確認遅延条件可"]: common.append("新要求確認遅延上限外")
    result = {}
    for policy in POLICIES:
        reasons = list(common)
        if policy == "T0" and row["価格区分"] != "T": reasons.append("順行T単独対象外")
        if policy == "R0" and row["価格区分"] != "R": reasons.append("反転R単独対象外")
        result[policy] = {"採用": not reasons, "理由": reasons or ["順序付きForce波と最初価格端採用"], "同時競合": False}
    return result


def event_row(frame: dict, watch: dict, upper: dict, kind: str, cutoff: float, deadline: float, config: dict) -> dict:
    """最初端の構造T/Rと技術/時間のWAITを別旗で保存する。

    引数: frame/watch/upper(dict)は現足/親/上位、kind(str)は構造T/R、cutoff/deadline(float)とconfig(dict)は時間条件。
    返り値: dictは新Pの全当時判定。技術不採用でも構造側の実side/役割を残す。
    """
    side = watch["元価格side"] if kind == "T" else -watch["元価格side"]
    now = frame["confirm"]
    time_ok = now < cutoff and now < deadline and deadline-now >= config["残り時間下限分"]*60
    delay_ok = now-frame["end"] <= config["確認遅延上限秒"]
    missing = []
    if not upper["上位現前準備"]: missing.append("最新上位現前未準備")
    if not frame["Force2"]["有効"]: missing.append("Force2未準備")
    if not finite(frame["atr"]) or frame["atr"] <= 0: missing.append("現在ATR14有限正未準備")
    direction_ok = bool(upper["上位方向"] == side and frame["Force符号"] == side)
    event = watch["登録ID"]+f"_初価格端_{frame['index']:04d}_{kind}"
    final_kind = kind if not missing and direction_ok and time_ok and delay_ok else "WAIT"
    row = {**J.numeric_projection(frame), "時間足分": 3, "入口系統": "Force波の初価格端",
        "発動ID": event, "イベントID": event, "入口ID": "3分_Force波", "元登録ID": watch["登録ID"],
        "元価格side": watch["元価格side"], "元登録時計秒": watch["登録時計秒"], "元登録原板行": watch["登録原板行"],
        "登録足番号": watch["登録足番号"], "回復足番号": watch["回復足番号"], "回復時計秒": watch["回復時計秒"],
        "回復原板行": watch["回復原板行"], "回復ID": watch["回復ID"], "初期逆端": watch["初期逆端"], "再開端": watch["再開端"],
        "年齢": frame["index"]-watch["登録足番号"], "価格区分": kind, "判別種別": final_kind,
        "役割": "順行" if kind == "T" else "反転", "side": side, "方向": "買い" if side == 1 else "売り",
        **deepcopy(upper), "共通M準備": not missing, "M除外理由": missing, "技術方向可": direction_ok,
        "時間条件可": time_ok, "確認遅延条件可": delay_ok, "要求時計秒": now, "要求原板行": frame["confirm_line"],
        "足終了時計秒": frame["end"], "確認遅延秒": now-frame["end"], "期限時計秒": deadline,
        "残り分_判断時": (deadline-now)/60, "先着評価対象": time_ok and delay_ok, "bb_mean": None}
    row["戦略判定"] = verdicts(row)
    return row


# ----------------------------------------
# 一監視の純価格機械。実pendingや建玉占有は後段の三運用へだけ委ねる。

def generate(frames: list[dict], higher15: list[dict], session: str,
             cutoff: float, deadline: float, config: dict) -> dict:
    """背景を知る→逆行cross→初回回復→後続初価格端の一巡を構築する。

    引数: frames(list[dict])は新Force26列、higher15(list[dict])は当場上位14列、session(str)は場、
    cutoff/deadline(float)は新規停止/強制、config(dict)は終端の残時間/遅延条件。
    返り値: dictは全数値/全cross登録/全監視/新P/三enriched/metadata/品質。先着・運用は計算しない。
    """
    upper_rows = [upper_projection(row) for row in higher15]
    if any(row["場"] != session or row["minutes"] != 15 for row in upper_rows):
        raise ValueError("当場15分の新Hだけです")
    if len({row["index"] for row in upper_rows}) != len(upper_rows):
        raise ValueError("上位足番号は一意だけです")
    rows = [J.numeric_projection(row) for row in frames]
    records, registrations, trace = [], [], []
    watch, previous, prior_upper, public_key = None, None, None, None
    for frame in rows:
        if frame["場"] != session or frame["minutes"] != 3: raise ValueError("当場Force3分だけです")
        if previous is not None and frame["index"] <= previous["index"]: raise ValueError("下位足番号重複又は後退")
        key = key_of(frame)
        if frame["publish"] and (frame["confirm"] < frame["end"] or public_key is not None and key <= public_key):
            raise ValueError("下位公開key同値/後退又は終了前公開")
        upper = upper_state(upper_rows, frame)
        actions, before = [], deepcopy(watch)
        had_watch = watch is not None
        price_ok = bool(frame["publish"] and not frame["missing"] and J.price_valid(frame))
        adjacent = previous is None or previous["index"]+1 == frame["index"] and previous["end"] == frame["start"]
        cancel_reasons = []
        if not price_ok: cancel_reasons.append("完全公開3分価格不正")
        if not adjacent: cancel_reasons.append("価格番号又は終了非連続")
        if not frame["Force2"]["有効"]: cancel_reasons.append("Force2未準備")
        if not upper["上位現前準備"]: cancel_reasons.append("最新上位現前未準備")
        if frame["confirm"] >= deadline: cancel_reasons.append("強制期限到達")
        if watch is not None:
            age = frame["index"]-watch["登録足番号"]
            parent_time = watch["登録時計秒"] if watch["段階"] == "回復待ち" else watch["回復時計秒"]
            parent_line = watch["登録原板行"] if watch["段階"] == "回復待ち" else watch["回復原板行"]
            if cancel_reasons:
                actions.append({"動作": "監視取消", "登録ID": watch["登録ID"], "年齢": age, "理由": cancel_reasons})
                watch = None
            elif age > 6:
                actions.append({"動作": "寿命満了", "登録ID": watch["登録ID"], "年齢": age, "理由": ["元bから6足超"]})
                watch = None
            elif frame["end"] <= parent_time or key <= (parent_time, parent_line):
                actions.append({"動作": "段階時点対象外", "登録ID": watch["登録ID"], "年齢": age, "理由": ["親確認後の終了key未成立"]})
            else:
                side = watch["元価格side"]
                failed = side*(Fraction(frame["close"])-Fraction(watch["初期逆端"])) < 0
                if watch["段階"] == "回復待ち":
                    if failed:
                        actions.append({"動作": "回復前失敗WAIT", "登録ID": watch["登録ID"], "年齢": age, "理由": ["回復前に元逆端strict終値失敗"]})
                        watch = None
                    elif side*frame["Force符号"] > 0:
                        if upper["上位方向"] != side:
                            actions.append({"動作": "初回回復不一致WAIT", "登録ID": watch["登録ID"], "年齢": age, "理由": ["初Force回復時の上位D不一致"]})
                            watch = None
                        else:
                            recovery = watch["登録ID"]+f"_回復_{frame['index']:04d}"
                            watch.update(段階="価格待ち", 回復足番号=frame["index"], 回復時計秒=frame["confirm"],
                                回復原板行=frame["confirm_line"], 回復ID=recovery,
                                再開端=frame["high"] if side == 1 else frame["low"])
                            actions.append({"動作": "初回回復固定", "登録ID": watch["登録ID"], "回復ID": recovery, "年齢": age,
                                "回復参照": {"足出典": price_source(frame), "Force2": deepcopy(frame["Force2"]), **deepcopy(upper)}})
                else:
                    resumed = side*(Fraction(frame["close"])-Fraction(watch["再開端"])) > 0
                    if resumed or failed:
                        record = event_row(frame, watch, upper, "T" if resumed else "R", cutoff, deadline, config)
                        records.append(record)
                        actions.append({"動作": "初価格端消費", "登録ID": watch["登録ID"], "発動ID": record["発動ID"],
                            "年齢": age, "価格区分": record["価格区分"], "判別種別": record["判別種別"]})
                        watch = None
        if frame["Force前"]["有効"] and frame["Force2"]["有効"]:
            old_force, current_force = fraction_value(frame["Force前"]), fraction_value(frame["Force2"])
            for side in (1, -1):
                if not (side*old_force >= 0 and side*current_force < 0): continue
                reasons = []
                if previous is None or not adjacent or not price_ok: reasons.append("登録の同場隣接価格未準備")
                if prior_upper is None or not prior_upper["上位現前準備"] or not upper["上位現前準備"]:
                    reasons.append("登録p/b上位現前未準備")
                elif prior_upper["上位方向"] != side or upper["上位方向"] != side:
                    reasons.append("登録p/b背景D不一致")
                if had_watch: reasons.append("監視中又は同足で監視終了")
                if frame["confirm"] >= deadline: reasons.append("登録強制期限以降")
                event = f"NK225_{session}_3分_Force波登録_{frame['index']:04d}_{side}"
                registration = {"場": session, "登録ID": event, "元価格side": side, "登録足": frame_projection(frame),
                    "前足番号": previous["index"] if previous is not None else None, "前足Force": deepcopy(frame["Force前"]),
                    "登録Force": deepcopy(frame["Force2"]), "前上位状態": deepcopy(prior_upper), "登録上位状態": deepcopy(upper),
                    "受理": not reasons, "登録除外理由": reasons}
                registrations.append(registration)
                actions.append({"動作": "Force波登録不受理" if reasons else "Force波登録", "登録ID": event,
                    "元価格side": side, "理由": list(reasons)})
                if not reasons:
                    watch = {"登録ID": event, "元価格side": side, "登録足番号": frame["index"],
                        "登録時計秒": frame["confirm"], "登録原板行": frame["confirm_line"],
                        "初期逆端": frame["low"] if side == 1 else frame["high"], "段階": "回復待ち",
                        "回復足番号": None, "回復時計秒": None, "回復原板行": None, "回復ID": None, "再開端": None}
        trace.append({"場": session, "index": frame["index"], "足出典": price_source(frame), "Force2": deepcopy(frame["Force2"]),
            "上位参照足番号": upper["上位参照"]["index"] if upper["上位参照"] is not None else None,
            "前上位参照足番号": upper["前上位参照"]["index"] if upper["前上位参照"] is not None else None,
            "上位現前準備": upper["上位現前準備"], "上位除外理由": deepcopy(upper["上位除外理由"]),
            "上位方向": upper["上位方向"], "監視前": before, "動作": actions, "監視後": deepcopy(watch)})
        previous, prior_upper = frame, upper
        if frame["publish"]: public_key = key
    ending = watch is not None
    if ending:
        trace[-1]["動作"].append({"動作": "場末監視取消", "登録ID": watch["登録ID"], "理由": ["場末"]})
        trace[-1]["監視後"] = None
    competing = defaultdict(list)
    for row in records:
        for policy in POLICIES:
            if row["戦略判定"][policy]["採用"]:
                competing[policy, row["要求時計秒"], row["要求原板行"]].append(row)
    for (policy, _, _), same in competing.items():
        if len(same) > 1:
            for row in same: row["戦略判定"][policy].update(採用=False, 理由=["同判断複数信号見送り"], 同時競合=True)
    signals = {"3分_"+policy: [] for policy in POLICIES}
    for row in records:
        for policy in POLICIES:
            if row["戦略判定"][policy]["採用"]:
                signals["3分_"+policy].append({**deepcopy(row), "イベントID": row["発動ID"]+"_"+policy,
                    "入口ID": "3分_"+policy, "戦略": policy, "複合判定": deepcopy(row["戦略判定"][policy])})
    metadata = {row["発動ID"]: {name: deepcopy(row[name]) for name in METADATA_FIELDS} for row in records}
    actions = Counter(action["動作"] for item in trace for action in item["動作"])
    quality = {"場": session, "時間足分": 3, "入力足数": len(rows), "Force逆行cross候補数": len(registrations),
        "監視受理数": sum(row["受理"] for row in registrations), "初回回復数": actions["初回回復固定"],
        "初価格端数": len(records), "価格区分別": dict(Counter(row["価格区分"] for row in records)),
        "判別種別": dict(Counter(row["判別種別"] for row in records)), "監視動作別": dict(actions),
        "場末残監視取消数": int(ending), "終了時監視残数": 0,
        "先着評価対象外数": sum(not row["先着評価対象"] for row in records),
        "戦略別発動数": {sid: len(values) for sid, values in signals.items()},
        "戦略採否理由別": {p: dict(Counter(reason for row in records for reason in row["戦略判定"][p]["理由"])) for p in POLICIES}}
    return {"場": session, "frames": {3: rows, 15: upper_rows}, "signals": signals, "raw": records, "decisions": records,
        "registrations": registrations, "monitor_trace": trace, "metadata": metadata, "quality": quality}
