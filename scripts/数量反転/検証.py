"""00014の固定12入口・12運用を、既使用65場で再現する。"""

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
from pathlib import Path
import platform
import sys
from typing import Any, Iterator, TextIO

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00014_反転入口と観測差分量"
WORK = ROOT / "work/数量反転/00014"
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


I = module(Path(__file__).with_name("入口.py"), "数量反転の入口生成")
E = module(ROOT / "scripts/外部探索/探索.py", "数量反転研究の共通集計")
W, O = E.W, E.O
Q = module(Path(__file__).with_name("数量.py"), "数量反転の観測差分集約")


@contextmanager
def compressed(path: Path) -> Iterator[TextIO]:
    """時刻と元ファイル名を埋めない作業gzipの書込先を作る。

    引数: path (Path) はGit外の保存先。
    返り値: Iterator[TextIO] はUTF-8テキスト出力先。
    """
    with path.open("wb") as binary, gzip.GzipFile(filename="", fileobj=binary, mode="wb", mtime=0) as archive:
        with io.TextIOWrapper(archive, encoding="utf-8", newline="\n") as text:
            yield text


def content_sha(path: Path) -> str:
    """作業gzipの展開内容を指紋化する。

    引数: path (Path) はgzip。
    返り値: str は展開内容SHA256。圧縮ファイル指紋と区別する。
    """
    digest = hashlib.sha256()
    with gzip.open(path, "rb") as stream:
        while block := stream.read(1024*1024):
            digest.update(block)
    return digest.hexdigest()


def sources(config: dict) -> list[dict]:
    """固定3足・2価格パターン・2数量補助から12入口を列挙する。

    引数: config (dict) は固定条件。
    返り値: list[dict] は12入口ID・価格系統・数量補助・反転役割。
    """
    if config["時間足分"] != [1,3,5] or config["入口系統"] != list(I.FAMILIES) or config["補助"] != list(I.EXTRAS) or config["出口"] != [{"出口ID":"X0"}]:
        raise ValueError("固定3足×2価格系統×2数量補助・X0と異なります")
    if (config["数量条件"]["参照足数"], config["数量条件"]["RVOL下限"], config["数量条件"]["数量準備両側共通"], config["逆行pt"], config["順行pt"]) != (20,1.2,True,125,250):
        raise ValueError("数量20足・RVOL1.2・共通準備・125/250を変更しません")
    return [{"入口ID":f"{size}分_{family}_{extra}","入口系統":family,"時間足分":size,"補助":extra,
             "名称":I.FAMILIES[family],"役割":"反転"}
            for size in config["時間足分"] for family in config["入口系統"] for extra in config["補助"]]


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
    inherited = W.read_json(INPUT.parent / "選定固定.json")["ファイルSHA256"]
    paths = [Path(__file__), Path(__file__).with_name("入口.py"), Path(__file__).with_name("数量.py"), ROOT/"scripts/テクニカル循環/運用.py",
             Path(__file__).with_name("合成検証.py"),
             ROOT / "scripts/利益回収/運用.py", ROOT / "scripts/利益回収/合成検証.py",
             ROOT / "scripts/広域研究/合成検証.py", ROOT / "scripts/広域研究/運用の合成検証.py",
             study / "計画.md", study / "条件.json", pointer_path, INPUT]
    paths += [ROOT / name for name in inherited]
    previous_lock = ROOT / "study/00011_順行と反転のチャート構造と利益回収/固定.json"
    paths.append(previous_lock)
    previous_pins = W.read_json(previous_lock)["ファイルSHA256"]
    if any(O.sha(ROOT/name) != digest for name, digest in previous_pins.items()):
        raise ValueError("参照する既存core・入力の固定版が変更されました")
    paths += [ROOT / name for name in previous_pins]
    pins = {p.relative_to(ROOT).as_posix(): O.sha(p) for p in dict.fromkeys(paths)}
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
# 出口は固定X0だけを使い、入口と運用の分母を分けて集計する。

def operation_metrics(infos: list[dict], trades: list[dict], role: str, policy: dict) -> dict:
    """固定X0会計へ一場DDと観測MFE診断を付ける。

    引数: infos/trades (list[dict]) は場別・完結取引、role (str) は役割、policy (dict) は固定X0。
    返り値: dict は基準/追加費用・品質・活動・MFE集計。
    """
    if policy != {"出口ID": "X0"}:
        raise ValueError("固定X0以外の出口を追加しません")
    result = E.operation_metrics(infos, trades)
    result.update(期間内最大場内DD円=max((i["観測含み込み最大DD円"] for i in infos), default=0),
                  最悪場内時価円=min((i["観測最悪時価円"] for i in infos), default=0),
                  基準赤字取引数=sum(t["基準純損益円"] < 0 for t in trades),
                  利確要求返済数=sum(t["返済理由"] == "利確" for t in trades),
                  初期125保護返済数=sum(t["返済理由"] == "保護" for t in trades))
    result["活動場赤字率"] = result["赤字場数"]/result["活動場数"] if result["活動場数"] else None
    for threshold in (20, 50, 100):
        reached = [t for t in trades if t["観測最大順行pt"] >= threshold]
        result[f"{threshold}pt到達取引"] = len(reached)
        result[f"{threshold}pt後純赤字"] = sum(t["基準純損益円"] < 0 for t in reached)
    return result


def entry_flags(result: dict, config: dict) -> tuple[bool, bool]:
    """旧二期間だけから支持と入口70%目標を判定する。

    引数: result/config (dict) は12入口の一集約と固定規則。
    返り値: tuple[bool,bool] は支持と目標。既使用最終1場を選定へ使わない。
    """
    support = all(W.supported(result[p], limits) for p, limits in config["入口支持"].items())
    goal = support and all(result[p]["確認率"] >= config["目標確認率"]
        and result[p]["30分間引き_約定候補数"] >= config["間引き必要件数"][p]
        and result[p]["30分間引き_確認率"] >= config["目標確認率"] for p in PERIODS[:2])
    return support, bool(goal)


def blank_label() -> dict:
    """確認遅延で新規できない入口ラベルを作る。

    引数: なし。
    返り値: dict は未約定と欠測。仮の価格を補わない。
    """
    return {"ラベル": "未約定", "理由": "足確定確認遅延30秒超", **{key: None for key in
            ("新規価格", "新規時計秒", "判定時計秒", "判定原板行", "新規原板行", "判定気配", "最大順行pt", "最大逆行pt", "所要分")}}


# ----------------------------------------
# 全65場を同じ準備と指標履歴で処理し、入口先着は12集合に一度だけ付ける。

def run(study: Path, work: Path) -> dict:
    """固定後の入口・出口比較を実行し、小型成果物を保存する。

    引数: study/work (Path) は正式試行・Git外の大きな作業先。
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
    freeze(study)
    engine = module(ROOT/"scripts/テクニカル循環/運用.py", "数量反転研究の固定X0運用")
    work.mkdir(parents=True, exist_ok=True)
    details, cases = work / "全運用詳細.jsonl.gz", work / "入口事例.jsonl.gz"
    price_cases, quantities_file = work/"基準価格入口.jsonl.gz", work/"数量足.jsonl.gz"
    infos, trades, entry_cases = defaultdict(list), defaultdict(list), defaultdict(list)
    quality, entry_quality, quantity_quality = [], [], []
    banks = {n: W.Indicators() for n in (1, 3, 5, 15)}
    previous_contract = None
    with compressed(details) as detail_stream, compressed(cases) as case_stream, compressed(price_cases) as price_stream, compressed(quantities_file) as quantity_stream:
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
                banks = {n: W.Indicators() for n in banks}
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
                frames[size] = W.features(formed, bank, start)
                tails[size] = max(0, int((end-start)//(size*60))-1-(formed[-1]["index"] if formed else -1))
                if tails[size]:
                    bank.__init__()
            path = W.OLD.気配経路([e for e in events if e.valid])
            label_cache = {}
            for size in config["時間足分"]:
                # ----------------------------------------
                # 数量の状態を集約し、足ごとの全属性はworkだけへ残す。
                quantity_by_index, quantity_audit = Q.aggregate(events, frames[size], start, end, size)
                quantity_quality.append({"場":session,"期間":period,**quantity_audit})
                for frame in frames[size]:
                    quantity_stream.write(json.dumps({"場":session,"期間":period,"時間足分":size,
                        **{key:frame[key] for key in ("index","start","end","confirm","confirm_line","publish")},
                        **quantity_by_index[frame["index"]]},ensure_ascii=False,allow_nan=False)+"\n")
                # ----------------------------------------
                # 価格発動へ数量準備を共通に加え、RVOLの有無だけを比較する。
                if frames[size]:
                    signals_by_source, input_quality = I.generate(frames[size], frames[15], session, cutoff.timestamp(), deadline.timestamp(), config, quantity_by_index)
                else:
                    signals_by_source = {f"{size}分_{f}_{extra}": [] for f in I.FAMILIES for extra in I.EXTRAS}
                    input_quality = {"場":session,"時間足分":size,"基準価格入口数":0,"数量準備除外数":0,"数量準備通過数":0,"RVOL補助除外数":0,"基準価格入口記録":[]}
                for price_record in input_quality.pop("基準価格入口記録"):
                    price_stream.write(json.dumps({"期間":period,**price_record},ensure_ascii=False,allow_nan=False)+"\n")
                input_quality["期間"] = period
                entry_quality.append(input_quality)
                for source_id, signals in signals_by_source.items():
                    grouped[source_id] = signals
                    for signal in signals:
                        signal.update(期間=period, 要求時計JST=O.iso(signal["要求時計秒"]))
                        key = signal["要求時計秒"], signal["side"]
                        if signal["確認遅延秒"] > config["確認遅延上限秒"]:
                            label = blank_label()
                        else:
                            if key not in label_cache:
                                label_cache[key] = path.evaluate(signal["要求時計秒"], cutoff.timestamp(), deadline.timestamp(), signal["side"], adverse=config["逆行pt"], favorable=config["順行pt"])
                            label = label_cache[key]
                        case = {**signal, **label}
                        entry_cases[source_id].append(case)
                        case_stream.write(json.dumps(case, ensure_ascii=False, allow_nan=False)+"\n")
            for source in entries:
                source_id = source["入口ID"]
                for policy in config["出口"]:
                    cid = source_id + "_" + policy["出口ID"]
                    # 運用へはlabelなしsignalだけを渡す。数量は入口選別だけで、保有を取り消さない。
                    state, info = engine.replay(events, grouped[source_id], frames[source["時間足分"]], session, cid, config["運用"], policy, source["役割"])
                    info.update(期間=period, 場時間分=(end-start)/60)
                    for trade in state.trades:
                        trade["期間"] = period
                    infos[cid].append(info)
                    trades[cid].extend(state.trades)
                    detail_stream.write(json.dumps({"候補ID": cid, "場": session, "品質": info, "約定": state.fills,
                                                   "取引": state.trades, "注文": state.orders, "入口取扱": state.signals}, ensure_ascii=False, allow_nan=False)+"\n")
            quality.append({"場": session, "期間": period, "正常板数": sum(e.valid for e in events),
                            "確定足数": {str(n): sum(f["publish"] for f in values) for n, values in frames.items()}, "尾部欠枠": tails})
            print(f"00014 {session} 12入口・12運用完了", flush=True)
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
        saved_ids.extend(row["候補ID"] for row in variants)
    saved_ids = list(dict.fromkeys(saved_ids))
    report = {"全65場既使用": True, "入口評価": entry_results, "結果": results, "表示固定ID": saved_ids,
              "入口70目標達成数": sum(r["70目標"] for r in entry_results), "費用資格数": sum(r["費用資格"] for r in results),
              "入口125250評価の変更": False, "位置付け": "既使用65場で固定12案を比較する追加開発。新しい未見確認ではない"}
    W.write_json(study / "入力品質.json", quality)
    W.write_json(study / "入口品質.json", entry_quality)
    W.write_json(study / "数量品質.json", quantity_quality)
    W.write_csv(study / "全候補_場別.csv", [i for cid in infos for i in infos[cid]])
    E.publish_details(study, details, saved_ids, manifest, "")
    catalog_path = study / "一覧.resources.json"
    catalog = W.read_json(catalog_path)
    for resource in catalog["resources"]:
        resource["id"] = resource["id"].replace("00008_", "00014_", 1)
    W.write_json(catalog_path, catalog)
    W.write_json(study / "作業成果物.json", {"原板複製": False, "展開内容SHA256が正本": True,
        "ファイル": [{"パス": path.relative_to(ROOT, walk_up=True).as_posix(), "展開内容SHA256": content_sha(path),
                     "圧縮SHA256参考": O.sha(path), "圧縮バイト": path.stat().st_size} for path in (details, cases, price_cases, quantities_file)]})
    W.write_json(study / "結果.json", report)
    return {"入口数": len(entry_results), "運用候補数": len(results), "入口70目標達成数": report["入口70目標達成数"],
            "費用資格数": report["費用資格数"], "表示固定ID": saved_ids}


def main() -> None:
    """試行・作業先を指定し、固定12案を実行する。

    引数: なし。--study/--workを読む。
    返り値: None。既存結果・固定不一致は拒否する。
    """
    parser = argparse.ArgumentParser(description="反転入口と観測差分量")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    args = parser.parse_args()
    print(json.dumps(run(args.study.resolve(), args.work.resolve()), ensure_ascii=False))


if __name__ == "__main__":
    main()
