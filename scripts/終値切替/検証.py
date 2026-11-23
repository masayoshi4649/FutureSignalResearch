"""00024の終値内復帰と外回復の二運用を既使用65場で比較する。"""

from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime
import gzip
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import platform
import sys
from typing import Any, Iterator, TextIO

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00024_終値の内復帰と外回復による順行反転"
WORK = ROOT / "work/終値切替/00024"
INPUT = ROOT / "study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
PERIODS = ("学習", "条件選択", "後続検査")


def module(path: Path, name: str) -> Any:
    """既存の固定処理を、コマンド行実行せず読み込む。

    引数: path (Path) はコード、name (str) はモジュール識別名。
    返り値: Any は読み込んだモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


BASE = module(ROOT/"scripts/高安再開/検証.py", "終値切替の固定23共通処理")
I = module(Path(__file__).with_name("入口.py"), "終値切替の入口生成")
J = module(Path(__file__).with_name("指標.py"), "終値切替の指標と30窓")
Q = module(ROOT/"scripts/数量反転/数量.py", "終値切替の診断専用固定14数量")
E, W, O = BASE.E, J.W, BASE.O
compressed, content_sha, output_stream = BASE.compressed, BASE.content_sha, BASE.output_stream


def sources(config: dict) -> list[dict]:
    """3分・二選択規則から二入口を列挙する。

    引数: config (dict) は固定条件。
    返り値: list[dict] は二入口IDと戦略・集合役割。
    """
    I.validate_config(config)
    if config["出口"] != [{"出口ID": "X0"}] or (config["逆行pt"], config["順行pt"]) != (125, 250):
        raise ValueError("固定一出口と125/250だけを扱います")
    return [{"入口ID": f"{size}分_{strategy}", "戦略": strategy, "時間足分": size,
             "名称": strategy, "役割": "混合", "複合本命": True}
            for size in config["時間足分"] for strategy in config["戦略"]]


def generate_or_empty(frames: list[dict], higher: list[dict], session: str, size: int,
                      cutoff: float, deadline: float, config: dict, regimes: list[dict],
                      channels: list[dict] | None = None, quantity: dict | None = None) -> tuple[dict, dict]:
    """価格足が空の場も、二入口を0発動として保持する。

    引数: frames/higher (list[dict]) は入口/15足、session (str) は場、size (int) は尺度、
    cutoff/deadline (float) は停止/期限、config (dict) は条件、regimes/channels (list[dict]|None) は局面/30窓、
    quantity (dict|None) は診断だけの数量。
    返り値: tuple[dict,dict] は入口と価格発動品質。空場でも候補を欠落させない。
    """
    if frames:
        return I.generate(frames, higher, session, cutoff, deadline, config, regimes, channels, quantity)
    grouped = {f"{size}分_{strategy}": [] for strategy in I.POLICIES}
    return grouped, {"場": session, "時間足分": size, "全Q発動記録": [], "複合context記録": [],
                     "足数": 0, "共通M準備足数": 0, "設定数": 0,
                     "内復帰価格消費数": 0, "外回復価格消費数": 0, "登録遅延超数": 0, "対象外足数": 0,
                     "先着評価対象外数": 0, "監視動作別": {}, "終了理由別": {}, "新設定除外理由別": {},
                     "登録候補数": 0, "登録見送り理由別": {}, "イベントM除外理由別": {},
                     "戦略採否理由別": {p: {} for p in I.POLICIES}, "イベント段階": [
                         {"役割": role, "原価格イベント数": 0, "時間可数": 0, "確認遅延可数": 0,
                          "先着評価対象数": 0, "M時間通過数": 0, "勢い通過E0数": 0, "上位通過E1数": 0}
                         for role in ("反転", "順行")],
                     "監視trace": [], "エピソード診断": [], "戦略別役割発動数": {key: {} for key in grouped},
                     "戦略別発動数": {key: 0 for key in grouped}}


def shadow_label(record: dict, path: Any, cache: dict, cutoff: float, deadline: float,
                 config: dict) -> dict:
    """要求時間外又は確認遅延超の価格eventを先着へ渡さず区別する。

    引数: record (dict) はshadow、path (Any) は同場気配経路、cache (dict) は同場評価結果、
    cutoff/deadline (float) は停止/期限、config (dict) は固定幅・残時間条件。
    返り値: dict は時間/遅延可の通常ラベル、又は数値全Noneの対象外。対象外でevaluateを呼ばない。
    """
    time_ok = record["要求時計秒"] < cutoff and deadline-record["要求時計秒"] >= config["残り時間下限分"]*60
    delay_ok = record["確認遅延秒"] <= config["確認遅延上限秒"]
    eligible = time_ok and delay_ok
    if bool(record["先着評価対象"]) != eligible:
        raise ValueError("先着評価対象flagと時間/確認遅延条件が不一致")
    if not eligible:
        return {**blank_label(), "ラベル": "対象外", "理由": "要求時間条件外" if not time_ok else "足確定確認遅延30秒超"}
    key = record["要求時計秒"], record["side"]
    if key not in cache:
        cache[key] = path.evaluate(record["要求時計秒"], cutoff, deadline, record["side"],
                                   adverse=config["逆行pt"], favorable=config["順行pt"])
    return cache[key]


def freeze(study: Path) -> dict:
    """コード・計画・条件・参照台帳を実行前に固定する。

    引数: study (Path) は試行。
    返り値: dict は固定SHA。固定後の変更、別入力、既存結果を拒否する。
    """
    if (study / "結果.json").exists():
        raise ValueError("正式結果を上書きしません")
    pointer = {"参照": INPUT.relative_to(study, walk_up=True).as_posix(), "SHA256": O.sha(INPUT)}
    pointer_path = study / "入力台帳.json"
    if pointer_path.exists() and W.read_json(pointer_path) != pointer:
        raise ValueError("既存の入力台帳参照を変更しません")
    if not pointer_path.exists():
        W.write_json(pointer_path, pointer)
    proof = W.read_json(ROOT/"work/終値切替/合成検証.json")
    if proof.get("全件成功") is not True or proof.get("合成編集終了") is not True:
        raise ValueError("最終合成の編集終了通知後だけ固定します")
    inherited = W.read_json(INPUT.parent / "選定固定.json")["ファイルSHA256"]
    paths = [Path(__file__), Path(__file__).with_name("入口.py"), Path(__file__).with_name("運用.py"), Path(__file__).with_name("指標.py"),
             Path(__file__).with_name("合成検証.py"),
             ROOT / "scripts/利益回収/運用.py", ROOT / "scripts/利益回収/合成検証.py",
             ROOT / "scripts/広域研究/合成検証.py", ROOT / "scripts/広域研究/運用の合成検証.py",
             study / "計画.md", study / "条件.json", pointer_path, INPUT]
    paths += [ROOT / name for name in inherited]
    previous_lock = ROOT / "study/00023_上位高安の再テストと順行再開/固定.json"
    paths.append(previous_lock)
    previous_pins = W.read_json(previous_lock)["ファイルSHA256"]
    if any(O.sha(ROOT/name) != digest for name, digest in previous_pins.items()):
        raise ValueError("参照する既存core・入力の固定版が変更されました")
    paths += [ROOT / name for name in previous_pins]
    quantity_lock = ROOT/"study/00014_反転入口と観測差分量/固定.json"
    quantity_path = ROOT/"scripts/数量反転/数量.py"
    if O.sha(quantity_path) != W.read_json(quantity_lock)["ファイルSHA256"][quantity_path.relative_to(ROOT).as_posix()]:
        raise ValueError("診断用数量helperの固定版が変更")
    paths += [quantity_lock, quantity_path]
    pins = {p.relative_to(ROOT).as_posix(): O.sha(p) for p in dict.fromkeys(paths)}
    for path in (Path(__file__), Path(__file__).with_name("入口.py"), Path(__file__).with_name("運用.py"), Path(__file__).with_name("指標.py"),
                 Path(__file__).with_name("合成検証.py"), study/"条件.json"):
        name = path.relative_to(ROOT).as_posix()
        if proof["ファイルSHA256"].get(name) != pins[name]:
            raise ValueError("最終合成後のcode/条件変更")
    fixed_path = study / "固定.json"
    if fixed_path.exists():
        locked = W.read_json(fixed_path)
        if locked["ファイルSHA256"] != pins:
            raise ValueError("実行前固定後にコード・条件・計画・入力が変更されました")
    else:
        locked = {"固定日時": datetime.now(W.JST).isoformat(), "ファイルSHA256": pins,
                  "全65場既使用": True, "Python": platform.python_version(), "NumPy": W.np.__version__}
        W.write_json(fixed_path, locked)
    return locked


# ----------------------------------------
# 固定幅と通常出口を比較し、入口先着と実運用の分母を分ける。

operation_metrics, entry_flags, blank_label = BASE.operation_metrics, BASE.entry_flags, BASE.blank_label


# ----------------------------------------
# 新しい内復帰/外回復を分け、数量は診断だけへ保存する。

def run(study: Path, work: Path, prepare_only: bool = False) -> dict:
    """固定後の入口・出口比較を実行し、小型成果物を保存する。

    引数: study/work (Path) は正式試行・Git外の大きな作業先、prepare_only (bool) はラベル/損益禁止の件数点検。
    返り値: dict は候補数・入口目標・表示固定の要約。
    """
    config = W.read_json(study / "条件.json")
    if config.get("全65場既使用") is not True:
        raise ValueError("全65場を既使用として扱う条件が必要")
    entries = sources(config)
    manifest = W.read_json(INPUT)
    if {p: sum(E.phase_of(e["session"], config) == p for e in manifest["entries"]) for p in PERIODS} != dict(zip(PERIODS, (40, 24, 1))):
        raise ValueError("固定40/24/1場と異なる入力")
    if len({e["session"] for e in manifest["entries"]}) != 65 or any(e["symbol"] != "NK225" for e in manifest["entries"]):
        raise ValueError("一意なNK22565場だけを扱います")
    if not prepare_only:
        freeze(study)
    engine = module(Path(__file__).with_name("運用.py"), "終値切替の固定23運用参照")
    work.mkdir(parents=True, exist_ok=True)
    details, cases = work / "全運用詳細.jsonl.gz", work / "入口事例.jsonl.gz"
    prices_file = work/"全複合shadow.jsonl.gz"
    normal_file = work/"追尾.jsonl.gz"
    regimes_file, context_file, uppers_file = work/"全局面.jsonl.gz", work/"全複合context.jsonl.gz", work/"上位足.jsonl.gz"
    channels_file, watch_file = work/"30分窓.jsonl.gz", work/"監視.jsonl.gz"
    infos, trades, entry_cases = defaultdict(list), defaultdict(list), defaultdict(list)
    quality, entry_quality = [], []
    banks = {n: J.Indicators() for n in (3, 15)}
    channel_bank = J.ChannelBank()
    previous_contract = None
    regime_quality, channel_quality, quantity_quality = [], [], []
    prepare_rows = []
    with output_stream(details, not prepare_only) as detail_stream, output_stream(cases, not prepare_only) as case_stream, output_stream(prices_file, not prepare_only) as prices_stream, output_stream(normal_file, not prepare_only) as normal_stream, output_stream(regimes_file, not prepare_only) as regime_stream, output_stream(context_file, not prepare_only) as context_stream, output_stream(uppers_file, not prepare_only) as uppers_stream, output_stream(channels_file, not prepare_only) as channels_stream, output_stream(watch_file, not prepare_only) as watch_stream:
        for entry in manifest["entries"]:
            session = entry["session"]
            period = E.phase_of(session, config)
            source, cache = Path(manifest["source_root"]) / entry["source_path"], ROOT / "work/複合検証" / entry["cache_path"]
            stat = source.stat()
            if (stat.st_size, stat.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]) or O.sha(cache) != entry["sha256_cache"]:
                raise ValueError("固定入力の指紋が変化")
            contract = tuple(entry["in_session_contract_codes"])
            if len(contract) != 1:
                raise ValueError("限月が一意でありません")
            if previous_contract is not None and contract != previous_contract:
                banks = {n: J.Indicators() for n in banks}
            previous_contract = contract
            begin, finish, cutoff, deadline = W.OLD.shared.legacy.session_times(session)
            start, end = begin.timestamp(), finish.timestamp()
            events, previous_now = [], -math.inf
            for event in W.PREP.read_events(cache):
                if math.isfinite(event.now) and start <= event.now <= end and event.now >= previous_now:
                    events.append(event)
                    previous_now = event.now
            frames, tails, grouped = {}, {}, {}
            for size, bank in banks.items():
                formed = W.bars_from_events(events, start, end, size)
                frames[size] = J.features(formed, bank, start)
                tails[size] = max(0, int((end-start)//(size*60))-1-(formed[-1]["index"] if formed else -1))
                if tails[size]:
                    bank.__init__()
            frames[30] = W.bars_from_events(events, start, end, 30)
            tails[30] = max(0, int((end-start)//1800)-1-(frames[30][-1]["index"] if frames[30] else -1))
            channels, channel_info = channel_bank.build(frames[30], session, contract, tails[30])
            channel_quality.append({"場": session, "期間": period, **channel_info})
            for row in channels:
                channels_stream.write(json.dumps({"期間": period, **row}, ensure_ascii=False, allow_nan=False)+"\n")
            quantities, quantity_info = Q.aggregate(events, frames[3], start, end, 3)
            quantity_quality.append({"場": session, "期間": period, **quantity_info})
            path = None if prepare_only else W.OLD.気配経路([e for e in events if e.valid])
            label_cache = {}
            regimes, regime_info = I.classify(frames[15], session, config)
            regime_quality.append({"場": session, "期間": period, **regime_info})
            for record in regimes:
                regime_stream.write(json.dumps({"期間": period, **record}, ensure_ascii=False, allow_nan=False)+"\n")
            for upper_size in (15, 30):
                for frame in frames[upper_size]:
                    uppers_stream.write(json.dumps({"場": session, "期間": period, **frame}, ensure_ascii=False, allow_nan=False)+"\n")
            for size in config["時間足分"]:
                # ----------------------------------------
                # 全足の新指標と準備を保存し、独立発動の採否を別shadowへ残す。
                signals_by_source, input_quality = generate_or_empty(frames[size], frames[15], session, size,
                    cutoff.timestamp(), deadline.timestamp(), config, regimes, channels, quantities)
                for record in input_quality.pop("全Q発動記録"):
                    if prepare_only:
                        continue
                    label = shadow_label(record, path, label_cache, cutoff.timestamp(), deadline.timestamp(), config)
                    prices_stream.write(json.dumps({"期間": period, **record, **label}, ensure_ascii=False, allow_nan=False)+"\n")
                for record in input_quality.pop("複合context記録"):
                    context_stream.write(json.dumps({"期間": period, **record}, ensure_ascii=False, allow_nan=False)+"\n")
                for record in input_quality.pop("監視trace"):
                    watch_stream.write(json.dumps({"種別": "足監視", "期間": period, **record}, ensure_ascii=False, allow_nan=False)+"\n")
                for record in input_quality.pop("エピソード診断"):
                    watch_stream.write(json.dumps({"種別": "監視終了診断", "場": session, "期間": period, **record}, ensure_ascii=False, allow_nan=False)+"\n")
                input_quality["期間"] = period
                entry_quality.append(input_quality)
                for source_id, signals in signals_by_source.items():
                    grouped[source_id] = signals
                    if prepare_only:
                        prepare_rows.append({"場": session, "期間": period, "入口ID": source_id,
                                             "発動数": len(signals), "買い発動数": sum(s["side"] == 1 for s in signals),
                                             "売り発動数": sum(s["side"] == -1 for s in signals)})
                        continue
                    for signal in signals:
                        signal.update(期間=period, 要求時計JST=O.iso(signal["要求時計秒"]))
                        if not signal["先着評価対象"]:
                            raise ValueError("採用caseに先着対象外eventが混入")
                        label = shadow_label(signal, path, label_cache, cutoff.timestamp(), deadline.timestamp(), config)
                        case = {**signal, **label}
                        entry_cases[source_id].append(case)
                        case_stream.write(json.dumps(case, ensure_ascii=False, allow_nan=False)+"\n")
            for source in entries:
                if prepare_only:
                    continue
                source_id = source["入口ID"]
                for policy in config["出口"]:
                    cid = source_id + "_" + policy["出口ID"]
                    # 運用へはlabelなしsignalだけを渡す。入口条件と建玉中の抑止を分ける。
                    operation_frames = frames[source["時間足分"]]
                    state, info = engine.replay(events, grouped[source_id], operation_frames, session, cid, config["運用"], policy, source["役割"])
                    info.update(期間=period, 場時間分=(end-start)/60)
                    for trade in state.trades:
                        trade["期間"] = period
                    infos[cid].append(info)
                    trades[cid].extend(state.trades)
                    for record in getattr(state, "normal_log", []):
                        normal_stream.write(json.dumps({"期間": period, **record}, ensure_ascii=False, allow_nan=False)+"\n")
                    detail_stream.write(json.dumps({"候補ID": cid, "場": session, "品質": info, "約定": state.fills,
                                                   "取引": state.trades, "注文": state.orders, "入口取扱": state.signals}, ensure_ascii=False, allow_nan=False)+"\n")
            quality.append({"場": session, "期間": period, "正常板数": sum(e.valid for e in events),
                            "確定足数": {str(n): sum(f["publish"] for f in values) for n, values in frames.items()}, "尾部欠枠": tails})
            print(f"00024 {session} "+("準備/発動件数のみ完了" if prepare_only else "2入口・2運用完了"), flush=True)
    if prepare_only:
        summary = {"ラベル計算": False, "損益計算": False, "全65場既使用": True,
                   "条件SHA256": O.sha(study/"条件.json"), "入力台帳SHA256": O.sha(INPUT),
                   "コードSHA256": {p.relative_to(ROOT).as_posix(): O.sha(p) for p in (Path(__file__), Path(__file__).with_name("入口.py"), Path(__file__).with_name("指標.py"), Path(__file__).with_name("運用.py"))},
                   "準備": entry_quality, "30窓品質": channel_quality, "数量診断品質": quantity_quality,
                   "場別発動": prepare_rows, "期間別発動": []}
        for source in entries:
            for period in PERIODS:
                local = [r for r in prepare_rows if r["入口ID"] == source["入口ID"] and r["期間"] == period]
                active = [r for r in local if r["発動数"]]
                summary["期間別発動"].append({"入口ID": source["入口ID"], "期間": period,
                    "発動数": sum(r["発動数"] for r in local), "発動場数": len(active),
                    "発動開始日数": len({r["場"][:10] for r in active}),
                    "買い発動数": sum(r["買い発動数"] for r in local), "売り発動数": sum(r["売り発動数"] for r in local)})
        W.write_json(work/"準備点検.json", summary)
        return {"準備点検": True, "ラベル計算": False, "損益計算": False, "全65場": True}
    # ----------------------------------------
    # 三期間の入口は独立追跡、運用は一建玉の参加経路を持つ。
    results, entry_results, saved_ids = [], [], []
    for source in entries:
        source_id = source["入口ID"]
        entry_result = {**source, **{p: E.entry_metrics([r for r in entry_cases[source_id] if r["期間"] == p], p) for p in PERIODS}}
        support, goal = entry_flags(entry_result, config)
        entry_result.update(入口支持=support, **{"70目標": goal})
        entry_results.append(entry_result)
        variants = []
        for policy in config["出口"]:
            cid = source_id + "_" + policy["出口ID"]
            row = {"候補ID": cid, "入口": source, "出口": policy, "入口支持": support, "70目標": goal}
            for period in PERIODS:
                period_infos = [i for i in infos[cid] if i["期間"] == period]
                period_trades = [t for t in trades[cid] if t["期間"] == period]
                operation = operation_metrics(period_infos, period_trades, source["役割"], policy)
                row[period] = {"入口": entry_result[period], "運用": operation}
            row["費用資格"] = all(W.supported(row[p]["運用"], limits) and row[p]["運用"]["品質注意場数"] == 0
                                  and row[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
            variants.append(row)
            results.append(row)
        if source["時間足分"] == 3:
            saved_ids.extend(row["候補ID"] for row in variants)
    saved_ids = list(dict.fromkeys(saved_ids))
    report = {"全65場既使用": True, "入口評価": entry_results, "結果": results, "表示固定ID": saved_ids,
              "入口70目標達成数": sum(r["70目標"] for r in entry_results), "費用資格数": sum(r["費用資格"] for r in results),
              "入口125250評価の変更": False, "位置付け": "既使用65場で固定高安への終値内復帰と外回復を比較する追加開発。数量は診断のみ。新しい未見確認ではない"}
    W.write_json(study / "入力品質.json", quality)
    W.write_json(study / "入口品質.json", entry_quality)
    W.write_json(study / "局面品質.json", regime_quality)
    W.write_json(study / "30窓品質.json", channel_quality)
    W.write_json(study / "数量診断品質.json", quantity_quality)
    W.write_csv(study / "全候補_場別.csv", [i for cid in infos for i in infos[cid]])
    E.publish_details(study, details, saved_ids, manifest, "")
    catalog_path = study / "一覧.resources.json"
    catalog = W.read_json(catalog_path)
    for resource in catalog["resources"]:
        resource["id"] = resource["id"].replace("00008_", "00024_", 1)
    W.write_json(catalog_path, catalog)
    W.write_json(study / "作業成果物.json", {"原板複製": False, "展開内容SHA256が正本": True,
        "ファイル": [{"パス": path.relative_to(ROOT, walk_up=True).as_posix(), "展開内容SHA256": content_sha(path),
                     "圧縮SHA256参考": O.sha(path), "圧縮バイト": path.stat().st_size} for path in (details, cases, prices_file, normal_file, regimes_file, context_file, uppers_file, channels_file, watch_file)]})
    W.write_json(study / "結果.json", report)
    return {"入口数": len(entry_results), "運用候補数": len(results), "入口70目標達成数": report["入口70目標達成数"],
            "費用資格数": report["費用資格数"], "表示固定ID": saved_ids}


def main() -> None:
    """試行・作業先を指定し、固定二案を実行する。

    引数: なし。--study/--work/--prepareを読む。
    返り値: None。既存結果・固定不一致は拒否する。
    """
    parser = argparse.ArgumentParser(description="終値の内復帰と外回復による順行反転")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--prepare", action="store_true", help="固定前の準備/発動件数だけ。ラベル/運用再生は禁止")
    args = parser.parse_args()
    print(json.dumps(run(args.study.resolve(), args.work.resolve(), args.prepare), ensure_ascii=False))


if __name__ == "__main__":
    main()
