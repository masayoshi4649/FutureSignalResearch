"""固定42の再テスト入口を保持し、現前CMF準備と変化方向を比較する。"""

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
STUDY = ROOT/"study/00043_再テスト時のCMF変化方向"
WORK = ROOT/"work/CMF変化/00043"
PREVIOUS = ROOT/"study/00042_突破再テストと数量加重終値位置"
ENTRY_STUDY = PREVIOUS
NUMERIC_STUDY = ROOT/"study/00029_BB内復帰とOBV非追随"
EXIT_STUDY = ROOT/"study/00033_CCI突破と足内終値位置"
MANIFEST_PATH = ROOT/"study/00028_基準線復帰と上位一目の方向/入力台帳.json"
PREVIOUS_LOCK_SHA = "604104ee9546e89e49add20415673020ed816d01f8ae2ef0badefa3cd66bba12"
CONTROL_ID = "3分_A0_XF"
PERIODS = ("学習", "条件選択", "後続検査")
FILES = ("発動判定.jsonl.gz", "入口事例.jsonl.gz", "全運用詳細.jsonl.gz", "追尾.jsonl.gz")
OPERATION_PAIRS = (("D0", "XF"), ("D1", "XF"), ("D2", "XF"))
LABEL_FIELDS = ("ラベル", "理由", "新規価格", "新規時計秒", "新規原板行", "判定時計秒", "判定原板行",
    "判定気配", "最大順行pt", "最大逆行pt", "所要分")
SOURCE_FIELDS = ("index", "minutes", "start", "end", "confirm", "confirm_line", "publish", "missing",
    "open", "high", "low", "close")


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


M = module(ROOT/"scripts/再テスト量方向/検証.py", "CMF変化の固定42数値参照補助")
D = module(ROOT/"scripts/OBV反転/検証.py", "CMF変化の固定29材料")
S = module(ROOT/"scripts/終値位置/検証.py", "CMF変化の固定33費用集計")
W, E, O = D.W, D.E, D.O
I = module(Path(__file__).with_name("入口.py"), "CMF変化の量と純射影")
ENGINE = module(Path(__file__).with_name("運用.py"), "CMF変化の固定出口接続")
OLD_CONFIG = W.read_json(ENTRY_STUDY/"条件.json")
canonical_sha, compressed, content_sha = I.canonical_sha, D.compressed, D.content_sha
RULES = I.RULES


def expected_config() -> dict:
    """固定42A0と現前CMFの三案へ固定33の出口・支持条件を接続する。

    引数: なし。
    返り値: dictは固定母集団とD0/D1/D2、全XF、既定の125/250と費用。
    """
    value = {k: deepcopy(OLD_CONFIG[k]) for k in D.I.CORE_KEYS}
    fee = W.read_json(EXIT_STUDY/"条件.json")
    value.update(運用=deepcopy(fee["運用"]), 必須追尾=deepcopy(fee["必須追尾"]), 版=1,
        全66場既使用=True, 戦略=list(I.POLICIES), CMF変化=deepcopy(RULES), カタログ版=4,
        出口=[{"出口ID": "XF"}], 運用組合せ=[{"戦略": p, "出口ID": x} for p, x in OPERATION_PAIRS],
        指標条件参照={"パス": "../00029_BB内復帰とOBV非追随/条件.json", "SHA256": O.sha(NUMERIC_STUDY/"条件.json")},
        運用条件参照={"パス": "../00033_CCI突破と足内終値位置/条件.json", "SHA256": O.sha(EXIT_STUDY/"条件.json")},
        現方針候補出口=["XF"], 入口評価数=3, 運用候補数=3, 表示代表="D0固定42A0/D1現前CMF準備/D2CMF変化方向",
        出口定義={"XF": "固定33現在費用後strict正・登録現ATR固定D・最低名目同値"})
    return value

def validate_config(config: dict) -> None:
    """事前の固定42A0・現前準備・CMF変化三案・共通運用からの変更を拒否する。

    引数: config(dict)は43条件。
    返り値: None。不一致は例外。
    """
    if config != expected_config():
        raise ValueError("固定43条件に差")


def code_pins() -> dict:
    """主三コードの現在指紋を返す。

    引数: なし。
    返り値: dictはROOT相対パス/SHA256。
    """
    return {p.relative_to(ROOT).as_posix(): O.sha(p) for p in
        (Path(__file__), Path(__file__).with_name("入口.py"), Path(__file__).with_name("運用.py"))}




def rename(value: object, old: str, new: str) -> object:
    """完全対照の識別子だけを全JSON末端まで正規化する。

    引数: value(object)は保存値、old/new(str)は識別子断片。
    返り値: objectは数値・時点・役割を変えない値。
    """
    if isinstance(value, dict): return {k: rename(v, old, new) for k, v in value.items()}
    if isinstance(value, list): return [rename(v, old, new) for v in value]
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


def decision_projection(rows: list[dict]) -> list[dict]:
    """固定jと現前CMF/入替えの出典/数値/採否を厳密に指紋化する。

    引数: rows(list[dict])は旧42全jにおける現前変化判定。
    返り値: list[dict]は微小差で境界を変更しないコピー。
    """
    return deepcopy(rows)

def sources(config: dict) -> list[dict]:
    """固定三入口を切替集合として列挙する。

    引数: config(dict)は条件。
    返り値: list[dict]は順序を結果で選び直さない表示定義。
    """
    validate_config(config)
    return [{"入口ID": "3分_"+p, "戦略": p, "時間足分": 3, "名称": p, "役割": I.ROLES[p], "複合本命": True} for p in I.POLICIES]


def manifest_for(study: Path, config: dict) -> dict:
    """固定28の66場台帳と既存cacheだけを解決する。

    引数: study(Path)は43、config(dict)は条件。
    返り値: dictは入力台帳。未予約の新原板を列挙しない。
    """
    validate_config(config)
    pointer = W.read_json(study/"入力台帳.json")
    if (study/pointer["参照"]).resolve() != MANIFEST_PATH.resolve() or pointer["SHA256"] != O.sha(MANIFEST_PATH):
        raise ValueError("固定66場台帳だけ")
    return D.manifest_for(PREVIOUS, OLD_CONFIG)


def validate_reference(study: Path, name: str) -> dict:
    """固定42入口/対照と固定29数値を、証明・明細内容まで検査する。

    引数: study(Path)は43、name(str)は三参照のいずれか。
    返り値: dictは検査済み参照。旧原板や大明細を複製しない。
    """
    if name not in ("入口参照.json", "対照参照.json", "指標参照.json"):
        raise ValueError("事前三参照だけです")
    if name == "指標参照.json":
        return M.validate_reference(study, name)
    ref = W.read_json(study/name)
    if ref["参照試行"] != "00042" or ref["旧固定SHA256"] != PREVIOUS_LOCK_SHA or O.sha(PREVIOUS/"固定.json") != PREVIOUS_LOCK_SHA or ref["大明細複製"] is not False:
        raise ValueError("固定42の共有だけです")
    names = {"固定.json", "条件.json", "結果.json", "作業成果物.json", "独立監査.json", "状態独立確認.json", "追尾独立確認.json", "入力台帳.json", "入力品質.json"}
    if set(ref["文書と証明"]) != names:
        raise ValueError("共有証明の過不足")
    for n, item in ref["文書と証明"].items():
        if (ROOT/item["パス"]).resolve() != (PREVIOUS/n).resolve() or O.sha(ROOT/item["パス"]) != item["SHA256"]:
            raise ValueError("共有正本に差")
    for n in ("独立監査.json", "状態独立確認.json", "追尾独立確認.json"):
        proof = W.read_json(PREVIOUS/n)
        if proof["全件一致"] is not True or proof["不一致数"] != 0:
            raise ValueError("共有証明は成功完了だけ")
    expected = W.read_json(PREVIOUS/"作業成果物.json")["ファイル"]
    if name == "対照参照.json":
        expected = [r for r in expected if Path(r["パス"]).name in ("全運用詳細.jsonl.gz", "追尾.jsonl.gz")]
        if ref["候補ID"] != CONTROL_ID:
            raise ValueError("対照は固定42A0だけ")
    if ref["共有明細"] != expected:
        raise ValueError("共有範囲に差")
    for item in expected:
        if O.sha(ROOT/item["パス"]) != item["圧縮SHA256参考"] or content_sha(ROOT/item["パス"]) != item["展開内容SHA256"]:
            raise ValueError("共有明細内容に差")
    return ref

def shared_path(ref: dict, name: str) -> Path:
    """共有する旧42/29明細を一意に解決する。

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


def read_bundle(study: Path) -> dict:
    """固定42A0の全純信号と旧j、固定29全3分Qをread共有する。

    引数: study(Path)は43の参照置場。
    返り値: dictはpure/metadata/old_decisions/lower。旧labelを判断へ渡さない。
    """
    entry_ref, numeric = validate_reference(study, "入口参照.json"), validate_reference(study, "指標参照.json")
    pure, metadata, old_decisions, lower = defaultdict(list), {}, defaultdict(list), defaultdict(list)
    for row in read_rows(shared_path(entry_ref, "入口事例.jsonl.gz")):
        if row["入口ID"] == "3分_A0":
            pure[row["場"]].append({k: deepcopy(row[k]) for k in I.SIGNAL_FIELDS})
            metadata[row["イベントID"]] = {k: deepcopy(row[k]) for k in ("元登録ID", "元価格side", "元登録時計秒", "元登録原板行", "判別種別")}
    for row in read_rows(shared_path(entry_ref, "発動判定.jsonl.gz")):
        old_decisions[row["場"]].append({k: deepcopy(v) for k, v in row.items() if k != "期間"})
    for row in read_rows(shared_path(numeric, "全指標.jsonl.gz")):
        if row["minutes"] == 3:
            lower[row["場"]].append(row)
    if sum(map(len, pure.values())) != 245 or sum(map(len, old_decisions.values())) != 424:
        raise ValueError("固定42の全A0又は全jに差")
    return {"pure": dict(pure), "metadata": metadata, "old_decisions": dict(old_decisions), "lower": dict(lower)}

def build_session(entry: dict, manifest: dict, bundle: dict, config: dict, include_events: bool = False) -> dict:
    """固定42A0へ現前CMFを同時点結合し、正式時だけ予約cacheの気配を読む。

    引数: entry/manifest/bundle/config(dict)は入力/数値/条件、include_events(bool)は正式だけ真。
    返り値: dictは純13列三集合/全現前CMF判定/足/時計と必要時の気配。
    """
    validate_config(config)
    session = entry["session"]
    source = Path(manifest["source_root"])/entry["source_path"]
    cache = (ROOT/"work/複合検証"/entry["cache_path"]).resolve()
    stat = source.stat()
    if not cache.is_relative_to((ROOT/"work").resolve()) or (stat.st_size, stat.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]) or O.sha(cache) != entry["sha256_cache"]:
        raise ValueError("予約原板/cacheに差")
    begin, finish, cutoff, deadline = W.OLD.shared.legacy.session_times(session)
    start, end = begin.timestamp(), finish.timestamp()
    frames = bundle["lower"][session]
    block = {"場": session, "signals": {"3分_A0": deepcopy(bundle["pure"].get(session, []))},
        "frames": {3: frames}, "旧j判定": deepcopy(bundle["old_decisions"].get(session, []))}
    I.select(block, session)
    block["signals"] = {sid: [{k: deepcopy(row[k]) for k in I.SIGNAL_FIELDS} for row in rows] for sid, rows in block["signals"].items()}
    block.update(frames={3: frames}, input_quality=deepcopy(block["quality"]), cutoff=cutoff.timestamp(),
        deadline=deadline.timestamp(), duration=(end-start)/60, events=[])
    if include_events:
        previous_now = -math.inf
        for event in W.PREP.read_events(cache):
            if math.isfinite(event.now) and start <= event.now <= end and event.now >= previous_now:
                block["events"].append(event)
                previous_now = event.now
    return block

def validate_independent(study: Path, work: Path) -> dict:
    """独立非PnL準備の成功と現在の主版/入力/全依存への接続を要求する。

    引数: study/work(Path)は43の保存先。
    返り値: dictは現在版の成功証明。
    """
    proof = W.read_json(work/"独立準備点検.json")
    expected = {"全件一致": True, "不一致数": 0, "不一致": [], "ラベル計算": False, "損益計算": False,
        "主準備SHA256": O.sha(work/"準備点検.json"), "主コードSHA256": code_pins(),
        "条件SHA256": O.sha(study/"条件.json"), "入力台帳SHA256": O.sha(study/"入力台帳.json"),
        "参照入力台帳SHA256": O.sha(MANIFEST_PATH), "入口参照SHA256": O.sha(study/"入口参照.json"), "対照参照SHA256": O.sha(study/"対照参照.json"), "指標参照SHA256": O.sha(study/"指標参照.json"), "コードSHA256": O.sha(Path(__file__).with_name("状態独立確認.py")),
        "追尾コードSHA256": O.sha(Path(__file__).with_name("追尾独立確認.py"))}
    if any(proof.get(k) != v for k, v in expected.items()):
        raise ValueError("独立準備の成功又は現在版bindに差")
    if not proof.get("依存コードSHA256") or any(O.sha(ROOT/n) != h for n, h in proof["依存コードSHA256"].items()):
        raise ValueError("独立依存に差")
    return proof


def freeze(study: Path, work: Path) -> dict:
    """主独立準備・最終人工・旧固定継承を正式結果前に必須接続する。

    引数: study/work(Path)は43の保存先。
    返り値: dictは447旧pinsを継承した新固定。結果は上書きしない。
    """
    if (study/"結果.json").exists():
        raise ValueError("既存結果を上書きしません")
    entry_ref, control_ref, numeric_ref = [validate_reference(study, n) for n in ("入口参照.json", "対照参照.json", "指標参照.json")]
    prepared = W.read_json(work/"準備点検.json")
    for k, v in current_bindings(study).items():
        if prepared.get(k) != v:
            raise ValueError("主準備の現在版bindに差")
    if prepared["ラベル計算"] or prepared["損益計算"] or prepared.get("旧A0純登録同値") is not True or prepared.get("旧A0登録数") != 245:
        raise ValueError("主非損益準備に差")
    independent = validate_independent(study, work)
    synthetic_path = ROOT/"work/CMF変化/合成検証.json"
    synthetic = W.read_json(synthetic_path)
    if synthetic.get("全件成功") is not True or synthetic.get("合成編集終了") is not True:
        raise ValueError("最終人工成功前")
    finance = W.read_json(work/"会計人工接続.json")
    if finance.get("全件一致") is not True or finance.get("不一致数") != 0 or finance.get("人工経路数") != 12:
        raise ValueError("人工会計の接続成功前")
    required_finance = {"scripts/CMF変化/独立監査.py", "scripts/CMF変化/運用.py", "work/CMF変化/00043/会計人工接続.py"}
    if not isinstance(finance.get("コードSHA256"), dict) or not required_finance <= set(finance["コードSHA256"]):
        raise ValueError("人工会計の必須出典が不足")
    if finance.get("条件SHA256") != O.sha(study/"条件.json") or finance.get("実行中code不変") is not True:
        raise ValueError("人工会計の条件又は実行中版に差")
    for name, expected in finance["コードSHA256"].items():
        if O.sha(ROOT/name) != expected:
            raise ValueError("人工会計の版bindに差")
    if O.sha(PREVIOUS/"固定.json") != PREVIOUS_LOCK_SHA:
        raise ValueError("直前42固定に差")
    pins = dict(W.read_json(PREVIOUS/"固定.json")["ファイルSHA256"])
    if any(O.sha(ROOT/n) != h for n, h in pins.items()):
        raise ValueError("旧固定出典に差")
    paths = [Path(__file__), *[Path(__file__).with_name(n) for n in
        ("入口.py", "運用.py", "合成検証.py", "状態独立確認.py", "追尾独立確認.py", "独立監査.py")], PREVIOUS/"固定.json",
        *[study/n for n in ("計画.md", "条件.json", "入力台帳.json", "入口参照.json", "対照参照.json", "指標参照.json")],
        *[work/n for n in ("準備点検.json", "独立準備点検.json", "診断予定.json", "会計人工接続.json", "会計人工接続.py")], synthetic_path,
        ROOT/"work/CMF変化43の事前案.md", ROOT/"work/CMF変化43の記録案.md", ROOT/"work/CMF変化43の独立案.md", ROOT/"scripts/発動値幅継続/独立監査.py", ROOT/"scripts/レポート/手法カタログ_版4.json", ROOT/"scripts/レポート/カタログ版4.py", ROOT/"docs/議論/手法と時間スケールの汎用表_版4.md", ROOT/"docs/technical-analysis/指標/CMFの変化と窓の入替え.md"]
    for ref in (entry_ref, control_ref, numeric_ref):
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
    """実行中に不変である主版・数値参照・入力を集める。

    引数: study(Path)は43。
    返り値: dictは主三コードと条件/台帳/数値参照のSHA。
    """
    return {"コードSHA256": code_pins(), "条件SHA256": O.sha(study/"条件.json"),
        "入力台帳SHA256": O.sha(study/"入力台帳.json"), "参照台帳SHA256": O.sha(MANIFEST_PATH),
        "入口参照SHA256": O.sha(study/"入口参照.json"), "対照参照SHA256": O.sha(study/"対照参照.json"), "指標参照SHA256": O.sha(study/"指標参照.json")}


# ----------------------------------------
# 準備は旧純入口/現前CMF/全採否だけ。正式で全新先着と運用を計算する。

def run(study: Path, work: Path, prepare_only: bool) -> dict:
    """固定入口/現前CMF準備/変化方向の三案を純準備又は固定後三運用で比較する。

    引数: study/work(Path)は43の保存先、prepare_only(bool)は非PnL準備。
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
    bundle = read_bundle(study)
    old_pure = {r["イベントID"]: I.pure_signal(r, "D0") for rows in bundle["pure"].values() for r in rows}
    old_labels = {r["イベントID"]: {k: r[k] for k in LABEL_FIELDS} for r in read_rows(shared_path(ref, "入口事例.jsonl.gz")) if r["入口ID"] == "3分_A0"} if not prepare_only else None
    previous_details, previous_logs = {}, defaultdict(list)
    if not prepare_only:
        previous_details = {r["場"]: r for r in read_rows(shared_path(control, "全運用詳細.jsonl.gz")) if r["候補ID"] == CONTROL_ID}
        for row in read_rows(shared_path(control, "追尾.jsonl.gz")):
            if row["候補ID"] == CONTROL_ID: previous_logs[row["場"]].append(row)
    prepared, inputs, controls, all_old = [], [], [], set()
    cases, infos, trades = defaultdict(list), defaultdict(list), defaultdict(list)
    with ExitStack() as stack:
        streams = {n: stack.enter_context(compressed(work/n)) for n in FILES} if not prepare_only else {}
        for entry in manifest["entries"]:
            session, period = entry["session"], E.phase_of(entry["session"], config)
            block = build_session(entry, manifest, bundle, config, not prepare_only)
            pure = [r for p in I.POLICIES for r in block["signals"]["3分_"+p]]
            for row in block["signals"]["3分_D0"]:
                old_id = row["イベントID"][:-3]+"_A0"
                if row != old_pure[old_id]: raise ValueError("固定42A0純13列の完全対照に差")
                all_old.add(old_id)
            record = {"場": session, "期間": period, "純信号": pure, "純信号内容SHA256": canonical_sha(pure),
                "純信号判断SHA256": canonical_sha([decision_signal(r) for r in pure]),
                "判定": block["decisions"], "判定SHA256": canonical_sha(block["decisions"]),
                "判定判断SHA256": canonical_sha(decision_projection(block["decisions"])),
                "全3分投影SHA256": canonical_sha([I.frame_projection(r) for r in bundle["lower"][session]]), "3分投影足数": len(bundle["lower"][session]), "入力品質": block["input_quality"],
                "全CMF投影SHA256": canonical_sha(block["volume_panels"]), "CMF足数": len(block["volume_panels"])}
            inputs.append({"期間": period, **block["input_quality"]})
            if prepare_only:
                prepared.append(record)
                print(f"00043 {session} 固定42A0/現前CMF/変化の非損益準備", flush=True)
                continue
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
                    original = origin+"_A0"
                    if any(label[k] != old_labels[original][k] for k in LABEL_FIELDS):
                        raise ValueError("同時計旧42A0の11先着値に差")
                    case = {**deepcopy(signal), "期間": period, "要求時計JST": O.iso(signal["要求時計秒"]),
                        "元価格発動ID": origin, **deepcopy(bundle["metadata"][original]), "旧A0イベントID": original, **deepcopy(label)}
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
                if policy == "D0":
                    adapted, adapted_logs = rename(detail, "_D0", "_A0"), rename(logs, "_D0", "_A0")
                    if adapted != previous_details[session] or adapted_logs != previous_logs[session]:
                        raise ValueError("旧42A0の全運用/追尾に差")
                    controls.append({"場": session, "候補ID": cid, "全運用同値": True, "全追尾同値": True,
                        "旧識別子全運用内容SHA256": canonical_sha(adapted), "旧識別子追尾内容SHA256": canonical_sha(adapted_logs)})
                infos[cid].append(info)
                trades[cid].extend(state.trades)
                streams["全運用詳細.jsonl.gz"].write(D.encode(detail))
                for row in logs:
                    streams["追尾.jsonl.gz"].write(D.encode(row))
            print(f"00043 {session} 三入口三運用完了", flush=True)
    if set(old_pure) != all_old or initial != current_bindings(study):
        raise ValueError("実行中出典に差")
    if prepare_only:
        W.write_json(work/"準備点検.json", {**initial, "ラベル計算": False, "損益計算": False,
            "全66場既使用": True, "旧A0純登録同値": True, "旧A0登録数": len(all_old), "純信号whitelist": list(I.SIGNAL_FIELDS),
            "準備": prepared})
        return {"準備点検": True, "ラベル計算": False, "損益計算": False, "旧A0登録数": len(all_old)}
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
        for role in ("順行", "反転"):
            local = {p: E.entry_metrics([r for r in cases[sid] if r["期間"] == p and r["役割"] == role], p) for p in PERIODS}
            support, goal = D.entry_flags(local, config)
            role_entries.append({"入口ID": sid, "役割": role, **local, "入口支持": support, "70目標": goal})
    report = {"全66場既使用": True, "入口評価": entrances, "役割別入口評価": role_entries, "結果": results, "表示固定ID": ids,
        "入口評価数": 3, "運用候補数": 3, "現方針運用候補数": 3, "入口125250評価の変更": False,
        "入口70目標達成数": sum(r["70目標"] for r in entrances), "費用資格数": sum(r["費用資格"] for r in results),
        "現方針費用資格数": sum(r["費用資格"] and r["現方針候補"] for r in results), "採用資格数": sum(r["採用資格"] for r in results),
        "位置付け": "固定42A0と全jをread共有。D0完全対照から現前CMF準備D1/変化方向D2を分離し、当足/窓脱落は診断のみ。旧水準A2全体との差を変化だけの効果としない"}
    W.write_json(study/"入力品質.json", inputs)
    W.write_json(study/"D0対照同値.json", {"全件一致": True, "旧先着全件同値": True, "場候補数": len(controls),
        "照合": controls, "入口参照SHA256": initial["入口参照SHA256"], "対照参照SHA256": initial["対照参照SHA256"]})
    W.write_csv(study/"全候補_場別.csv", [r for cid in ids for r in infos[cid]])
    E.publish_details(study, work/"全運用詳細.jsonl.gz", ids, manifest, "")
    catalog = W.read_json(study/"一覧.resources.json")
    for resource in catalog["resources"]:
        resource["id"] = resource["id"].replace("00008_", "00043_", 1)
    W.write_json(study/"一覧.resources.json", catalog)
    W.write_json(study/"作業成果物.json", {"原板複製": False, "展開内容SHA256が正本": True,
        "共有参照": ["入口参照.json", "対照参照.json", "指標参照.json"], "ファイル": [{"パス": (work/n).relative_to(ROOT).as_posix(),
            "展開内容SHA256": content_sha(work/n), "圧縮SHA256参考": O.sha(work/n), "圧縮バイト": (work/n).stat().st_size} for n in FILES]})
    W.write_json(study/"結果.json", report)
    return {k: report[k] for k in ("入口評価数", "運用候補数", "入口70目標達成数", "現方針費用資格数", "採用資格数")}


def main() -> None:
    """純準備又は固定後の一回正式比較を起動する。

    引数: なし。CLIは--study/--work/--prepare。
    返り値: None。市場起動はroot。
    """
    parser = argparse.ArgumentParser(description="再テスト時のCMF変化方向")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.study.resolve(), args.work.resolve(), args.prepare), ensure_ascii=False))


if __name__ == "__main__":
    main()
