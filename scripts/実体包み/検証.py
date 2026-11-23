"""二足の実体包みとMACDを新入口とし、前平均の準備・進行位置を比較する。"""

import argparse
from collections import defaultdict
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime
import importlib.util
import json
import math
from pathlib import Path
import platform
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00046_二足の実体包みと平均進行"
WORK = ROOT/"work/実体包み/00046"
PREVIOUS = ROOT/"study/00045_確定スイング突破と方向優勢"
PREVIOUS_LOCK_SHA = "db48bcd65c84319000098f2b82271b44c705b1e1dfd6c7468b112e8e79589ddd"
NUMERIC_STUDY = ROOT/"study/00029_BB内復帰とOBV非追随"
EXIT_STUDY = ROOT/"study/00033_CCI突破と足内終値位置"
MANIFEST_PATH = ROOT/"study/00028_基準線復帰と上位一目の方向/入力台帳.json"
PERIODS = ("学習", "条件選択", "後続検査")
FILES = ("全指標.jsonl.gz", "発動判定.jsonl.gz", "入口事例.jsonl.gz", "全運用詳細.jsonl.gz", "追尾.jsonl.gz")
OPERATION_PAIRS = (("B0", "XF"), ("B1", "XF"), ("B2", "XF"))


def module(path: Path, name: str) -> Any:
    """固定補助をCLI起動せず読む。

    引数: path(Path)はコード、name(str)は一意な読込名。
    返り値: Anyはモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


C = module(ROOT/"scripts/回帰突破/検証.py", "実体包みの固定41共通保存")
D, S, W, E, O = C.D, C.S, C.W, C.E, C.O
I = module(Path(__file__).with_name("入口.py"), "実体包みの新価格発動")
J = I.J
ENGINE = module(Path(__file__).with_name("運用.py"), "実体包みの固定33出口")
OLD_CONFIG = W.read_json(PREVIOUS/"条件.json")
canonical_sha, compressed, content_sha = I.canonical_sha, C.compressed, C.content_sha
RULES, decision_signal = I.RULES, C.decision_signal
decision_projection = C.decision_projection
shared_path, read_rows = C.shared_path, C.read_rows


def expected_config() -> dict:
    """新しい複合入口三案を既定の評価尺度とXFへ接続する。

    引数: なし。
    返り値: dictはB0/B1/B2、全XF、固定した支持・費用・125/250。
    """
    value = {k: deepcopy(OLD_CONFIG[k]) for k in D.I.CORE_KEYS}
    fee = W.read_json(EXIT_STUDY/"条件.json")
    value.update(運用=deepcopy(fee["運用"]), 必須追尾=deepcopy(fee["必須追尾"]), 版=1,
        全66場既使用=True, 戦略=list(I.POLICIES), 実体包み=deepcopy(RULES), カタログ版=4,
        出口=[{"出口ID": "XF"}], 運用組合せ=[{"戦略": p, "出口ID": x} for p, x in OPERATION_PAIRS],
        指標条件参照={"パス": "../00029_BB内復帰とOBV非追随/条件.json", "SHA256": O.sha(NUMERIC_STUDY/"条件.json")},
        運用条件参照={"パス": "../00033_CCI突破と足内終値位置/条件.json", "SHA256": O.sha(EXIT_STUDY/"条件.json")},
        現方針候補出口=["XF"], 入口評価数=3, 運用候補数=3,
        表示代表="B0二足実体包みとヒスト差/B1前平均準備/B2前平均進行位置切替",
        出口定義={"XF": "固定33現在費用後strict正・要求jATR固定D・最低名目entry床"})
    return value


def validate_config(config: dict) -> None:
    """新母集団と三案・評価尺度の変更を拒否する。

    引数: config(dict)は46条件。
    返り値: None。不一致は例外。
    """
    if config != expected_config():
        raise ValueError("固定46条件に差")


def code_pins() -> dict:
    """主接続・新指標・価格発動・固定出口の版を返す。

    引数: なし。
    返り値: dictは相対パスとSHA256。
    """
    return {p.relative_to(ROOT).as_posix(): O.sha(p) for p in
        (Path(__file__), *[Path(__file__).with_name(n) for n in ("入口.py", "指標.py", "運用.py")])}


def sources(config: dict) -> list[dict]:
    """事前の二反転入口と一切替入口を列挙する。

    引数: config(dict)は条件。
    返り値: list[dict]は三候補の表示定義。
    """
    validate_config(config)
    return [{"入口ID": "3分_"+p, "戦略": p, "時間足分": 3, "名称": p,
        "役割": I.ROLES[p], "複合本命": True} for p in I.POLICIES]


def manifest_for(study: Path, config: dict) -> dict:
    """既使用NK66の固定台帳だけを解決する。

    引数: study(Path)は46、config(dict)は条件。
    返り値: dictは原板の複製を含まない旧台帳。
    """
    validate_config(config)
    pointer = W.read_json(study/"入力台帳.json")
    if (study/pointer["参照"]).resolve() != MANIFEST_PATH.resolve() or pointer["SHA256"] != O.sha(MANIFEST_PATH):
        raise ValueError("固定28のNK66だけ")
    return D.manifest_for(PREVIOUS, OLD_CONFIG)


def validate_reference(study: Path, name: str = "指標参照.json") -> dict:
    """旧29の価格・ATR/ヒスト正本を内容指紋と証明まで照合する。

    引数: study(Path)は46、name(str)は指標参照.jsonだけ。
    返り値: dictは検査済み参照。旧入口/先着/運用は転用しない。
    """
    return C.validate_reference(study, name)


def read_bundle(study: Path) -> dict:
    """固定29の価格/ATR/ヒスト15列から、当場の前平均を作る。

    引数: study(Path)は46。
    返り値: dictはlower/numeric/numeric_quality。旧入口/label/運用は含まない。
    """
    shared = C.read_bundle(study)
    lower = {session: [J.frame_projection(row) for row in rows] for session, rows in shared["lower"].items()}
    numeric, quality = {}, {}
    for session, rows in lower.items():
        numeric[session], quality[session] = J.build(rows, session)
    return {"lower": lower, "numeric": numeric, "numeric_quality": quality}


def build_session(entry: dict, manifest: dict, bundle: dict, config: dict, include_events: bool = False) -> dict:
    """二足Pと前平均の採否を作り、正式の場合だけNK執行気配を読む。

    引数: entry/manifest/bundle/config(dict)は入力/数値/条件、include_events(bool)は正式のみ真。
    返り値: dictは三純信号/全二足P/全数値/必要時気配。
    """
    validate_config(config)
    session = entry["session"]
    source = Path(manifest["source_root"])/entry["source_path"]
    cache = (ROOT/"work/複合検証"/entry["cache_path"]).resolve()
    stat = source.stat()
    if not cache.is_relative_to((ROOT/"work").resolve()) or (stat.st_size, stat.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]) or O.sha(cache) != entry["sha256_cache"]:
        raise ValueError("予約NK原板/cacheに差")
    begin, finish, cutoff, deadline = W.OLD.shared.legacy.session_times(session)
    start, end = begin.timestamp(), finish.timestamp()
    frames = bundle["numeric"][session]
    block = I.generate(frames, session, cutoff.timestamp(), deadline.timestamp(), config)
    block["signals"] = {sid: [I.pure_signal(row, sid[3:]) for row in rows] for sid, rows in block["signals"].items()}
    block.update(frames={3: frames}, input_quality=deepcopy(block["quality"]), cutoff=cutoff.timestamp(),
        deadline=deadline.timestamp(), duration=(end-start)/60, events=[])
    if include_events:
        previous_now = -math.inf
        for event in W.PREP.read_events(cache):
            if math.isfinite(event.now) and start <= event.now <= end and event.now >= previous_now:
                block["events"].append(event)
                previous_now = event.now
    return block


def current_bindings(study: Path) -> dict:
    """主四コード・条件・入力・共有数値の指紋を返す。

    引数: study(Path)は46。
    返り値: dictは実行中固定出典。
    """
    return {"コードSHA256": code_pins(), "条件SHA256": O.sha(study/"条件.json"),
        "入力台帳SHA256": O.sha(study/"入力台帳.json"), "参照台帳SHA256": O.sha(MANIFEST_PATH),
        "指標参照SHA256": O.sha(study/"指標参照.json")}


def validate_independent(study: Path, work: Path) -> dict:
    """原8列からの二実体/前平均/H/ATR独立準備成功を要求する。

    引数: study/work(Path)は46保存先。
    返り値: dictは現在版へ接続した非損益証明。
    """
    proof = W.read_json(work/"独立準備点検.json")
    expected = {"全件一致": True, "不一致数": 0, "不一致": [], "ラベル計算": False, "損益計算": False,
        "主準備SHA256": O.sha(work/"準備点検.json"), "主コードSHA256": code_pins(),
        "条件SHA256": O.sha(study/"条件.json"), "入力台帳SHA256": O.sha(study/"入力台帳.json"),
        "参照入力台帳SHA256": O.sha(MANIFEST_PATH), "指標参照SHA256": O.sha(study/"指標参照.json"),
        "コードSHA256": O.sha(Path(__file__).with_name("状態独立確認.py")),
        "追尾コードSHA256": O.sha(Path(__file__).with_name("追尾独立確認.py"))}
    if any(proof.get(k) != v for k, v in expected.items()):
        raise ValueError("46独立準備の成功/現在版に差")
    if not proof.get("依存コードSHA256") or any(O.sha(ROOT/n) != h for n, h in proof["依存コードSHA256"].items()):
        raise ValueError("独立依存に差")
    return proof


def freeze(study: Path, work: Path) -> dict:
    """旧537指紋を継承し新母集団・主独立・最終人工を結果前に固定する。

    引数: study/work(Path)は46保存先。
    返り値: dictは固定記録。既存結果と異版上書きを拒否する。
    """
    if (study/"結果.json").exists():
        raise ValueError("既存結果を上書きしません")
    validate_reference(study)
    prepared = W.read_json(work/"準備点検.json")
    if any(prepared.get(k) != v for k, v in current_bindings(study).items()) or prepared["ラベル計算"] or prepared["損益計算"]:
        raise ValueError("主非損益準備と現在版に差")
    independent = validate_independent(study, work)
    synthetic_path = ROOT/"work/実体包み/合成検証.json"
    synthetic = W.read_json(synthetic_path)
    if any(synthetic.get(k) is not True for k in ("全件成功", "合成編集終了", "実行中code不変")):
        raise ValueError("最終人工成功前")
    for p in [Path(__file__), *[Path(__file__).with_name(n) for n in ("入口.py", "指標.py", "運用.py", "合成検証.py")], study/"条件.json"]:
        if synthetic.get("ファイルSHA256", {}).get(p.relative_to(ROOT).as_posix()) != O.sha(p):
            raise ValueError("最終人工の主版に差")
    for key, name in (("独立数値補助SHA256", "状態独立確認.py"), ("独立追尾補助SHA256", "追尾独立確認.py")):
        if synthetic.get(key) != O.sha(Path(__file__).with_name(name)):
            raise ValueError("最終人工の独立版に差")
    finance = W.read_json(work/"会計人工接続.json")
    if finance.get("全件一致") is not True or finance.get("不一致数") != 0 or finance.get("人工経路数") != 8 or finance.get("実行中code不変") is not True:
        raise ValueError("会計人工接続前")
    required = {"scripts/実体包み/独立監査.py", "scripts/実体包み/運用.py", "work/実体包み/00046/会計人工接続.py"}
    if not required <= set(finance.get("コードSHA256", {})) or finance.get("条件SHA256") != O.sha(study/"条件.json"):
        raise ValueError("会計人工の必須出典/条件不足")
    if any(O.sha(ROOT/n) != h for n, h in finance["コードSHA256"].items()):
        raise ValueError("会計人工の現在版に差")
    if O.sha(PREVIOUS/"固定.json") != PREVIOUS_LOCK_SHA:
        raise ValueError("固定45に差")
    pins = dict(W.read_json(PREVIOUS/"固定.json")["ファイルSHA256"])
    if any(O.sha(ROOT/n) != h for n, h in pins.items()):
        raise ValueError("旧出典変更")
    paths = [Path(__file__), *[Path(__file__).with_name(n) for n in ("入口.py", "指標.py", "運用.py", "合成検証.py", "状態独立確認.py", "追尾独立確認.py", "独立監査.py")],
        *[study/n for n in ("計画.md", "条件.json", "入力台帳.json", "指標参照.json")],
        *[work/n for n in ("準備点検.json", "独立準備点検.json", "診断予定.json", "会計人工接続.json", "会計人工接続.py")],
        synthetic_path, PREVIOUS/"固定.json", ROOT/"work/次研究46の独立案.md",
        ROOT/"docs/technical-analysis/指標/二足の実体包み.md", ROOT/"scripts/レポート/手法カタログ_版4.json"]
    paths.extend(ROOT/n for n in independent["依存コードSHA256"])
    ref = W.read_json(study/"指標参照.json")
    paths.extend(ROOT/r["パス"] for r in ref["文書と証明"].values())
    paths.extend(ROOT/r["パス"] for r in ref["共有明細"])
    pins.update({p.relative_to(ROOT).as_posix(): O.sha(p) for p in paths})
    value = {"固定日時": datetime.now().astimezone().isoformat(), "ファイルSHA256": dict(sorted(pins.items())),
        "主準備SHA256": O.sha(work/"準備点検.json"), "独立準備SHA256": O.sha(work/"独立準備点検.json"),
        "全66場既使用": True, "Python": platform.python_version(), "NumPy": W.np.__version__}
    if (study/"固定.json").exists():
        previous = W.read_json(study/"固定.json")
        if previous["ファイルSHA256"] != value["ファイルSHA256"]:
            raise ValueError("固定後出典変更")
        return previous
    W.write_json(study/"固定.json", value)
    return value


# ----------------------------------------
# 準備は新二足P・ヒスト差・前平均のみ。正式で新先着と三運用を計算する。

def run(study: Path, work: Path, prepare_only: bool) -> dict:
    """二足包みの基準/前平均準備/進行位置の三案を純準備又は固定後三運用で比較する。

    引数: study/work(Path)は46の保存先、prepare_only(bool)は非PnL準備。
    返り値: dictは完了要約。市場起動はrootだけが行う。
    """
    config = W.read_json(study/"条件.json")
    manifest, entries = manifest_for(study, config), sources(config)
    validate_reference(study)
    initial = current_bindings(study)
    work.mkdir(parents=True, exist_ok=True)
    if prepare_only and ((work/"準備点検.json").exists() or (study/"結果.json").exists()
                         or any((work/name).exists() for name in FILES)):
        raise ValueError("既存の準備又は正式成果物を上書きしません")
    if not prepare_only:
        if any((work/n).exists() for n in FILES):
            raise ValueError("正式明細は上書きしません")
        freeze(study, work)
    bundle = read_bundle(study)
    prepared, inputs = [], []
    cases, infos, trades = defaultdict(list), defaultdict(list), defaultdict(list)
    with ExitStack() as stack:
        streams = {n: stack.enter_context(compressed(work/n)) for n in FILES} if not prepare_only else {}
        for entry in manifest["entries"]:
            session, period = entry["session"], E.phase_of(entry["session"], config)
            block = build_session(entry, manifest, bundle, config, not prepare_only)
            pure = [r for p in I.POLICIES for r in block["signals"]["3分_"+p]]
            record = {"場": session, "期間": period, "純信号": pure, "純信号内容SHA256": canonical_sha(pure),
                "純信号判断SHA256": canonical_sha([decision_signal(r) for r in pure]),
                "判定": block["decisions"], "判定SHA256": canonical_sha(block["decisions"]),
                "判定判断SHA256": canonical_sha(decision_projection(block["decisions"])),
                "全3分投影SHA256": canonical_sha([I.frame_projection(r) for r in bundle["lower"][session]]), "3分投影足数": len(bundle["lower"][session]), "入力品質": block["input_quality"],
                "全指標内容SHA256": canonical_sha(block["frames"][3]), "全指標足数": len(block["frames"][3]),
                "数値品質": bundle["numeric_quality"][session]}
            inputs.append({"期間": period, **block["input_quality"]})
            if prepare_only:
                prepared.append(record)
                print(f"00046 {session} 二実体/ヒスト差/前平均の非損益準備", flush=True)
                continue
            for frame in block["frames"][3]:
                streams["全指標.jsonl.gz"].write(D.encode({"期間": period, **frame}))
            for decision in block["decisions"]:
                streams["発動判定.jsonl.gz"].write(D.encode({"期間": period, **decision}))
            path = W.OLD.気配経路([e for e in block["events"] if e.valid])
            labels = {}
            for source in entries:
                sid = source["入口ID"]
                for signal in block["signals"][sid]:
                    origin = signal["イベントID"][:-3]
                    label_key = signal["要求時計秒"], signal["side"]
                    if label_key not in labels:
                        labels[label_key] = path.evaluate(signal["要求時計秒"], block["cutoff"], block["deadline"],
                            signal["side"], adverse=125, favorable=250)
                    label = labels[label_key]
                    case = {**deepcopy(signal), "期間": period, "要求時計JST": O.iso(signal["要求時計秒"]),
                        "元価格発動ID": origin, **deepcopy(block["metadata"][origin]), **deepcopy(label)}
                    cases[sid].append(case)
                    streams["入口事例.jsonl.gz"].write(D.encode(case))
            for policy, exit_id in OPERATION_PAIRS:
                sid, cid = "3分_"+policy, "3分_"+policy+"_"+exit_id
                signals = block["signals"][sid]
                state, info = ENGINE.replay(block["events"], signals, block["frames"][3], session,
                    cid, config["運用"], {"出口ID": exit_id}, I.ROLES[policy])
                info.update(期間=period, 場時間分=block["duration"])
                for trade in state.trades:
                    trade["期間"] = period
                detail = {"候補ID": cid, "場": session, "品質": info, "約定": state.fills,
                    "取引": state.trades, "注文": state.orders, "入口取扱": state.signals}
                logs = [{"期間": period, **r} for r in state.normal_log]
                infos[cid].append(info)
                trades[cid].extend(state.trades)
                streams["全運用詳細.jsonl.gz"].write(D.encode(detail))
                for row in logs:
                    streams["追尾.jsonl.gz"].write(D.encode(row))
            print(f"00046 {session} 三入口三運用完了", flush=True)
    if initial != current_bindings(study):
        raise ValueError("実行中出典に差")
    if prepare_only:
        W.write_json(work/"準備点検.json", {**initial, "ラベル計算": False, "損益計算": False,
            "全66場既使用": True, "純信号whitelist": list(I.SIGNAL_FIELDS),
            "準備": prepared})
        return {"準備点検": True, "ラベル計算": False, "損益計算": False}
    entrances, by_id = [], {}
    for source in entries:
        sid = source["入口ID"]
        item = {**source, **{p: E.entry_metrics([r for r in cases[sid] if r["期間"] == p], p) for p in PERIODS}}
        support, goal = D.entry_flags(item, config)
        item.update(入口支持=support, **{"70目標": goal})
        entrances.append(item)
        by_id[sid] = item
    results, ids = [], []
    for policy, exit_id in OPERATION_PAIRS:
        sid, cid = "3分_"+policy, "3分_"+policy+"_"+exit_id
        entrance = by_id[sid]
        source = next(r for r in entries if r["入口ID"] == sid)
        result = {"候補ID": cid, "入口": source, "出口": {"出口ID": exit_id}, "入口支持": entrance["入口支持"],
            "70目標": entrance["70目標"], "現方針候補": exit_id == "XF"}
        for p in PERIODS:
            result[p] = {"入口": entrance[p], "運用": S.operation_metrics([r for r in infos[cid] if r["期間"] == p],
                [r for r in trades[cid] if r["期間"] == p], I.ROLES[policy], {"出口ID": exit_id})}
        result["費用資格"] = all(W.supported(result[p]["運用"], limits) and result[p]["運用"]["品質注意場数"] == 0
            and result[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        result["採用資格"] = result["現方針候補"] and result["70目標"] and result["費用資格"]
        results.append(result)
        ids.append(cid)
    role_entries = []
    for source in entries:
        sid = source["入口ID"]
        for role in I.ACTIVE_ROLES[source["戦略"]]:
            local = {p: E.entry_metrics([r for r in cases[sid] if r["期間"] == p and r["役割"] == role], p) for p in PERIODS}
            support, goal = D.entry_flags(local, config)
            role_entries.append({"入口ID": sid, "役割": role, **local, "入口支持": support, "70目標": goal})
    report = {"全66場既使用": True, "入口評価": entrances, "役割別入口評価": role_entries, "結果": results, "表示固定ID": ids,
        "入口評価数": 3, "運用候補数": 3, "現方針運用候補数": 3, "入口125250評価の変更": False,
        "実役割群数": 4, "対象実役割": {key: list(value) for key, value in I.ACTIVE_ROLES.items()},
        "入口70目標達成数": sum(r["70目標"] for r in entrances), "費用資格数": sum(r["費用資格"] for r in results),
        "現方針費用資格数": sum(r["費用資格"] and r["現方針候補"] for r in results), "採用資格数": sum(r["採用資格"] for r in results),
        "位置付け": "固定29価格/ATR/中心化ヒストを共有。二足実体包みと実方向ヒスト差を新母集団とし、前二平均の準備/位置進行によるT-R-WAITを分離。B0/B1反転とB2背景役割の名称差を利益にしない。旧入口/旧label/旧運用controlは作らない"}
    W.write_json(study/"入力品質.json", inputs)
    W.write_csv(study/"全候補_場別.csv", [r for cid in ids for r in infos[cid]])
    E.publish_details(study, work/"全運用詳細.jsonl.gz", ids, manifest, "")
    catalog = W.read_json(study/"一覧.resources.json")
    for resource in catalog["resources"]:
        resource["id"] = resource["id"].replace("00008_", "00046_", 1)
    W.write_json(study/"一覧.resources.json", catalog)
    W.write_json(study/"作業成果物.json", {"原板複製": False, "展開内容SHA256が正本": True,
        "共有参照": ["指標参照.json"], "ファイル": [{"パス": (work/n).relative_to(ROOT).as_posix(),
            "展開内容SHA256": content_sha(work/n), "圧縮SHA256参考": O.sha(work/n), "圧縮バイト": (work/n).stat().st_size} for n in FILES]})
    W.write_json(study/"結果.json", report)
    return {k: report[k] for k in ("入口評価数", "運用候補数", "入口70目標達成数", "現方針費用資格数", "採用資格数")}


def main() -> None:
    """非損益準備又は固定後正式比較をroot管理で起動する。

    引数: なし。CLIは--study/--work/--prepare。
    返り値: None。既存正式明細の再実行は拒否する。
    """
    parser = argparse.ArgumentParser(description="二足の実体包みと平均進行")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.study.resolve(), args.work.resolve(), args.prepare), ensure_ascii=False))


if __name__ == "__main__":
    main()
