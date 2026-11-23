"""00016の準備・最新一件監視・逆方向入口を、原価格と区間探索から独立再構成する。"""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00016_反転不成立からの継続"
WORK = ROOT / "work/反転失効/00016"
MANIFEST = ROOT / "study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
HELPER = ROOT / "scripts/RSI構造/状態独立確認.py"
OLD_CASES = ROOT / "work/RSI構造/00015/入口事例.jsonl.gz"
OLD_STUDY = ROOT / "study/00015_RSIの山谷と価格構造"


def independent_helper() -> Any:
    """旧15の原価格からの独立再構成補助だけを読む。

    引数: なし。
    返り値: Any は独立足・RSI・pivot/隣接組列挙。旧15の元入口や今回の入口は読み込まない。
    """
    spec = importlib.util.spec_from_file_location("反転失効の独立RSI構造", HELPER)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


S = independent_helper()


def preparation(frames: list[dict], higher: list[dict], session: str, period: str) -> list[dict]:
    """独立極値の隣接比較から、旧15反転乖離なしだけを再構成する。

    引数: frames/higher (list[dict]) は独立の下位/15分足、session/period (str) は場と期間。
    返り値: list[dict] は遅延30秒超も含む全準備。未来ラベルは読まず、型・距離等を変更しない。
    """
    output = []
    for pair in S.listed_pairs(frames, higher, session):
        _, events = S.canonical(pair, session, period)
        output.extend(r for r in events.values() if r["入口系統"] == "反転乖離" and r["補助"] == "なし")
    return sorted(output, key=lambda r: (r["index"], r["要求時計秒"], r["要求原板行"]))


def current_context(frame: dict, higher: list[dict], session: str) -> dict:
    """実発動足の上位・共通指標・時間と遅延を独立に評価する。

    引数: frame (dict) は判断足、higher (list[dict]) は独立15分足、session (str) は場。
    返り値: dict は実発動時点の属性と追加上位を除く抑止理由。
    """
    _, _, cutoff, deadline = S.S.G.times(session)
    upper = S.upper_context(frame, higher)
    reasons = []
    if not S.S.finite(frame["rsi"], frame["atr"]) or frame["atr"] <= 0:
        reasons.append("判断RSI_ATR未準備")
    if not upper["上位準備済"]:
        reasons.append("上位未準備")
    if frame["confirm"] >= cutoff or deadline - frame["confirm"] < 3600:
        reasons.append("時間条件不成立")
    if frame["confirm"] - frame["end"] > 30:
        reasons.append("確認遅延30秒超")
    return {**frame, **upper, "実発動共通除外": reasons}


# ----------------------------------------
# 最新一件のオンライン状態を写さず、各登録から次登録を含む監視区間を探索する。

def watched_intervals(frames: list[dict], prepared: list[dict]) -> list[dict]:
    """各有効準備の次足から、失効・7満了・次準備での置換・欠枠まで走査する。

    引数: frames (list[dict]) は一場一尺度の全足、prepared (list[dict]) は独立準備。
    返り値: list[dict] は登録ごとの全判定足と終端。次登録足でも旧監視の失効を先に判定する。
    """
    valid = [p for p in prepared if p["確認遅延秒"] <= 30]
    if len({r["index"] for r in prepared}) != len(prepared):
        raise ValueError("同じ尺度の同足に複数の準備")
    position = {row["index"]: i for i, row in enumerate(frames)}
    output = []
    for order, origin in enumerate(valid):
        following = valid[order + 1] if order + 1 < len(valid) else None
        start_at = position[origin["index"]]
        reference = origin["現極値"]["極値価格"]
        inspected, termination, terminal_row = [], "場末未消費", None
        previous_index = origin["index"]
        for row in frames[start_at + 1:]:
            if not row["publish"] or row["missing"] or row["index"] != previous_index + 1:
                termination, terminal_row = "欠枠リセット", row
                break
            age = row["index"] - origin["index"]
            if age > 6:
                termination, terminal_row = "満了", row
                break
            failed = origin["side"] * (row["close"] - reference) < 0
            inspected.append({"足": row, "経過": age, "失効": bool(failed)})
            if failed:
                termination, terminal_row = "失効消費", row
                break
            if following is not None and row["index"] == following["index"]:
                termination, terminal_row = "置換", row
                break
            previous_index = row["index"]
        output.append({"準備": origin, "失効線": reference, "判断列": inspected,
                       "終端種別": termination, "終端足": terminal_row})
    return output


def reference(source: dict) -> dict:
    """独立準備を、現在足と混同しない不変の参照へ写像する。

    引数: source (dict) は独立した旧15の反転乖離なし。
    返り値: dict は元側/実入口側・極値・準備時点/指標/上位キー。
    """
    return {"元準備イベントID": source["イベントID"], "準備足番号": source["index"],
        "準備時計秒": source["要求時計秒"], "準備原板行": source["要求原板行"],
        "元準備side": source["side"], "実入口側": -source["side"],
        "第2極値価格": source["現極値"]["極値価格"], "第2極値中心番号": source["現極値"]["中心番号"],
        "準備確認遅延秒": source["確認遅延秒"], "準備ATR14": source["atr"], "準備RSI14": source["rsi"],
        "準備上位方向": source["上位方向"], "準備上位確認秒": source["上位確認秒"],
        "準備上位確認行": source["上位確認行"], "準備上位足終了秒": source["上位足終了秒"],
        "前極値": source["前極値"], "現極値": source["現極値"]}


def observation(action: str, row: dict, prepared_reference: dict | None, session: str,
                period: str, attributes: dict | None = None) -> dict:
    """独立区間から導いた動作を監視保存schemaへ変換する。

    引数: action/session/period (str) は動作/場/期間、row (dict) は現足、
    prepared_reference (dict|None) は準備、attributes (dict|None) は動作属性。
    返り値: dict は順序付け前の監視行。オンライン状態は更新しない。
    """
    return {"場": session, "期間": period, "時間足分": row["minutes"], "動作": action,
        "判断足番号": row["index"], "判断足終了秒": row["end"], "判断時計秒": row["confirm"],
        "判断原板行": row["confirm_line"], "判断終値": row["close"], "準備参照": prepared_reference,
        **(attributes or {})}


def entry_decision(family: str, frame: dict, higher: list[dict], origin: dict, age: int,
                   session: str, period: str) -> tuple[dict, dict[str, dict], Counter]:
    """実発動足と逆側の入方向へ共通gate・15分方向を適用する。

    引数: family/session/period (str) は方式/場/期間、frame (dict) は現足、
    higher (list[dict]) は独立15分足、origin (dict) は元準備、age (int) は待機本数。
    返り値: tuple[dict,dict[str,dict],Counter] は入口判定記録・発動・補助別重複除外数。
    """
    row, prepared_reference = current_context(frame, higher, session), reference(origin)
    _, _, _, deadline = S.S.G.times(session)
    side, reasons = -origin["side"], row["実発動共通除外"]
    by_extra, events, counts = {}, {}, Counter()
    for extra in ("なし", "15分方向一致"):
        rejected = reasons + (["実入口側と15分方向不一致"] if extra != "なし" and row["上位方向"] != side else [])
        by_extra[extra] = rejected
        counts.update(rejected)
        if rejected:
            continue
        source_id = f'{frame["minutes"]}分_{family}_{extra}'
        identity = f'NK225_{session}_{source_id}_{frame["index"]:04d}_{side}'
        events[identity] = {**row, "準備属性": prepared_reference,
            **{k: prepared_reference[k] for k in ("元準備イベントID", "第2極値価格", "準備足番号",
                "準備時計秒", "準備原板行", "元準備side", "実入口側")},
            "場": session, "期間": period, "時間足分": frame["minutes"], "入口ID": source_id,
            "入口系統": family, "補助": extra, "役割": "順行", "side": side,
            "方向": "買い" if side == 1 else "売り", "待機本数": age, "イベントID": identity,
            "要求時計秒": row["confirm"], "要求原板行": row["confirm_line"], "確認遅延秒": row["confirm"] - row["end"],
            "期限時計秒": deadline, "足終了時計秒": row["end"], "残り分_判断時": (deadline - row["confirm"]) / 60,
            "入口中心まで方向距離pt": side * (row["bb_mean"] - row["close"]) if S.S.finite(row["bb_mean"]) else None,
            "250ptのATR倍": 250 / row["atr"]}
    attributes = {"方式": family, "待機本数": age, "共通除外理由": reasons, "追加確認別除外理由": by_extra,
        "方向一致": row["上位方向"] == side, "発動入口ID": [r["入口ID"] for r in events.values()],
        "判断ATR14": row["atr"], "判断RSI14": row["rsi"], "上位準備済": row["上位準備済"],
        "上位方向": row["上位方向"], "上位確認秒": row["上位確認秒"], "上位確認行": row["上位確認行"],
        "上位足終了秒": row["上位足終了秒"], "確認遅延秒": row["confirm"] - row["end"]}
    return observation("入口判定", row, prepared_reference, session, period, attributes), events, counts


# ----------------------------------------
# 監視区間を動作の時点へ射影し、旧判定→新登録の順序まで独立に組み直す。

def reconstruct(frames: list[dict], higher: list[dict], prepared: list[dict], session: str,
                period: str) -> tuple[list[dict], dict[str, dict], dict]:
    """区間探索の判定列・終端から、全監視記録と12入口を再構成する。

    引数: frames/higher (list[dict]) は独立足、prepared (list[dict]) は全準備、session/period (str) は場/期間。
    返り値: tuple[list[dict],dict[str,dict],dict] は原順監視・発動・品質。実建玉の有無は参照しない。
    """
    intervals, staged, events, rejected = watched_intervals(frames, prepared), [], {}, Counter()
    reset_origins, replaced_origins = {}, {}
    for interval in intervals:
        origin, prepared_reference = interval["準備"], reference(interval["準備"])
        for checked in interval["判断列"]:
            row = current_context(checked["足"], higher, session)
            attributes = {"待機本数": checked["経過"], "厳密失効": checked["失効"],
                "判断ATR14": row["atr"], "判断RSI14": row["rsi"], "上位準備済": row["上位準備済"],
                "上位方向": row["上位方向"], "上位確認秒": row["上位確認秒"], "上位確認行": row["上位確認行"],
                "上位足終了秒": row["上位足終了秒"]}
            staged.append((row["index"], 0, observation("監視判定", row, prepared_reference, session, period, attributes)))
            if checked["失効"]:
                decision, fired, counts = entry_decision("価格失効待ち", row, higher, origin, checked["経過"], session, period)
                events.update(fired)
                rejected.update(counts)
                staged.append((row["index"], 1, decision))
                staged.append((row["index"], 2, observation("失効消費", row, prepared_reference, session, period,
                    {"待機本数": checked["経過"], "発動入口ID": [r["入口ID"] for r in fired.values()]})))
        terminal = interval["終端足"]
        if interval["終端種別"] == "欠枠リセット":
            if terminal["index"] in reset_origins:
                raise ValueError("同じreset足へ複数の監視が到達")
            reset_origins[terminal["index"]] = prepared_reference
        elif interval["終端種別"] == "置換":
            replaced_origins[terminal["index"]] = prepared_reference
        elif interval["終端種別"] == "満了":
            staged.append((terminal["index"], 0, observation("監視満了", terminal, prepared_reference, session, period,
                {"待機本数": terminal["index"] - origin["index"]})))
        elif interval["終端種別"] == "場末未消費":
            last = frames[-1]
            staged.append((last["index"], 9, observation("場末未消費終了", last, prepared_reference, session, period,
                {"待機本数": last["index"] - origin["index"]})))
    previous_index = None
    for frame in frames:
        gap = previous_index is not None and frame["index"] != previous_index + 1
        if not frame["publish"] or frame["missing"] or gap:
            staged.append((frame["index"], -1, observation("状態リセット", frame, reset_origins.get(frame["index"]),
                session, period, {"非公開": not frame["publish"], "欠枠": bool(frame["missing"]), "番号飛越": bool(gap)})))
        previous_index = frame["index"]
    for origin in prepared:
        frame, prepared_reference = next(f for f in frames if f["index"] == origin["index"]), reference(origin)
        if origin["確認遅延秒"] > 30:
            staged.append((frame["index"], 3, observation("準備遅延除外", frame, prepared_reference, session, period)))
            continue
        decision, fired, counts = entry_decision("単純逆向き", frame, higher, origin, 0, session, period)
        events.update(fired)
        rejected.update(counts)
        staged.append((frame["index"], 3, decision))
        previous = replaced_origins.get(frame["index"])
        staged.append((frame["index"], 4, observation("監視置換" if previous is not None else "監視登録",
            frame, prepared_reference, session, period, {"旧準備参照": previous})))
    watch = [{**row, "状態順序": order + 1} for order, (_, _, row) in enumerate(sorted(staged, key=lambda r: r[:2]))]
    counts = Counter(row["動作"] for row in watch)
    counts.update({"公開足": sum(f["publish"] for f in frames), "元準備信号数": len(prepared),
                   "準備遅延共通除外数": sum(p["確認遅延秒"] > 30 for p in prepared),
                   "利用可能準備信号数": sum(p["確認遅延秒"] <= 30 for p in prepared)})
    size = frames[0]["minutes"] if frames else None
    return watch, events, {**dict(counts), "発動除外理由_補助別重複あり": dict(rejected),
        "系統別発動数": {f"{size}分_{family}_{extra}": sum(r["入口ID"] == f"{size}分_{family}_{extra}" for r in events.values())
            for family in ("単純逆向き", "価格失効待ち") for extra in ("なし", "15分方向一致")}}


def old_price_quality(frames: list[dict], higher: list[dict], session: str, period: str) -> dict:
    """独立全pivotから旧15品質の数値カウンタを求める。

    引数: frames/higher (list[dict]) は独立下位/15分足、session/period (str) は場/期間。
    返り値: dict は元15品質と比較できる数値。旧15元コードは実行しない。
    """
    records, events = [], {}
    for pair in S.listed_pairs(frames, higher, session):
        record, fired = S.canonical(pair, session, period)
        records.append(record)
        events.update(fired)
    return {k: v for k, v in S.quality(frames, records, events).items() if isinstance(v, (int, float))}


def read_rows(path: Path) -> tuple[list[dict], str]:
    """作業JSONLの全行と展開内容指紋を読む。

    引数: path (Path) はgzip。
    返り値: tuple[list[dict],str] は行とSHA256。
    """
    return S.compressed_rows(path)


def run(study: Path, work: Path) -> dict:
    """正式再生後だけ、旧15準備同値・全監視と全12発動を原cacheから独立照合する。

    引数: study/work (Path) は00016の正式/作業先。
    返り値: dict は明示合否・件数・指紋と範囲。先着/会計は親の別監査へ分ける。
    """
    for name in ("結果.json", "固定.json", "入口品質.json"):
        if not (study / name).exists():
            raise ValueError("正式再生完了資料がないため実行しません")
    audit = S.S.Audit()
    manifest, config = S.S.read(MANIFEST), S.S.read(study / "条件.json")
    saved_prepared, prepared_sha = read_rows(work / "全準備.jsonl.gz")
    saved_watch, watch_sha = read_rows(work / "全監視.jsonl.gz")
    saved_cases, cases_sha = read_rows(work / "入口事例.jsonl.gz")
    original_cases, original_sha = read_rows(OLD_CASES)
    old_artifacts = S.S.read(OLD_STUDY / "作業成果物.json")["ファイル"]
    audit.check("旧15事例展開内容正本", original_sha,
        next(r["展開内容SHA256"] for r in old_artifacts if Path(r["パス"]).name == OLD_CASES.name))
    original = {r["イベントID"]: r for r in original_cases if r["入口系統"] == "反転乖離" and r["補助"] == "なし"}
    actual_prepared = {r["元準備イベントID"]: r for r in saved_prepared}
    actual_watch = {(r["場"], r["時間足分"], r["状態順序"]): r for r in saved_watch}
    actual_cases = {r["イベントID"]: r for r in saved_cases}
    for name, mapping, rows in (("全準備", actual_prepared, saved_prepared), ("全監視", actual_watch, saved_watch), ("全入口", actual_cases, saved_cases)):
        audit.check(name + "の一意性", len(mapping), len(rows))
    saved_quality = {(r["場"], r["時間足分"]): r for r in S.S.read(study / "入口品質.json")}
    expected_prepared, expected_watch, expected_cases = {}, {}, {}
    banks, contract, frame_count, period_count = {n: S.Indicators() for n in (1, 3, 5, 15)}, None, Counter(), Counter()
    for entry in manifest["entries"]:
        session, codes = entry["session"], tuple(entry["in_session_contract_codes"])
        if len(codes) != 1:
            raise ValueError("限月が一意でない")
        if contract is not None and codes != contract:
            banks = {n: S.Indicators() for n in banks}
        contract = codes
        period = "後続検査" if session[:10] >= config["分割"]["後続開始日"] else (
            "条件選択" if session[:10] >= config["分割"]["選択開始日"] else "学習")
        period_count[period] += 1
        data = S.S.observed(entry)
        formed = {n: S.S.bars(data, session, n, bank) for n, bank in banks.items()}
        for minutes in (1, 3, 5):
            prepared = preparation(formed[minutes], formed[15], session, period)
            for origin in prepared:
                expected_prepared[origin["イベントID"]] = {"場": session, "期間": period, "時間足分": minutes,
                    **reference(origin), "共通遅延除外": origin["確認遅延秒"] > 30, "元信号": origin}
            watch, events, quality = reconstruct(formed[minutes], formed[15], prepared, session, period)
            expected_watch.update({(session, minutes, r["状態順序"]): r for r in watch})
            expected_cases.update(events)
            actual = saved_quality.get((session, minutes), {})
            for field, expected in quality.items():
                audit.check(f"{session}:{minutes}分:状態品質:{field}", actual.get(field, 0), expected)
            for field, expected in old_price_quality(formed[minutes], formed[15], session, period).items():
                audit.check(f"{session}:{minutes}分:元15品質:{field}", actual.get("元15品質", {}).get(field, 0), expected)
            frame_count[str(minutes)] += len(formed[minutes])
        frame_count["15"] += len(formed[15])
        print(json.dumps({"場": session, "独立確認": "原価格・旧15準備・最新監視区間", "現時点不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("固定入力65場", len(manifest["entries"]), 65)
    audit.check("固定分割40/24/1", dict(period_count), {"学習": 40, "条件選択": 24, "後続検査": 1})
    S.compare_keys(audit, "旧15固定準備集合", set(actual_prepared), set(original))
    S.compare_keys(audit, "原価格からの準備集合", set(actual_prepared), set(expected_prepared))
    original_fields = ("index", "start", "end", "minutes", "open", "high", "low", "close", "missing", "publish",
        "confirm", "confirm_line", "ema20", "ema20_previous", "atr", "rsi", "adx", "bb_mean", "bb_sd", "plus_di", "minus_di",
        "上位準備済", "上位方向", "上位確認秒", "上位確認行", "上位足終了秒", "上位足番号",
        "現極値", "前極値", "極値間隔本数", "極値間高値", "極値間安値", "ネック価格", "ネック条件成立",
        "場", "時間足分", "入口ID", "入口系統", "補助", "追加確認", "役割", "side", "方向",
        "要求時計秒", "要求原板行", "確認遅延秒", "期限時計秒", "足終了時計秒", "残り分_判断時", "入口中心まで方向距離pt", "250ptのATR倍")
    for identity in actual_prepared.keys() & expected_prepared.keys():
        actual, expected = actual_prepared[identity], expected_prepared[identity]
        audit.check(identity + ":準備参照全属性", {k: v for k, v in actual.items() if k != "元信号"},
                    {k: v for k, v in expected.items() if k != "元信号"})
        for field in original_fields:
            audit.check(identity + ":原価格からの準備:" + field, actual["元信号"][field], expected["元信号"][field])
        if identity in original:
            old, current = original[identity], actual["元信号"]
            added_after_generation = {"期間", "要求時計JST", "ラベル", "理由", "新規価格", "新規時計秒", "新規原板行",
                "判定時計秒", "判定原板行", "判定気配", "最大順行pt", "最大逆行pt", "所要分"}
            fixed_source = {key: value for key, value in old.items() if key not in added_after_generation}
            audit.check(identity + ":旧15元信号全文", current, fixed_source)
    S.compare_keys(audit, "全監視原順集合", set(actual_watch), set(expected_watch))
    for key in actual_watch.keys() & expected_watch.keys():
        audit.check(f"監視{key}", actual_watch[key], expected_watch[key])
    S.compare_keys(audit, "全12発動集合", set(actual_cases), set(expected_cases))
    event_fields = tuple(k for k in original_fields if k not in ("現極値", "前極値", "極値間隔本数", "極値間高値",
        "極値間安値", "ネック価格", "ネック条件成立", "追加確認")) + (
        "準備属性", "元準備イベントID", "第2極値価格", "準備足番号", "準備時計秒", "準備原板行", "元準備side",
        "実入口側", "待機本数", "期間")
    for identity in actual_cases.keys() & expected_cases.keys():
        for field in event_fields:
            audit.check(identity + ":" + field, actual_cases[identity][field], expected_cases[identity][field])
    result = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches, "不一致": audit.errors,
        "入力場数": len(manifest["entries"]), "期間場数": dict(period_count), "独立足数": dict(frame_count),
        "保存準備数": len(saved_prepared), "独立準備数": len(expected_prepared), "旧15固定準備数": len(original),
        "準備30秒超除外数": sum(r["共通遅延除外"] for r in expected_prepared.values()),
        "保存監視行数": len(saved_watch), "独立監視行数": len(expected_watch),
        "保存入口数": len(saved_cases), "独立入口数": len(expected_cases),
        "動作別件数": dict(Counter(r["動作"] for r in expected_watch.values())),
        "入口別件数": dict(Counter(r["入口ID"] for r in expected_cases.values())),
        "コードSHA256": S.S.sha(Path(__file__)), "独立RSI構造補助SHA256": S.S.sha(HELPER),
        "独立価格補助SHA256": S.S.sha(S.HELPER), "独立Wilder補助SHA256": S.S.sha(S.S.HELPER),
        "入力台帳SHA256": S.S.sha(MANIFEST), "旧15結果SHA256": S.S.sha(OLD_STUDY / "結果.json"),
        "旧15事例展開SHA256": original_sha, "全準備展開SHA256": prepared_sha, "全監視展開SHA256": watch_sha,
        "入口事例展開SHA256": cases_sha,
        "検証範囲": "固定cacheから1/3/5/15足・RSI14/ATR14/上位EMAを独立計算し、旧15反転乖離なしの全準備を再構成。旧15固定事例から生成後の期間/JST補助表記/先着ラベル11列を除いた元信号全文の同値を確認。遅延30秒超を共通除外後、各登録から次登録足を含む区間を探索し、最新global一件・1〜6strict失効/7満了・旧判定→現登録・置換・欠枠/非公開reset・抑止でも消費を全監視行/順序と12実発動集合で照合。実sideへ方向補助を適用し、準備と実発動の属性/時計/原行を分離。",
        "限界": "新16や元15の入口/driver/元指標classをimportして再生しない。旧15の独立再構成補助だけを読み取る。原板本文の再取得や実受信時計を証明しない。旧15固定照合と原価格独立照合を分け、先着/実建玉抑止/運用会計は別監査とする。"}
    (work / "状態独立確認.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("全件一致", "照合項目数", "不一致数", "保存準備数", "保存監視行数", "保存入口数")}, ensure_ascii=False))
    if audit.errors:
        print(json.dumps(audit.errors[:5], ensure_ascii=False))
    return result


def main() -> None:
    """正式再生完了通知後の明示指定だけで実データ監査を開始する。

    引数: なし。--study/--work/--実行許可を読む。
    返り値: None。不許可時は実データを開かない。
    """
    parser = argparse.ArgumentParser(description="00016準備・監視・逆方向発動の独立確認")
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

