"""反転の値条件と確認時計、共通順行の実参加、利益回収を分ける。"""

from collections import Counter, defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00026_反転のSAR確認時刻と順行持続"
WORK = ROOT / "work/反転確認時計/00026"
OLD_STUDY = ROOT / "study/00025_価格イベントとSAR方向持続"
OLD_WORK = ROOT / "work/SAR持続/00025"
PERIODS = ("学習", "条件選択", "後続検査")
POLICIES = ("N0", "N1", "N2")
FAMILIES = ("R内復帰", "T外回復", "R方向確認")


def module(path: Path, name: str) -> Any:
    """保存診断用の固定補助を読み取る。

    引数: path(Path)はコード、name(str)は識別名。
    返り値: Anyは補助。26主入口・運用を再実行しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


D = module(ROOT / "scripts/終値切替/対応診断.py", "反転確認時計の固定保存診断補助")


def read(name: str, study: Path = STUDY, work: Path = WORK) -> list[dict]:
    """展開SHAを照合して指定試行の保存明細を読む。

    引数: name(str)はファイル名、study/work(Path)は正本/作業先。
    返り値: list[dict]は保存全行。新Nightや原板を開かない。
    """
    return D.read(name, study, work)


def main() -> None:
    """同f値条件、後続hの別価格、実参加と出口差を保存する。

    引数: なし。
    返り値: None。正式条件・結果を変更せず対応診断JSONを保存する。
    """
    raw, cases, details, reactions = [read(n) for n in (
        "全複合shadow.jsonl.gz", "入口事例.jsonl.gz", "全運用詳細.jsonl.gz", "反転監視.jsonl.gz")]
    old_raw = read("全複合shadow.jsonl.gz", OLD_STUDY, OLD_WORK)
    canonical, old_map = {r["発動ID"]: r for r in raw}, {r["発動ID"]: r for r in old_raw}
    prices = {key: r for key, r in canonical.items() if r["入口系統"] != "R方向確認"}
    if len(canonical) != len(raw) or set(prices) != set(old_map):
        raise ValueError("原価格イベント重複又は固定25母集団が不一致")
    checks = 1
    for key, row in prices.items():
        prior = old_map[key]
        for field in ("場", "index", "end", "confirm", "confirm_line", "close", "atr", "macd_hist", "MACDヒスト変化",
                      "side", "役割", "入口系統", "要求時計秒", "要求原板行", "先着評価対象", "固定設定", "ラベル", "理由", *D.NUMBERS):
            if row[field] != prior[field]:
                raise ValueError("固定25価格/先着不変の不一致: "+field)
            checks += 1
        if row["共通M26準備"] != prior["共通M25準備"]:
            raise ValueError("共通数値準備が変化")
        if row["入口系統"] == "T外回復":
            expected = prior["戦略判定"]["Q1"]["採用"]
            if any(row["戦略判定"][p]["採用"] != expected for p in POLICIES):
                raise ValueError("共有T原採否が25Q1と不一致")
        else:
            if row["戦略判定"]["N0"]["採用"] != prior["戦略判定"]["Q0"]["採用"]:
                raise ValueError("同fのMACD参照採否が不一致")
            if row["戦略判定"]["N1"]["採用"] != row["戦略判定"]["N2"]["採用"]:
                raise ValueError("同f即時SARのN1/N2が不一致")
        checks += 2
    f_map = {r["エピソードID"]: r for r in prices.values() if r["入口系統"] == "R内復帰"}
    for row in raw:
        D.labels([row])
        if row["入口系統"] == "R方向確認":
            f = f_map[row["エピソードID"]]
            if row["f起点発動ID"] != f["発動ID"] or row["side"] != f["side"]:
                raise ValueError("後続hのf起点又は方向が不一致")
            if row["要求時計秒"] <= f["要求時計秒"] or any(row["戦略判定"][p]["採用"] for p in ("N0", "N1")):
                raise ValueError("後続hの時計又は対象戦略が不一致")
            inside = f["固定設定"]["L"] < row["close"] < f["固定設定"]["R"]
            if row["h価格条件可"] != inside or not inside and row["戦略判定"]["N2"]["採用"]:
                raise ValueError("後続h範囲条件表示/採否が不一致")
            checks += 4
    selected, event_map = defaultdict(set), {}
    for row in cases:
        if row["イベントID"] in event_map or not row["先着評価対象"]:
            raise ValueError("case重複又は対象外混入")
        expected = canonical[row["発動ID"]]["戦略判定"]
        if row["戦略判定"] != expected or row["複合判定"] != expected[row["戦略"]]:
            raise ValueError("case全N採否が正本と不一致")
        event_map[row["イベントID"]] = row
        selected[row["戦略"], row["期間"]].add(row["発動ID"])
        checks += 3
    for p in POLICIES:
        for period in PERIODS:
            expected = {r["発動ID"] for r in raw if r["期間"] == period and r["戦略判定"][p]["採用"]}
            if selected[p, period] != expected:
                raise ValueError("純case集合と正本採否が不一致")
            checks += 1
    for period in PERIODS:
        if not selected["N1", period] <= selected["N2", period]:
            raise ValueError("原N1がN2の部分集合でない")
        checks += 1

    # ----------------------------------------
    # 同じf上の値条件と、後続hからの新しい時計/価格を分ける。
    stages, participation, waiting_rows, waiting = [], [], [], []
    for period in PERIODS:
        for family in FAMILIES:
            own = [r for r in raw if r["期間"] == period and r["入口系統"] == family]
            stages.append({"期間": period, "系統": family, "全原イベント": D.labels(own),
                "M26時間通過": D.labels([r for r in own if r["共通M26準備"] and r["時間条件可"]]),
                **{p: D.labels([r for r in own if r["戦略判定"][p]["採用"]]) for p in POLICIES}})
        for left, right in (("N0", "N1"), ("N1", "N2"), ("N0", "N2")):
            a, b = selected[left, period], selected[right, period]
            participation.append({"期間": period, "左": left, "右": right,
                "共通原採用数": len(a & b), "左のみ原採用数": len(a-b), "右のみ原採用数": len(b-a)})
        delayed = [r for r in raw if r["期間"] == period and r["入口系統"] == "R方向確認"]
        for row in delayed:
            f = f_map[row["エピソードID"]]
            comparable = f["先着評価対象"] and row["先着評価対象"]
            price_comparable = comparable and f["新規価格"] is not None and row["新規価格"] is not None
            waiting_rows.append({"期間": period, "場": row["場"], "エピソードID": row["エピソードID"],
                "f発動ID": f["発動ID"], "h発動ID": row["発動ID"], "N0のf採用": f["戦略判定"]["N0"]["採用"],
                "N2のh採用": row["戦略判定"]["N2"]["採用"], "h価格条件可": row["h価格条件可"],
                "要求待機分": (row["要求時計秒"]-f["要求時計秒"])/60,
                "両先着対象": comparable, "両仮新規比較可": price_comparable,
                "f先着": f["ラベル"], "h先着": row["ラベル"],
                "仮新規進行pt": row["side"]*(row["新規価格"]-f["新規価格"]) if price_comparable else None})
        for mode in ("全後続h", "N2採用h", "N0fかつN2h採用"):
            own = [r for r in waiting_rows if r["期間"] == period and (mode == "全後続h" or r["N2のh採用"] and (mode != "N0fかつN2h採用" or r["N0のf採用"]))]
            paired = [r for r in own if r["両仮新規比較可"]]
            paired_f = [f_map[r["エピソードID"]] for r in paired]
            paired_h = [canonical[r["h発動ID"]] for r in paired]
            waiting.append({"期間": period, "集合": mode, "後続h数": len(own),
                "両先着対象数": sum(r["両先着対象"] for r in own), "両仮新規比較可数": len(paired),
                "要求待機分": D.distribution([r["要求待機分"] for r in own]),
                "仮新規進行pt": D.distribution([r["仮新規進行pt"] for r in paired]),
                "対応fの先着": D.labels(paired_f), "対応hの先着": D.labels(paired_h),
                "限界": "同episodeの別時計/価格からの仮参加。fの技術採用を仮定せず、同じ実新規の出口比較とはしない。"})
    diagnoses = [r for r in reactions if r["種別"] == "反転終了診断"]
    if {r["エピソードID"] for r in diagnoses} != set(f_map) or len(diagnoses) != len(f_map):
        raise ValueError("f登録と反転終了診断の全集合が不一致")
    stage_counts = [{"期間": p, "f登録数": sum(r["期間"] == p for r in diagnoses),
        "確認種別": dict(Counter((r["確認種別"] or "確認なし") for r in diagnoses if r["期間"] == p)),
        "終了理由": dict(Counter(r["終了理由"] for r in diagnoses if r["期間"] == p))} for p in PERIODS]

    # ----------------------------------------
    # 一建玉の実参加と共通実新規の出口を、異なる時計の反実仮想と区別する。
    trades, handled = defaultdict(list), defaultdict(list)
    for row in details:
        key = row["候補ID"], row["品質"]["期間"]
        trades[key].extend(row["取引"])
        handled[key].extend(row["入口取扱"])
    official = json.loads((STUDY / "結果.json").read_text(encoding="utf-8"))
    result = {r["候補ID"]: r for r in official["結果"]}
    comparisons, protection, realization, operations, sequences = [], [], [], [], []
    for period in PERIODS:
        for left, right in (("3分_N0_X0", "3分_N1_X0"), ("3分_N1_X0", "3分_N2_X0"), ("3分_N0_X0", "3分_N2_X0")):
            paired = D.P.compare(trades[left, period], trades[right, period], event_map, True)
            if paired["全運用純額差円"] != result[right][period]["運用"]["追加0pt純損益円"]-result[left][period]["運用"]["追加0pt純損益円"]:
                raise ValueError("実参加分解と全額差の不一致")
            comparisons.append({"期間": period, "左": left, "右": right, "運用比較": paired})
            checks += 1
        for cid in ("3分_N0_X0", "3分_N1_X0", "3分_N2_X0"):
            own = trades[cid, period]
            armed = [t for t in own if t["追尾起動"]]
            protection.append({"候補ID": cid, "期間": period, "完結数": len(own), "追尾起動数": len(armed),
                "起動後純赤字数": sum(t["基準純損益円"] < 0 for t in armed),
                "起動後同値未満約定数": sum((1 if t["方向"] == "買い" else -1)*(t["返済価格"]-t["新規価格"]) < 0 for t in armed),
                "最終設定未満約定数": sum(t["最終追尾から実返済方向差pt"] < 0 for t in armed),
                "最終設定からの不足pt計": sum(max(0, -t["最終追尾から実返済方向差pt"]) for t in armed)})
            paired_roles = defaultdict(dict)
            for role in ("反転", "順行"):
                subset = [t for t in own if event_map[t["入口イベントID"]]["役割"] == role]
                for trade in subset:
                    case = event_map[trade["入口イベントID"]]
                    for field in ("新規時計秒", "新規原板行", "新規価格"):
                        if trade[field] != case[field]:
                            raise ValueError("実新規と原先着の新規が不一致")
                        checks += 1
                    key = case["エピソードID"]
                    if role in paired_roles[key]:
                        raise ValueError("同episode同役割の実参加重複")
                    paired_roles[key][role] = trade
                wins = [t for t in subset if event_map[t["入口イベントID"]]["ラベル"] == "順行先着"]
                realization.append({"候補ID": cid, "期間": period, "役割": role, "実新規対応数": len(subset),
                    "対応先着250数": len(wins), "先着250だが基準純赤字数": sum(t["基準純損益円"] < 0 for t in wins),
                    "先着250だが250利確以外数": sum(t["返済理由"] != "利確" for t in wins),
                    "基準純額円": sum(t["基準純損益円"] for t in subset),
                    "追加5pt純額円": sum(t["追加滑り5pt純損益円"] for t in subset)})
                treatment = Counter(r["取扱"] for r in handled[cid, period] if event_map[r["イベントID"]]["役割"] == role)
                operations.append({"候補ID": cid, "期間": period, "役割": role, "運用入口取扱": dict(treatment), "実完結数": len(subset)})
            both = [r for r in paired_roles.values() if set(r) == {"反転", "順行"}]
            for row in both:
                if not row["反転"]["新規時計秒"] < row["順行"]["新規時計秒"] or row["反転"]["返済時計秒"] > row["順行"]["新規時計秒"]:
                    raise ValueError("同episodeのR/T順序または一建玉の重複が不一致")
                checks += 1
            sequences.append({"候補ID": cid, "期間": period, "反転のみ実参加episode数": sum(set(r) == {"反転"} for r in paired_roles.values()),
                "順行のみ実参加episode数": sum(set(r) == {"順行"} for r in paired_roles.values()),
                "両役割実参加episode数": len(both), "両役割基準純額円": sum(t["基準純損益円"] for r in both for t in r.values()),
                "限界": "同episodeの二取引は独立標本ではない。保有中の役割イベントは新規ではなく抑止され得る。"})
    # ----------------------------------------
    # 将来h成立で事後対応したf/hは、新規価格と実額の診断として分離する。
    actual = {(d["候補ID"], t["入口イベントID"]): t for d in details for t in d["取引"]}
    matched = []
    for period in PERIODS:
        eligible = [r for r in waiting_rows if r["期間"] == period and r["N0のf採用"] and r["N2のh採用"]]
        pairs = [(r, actual.get(("3分_N0_X0", r["f発動ID"]+"_N0")), actual.get(("3分_N2_X0", r["h発動ID"]+"_N2"))) for r in eligible]
        pairs = [(r, a, b) for r, a, b in pairs if a is not None and b is not None]
        for row, a, b in pairs:
            side = f_map[row["エピソードID"]]["side"]
            if side*(b["新規価格"]-a["新規価格"]) != row["仮新規進行pt"]:
                raise ValueError("f/h仮新規と実新規の価格進行不一致")
            checks += 1
        matched.append({"期間": period, "原両採用数": len(eligible), "両実新規対応数": len(pairs),
            "要求待機分": D.distribution([r["要求待機分"] for r, a, b in pairs]),
            "実新規進行pt": D.distribution([f_map[r["エピソードID"]]["side"]*(b["新規価格"]-a["新規価格"]) for r, a, b in pairs]),
            "f先着": D.labels([f_map[r["エピソードID"]] for r, a, b in pairs]),
            "h先着": D.labels([canonical[r["h発動ID"]] for r, a, b in pairs]),
            "f基準純額円": sum(a["基準純損益円"] for r, a, b in pairs), "h基準純額円": sum(b["基準純損益円"] for r, a, b in pairs),
            "f追加5pt純額円": sum(a["追加滑り5pt純損益円"] for r, a, b in pairs),
            "h追加5pt純額円": sum(b["追加滑り5pt純損益円"] for r, a, b in pairs),
            "限界": "後にhが成立し両案が実参加したことによる事後集合。f時点で選べる新戦略の収益や同じ実新規の出口差とはしない。"})
    output = {"確認日": "2026-11-05", "全65場既使用": True, "対応集合全件一致": True, "照合項目数": checks,
        "全原発動数": len(raw), "固定25価格原イベント数": len(prices), "後続h原イベント数": len(raw)-len(prices),
        "純入口数": len(cases), "全case全戦略属性一致": True, "旧25価格と先着全件同値": True,
        "共有T原採否は25Q1同値": True, "同fのN0原採否は25Q0同値": True, "生N1はN2部分集合": True,
        "役割別値と時計": stages, "反転段階": stage_counts, "原発動参加集合": participation,
        "待機要約": waiting, "待機対応": waiting_rows, "N0fとN2hの実対応": matched,
        "運用対応": comparisons, "役割別運用抑止": operations, "同episode役割順序": sequences,
        "利益保護": protection, "入口先着と利益回収": realization,
        "コードSHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "結果SHA256": hashlib.sha256((STUDY / "結果.json").read_bytes()).hexdigest(),
        "旧結果SHA256": hashlib.sha256((OLD_STUDY / "結果.json").read_bytes()).hexdigest(),
        "限界": "全65場既使用。同fのMACD/現在SARと、後続hの別時計/価格を分離。待機対応は同episode仮参加であり出口差ではない。共有T原採否同値でも保有抑止により実参加が変わる。原先着は実返済後も含む。同値床は実現同値や費用後の非赤字を保証しない。予約済み新11/4Nightは本診断で開かない。"}
    (STUDY / "対応診断.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({k: output[k] for k in ("対応集合全件一致", "照合項目数", "全原発動数", "純入口数")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
