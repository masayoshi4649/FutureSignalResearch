"""固定した外部研究の着想を125/250先着と一建玉運用で比較する。"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
from datetime import datetime
import gzip
import importlib.util
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00008_外部研究を共通尺度へ移して探索"
WORK = ROOT / "work/外部研究/探索00008"


def module(path: Path, name: str):
    """既存の固定コードを読み取る。

    引数: path (Path) は実装、name (str) はモジュール名。
    返り値: ModuleType は読み込んだ処理。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


W = module(ROOT / "scripts/広域研究/検証.py", "外部探索の足と先着")
O = module(ROOT / "scripts/広域研究/運用検証.py", "外部探索の固定運用")


# ----------------------------------------
# 固定した候補と、判断時点までの特徴を定義する。

def rules(config: dict) -> list[dict]:
    """計画から32条件と旧固定対照を列挙する。

    引数: config (dict) は固定条件。
    返り値: list[dict] は一意な候補ID・時間足・閾値・補助。
    """
    result = []
    for size in config["時間足分"]:
        for family, parameters in config["手法"].items():
            for parameter in parameters:
                for extra in config["補助"]:
                    result.append({"候補ID": f"{size}分_{family}_{parameter}_{extra}", "時間足分": size,
                                   "手法": family, "パラメータ": parameter, "補助": extra})
    if len(result) != config["新候補数"]:
        raise ValueError("新候補数が計画と異なる")
    result.append({"候補ID": config["対照ID"], "時間足分": 3, "手法": "開始幅失敗復帰", "パラメータ": 15, "補助": "ADX環境"})
    if len({r["候補ID"] for r in result}) != len(result):
        raise ValueError("候補ID重複")
    return result


def defined(*values: float | None) -> bool:
    """計算に必要な値の準備状態を調べる。

    引数: values (float | None) は指標の値。
    返り値: bool は全値が定義された有限値か。
    """
    return all(v is not None and math.isfinite(v) for v in values)


def upper_state(higher: dict | None) -> tuple[bool, int]:
    """確定上位足の準備と方向を区別する。

    引数: higher (dict | None) は利用可能な15分確定足。
    返り値: tuple[bool, int] は準備済みフラグと買1/中立0/売-1。
    """
    if higher is None or not higher["publish"] or not defined(higher["ema20"], higher["ema20_previous"]):
        return False, 0
    direction = 1 if higher["close"] > higher["ema20"] > higher["ema20_previous"] else (
        -1 if higher["close"] < higher["ema20"] < higher["ema20_previous"] else 0)
    return True, direction


def enrich(frames: list[dict], higher: list[dict]) -> list[dict]:
    """同場の前足・過去RSI窓・利用可能上位足を付加する。

    引数: frames (list[dict]) は一尺度の確定足、higher (list[dict]) は同場15分足。
    返り値: list[dict] は未来値を使わない特徴。欠枠で過去窓を切る。
    """
    result, history = [], deque(maxlen=5)
    pointer, upper = 0, None
    for frame in frames:
        if frame["missing"]:
            history.clear()
        while pointer < len(higher) and (higher[pointer]["confirm"], higher[pointer]["confirm_line"]) <= (frame["confirm"], frame["confirm_line"]) and higher[pointer]["end"] <= frame["end"]:
            upper = higher[pointer]
            pointer += 1
        ready, direction = upper_state(upper)
        prior = history[-1] if history else {}
        row = {**frame, "前値": {key: prior.get(key) for key in ("close", "rsi", "adx", "plus_di", "minus_di", "bb_mean", "bb_sd")},
               "過去RSI": [v["rsi"] for v in history], "上位準備済": ready, "上位方向": direction,
               "上位確認秒": upper["confirm"] if upper is not None else None,
               "上位確認行": upper["confirm_line"] if upper is not None else None,
               "上位足終了秒": upper["end"] if upper is not None else None}
        result.append(row)
        history.append(frame)
    return result


def allowed(row: dict, rule: dict) -> bool:
    """現在までの特徴から一候補の入口を判定する。

    引数: row (dict) は特徴・方向、rule (dict) は固定した規則。
    返り値: bool は発動条件と補助の成立。将来ラベルを参照しない。
    """
    if row["時間足分"] != rule["時間足分"]:
        return False
    if rule["手法"] == "開始幅失敗復帰":
        return W.allowed(row, rule)
    family, parameter, side = rule["手法"], rule["パラメータ"], row["side"]
    p = row["前値"]
    if not defined(p["close"]) or side * (row["close"] - p["close"]) <= 0:
        return False
    rsi = row["rsi"] if side == 1 else (100 - row["rsi"] if row["rsi"] is not None else None)
    previous_rsi = p["rsi"] if side == 1 else (100 - p["rsi"] if p["rsi"] is not None else None)
    trigger = False
    if family == "RSI回復":
        trigger = defined(rsi, previous_rsi) and previous_rsi <= parameter < rsi
    elif family == "RSI再加速":
        history = row["過去RSI"][-parameter:]
        directional = history if side == 1 else [None if v is None else 100-v for v in history]
        trigger = (len(history) == parameter and defined(rsi, previous_rsi, row["ema20"], *history)
                   and previous_rsi <= 50 < rsi and min(directional) <= 40 and side * (row["close"]-row["ema20"]) > 0)
    elif family == "DMI方向発生":
        trigger = (defined(row["plus_di"], row["minus_di"], p["plus_di"], p["minus_di"], row["adx"], p["adx"], row["ema20"])
                   and side*(p["plus_di"]-p["minus_di"]) <= 0 < side*(row["plus_di"]-row["minus_di"])
                   and row["adx"] >= parameter and row["adx"] > p["adx"] and side*(row["close"]-row["ema20"]) > 0)
    elif family == "BB復帰価格確認":
        trigger = (defined(p["bb_mean"], p["bb_sd"], row["bb_mean"], row["bb_sd"])
                   and side*(p["close"]-p["bb_mean"]) < -parameter*p["bb_sd"]
                   and side*(row["close"]-row["bb_mean"]) >= -parameter*row["bb_sd"])
    else:
        raise ValueError("未知の入口系統")
    if not trigger or rule["補助"] == "なし":
        return bool(trigger)
    low_adx = defined(row["adx"], p["adx"]) and row["adx"] < 20 and row["adx"] <= p["adx"]
    if family == "RSI回復":
        return low_adx
    if family == "RSI再加速":
        return row["上位準備済"] and row["上位方向"] == side
    if family == "DMI方向発生":
        return row["上位準備済"] and row["上位方向"] != -side
    return low_adx and row["上位準備済"] and row["上位方向"] == 0


# ----------------------------------------
# 入口と運用の分母・支持・固定順位を集計する。

def phase_of(session: str, config: dict) -> str:
    """セッション開始日を事前の分割へ割り当てる。

    引数: session (str) は場、config (dict) は条件。
    返り値: str は学習・条件選択・後続検査。
    """
    return "後続検査" if session[:10] >= config["分割"]["後続開始日"] else (
        "条件選択" if session[:10] >= config["分割"]["選択開始日"] else "学習")


def entry_metrics(rows: list[dict], phase: str) -> dict:
    """固定済みの入口集計を利用する。

    引数: rows (list[dict]) は一候補の事例、phase (str) は期間名。
    返り値: dict は五分類・確認率・間引き・日別等。
    """
    return W.metrics(rows, phase)


def operation_metrics(infos: list[dict], trades: list[dict]) -> dict:
    """一期間の運用、活動頻度、品質、利益の集中を集約する。

    引数: infos (list[dict]) は場別品質、trades (list[dict]) は完結取引。
    返り値: dict は費用感度等。空白や未完を含む全体確定額はNone。
    """
    sessions = {t["場"] for t in trades}
    daily = defaultdict(float)
    for trade in trades:
        daily[trade["場"]] += trade["基準純損益円"]
    profits = sum(max(0, v) for v in daily.values())
    attention = sum(bool(i["観測経路注意"]) for i in infos)
    result = {"入力場数": len(infos), "完結取引数": len(trades), "活動場数": len(sessions),
              "活動開始日数": len({s[:10] for s in sessions}), "無取引場数": len(infos)-len(sessions),
              "買い取引数": sum(t["方向"] == "買い" for t in trades), "売り取引数": sum(t["方向"] == "売り" for t in trades),
              "黒字取引数": sum(t["基準純損益円"] > 0 for t in trades), "保有分合計": sum(t["保有分"] for t in trades),
              "保有時間率_観測": sum(t["保有分"] for t in trades) / sum(i["場時間分"] for i in infos) if infos else None,
              "赤字場数": sum(v < 0 for v in daily.values()), "品質注意場数": attention,
              "未解消場数": sum(i["終了建玉"] for i in infos), "EOF期限未達場数": sum(i["EOF期限未達"] for i in infos),
              "黒字場利益の最大場寄与": max((max(0, v) for v in daily.values()), default=0) / profits if profits else None}
    for slip in (0, 5, 10):
        net = sum(t[f"追加滑り{slip}pt純損益円"] for t in trades)
        result[f"追加{slip}pt純損益円"] = net
        result[f"追加{slip}pt平均円"] = net / len(trades) if trades else None
        result[f"追加{slip}pt確定対象円"] = None if attention else net
    return result


def fixed_files(study: Path) -> dict[str, str]:
    """後続確認前に固定する小さな入力と実装を列挙する。

    引数: study (Path) は試行フォルダ。
    返り値: dict[str, str] はrepo相対パスとSHA256。
    """
    paths = [Path(__file__), Path(__file__).with_name("合成検証.py"), ROOT / "scripts/広域研究/検証.py", ROOT / "scripts/広域研究/運用検証.py",
             ROOT / "scripts/入口分析/分析.py", ROOT / "scripts/入口探索/評価.py", ROOT / "scripts/複合検証/データ準備.py",
             ROOT / "scripts/複合検証/再生.py", ROOT / "study/00001_MACDと方向条件の比較/再現.py",
             study / "計画.md", study / "条件.json", study / "入力台帳.json", study / "外部参照台帳.json"]
    return {p.relative_to(ROOT).as_posix(): O.sha(p) for p in paths}


def select(results: list[dict], config: dict) -> dict:
    """旧64場だけから入口用と費用用を事前順位で固定する。

    引数: results (list[dict]) は全候補の期間別結果、config (dict) は支持と順位条件。
    返り値: dict は固定ID、資格内訳、70目標達成数。
    """
    candidates = [r for r in results if r["候補ID"] != config["対照ID"]]
    for row in candidates:
        row["入口支持"] = all(W.supported(row[phase]["入口"], limits) for phase, limits in config["入口支持"].items())
        row["70目標"] = row["入口支持"] and all(row[phase]["入口"]["確認率"] >= config["目標確認率"]
            and row[phase]["入口"]["30分間引き_約定候補数"] >= config["間引き必要件数"][phase]
            and row[phase]["入口"]["30分間引き_確認率"] >= config["目標確認率"] for phase in ("学習", "条件選択"))
        row["費用資格"] = all(W.supported(row[phase]["運用"], limits) and row[phase]["運用"]["品質注意場数"] == 0
            and row[phase]["運用"]["追加5pt純損益円"] > 0 for phase, limits in config["費用支持"].items())
    def entry_rank(row: dict) -> tuple:
        """入口の安定した方の率で順位を作る。

        引数: row (dict) は一候補の両期間結果。
        返り値: tuple は昇順ソートの優先キー。
        """
        values = [row[p]["入口"] for p in ("学習", "条件選択")]
        return (-row["入口支持"], -min((v["確認率"] or 0) for v in values),
                -min((v["30分間引き_確認率"] or 0) for v in values), -values[1]["約定候補数"], row["候補ID"])
    entry = min(candidates, key=entry_rank)
    qualified = [r for r in candidates if r["費用資格"]]
    profit = min(qualified, key=lambda r: (-min(r[p]["運用"]["追加5pt平均円"] for p in ("学習", "条件選択")),
        -sum(r[p]["運用"]["追加5pt純損益円"] for p in ("学習", "条件選択")), r["候補ID"])) if qualified else None
    return {"入口用ID": entry["候補ID"], "入口用支持": entry["入口支持"], "費用用ID": profit["候補ID"] if profit else None,
            "費用資格数": len(qualified), "70目標達成数": sum(r["70目標"] for r in candidates),
            "固定ID": list(dict.fromkeys([entry["候補ID"], *([profit["候補ID"]] if profit else []), config["対照ID"]]))}


# ----------------------------------------
# 固定候補の小型成果物と、探索・後続の読取境界を管理する。

def publish_details(study: Path, detail_path: Path, fixed_ids: list[str], manifest: dict, subdir: str) -> None:
    """固定候補だけの小容量Viewer資料と取引表を出す。

    引数: study (Path) は試行、detail_path (Path) は作業gzip、fixed_ids (list[str]) は固定候補、manifest (dict) は原板台帳、subdir (str) は追加先。
    返り値: None。原板は複製しない。
    """
    output = study / subdir
    output.mkdir(parents=True, exist_ok=True)
    sources = {e["session"]: e["source_path"] for e in manifest["entries"]}
    resources, trades, orders = [], [], []
    with gzip.open(detail_path, "rt", encoding="utf-8") as stream:
        for line in stream:
            value = json.loads(line)
            cid, session = value["候補ID"], value["場"]
            if cid not in fixed_ids:
                continue
            relative = Path("約定") / cid / f"{session}.trades.jsonl"
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("".join(json.dumps(v, ensure_ascii=False, allow_nan=False)+"\n" for v in value["約定"]), encoding="utf-8")
            resources.append({"id": f"00008_{cid}_{session}", "title": f"{session} {cid} 基準費用・観測代理", "symbol": "NK225",
                "session": session, "product": "NK225micro", "method_id": cid, "entry_method_id": cid, "point_value": 10,
                "pnl_format": "trades", "pnl_basis": "net", "pnl_path": relative.as_posix(), "market_path": sources[session]})
            trades.extend(value["取引"])
            orders.extend({"候補ID": cid, **r} for r in value["注文"])
    W.write_json(output / "一覧.resources.json", {"schema_version": 1, "path_base": "catalog", "resources": resources})
    W.write_csv(output / "固定候補_取引.csv", trades)
    W.write_csv(output / "固定候補_注文.csv", orders)


def validate_locked(study: Path, locked: dict, config: dict, all_rules: list[dict]) -> list[dict]:
    """後続の前に探索結果・選定・全依存の固定を照合する。

    引数: study (Path) は試行、locked/config (dict) は固定と条件、all_rules (list[dict]) は全候補。
    返り値: list[dict] は有効な固定候補。不一致・未知ID・過剰選択は例外。
    """
    if locked["ファイルSHA256"] != fixed_files(study):
        raise ValueError("選定固定後に入力・条件・実装が変更された")
    result_path = study / "探索結果.json"
    if O.sha(result_path) != locked["探索結果SHA256"] or W.read_json(result_path)["選定"] != locked["選定"]:
        raise ValueError("固定した探索結果・選定と不一致")
    selection = locked["選定"]
    expected = list(dict.fromkeys([selection["入口用ID"], *([selection["費用用ID"]] if selection["費用用ID"] else []), config["対照ID"]]))
    known = {r["候補ID"] for r in all_rules}
    if selection["固定ID"] != expected or not 2 <= len(expected) <= 3 or any(cid not in known for cid in expected) or selection["入口用ID"] == config["対照ID"]:
        raise ValueError("固定IDが既知の新候補最大2と対照に一致しない")
    return [r for r in all_rules if r["候補ID"] in expected]


def run(study: Path, phase: str) -> dict:
    """旧64探索又は固定後新1場だけを処理する。

    引数: study (Path) は試行、phase (str) は探索/後続。
    返り値: dict は選定又は固定候補の確認結果。
    """
    if phase not in ("探索", "後続"):
        raise ValueError("未知の実行段階")
    config, manifest = W.read_json(study / "条件.json"), W.read_json(study / "入力台帳.json")
    counts = {period: sum(phase_of(e["session"], config) == period for e in manifest["entries"]) for period in ("学習", "条件選択", "後続検査")}
    if counts != {"学習": 40, "条件選択": 24, "後続検査": 1} or any(e["symbol"] != "NK225" for e in manifest["entries"]):
        raise ValueError("固定した40/24/1場・NK225と異なる入力")
    output = study / ("後続結果.json" if phase == "後続" else "探索結果.json")
    if output.exists():
        raise ValueError("正式結果の上書きはしません")
    chosen = rules(config)
    if phase == "後続":
        locked = W.read_json(study / "選定固定.json")
        chosen = validate_locked(study, locked, config, chosen)
    else:
        freeze_path = study / "探索開始固定.json"
        pins = fixed_files(study)
        if freeze_path.exists() and W.read_json(freeze_path)["ファイルSHA256"] != pins:
            raise ValueError("探索開始固定後に条件・コード・入力が変わった")
        if not freeze_path.exists():
            W.write_json(freeze_path, {"固定日時": datetime.now(W.JST).isoformat(), "ファイルSHA256": pins, "段階": "旧64場の正式探索前、新1未確認"})
    WORK.mkdir(parents=True, exist_ok=True)
    detail_path, cases_path = WORK / f"{phase}_運用詳細.jsonl.gz", WORK / f"{phase}_入口事例.jsonl.gz"
    entry_cases, infos, all_trades, quality = defaultdict(list), defaultdict(list), defaultdict(list), []
    banks = {size: W.Indicators() for size in (3, 5, 15)}
    previous_contract = None
    with gzip.open(detail_path, "wt", encoding="utf-8") as detail_stream, gzip.open(cases_path, "wt", encoding="utf-8") as case_stream:
        for entry in manifest["entries"]:
            session = entry["session"]
            period = phase_of(session, config)
            if phase == "探索" and period == "後続検査":
                continue
            publish = phase == "探索" or period == "後続検査"
            source = Path(manifest["source_root"]) / entry["source_path"]
            stat = source.stat()
            cache = ROOT / "work/複合検証" / entry["cache_path"]
            if (stat.st_size, stat.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]) or O.sha(cache) != entry["sha256_cache"]:
                raise ValueError(f"台帳と不一致: {session}")
            contract = tuple(entry["in_session_contract_codes"])
            if len(contract) != 1:
                raise ValueError("限月が一意でない")
            if previous_contract is not None and contract != previous_contract:
                banks = {size: W.Indicators() for size in banks}
            previous_contract = contract
            begin, finish, cutoff, deadline = W.OLD.shared.legacy.session_times(session)
            start, end = begin.timestamp(), finish.timestamp()
            events, previous_now = [], -math.inf
            for event in W.PREP.read_events(cache):
                if not math.isfinite(event.now) or not start <= event.now <= end or event.now < previous_now:
                    continue
                previous_now = event.now
                events.append(event)
            frames, tails = {}, {}
            for size, bank in banks.items():
                bars = W.bars_from_events(events, start, end, size)
                frames[size] = W.features(bars, bank, start)
                tails[size] = max(0, int((end-start)//(size*60))-1-(bars[-1]["index"] if bars else -1))
                if tails[size]:
                    bank.__init__()
            if not publish:
                continue
            path = W.OLD.気配経路([e for e in events if e.valid])
            by_id = defaultdict(list)
            for size in config["時間足分"]:
                for frame in enrich(frames[size], frames[15]):
                    signal = frame["confirm"]
                    if not (frame["publish"] and frame["has_previous"] and defined(frame["atr"]) and frame["atr"] > 0) or signal >= cutoff.timestamp() or deadline.timestamp()-signal < config["残り時間下限分"]*60:
                        continue
                    for side in (1, -1):
                        row = {**frame, "場": session, "時間足分": size, "side": side, "方向": "買い" if side == 1 else "売り",
                            "イベントID": f"NK225_{session}_{size}分_{frame['index']:04d}_{side}", "要求時計秒": signal,
                            "要求原板行": frame["confirm_line"], "確認遅延秒": signal-frame["end"], "期限時計秒": deadline.timestamp(),
                            "要求時計JST": O.iso(signal), "足終了時計秒": frame["end"], "期間": period}
                        members = [r["候補ID"] for r in chosen if allowed(row, r)]
                        if not members:
                            continue
                        label = ({"ラベル": "未約定", "理由": "足確定確認遅延30秒超", "新規価格": None, "新規時計秒": None,
                            "判定時計秒": None, "判定原板行": None, "新規原板行": None, "判定気配": None,
                            "最大順行pt": None, "最大逆行pt": None, "所要分": None} if row["確認遅延秒"] > config["確認遅延上限秒"] else
                            path.evaluate(signal, cutoff.timestamp(), deadline.timestamp(), side, adverse=config["逆行pt"], favorable=config["順行pt"]))
                        row.update(label)
                        case_stream.write(json.dumps({"候補IDs": members, **row}, ensure_ascii=False, allow_nan=False)+"\n")
                        for cid in members:
                            entry_cases[cid].append(row)
                            by_id[cid].append(row)
            for rule in chosen:
                cid = rule["候補ID"]
                state, info = O.replay_session(events, by_id[cid], session, cid, config["運用"])
                info.update(期間=period, 場時間分=(end-start)/60)
                for trade in state.trades:
                    trade["期間"] = period
                infos[cid].append(info)
                all_trades[cid].extend(state.trades)
                detail_stream.write(json.dumps({"候補ID": cid, "場": session, "品質": info,
                    "約定": state.fills, "取引": state.trades, "注文": state.orders, "入口取扱": state.signals}, ensure_ascii=False, allow_nan=False)+"\n")
            quality.append({"場": session, "正常板数": sum(e.valid for e in events), "確定足数": {str(s): sum(f["publish"] for f in fs) for s, fs in frames.items()}, "尾部欠枠": tails})
            print(f"{phase} {session} {len(chosen)}条件完了", flush=True)
    results = []
    phases = ["後続検査"] if phase == "後続" else ["学習", "条件選択"]
    for rule in chosen:
        cid = rule["候補ID"]
        row = dict(rule)
        for period in phases:
            row[period] = {"入口": entry_metrics([r for r in entry_cases[cid] if r["期間"] == period], period),
                           "運用": operation_metrics([r for r in infos[cid] if r["期間"] == period], [r for r in all_trades[cid] if r["期間"] == period])}
        results.append(row)
    if phase == "探索":
        selection = select(results, config)
        result = {"段階": phase, "結果": results, "選定": selection}
        W.write_json(output, result)
        locked = {"固定日時": datetime.now(W.JST).isoformat(), "選定": selection, "ファイルSHA256": fixed_files(study), "探索結果SHA256": O.sha(output)}
        W.write_json(study / "選定固定.json", locked)
        fixed_ids = selection["固定ID"]
    else:
        result = {"段階": phase, "選定固定SHA256": O.sha(study / "選定固定.json"), "結果": results,
                  "制約": "新1場の診断であり支持と安定性を確立しない。確認後の再選択なし。"}
        W.write_json(output, result)
        fixed_ids = locked["選定"]["固定ID"]
    W.write_json(study / f"入力品質_{phase}.json", quality)
    publish_details(study, detail_path, fixed_ids, manifest, "追加確認" if phase == "後続" else "")
    selected_rows = [{"候補ID": cid, **r} for cid in fixed_ids for r in entry_cases[cid]]
    W.write_csv(study / ("後続事例.csv" if phase == "後続" else "固定候補_探索事例.csv"), selected_rows)
    return {"段階": phase, "候補数": len(chosen), "選定": fixed_ids}


def main() -> None:
    """段階を指定して探索又は固定後確認を実行する。

    引数: なし。--study/--phaseを読む。
    返り値: None。
    """
    parser = argparse.ArgumentParser(description="外部研究の部分取得を踏まえた固定32条件の探索")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--phase", choices=("探索", "後続"), default="探索")
    args = parser.parse_args()
    print(json.dumps(run(args.study.resolve(), args.phase), ensure_ascii=False))


if __name__ == "__main__":
    main()
