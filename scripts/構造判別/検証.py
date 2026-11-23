"""既使用66場で、高安帰還の反転と外側残留の継続を同時計判別する。"""

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
STUDY = ROOT/"study/00037_高安帰還と外側継続の判別"
WORK = ROOT/"work/構造判別/00037"
PREVIOUS = ROOT/"study/00036_価格失敗と量比の方向変化"
ENTRY_STUDY = ROOT/"study/00029_BB内復帰とOBV非追随"
EXIT_STUDY = ROOT/"study/00033_CCI突破と足内終値位置"
MANIFEST_PATH = ROOT/"study/00028_基準線復帰と上位一目の方向/入力台帳.json"
PREVIOUS_LOCK_SHA = "f373b12d6248482a8181d0964866a3bee876aa28bd08756b7961deb5824b4e41"
ENTRY_LOCK_SHA = "353143ea3f7a626736bf44551d17ba6e22b8bfd76ee40e2f4f9b0c190736f48a"
PERIODS = ("学習", "条件選択", "後続検査")
FILES = ("構造判定.jsonl.gz", "入口事例.jsonl.gz", "全運用詳細.jsonl.gz", "追尾.jsonl.gz")
OPERATION_PAIRS = (("B0", "X0"), ("B0", "XF"), ("R1", "XF"), ("T1", "XF"), ("S1", "XF"))
CONTROL_ID = "3分_R0_X0"
LABEL_FIELDS = ("ラベル", "理由", "新規価格", "新規時計秒", "新規原板行", "判定時計秒", "判定原板行",
    "判定気配", "最大順行pt", "最大逆行pt", "所要分")
RULES = {"B0": "固定29R0完全入口。元価格P/中心化MACD差/ATR/元P数量M/時間/競合を維持",
    "R1": "B0かつ旧L<C<旧H strict全範囲内。片端帰還だけで反対端超えを含めない",
    "T1": "全旧価格Pの元M/時間/遅延かつ元s*(C-K)<0、(-元s)*δH>0。実side=-元s・順行。旧R0の補数ではない",
    "S1": "R1とT1の同時点候補和で反転/順行を切替。保有中の役割変更・自動ドテンなし",
    "K": "元s買Pは前20最安L、売Pは前20最高H。元P/kの数量Mを反対端へ取り直さない",
    "判別": "全範囲内/元方向外側/反対端外側/境界等号とMACD符号。等号/不一致は待機",
    "競合": "候補ごと公開keyの複数採用を同方向も全見送り。Sは技術候補和から独立に競合処理",
    "時点": "当足公開で一回判断、後続監視/固定過去登録/確認待ち/水準差替なし",
    "限界": "新極値と外側終値はT側で論理的重複。BB内と全高安内は別。既使用66場の追加開発"}


def module(path: Path, name: str) -> Any:
    """固定コードをCLI起動せず読み込む。

    引数: path(Path)はコード、name(str)は識別。
    返り値: Anyはモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


D = module(ROOT/"scripts/OBV反転/検証.py", "構造判別の固定29材料")
S = module(ROOT/"scripts/終値位置/検証.py", "構造判別の固定33費用集計")
W, E, O = D.W, D.E, D.O
I = module(Path(__file__).with_name("入口.py"), "構造判別の量と純射影")
ENGINE = module(Path(__file__).with_name("運用.py"), "構造判別の固定出口接続")
OLD_CONFIG = W.read_json(ENTRY_STUDY/"条件.json")
canonical_sha, compressed, content_sha = I.canonical_sha, D.compressed, D.content_sha


def expected_config() -> dict:
    """旧29価格と数量の規約を参照し、帰還反転・外側継続・切替を固定する。

    引数: なし。
    返り値: dictは四入口/五運用、費用後起動と支持を含む条件。
    """
    value = {k: deepcopy(OLD_CONFIG[k]) for k in D.I.CORE_KEYS}
    fee = W.read_json(EXIT_STUDY/"条件.json")
    value["運用"] = deepcopy(fee["運用"])
    value["必須追尾"] = deepcopy(fee["必須追尾"])
    value.update(版=1, 全66場既使用=True, 戦略=list(I.POLICIES), 構造判別=deepcopy(RULES),
        カタログ版=2, 出口=[{"出口ID": "X0"}, {"出口ID": "XF"}],
        運用組合せ=[{"戦略": p, "出口ID": x} for p, x in OPERATION_PAIRS],
        入口条件参照={"パス": "../00029_BB内復帰とOBV非追随/条件.json", "SHA256": O.sha(ENTRY_STUDY/"条件.json")},
        運用条件参照={"パス": "../00033_CCI突破と足内終値位置/条件.json", "SHA256": O.sha(EXIT_STUDY/"条件.json")},
        現方針候補出口=["XF"], 入口評価数=4, 運用候補数=5, 表示代表="旧B0X0参考/B0XF/R1XF/T1XF/S1XF",
        出口定義={"X0": "旧29A5参考、現在方針候補外", "XF": "固定33現在費用後strict正・登録ATR固定D・最低名目同値"})
    return value


def validate_config(config: dict) -> None:
    """事前の構造式・四案・共通運用からの変更を拒否する。

    引数: config(dict)は37条件。
    返り値: None。不一致は例外。
    """
    if config != expected_config():
        raise ValueError("固定37条件に差")


def code_pins() -> dict:
    """主三コードの現在指紋を返す。

    引数: なし。
    返り値: dictはROOT相対パス/SHA256。
    """
    return {p.relative_to(ROOT).as_posix(): O.sha(p) for p in
        (Path(__file__), Path(__file__).with_name("入口.py"), Path(__file__).with_name("運用.py"))}


def rename(value: object, old: str, new: str) -> object:
    """候補の識別子だけを深いJSON値まで写す。

    引数: value(object)は値、old/new(str)は識別子断片。
    返り値: objectは数値/時計を変えない変換値。
    """
    if isinstance(value, dict):
        return {k: rename(v, old, new) for k, v in value.items()}
    if isinstance(value, list):
        return [rename(v, old, new) for v in value]
    return value.replace(old, new) if isinstance(value, str) else value


def decision_signal(row: dict) -> dict:
    """純信号のATR表現差だけを判断指紋から分ける。

    引数: row(dict)は純13列。
    返り値: dictは他値厳密、ATR正有効とD整数の射影。
    """
    value = deepcopy(row)
    atr = value.pop("atr")
    value["ATR判断"] = {"正有効": atr is not None and atr > 0,
        "D整数": max(5, math.ceil(atr/5)*5) if atr is not None and atr > 0 else None}
    return value


def raw_projection(rows: list[dict]) -> list[dict]:
    """旧29価格Pと当時の判断を、MACD表現差から分けて指紋化する。

    引数: rows(list[dict])は旧29全原P。
    返り値: list[dict]は公開/価格窓/旧M/採否の厳密な射影。
    """
    fields = ("場", "発動ID", "index", "side", "要求時計秒", "要求原板行", "low", "high", "close",
        "前20足番号", "旧BB下端", "旧BB上端", "共通M準備", "時間条件可", "確認遅延条件可")
    return [{**{k: deepcopy(r[k]) for k in fields}, "旧R0採用": r["戦略判定"]["R0"]["採用"]} for r in rows]


def decision_projection(rows: list[dict]) -> list[dict]:
    """構造/採否の厳密指紋からMACD末端の微小表現差だけを分ける。

    引数: rows(list[dict])は全構造判定。
    返り値: list[dict]はMACD有限/符号と他値厳密の射影。
    """
    values = deepcopy(rows)
    for row in values:
        delta = row.pop("MACDヒスト変化")
        finite = D.I.finite(delta)
        row["MACD差判断"] = {"有限": finite, "符号": int(delta > 0)-int(delta < 0) if finite else None}
    return values


def sources(config: dict) -> list[dict]:
    """固定四入口を各役割で列挙する。

    引数: config(dict)は条件。
    返り値: list[dict]は順序を結果で選び直さない表示定義。
    """
    validate_config(config)
    return [{"入口ID": "3分_"+p, "戦略": p, "時間足分": 3, "名称": p, "役割": I.ROLES[p], "複合本命": True} for p in I.POLICIES]


def manifest_for(study: Path, config: dict) -> dict:
    """固定28の66場台帳と既存cacheだけを解決する。

    引数: study(Path)は36、config(dict)は条件。
    返り値: dictは入力台帳。新しい原板を列挙しない。
    """
    validate_config(config)
    pointer = W.read_json(study/"入力台帳.json")
    if (study/pointer["参照"]).resolve() != MANIFEST_PATH.resolve() or pointer["SHA256"] != O.sha(MANIFEST_PATH):
        raise ValueError("固定66場台帳だけ")
    return D.manifest_for(ENTRY_STUDY, OLD_CONFIG)


def validate_reference(study: Path, name: str) -> dict:
    """旧29の完了証明と、共有六系列又は対照二系列を現在SHAで照合する。

    引数: study(Path)は36、name(str)は入口参照/対照参照。
    返り値: dictは小型参照。古い証明又は他の試行を拒否する。
    """
    ref = W.read_json(study/name)
    if ref["参照試行"] != "00029" or ref["旧固定SHA256"] != ENTRY_LOCK_SHA or O.sha(ENTRY_STUDY/"固定.json") != ENTRY_LOCK_SHA:
        raise ValueError("旧29固定参照に差")
    names = {"固定.json", "条件.json", "結果.json", "作業成果物.json", "独立監査.json", "状態独立確認.json", "追尾独立確認.json", "入力台帳.json"}
    if set(ref["文書と証明"]) != names or ref["大明細複製"] is not False:
        raise ValueError("旧29の全完了証明と共有宣言が必要")
    for n, item in ref["文書と証明"].items():
        if (ROOT/item["パス"]).resolve() != (ENTRY_STUDY/n).resolve() or O.sha(ROOT/item["パス"]) != item["SHA256"]:
            raise ValueError("旧29正本又は指紋に差")
    expected = W.read_json(ENTRY_STUDY/"作業成果物.json")["ファイル"]
    if name == "対照参照.json":
        expected = [r for r in expected if Path(r["パス"]).name in ("全運用詳細.jsonl.gz", "追尾.jsonl.gz")]
        if ref["候補ID"] != CONTROL_ID:
            raise ValueError("旧29R0X0だけを対照とします")
    if ref["共有明細"] != expected:
        raise ValueError("旧29共有範囲に差")
    for item in expected:
        if O.sha(ROOT/item["パス"]) != item["圧縮SHA256参考"]:
            raise ValueError("旧29共有明細に差")
    return ref


def shared_path(ref: dict, name: str) -> Path:
    """共有する旧29明細を一意に解決する。

    引数: ref(dict)は参照、name(str)はファイル名。
    返り値: Pathは検査済み旧明細。
    """
    paths = [ROOT/r["パス"] for r in ref["共有明細"] if Path(r["パス"]).name == name]
    if len(paths) != 1:
        raise ValueError("共有明細は一意だけ")
    return paths[0]


def read_rows(path: Path) -> list[dict]:
    """検査済み圧縮JSONLを読む。

    引数: path(Path)は共有又は正式明細。
    返り値: list[dict]は保存行。計算を起動しない。
    """
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def build_session(entry: dict, manifest: dict, banks: dict, config: dict) -> dict:
    """固定29の全価格発動を維持し、構造判定と四純集合を追加する。

    引数: entry/manifest/config(dict)は入力/条件、banks(dict)は旧29数値銀行。
    返り値: dictはラベル/PnLを計算しない場材料。
    """
    validate_config(config)
    return I.select(D.build_session(entry, manifest, banks, OLD_CONFIG))


def validate_independent(study: Path, work: Path) -> dict:
    """独立非PnL準備の成功と現在の主版/入力/全依存への接続を要求する。

    引数: study/work(Path)は保存先。
    返り値: dictは現在版の成功証明。
    """
    proof = W.read_json(work/"独立準備点検.json")
    expected = {"全件一致": True, "不一致数": 0, "不一致": [], "ラベル計算": False, "損益計算": False,
        "主準備SHA256": O.sha(work/"準備点検.json"), "主コードSHA256": code_pins(),
        "条件SHA256": O.sha(study/"条件.json"), "入力台帳SHA256": O.sha(study/"入力台帳.json"),
        "参照入力台帳SHA256": O.sha(MANIFEST_PATH), "入口参照SHA256": O.sha(study/"入口参照.json"),
        "対照参照SHA256": O.sha(study/"対照参照.json"), "コードSHA256": O.sha(Path(__file__).with_name("状態独立確認.py")),
        "追尾コードSHA256": O.sha(Path(__file__).with_name("追尾独立確認.py"))}
    if any(proof.get(k) != v for k, v in expected.items()):
        raise ValueError("独立準備の成功又は現在版bindに差")
    if not proof.get("依存コードSHA256") or any(O.sha(ROOT/n) != h for n, h in proof["依存コードSHA256"].items()):
        raise ValueError("独立依存に差")
    return proof


def freeze(study: Path, work: Path) -> dict:
    """主独立準備・最終人工・旧固定継承を正式結果前に必須接続する。

    引数: study/work(Path)は保存先。
    返り値: dictは278旧pinsを継承した新固定。結果は上書きしない。
    """
    if (study/"結果.json").exists():
        raise ValueError("既存結果を上書きしません")
    entry_ref, control_ref = validate_reference(study, "入口参照.json"), validate_reference(study, "対照参照.json")
    prepared = W.read_json(work/"準備点検.json")
    for k, v in current_bindings(study).items():
        if prepared.get(k) != v:
            raise ValueError("主準備の現在版bindに差")
    if prepared["ラベル計算"] or prepared["損益計算"] or prepared["旧29R0純登録同値"] is not True:
        raise ValueError("主非損益準備に差")
    independent = validate_independent(study, work)
    synthetic_path = ROOT/"work/構造判別/合成検証.json"
    synthetic = W.read_json(synthetic_path)
    if synthetic.get("全件成功") is not True or synthetic.get("合成編集終了") is not True:
        raise ValueError("最終人工成功前")
    if O.sha(PREVIOUS/"固定.json") != PREVIOUS_LOCK_SHA:
        raise ValueError("直前36固定に差")
    pins = dict(W.read_json(PREVIOUS/"固定.json")["ファイルSHA256"])
    if any(O.sha(ROOT/n) != h for n, h in pins.items()):
        raise ValueError("旧固定出典に差")
    paths = [Path(__file__), *[Path(__file__).with_name(n) for n in
        ("入口.py", "運用.py", "合成検証.py", "状態独立確認.py", "追尾独立確認.py")], PREVIOUS/"固定.json",
        *[study/n for n in ("計画.md", "条件.json", "入力台帳.json", "入口参照.json", "対照参照.json")],
        *[work/n for n in ("準備点検.json", "独立準備点検.json", "診断予定.json")], synthetic_path,
        ROOT/"work/構造判別37の事前案.md", ROOT/"work/構造判別37の記録案.md", ROOT/"work/構造判別37の独立案.md"]
    for ref in (entry_ref, control_ref):
        paths.extend(ROOT/r["パス"] for r in ref["文書と証明"].values())
        paths.extend(ROOT/r["パス"] for r in ref["共有明細"])
    paths.extend(ROOT/n for n in independent["依存コードSHA256"])
    pins.update({p.relative_to(ROOT).as_posix(): O.sha(p) for p in paths})
    for p in (Path(__file__), Path(__file__).with_name("入口.py"), Path(__file__).with_name("運用.py"),
        Path(__file__).with_name("合成検証.py"), study/"条件.json"):
        if synthetic.get("ファイルSHA256", {}).get(p.relative_to(ROOT).as_posix()) != O.sha(p):
            raise ValueError("最終人工の主版bindに差")
    for key, n in (("独立数値補助SHA256", "状態独立確認.py"), ("独立追尾補助SHA256", "追尾独立確認.py")):
        if synthetic.get(key) != O.sha(Path(__file__).with_name(n)):
            raise ValueError("最終人工の独立版bindに差")
    locked = {"固定日時": datetime.now().astimezone().isoformat(), "ファイルSHA256": dict(sorted(pins.items())),
        "主準備SHA256": O.sha(work/"準備点検.json"), "独立準備SHA256": O.sha(work/"独立準備点検.json"),
        "全66場既使用": True, "Python": platform.python_version(), "NumPy": W.np.__version__}
    if (study/"固定.json").exists():
        old = W.read_json(study/"固定.json")
        if old["ファイルSHA256"] != locked["ファイルSHA256"]:
            raise ValueError("固定後出典変更")
        return old
    W.write_json(study/"固定.json", locked)
    return locked


def current_bindings(study: Path) -> dict:
    """実行中に不変であるべき主版と参照を集める。

    引数: study(Path)は36。
    返り値: dictは主三codeと条件/入力/二参照のSHA。
    """
    return {"コードSHA256": code_pins(), "条件SHA256": O.sha(study/"条件.json"),
        "入力台帳SHA256": O.sha(study/"入力台帳.json"), "参照台帳SHA256": O.sha(MANIFEST_PATH),
        "入口参照SHA256": O.sha(study/"入口参照.json"), "対照参照SHA256": O.sha(study/"対照参照.json")}


# ----------------------------------------
# 準備は構造/全採否だけ。正式で全先着を新計算し、同時計反転は旧結果とも比較する。

def run(study: Path, work: Path, prepare_only: bool) -> dict:
    """高安帰還と外側継続の四案を純準備又は固定後五運用で比較する。

    引数: study/work(Path)は保存先、prepare_only(bool)は非PnL準備。
    返り値: dictは完了要約。市場起動はrootだけが行う。
    """
    config = W.read_json(study/"条件.json")
    manifest, entries = manifest_for(study, config), sources(config)
    ref, control = validate_reference(study, "入口参照.json"), validate_reference(study, "対照参照.json")
    initial = current_bindings(study)
    work.mkdir(parents=True, exist_ok=True)
    if not prepare_only:
        if any((work/n).exists() for n in FILES):
            raise ValueError("正式明細は上書きしません")
        freeze(study, work)
    old_cases = [r for r in read_rows(shared_path(ref, "入口事例.jsonl.gz")) if r["入口ID"] == "3分_R0"]
    old_pure = {r["イベントID"]: I.pure_signal(r, "B0") for r in old_cases}
    old_labels = {r["イベントID"]: {k: r[k] for k in LABEL_FIELDS} for r in old_cases} if not prepare_only else None
    previous_details, previous_logs = {}, defaultdict(list)
    if not prepare_only:
        previous_details = {r["場"]: r for r in read_rows(shared_path(control, "全運用詳細.jsonl.gz")) if r["候補ID"] == CONTROL_ID}
        for row in read_rows(shared_path(control, "追尾.jsonl.gz")):
            if row["候補ID"] == CONTROL_ID:
                previous_logs[row["場"]].append(row)
    banks = {3: D.J.NumericBank()}
    prepared, inputs, controls, all_old = [], [], [], set()
    cases, infos, trades = defaultdict(list), defaultdict(list), defaultdict(list)
    with ExitStack() as stack:
        streams = {n: stack.enter_context(compressed(work/n)) for n in FILES} if not prepare_only else {}
        for entry in manifest["entries"]:
            session, period = entry["session"], E.phase_of(entry["session"], config)
            block = build_session(entry, manifest, banks, config)
            pure = [r for p in I.POLICIES for r in block["signals"]["3分_"+p]]
            for row in block["signals"]["3分_B0"]:
                old_id = row["イベントID"][:-3]+"_R0"
                if row != old_pure[old_id]:
                    raise ValueError("旧29R0純13列に差")
                all_old.add(old_id)
            record = {"場": session, "期間": period, "純信号": pure, "純信号内容SHA256": canonical_sha(pure),
                "純信号判断SHA256": canonical_sha([decision_signal(r) for r in pure]),
                "判定": block["decisions"], "判定SHA256": canonical_sha(block["decisions"]),
                "判定判断SHA256": canonical_sha(decision_projection(block["decisions"])),
                "旧原P判断SHA256": canonical_sha(raw_projection(block["quality"]["全Q発動記録"])), "入力品質": block["input_quality"]}
            inputs.append({"期間": period, **block["input_quality"]})
            if prepare_only:
                prepared.append(record)
                print(f"00037 {session} 高安位置/方向の非損益準備", flush=True)
                continue
            for decision in block["decisions"]:
                streams["構造判定.jsonl.gz"].write(D.encode({"期間": period, **decision}))
            path = W.OLD.気配経路([e for e in block["events"] if e.valid])
            labels = {}
            origins = {r["発動ID"]: r for r in block["quality"]["全Q発動記録"]}
            for source in entries:
                sid = source["入口ID"]
                for signal in block["signals"][sid]:
                    origin = signal["イベントID"][:-3]
                    original = origin+"_R0"
                    label_key = signal["要求時計秒"], signal["side"]
                    if label_key not in labels:
                        labels[label_key] = path.evaluate(signal["要求時計秒"], block["cutoff"], block["deadline"],
                            signal["side"], adverse=125, favorable=250)
                    label = labels[label_key]
                    if signal["役割"] == "反転" and any(label[k] != old_labels[original][k] for k in LABEL_FIELDS):
                        raise ValueError("同時計反転の旧先着に差")
                    case = {**deepcopy(signal), "期間": period, "要求時計JST": O.iso(signal["要求時計秒"]),
                        "元価格発動ID": origin, "元価格side": origins[origin]["side"],
                        "旧R0イベントID": original if signal["役割"] == "反転" else None, **deepcopy(label)}
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
                if (policy, exit_id) == ("B0", "X0"):
                    adapted, adapted_logs = rename(detail, "_B0", "_R0"), rename(logs, "_B0", "_R0")
                    if adapted != previous_details[session] or adapted_logs != previous_logs[session]:
                        raise ValueError("旧29R0X0全属性対照に差")
                    controls.append({"場": session, "候補ID": cid, "全運用同値": True, "全追尾同値": True,
                        "旧識別子全運用内容SHA256": canonical_sha(adapted), "旧識別子追尾内容SHA256": canonical_sha(adapted_logs)})
                infos[cid].append(info)
                trades[cid].extend(state.trades)
                streams["全運用詳細.jsonl.gz"].write(D.encode(detail))
                for row in logs:
                    streams["追尾.jsonl.gz"].write(D.encode(row))
            print(f"00037 {session} 四入口五運用完了", flush=True)
    if set(old_pure) != all_old or initial != current_bindings(study):
        raise ValueError("旧R0全集合又は実行中出典に差")
    if prepare_only:
        W.write_json(work/"準備点検.json", {**initial, "ラベル計算": False, "損益計算": False,
            "全66場既使用": True, "旧29R0純登録同値": True, "純信号whitelist": list(I.SIGNAL_FIELDS),
            "準備": prepared, "旧R0登録数": len(all_old)})
        return {"準備点検": True, "ラベル計算": False, "損益計算": False, "旧R0登録数": len(all_old)}
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
        for role in (("反転", "順行") if source["戦略"] == "S1" else (source["役割"],)):
            local = {p: E.entry_metrics([r for r in cases[sid] if r["期間"] == p and r["役割"] == role], p) for p in PERIODS}
            support, goal = D.entry_flags(local, config)
            role_entries.append({"入口ID": sid, "役割": role, **local, "入口支持": support, "70目標": goal})
    report = {"全66場既使用": True, "入口評価": entrances, "役割別入口評価": role_entries, "結果": results, "表示固定ID": ids,
        "入口評価数": 4, "運用候補数": 5, "現方針運用候補数": 4, "入口125250評価の変更": True,
        "入口70目標達成数": sum(r["70目標"] for r in entrances), "費用資格数": sum(r["費用資格"] for r in results),
        "現方針費用資格数": sum(r["費用資格"] and r["現方針候補"] for r in results), "採用資格数": sum(r["採用資格"] for r in results),
        "位置付け": "旧29価格P/中心化MACD/元P数量Mを共有。全高安帰還の反転と元方向外側の継続を分け、混合切替と単独を同出口で比較"}
    W.write_json(study/"入力品質.json", inputs)
    W.write_json(study/"B0対照同値.json", {"全件一致": True, "旧先着全件同値": True,
        "場候補数": len(controls), "照合": controls, "入口参照SHA256": initial["入口参照SHA256"], "対照参照SHA256": initial["対照参照SHA256"]})
    W.write_csv(study/"全候補_場別.csv", [r for cid in ids for r in infos[cid]])
    E.publish_details(study, work/"全運用詳細.jsonl.gz", ids, manifest, "")
    catalog = W.read_json(study/"一覧.resources.json")
    for resource in catalog["resources"]:
        resource["id"] = resource["id"].replace("00008_", "00037_", 1)
    W.write_json(study/"一覧.resources.json", catalog)
    W.write_json(study/"作業成果物.json", {"原板複製": False, "展開内容SHA256が正本": True,
        "共有参照": ["入口参照.json", "対照参照.json"], "ファイル": [{"パス": (work/n).relative_to(ROOT).as_posix(),
            "展開内容SHA256": content_sha(work/n), "圧縮SHA256参考": O.sha(work/n), "圧縮バイト": (work/n).stat().st_size} for n in FILES]})
    W.write_json(study/"結果.json", report)
    return {k: report[k] for k in ("入口評価数", "運用候補数", "入口70目標達成数", "現方針費用資格数", "採用資格数")}


def main() -> None:
    """純準備又は固定後の一回正式比較を起動する。

    引数: なし。CLIは--study/--work/--prepare。
    返り値: None。市場起動はroot。
    """
    parser = argparse.ArgumentParser(description="価格失敗と高安帰還と外側継続")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.study.resolve(), args.work.resolve(), args.prepare), ensure_ascii=False))


if __name__ == "__main__":
    main()
