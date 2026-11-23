"""既使用66場で、極値更新帯内の反転にOBV非追随を足した二案を比較する。"""

from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import ExitStack
from datetime import datetime
import importlib.util
import json
import math
from pathlib import Path
import platform
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00029_BB内復帰とOBV非追随"
WORK = ROOT/"work/OBV反転/00029"
OLD_STUDY = ROOT/"study/00028_基準線復帰と上位一目の方向"
PERIODS = ("学習", "条件選択", "後続検査")
FILES = ("全指標.jsonl.gz", "全複合context.jsonl.gz", "全複合shadow.jsonl.gz",
         "入口事例.jsonl.gz", "全運用詳細.jsonl.gz", "追尾.jsonl.gz")


def module(path: Path, name: str) -> Any:
    """コマンド行実行せず、固定済みの処理を読み込む。

    引数: path(Path)はコード、name(str)は識別名。
    返り値: Anyは読取モジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


D = module(ROOT/"scripts/一目基準線/検証.py", "OBV反転の固定28共通処理")
I = module(Path(__file__).with_name("入口.py"), "OBV反転の入口生成")
J, W, E, O = I.J, D.W, D.E, D.O
Q = module(ROOT/"scripts/数量反転/数量.py", "OBV反転の固定14数量")
ENGINE = module(ROOT/"scripts/反転確認時計/運用.py", "OBV反転の固定26運用")
compressed, content_sha = D.compressed, D.content_sha
shadow_label, entry_flags, operation_metrics = D.shadow_label, D.entry_flags, D.operation_metrics


def code_pins() -> dict:
    """当試行の三主コードを指紋化する。

    引数: なし。
    返り値: dictはROOT相対パスとSHA256。
    """
    return {p.relative_to(ROOT).as_posix(): O.sha(p) for p in
        (Path(__file__), Path(__file__).with_name("入口.py"), Path(__file__).with_name("指標.py"))}


def sources(config: dict) -> list[dict]:
    """事前固定した3分二案を同じ順で列挙する。

    引数: config(dict)は条件。
    返り値: list[dict]は入口の表示・運用参照。候補選択を行わない。
    """
    I.validate_config(config)
    return [{"入口ID": "3分_"+p, "戦略": p, "時間足分": 3, "名称": p,
        "役割": "反転", "複合本命": True} for p in I.POLICIES]


def manifest_for(study: Path, config: dict) -> dict:
    """固定済み65場と27確認1場から成る66入力だけを許可する。

    引数: study(Path)は29、config(dict)は期間条件。
    返り値: dictは既存キャッシュを指す実台帳。ラベル・結果を読まない。
    """
    pointer = W.read_json(study/"入力台帳.json")
    target = (study/pointer["参照"]).resolve()
    canonical = OLD_STUDY/"入力台帳.json"
    if target != canonical.resolve() or pointer["SHA256"] != O.sha(canonical):
        raise ValueError("固定28の66場台帳参照だけ")
    manifest = D.manifest_for(OLD_STUDY, config)
    return manifest


def build_session(entry: dict, manifest: dict, banks: dict, config: dict) -> dict:
    """一場のOHLC・数値・原価格発動だけを計算する。

    引数: entry/manifest/config(dict)は入力・条件、banks(dict)は3分の同限月数値銀行。
    返り値: dictはラベル/PnLなしの場内材料。建玉・公開履歴は毎場初期化する。
    """
    session = entry["session"]
    source = Path(manifest["source_root"])/entry["source_path"]
    cache = (ROOT/"work/複合検証"/entry["cache_path"]).resolve()
    if not cache.is_relative_to((ROOT/"work").resolve()):
        raise ValueError("キャッシュ参照がwork外")
    stat = source.stat()
    if (stat.st_size, stat.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]) or O.sha(cache) != entry["sha256_cache"]:
        raise ValueError("固定入力の指紋が変化")
    contract = tuple(entry["in_session_contract_codes"])
    if len(contract) != 1:
        raise ValueError("限月が一意でありません")
    begin, finish, cutoff, deadline = W.OLD.shared.legacy.session_times(session)
    start, end = begin.timestamp(), finish.timestamp()
    events, previous_now = [], -math.inf
    for event in W.PREP.read_events(cache):
        if math.isfinite(event.now) and start <= event.now <= end and event.now >= previous_now:
            events.append(event)
            previous_now = event.now
    frames, tails, qualities, quantities_quality = {}, {}, [], []
    for size, bank in banks.items():
        formed = W.bars_from_events(events, start, end, size)
        tail = max(0, int((end-start)//(size*60))-1-(formed[-1]["index"] if formed else -1))
        quantities, quantity_info = Q.aggregate(events, formed, start, end, size)
        quantities_quality.append({"場": session, **quantity_info})
        frames[size], quality = bank.build(formed, session, contract, tail, quantities)
        tails[str(size)] = tail
        qualities.append(quality)
    grouped, entry_quality = I.generate(frames[3], session, cutoff.timestamp(), deadline.timestamp(), config)
    return {"events": events, "frames": frames, "signals": grouped, "quality": entry_quality,
        "numeric_quality": qualities, "quantity_quality": quantities_quality, "cutoff": cutoff.timestamp(), "deadline": deadline.timestamp(),
        "duration": (end-start)/60, "input_quality": {"場": session, "正常板数": sum(e.valid for e in events),
            "確定足数": {str(n): sum(r["publish"] for r in rows) for n, rows in frames.items()}, "尾部欠枠": tails}}


def freeze(study: Path, work: Path) -> dict:
    """最終合成・主準備と旧固定を照合して実行前版を保存する。

    引数: study/work(Path)は正式/作業先。
    返り値: dictは固定。既存結果の上書きと準備後のコード変更を拒否する。
    """
    if (study/"結果.json").exists():
        raise ValueError("正式結果を上書きしません")
    proof = W.read_json(ROOT/"work/OBV反転/合成検証.json")
    if proof.get("全件成功") is not True or proof.get("合成編集終了") is not True:
        raise ValueError("最終合成の編集終了前には固定しません")
    prepare = W.read_json(work/"準備点検.json")
    if prepare["コードSHA256"] != code_pins() or prepare["条件SHA256"] != O.sha(study/"条件.json") or prepare["入力台帳SHA256"] != O.sha(study/"入力台帳.json") or prepare["参照台帳SHA256"] != O.sha(OLD_STUDY/"入力台帳.json"):
        raise ValueError("主準備のコード/条件/入力bindが不一致")
    paths = [Path(__file__), Path(__file__).with_name("入口.py"), Path(__file__).with_name("指標.py"),
        Path(__file__).with_name("合成検証.py"), study/"計画.md", study/"条件.json", study/"入力台帳.json"]
    for previous in (OLD_STUDY/"固定.json",):
        locked = W.read_json(previous)
        pins = locked["ファイルSHA256"]
        if any(O.sha(ROOT/name) != digest for name, digest in pins.items()):
            raise ValueError("固定済み参照コード又は入力が変更")
        paths += [previous, *[ROOT/name for name in pins]]
    pins = {p.relative_to(ROOT).as_posix(): O.sha(p) for p in dict.fromkeys(paths)}
    for p in (Path(__file__), Path(__file__).with_name("入口.py"), Path(__file__).with_name("指標.py"), Path(__file__).with_name("合成検証.py"), study/"条件.json"):
        key = p.relative_to(ROOT).as_posix()
        if proof["ファイルSHA256"].get(key) != pins[key]:
            raise ValueError("最終合成後のコード/条件変更")
    filename = study/"固定.json"
    if filename.exists():
        fixed = W.read_json(filename)
        if fixed["ファイルSHA256"] != pins:
            raise ValueError("実行前固定からの変更")
    else:
        fixed = {"固定日時": datetime.now(W.JST).isoformat(), "ファイルSHA256": pins,
            "主準備SHA256": O.sha(work/"準備点検.json"), "全66場既使用": True,
            "Python": platform.python_version(), "NumPy": W.np.__version__}
        W.write_json(filename, fixed)
    return fixed


def encode(row: dict) -> str:
    """一行の日本語JSONを作る。

    引数: row(dict)は保存対象。
    返り値: strは改行付きUTF-8用JSON。非有限値は例外。
    """
    return json.dumps(row, ensure_ascii=False, allow_nan=False)+"\n"


# ----------------------------------------
# 準備は純数値だけ、正式だけが先着・単一建玉・Viewerを作る。

def run(study: Path = STUDY, work: Path = WORK, prepare_only: bool = False) -> dict:
    """同じ数値銀行から二案を再生し、期間と参加集合を分けて保存する。

    引数: study/work(Path)は保存先、prepare_only(bool)は先着・損益を禁止する準備専用。
    返り値: dictは準備又は正式結果の件数。条件探索や候補選択は行わない。
    """
    config = W.read_json(study/"条件.json")
    entries, manifest = sources(config), manifest_for(study, config)
    initial_pins = code_pins()
    condition_sha, input_sha = O.sha(study/"条件.json"), O.sha(study/"入力台帳.json")
    manifest_sha = O.sha(OLD_STUDY/"入力台帳.json")
    if not prepare_only:
        freeze(study, work)
        if any((work/name).exists() for name in FILES):
            raise ValueError("既存の正式中間物を上書きしません")
    work.mkdir(parents=True, exist_ok=True)
    banks = {3: J.NumericBank()}
    cases, infos, trades = defaultdict(list), defaultdict(list), defaultdict(list)
    input_qualities, entry_qualities, numeric_qualities, quantity_qualities, prepared = [], [], [], [], []
    counts = []
    with ExitStack() as stack:
        streams = {name: stack.enter_context(compressed(work/name)) for name in FILES} if not prepare_only else {}
        for entry in manifest["entries"]:
            session, period = entry["session"], E.phase_of(entry["session"], config)
            block = build_session(entry, manifest, banks, config)
            quality = block["quality"]
            input_qualities.append({"期間": period, **block["input_quality"]})
            numeric_qualities.extend({"期間": period, **row} for row in block["numeric_quality"])
            quantity_qualities.extend({"期間": period, **row} for row in block["quantity_quality"])
            small = {k: v for k, v in quality.items() if k not in ("全Q発動記録", "複合context記録")}
            entry_qualities.append({"期間": period, **small})
            if prepare_only:
                prepared.append({"場": session, "期間": period, "指標": {str(n): rows for n, rows in block["frames"].items()},
                    "入口品質": quality, "指標品質": block["numeric_quality"], "数量品質": block["quantity_quality"], "入力品質": block["input_quality"]})
            else:
                for rows in block["frames"].values():
                    for row in rows:
                        streams["全指標.jsonl.gz"].write(encode({"期間": period, **row}))
                for row in quality["複合context記録"]:
                    streams["全複合context.jsonl.gz"].write(encode({"期間": period, **row}))
                path = W.OLD.気配経路([e for e in block["events"] if e.valid])
                label_cache = {}
                for row in quality["全Q発動記録"]:
                    label = shadow_label(row, path, label_cache, block["cutoff"], block["deadline"], config)
                    streams["全複合shadow.jsonl.gz"].write(encode({"期間": period, **row, **label}))
            for source in entries:
                source_id = source["入口ID"]
                signals = block["signals"][source_id]
                counts.append({"場": session, "期間": period, "入口ID": source_id, "発動数": len(signals),
                    "買い発動数": sum(s["side"] == 1 for s in signals), "売り発動数": sum(s["side"] == -1 for s in signals)})
                if prepare_only:
                    continue
                for signal in signals:
                    signal.update(期間=period, 要求時計JST=O.iso(signal["要求時計秒"]))
                    if not signal["先着評価対象"]:
                        raise ValueError("採用caseに先着対象外が混入")
                    label = shadow_label(signal, path, label_cache, block["cutoff"], block["deadline"], config)
                    case = {**signal, **label}
                    cases[source_id].append(case)
                    streams["入口事例.jsonl.gz"].write(encode(case))
                cid = source_id+"_X0"
                state, info = ENGINE.replay(block["events"], signals, block["frames"][3], session, cid,
                    config["運用"], config["出口"][0], source["役割"])
                info.update(期間=period, 場時間分=block["duration"])
                for trade in state.trades:
                    trade["期間"] = period
                infos[cid].append(info)
                trades[cid].extend(state.trades)
                for row in getattr(state, "normal_log", []):
                    streams["追尾.jsonl.gz"].write(encode({"期間": period, **row}))
                streams["全運用詳細.jsonl.gz"].write(encode({"候補ID": cid, "場": session, "品質": info,
                    "約定": state.fills, "取引": state.trades, "注文": state.orders, "入口取扱": state.signals}))
            print(f"00029 {session} "+("準備/原発動だけ完了" if prepare_only else "2入口・2運用完了"), flush=True)
    if code_pins() != initial_pins or O.sha(study/"条件.json") != condition_sha or O.sha(study/"入力台帳.json") != input_sha or O.sha(OLD_STUDY/"入力台帳.json") != manifest_sha:
        raise ValueError("実行中の主コード/条件/入力台帳変更")
    if prepare_only:
        summary = {"ラベル計算": False, "損益計算": False, "全66場既使用": True,
            "コードSHA256": initial_pins, "条件SHA256": condition_sha,
            "入力台帳SHA256": input_sha, "参照台帳SHA256": manifest_sha, "準備": prepared, "場別発動": counts, "期間別発動": []}
        for source in entries:
            for period in PERIODS:
                local = [r for r in counts if r["入口ID"] == source["入口ID"] and r["期間"] == period]
                active = [r for r in local if r["発動数"]]
                summary["期間別発動"].append({"入口ID": source["入口ID"], "期間": period,
                    "発動数": sum(r["発動数"] for r in local), "発動場数": len(active),
                    "発動開始日数": len({r["場"][:10] for r in active}),
                    "買い発動数": sum(r["買い発動数"] for r in local), "売り発動数": sum(r["売り発動数"] for r in local)})
        W.write_json(work/"準備点検.json", summary)
        return {"準備点検": True, "ラベル計算": False, "損益計算": False, "全66場": True}
    results, entrance_results, saved = [], [], []
    for source in entries:
        source_id = source["入口ID"]
        entrance = {**source, **{p: E.entry_metrics([r for r in cases[source_id] if r["期間"] == p], p) for p in PERIODS}}
        support, goal = entry_flags(entrance, config)
        entrance.update(入口支持=support, **{"70目標": goal})
        entrance_results.append(entrance)
        cid = source_id+"_X0"
        result = {"候補ID": cid, "入口": source, "出口": config["出口"][0], "入口支持": support, "70目標": goal}
        for period in PERIODS:
            operation = operation_metrics([i for i in infos[cid] if i["期間"] == period],
                [t for t in trades[cid] if t["期間"] == period], source["役割"], config["出口"][0])
            result[period] = {"入口": entrance[period], "運用": operation}
        result["費用資格"] = all(W.supported(result[p]["運用"], limits) and result[p]["運用"]["品質注意場数"] == 0
            and result[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        results.append(result)
        saved.append(cid)
    report = {"全66場既使用": True, "入口評価": entrance_results, "結果": results, "表示固定ID": saved,
        "入口70目標達成数": sum(r["70目標"] for r in results), "費用資格数": sum(r["費用資格"] for r in results),
        "入口125250評価の変更": False, "位置付け": "既使用66場で極値更新帯内反転への観測OBV非追随を比較。未使用確認ではない"}
    for name, value in (("入力品質.json", input_qualities), ("入口品質.json", entry_qualities), ("指標品質.json", numeric_qualities), ("数量品質.json", quantity_qualities)):
        W.write_json(study/name, value)
    W.write_csv(study/"全候補_場別.csv", [i for cid in infos for i in infos[cid]])
    E.publish_details(study, work/"全運用詳細.jsonl.gz", saved, manifest, "")
    catalog = W.read_json(study/"一覧.resources.json")
    for resource in catalog["resources"]:
        resource["id"] = resource["id"].replace("00008_", "00029_", 1)
    W.write_json(study/"一覧.resources.json", catalog)
    W.write_json(study/"作業成果物.json", {"原板複製": False, "展開内容SHA256が正本": True,
        "ファイル": [{"パス": (work/name).relative_to(ROOT).as_posix(), "展開内容SHA256": content_sha(work/name),
            "圧縮SHA256参考": O.sha(work/name), "圧縮バイト": (work/name).stat().st_size} for name in FILES]})
    W.write_json(study/"結果.json", report)
    return {"入口数": 2, "運用候補数": 2, "入口70目標達成数": report["入口70目標達成数"],
        "費用資格数": report["費用資格数"], "表示固定ID": saved}


def main() -> None:
    """準備又は固定後再生を、指定した保存先で行う。

    引数: なし。CLIの--prepare/--study/--workを読む。
    返り値: None。準備ではラベル・運用を呼ばない。
    """
    parser = argparse.ArgumentParser(description="BB内復帰とOBV非追随")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--prepare", action="store_true", help="純数値・原価格発動だけ。ラベル/運用再生は禁止")
    args = parser.parse_args()
    print(json.dumps(run(args.study.resolve(), args.work.resolve(), args.prepare), ensure_ascii=False))


if __name__ == "__main__":
    main()
