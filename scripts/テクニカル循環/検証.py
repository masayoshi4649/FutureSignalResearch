"""00011の固定8入口・24運用を、既使用65場で再現する。"""

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

import 入口 as I


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00011_順行と反転のチャート構造と利益回収"
WORK = ROOT / "work/テクニカル循環/00011"
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


E = module(ROOT / "scripts/外部探索/探索.py", "循環研究の共通集計")
W, O = E.W, E.O


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
    """固定した4系統と2足幅から8入口を列挙する。

    引数: config (dict) は条件。
    返り値: list[dict] は一意な入口ID・役割・尺度。
    """
    if config["時間足分"] != [3, 5] or list(config["入口系統"]) != list(I.FAMILIES) or config["出口"] != [{"出口ID": key} for key in ("X0", "X1", "X2")]:
        raise ValueError("事前固定した4系統×2足×3出口と異なります")
    expected = {"T1": {"名称": "押し目再開", "役割": "順行", "上位足分": 15, "EMA期間": 20, "前現上位方向保持": True},
                "T2": {"名称": "突破後再テスト", "役割": "順行", "上位足分": 15, "直前高安窓本数": 6, "待機本数": 3, "再テスト帯ティック": 1, "登録再使用": False},
                "R1": {"名称": "端の失敗突破", "役割": "反転", "直前高安窓本数": 6, "ADX上限未満": 20, "入口中心方向条件": True},
                "R2": {"名称": "BB内復帰", "役割": "反転", "BB期間": 20, "母標準偏差倍率": 2, "ADX上限未満": 20, "入口中心方向条件": True}}
    if config["入口系統"] != expected or config["逆行pt"] != 125 or config["順行pt"] != 250 or config["運用"]["呼値pt"] != 5:
        raise ValueError("この実装にない閾値変更は別試行とコード変更が必要です")
    return [{"入口ID": f"{size}分_{family}", "入口系統": family, "時間足分": size,
             "名称": I.FAMILIES[family], "役割": "順行" if family.startswith("T") else "反転"}
            for size in config["時間足分"] for family in config["入口系統"]]


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
    paths = [Path(__file__), Path(__file__).with_name("入口.py"), Path(__file__).with_name("運用.py"),
             Path(__file__).with_name("合成検証.py"), Path(__file__).with_name("入口検証.py"),
             ROOT / "scripts/利益回収/運用.py", ROOT / "scripts/利益回収/合成検証.py",
             ROOT / "scripts/広域研究/合成検証.py", ROOT / "scripts/広域研究/運用の合成検証.py",
             study / "計画.md", study / "条件.json", pointer_path, INPUT]
    paths += [ROOT / name for name in inherited]
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
# 運用差を共通の実新規と参加集合の差へ分ける。未解消は完結取引へ混ぜない。

def paired(base: list[dict], changed: list[dict]) -> dict:
    """実際の新規が同じ完結取引だけを対応させる。

    引数: base/changed (list[dict]) はX0と変更出口の完結取引。
    返り値: dict は共通・集合差と損益。実新規集合の重複は拒否する。
    """
    original, modified = {}, {}
    for target, trades in ((original, base), (modified, changed)):
        for trade in trades:
            key = (trade["入口イベントID"], trade["新規時計秒"], trade["新規原板行"], trade["新規価格"])
            if key in target:
                raise ValueError("同じ実新規が重複")
            target[key] = trade
    common = original.keys() & modified.keys()
    only_base, only_changed = original.keys()-modified.keys(), modified.keys()-original.keys()
    return {"共通実新規": len(common), "元のみ新規": len(only_base), "変更のみ新規": len(only_changed),
            "共通新規の純損益差円": sum(modified[k]["基準純損益円"]-original[k]["基準純損益円"] for k in common),
            "元赤字から黒字": sum(original[k]["基準純損益円"] < 0 < modified[k]["基準純損益円"] for k in common),
            "元黒字から赤字": sum(modified[k]["基準純損益円"] < 0 < original[k]["基準純損益円"] for k in common),
            "元黒字だった共通新規の純額差円": sum(modified[k]["基準純損益円"]-original[k]["基準純損益円"] for k in common if original[k]["基準純損益円"] > 0),
            "元のみ純損益円": sum(original[k]["基準純損益円"] for k in only_base),
            "変更のみ純損益円": sum(modified[k]["基準純損益円"] for k in only_changed)}


def operation_metrics(infos: list[dict], trades: list[dict], role: str, policy: dict) -> dict:
    """共通会計にMFE・利益保護・一場DDを加える。

    引数: infos/trades (list[dict]) は場別・完結取引、role (str) は役割、policy (dict) は出口。
    返り値: dict は期間の運用集計。欠測・対象外をゼロへ変換しない。
    """
    result = E.operation_metrics(infos, trades)
    floor = role == "反転" and policy["出口ID"] == "X2"
    armed = [t for t in trades if t["利益床起動"]]
    unarmed = [t for t in trades if not t["利益床起動"]]
    result.update(期間内最大場内DD円=max((i["観測含み込み最大DD円"] for i in infos), default=0),
                  最悪場内時価円=min((i["観測最悪時価円"] for i in infos), default=0),
                  利益床使用=floor, 床起動取引数=len(armed),
                  床未起動取引数=len(unarmed) if floor else None,
                  床未起動赤字取引数=sum(t["基準純損益円"] < 0 for t in unarmed) if floor else None,
                  床未起動純損益円=sum(t["基準純損益円"] for t in unarmed) if floor else None,
                  床起動済純損益円=sum(t["基準純損益円"] for t in armed) if floor else None)
    result["活動場赤字率"] = result["赤字場数"]/result["活動場数"] if result["活動場数"] else None
    for threshold in (20, 50, 100):
        reached = [t for t in trades if t["観測最大順行pt"] >= threshold]
        result[f"{threshold}pt到達取引"] = len(reached)
        result[f"{threshold}pt後純赤字"] = sum(t["基準純損益円"] < 0 for t in reached)
    reached_atr = [t for t in trades if t["観測最大順行pt"] >= t["入口ATR"]]
    result["1ATR到達取引"] = len(reached_atr)
    result["1ATR後純赤字"] = sum(t["基準純損益円"] < 0 for t in reached_atr)
    result["中心線超過新規数"] = sum(i["中心線超過新規数"] for i in infos)
    return result


def entry_flags(result: dict, config: dict) -> tuple[bool, bool]:
    """旧二期間だけから支持と入口70%目標を判定する。

    引数: result/config (dict) は8入口の一集約と固定規則。
    返り値: tuple[bool,bool] は支持と目標。既使用最終1場を選定へ使わない。
    """
    support = all(W.supported(result[p], limits) for p, limits in config["入口支持"].items())
    goal = support and all(result[p]["確認率"] >= config["目標確認率"]
        and result[p]["30分間引き_約定候補数"] >= config["間引き必要件数"][p]
        and result[p]["30分間引き_確認率"] >= config["目標確認率"] for p in PERIODS[:2])
    return support, bool(goal)


def representative_key(row: dict) -> tuple:
    """旧二期間による表示代表の順序を固定する。

    引数: row (dict) は一運用候補。
    返り値: tuple は追加5pt平均の最小側が大きい順、同値ID順。
    """
    return (-min(row[p]["運用"]["追加5pt平均円"] if row[p]["運用"]["追加5pt平均円"] is not None else -math.inf for p in PERIODS[:2]), row["候補ID"])


def blank_label() -> dict:
    """確認遅延で新規できない入口ラベルを作る。

    引数: なし。
    返り値: dict は未約定と欠測。仮の価格を補わない。
    """
    return {"ラベル": "未約定", "理由": "足確定確認遅延30秒超", **{key: None for key in
            ("新規価格", "新規時計秒", "判定時計秒", "判定原板行", "新規原板行", "判定気配", "最大順行pt", "最大逆行pt", "所要分")}}


# ----------------------------------------
# 全65場を同じ準備と指標履歴で処理し、入口先着は8系統に一度だけ付ける。

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
    engine = module(Path(__file__).with_name("運用.py"), "循環研究のチャート運用")
    work.mkdir(parents=True, exist_ok=True)
    details, cases = work / "全運用詳細.jsonl.gz", work / "入口事例.jsonl.gz"
    infos, trades, entry_cases = defaultdict(list), defaultdict(list), defaultdict(list)
    quality, entry_quality = [], []
    banks = {n: W.Indicators() for n in (3, 5, 15)}
    previous_contract = None
    with compressed(details) as detail_stream, compressed(cases) as case_stream:
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
                if frames[size]:
                    signals_by_source, input_quality = I.generate(frames[size], frames[15], session, cutoff.timestamp(), deadline.timestamp(), config)
                else:
                    signals_by_source = {f"{size}分_{f}": [] for f in I.FAMILIES}
                    input_quality = {"場": session, "時間足分": size, "公開足": 0, "共通準備可足": 0, "共通時間条件可足": 0}
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
                    # 運用へ渡すのはラベルを付けていない当時既知のsignalだけ。
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
            print(f"00011 {session} 8入口・24運用完了", flush=True)
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
                operation["共通新規比較"] = paired([t for t in trades[source_id+"_X0"] if t["期間"] == period], period_trades)
                row[period] = {"入口": entry_result[period], "運用": operation}
            row["費用資格"] = all(W.supported(row[p]["運用"], limits) and row[p]["運用"]["品質注意場数"] == 0
                                  and row[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
            variants.append(row)
            results.append(row)
        representative = min(variants, key=representative_key)
        saved_ids.extend((source_id+"_X0", representative["候補ID"]))
    saved_ids = list(dict.fromkeys(saved_ids))
    report = {"全65場既使用": True, "入口評価": entry_results, "結果": results, "表示固定ID": saved_ids,
              "入口70目標達成数": sum(r["70目標"] for r in entry_results), "費用資格数": sum(r["費用資格"] for r in results),
              "入口125250評価の変更": False, "位置付け": "既使用65場で固定24案を比較する追加開発。新しい未見確認ではない"}
    W.write_json(study / "入力品質.json", quality)
    W.write_json(study / "入口品質.json", entry_quality)
    W.write_csv(study / "全候補_場別.csv", [i for cid in infos for i in infos[cid]])
    E.publish_details(study, details, saved_ids, manifest, "")
    catalog_path = study / "一覧.resources.json"
    catalog = W.read_json(catalog_path)
    for resource in catalog["resources"]:
        resource["id"] = resource["id"].replace("00008_", "00011_", 1)
    W.write_json(catalog_path, catalog)
    W.write_json(study / "作業成果物.json", {"原板複製": False, "展開内容SHA256が正本": True,
        "ファイル": [{"パス": path.relative_to(ROOT, walk_up=True).as_posix(), "展開内容SHA256": content_sha(path),
                     "圧縮SHA256参考": O.sha(path), "圧縮バイト": path.stat().st_size} for path in (details, cases)]})
    W.write_json(study / "結果.json", report)
    return {"入口数": len(entry_results), "運用候補数": len(results), "入口70目標達成数": report["入口70目標達成数"],
            "費用資格数": report["費用資格数"], "表示固定ID": saved_ids}


def main() -> None:
    """試行・作業先を指定し、固定24案を実行する。

    引数: なし。--study/--workを読む。
    返り値: None。既存結果・固定不一致は拒否する。
    """
    parser = argparse.ArgumentParser(description="順行と反転のチャート構造と利益回収")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    args = parser.parse_args()
    print(json.dumps(run(args.study.resolve(), args.work.resolve()), ensure_ascii=False))


if __name__ == "__main__":
    main()
