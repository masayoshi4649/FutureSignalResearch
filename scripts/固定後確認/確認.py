"""固定26の全三案を変更せず、旧65場の助走後に新一場だけ確認する。"""

from contextlib import ExitStack
from datetime import datetime
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00027_試行00026の新Night固定後確認"
WORK = ROOT/"work/固定後確認/00027"
OLD_STUDY = ROOT/"study/00026_反転のSAR確認時刻と順行持続"
PERIOD = "固定後確認"
IDS = ["3分_"+p+"_X0" for p in ("N0", "N1", "N2")]
TECHNICAL = ("全局面.jsonl.gz", "上位足.jsonl.gz", "30分窓.jsonl.gz", "SAR.jsonl.gz",
    "全複合context.jsonl.gz", "監視.jsonl.gz", "反転監視.jsonl.gz")
ALL_FILES = ("全運用詳細.jsonl.gz", "入口事例.jsonl.gz", "全複合shadow.jsonl.gz", "追尾.jsonl.gz", *TECHNICAL)
LARGE_FIELDS = ("全Q発動記録", "複合context記録", "監視trace", "エピソード診断", "反転監視trace", "反転監視診断", "ATR検算列", "ATR全足検算列")


def module(path: Path, name: str) -> Any:
    """固定処理をコマンド実行せず読み込む。

    引数: path(Path)はコード、name(str)は識別名。
    返り値: Anyは読取モジュール。原板やcacheを開く入口にはしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


D = module(ROOT/"scripts/反転確認時計/検証.py", "固定後確認の固定26主処理")
X = module(Path(__file__).with_name("抽出.py"), "固定後確認の予約入力抽出")
ENGINE = module(ROOT/"scripts/反転確認時計/運用.py", "固定後確認の固定26単一建玉")
read_json, write_json = D.W.read_json, D.W.write_json


def sha(path: Path) -> str:
    """既知のコード・証拠を指紋化する。

    引数: path(Path)は対象。
    返り値: strはSHA256。新原板をこの関数へ渡して開封を先行しない。
    """
    return X.PREP.hash_file(path)


def code_pins() -> dict:
    """27主・抽出の現在版だけを返す。

    引数: なし。
    返り値: dictは二コードのパスとSHA。
    """
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in (Path(__file__), Path(__file__).with_name("抽出.py"))}


def validate_pointer(study: Path = STUDY) -> tuple[dict, dict, Path]:
    """26条件/固定・全三案・旧65場を照合し、新内容を開かない。

    引数: study(Path)は27試行。
    返り値: tuple[dict,dict,Path]は参照条件/固定26条件/旧台帳。予約の内容hashは計算しない。
    """
    pointer = read_json(study/"条件参照.json")
    config_path = (study/pointer["条件参照"]).resolve()
    fixed_path = (study/pointer["固定参照"]).resolve()
    if pointer["条件SHA256"] != sha(OLD_STUDY/"条件.json") or pointer["固定SHA256"] != sha(OLD_STUDY/"固定.json"):
        raise ValueError("参照先と指紋を同時に変えて固定26正本を差し替えません")
    if sha(config_path) != pointer["条件SHA256"] or sha(fixed_path) != pointer["固定SHA256"]:
        raise ValueError("固定26の参照指紋が変化")
    fixed, config = read_json(fixed_path), read_json(config_path)
    for name, digest in fixed["ファイルSHA256"].items():
        if sha(ROOT/name) != digest:
            raise ValueError("固定26依存が変化: "+name)
    if pointer["確認候補"] != IDS or [s["入口ID"]+"_X0" for s in D.sources(config)] != IDS:
        raise ValueError("事前の全N0/N1/N2を変更しません")
    manifest_path = D.INPUT
    manifest = read_json(manifest_path)
    if len(manifest["entries"]) != 65 or pointer["新規確認場"] in {e["session"] for e in manifest["entries"]}:
        raise ValueError("旧65場と新規確認一場を分ける必要があります")
    if not all(e["symbol"] == "NK225" for e in manifest["entries"]):
        raise ValueError("旧助走は固定NK225だけ")
    if {p: sum(D.E.phase_of(e["session"], config) == p for e in manifest["entries"]) for p in D.PERIODS} != dict(zip(D.PERIODS, (40, 24, 1))):
        raise ValueError("固定26の旧40/24/1場から助走を変更しません")
    return pointer, config, manifest_path


class Banks:
    """持続する数値銀行だけを持ち、注文/価格/h監視を持ち越さない。"""

    def __init__(self) -> None:
        """固定26の銀行を空状態で用意する。

        引数: なし。
        返り値: None。場内のI.generate/ENGINE.replayは毎場別呼出しにする。
        """
        self.indicators = {n: D.J.Indicators() for n in (3, 15)}
        self.channel = D.J.ChannelBank()
        self.sar = D.J.SARBank()
        self.contract = None


def build_session(entry: dict, cache: Path, banks: Banks, config: dict) -> dict:
    """一場の技術状態だけを固定26と同じ順に生成する。

    引数: entry(dict)は台帳、cache(Path)は八列、banks(Banks)は数値助走、config(dict)は固定26条件。
    返り値: dictは足/全原発動/採用と品質。先着・注文・損益を計算しない。
    """
    contract = tuple(entry["in_session_contract_codes"])
    if len(contract) != 1:
        raise ValueError("場内限月が一意でありません")
    if banks.contract is not None and contract != banks.contract:
        banks.indicators = {n: D.J.Indicators() for n in (3, 15)}
    banks.contract = contract
    session = entry["session"]
    begin, finish, cutoff, deadline = D.W.OLD.shared.legacy.session_times(session)
    start, end = begin.timestamp(), finish.timestamp()
    events, previous_now = [], -math.inf
    for event in D.W.PREP.read_events(cache):
        if math.isfinite(event.now) and start <= event.now <= end and event.now >= previous_now:
            events.append(event)
            previous_now = event.now
    frames, tails = {}, {}
    for size, bank in banks.indicators.items():
        formed = D.W.bars_from_events(events, start, end, size)
        frames[size] = D.J.features(formed, bank, start)
        tails[size] = max(0, int((end-start)//(size*60))-1-(formed[-1]["index"] if formed else -1))
        if tails[size]:
            bank.__init__()
    frames[30] = D.W.bars_from_events(events, start, end, 30)
    tails[30] = max(0, int((end-start)//1800)-1-(frames[30][-1]["index"] if frames[30] else -1))
    channels, channel_info = banks.channel.build(frames[30], session, contract, tails[30])
    sar, sar_info = banks.sar.build(frames[3], session, contract, tails[3])
    quantities, quantity_info = D.Q.aggregate(events, frames[3], start, end, 3)
    regimes, regime_info = D.I.classify(frames[15], session, config)
    signals, quality = D.generate_or_empty(frames[3], frames[15], session, 3, cutoff.timestamp(), deadline.timestamp(),
        config, regimes, channels, quantities, sar)
    return {"場": session, "events": events, "frames": frames, "signals": signals, "quality": quality,
        "channels": channels, "sar": sar, "regimes": regimes, "channel_info": channel_info,
        "sar_info": sar_info, "regime_info": regime_info, "quantity_info": quantity_info,
        "cutoff": cutoff.timestamp(), "deadline": deadline.timestamp(),
        "input_info": {"場": session, "正常板数": sum(e.valid for e in events),
            "確定足数": {str(n): sum(f["publish"] for f in values) for n, values in frames.items()},
            "尾部欠枠": {str(n): count for n, count in tails.items()}}}


def technical_rows(block: dict, period: str) -> dict:
    """固定26と同じJSONL順序の七つの技術系列を組み立てる。

    引数: block(dict)は一場の技術生成結果、period(str)は表示区分。
    返り値: dictは系列名と保存行配列。先着/損益列を読まない。
    """
    q, session = block["quality"], block["場"]
    return {"全局面.jsonl.gz": [{"期間": period, **r} for r in block["regimes"]],
        "上位足.jsonl.gz": [{"場": session, "期間": period, **r} for size in (15, 30) for r in block["frames"][size]],
        "30分窓.jsonl.gz": [{"期間": period, **r} for r in block["channels"]],
        "SAR.jsonl.gz": [{"期間": period, **r} for r in block["sar"]],
        "全複合context.jsonl.gz": [{"期間": period, **r} for r in q["複合context記録"]],
        "監視.jsonl.gz": [{"種別": "足監視", "期間": period, **r} for r in q["監視trace"]]
            +[{"種別": "監視終了診断", "場": session, "期間": period, **r} for r in q["エピソード診断"]],
        "反転監視.jsonl.gz": [{"種別": "反転足監視", "期間": period, **r} for r in q["反転監視trace"]]
            +[{"種別": "反転終了診断", "場": session, "期間": period, **r} for r in q["反転監視診断"]]}


def encode(row: dict) -> str:
    """固定26と同じ日本語JSONL表現を使う。

    引数: row(dict)は保存行。
    返り値: strは改行付きJSON。非有限値は拒否する。
    """
    return json.dumps(row, ensure_ascii=False, allow_nan=False)+"\n"


def summary_quality(block: dict, period: str) -> dict:
    """大きな全件列を重複させず場別品質を保存する。

    引数: block(dict)は生成結果、period(str)は表示区分。
    返り値: dictは固定26品質と同じ小型項目。
    """
    return {**{k: v for k, v in block["quality"].items() if k not in LARGE_FIELDS}, "期間": period}


def warmup(study: Path = STUDY, work: Path = WORK) -> tuple[Banks, dict]:
    """旧65場だけで全数値銀行を再現し保存26技術系列へ照合する。

    引数: study/work(Path)は27の計画とGit外出力。
    返り値: tuple[Banks,dict]はlive銀行と助走証拠。新原板/CSV/cache、先着、運用を呼ばない。
    """
    initial_codes = code_pins()
    pointer, config, manifest_path = validate_pointer(study)
    manifest = read_json(manifest_path)
    artifacts = read_json(OLD_STUDY/"作業成果物.json")
    expected_streams = {Path(r["パス"]).name: r["展開内容SHA256"] for r in artifacts["ファイル"]}
    expected_quality = {r["場"]: r for r in read_json(OLD_STUDY/"入口品質.json")}
    quality_files = {name: {r["場"]: r for r in read_json(OLD_STUDY/name)} for name in
        ("入力品質.json", "30窓品質.json", "SAR品質.json", "局面品質.json", "数量診断品質.json")}
    digests, counts, checks, errors = {n: hashlib.sha256() for n in TECHNICAL}, {n: 0 for n in TECHNICAL}, 0, []
    banks, sessions = Banks(), []
    for entry in manifest["entries"]:
        source = Path(manifest["source_root"])/entry["source_path"]
        stat = source.stat()
        cache = ROOT/"work/複合検証"/entry["cache_path"]
        if (stat.st_size, stat.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]) or sha(cache) != entry["sha256_cache"]:
            raise ValueError("旧助走入力の指紋が変化")
        block = build_session(entry, cache, banks, config)
        period = D.E.phase_of(entry["session"], config)
        q = summary_quality(block, period)
        actual = {"入口品質.json": q, "入力品質.json": {**block["input_info"], "期間": period},
            "30窓品質.json": {"場": entry["session"], "期間": period, **block["channel_info"]},
            "SAR品質.json": {"期間": period, **block["sar_info"]},
            "局面品質.json": {"場": entry["session"], "期間": period, **block["regime_info"]},
            "数量診断品質.json": {"場": entry["session"], "期間": period, **block["quantity_info"]}}
        for name, row in actual.items():
            expected = expected_quality[entry["session"]] if name == "入口品質.json" else quality_files[name][entry["session"]]
            checks += 1
            if row != expected:
                errors.append({"場": entry["session"], "対象": name, "不一致列": sorted(k for k in row.keys() | expected.keys() if row.get(k) != expected.get(k))})
        for name, rows in technical_rows(block, period).items():
            for row in rows:
                digests[name].update(encode(row).encode("utf-8"))
                counts[name] += 1
        sessions.append({"場": entry["session"], "期間": period, "cacheSHA256": entry["sha256_cache"],
            "入口品質": q, "SAR品質": actual["SAR品質.json"], "30窓品質": actual["30窓品質.json"],
            "局面品質": actual["局面品質.json"], "入力品質": actual["入力品質.json"]})
        print("00027旧助走 "+entry["session"]+" 技術だけ完了", flush=True)
    streams = []
    for name in TECHNICAL:
        digest = digests[name].hexdigest()
        same = digest == expected_streams[name]
        checks += 1
        if not same:
            errors.append({"対象": name, "期待SHA256": expected_streams[name], "実SHA256": digest})
        streams.append({"系列": name, "件数": counts[name], "展開SHA256": digest, "固定26同値": same})
    if code_pins() != initial_codes:
        raise ValueError("助走実行中に27コードが変更")
    proof = {"全件一致": not errors, "照合項目数": checks, "不一致数": len(errors), "不一致": errors,
        "旧助走場数": 65, "新規原板閲覧": False, "新規cache閲覧": False, "先着計算": False, "損益計算": False,
        "コードSHA256": initial_codes, "条件参照SHA256": sha(study/"条件参照.json"),
        "旧入力台帳SHA256": sha(manifest_path), "参照26固定SHA256": pointer["固定SHA256"],
        "技術系列": streams, "場別": sessions, "場内状態": "各場の価格/h監視はI.generateで初期化、運用/建玉/注文は助走で作らない",
        "一致の範囲": "固定26処理と同じ65場/順序/全銀行更新・未公開数値/尾部/限月規約を再実行。七技術系列全文と全場品質/原発動重要列・反転投影を保存26へ照合。独立数式証明は別担当。旧先着/会計を評価し直さない。"}
    work.mkdir(parents=True, exist_ok=True)
    write_json(work/"助走点検.json", proof)
    if errors:
        raise ValueError("固定26の旧技術系列と助走が不一致")
    return banks, proof


def fixed_files(study: Path, work: Path) -> dict:
    """開封前に固定するコード/計画/既知証拠だけを列挙する。

    引数: study/work(Path)は正式/作業先。
    返り値: dictはパスとSHA。新Nightの原板/CSV/cacheを指紋対象にしない。
    """
    _, _, manifest_path = validate_pointer(study)
    paths = [Path(__file__), Path(__file__).with_name("抽出.py"), Path(__file__).with_name("合成検証.py"),
        study/"計画.md", study/"条件参照.json", manifest_path, OLD_STUDY/"固定.json",
        OLD_STUDY/"作業成果物.json", OLD_STUDY/"入口品質.json", work/"助走点検.json",
        ROOT/"work/固定後確認/合成検証.json"]
    paths += [OLD_STUDY/n for n in ("入力品質.json", "30窓品質.json", "SAR品質.json", "局面品質.json", "数量診断品質.json", "結果.json")]
    paths += [ROOT/p for p in read_json(OLD_STUDY/"固定.json")["ファイルSHA256"]]
    return {p.relative_to(ROOT, walk_up=True).as_posix(): sha(p) for p in dict.fromkeys(paths)}


def freeze(study: Path = STUDY, work: Path = WORK) -> dict:
    """最終人工合成と旧助走の版を確認し、新原板を開かず固定する。

    引数: study/work(Path)は27保存先。
    返り値: dictは開封前固定。既存結果/初回開封/固定版変更を拒否する。
    """
    if (study/"結果.json").exists() or (work/"初回開封記録.json").exists():
        raise FileExistsError("新規確認を開始した後に開封前固定を書き換えません")
    proof = read_json(ROOT/"work/固定後確認/合成検証.json")
    if not proof.get("全件成功") or not proof.get("合成編集終了"):
        raise ValueError("最終合成成功と編集終了が必要")
    for path in (Path(__file__), Path(__file__).with_name("抽出.py"), Path(__file__).with_name("合成検証.py"), study/"条件参照.json"):
        if proof["ファイルSHA256"].get(path.relative_to(ROOT).as_posix()) != sha(path):
            raise ValueError("最終合成後に27コード/条件参照が変更")
    warm = read_json(work/"助走点検.json")
    if not warm["全件一致"] or warm["コードSHA256"] != code_pins() or warm["条件参照SHA256"] != sha(study/"条件参照.json"):
        raise ValueError("旧助走の最終一致/版が不一致")
    pointer, _, _ = validate_pointer(study)
    X.check_reservation(pointer)
    value = {"固定日時": datetime.now(D.W.JST).isoformat(), "新原板内容未閲覧": True,
        "確認候補": IDS, "新規確認場": pointer["新規確認場"], "ファイルSHA256": fixed_files(study, work),
        "Python": platform.python_version(), "NumPy": D.W.np.__version__}
    path = study/"固定.json"
    if path.exists():
        prior = read_json(path)
        if prior["ファイルSHA256"] != value["ファイルSHA256"]:
            raise ValueError("27開封前固定後に版が変更")
        return prior
    write_json(path, value)
    return value


def check_fixed(study: Path = STUDY, work: Path = WORK) -> dict:
    """開封前固定が現コード/計画/旧証拠と一致するか検査する。

    引数: study/work(Path)は27保存先。
    返り値: dictは固定値。不一致又は未固定なら新入力を開く前に例外。
    """
    locked = read_json(study/"固定.json")
    if locked["確認候補"] != IDS or locked["ファイルSHA256"] != fixed_files(study, work):
        raise ValueError("27開封前固定と現在版が不一致")
    return locked


# ----------------------------------------
# ここから先は固定＋root開封承認後の新一場だけを扱う。

def run(study: Path = STUDY, work: Path = WORK, open_authorized: bool = False) -> dict:
    """予約一場を開封し、同じ助走銀行から全三案を一回確認する。

    引数: study/work(Path)は27保存先、open_authorized(bool)はrootの明示開封承認。
    返り値: dictは新一場の入口/三運用と旧資格。旧65の約定/損益を合算しない。
    """
    if not open_authorized:
        raise ValueError("root開封承認後の--開封実行だけで新規確認します")
    if (study/"結果.json").exists() or (work/"初回開封記録.json").exists():
        raise FileExistsError("既存結果/初回開封を上書きしません")
    locked = check_fixed(study, work)
    pointer, config, manifest_path = validate_pointer(study)
    X.check_reservation(pointer)
    banks, warm = warmup(study, work)
    check_fixed(study, work)
    manifest = X.extract(pointer, work, sha(study/"固定.json"), authorized=True)
    try:
        check_fixed(study, work)
        entry = manifest["entries"][0]
        cache = (ROOT/"work/複合検証"/entry["cache_path"]).resolve()
        if cache != (work/"キャッシュ/NK225"/(entry["session"]+".npz")).resolve() or not cache.is_relative_to(work.resolve()):
            raise ValueError("新規cacheの解決先が不正")
        if sha(cache) != entry["sha256_cache"]:
            raise ValueError("新cache指紋不一致")
        block = build_session(entry, cache, banks, config)
        old_manifest = read_json(manifest_path)
        write_json(work/"結合入力台帳.json", {**manifest, "entries": old_manifest["entries"]+[entry],
            "旧助走場数": 65, "新規確認場数": 1, "旧助走台帳SHA256": sha(manifest_path)})
        # ----------------------------------------
        # 技術と先着を保存し、運用へはラベルなしのsignalだけを渡す。
        cases, details, infos, paths = [], [], [], {name: work/name for name in ALL_FILES}
        with ExitStack() as stack:
            streams = {n: stack.enter_context(D.output_stream(p, True)) for n, p in paths.items()}
            for name, rows in technical_rows(block, PERIOD).items():
                for row in rows:
                    streams[name].write(encode(row))
            path = D.W.OLD.気配経路([e for e in block["events"] if e.valid])
            label_cache = {}
            for raw in block["quality"]["全Q発動記録"]:
                label = D.shadow_label(raw, path, label_cache, block["cutoff"], block["deadline"], config)
                streams["全複合shadow.jsonl.gz"].write(encode({"期間": PERIOD, **raw, **label}))
            for source in D.sources(config):
                signals = block["signals"][source["入口ID"]]
                for signal in signals:
                    signal.update(期間=PERIOD, 要求時計JST=D.O.iso(signal["要求時計秒"]))
                    label = D.shadow_label(signal, path, label_cache, block["cutoff"], block["deadline"], config)
                    case = {**signal, **label}
                    cases.append(case)
                    streams["入口事例.jsonl.gz"].write(encode(case))
                cid = source["入口ID"]+"_X0"
                state, info = ENGINE.replay(block["events"], signals, block["frames"][3], entry["session"], cid,
                    config["運用"], config["出口"][0], source["役割"])
                begin, finish, _, _ = D.W.OLD.shared.legacy.session_times(entry["session"])
                info.update(期間=PERIOD, 場時間分=(finish.timestamp()-begin.timestamp())/60)
                for trade in state.trades:
                    trade["期間"] = PERIOD
                detail = {"候補ID": cid, "場": entry["session"], "品質": info, "約定": state.fills,
                    "取引": state.trades, "注文": state.orders, "入口取扱": state.signals}
                details.append(detail)
                infos.append(info)
                streams["全運用詳細.jsonl.gz"].write(encode(detail))
                for record in state.normal_log:
                    streams["追尾.jsonl.gz"].write(encode({"期間": PERIOD, **record}))
        # ----------------------------------------
        # 新一場の率と、旧26の支持/70/費用資格を別の欄へ置く。
        old_result = read_json(OLD_STUDY/"結果.json")
        old_rows = {r["候補ID"]: r for r in old_result["結果"]}
        results, entrances = [], []
        for source in D.sources(config):
            cid = source["入口ID"]+"_X0"
            local = [r for r in cases if r["入口ID"] == source["入口ID"]]
            entrance = D.E.entry_metrics(local, PERIOD)
            entrances.append({**source, "新規確認": entrance})
            detail = next(d for d in details if d["候補ID"] == cid)
            operation = D.operation_metrics([detail["品質"]], detail["取引"], source["役割"], config["出口"][0])
            prior = old_rows[cid]
            results.append({"候補ID": cid, "入口": source, "出口": config["出口"][0],
                "新規確認": {"入口": entrance, "運用": operation},
                "旧26資格": {"入口支持": prior["入口支持"], "70目標": prior["70目標"], "費用資格": prior["費用資格"]}})
        report = {"新規確認場": entry["session"], "新規確認場数": 1, "確認候補": IDS,
            "期間": PERIOD, "旧助走場数": 65, "旧場損益合算": False, "条件変更": False,
            "新規場確認前未使用": True, "確認後は既使用": True, "入口評価": entrances, "結果": results,
            "表示固定ID": IDS, "新1場による支持代用": False, "参照26結果SHA256": sha(OLD_STUDY/"結果.json"),
            "27固定SHA256": sha(study/"固定.json"), "位置付け": "固定26の全三案を一新規場で確認。1場の率/黒字だけで支持付き70%や安定収益を達成したとしない。"}
        write_json(study/"入力台帳.json", manifest)
        write_json(study/"助走参照.json", {"旧入力台帳": D.INPUT.relative_to(study, walk_up=True).as_posix(),
            "旧入力台帳SHA256": sha(manifest_path), "助走証拠": (work/"助走点検.json").relative_to(ROOT).as_posix(),
            "助走証拠SHA256": sha(work/"助走点検.json"), "全件一致": warm["全件一致"], "旧場損益合算": False})
        for name, value in (("入口品質.json", summary_quality(block, PERIOD)), ("入力品質.json", {**block["input_info"], "期間": PERIOD}),
            ("SAR品質.json", {"期間": PERIOD, **block["sar_info"]}), ("30窓品質.json", {"場": entry["session"], "期間": PERIOD, **block["channel_info"]}),
            ("局面品質.json", {"場": entry["session"], "期間": PERIOD, **block["regime_info"]}),
            ("数量診断品質.json", {"場": entry["session"], "期間": PERIOD, **block["quantity_info"]})):
            write_json(study/name, [value])
        D.W.write_csv(study/"全候補_場別.csv", infos)
        D.E.publish_details(study, paths["全運用詳細.jsonl.gz"], IDS, manifest, "")
        catalog = read_json(study/"一覧.resources.json")
        for resource in catalog["resources"]:
            resource["id"] = resource["id"].replace("00008_", "00027_", 1)
        write_json(study/"一覧.resources.json", catalog)
        write_json(study/"作業成果物.json", {"原板複製": False, "展開内容SHA256が正本": True,
            "ファイル": [{"パス": p.relative_to(ROOT).as_posix(), "展開内容SHA256": D.content_sha(p),
                "圧縮SHA256参考": sha(p), "圧縮バイト": p.stat().st_size} for p in paths.values()]})
        X.check_reservation(pointer)
        if sha(cache) != entry["sha256_cache"]:
            raise ValueError("新規確認実行中にcache内容が変化")
        if check_fixed(study, work) != locked:
            raise ValueError("新規確認実行中に固定が変化")
        write_json(study/"結果.json", report)
        write_json(work/"新規確認実行記録.json", {"状態": "初回新規確認完了", "結果SHA256": sha(study/"結果.json"),
            "27固定SHA256": sha(study/"固定.json"), "旧助走のみ": True, "旧場損益合算": False,
            "終了日時": datetime.now(D.W.JST).isoformat(), "入力台帳SHA256": sha(work/"新規入力台帳.json")})
        return report
    except BaseException as error:
        write_json(work/"新規確認実行記録.json", {"状態": "初回開封後の確認失敗", "例外型": type(error).__name__,
            "理由": str(error), "27固定SHA256": sha(study/"固定.json"), "失敗日時": datetime.now(D.W.JST).isoformat(),
            "再度未見としない": True})
        raise


def main() -> None:
    """助走・開封前固定・承認後確認を別の明示操作にする。

    引数: なし。CLIは--warmup/--freeze/--開封実行の一つと--study/--workを受け取る。
    返り値: None。無指定では新資料を読まず終了する。
    """
    import argparse
    parser = argparse.ArgumentParser(description="固定26全三案の新一場確認")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--warmup", action="store_true")
    group.add_argument("--freeze", action="store_true")
    group.add_argument("--開封実行", action="store_true")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    args = parser.parse_args()
    study, work = args.study.resolve(), args.work.resolve()
    if args.warmup:
        _, result = warmup(study, work)
        output = {k: result[k] for k in ("全件一致", "照合項目数", "不一致数", "旧助走場数", "新規原板閲覧", "先着計算", "損益計算")}
    elif args.freeze:
        result = freeze(study, work)
        output = {"開封前固定": True, "確認候補": result["確認候補"], "新原板内容未閲覧": True}
    else:
        result = run(study, work, open_authorized=True)
        output = {"新規確認完了": True, "新規確認場": result["新規確認場"], "確認候補": result["確認候補"], "旧場損益合算": False}
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
