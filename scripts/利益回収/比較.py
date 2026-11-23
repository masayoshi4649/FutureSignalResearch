"""00010の固定3入口と6出口を、既使用65場で比較する。"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import gzip
import json
from pathlib import Path

import 運用 as M


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00010_順行と反転の利益保護と通常出口"
WORK = ROOT / "work/利益回収/00010"
E = M.module(ROOT / "scripts/外部探索/探索.py", "利益回収の固定入口")
W, O = E.W, M.O
INPUT = ROOT / "study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
BASE = ROOT / "study/00008_外部研究を共通尺度へ移して探索/条件.json"


def definitions() -> tuple[list[dict], list[dict]]:
    """固定した3入口と6出口を列挙する。

    引数: なし。
    返り値: tuple[list[dict], list[dict]] は入口と出口。
    """
    sources = [
        {"入口ID": "T01", "役割": "順行", "候補ID": "3分_RSI再加速_3_役割別", "時間足分": 3, "手法": "RSI再加速", "パラメータ": 3, "補助": "役割別"},
        {"入口ID": "R01", "役割": "反転", "候補ID": "対照_3分開始15分失敗復帰_ADX20未満", "時間足分": 3, "手法": "開始幅失敗復帰", "パラメータ": 15, "補助": "ADX環境"},
        {"入口ID": "R02", "役割": "反転", "候補ID": "5分_RSI回復_40_なし", "時間足分": 5, "手法": "RSI回復", "パラメータ": 40, "補助": "なし"}]
    policies = [{"出口ID": "X00"}, {"出口ID": "X01", "床起動pt": 20, "床利益pt": 10},
                {"出口ID": "X02", "床起動pt": 50, "床利益pt": 20}, {"出口ID": "X03", "ATR追尾": True},
                {"出口ID": "X04", "指標出口": True}, {"出口ID": "X05", "指標出口": True, "床起動pt": 50, "床利益pt": 20}]
    return sources, policies


def metrics(infos: list[dict], trades: list[dict]) -> dict:
    """既存会計に利益消失とDDを加える。

    引数: infos (list[dict]) は場別、trades (list[dict]) は完結取引。
    返り値: dict は期間集計。
    """
    result = E.operation_metrics(infos, trades)
    result.update(期間内最大場内DD円=max((i["観測含み込み最大DD円"] for i in infos), default=0),
                  最悪場内時価円=min((i["観測最悪時価円"] for i in infos), default=0),
                  床起動取引数=sum(t["利益床起動"] for t in trades),
                  中心目標無効=sum(i["中心線目標無効取引数"] for i in infos))
    result["活動場赤字率"] = result["赤字場数"]/result["活動場数"] if result["活動場数"] else None
    has_floor = bool(infos and infos[0]["利益床使用"])
    unarmed = [t for t in trades if not t["利益床起動"]]
    result.update(利益床使用=has_floor, 床未起動取引数=len(unarmed) if has_floor else None,
                  床未起動純損益円=sum(t["基準純損益円"] for t in unarmed) if has_floor else None,
                  床未起動赤字取引数=sum(t["基準純損益円"] < 0 for t in unarmed) if has_floor else None,
                  床起動済純損益円=sum(t["基準純損益円"] for t in trades if t["利益床起動"]) if has_floor else None)
    for threshold in (20, 50, 100):
        reached = [t for t in trades if t["観測最大順行pt"] >= threshold]
        result[f"{threshold}pt到達取引"] = len(reached)
        result[f"{threshold}pt後純赤字"] = sum(t["基準純損益円"] < 0 for t in reached)
    return result


def paired(base: list[dict], changed: list[dict]) -> dict:
    """同じ実新規と、出口に伴う追加/抑止を分ける。

    引数: base/changed (list[dict]) は基準/比較の取引。
    返り値: dict は共通新規での利益・損失救済と集合差。
    """
    def key(t: dict) -> tuple:
        """同じ実新規を識別する。

        引数: t (dict) は取引。
        返り値: tuple は入口・時計・行・価格。
        """
        return t["入口イベントID"], t["新規時計秒"], t["新規原板行"], t["新規価格"]
    original = {key(t): t for t in base}
    modified = {key(t): t for t in changed}
    common = original.keys() & modified.keys()
    return {"共通実新規": len(common), "元のみ新規": len(original.keys()-modified.keys()), "変更のみ新規": len(modified.keys()-original.keys()),
            "共通新規の純損益差円": sum(modified[k]["基準純損益円"]-original[k]["基準純損益円"] for k in common),
            "元赤字から黒字": sum(original[k]["基準純損益円"] < 0 < modified[k]["基準純損益円"] for k in common),
            "元黒字から赤字": sum(modified[k]["基準純損益円"] < 0 < original[k]["基準純損益円"] for k in common),
            "元黒字を早く確定した純額差円": sum(modified[k]["基準純損益円"]-original[k]["基準純損益円"] for k in common if original[k]["基準純損益円"] > 0)}


def run(study: Path) -> dict:
    """固定条件を保存後、全65場を再生する。

    引数: study (Path) は試行先。
    返り値: dict は全18条件の要約。
    """
    if (study / "結果.json").exists():
        raise ValueError("正式結果を上書きしません")
    config, manifest = W.read_json(BASE), W.read_json(INPUT)
    sources, policies = definitions()
    paths = [Path(__file__), Path(__file__).with_name("運用.py"), Path(__file__).with_name("合成検証.py"), study / "計画.md", INPUT, BASE]
    paths += [ROOT / name for name in W.read_json(ROOT / "study/00008_外部研究を共通尺度へ移して探索/選定固定.json")["ファイルSHA256"]]
    pins = {p.relative_to(ROOT).as_posix(): O.sha(p) for p in dict.fromkeys(paths)}
    definition = {"入口": sources, "出口": policies, "運用": config["運用"], "全65場既使用": True}
    condition_path, freeze_path = study / "条件.json", study / "固定.json"
    if condition_path.exists() and W.read_json(condition_path) != definition:
        raise ValueError("既存の固定条件を変更しません")
    if not condition_path.exists():
        W.write_json(condition_path, definition)
    if freeze_path.exists():
        locked = W.read_json(freeze_path)
        if locked["ファイルSHA256"] != pins or locked["条件SHA256"] != O.sha(condition_path):
            raise ValueError("実行前固定後にコード・入力・条件が変更された")
    else:
        W.write_json(freeze_path, {"固定日時": datetime.now(W.JST).isoformat(), "ファイルSHA256": pins, "条件SHA256": O.sha(condition_path)})
    W.write_json(study / "入力台帳.json", {"参照": INPUT.relative_to(study, walk_up=True).as_posix(), "SHA256": O.sha(INPUT)})
    WORK.mkdir(parents=True, exist_ok=True)
    by_id, trades_by_id, details = defaultdict(list), defaultdict(list), WORK / "全運用詳細.jsonl.gz"
    banks = {n: W.Indicators() for n in (3, 5, 15)}
    contract_before = None
    with gzip.open(details, "wt", encoding="utf-8") as stream:
        for entry in manifest["entries"]:
            session = entry["session"]
            source_path = Path(manifest["source_root"]) / entry["source_path"]
            stat = source_path.stat()
            cache = ROOT / "work/複合検証" / entry["cache_path"]
            if (stat.st_size, stat.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]) or O.sha(cache) != entry["sha256_cache"]:
                raise ValueError("固定入力が変化")
            contract = tuple(entry["in_session_contract_codes"])
            if contract_before is not None and contract != contract_before:
                banks = {n: W.Indicators() for n in banks}
            contract_before = contract
            begin, finish, cutoff, deadline = W.OLD.shared.legacy.session_times(session)
            start, end = begin.timestamp(), finish.timestamp()
            events, previous = [], -float("inf")
            for event in W.PREP.read_events(cache):
                if start <= event.now <= end and event.now >= previous:
                    events.append(event)
                    previous = event.now
            frames = {}
            for size, bank in banks.items():
                formed = W.bars_from_events(events, start, end, size)
                frames[size] = W.features(formed, bank, start)
                if int((end-start)//(size*60))-1-(formed[-1]["index"] if formed else -1) > 0:
                    bank.__init__()
            enriched = {size: E.enrich(frames[size], frames[15]) for size in (3, 5)}
            period = E.phase_of(session, config)
            for source in sources:
                signals = []
                for frame in enriched[source["時間足分"]]:
                    now = frame["confirm"]
                    if not frame["publish"] or not frame["has_previous"] or not E.defined(frame["atr"]) or frame["atr"] <= 0 or now >= cutoff.timestamp() or deadline.timestamp()-now < 3600:
                        continue
                    for side in (1, -1):
                        row = {**frame, "場": session, "時間足分": source["時間足分"], "side": side, "方向": "買い" if side == 1 else "売り",
                               "要求時計秒": now, "要求原板行": frame["confirm_line"], "確認遅延秒": now-frame["end"],
                               "イベントID": f"NK225_{session}_{source['時間足分']}分_{frame['index']:04d}_{side}"}
                        if E.allowed(row, source):
                            signals.append(row)
                for policy in policies:
                    cid = source["入口ID"] + "_" + policy["出口ID"]
                    state, info = M.replay(events, signals, frames[source["時間足分"]], session, cid, config["運用"], policy, source["役割"])
                    info.update(期間=period, 場時間分=(end-start)/60)
                    for t in state.trades:
                        t["期間"] = period
                    by_id[cid].append(info)
                    trades_by_id[cid].extend(state.trades)
                    stream.write(json.dumps({"候補ID": cid, "場": session, "品質": info, "約定": state.fills,
                                             "取引": state.trades, "注文": state.orders, "入口取扱": state.signals}, ensure_ascii=False, allow_nan=False)+"\n")
            print(f"00010 {session} 18条件完了", flush=True)
    result, saved_ids = [], []
    for source in sources:
        variants = []
        for policy in policies:
            cid = source["入口ID"]+"_"+policy["出口ID"]
            row = {"候補ID": cid, "入口": source, "出口": policy}
            for period in ("学習", "条件選択", "後続検査"):
                infos = [i for i in by_id[cid] if i["期間"] == period]
                trades = [t for t in trades_by_id[cid] if t["期間"] == period]
                row[period] = metrics(infos, trades)
                row[period]["共通新規比較"] = paired([t for t in trades_by_id[source["入口ID"]+"_X00"] if t["期間"] == period], trades)
            row["費用資格"] = all(W.supported(row[p], limits) and row[p]["品質注意場数"] == 0 and row[p]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
            variants.append(row)
            result.append(row)
        def rank(row: dict) -> tuple:
            """既使用最終1場を使わず表示用代表を選ぶ。

            引数: row (dict) は一出口の期間結果。
            返り値: tuple は昇順優先キー。
            """
            return (-min(row[p]["追加5pt平均円"] if row[p]["追加5pt平均円"] is not None else -float("inf") for p in ("学習", "条件選択")), row["候補ID"])
        representative = min(variants, key=rank)
        saved_ids.extend([source["入口ID"]+"_X00", representative["候補ID"]])
    saved_ids = list(dict.fromkeys(saved_ids))
    report = {"全65場既使用": True, "結果": result, "表示固定ID": saved_ids,
              "費用資格数": sum(r["費用資格"] for r in result), "入口125250評価の変更": False}
    W.write_json(study / "結果.json", report)
    E.publish_details(study, details, saved_ids, manifest, "")
    catalog_path = study / "一覧.resources.json"
    catalog = W.read_json(catalog_path)
    for resource in catalog["resources"]:
        resource["id"] = resource["id"].replace("00008_", "00010_", 1)
    W.write_json(catalog_path, catalog)
    W.write_csv(study / "全候補_場別.csv", [i for cid in by_id for i in by_id[cid]])
    return {"候補数": len(result), "費用資格数": report["費用資格数"], "表示固定ID": saved_ids}


def main() -> None:
    """試行先を指定して18出口比較を実行する。

    引数: なし。--studyを読む。
    返り値: None。
    """
    parser = argparse.ArgumentParser(description="順行と反転の利益保護と通常出口")
    parser.add_argument("--study", type=Path, default=STUDY)
    args = parser.parse_args()
    print(json.dumps(run(args.study.resolve()), ensure_ascii=False))


if __name__ == "__main__":
    main()
