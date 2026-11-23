"""同じ価格発動でSAR準備差・方向条件差・実参加・利益回収を分ける。"""

from collections import Counter, defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00025_価格イベントとSAR方向持続"
WORK = ROOT / "work/SAR持続/00025"
OLD_STUDY = ROOT / "study/00024_終値の内復帰と外回復による順行反転"
OLD_WORK = ROOT / "work/終値切替/00024"
PERIODS = ("学習", "条件選択", "後続検査")
POLICIES = ("Q0", "Q1")
FAMILIES = ("R内復帰", "T外回復")


def module(path: Path, name: str) -> Any:
    """固定済みの保存診断補助を読み取る。

    引数: path(Path)はコード、name(str)は識別名。
    返り値: Anyは補助。主入口や運用を再実行しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


D = module(ROOT / "scripts/終値切替/対応診断.py", "SAR持続の保存集合診断補助")


def read(name: str, study: Path = STUDY, work: Path = WORK) -> list[dict]:
    """展開SHAを確認し、指定試行の保存行だけを読む。

    引数: name(str)は明細名、study/work(Path)は正式/作業先。
    返り値: list[dict]は全保存行。原板の複製や再生はしない。
    """
    return D.read(name, study, work)


def category(row: dict) -> str:
    """公開SARの現在/前方向を実sideに対して分類する。

    引数: row(dict)は原価格発動。
    返り値: strは準備不可、現在不一致、現在のみ、二本持続。
    """
    if not row["SAR現在有効"] or not row["SAR前値有効"]:
        return "公開現前SAR未準備"
    if row["SAR現方向"] != row["side"]:
        return "現在方向不一致"
    if row["SAR前方向"] != row["side"]:
        return "現在のみ実方向"
    return "実方向二本持続"


def main() -> None:
    """準備と値選別を分け、旧価格同値と実参加差を保存する。

    引数: なし。
    返り値: None。結果・条件・主コードを変更せず対応診断JSONを保存する。
    """
    raw, cases, details, contexts = [read(name) for name in (
        "全複合shadow.jsonl.gz", "入口事例.jsonl.gz", "全運用詳細.jsonl.gz", "全複合context.jsonl.gz")]
    old_raw = read("全複合shadow.jsonl.gz", OLD_STUDY, OLD_WORK)
    canonical, old_map = {r["発動ID"]: r for r in raw}, {r["発動ID"]: r for r in old_raw}
    if len(canonical) != len(raw) or set(canonical) != set(old_map):
        raise ValueError("旧24と原価格イベント全集合が不一致")
    checks = 1
    for key, row in canonical.items():
        previous = old_map[key]
        for field in ("場", "index", "end", "confirm", "confirm_line", "close", "atr", "macd_hist", "MACDヒスト変化",
                      "side", "役割", "入口系統", "要求時計秒", "要求原板行", "先着評価対象", "固定設定", "ラベル", "理由", *D.NUMBERS):
            if row[field] != previous[field]:
                raise ValueError("旧価格/先着不変の照合失敗: "+field)
            checks += 1
        if row["旧24戦略判定"] != previous["戦略判定"]:
            raise ValueError("旧採否の参照が正本と不一致")
        if row["共通M24準備"] != previous["共通M24準備"] or row["共通M25準備"] and not row["共通M24準備"]:
            raise ValueError("旧M24または新共通準備包含が不一致")
        if row["戦略判定"]["Q0"]["採用"] and not previous["戦略判定"]["E0"]["採用"]:
            raise ValueError("新Q0が旧E0準備部分集合でない")
        D.labels([row])
        checks += 4
    selected, event_map = defaultdict(set), {}
    for row in cases:
        if row["イベントID"] in event_map or not row["先着評価対象"]:
            raise ValueError("case重複または対象外混入")
        correct = canonical[row["発動ID"]]["戦略判定"]
        if row["戦略判定"] != correct or row["複合判定"] != correct[row["戦略"]]:
            raise ValueError("case全採否表示差")
        selected[row["戦略"], row["期間"]].add(row["発動ID"])
        event_map[row["イベントID"]] = row
        checks += 3
    for policy in POLICIES:
        for period in PERIODS:
            expected = {r["発動ID"] for r in raw if r["期間"] == period and r["戦略判定"][policy]["採用"]}
            if expected != selected[policy, period]:
                raise ValueError("純case集合と正本採否不一致")
            checks += 1

    # ----------------------------------------
    # 共通準備の差と、同じ準備内の手法による選別差を分ける。
    stages, groups, participation, room = [], [], [], []
    for period in PERIODS:
        for family in FAMILIES:
            own = [r for r in raw if r["期間"] == period and r["入口系統"] == family]
            m24 = [r for r in own if r["共通M24準備"] and r["時間条件可"]]
            m25 = [r for r in own if r["共通M25準備"] and r["時間条件可"]]
            old_e0 = [r for r in own if old_map[r["発動ID"]]["戦略判定"]["E0"]["採用"]]
            q0 = [r for r in own if r["戦略判定"]["Q0"]["採用"]]
            q1 = [r for r in own if r["戦略判定"]["Q1"]["採用"]]
            lost_ready = [r for r in old_e0 if not r["共通M25準備"]]
            common = [r for r in q0 if r["戦略判定"]["Q1"]["採用"]]
            q0_only = [r for r in q0 if not r["戦略判定"]["Q1"]["採用"]]
            q1_only = [r for r in q1 if not r["戦略判定"]["Q0"]["採用"]]
            stages.append({"期間": period, "系統": family, "全価格発動": D.labels(own),
                "M24時間通過": D.labels(m24), "M25時間通過": D.labels(m25),
                "旧24E0": D.labels(old_e0), "SAR準備で旧E0除外": D.labels(lost_ready),
                "Q0価格と勢い": D.labels(q0), "Q1価格とSAR持続": D.labels(q1),
                "共通原採用": D.labels(common), "Q0のみ原採用": D.labels(q0_only), "Q1のみ原採用": D.labels(q1_only)})
            for group in sorted({category(r) for r in own}):
                for side in (1, -1):
                    subset = [r for r in own if category(r) == group and r["side"] == side]
                    groups.append({"期間": period, "系統": family, "side": side, "SAR状態": group,
                        "全価格発動": D.labels(subset), "Q0採用": D.labels([r for r in subset if r["戦略判定"]["Q0"]["採用"]]),
                        "Q1採用": D.labels([r for r in subset if r["戦略判定"]["Q1"]["採用"]])})
            if family == "R内復帰":
                for policy, rows in (("共通M25", m25), ("Q0", q0), ("Q1", q1)):
                    distances = []
                    for r in rows:
                        setting, side, close = r["固定設定"], r["side"], r["close"]
                        target = setting["R"] if side == 1 else setting["L"]
                        failure = setting["L"] if side == 1 else setting["R"]
                        distances.append((side*(target-close), side*(close-failure)))
                    room.append({"期間": period, "系統": family, "集合": policy, "件数": len(rows),
                        "反対端までの距離pt": D.distribution([r[0] for r in distances]),
                        "元境界までの無効化距離pt": D.distribution([r[1] for r in distances]),
                        "目標余地250以上かつ無効化125以内数": sum(a >= 250 and b <= 125 for a, b in distances),
                        "限界": "公開終値と固定構造の診断だけ。実約定価格とは異なり、注文gateや最適閾値の選択には使わない。"})
        left, right = selected["Q0", period], selected["Q1", period]
        participation.append({"期間": period, "共通原採用数": len(left & right),
            "Q0のみ原採用数": len(left-right), "Q1のみ原採用数": len(right-left)})

    # ----------------------------------------
    # 一建玉の実参加差と同じ実新規の出口差・回収を別に検算する。
    trades, handled = defaultdict(list), defaultdict(list)
    for row in details:
        key = row["候補ID"], row["品質"]["期間"]
        trades[key].extend(row["取引"])
        handled[key].extend(row["入口取扱"])
    official = json.loads((STUDY / "結果.json").read_text(encoding="utf-8"))
    result = {r["候補ID"]: r for r in official["結果"]}
    comparisons, protection, realization, operations, sequences = [], [], [], [], []
    for period in PERIODS:
        left, right = "3分_Q0_X0", "3分_Q1_X0"
        paired = D.P.compare(trades[left, period], trades[right, period], event_map, True)
        if paired["全運用純額差円"] != result[right][period]["運用"]["追加0pt純損益円"]-result[left][period]["運用"]["追加0pt純損益円"]:
            raise ValueError("実参加分解と全額差の不一致")
        comparisons.append({"期間": period, "左": left, "右": right, "運用比較": paired})
        checks += 1
        for cid in (left, right):
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
    # 共通準備の追加以外に参照案の再生が変わっていないか旧24と対応させる。
    old_cases = read("入口事例.jsonl.gz", OLD_STUDY, OLD_WORK)
    old_details = read("全運用詳細.jsonl.gz", OLD_STUDY, OLD_WORK)
    combined_cases = {r["イベントID"]: r for r in old_cases}
    combined_cases.update(event_map)
    old_control = []
    for period in PERIODS:
        left_trades = [t for row in old_details if row["候補ID"] == "3分_E0_X0" and row["品質"]["期間"] == period for t in row["取引"]]
        paired = D.P.compare(left_trades, trades["3分_Q0_X0", period], combined_cases, True)
        no_preparation_loss = all(not r["旧24戦略判定"]["E0"]["採用"] or r["共通M25準備"] for r in raw if r["期間"] == period)
        if no_preparation_loss and any(paired[k] != 0 for k in ("左側のみ実新規数", "右側のみ実新規数", "共通実新規純額差円", "全運用純額差円")):
            raise ValueError("SAR準備除外なしなのに旧24E0とQ0実運用が変化")
        old_control.append({"期間": period, "SAR準備除外なし": no_preparation_loss, "運用比較": paired})
        checks += 1
    output = {"確認日": "2026-11-05", "全65場既使用": True, "対応集合全件一致": True, "照合項目数": checks,
        "全原発動数": len(raw), "純入口数": len(cases), "全case全戦略属性一致": True,
        "旧24価格と先着全件同値": True, "Q0は旧24E0準備部分集合": True,
        "役割別準備と選別": stages, "SAR状態別": groups, "原発動参加集合": participation,
        "運用対応": comparisons, "旧24E0とQ0運用対応": old_control, "役割別運用抑止": operations, "同episode役割順序": sequences,
        "利益保護": protection, "入口先着と利益回収": realization, "価格余地診断": room,
        "数量診断準備": [{"期間": p, "全context数": sum(r["期間"] == p for r in contexts),
            "数量準備足数": sum(r["期間"] == p and bool(r["数量診断"] and r["数量診断"]["数量準備済"]) for r in contexts),
            "売買gate使用": False} for p in PERIODS],
        "コードSHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "結果SHA256": hashlib.sha256((STUDY / "結果.json").read_bytes()).hexdigest(),
        "旧結果SHA256": hashlib.sha256((OLD_STUDY / "結果.json").read_bytes()).hexdigest(),
        "限界": "全65場既使用。新旧価格/先着同値、共通SAR準備落ち、同M25上の方向条件、原入口と一建玉実参加を分離。原先着は返済後の仮保有経路を含む。価格余地は当時終値からの診断のみで採否に使わない。同値床は実約定や費用後の非赤字を保証しない。"}
    (STUDY / "対応診断.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({k: output[k] for k in ("対応集合全件一致", "照合項目数", "全原発動数", "純入口数")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
