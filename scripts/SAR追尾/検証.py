"""固定31の二入口を共有し、ATR対照と精密公開SARの四運用を比較する。"""

from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime
import gzip
import importlib.util
import json
import math
from pathlib import Path
import platform
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00032_最低同値床と公開SAR追尾"
WORK = ROOT / "work/SAR追尾/00032"
OLD_STUDY = ROOT / "study/00031_CCI持続と上位BB幅"
ENTRY_WORK = ROOT / "work/CCI突破/00031"
MANIFEST_PATH = ROOT / "study/00028_基準線復帰と上位一目の方向/入力台帳.json"
PERIODS = ("学習", "条件選択", "後続検査")
FILES = ("SAR全足.jsonl.gz", "全運用詳細.jsonl.gz", "追尾.jsonl.gz")
SIGNAL_FIELDS = ("場", "イベントID", "入口ID", "役割", "side", "方向", "要求時計秒", "要求原板行",
    "確認遅延秒", "low", "high", "atr", "bb_mean")
OLD_LOCK_SHA = "b1a8cc4aec9def6907f65e0372ad8d280d62390e8059e83c1f38d6c927615cce"
OLD_CONDITION_SHA = "8d4cd04e02e26144f16375dea7e722fb84f7f6384a75606b925f1ea792d9ded1"
RULES = {"AF初期整数": 2, "AF増分整数": 2, "AF上限整数": 20, "AF分母": 100, "時間足分": 3,
    "精密": "元OHLC各floatからFraction、AF整数/100。hex分子/正分母を正規保存。float表示は判定へ戻さない",
    "SAR": "固定25の初期終値差strict/同値保留。成熟は前nextのstrict貫通先→非反転前2足clamp→EPstrict/AF→無clamp次足線",
    "初期": "買min(前L,現L)/売max(前H,現H)、EP現H/L。反転後買min(旧EP,現L)/売max(旧EP,現H)、EP現/AF初期",
    "数値": "同限月carry。欠枠/番号欠/不正/尾部欠/限月clear、有効欠枠当足は新種。全幅NP数値のみ、partial不投入",
    "公開": "当場最新だけ、場開始空。公開key後の正常BBOだけ、同秒後行可。最新無効に古正常fallbackなし",
    "起動": "正常返済BBOの観測MFE>=5で必ず名目同値床。SAR不準備でも起動",
    "候補": "公開tの次足線、t確定方向=実sideかつ元精密線の名目利益strict正。入口前の当場公開済みも可、最新一つ",
    "丸め": "Fraction整数演算の買ceil/売floorで5pt。買max/売min、最低同値かつ非緩和",
    "時点": "quote→公開SAR→signal。同keyの過去BBOやbar時lastBBOで更新/要求しない。候補が気配を越えても次BBOで初着要求",
    "pending": "数値/グローバル公開参照は進行、建玉の起動/設定線/適用出典は凍結。返済理由を取り直さない",
    "優先": "期限/既pending約定→hard125→TP250→必須追尾。通常exit/自動ドテンなし",
    "入口": "固定31C0/C1と125250を共有。SARを入口gateへ足さない。旧label/未来数値は純signalへ渡さない"}


def module(path: Path, name: str) -> Any:
    """固定済み処理をコマンド行実行せず読む。

    引数: path(Path)はコード、name(str)は識別名。
    返り値: Anyはモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


D = module(ROOT / "scripts/CCI突破/検証.py", "SAR追尾の固定31入口")
J = module(Path(__file__).with_name("指標.py"), "SAR追尾の精密銀行")
ENGINE = module(Path(__file__).with_name("運用.py"), "SAR追尾の二出口運用")
W, E, O = D.W, D.E, D.O
OLD_CONFIG = W.read_json(OLD_STUDY / "条件.json")
compressed, content_sha = D.compressed, D.content_sha


def operation_metrics(infos: list[dict], trades: list[dict], role: str, policy: dict) -> dict:
    """共通会計集計を、X0制限だけ外して二出口へ適用する。

    引数: infos/trades(list[dict])は場/取引、role(str)は役割、policy(dict)はX0又はXS。
    返り値: dictは旧31と同じ指標集合。出口条件は再生側で確定済み。
    """
    if policy not in ({"出口ID": "X0"}, {"出口ID": "XS"}):
        raise ValueError("未知の出口")
    return D.operation_metrics(infos, trades, role, {"出口ID": "X0"})


def expected_config() -> dict:
    """入口31と共通運用を保つ二出口条件を作る。

    引数: なし。
    返り値: dictは完全固定条件。閾値探索を行わない。
    """
    config = deepcopy(OLD_CONFIG)
    config.update(出口=[{"出口ID": "X0"}, {"出口ID": "XS"}], SAR追尾=deepcopy(RULES),
        入口条件参照={"パス": "../00031_CCI持続と上位BB幅/条件.json", "SHA256": O.sha(OLD_STUDY / "条件.json")},
        表示代表="C0_X0/C0_XS/C1_X0/C1_XSの4運用、入口評価は2案",
        出口定義={"X0": "固定31A5/入口ATR距離Dを完全再用", "XS": "A5最低同値床＋公開3分精密SAR次足線、ATR距離未使用"},
        依存="固定31入口/125250共有、固定26X0対照、32精密SARとXSだけ新規。入口評価2/運用4")
    return config


def validate_config(config: dict) -> None:
    """全入口・運用・SAR規約の改変を拒否する。

    引数: config(dict)は条件。
    返り値: None。不一致は例外。
    """
    if config != expected_config():
        raise ValueError("固定32条件又は固定31入口の参照が不一致")


def code_pins() -> dict:
    """新規主三コードの指紋を返す。

    引数: なし。
    返り値: dictはROOT相対パスからSHA256。
    """
    return {p.relative_to(ROOT).as_posix(): O.sha(p) for p in
        (Path(__file__), Path(__file__).with_name("指標.py"), Path(__file__).with_name("運用.py"))}


def sources(config: dict) -> list[dict]:
    """固定31の二入口をそのまま列挙する。

    引数: config(dict)は32条件。
    返り値: list[dict]は入口表示。四出口を入口候補数へ重複計上しない。
    """
    validate_config(config)
    return D.sources(OLD_CONFIG)


def manifest_for(study: Path, config: dict) -> dict:
    """既使用66場の固定台帳だけを解決する。

    引数: study(Path)は32、config(dict)は32条件。
    返り値: dictは既存キャッシュ台帳。新原板を探索しない。
    """
    validate_config(config)
    pointer = W.read_json(study / "入力台帳.json")
    if (study / pointer["参照"]).resolve() != MANIFEST_PATH.resolve() or pointer["SHA256"] != O.sha(MANIFEST_PATH):
        raise ValueError("固定28の66場参照だけ")
    return D.manifest_for(OLD_STUDY, OLD_CONFIG)


def validate_entry_reference(study: Path) -> dict:
    """共有入口の文書・証明・全圧縮明細の現在指紋を確認する。

    引数: study(Path)は32正式先。
    返り値: dictはroot所有の入口参照。改変された共有先は拒否する。
    """
    pointer = W.read_json(study / "入口参照.json")
    if pointer.get("参照試行") != "00031" or pointer.get("全66場既使用") is not True or pointer.get("大明細複製") is not False:
        raise ValueError("共有入口は固定31だけ")
    if pointer["旧固定SHA256"] != OLD_LOCK_SHA or O.sha(OLD_STUDY / "固定.json") != OLD_LOCK_SHA or O.sha(OLD_STUDY / "条件.json") != OLD_CONDITION_SHA:
        raise ValueError("固定31参照不一致")
    if set(pointer["文書と証明"]) != {"固定.json", "条件.json", "結果.json", "作業成果物.json", "独立監査.json", "状態独立確認.json", "追尾独立確認.json", "入力台帳.json"}:
        raise ValueError("共有入口の全証明が必要")
    for name, item in pointer["文書と証明"].items():
        canonical = OLD_STUDY / name
        if (ROOT / item["パス"]).resolve() != canonical.resolve() or item["SHA256"] != O.sha(canonical):
            raise ValueError("共有入口の文書/証明が不一致")
    expected = W.read_json(OLD_STUDY / "作業成果物.json")["ファイル"]
    if pointer["共有明細"] != expected:
        raise ValueError("共有明細の宣言が固定31と不一致")
    for item in expected:
        path = ROOT / item["パス"]
        if path.resolve().parent != ENTRY_WORK.resolve() or O.sha(path) != item["圧縮SHA256参考"]:
            raise ValueError("共有明細が固定31と不一致")
    return pointer


def shared_path(pointer: dict, name: str) -> Path:
    """共有明細の一意な参照先を得る。

    引数: pointer(dict)は入口参照、name(str)は共有ファイル名。
    返り値: Pathはroot配下の固定31明細。
    """
    found = [ROOT / r["パス"] for r in pointer["共有明細"] if Path(r["パス"]).name == name]
    if len(found) != 1 or found[0].resolve() != (ENTRY_WORK / name).resolve():
        raise ValueError("共有明細参照が一意でない")
    return found[0]


def load_shared_cases(pointer: dict) -> dict:
    """共有caseを比較/結果表示用に読む。

    引数: pointer(dict)は入口参照。
    返り値: dictは入口ID別保存case。live信号は別の純再構成から作る。
    """
    grouped = defaultdict(list)
    with gzip.open(shared_path(pointer, "入口事例.jsonl.gz"), "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            grouped[row["入口ID"]].append(row)
    return dict(grouped)


def pure_signal(row: dict) -> dict:
    """明示whitelistだけを新辞書へ写してlive信号を作る。

    引数: row(dict)は固定31の純再構成信号又は比較用保存case。
    返り値: dictは当時情報だけ。label/仮約定/将来MFE等を渡さない。
    """
    return {key: deepcopy(row.get(key)) if key == "bb_mean" else deepcopy(row[key]) for key in SIGNAL_FIELDS}


def decision_signal(row: dict) -> dict:
    """ATRの微小表現差だけをD整数と有効性へ分離する。

    引数: row(dict)は純signal。
    返り値: dictは独立厳密SHA用射影。ATR原値は準備の純信号に残す。
    """
    result = deepcopy(row)
    atr = result.pop("atr")
    valid = isinstance(atr, (float, int)) and math.isfinite(atr) and atr > 0
    result["ATR判断"] = {"正有効": valid, "Dpt整数": max(5, math.ceil(atr / 5) * 5) if valid else None}
    return result


def raw_projection(rows: list[dict]) -> list[dict]:
    """旧原Pの値をコピーせず、採否/時点の小射影を指紋化へ渡す。

    引数: rows(list[dict])は固定31の純原P。
    返り値: list[dict]は価格/CCI有理数/上位幅符号/全採否の射影。
    """
    keys = ("場", "発動ID", "index", "side", "close", "要求時計秒", "要求原板行", "足終了時計秒",
        "直前最高H", "直前最安L", "共通M準備", "M除外理由", "時間条件可", "確認遅延条件可", "先着評価対象", "戦略判定", "BB幅比較厳密符号")
    return [{**{key: deepcopy(r[key]) for key in keys}, **{name: None if r[name] is None else
        {key: r[name][key] for key in ("分子", "分母", "有効")} for name in ("CCI現", "CCI前")}} for r in rows]


def build_session(entry: dict, manifest: dict, banks: dict, sarbank: Any, config: dict) -> dict:
    """固定31を純再構成し、別銀行のSARだけを追加する。

    引数: entry/manifest/config(dict)は台帳/条件、banks(dict)は旧3/15銀行、sarbank(Any)は新精密銀行。
    返り値: dictはlabel/PnLなしの場材料。旧数値/contextを32へ全転記しない。
    """
    block = D.build_session(entry, manifest, banks, OLD_CONFIG)
    block["signals"] = {key: [pure_signal(row) for row in rows] for key, rows in block["signals"].items()}
    block["sar_rows"], block["sar_quality"] = sarbank.build(block["frames"][3], entry["session"],
        tuple(entry["in_session_contract_codes"]), block["input_quality"]["尾部欠枠"]["3"])
    return block


def validate_independent(study: Path, work: Path) -> dict:
    """独立の主準備/条件/共有先/全コードbindを必須joinする。

    引数: study/work(Path)は32正式/作業先。
    返り値: dictは成功proof。不足・不一致では固定を拒否する。
    """
    proof = W.read_json(work / "独立準備点検.json")
    if proof.get("全件一致") is not True or proof.get("不一致数") != 0 or proof.get("不一致") != [] or proof.get("ラベル計算") is not False or proof.get("損益計算") is not False:
        raise ValueError("独立非PnL準備の成功前には固定しません")
    expected = {"主準備SHA256": O.sha(work / "準備点検.json"), "主コードSHA256": code_pins(),
        "条件SHA256": O.sha(study / "条件.json"), "入力台帳SHA256": O.sha(study / "入力台帳.json"),
        "参照入力台帳SHA256": O.sha(MANIFEST_PATH), "入口参照SHA256": O.sha(study / "入口参照.json"),
        "コードSHA256": O.sha(Path(__file__).with_name("状態独立確認.py")),
        "追尾コードSHA256": O.sha(Path(__file__).with_name("追尾独立確認.py"))}
    if any(proof.get(key) != value for key, value in expected.items()):
        raise ValueError("独立準備の現在版/共有入口bind不一致")
    dependencies = proof.get("依存コードSHA256")
    if not isinstance(dependencies, dict) or not dependencies:
        raise ValueError("独立依存の指紋が必要")
    for name, digest in dependencies.items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT.resolve()) or path.suffix != ".py" or O.sha(path) != digest:
            raise ValueError("独立依存の現在版不一致")
    return proof


def freeze(study: Path, work: Path) -> dict:
    """主/独立準備・合成・共有31と全出典を固定する。

    引数: study/work(Path)は32正式/作業先。
    返り値: dictは固定版。既存結果上書きと準備後変更は拒否する。
    """
    if (study / "結果.json").exists():
        raise ValueError("既存結果は上書きしません")
    reference_data = validate_entry_reference(study)
    prepared = W.read_json(work / "準備点検.json")
    expected = {"コードSHA256": code_pins(), "条件SHA256": O.sha(study / "条件.json"),
        "入力台帳SHA256": O.sha(study / "入力台帳.json"), "参照台帳SHA256": O.sha(MANIFEST_PATH),
        "入口参照SHA256": O.sha(study / "入口参照.json")}
    if any(prepared.get(key) != value for key, value in expected.items()) or prepared.get("ラベル計算") is not False or prepared.get("損益計算") is not False or prepared.get("旧31純信号同値") is not True:
        raise ValueError("主準備の現版又は純入口同値が未確認")
    independent = validate_independent(study, work)
    synthetic_path = ROOT / "work/SAR追尾/合成検証.json"
    synthetic = W.read_json(synthetic_path)
    if synthetic.get("全件成功") is not True or synthetic.get("合成編集終了") is not True:
        raise ValueError("合成の最終成功前には固定しません")
    old_lock = W.read_json(OLD_STUDY / "固定.json")
    pins = dict(old_lock["ファイルSHA256"])
    for name, digest in pins.items():
        if O.sha(ROOT / name) != digest:
            raise ValueError("旧31固定出典に変化")
    paths = [Path(__file__), Path(__file__).with_name("指標.py"), Path(__file__).with_name("運用.py"),
        Path(__file__).with_name("合成検証.py"), Path(__file__).with_name("状態独立確認.py"), Path(__file__).with_name("追尾独立確認.py"),
        study / "計画.md", study / "条件.json", study / "入力台帳.json", study / "入口参照.json",
        work / "準備点検.json", work / "独立準備点検.json", work / "診断予定.json", synthetic_path,
        ROOT / "docs/technical-analysis/指標/パラボリックSAR.md"]
    paths.extend(ROOT / item["パス"] for item in reference_data["文書と証明"].values())
    paths.extend(ROOT / item["パス"] for item in reference_data["共有明細"])
    paths.extend(ROOT / name for name in independent["依存コードSHA256"])
    for path in paths:
        pins[path.relative_to(ROOT).as_posix()] = O.sha(path)
    for path in (Path(__file__), Path(__file__).with_name("指標.py"), Path(__file__).with_name("運用.py"), Path(__file__).with_name("合成検証.py"), study / "条件.json"):
        key = path.relative_to(ROOT).as_posix()
        if synthetic.get("ファイルSHA256", {}).get(key) != pins[key]:
            raise ValueError("合成が最終主版へbindされていません")
    locked = {"固定日時": datetime.now().astimezone().isoformat(), "ファイルSHA256": dict(sorted(pins.items())),
        "主準備SHA256": O.sha(work / "準備点検.json"), "独立準備SHA256": O.sha(work / "独立準備点検.json"),
        "入口参照SHA256": O.sha(study / "入口参照.json"), "全66場既使用": True, "Python": platform.python_version(), "NumPy": W.np.__version__}
    if (study / "固定.json").exists():
        existing = W.read_json(study / "固定.json")
        if existing["ファイルSHA256"] != locked["ファイルSHA256"]:
            raise ValueError("固定後の出典変更")
        return existing
    W.write_json(study / "固定.json", locked)
    return locked


def run(study: Path, work: Path, prepare_only: bool) -> dict:
    """共有純入口を検査し、準備又は固定後の四運用を実行する。

    引数: study/work(Path)は32正式/作業先、prepare_only(bool)は非PnL準備。
    返り値: dictは完了要約。市場実行開始はrootが担当する。
    """
    config = W.read_json(study / "条件.json")
    validate_config(config)
    manifest = manifest_for(study, config)
    reference_data = validate_entry_reference(study)
    source_list = sources(config)
    study.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    initial = {"コードSHA256": code_pins(), "条件SHA256": O.sha(study / "条件.json"),
        "入力台帳SHA256": O.sha(study / "入力台帳.json"), "参照台帳SHA256": O.sha(MANIFEST_PATH),
        "入口参照SHA256": O.sha(study / "入口参照.json")}
    if not prepare_only:
        if any((work / name).exists() for name in FILES):
            raise ValueError("既存の正式中間物を上書きしません")
        freeze(study, work)
    saved_cases = load_shared_cases(reference_data)
    saved_projection = {r["イベントID"]: pure_signal(r) for rows in saved_cases.values() for r in rows}
    del saved_cases
    banks, sarbank = {n: D.J.NumericBank(n) for n in (3, 15)}, J.SARBank()
    prepared, input_quality, numeric_quality, control, all_signals = [], [], [], [], {}
    infos, trades = defaultdict(list), defaultdict(list)
    old_operations, old_logs = {}, defaultdict(list)
    if not prepare_only:
        with gzip.open(shared_path(reference_data, "全運用詳細.jsonl.gz"), "rt", encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                old_operations[row["候補ID"], row["場"]] = row
        with gzip.open(shared_path(reference_data, "追尾.jsonl.gz"), "rt", encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                old_logs[row["候補ID"], row["場"]].append(row)
    encode = lambda row: json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
    with ExitStack() as stack:
        streams = {name: stack.enter_context(compressed(work / name)) for name in FILES} if not prepare_only else {}
        for entry in manifest["entries"]:
            session, period = entry["session"], E.phase_of(entry["session"], config)
            block = build_session(entry, manifest, banks, sarbank, config)
            current_signals = [r for source in source_list for r in block["signals"][source["入口ID"]]]
            for signal in current_signals:
                if signal != saved_projection.get(signal["イベントID"]):
                    raise ValueError("固定31と純信号が一致しません")
                all_signals[signal["イベントID"]] = signal
            record = {"場": session, "期間": period, "純信号": current_signals,
                "純信号内容SHA256": J.canonical_sha(current_signals),
                "純信号判断SHA256": J.canonical_sha([decision_signal(r) for r in current_signals]),
                "原P判定SHA256": J.canonical_sha(raw_projection(block["quality"]["全Q発動記録"])),
                "入口品質": {key: value for key, value in block["quality"].items() if key not in ("全Q発動記録", "複合context記録")},
                "SAR品質": block["sar_quality"], "入力品質": block["input_quality"]}
            input_quality.append({"期間": period, **block["input_quality"]})
            numeric_quality.append({"期間": period, **block["sar_quality"]})
            if prepare_only:
                prepared.append({**record, "SAR全足": block["sar_rows"]})
                print(f"00032 {session} 純入口同値/SAR準備のみ", flush=True)
                continue
            for row in block["sar_rows"]:
                streams["SAR全足.jsonl.gz"].write(encode({"期間": period, **row}))
            for source in source_list:
                signals = block["signals"][source["入口ID"]]
                for policy in config["出口"]:
                    cid = source["入口ID"] + "_" + policy["出口ID"]
                    state, info = ENGINE.replay(block["events"], signals, block["frames"][3], block["sar_rows"],
                        session, cid, config["運用"], policy, source["役割"])
                    info.update(期間=period, 場時間分=block["duration"])
                    for trade in state.trades:
                        trade["期間"] = period
                    detail = {"候補ID": cid, "場": session, "品質": info, "約定": state.fills,
                        "取引": state.trades, "注文": state.orders, "入口取扱": state.signals}
                    normal_log = [{"期間": period, **row} for row in state.normal_log]
                    if policy["出口ID"] == "X0":
                        if detail != old_operations[cid, session] or normal_log != old_logs[cid, session]:
                            raise ValueError("X0の全保存運用/追尾が旧31と不一致")
                        control.append({"場": session, "候補ID": cid, "全運用同値": True, "全追尾同値": True,
                            "全運用内容SHA256": J.canonical_sha([detail]), "追尾内容SHA256": J.canonical_sha(normal_log)})
                    infos[cid].append(info)
                    trades[cid].extend(state.trades)
                    streams["全運用詳細.jsonl.gz"].write(encode(detail))
                    for row in normal_log:
                        streams["追尾.jsonl.gz"].write(encode(row))
            print(f"00032 {session} 2入口/4運用完了", flush=True)
    if set(all_signals) != set(saved_projection):
        raise ValueError("純入口全集合が旧31と不一致")
    current = {"コードSHA256": code_pins(), "条件SHA256": O.sha(study / "条件.json"),
        "入力台帳SHA256": O.sha(study / "入力台帳.json"), "参照台帳SHA256": O.sha(MANIFEST_PATH),
        "入口参照SHA256": O.sha(study / "入口参照.json")}
    if current != initial:
        raise ValueError("実行中の主版/条件/共有参照変更")
    if prepare_only:
        W.write_json(work / "準備点検.json", {**initial, "ラベル計算": False, "損益計算": False,
            "全66場既使用": True, "旧31純信号同値": True, "純信号whitelist": list(SIGNAL_FIELDS),
            "準備": prepared, "共有入口参照": reference_data, "純信号数": len(all_signals)})
        return {"準備点検": True, "ラベル計算": False, "損益計算": False, "純信号数": len(all_signals)}
    old_result = W.read_json(OLD_STUDY / "結果.json")
    entrances, results, ids = deepcopy(old_result["入口評価"]), [], []
    for source in source_list:
        entrance = next(r for r in entrances if r["入口ID"] == source["入口ID"])
        for policy in config["出口"]:
            cid = source["入口ID"] + "_" + policy["出口ID"]
            result = {"候補ID": cid, "入口": source, "出口": policy,
                "入口支持": entrance["入口支持"], "70目標": entrance["70目標"]}
            for period in PERIODS:
                metric = operation_metrics([r for r in infos[cid] if r["期間"] == period],
                    [t for t in trades[cid] if t["期間"] == period], source["役割"], policy)
                result[period] = {"入口": entrance[period], "運用": metric}
            result["費用資格"] = all(W.supported(result[p]["運用"], limits) and result[p]["運用"]["品質注意場数"] == 0
                and result[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
            results.append(result)
            ids.append(cid)
    report = {"全66場既使用": True, "入口評価": entrances, "結果": results, "表示固定ID": ids,
        "入口70目標達成数": sum(r["70目標"] for r in entrances), "費用資格数": sum(r["費用資格"] for r in results),
        "入口125250評価の変更": False, "入口評価数": 2, "運用候補数": 4,
        "位置付け": "固定31の二入口/先着を共有し、最低同値床後のATR対公開SARを既使用66場で比較"}
    W.write_json(study / "入力品質.json", input_quality)
    W.write_json(study / "指標品質.json", numeric_quality)
    W.write_json(study / "X0対照同値.json", {"全件一致": True, "場候補数": len(control), "照合": control,
        "入口参照SHA256": initial["入口参照SHA256"]})
    W.write_csv(study / "全候補_場別.csv", [r for cid in ids for r in infos[cid]])
    E.publish_details(study, work / "全運用詳細.jsonl.gz", ids, manifest, "")
    catalog = W.read_json(study / "一覧.resources.json")
    for resource in catalog["resources"]:
        resource["id"] = resource["id"].replace("00008_", "00032_", 1)
    W.write_json(study / "一覧.resources.json", catalog)
    W.write_json(study / "作業成果物.json", {"原板複製": False, "展開内容SHA256が正本": True,
        "共有入口参照": "入口参照.json", "ファイル": [{"パス": (work / name).relative_to(ROOT).as_posix(),
            "展開内容SHA256": content_sha(work / name), "圧縮SHA256参考": O.sha(work / name),
            "圧縮バイト": (work / name).stat().st_size} for name in FILES]})
    W.write_json(study / "結果.json", report)
    return {"入口数": 2, "運用候補数": 4, "入口70目標達成数": report["入口70目標達成数"], "費用資格数": report["費用資格数"]}


def main() -> None:
    """準備又は固定後の正式比較を起動する。

    引数: なし。CLIは--study/--work/--prepare。
    返り値: None。主市場計算の起動担当はroot。
    """
    parser = argparse.ArgumentParser(description="最低同値床と公開SAR追尾")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--prepare", action="store_true", help="純入口/SARだけ。先着/運用/PnLは禁止")
    args = parser.parse_args()
    print(json.dumps(run(args.study.resolve(), args.work.resolve(), args.prepare), ensure_ascii=False))


if __name__ == "__main__":
    main()
