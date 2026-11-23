"""原価格イベント、上位選別、一建玉の実参加と利益回収を分けて診断する。"""

from collections import Counter, defaultdict
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00024_終値の内復帰と外回復による順行反転"
WORK = ROOT / "work/終値切替/00024"
OLD_STUDY = ROOT / "study/00023_上位高安の再テストと順行再開"
OLD_WORK = ROOT / "work/高安再開/00023"
PERIODS = ("学習", "条件選択", "後続検査")
FAMILIES = ("R内復帰", "T外回復")
LABELS = ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定")
NUMBERS = ("新規価格", "新規時計秒", "新規原板行", "判定時計秒", "判定原板行",
           "判定気配", "最大順行pt", "最大逆行pt", "所要分")


def module(path: Path, name: str) -> Any:
    """既存の同じ実新規に対する会計比較だけを読む。

    引数: path(Path)は補助コード、name(str)は識別名。
    返り値: Anyはモジュール。24の主入口/運用は再実行しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


P = module(ROOT / "scripts/VWAP復帰/対応診断.py", "終値切替の同実新規対応")


def read(name: str, study: Path = STUDY, work: Path = WORK) -> list[dict]:
    """展開内容SHAを確認し、保存明細だけを読む。

    引数: name(str)はgzip名、study/work(Path)は台帳/作業先。
    返り値: list[dict]は全保存行。原板や価格cacheを再走査しない。
    """
    artifacts = json.loads((study / "作業成果物.json").read_text(encoding="utf-8"))
    expected = next(r["展開内容SHA256"] for r in artifacts["ファイル"] if r["パス"].endswith("/"+name))
    with gzip.open(work / name, "rb") as stream:
        data = stream.read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("作業明細の内容指紋が不一致")
    return [json.loads(line) for line in data.splitlines() if line.strip()]


def labels(rows: list[dict]) -> dict:
    """時間/確認遅延の対象外を五分類から分けて集計する。

    引数: rows(list[dict])は原価格イベントまたは採用case。
    返り値: dictは全数、対象外、約定分母の先着率。
    """
    eligible = [r for r in rows if r["先着評価対象"]]
    excluded = [r for r in rows if not r["先着評価対象"]]
    for row in excluded:
        reason = "要求時間条件外" if not row["時間条件可"] else "足確定確認遅延30秒超"
        if row["ラベル"] != "対象外" or row["理由"] != reason or any(row[k] is not None for k in NUMBERS):
            raise ValueError("対象外の優先理由または数値欠測が不一致")
    values = Counter(r["ラベル"] for r in eligible)
    if values.keys()-set(LABELS):
        raise ValueError("評価対象に未知ラベル")
    filled = len(eligible)-values["未約定"]
    return {"候補数": len(rows), "先着評価対象数": len(eligible), "対象外数": len(excluded),
            "対象外時間数": sum(not r["時間条件可"] for r in excluded),
            "対象外遅延数": sum(r["時間条件可"] for r in excluded),
            "約定候補数": filled, **{k: values[k] for k in LABELS},
            "確認率": values["順行先着"]/filled if filled else None}


def upper_group(row: dict) -> str:
    """イベント当時の上位数値だけから許可理由を分類する。

    引数: row(dict)は原価格イベント。
    返り値: strは上位未準備、実方向T、ADX非上昇、対象外。
    """
    if not row["ペア準備済"]:
        return "上位未準備"
    same_trend = row["S2局面"] == "トレンド" and row["S2方向"] == row["side"]
    if same_trend:
        return "実方向の上位T: "+row["S2理由"]
    if row["入口系統"] == "R内復帰" and row["ADX変化"] is not None and math.isfinite(row["ADX変化"]) and row["ADX変化"] <= 0:
        return "ADX横ばい" if row["ADX変化"] == 0 else "ADX低下"
    return "上位選別対象外"


def distribution(values: list[float]) -> dict:
    """待機や距離を小さく要約し、閾値探索へ使わない。

    引数: values(list[float])は欠測を除いた数値。
    返り値: dictは数・最小・中央値・最大。
    """
    return {"数": len(values), "最小": min(values, default=None),
            "中央値": statistics.median(values) if values else None, "最大": max(values, default=None)}


def main() -> None:
    """登録母集団、選別集合、実参加、先着と回収を別々に保存する。

    引数: なし。
    返り値: None。条件・主core・成績・生明細を変更しない。
    """
    raw, cases, details, watches = [read(name) for name in (
        "全複合shadow.jsonl.gz", "入口事例.jsonl.gz", "全運用詳細.jsonl.gz", "監視.jsonl.gz")]
    contexts = read("全複合context.jsonl.gz")
    old_raw = read("全複合shadow.jsonl.gz", OLD_STUDY, OLD_WORK)
    canonical = {r["発動ID"]: r for r in raw}
    event_map, selected = {}, defaultdict(set)
    checks = 1
    if len(canonical) != len(raw):
        raise ValueError("原価格イベントID重複")
    for row in raw:
        if row["入口系統"] not in FAMILIES:
            raise ValueError("f/g以外が原価格イベントへ混入")
        if row["戦略判定"]["E1"]["採用"] and not row["戦略判定"]["E0"]["採用"]:
            raise ValueError("生E1がE0の部分集合でない")
        labels([row])
        checks += 2
    for row in cases:
        correct = canonical[row["発動ID"]]["戦略判定"]
        if row["戦略判定"] != correct or row["複合判定"] != correct[row["戦略"]] or not row["先着評価対象"]:
            raise ValueError("case採否snapshotまたは評価対象が不一致")
        if row["イベントID"] in event_map:
            raise ValueError("採用case重複")
        event_map[row["イベントID"]] = row
        selected[row["戦略"], row["期間"]].add(row["発動ID"])
        checks += 3
    for policy in ("E0", "E1"):
        for period in PERIODS:
            expected = {r["発動ID"] for r in raw if r["期間"] == period and r["戦略判定"][policy]["採用"]}
            if selected[policy, period] != expected:
                raise ValueError("正本採否と採用集合の不一致")
            checks += 1

    # ----------------------------------------
    # 同じ原発動から上位選別で何を除き、何を逃したかを分ける。
    stages, groups, participation = [], [], []
    quality = json.loads((STUDY / "入口品質.json").read_text(encoding="utf-8"))
    for period in PERIODS:
        for family in FAMILIES:
            own = [r for r in raw if r["期間"] == period and r["入口系統"] == family]
            m_ready = [r for r in own if r["共通M準備"] and r["時間条件可"]]
            e0 = [r for r in own if r["戦略判定"]["E0"]["採用"]]
            e1 = [r for r in own if r["戦略判定"]["E1"]["採用"]]
            removed = [r for r in e0 if not r["戦略判定"]["E1"]["採用"]]
            stages.append({"期間": period, "系統": family, "全価格発動": labels(own), "M時間通過": labels(m_ready),
                "E0価格と勢い": labels(e0), "E1上位通過": labels(e1), "上位で除外したE0": labels(removed),
                "上位除外群の逆行先着数": sum(r["ラベル"] == "逆行先着" for r in removed),
                "上位除外群の順行先着数": sum(r["ラベル"] == "順行先着" for r in removed)})
            for category in sorted({upper_group(r) for r in own}):
                for side in (1, -1):
                    subset = [r for r in own if upper_group(r) == category and r["side"] == side]
                    groups.append({"期間": period, "系統": family, "side": side, "上位理由": category,
                        "全価格発動": labels(subset), "E0採用": labels([r for r in subset if r["戦略判定"]["E0"]["採用"]]),
                        "E1採用": labels([r for r in subset if r["戦略判定"]["E1"]["採用"]])})
        a, b = selected["E0", period], selected["E1", period]
        participation.append({"期間": period, "共通原採用数": len(a & b), "E0のみ原採用数": len(a-b), "E1のみ原採用数": len(b-a)})

    # ----------------------------------------
    # 旧23は違う時計/準備/監視母集団であり、登録出典の共通部分だけを照合する。
    episodes = [r for r in watches if r["種別"] == "監視終了診断"]
    episode_map = {r["エピソードID"]: r for r in episodes}
    setup = {}
    for row in watches:
        if row["種別"] == "足監視" and row["監視後"]:
            state = row["監視後"]
            setup.setdefault(state["エピソードID"], state)
    if episode_map.keys() != setup.keys():
        raise ValueError("登録と終了episode集合が不一致")
    old_setup = {r["固定設定"]["エピソードID"]: r for r in old_raw if r["入口系統"] == "T突破"}
    for key in setup.keys() & old_setup.keys():
        current, previous = setup[key], old_setup[key]["固定設定"]
        for field in ("side", "境界", "R", "L", "ε", "30窓出典"):
            if current[field] != previous[field]:
                raise ValueError("共通実登録の固定出典が不一致: "+field)
            checks += 1
        for field in ("index", "start", "end", "confirm", "confirm_line", "atr"):
            if current["設定"][field] != previous["設定"][field]:
                raise ValueError("共通実登録の設定足が不一致")
            checks += 1
    lineage, episode_stages = [], []
    for period in PERIODS:
        keys = {r["エピソードID"] for r in episodes if r["期間"] == period}
        old_keys = {k for k, r in old_setup.items() if r["期間"] == period}
        lineage.append({"期間": period, "旧23実登録数": len(old_keys), "新24実登録数": len(keys),
            "共通実登録数": len(keys & old_keys), "旧23のみ実登録数": len(old_keys-keys), "新24のみ実登録数": len(keys-old_keys),
            "新登録の旧方向勢い単点資格あり": sum(setup[k]["登録旧23方向勢い資格"] for k in keys),
            "限界": "新母集団は価格登録/準備/状態を変更。方向勢いの単点資格を旧23実登録と読み替えない。"})
        own = [episode_map[k] for k in keys]
        f = {r["エピソードID"]: r for r in raw if r["期間"] == period and r["入口系統"] == "R内復帰"}
        g = {r["エピソードID"]: r for r in raw if r["期間"] == period and r["入口系統"] == "T外回復"}
        values = {"期間": period, "登録数": len(keys), "内復帰数": len(f), "外回復数": len(g),
            "終了理由別": dict(Counter(r["終了理由"] for r in own)),
            "登録から内復帰分": distribution([(r["要求時計秒"]-setup[k]["設定"]["confirm"])/60 for k, r in f.items()]),
            "内復帰から外回復分": distribution([(r["要求時計秒"]-f[k]["要求時計秒"])/60 for k, r in g.items()])}
        q = [r for r in quality if r["期間"] == period]
        for key, field in (("登録数", "設定数"), ("内復帰数", "内復帰価格消費数"), ("外回復数", "外回復価格消費数")):
            if values[key] != sum(r[field] for r in q):
                raise ValueError("監視/価格発動と正式段階数が不一致")
            checks += 1
        episode_stages.append(values)

    # ----------------------------------------
    # 一建玉の実参加と、仮先着の回収を別の集合で比較する。
    trades, handled = defaultdict(list), defaultdict(list)
    for row in details:
        key = row["候補ID"], row["品質"]["期間"]
        trades[key].extend(row["取引"])
        handled[key].extend(row["入口取扱"])
    official = json.loads((STUDY / "結果.json").read_text(encoding="utf-8"))
    result = {r["候補ID"]: r for r in official["結果"]}
    comparisons, protection, realization, operations, sequences = [], [], [], [], []
    for period in PERIODS:
        left, right = "3分_E0_X0", "3分_E1_X0"
        paired = P.compare(trades[left, period], trades[right, period], event_map, True)
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
    output = {"確認日": "2026-11-05", "全65場既使用": True, "対応集合全件一致": True, "照合項目数": checks,
        "全原発動数": len(raw), "純入口数": len(cases), "全case全戦略属性一致": True, "生E1はE0部分集合": True,
        "登録母集団と旧23": lineage, "段階": episode_stages, "役割別選別": stages, "上位理由別": groups,
        "原発動参加集合": participation, "運用対応": comparisons, "役割別運用抑止": operations,
        "同episode役割順序": sequences, "利益保護": protection, "入口先着と利益回収": realization,
        "数量診断準備": [{"期間": p, "全context数": sum(r["期間"] == p for r in contexts),
            "数量準備足数": sum(r["期間"] == p and bool(r["数量診断"] and r["数量診断"]["数量準備済"]) for r in contexts),
            "売買gate使用": False} for p in PERIODS],
        "コードSHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "結果SHA256": hashlib.sha256((STUDY / "結果.json").read_bytes()).hexdigest(),
        "旧結果SHA256": hashlib.sha256((OLD_STUDY / "結果.json").read_bytes()).hexdigest(),
        "限界": "全65場既使用。価格登録の母集団/準備/時計を23から変更し、E0/E1間だけ同じ価格eventで対照する。原先着と一建玉実参加、上位による選別と役割構成比、同episodeのR/Tを区別。過去の失敗率の補数を新反転の勝率とせず、将来の採否へラベルを戻さない。同値設定は実現同値・費用後非赤字を保証しない。"}
    (STUDY / "対応診断.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({k: output[k] for k in ("対応集合全件一致", "照合項目数", "全原発動数", "純入口数")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
