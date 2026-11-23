"""固定31C0の価格突破とCCI持続へ、同時点CLV選別だけを追加する。"""

from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00033_CCI突破と足内終値位置"
WORK = ROOT/"work/終値位置/00033"
OLD_STUDY = ROOT/"study/00031_CCI持続と上位BB幅"
MANIFEST_PATH = ROOT/"study/00028_基準線復帰と上位一目の方向/入力台帳.json"
PERIODS = ("学習", "条件選択", "後続検査")
FILES = ("形状選別.jsonl.gz", "全運用詳細.jsonl.gz", "追尾.jsonl.gz")
OPERATION_PAIRS = (("T0", "X0"), ("T0", "XF"), ("T1", "XF"))
RULES = {"対照": "T0は固定31C0。M/価格/現前CCI/時間/確認遅延を完全保持",
    "追加": "T1はT0かつ現在足H>Lかつ実side*CLV>0strict。CLV0不採用、幅0はT1だけ技術不可",
    "CLV": "元OHLC各floatをFraction化、(2C-H-L)/(H-L)。表示floatは判定へ戻さない",
    "公開": "固定31と同じ3分突破足の公開key。後続待ち/当足途中/価格取り直しなし",
    "診断": "前3分ATRと直前20高安幅による突破距離を保存するが採否へ不使用。欠測で入口を除外しない",
    "段階": "全原P→M/時間/CCI後T0→CLV幅有効→実方向正/0/負。幅0除外と符号選別を分離",
    "運用": "旧X0/A5参考と新XF。XFは現在返済BBO利益×倍率−往復手数料−往復想定追加滑り>0strictで起動。起動後MFE-D/最低名目新規床。SAR/上位BB幅値/通常出口なし",
    "先着": "旧31C0の同時計caseを正式集計だけ共有。liveは純再構成whitelist、未来情報なし"}


def module(path: Path, name: str) -> Any:
    """固定コードをCLI起動せず読み込む。

    引数: path(Path)はコード、name(str)は識別名。
    返り値: Anyは読取モジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


S = module(ROOT/"scripts/SAR追尾/検証.py", "終値位置の固定32共有参照")
D = S.D
I = module(Path(__file__).with_name("入口.py"), "終値位置の同時点選別")
J, W, E, O = D.J, D.W, D.E, D.O
ENGINE = module(Path(__file__).with_name("運用.py"), "終値位置の費用起動運用")
OLD_CONFIG = W.read_json(OLD_STUDY/"条件.json")
compressed, content_sha = D.compressed, D.content_sha
SIGNAL_FIELDS = I.SIGNAL_FIELDS


def canonical_sha(rows: object) -> str:
    """保存値を固定JSON書式で指紋化する。

    引数: rows(object)はJSON化可能な値。
    返り値: strはSHA256。
    """
    body = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def expected_config() -> dict:
    """旧運用値を保持した同時点二入口を組み立てる。

    引数: なし。
    返り値: dictは33固定条件。旧CCI定義は参照内へ残す。
    """
    config = deepcopy(OLD_CONFIG)
    config.pop("CCI突破")
    config["運用"]["追尾起動想定片道滑りpt"] = 5
    config["必須追尾"].update(起動幅pt=None, 起動条件="XFは現在返済BBOの有利額×倍率−往復手数料−往復想定追加滑り>0strict",
        起動参照想定片道滑りpt=5, 起動参照往復費用円=122, 旧X0起動幅pt=5,
        最低床="名目新規価格。費用後同値への床変更ではない")
    config.update(戦略=list(I.POLICIES), 終値位置=deepcopy(RULES), 出口=[{"出口ID": "X0"}, {"出口ID": "XF"}],
        入口条件参照={"パス": "../00031_CCI持続と上位BB幅/条件.json", "SHA256": O.sha(OLD_STUDY/"条件.json")},
        表示代表="T0_X0旧参考/T0_XF費用起動/T1_XF形状追加の3運用", 入口125250評価の変更=True,
        運用組合せ=[{"戦略": p, "出口ID": x} for p, x in OPERATION_PAIRS],
        現方針候補出口=["XF"],
        出口定義={"X0": "旧31A5参考、現在方針採用候補外", "XF": "現在費用後含み益strict正で起動、以後入口ATR固定D・最低名目同値"},
        依存="固定31純C0/元OHLCとX0、固定32共有参照補助。新規は同時点CLVとユーザー指定の費用後正起動")
    return config


def validate_config(config: dict) -> None:
    """事前定義以外の閾値・運用変更を拒否する。

    引数: config(dict)は33条件。
    返り値: None。不一致は例外。
    """
    if config != expected_config():
        raise ValueError("固定33条件に不一致")


def code_pins() -> dict:
    """新しい主二コードの現在指紋を返す。

    引数: なし。
    返り値: dictはROOT相対パスとSHA256。
    """
    return {p.relative_to(ROOT).as_posix(): O.sha(p) for p in
        (Path(__file__), Path(__file__).with_name("入口.py"), Path(__file__).with_name("運用.py"))}


def sources(config: dict) -> list[dict]:
    """固定二案を候補選択せず列挙する。

    引数: config(dict)は条件。
    返り値: list[dict]は表示・運用の入口定義。
    """
    validate_config(config)
    return [{"入口ID": "3分_"+p, "戦略": p, "時間足分": 3, "名称": p,
        "役割": "順行", "複合本命": True} for p in I.POLICIES]


def exits_for(source: dict) -> list[dict]:
    """入口別に事前指定した三運用だけを列挙する。

    引数: source(dict)はT0又はT1の入口。
    返り値: list[dict]はX0参考又はXF。T1_X0は生成しない。
    """
    return [{"出口ID": exit_id} for policy, exit_id in OPERATION_PAIRS if policy == source["戦略"]]


def operation_metrics(infos: list[dict], trades: list[dict], role: str, policy: dict) -> dict:
    """固定会計を参照出口と新起動出口へ同じ式で集計する。

    引数: infos/trades(list[dict])は場/取引、role(str)は役割、policy(dict)は出口。
    返り値: dictは従来と同じ会計指標。出口の再生はやり直さない。
    """
    if policy not in ({"出口ID": "X0"}, {"出口ID": "XF"}):
        raise ValueError("固定二出口だけ")
    return D.operation_metrics(infos, trades, role, {"出口ID": "X0"})


def manifest_for(study: Path, config: dict) -> dict:
    """既使用66場の固定台帳だけを解決する。

    引数: study(Path)は33、config(dict)は条件。
    返り値: dictは既存キャッシュ入力。新場を探索しない。
    """
    validate_config(config)
    pointer = W.read_json(study/"入力台帳.json")
    if (study/pointer["参照"]).resolve() != MANIFEST_PATH.resolve() or pointer["SHA256"] != O.sha(MANIFEST_PATH):
        raise ValueError("固定28台帳だけ")
    return D.manifest_for(OLD_STUDY, OLD_CONFIG)


def validate_entry_reference(study: Path) -> dict:
    """共有31の文書・証明・六明細を現在指紋で確認する。

    引数: study(Path)は33。
    返り値: dictは共有先の固定参照。
    """
    return S.validate_entry_reference(study)


def shared_path(pointer: dict, name: str) -> Path:
    """共有31の明細パスを一意に解決する。

    引数: pointer(dict)は参照、name(str)はファイル名。
    返り値: Pathは固定31作業明細。
    """
    return S.shared_path(pointer, name)


def old_identity(value: object) -> object:
    """T0候補とイベントの識別子だけをC0へ戻す。

    引数: value(object)はJSON保存値。
    返り値: objectは全数値を保った旧識別子の値。
    """
    if isinstance(value, dict):
        return {k: old_identity(v) for k, v in value.items()}
    if isinstance(value, list):
        return [old_identity(v) for v in value]
    if isinstance(value, str):
        return value.replace("_T0", "_C0")
    return value


def build_session(entry: dict, manifest: dict, banks: dict, config: dict) -> dict:
    """固定31を純再構成し、同時点形状選別だけを加える。

    引数: entry/manifest/config(dict)は入力/条件、banks(dict)は固定31数値銀行。
    返り値: dictは先着・運用・損益なしの場材料。
    """
    validate_config(config)
    return I.select(D.build_session(entry, manifest, banks, OLD_CONFIG))


def decision_shape(row: dict) -> dict:
    """独立ATRの微小表現差だけを判断指紋から分ける。

    引数: row(dict)は元の形状保存値。
    返り値: dictはCLV/価格/採否厳密の射影。前ATR原値は別照合する。
    """
    value = deepcopy(row)
    diagnostic = value["診断"]
    atr = diagnostic.pop("前ATR")
    diagnostic["前ATR判断"] = {"正有効": atr is not None,
        "Dpt整数": max(5, math.ceil(atr/5)*5) if atr is not None else None}
    diagnostic["前ATR規格化突破距離"] = {"有効": diagnostic["前ATR規格化突破距離"]["有効"]}
    return value


def validate_independent(study: Path, work: Path) -> dict:
    """独立準備の成功と現在版への接続を必須にする。

    引数: study/work(Path)は33保存先。
    返り値: dictは独立準備証明。差又は古版は拒否する。
    """
    proof = W.read_json(work/"独立準備点検.json")
    if proof.get("全件一致") is not True or proof.get("不一致数") != 0 or proof.get("不一致") != [] or proof.get("ラベル計算") is not False or proof.get("損益計算") is not False:
        raise ValueError("独立非PnL準備成功前には固定しません")
    expected = {"主準備SHA256": O.sha(work/"準備点検.json"), "主コードSHA256": code_pins(),
        "条件SHA256": O.sha(study/"条件.json"), "入力台帳SHA256": O.sha(study/"入力台帳.json"),
        "参照入力台帳SHA256": O.sha(MANIFEST_PATH), "入口参照SHA256": O.sha(study/"入口参照.json"),
        "コードSHA256": O.sha(Path(__file__).with_name("状態独立確認.py")),
        "追尾コードSHA256": O.sha(Path(__file__).with_name("追尾独立確認.py"))}
    if any(proof.get(k) != v for k, v in expected.items()):
        raise ValueError("独立準備の現在版bind不一致")
    dependencies = proof.get("依存コードSHA256")
    if not isinstance(dependencies, dict) or not dependencies:
        raise ValueError("独立依存の指紋が必要")
    for name, digest in dependencies.items():
        path = (ROOT/name).resolve()
        if not path.is_relative_to(ROOT.resolve()) or path.suffix != ".py" or O.sha(path) != digest:
            raise ValueError("独立依存に現在版との差")
    return proof


def freeze(study: Path, work: Path) -> dict:
    """非PnL準備・人工・共有先の全出典を正式再生前に固定する。

    引数: study/work(Path)は33保存先。
    返り値: dictは固定。既存結果と不一致固定の上書きを拒否する。
    """
    if (study/"結果.json").exists():
        raise ValueError("既存結果は上書きしません")
    reference_data = validate_entry_reference(study)
    prepared = W.read_json(work/"準備点検.json")
    expected = {"コードSHA256": code_pins(), "条件SHA256": O.sha(study/"条件.json"),
        "入力台帳SHA256": O.sha(study/"入力台帳.json"), "参照台帳SHA256": O.sha(MANIFEST_PATH),
        "入口参照SHA256": O.sha(study/"入口参照.json")}
    if any(prepared.get(k) != v for k, v in expected.items()) or prepared.get("ラベル計算") is not False or prepared.get("損益計算") is not False or prepared.get("旧31C0純信号同値") is not True:
        raise ValueError("主準備の現在版又は純入口同値が未確認")
    independent = validate_independent(study, work)
    synthetic_path = ROOT/"work/終値位置/合成検証.json"
    synthetic = W.read_json(synthetic_path)
    if synthetic.get("全件成功") is not True or synthetic.get("合成編集終了") is not True:
        raise ValueError("最終人工成功前には固定しません")
    previous = ROOT/"study/00032_最低同値床と公開SAR追尾/固定.json"
    pins = dict(W.read_json(previous)["ファイルSHA256"])
    for name, digest in pins.items():
        if O.sha(ROOT/name) != digest:
            raise ValueError("旧固定出典に変更")
    paths = [Path(__file__), Path(__file__).with_name("入口.py"), Path(__file__).with_name("運用.py"), Path(__file__).with_name("合成検証.py"),
        Path(__file__).with_name("状態独立確認.py"), Path(__file__).with_name("追尾独立確認.py"),
        study/"計画.md", study/"条件.json", study/"入力台帳.json", study/"入口参照.json", previous,
        work/"準備点検.json", work/"独立準備点検.json", work/"診断予定.json", work/"仕様更新記録.json", synthetic_path,
        ROOT/"work/次入口候補33.md"]
    paths.extend(ROOT/item["パス"] for item in reference_data["文書と証明"].values())
    paths.extend(ROOT/item["パス"] for item in reference_data["共有明細"])
    paths.extend(ROOT/name for name in independent["依存コードSHA256"])
    for path in paths:
        pins[path.relative_to(ROOT).as_posix()] = O.sha(path)
    for path in (Path(__file__), Path(__file__).with_name("入口.py"), Path(__file__).with_name("運用.py"), Path(__file__).with_name("合成検証.py"), study/"条件.json"):
        key = path.relative_to(ROOT).as_posix()
        if synthetic.get("ファイルSHA256", {}).get(key) != pins[key]:
            raise ValueError("最終人工と主版bindが不一致")
    for field, name in (("独立数値補助SHA256", "状態独立確認.py"), ("独立追尾補助SHA256", "追尾独立確認.py")):
        if synthetic.get(field) != O.sha(Path(__file__).with_name(name)):
            raise ValueError("最終人工の独立コードbindが不一致")
    locked = {"固定日時": datetime.now().astimezone().isoformat(), "ファイルSHA256": dict(sorted(pins.items())),
        "主準備SHA256": O.sha(work/"準備点検.json"), "独立準備SHA256": O.sha(work/"独立準備点検.json"),
        "入口参照SHA256": O.sha(study/"入口参照.json"), "全66場既使用": True,
        "Python": platform.python_version(), "NumPy": W.np.__version__}
    if (study/"固定.json").exists():
        old = W.read_json(study/"固定.json")
        if old["ファイルSHA256"] != locked["ファイルSHA256"]:
            raise ValueError("固定後出典変更")
        return old
    W.write_json(study/"固定.json", locked)
    return locked


def run(study: Path, work: Path, prepare_only: bool) -> dict:
    """全原Pの形状を純準備し、固定後だけ二案を運用する。

    引数: study/work(Path)は保存先、prepare_only(bool)は非PnL準備。
    返り値: dictは完了要約。市場起動担当はroot。
    """
    config = W.read_json(study/"条件.json")
    validate_config(config)
    manifest, pointer = manifest_for(study, config), validate_entry_reference(study)
    entries = sources(config)
    initial = {"コードSHA256": code_pins(), "条件SHA256": O.sha(study/"条件.json"),
        "入力台帳SHA256": O.sha(study/"入力台帳.json"), "参照台帳SHA256": O.sha(MANIFEST_PATH),
        "入口参照SHA256": O.sha(study/"入口参照.json")}
    work.mkdir(parents=True, exist_ok=True)
    if not prepare_only:
        if any((work/name).exists() for name in FILES):
            raise ValueError("既存正式明細は上書きしません")
        freeze(study, work)
    shared_cases = S.load_shared_cases(pointer)["3分_C0"]
    saved_projection = {r["イベントID"]: S.pure_signal(r) for r in shared_cases}
    case_lookup = {r["イベントID"]: r for r in shared_cases} if not prepare_only else None
    del shared_cases
    banks = {n: J.NumericBank(n) for n in (3, 15)}
    prepared, input_quality, control, all_t0 = [], [], [], {}
    infos, trades, selected_ids = defaultdict(list), defaultdict(list), defaultdict(list)
    old_operations, old_logs = {}, defaultdict(list)
    if not prepare_only:
        with gzip.open(shared_path(pointer, "全運用詳細.jsonl.gz"), "rt", encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if row["候補ID"] == "3分_C0_X0":
                    old_operations[row["場"]] = row
        with gzip.open(shared_path(pointer, "追尾.jsonl.gz"), "rt", encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if row["候補ID"] == "3分_C0_X0":
                    old_logs[row["場"]].append(row)
    encode = lambda row: json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False)+"\n"
    with ExitStack() as stack:
        streams = {name: stack.enter_context(compressed(work/name)) for name in FILES} if not prepare_only else {}
        for entry in manifest["entries"]:
            session, period = entry["session"], E.phase_of(entry["session"], config)
            block = build_session(entry, manifest, banks, config)
            current = [r for source in entries for r in block["signals"][source["入口ID"]]]
            for signal in block["signals"]["3分_T0"]:
                old = old_identity(signal)
                if old != saved_projection.get(old["イベントID"]):
                    raise ValueError("固定31C0と純信号不一致")
                all_t0[old["イベントID"]] = old
            record = {"場": session, "期間": period, "純信号": current,
                "純信号内容SHA256": canonical_sha(current),
                "純信号判断SHA256": canonical_sha([S.decision_signal(r) for r in current]),
                "原P判定SHA256": canonical_sha(S.raw_projection(block["quality"]["全Q発動記録"])),
                "形状判断SHA256": canonical_sha([decision_shape(r) for r in block["shape_rows"]]),
                "形状選別": block["shape_rows"], "入力品質": block["input_quality"]}
            input_quality.append({"期間": period, **block["input_quality"]})
            if prepare_only:
                prepared.append(record)
                print(f"00033 {session} T0同値/CLV純準備のみ", flush=True)
                continue
            for row in block["shape_rows"]:
                streams["形状選別.jsonl.gz"].write(encode({"期間": period, **row}))
            for source in entries:
                sid, policy = source["入口ID"], source["戦略"]
                signals = block["signals"][sid]
                selected_ids[sid].extend(r["イベントID"][:-3]+"_C0" for r in signals)
                for exit_policy in exits_for(source):
                    cid = sid+"_"+exit_policy["出口ID"]
                    state, info = ENGINE.replay(block["events"], signals, block["frames"][3], session,
                        cid, config["運用"], exit_policy, source["役割"])
                    info.update(期間=period, 場時間分=block["duration"])
                    for trade in state.trades:
                        trade["期間"] = period
                    detail = {"候補ID": cid, "場": session, "品質": info, "約定": state.fills,
                        "取引": state.trades, "注文": state.orders, "入口取扱": state.signals}
                    logs = [{"期間": period, **r} for r in state.normal_log]
                    if policy == "T0" and exit_policy["出口ID"] == "X0":
                        if old_identity(detail) != old_operations[session] or old_identity(logs) != old_logs[session]:
                            raise ValueError("T0_X0と旧31C0の全運用/追尾に差")
                        control.append({"場": session, "候補ID": cid, "全運用同値": True, "全追尾同値": True,
                            "旧識別子全運用内容SHA256": canonical_sha(old_identity(detail)),
                            "旧識別子追尾内容SHA256": canonical_sha(old_identity(logs))})
                    infos[cid].append(info)
                    trades[cid].extend(state.trades)
                    streams["全運用詳細.jsonl.gz"].write(encode(detail))
                    for row in logs:
                        streams["追尾.jsonl.gz"].write(encode(row))
            print(f"00033 {session} 2入口/3運用完了", flush=True)
    if set(all_t0) != set(saved_projection):
        raise ValueError("固定31C0の純入口全集合に差")
    final = {"コードSHA256": code_pins(), "条件SHA256": O.sha(study/"条件.json"),
        "入力台帳SHA256": O.sha(study/"入力台帳.json"), "参照台帳SHA256": O.sha(MANIFEST_PATH),
        "入口参照SHA256": O.sha(study/"入口参照.json")}
    if initial != final:
        raise ValueError("実行中の主版/条件/入力/共有参照変更")
    if prepare_only:
        W.write_json(work/"準備点検.json", {**initial, "ラベル計算": False, "損益計算": False,
            "全66場既使用": True, "旧31C0純信号同値": True, "純信号whitelist": list(SIGNAL_FIELDS),
            "準備": prepared, "共有入口参照": pointer, "T0純信号数": len(all_t0)})
        return {"準備点検": True, "ラベル計算": False, "損益計算": False, "T0純信号数": len(all_t0)}
    entrances, results, ids = [], [], []
    for source in entries:
        sid = source["入口ID"]
        cases = [case_lookup[eid] for eid in selected_ids[sid]]
        entrance = {**source, **{p: E.entry_metrics([r for r in cases if r["期間"] == p], p) for p in PERIODS}}
        support, goal = D.entry_flags(entrance, config)
        entrance.update(入口支持=support, **{"70目標": goal})
        entrances.append(entrance)
        for exit_policy in exits_for(source):
            cid = sid+"_"+exit_policy["出口ID"]
            result = {"候補ID": cid, "入口": source, "出口": exit_policy, "入口支持": support, "70目標": goal,
                "現方針候補": exit_policy["出口ID"] == "XF"}
            for p in PERIODS:
                result[p] = {"入口": entrance[p], "運用": operation_metrics([r for r in infos[cid] if r["期間"] == p],
                    [r for r in trades[cid] if r["期間"] == p], source["役割"], exit_policy)}
            result["費用資格"] = all(W.supported(result[p]["運用"], limits) and result[p]["運用"]["品質注意場数"] == 0
                and result[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
            result["採用資格"] = result["現方針候補"] and goal and result["費用資格"]
            results.append(result)
            ids.append(cid)
    report = {"全66場既使用": True, "入口評価": entrances, "結果": results, "表示固定ID": ids,
        "入口70目標達成数": sum(r["70目標"] for r in entrances), "費用資格数": sum(r["費用資格"] for r in results),
        "入口125250評価の変更": True, "入口評価数": 2, "運用候補数": 3, "現方針運用候補数": 2,
        "現方針費用資格数": sum(r["現方針候補"] and r["費用資格"] for r in results),
        "採用資格数": sum(r["採用資格"] for r in results),
        "先着共有方式": "固定31C0の同時計・同仮価格caseの選別。新要求へ未来値を渡さない",
        "位置付け": "既使用66場で費用後含み益正の起動を適用し、CCI突破へ同時点CLV符号を追加。旧A5は参考。未使用確認ではない"}
    W.write_json(study/"入力品質.json", input_quality)
    W.write_json(study/"T0対照同値.json", {"全件一致": True, "場候補数": len(control), "照合": control,
        "入口参照SHA256": initial["入口参照SHA256"]})
    W.write_csv(study/"全候補_場別.csv", [r for cid in ids for r in infos[cid]])
    E.publish_details(study, work/"全運用詳細.jsonl.gz", ids, manifest, "")
    catalog = W.read_json(study/"一覧.resources.json")
    for resource in catalog["resources"]:
        resource["id"] = resource["id"].replace("00008_", "00033_", 1)
    W.write_json(study/"一覧.resources.json", catalog)
    W.write_json(study/"作業成果物.json", {"原板複製": False, "展開内容SHA256が正本": True,
        "共有入口参照": "入口参照.json", "ファイル": [{"パス": (work/name).relative_to(ROOT).as_posix(),
            "展開内容SHA256": content_sha(work/name), "圧縮SHA256参考": O.sha(work/name),
            "圧縮バイト": (work/name).stat().st_size} for name in FILES]})
    W.write_json(study/"結果.json", report)
    return {"入口数": 2, "運用候補数": 3, "入口70目標達成数": report["入口70目標達成数"],
        "費用資格数": report["費用資格数"], "現方針費用資格数": report["現方針費用資格数"], "採用資格数": report["採用資格数"]}


def main() -> None:
    """純準備又は固定後の正式比較を起動する。

    引数: なし。CLIは--study/--work/--prepare。
    返り値: None。主市場起動はrootが行う。
    """
    parser = argparse.ArgumentParser(description="CCI突破と足内終値位置")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.study.resolve(), args.work.resolve(), args.prepare), ensure_ascii=False))


if __name__ == "__main__":
    main()
