"""固定CCI突破を同時計登録し、30秒指値と180秒指値・到達後回復の価格・機会・損益を比べる。"""

import argparse
from collections import defaultdict
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime
import gzip
import importlib.util
import json
from pathlib import Path
import platform
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00035_CCI突破の到達後回復"
WORK = ROOT/"work/回復監視/00035"
PREVIOUS = ROOT/"study/00034_CCI突破の水準指値"
EXIT_STUDY = ROOT/"study/00033_CCI突破と足内終値位置"
ENTRY_STUDY = ROOT/"study/00031_CCI持続と上位BB幅"
MANIFEST_PATH = ROOT/"study/00028_基準線復帰と上位一目の方向/入力台帳.json"
PERIODS = ("学習", "条件選択", "後続検査")
FILES = ("入口事例.jsonl.gz", "全運用詳細.jsonl.gz", "追尾.jsonl.gz")
CONTROL_ID = "3分_E1_XF"
PREVIOUS_LOCK_SHA = "f4351a3a5cc43a223641bc4c321135c402075266d1e8e3158d101cc6ba8ed879"
RULES = {"登録": "固定31C0の3分前20高安strict終値突破＋現前CCI20実方向100超。M/登録時計/ATRを全案保持",
    "E1": "固定34E1の完全対照。登録+1〜30秒、買ask<=旧R/売bid>=旧Lの最初正常BBO",
    "E2": "同じ固定指値で登録+1〜180秒。延命/差替/後続CCI再判定なし",
    "E3": "登録+1〜180秒で初到達、strict後keyの最初買bid>R/売ask<Lを回復。時間可なら市場要求、+1秒以降の最初正常BBO",
    "回復時時間": "cutoff/forceより前、残60分以上、回復+1<=元登録+180。最初回復が不可でも後で取り直さない",
    "絶対期限": "E3も元登録+180を固定。回復要求からTTLを再始動しない。新規fillは期限等号可、cutoff/force等号不可",
    "単一予約": "E3は実監視一件、監視中/注文待機中/保有中の後続登録を記録して消費抑止。監視と実注文を区別",
    "先着": "各登録の仮監視は独立。各案の仮新規BBOから125/250を新計算。30分間引きは元登録時計",
    "費用": "固定33XFの現在費用後strict正で起動。参照往復122円、名目同値床。0/5/10は同約定費用負荷",
    "限界": "単発回復は支持持続を証明しない。価格時計は受信時計でない。価格/選別/待機/占有の方針差"}


def module(path: Path, name: str) -> Any:
    """固定コードをCLI起動せず読み込む。

    引数: path(Path)はコード、name(str)は識別名。
    返り値: Anyはモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


S = module(ROOT/"scripts/終値位置/検証.py", "回復監視の固定33参照")
D, W, E, O = S.D, S.W, S.E, S.O
I = module(Path(__file__).with_name("入口.py"), "回復監視の純登録と先着")
ENGINE = module(Path(__file__).with_name("運用.py"), "回復監視の新規条件")
OLD_CONFIG = S.OLD_CONFIG
canonical_sha, compressed, content_sha = I.canonical_sha, S.compressed, S.content_sha


def expected_config() -> dict:
    """固定33の費用後起動を保った三入口条件を作る。

    引数: なし。
    返り値: dictは事前三案と費用・支持・時刻条件。
    """
    previous = W.read_json(EXIT_STUDY/"条件.json")
    value = {key: deepcopy(previous[key]) for key in D.I.CORE_KEYS}
    value["出口"] = [{"出口ID": "XF"}]
    value["必須追尾"].pop("旧X0起動幅pt", None)
    value.update(版=1, 全66場既使用=True, 戦略=list(I.POLICIES), 到達後回復=deepcopy(RULES), カタログ版=2,
        入口条件参照={"パス": "../00031_CCI持続と上位BB幅/条件.json", "SHA256": O.sha(ENTRY_STUDY/"条件.json")},
        運用条件参照={"パス": "../00033_CCI突破と足内終値位置/条件.json", "SHA256": O.sha(EXIT_STUDY/"条件.json")},
        表示代表="3分_E1_XF/3分_E2_XF/3分_E3_XF", 入口評価数=3, 運用候補数=3,
        現方針候補出口=["XF"], 入口125250評価の変更=True,
        出口定義={"XF": "固定33現在費用後strict正/入口ATR固定D/最低名目同値・非緩和"})
    return value


def validate_config(config: dict) -> None:
    """固定三案以外の閾値や注文条件を拒否する。

    引数: config(dict)は35条件。
    返り値: None。不一致は例外。
    """
    if config != expected_config():
        raise ValueError("固定35条件に差")


def code_pins() -> dict:
    """新主三コードを指紋化する。

    引数: なし。
    返り値: dictはROOT相対パスとSHA256。
    """
    return {p.relative_to(ROOT).as_posix(): O.sha(p) for p in
        (Path(__file__), Path(__file__).with_name("入口.py"), Path(__file__).with_name("運用.py"))}


def rename(value: object, old: str, new: str) -> object:
    """候補とイベント識別子だけを変換して旧対照へ接続する。

    引数: value(object)はJSON値、old/new(str)は識別子断片。
    返り値: objectは価格・金額・時点を変えない変換値。
    """
    if isinstance(value, dict):
        return {k: rename(v, old, new) for k, v in value.items()}
    if isinstance(value, list):
        return [rename(v, old, new) for v in value]
    return value.replace(old, new) if isinstance(value, str) else value


def sources(config: dict) -> list[dict]:
    """固定した寿命延長/回復の三入口を列挙する。

    引数: config(dict)は条件。
    返り値: list[dict]は表示・運用定義。結果で候補選択しない。
    """
    validate_config(config)
    return [{"入口ID": "3分_"+p, "戦略": p, "時間足分": 3, "名称": p,
        "役割": "順行", "複合本命": True} for p in I.POLICIES]


def manifest_for(study: Path, config: dict) -> dict:
    """既使用66場の固定台帳だけを解決する。

    引数: study(Path)は35、config(dict)は条件。
    返り値: dictは既存キャッシュ参照。新原板を列挙しない。
    """
    validate_config(config)
    pointer = W.read_json(study/"入力台帳.json")
    if (study/pointer["参照"]).resolve() != MANIFEST_PATH.resolve() or pointer["SHA256"] != O.sha(MANIFEST_PATH):
        raise ValueError("固定66場参照だけ")
    return D.manifest_for(ENTRY_STUDY, OLD_CONFIG)


def validate_control_reference(study: Path) -> dict:
    """旧34対照の固定・証明・運用と追尾を現在指紋で照合する。

    引数: study(Path)は35保存先。
    返り値: dictは小型対照参照。旧明細を複製しない。
    """
    ref = W.read_json(study/"対照参照.json")
    if ref["参照試行"] != "00034" or ref["候補ID"] != CONTROL_ID or ref["大明細複製"] is not False:
        raise ValueError("旧34E1XFだけを対照とします")
    if ref["旧固定SHA256"] != PREVIOUS_LOCK_SHA or O.sha(PREVIOUS/"固定.json") != PREVIOUS_LOCK_SHA:
        raise ValueError("旧34固定版に差")
    if set(ref["文書と証明"]) != {"固定.json", "条件.json", "結果.json", "作業成果物.json",
            "独立監査.json", "状態独立確認.json", "追尾独立確認.json", "入力台帳.json"}:
        raise ValueError("旧34対照の全証明が必要")
    for name, item in ref["文書と証明"].items():
        if (ROOT/item["パス"]).resolve() != (PREVIOUS/name).resolve() or O.sha(ROOT/item["パス"]) != item["SHA256"]:
            raise ValueError("旧対照の文書又は証明に差")
    expected = [r for r in W.read_json(PREVIOUS/"作業成果物.json")["ファイル"]
        if Path(r["パス"]).name in FILES]
    if ref["共有明細"] != expected or len(expected) != 3:
        raise ValueError("旧対照明細は固定34の三系列だけ")
    for item in expected:
        if O.sha(ROOT/item["パス"]) != item["圧縮SHA256参考"]:
            raise ValueError("旧対照明細に差")
    return ref


def build_session(entry: dict, manifest: dict, banks: dict, config: dict) -> dict:
    """元C0の純再構成から同時計の三登録を作る。

    引数: entry/manifest/config(dict)は入力と条件、banks(dict)は固定31数値銀行。
    返り値: dictは先着・注文・損益を計算しない場材料。
    """
    validate_config(config)
    return I.select(D.build_session(entry, manifest, banks, OLD_CONFIG))


def validate_independent(study: Path, work: Path) -> dict:
    """独立準備の成功と現在の主・条件・入力へのbindを必須にする。

    引数: study/work(Path)は35保存先。
    返り値: dictは独立準備proof。古版や差を拒否する。
    """
    proof = W.read_json(work/"独立準備点検.json")
    expected = {"全件一致": True, "不一致数": 0, "不一致": [], "ラベル計算": False, "損益計算": False,
        "主準備SHA256": O.sha(work/"準備点検.json"), "主コードSHA256": code_pins(),
        "条件SHA256": O.sha(study/"条件.json"), "入力台帳SHA256": O.sha(study/"入力台帳.json"),
        "参照入力台帳SHA256": O.sha(MANIFEST_PATH), "入口参照SHA256": O.sha(study/"入口参照.json"),
        "対照参照SHA256": O.sha(study/"対照参照.json"), "コードSHA256": O.sha(Path(__file__).with_name("状態独立確認.py")),
        "追尾コードSHA256": O.sha(Path(__file__).with_name("追尾独立確認.py"))}
    if any(proof.get(k) != v for k, v in expected.items()):
        raise ValueError("独立非PnL準備の現在版bind又は成功に差")
    dependencies = proof.get("依存コードSHA256")
    if not isinstance(dependencies, dict) or not dependencies:
        raise ValueError("独立依存指紋が必要")
    if any(not (ROOT/n).resolve().is_relative_to(ROOT.resolve()) or O.sha(ROOT/n) != h for n, h in dependencies.items()):
        raise ValueError("独立依存に差")
    return proof


def freeze(study: Path, work: Path) -> dict:
    """準備・人工・共有先を照合し、正式計算前に全出典を固定する。

    引数: study/work(Path)は35保存先。
    返り値: dictは固定。既存結果や不一致固定は上書きしない。
    """
    if (study/"結果.json").exists():
        raise ValueError("既存結果は上書きしません")
    reference, control = S.validate_entry_reference(study), validate_control_reference(study)
    prepared = W.read_json(work/"準備点検.json")
    expected = {"コードSHA256": code_pins(), "条件SHA256": O.sha(study/"条件.json"),
        "入力台帳SHA256": O.sha(study/"入力台帳.json"), "参照台帳SHA256": O.sha(MANIFEST_PATH),
        "入口参照SHA256": O.sha(study/"入口参照.json"), "対照参照SHA256": O.sha(study/"対照参照.json"),
        "旧31C0純登録同値": True, "ラベル計算": False, "損益計算": False}
    if any(prepared.get(k) != v for k, v in expected.items()):
        raise ValueError("主準備の現在版又は非PnLに差")
    independent = validate_independent(study, work)
    synthetic_path = ROOT/"work/回復監視/合成検証.json"
    synthetic = W.read_json(synthetic_path)
    if synthetic.get("全件成功") is not True or synthetic.get("合成編集終了") is not True:
        raise ValueError("最終人工の成功前には固定しません")
    previous_lock = PREVIOUS/"固定.json"
    pins = dict(W.read_json(previous_lock)["ファイルSHA256"])
    if any(O.sha(ROOT/n) != h for n, h in pins.items()):
        raise ValueError("旧固定参照に差")
    paths = [Path(__file__), *[Path(__file__).with_name(n) for n in
        ("入口.py", "運用.py", "合成検証.py", "状態独立確認.py", "追尾独立確認.py")], previous_lock,
        *[study/n for n in ("計画.md", "条件.json", "入力台帳.json", "入口参照.json", "対照参照.json")],
        *[work/n for n in ("準備点検.json", "独立準備点検.json", "診断予定.json")], synthetic_path,
        ROOT/"work/次入口候補35.md", ROOT/"work/回復確認35の記録案.md"]
    for ref in (reference, control):
        paths.extend(ROOT/r["パス"] for r in ref["文書と証明"].values())
        paths.extend(ROOT/r["パス"] for r in ref["共有明細"])
    paths.extend(ROOT/n for n in independent["依存コードSHA256"])
    for path in paths:
        pins[path.relative_to(ROOT).as_posix()] = O.sha(path)
    for path in (Path(__file__), Path(__file__).with_name("入口.py"), Path(__file__).with_name("運用.py"),
                 Path(__file__).with_name("合成検証.py"), study/"条件.json"):
        if synthetic.get("ファイルSHA256", {}).get(path.relative_to(ROOT).as_posix()) != O.sha(path):
            raise ValueError("最終人工の主版bindに差")
    for key, name in (("独立数値補助SHA256", "状態独立確認.py"), ("独立追尾補助SHA256", "追尾独立確認.py")):
        if synthetic.get(key) != O.sha(Path(__file__).with_name(name)):
            raise ValueError("最終人工の独立版bindに差")
    locked = {"固定日時": datetime.now().astimezone().isoformat(), "ファイルSHA256": dict(sorted(pins.items())),
        "主準備SHA256": O.sha(work/"準備点検.json"), "独立準備SHA256": O.sha(work/"独立準備点検.json"),
        "全66場既使用": True, "Python": platform.python_version(), "NumPy": W.np.__version__}
    if (study/"固定.json").exists():
        existing = W.read_json(study/"固定.json")
        if existing["ファイルSHA256"] != locked["ファイルSHA256"]:
            raise ValueError("固定後出典変更")
        return existing
    W.write_json(study/"固定.json", locked)
    return locked


# ----------------------------------------
# 主準備は純登録だけ。正式時に初めて仮新規ラベルと単一建玉運用を計算する。

def run(study: Path, work: Path, prepare_only: bool) -> dict:
    """同C0登録の寿命延長/回復を準備又は固定後に三案再生する。

    引数: study/work(Path)は保存先、prepare_only(bool)は非PnL準備。
    返り値: dictは完了要約。市場起動はrootが行う。
    """
    config = W.read_json(study/"条件.json")
    validate_config(config)
    manifest = manifest_for(study, config)
    reference, control_ref = S.validate_entry_reference(study), validate_control_reference(study)
    entries = sources(config)
    work.mkdir(parents=True, exist_ok=True)
    initial = {"コードSHA256": code_pins(), "条件SHA256": O.sha(study/"条件.json"),
        "入力台帳SHA256": O.sha(study/"入力台帳.json"), "参照台帳SHA256": O.sha(MANIFEST_PATH),
        "入口参照SHA256": O.sha(study/"入口参照.json"), "対照参照SHA256": O.sha(study/"対照参照.json")}
    if not prepare_only:
        if any((work/n).exists() for n in FILES):
            raise ValueError("既存正式明細は上書きしません")
        freeze(study, work)
    shared_cases = S.S.load_shared_cases(reference)["3分_C0"]
    old_pure = {r["イベントID"]: S.S.pure_signal(r) for r in shared_cases}
    del shared_cases
    previous_details, previous_logs, previous_cases = {}, defaultdict(list), {}
    if not prepare_only:
        for item in control_ref["共有明細"]:
            with gzip.open(ROOT/item["パス"], "rt", encoding="utf-8") as stream:
                for line in stream:
                    row = json.loads(line)
                    if Path(item["パス"]).name == "入口事例.jsonl.gz":
                        if row["入口ID"] == "3分_E1":
                            previous_cases[row["イベントID"]] = row
                        continue
                    if row["候補ID"] != CONTROL_ID:
                        continue
                    if Path(item["パス"]).name == "全運用詳細.jsonl.gz":
                        previous_details[row["場"]] = row
                    else:
                        previous_logs[row["場"]].append(row)
    banks = {n: D.J.NumericBank(n) for n in (3, 15)}
    prepared, inputs, controls, all_old = [], [], [], {}
    cases, infos, trades = defaultdict(list), defaultdict(list), defaultdict(list)
    encode = lambda row: json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False)+"\n"
    with ExitStack() as stack:
        streams = {n: stack.enter_context(compressed(work/n)) for n in FILES} if not prepare_only else {}
        for entry in manifest["entries"]:
            session, period = entry["session"], E.phase_of(entry["session"], config)
            block = build_session(entry, manifest, banks, config)
            pure = [r for source in entries for r in block["signals"][source["入口ID"]]]
            for row in block["signals"]["3分_E1"]:
                old = rename({k: row[k] for k in I.BASE_FIELDS}, "_E1", "_C0")
                if old != old_pure.get(old["イベントID"]):
                    raise ValueError("旧31C0の純登録に差")
                all_old[old["イベントID"]] = old
            inputs.append({"期間": period, **block["input_quality"]})
            record = {"場": session, "期間": period, "純信号": pure,
                "純信号内容SHA256": canonical_sha(pure), "純信号判断SHA256": canonical_sha([S.S.decision_signal(r) for r in pure]),
                "登録台帳": block["registrations"], "登録内容SHA256": canonical_sha(block["registrations"]),
                "原P判定SHA256": canonical_sha(S.S.raw_projection(block["quality"]["全Q発動記録"])), "入力品質": block["input_quality"]}
            path = I.入口経路([q for q in block["events"] if q.valid])
            observations = [{"イベントID": q["イベントID"], "入口ID": q["入口ID"],
                "回復観測": path.observation(q, block["cutoff"], block["deadline"])} for q in block["signals"]["3分_E3"]]
            record.update(仮監視観測=observations, 仮監視観測SHA256=canonical_sha(observations))
            if prepare_only:
                prepared.append(record)
                print(f"00035 {session} C0同登録/固定水準の純準備のみ", flush=True)
                continue
            anchors = {r["旧C0イベントID"]: r for r in block["registrations"]}
            for source in entries:
                sid, policy = source["入口ID"], source["戦略"]
                signals = block["signals"][sid]
                for signal in signals:
                    old_id = signal["イベントID"][:-3]+"_C0"
                    label = path.evaluate_signal(signal, block["cutoff"], block["deadline"], policy)
                    case = {**deepcopy(signal), "期間": period, "要求時計JST": O.iso(signal["要求時計秒"]),
                        "旧C0イベントID": old_id, "登録出典": deepcopy(anchors[old_id]), **label}
                    if policy == "E3":
                        observation = path.observation(signal, block["cutoff"], block["deadline"])
                        case.update(回復観測=observation, 新規要求時計秒=observation["新規要求時計秒"], 新規要求原板行=observation["新規要求原板行"])
                    if policy == "E1" and case != previous_cases[case["イベントID"]]:
                        raise ValueError("固定34E1先着case全列に差")
                    cases[sid].append(case)
                    streams["入口事例.jsonl.gz"].write(encode(case))
                cid = sid+"_XF"
                state, info = ENGINE.replay(block["events"], signals, block["frames"][3], session,
                    cid, config["運用"], config["出口"][0], source["役割"])
                info.update(期間=period, 場時間分=block["duration"])
                for trade in state.trades:
                    trade["期間"] = period
                detail = {"候補ID": cid, "場": session, "品質": info, "約定": state.fills,
                    "取引": state.trades, "注文": state.orders, "入口取扱": state.signals}
                if policy == "E3":
                    detail["監視記録"] = state.watch_records
                logs = [{"期間": period, **r} for r in state.normal_log]
                if policy == "E1":
                    adapted, adapted_logs = detail, logs
                    if adapted != previous_details[session] or adapted_logs != previous_logs[session]:
                        raise ValueError("E1XFが旧34の全属性対照と不一致")
                    controls.append({"場": session, "候補ID": cid, "全運用同値": True, "全追尾同値": True,
                        "旧識別子全運用内容SHA256": canonical_sha(adapted), "旧識別子追尾内容SHA256": canonical_sha(adapted_logs)})
                infos[cid].append(info)
                trades[cid].extend(state.trades)
                streams["全運用詳細.jsonl.gz"].write(encode(detail))
                for row in logs:
                    streams["追尾.jsonl.gz"].write(encode(row))
            print(f"00035 {session} 寿命/回復の3入口3運用完了", flush=True)
    if set(all_old) != set(old_pure):
        raise ValueError("C0純登録の全集合に差")
    current = {"コードSHA256": code_pins(), "条件SHA256": O.sha(study/"条件.json"),
        "入力台帳SHA256": O.sha(study/"入力台帳.json"), "参照台帳SHA256": O.sha(MANIFEST_PATH),
        "入口参照SHA256": O.sha(study/"入口参照.json"), "対照参照SHA256": O.sha(study/"対照参照.json")}
    if initial != current:
        raise ValueError("実行中の主版/条件/入力/参照変更")
    if prepare_only:
        W.write_json(work/"準備点検.json", {**initial, "ラベル計算": False, "損益計算": False,
            "全66場既使用": True, "旧31C0純登録同値": True, "純信号whitelist": I.SIGNAL_FIELDS,
            "準備": prepared, "原C0登録数": len(all_old)})
        return {"準備点検": True, "ラベル計算": False, "損益計算": False, "原C0登録数": len(all_old)}

    # ----------------------------------------
    # 仮参加の三先着評価と、単一建玉の実会計を別の分母で集計する。

    entrances, results, ids = [], [], []
    for source in entries:
        sid, cid = source["入口ID"], source["入口ID"]+"_XF"
        entrance = {**source, **{p: E.entry_metrics([r for r in cases[sid] if r["期間"] == p], p) for p in PERIODS}}
        support, goal = D.entry_flags(entrance, config)
        entrance.update(入口支持=support, **{"70目標": goal})
        entrances.append(entrance)
        result = {"候補ID": cid, "入口": source, "出口": config["出口"][0], "入口支持": support,
            "70目標": goal, "現方針候補": True}
        for p in PERIODS:
            result[p] = {"入口": entrance[p], "運用": S.operation_metrics([r for r in infos[cid] if r["期間"] == p],
                [r for r in trades[cid] if r["期間"] == p], source["役割"], config["出口"][0])}
        result["費用資格"] = all(W.supported(result[p]["運用"], limits) and result[p]["運用"]["品質注意場数"] == 0
            and result[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        result["採用資格"] = goal and result["費用資格"]
        results.append(result)
        ids.append(cid)
    report = {"全66場既使用": True, "入口評価": entrances, "結果": results, "表示固定ID": ids,
        "入口評価数": 3, "運用候補数": 3, "現方針運用候補数": 3, "入口125250評価の変更": True,
        "入口70目標達成数": sum(r["70目標"] for r in entrances), "費用資格数": sum(r["費用資格"] for r in results),
        "現方針費用資格数": sum(r["費用資格"] for r in results), "採用資格数": sum(r["採用資格"] for r in results),
        "位置付け": "同じ既使用66場のC0登録で30秒指値/180秒指値/180秒到達後回復を比較。選別・価格・時計・単一監視占有を含む方針差"}
    W.write_json(study/"入力品質.json", inputs)
    W.write_json(study/"E1対照同値.json", {"全件一致": True, "旧先着全件同値": True,
        "場候補数": len(controls), "照合": controls, "対照参照SHA256": initial["対照参照SHA256"]})
    W.write_csv(study/"全候補_場別.csv", [r for cid in ids for r in infos[cid]])
    E.publish_details(study, work/"全運用詳細.jsonl.gz", ids, manifest, "")
    catalog = W.read_json(study/"一覧.resources.json")
    for resource in catalog["resources"]:
        resource["id"] = resource["id"].replace("00008_", "00035_", 1)
    W.write_json(study/"一覧.resources.json", catalog)
    W.write_json(study/"作業成果物.json", {"原板複製": False, "展開内容SHA256が正本": True,
        "共有参照": ["入口参照.json", "対照参照.json"], "ファイル": [{"パス": (work/n).relative_to(ROOT).as_posix(),
            "展開内容SHA256": content_sha(work/n), "圧縮SHA256参考": O.sha(work/n), "圧縮バイト": (work/n).stat().st_size} for n in FILES]})
    W.write_json(study/"結果.json", report)
    return {k: report[k] for k in ("入口評価数", "運用候補数", "入口70目標達成数", "費用資格数", "採用資格数")}


def main() -> None:
    """純準備又は固定後の正式三案比較を起動する。

    引数: なし。CLIは--study/--work/--prepare。
    返り値: None。市場起動担当はroot。
    """
    parser = argparse.ArgumentParser(description="CCI突破の固定水準指値")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.study.resolve(), args.work.resolve(), args.prepare), ensure_ascii=False))


if __name__ == "__main__":
    main()
