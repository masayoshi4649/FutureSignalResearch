"""固定88主条件33玉の押し前終値と確認足終値を、保存観測だけで結合する。"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, median


def digest(path: Path) -> str:
    """
    機能: 読取対象のSHA256を計算する。
    引数: path(Path)は入力又は固定コードのパス。
    返り値: strはファイル指紋。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_lines(path: Path) -> list:
    """
    機能: 正式gzipを原保存順で読む。
    引数: path(Path)はJSONL gzip。
    返り値: list[dict]は保存レコード。原板を読まない。
    """
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def fixed_files(root: Path) -> dict:
    """
    機能: 88/89停止コードと今回の条件文書を指紋へ束ねる。
    引数: root(Path)はリポジトリ根。
    返り値: dict[str,str]は指紋。停止記録との相違は拒否する。
    """
    stop_path = root / "work/89Go正式化/停止.json"
    stop = json.loads(stop_path.read_text(encoding="utf-8"))
    paths = {}
    for name in ("新GoとmodsumSHA256", "旧88Go16SHA256", "旧87と依存163SHA256", "純戦略43SHA256"):
        for name, expected in stop[name].items():
            path = root / name
            assert digest(path) == expected, f"固定コード相違: {name}"
            paths[str(path)] = expected
    paths[str(stop_path)] = digest(stop_path)
    for study in ("00088_背景維持と押戻し再開の時系列比較", "00089_最低建値床を共通にした収穫配分の比較"):
        for name in ("条件.json", "検証計画.md"):
            path = root / "study" / study / name
            if path.exists():
                paths[str(path)] = digest(path)
    return paths


def observe_close(event: dict, observations: list, at: float) -> dict:
    """
    機能: i以降p未満の方向最大Closeとk.Closeを、当時観測だけで比べる。
    引数: event(dict)は保存再開event、observations(list[dict])は同場観測、at(float)は新規要求時計。
    返り値: dictは既知/未知、点の結合値、推進Close基準と符号付き差。損益を参照しない。
    """
    index = {}
    for record in observations:
        key = record["id"]
        if key in index:
            raise ValueError("観測IDが重複")
        index[key] = record
    side = event["side"]
    if side not in (-1, 1):
        raise ValueError("方向が不正")
    # ----------------------------------------
    # kindは通知の主理由。期限失効と新足公開が同時の記録も確定足を含む。
    published_bars = {}
    for record in observations:
        data, technical = record["input"], record["input"]["technical"]
        if record["kind"] not in ("確定3分", "期限失効", "窓開始"):
            continue
        key = (data["window"], data["epoch_start"], technical["bar3_end"])
        prior = published_bars.get(key)
        if prior is None:
            published_bars[key] = record
        elif prior["input"]["technical"]["close3"] != technical["close3"]:
            raise ValueError("同じ確定足のCloseが後から変わる")
    answer = {"既知": False, "分類": "未知", "理由": [], "当時の点": {}, "推進Close基準": None, "k対基準の方向差pt": None}
    points = {}
    names = {"i": "impulse", "p": "pullback", "r": "recovery", "k": "confirmation"}
    for label, name in names.items():
        point = event[name]
        record = index.get(point["observation_id"])
        if record is None:
            answer["理由"].append(f"{label}:観測ID欠落")
            continue
        data, technical = record["input"], record["input"]["technical"]
        close, bar_end, published = technical["close3"], technical["bar3_end"], data["at"]
        finite = all(isinstance(value, (int, float)) and math.isfinite(value) for value in (close, bar_end, published))
        key = (data["window"], data["epoch_start"], bar_end)
        valid = finite and close > 0 and published_bars.get(key, {}).get("id") == record["id"] and not data["after_eof"]
        valid = valid and data["window"] == event["window"] and data["epoch_start"] == event["epoch_start"]
        valid = valid and bar_end == point["bar_end"] and published == point["published_at"]
        valid = valid and event["epoch_start"] < bar_end <= published <= at
        if not valid:
            answer["理由"].append(f"{label}:当時の同窓確定終値へ結合できない")
            continue
        points[label] = record
        answer["当時の点"][label] = {"observation_id": record["id"], "kind": record["kind"], "ordinal": data["ordinal"], "bar_end": bar_end, "published_at": published, "close": close}
    if answer["理由"]:
        return answer
    i, p, r, k = [answer["当時の点"][label] for label in names]
    if not (i["bar_end"] < p["bar_end"] < r["bar_end"] <= k["bar_end"]):
        answer["理由"].append("i<p<r<=kの確定足順序が不整合")
        return answer
    if not (i["ordinal"] < p["ordinal"] < r["ordinal"] <= k["ordinal"]):
        answer["理由"].append("観測ordinalの順序が不整合")
        return answer
    endpoints = list(range(int(i["bar_end"]), int(p["bar_end"]), 180))
    if i["bar_end"] != int(i["bar_end"]) or p["bar_end"] - i["bar_end"] != 180 * len(endpoints):
        answer["理由"].append("3分足区間の端が不整合")
        return answer
    by_end = {}
    for record in published_bars.values():
        data, technical = record["input"], record["input"]["technical"]
        bar_end = technical["bar3_end"]
        if data["window"] != event["window"] or data["epoch_start"] != event["epoch_start"]:
            continue
        if not (i["bar_end"] <= bar_end < p["bar_end"]):
            continue
        # ----------------------------------------
        # 同時計もordinalを用い、確認足の公開時点より後の観測を混ぜない。
        if data["at"] > k["published_at"] or data["ordinal"] > k["ordinal"]:
            continue
        close = technical["close3"]
        if data["after_eof"] or not math.isfinite(close) or close <= 0 or not (bar_end <= data["at"] <= at):
            answer["理由"].append("区間内の確定終値が未知")
            continue
        if bar_end in by_end:
            raise ValueError("同窓の同一確定足が重複")
        by_end[bar_end] = record
    answer["区間の期待足数"] = len(endpoints)
    answer["区間の保存足数"] = len(by_end)
    missing = sorted(set(endpoints) - set(by_end))
    if missing:
        answer["理由"].append("i以上p未満の確定3分足欠落")
        answer["欠落bar_end"] = missing
    if answer["理由"]:
        return answer
    basis = max(side * record["input"]["technical"]["close3"] for record in by_end.values()) * side
    basis_records = [record for _, record in sorted(by_end.items()) if record["input"]["technical"]["close3"] == basis]
    gap = side * (k["close"] - basis)
    answer.update({"既知": True, "分類": "越過" if gap > 0 else "同値" if gap == 0 else "未回復", "理由": ["同窓/epochのi以上p未満の全確定Closeとk.Closeを当時の公開観測へ結合"], "推進Close基準": basis, "基準の出典": [{"observation_id": rec["id"], "bar_end": rec["input"]["technical"]["bar3_end"]} for rec in basis_records], "k対基準の方向差pt": gap, "iが基準と同値": i["close"] == basis})
    return answer


def describe(rows: list) -> dict:
    """
    機能: 判定済み群の最終損益を記述統計へ分離する。
    引数: rows(list[dict])は当時分類と事後損益を持つ作業内の玉。
    返り値: dictは件数・数量・損益分布。別戦略の成績とはしない。
    """
    pnls = [row["事後純額円"] for row in rows]
    return {"実玉数": len(rows), "初期枚数": sum(row["初期枚数"] for row in rows), "費用後純額円": sum(pnls), "黒字玉": sum(value > 0 for value in pnls), "赤字玉": sum(value < 0 for value in pnls), "同額玉": sum(value == 0 for value in pnls), "純額平均円": mean(pnls) if pnls else None, "純額中央値円": median(pnls) if pnls else None, "純額最小円": min(pnls) if pnls else None, "純額最大円": max(pnls) if pnls else None}


def artificial() -> dict:
    """
    機能: 売買鏡像・i以外の進行終値・欠落・未来を手計算で検査する。
    引数: ありません。
    返り値: dictは人工検査数と成功。市場入力は使わない。
    """
    checks = 0
    for side in (1, -1):
        for last, expected in ((130, "越過"), (120, "同値"), (110, "未回復")):
            observations = [{"id": n + 1, "kind": "確定3分", "input": {"ordinal": n + 1, "at": 1180 + n * 180, "window": "D164_15", "epoch_start": 1000, "after_eof": False, "technical": {"bar3_end": 1180 + n * 180, "close3": 1000 + side * close}}} for n, close in enumerate((100, 120, 90, last))]
            point = lambda n: {"observation_id": n, "bar_end": observations[n - 1]["input"]["at"], "published_at": observations[n - 1]["input"]["at"]}
            event = {"side": side, "window": "D164_15", "epoch_start": 1000, "impulse": point(1), "pullback": point(3), "recovery": point(4), "confirmation": point(4)}
            value = observe_close(event, observations, 1900)
            assert value["既知"] and value["分類"] == expected and not value["iが基準と同値"]
            checks += 1
            if expected == "越過":
                assert not observe_close(event, observations[:1] + observations[2:], 1900)["既知"]
                checks += 1
                assert not observe_close(event, observations, 1700)["既知"]
                checks += 1
                assert not observe_close(event, observations[:-1], 1900)["既知"]
                checks += 1
                observations[0]["kind"] = "期限失効"
                assert observe_close(event, observations, 1900)["分類"] == "越過"
                checks += 1
    return {"成功": True, "手計算照合数": checks, "対象": ["買売鏡像", "i以後に推進Close基準が進む", "越過/同値/未回復", "中間足欠落は未知", "要求後のkは未知", "point欠落は未知", "期限失効と同時に公開された足を欠落扱いしない"]}


def main() -> None:
    """
    機能: 正式2gzを明示読取し、主E1だけの観測JSON/MDと不変証拠を作る。
    引数: CLIの--decisions/--diagnostics/--out-json/--out-md(Path)、--self-test(bool)。
    返り値: ありません。正式成果・金融・入口条件を書き換えない。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("decisions", "diagnostics", "out-json", "out-md"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    tests = artificial()
    if args.self_test:
        print(json.dumps(tests, ensure_ascii=False))
        return
    assert all((args.decisions, args.diagnostics, args.out_json, args.out_md)), "4明示Pathが必須"
    assert not args.out_json.exists() and not args.out_md.exists(), "新規出力先が必須"
    root = Path(__file__).resolve().parents[2]
    fixed = fixed_files(root)
    paths = [args.decisions.resolve(), args.diagnostics.resolve()]
    before = {str(path): digest(path) for path in paths}
    scenes = json_lines(paths[0])
    scenes_by_id = {scene["session"]: scene for scene in scenes}
    assert len(scenes_by_id) == len(scenes) == 66
    diagnostics = [row for row in json_lines(paths[1]) if row["key"] == "E1_D0"]
    assert len(diagnostics) == len({row["lot"]["id"] for row in diagnostics}) == 33
    rows = []
    for trade in diagnostics:
        lot, order = trade["lot"], trade["entry_order"]
        scene = scenes_by_id[trade["session"]]
        grids = [grid for grid in scene["grid_decisions"] if grid["at"] == order["request_time"]]
        assert len(grids) == 1
        grid = grids[0]
        pool = [row for row in grid["policies"]["E1"]["pool"] if row["reference_id"] == lot["reference_id"]]
        assert len(pool) == 1 and pool[0]["allowed"] and pool[0]["known"] and pool[0]["side"] == lot["side"]
        direction = next(row for row in grid["entry"]["directions"] if row["side"] == lot["side"])
        event = direction["event"]
        assert event and direction["e1_allowed"] and direction["event_valid"] and event["id"] == pool[0]["event_id"]
        assert event["window"] == grid["window"] and event["side"] == lot["side"]
        observation = observe_close(event, scene["entry_observations"], order["request_time"])
        rows.append({"session": trade["session"], "policy": "E1_D0", "position_id": lot["id"], "reference_id": lot["reference_id"], "side": lot["side"], "初期枚数": lot["initial_quantity"], "request_at": order["request_time"], "event_id": event["id"], "window": event["window"], "epoch_start": event["epoch_start"], "当時観測": observation, "事後純額円": lot["net_pnl"]})
    groups = {name: describe([row for row in rows if row["当時観測"]["分類"] == name]) for name in ("越過", "同値", "未回復", "未知")}
    assert sum(group["実玉数"] for group in groups.values()) == 33
    assert sum(group["費用後純額円"] for group in groups.values()) == describe(rows)["費用後純額円"]
    unchanged = before == {str(path): digest(path) for path in paths} and fixed == fixed_files(root)
    assert unchanged
    result = {"試行": "89次候補の観測・固定88主E1のみ", "確認時刻UTC": datetime.now(timezone.utc).isoformat(), "成功": True, "入力SHA256": before, "コードSHA256": digest(Path(__file__)), "人工": tests, "定義": {"推進Close基準": "保存eventのi<=Bar3End<p、同window/epochの全確定3分Closeの方向側最大（買いmax・売りmin）", "k比較": "side*(k.Close-推進Close基準)>0が越過、=0が同値、<0が未回復", "保存p": "最新押し足であり、最初の押し足とは限らない。iも直前ピークではない。", "当時性": "EventPoint.observation_idへ結合し公開時計/ordinalを確認。k公開後の記録を基準へ混入せず、欠足/欠pointは未知。", "事後損益": "分類に使わず群の記述統計のみへ保存。全玉JSONへPNLを転記しない。"}, "全33玉の記述統計": describe(rows), "群の記述統計": groups, "iが基準ではない玉数": sum(row["当時観測"].get("既知") and not row["当時観測"].get("iが基準と同値") for row in rows), "全玉の当時観測": [{key: value for key, value in row.items() if key != "事後純額円"} for row in rows], "固定88_89SHA256": fixed, "入力と固定コード前後不変": unchanged, "限界": ["同じ既使用66場のE1_D0実33玉のみ。D1を独立玉に加えない。", "確定終値の比較であり、高安・板内極値・回復の原因を測っていない。", "保存pの定義に従うため、最新押し足より前の区間を使う。", "群の既存損益の足し算は、この条件で新規選別した別戦略の成績ではない。", "Source年齢/指標の因果効果や最適閾値は推論しない。"], "新売買": 0, "閾値scan": 0, "新原板読取": 0, "89条件変更": 0}
    text = ["# 押し前の確定終値を回復したか（固定88・主E1）", "", "固定88の定時判断と取引診断だけから、E1_D0実33玉を観測した。D1は含めない。損益は分類後の記述統計である。", "", "推進Close基準は、同window/epochの`i <= Bar3End < p`にある全確定3分Closeの方向側最大（買いmax・売りmin）。保存pは最新押し足であり、初回押し足とは限らない。k.Closeとの方向差を、越過・同値・未回復に分ける。高安や板内ピークとは呼ばない。", "", "| 当時の分類 | 玉数 | 初期枚数 | 費用後純額円 | 黒字/赤字 | 純額中央値円 |", "|---|---:|---:|---:|---:|---:|"]
    for name, group in groups.items():
        text.append(f"| {name} | {group['実玉数']} | {group['初期枚数']} | {group['費用後純額円']:,} | {group['黒字玉']}/{group['赤字玉']} | {group['純額中央値円']} |")
    text += ["", f"合計{len(rows)}玉、初期{describe(rows)['初期枚数']}枚、純額{describe(rows)['費用後純額円']:,}円。i以後に推進Close基準が進んだ玉は{result['iが基準ではない玉数']}玉。", "", "各i/p/r/kはobservation_idから元Technicalへ結合し、時計・ordinal・同窓/epoch・全3分足の連続を検査した。欠けは未知とする。全玉の当時値はJSONへ保存し、個別PNLは複製しない。", "", "この表は新しい選別戦略の損益ではない。観測済み33玉の群差から原因や将来利益は断定できず、Source年齢や指標の因果にも結び付けない。次候補では、平均の回復と以前の確定終値進行の回復を役割として分ける材料にする。", "", f"人工{tests['手計算照合数']}照合成功。入力2gzと88/89固定コードは実行前後不変。新売買・閾値scan・新原板読取・89条件変更はいずれも0。", "", f"入力指紋・再現コード・全玉当時観測は[{args.out_json.name}]({args.out_json.name})を参照。"]
    args.out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.out_md.write_text("\n".join(text) + "\n", encoding="utf-8")
    print(json.dumps({"成功": True, "全体": describe(rows), "群": groups, "入力前後不変": unchanged}, ensure_ascii=False))


if __name__ == "__main__":
    main()
