"""保存明細から入口時点の移動、監視の失効、実参加と利益回収を分ける。"""

from collections import Counter, defaultdict
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00023_上位高安の再テストと順行再開"
WORK = ROOT / "work/高安再開/00023"
OLD_STUDY = ROOT / "study/00022_ADXと上位BB幅の変化による局面切替"
OLD_WORK = ROOT / "work/局面変化/00022"
PERIODS = ("学習", "条件選択", "後続検査")
LABELS = ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定")
NUMBERS = ("新規価格", "新規時計秒", "新規原板行", "判定時計秒", "判定原板行",
           "判定気配", "最大順行pt", "最大逆行pt", "所要分")


def module(path: Path, name: str) -> Any:
    """既存の同実新規会計の対応補助だけを読む。

    引数: path(Path)は補助、name(str)は識別名。
    返り値: Anyはモジュール。23の主入口や運用を再実行しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


P = module(ROOT / "scripts/VWAP復帰/対応診断.py", "高安再開の同実新規対応")


def read(name: str, study: Path = STUDY, work: Path = WORK) -> list[dict]:
    """内容指紋を確認して圧縮明細を読む。

    引数: name(str)はファイル名、study/work(Path)は正式台帳と作業明細の場所。
    返り値: list[dict]は全保存行。原価格は複製も再走査もしない。
    """
    artifacts = json.loads((study / "作業成果物.json").read_text(encoding="utf-8"))
    expected = next(r["展開内容SHA256"] for r in artifacts["ファイル"] if r["パス"].endswith("/"+name))
    with gzip.open(work / name, "rb") as stream:
        data = stream.read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("作業明細の内容指紋が不一致")
    return [json.loads(row) for row in data.splitlines() if row.strip()]


def labels(rows: list[dict]) -> dict:
    """時間条件外を分け、評価対象の五分類と率を集計する。

    引数: rows(list[dict])は保存された原発動または採用caseの群。
    返り値: dictは全数・対象外数・約定候補の分母と先着率。
    """
    own = [r for r in rows if r["先着評価対象"]]
    excluded = [r for r in rows if not r["先着評価対象"]]
    for row in excluded:
        if row["ラベル"] != "対象外" or row["理由"] != "要求時間条件外" or any(row[k] is not None for k in NUMBERS):
            raise ValueError("先着対象外の表示または欠測が不一致")
    values = Counter(r["ラベル"] for r in own)
    if values.keys()-set(LABELS):
        raise ValueError("評価対象の未知ラベル")
    filled = len(own)-values["未約定"]
    return {"候補数": len(rows), "先着評価対象数": len(own), "対象外数": len(excluded),
            "約定候補数": filled, **{k: values[k] for k in LABELS},
            "確認率": values["順行先着"]/filled if filled else None}


def distribution(values: list[float]) -> dict:
    """距離や待機時間の範囲を小さく要約する。

    引数: values(list[float])は欠測を除いた診断量。
    返り値: dictは数・最小・中央値・最大。新しい選別閾値は作らない。
    """
    return {"数": len(values), "最小": min(values, default=None),
            "中央値": statistics.median(values) if values else None, "最大": max(values, default=None)}


def main() -> None:
    """同じ登録の遅い入口と、同じ実新規の出口差を別々に保存する。

    引数: なし。
    返り値: None。固定core・条件・正式成績は変更しない。
    """
    raw, cases, details, watches, contexts = [read(name) for name in (
        "全複合shadow.jsonl.gz", "入口事例.jsonl.gz", "全運用詳細.jsonl.gz", "監視.jsonl.gz", "全複合context.jsonl.gz")]
    old_raw = read("全複合shadow.jsonl.gz", OLD_STUDY, OLD_WORK)
    old_r = {r["発動ID"]: r for r in old_raw if r["時間足分"] == 3 and r["入口系統"] == "R1"}
    current_r = {r["発動ID"]: r for r in raw if r["入口系統"] == "R1"}
    checks = 1
    if old_r.keys() != current_r.keys():
        raise ValueError("旧22の3分R1発動集合が不一致")
    fields = ("index", "start", "end", "open", "high", "low", "close", "confirm", "confirm_line", "atr",
              "macd", "macd_signal", "macd_hist", "stoch_raw", "stoch_k", "stoch_d", "bb_mean", "bb_sd", "bandwidth",
              "side", "要求時計秒", "要求原板行", "S2局面", "S2方向", "S2理由", "共通M22準備")
    for key, row in current_r.items():
        for field in (*fields, "ラベル", "理由", *NUMBERS):
            if row["旧22R1"].get(field) != old_r[key].get(field) and field in fields:
                raise ValueError("旧R1の入力/発動属性が不一致: "+field)
            if field not in fields and row[field] != old_r[key][field]:
                raise ValueError("旧R1の原先着が不一致: "+field)
            checks += 1
    canonical = {r["発動ID"]: r for r in raw}
    if len(canonical) != len(raw):
        raise ValueError("全発動ID重複")
    event_map, selected = {}, defaultdict(set)
    for row in cases:
        correct = canonical[row["発動ID"]]["戦略判定"]
        if row["戦略判定"] != correct or row["複合判定"] != correct[row["戦略"]] or not row["先着評価対象"]:
            raise ValueError("caseの採否snapshotまたは評価対象が不一致")
        if row["イベントID"] in event_map:
            raise ValueError("採用case重複")
        event_map[row["イベントID"]] = row
        selected[row["戦略"], row["期間"]].add(row["発動ID"])
        checks += 3
    for policy in ("B0", "C0"):
        for period in PERIODS:
            expected = {r["発動ID"] for r in raw if r["期間"] == period and r["戦略判定"][policy]["採用"]}
            if selected[policy, period] != expected:
                raise ValueError("全発動採否と採用集合の不一致")
            checks += 1

    # ----------------------------------------
    # 同じepisodeでもB0/C0は新規時計と価格が違い、純粋な出口比較ではない。
    episodes = [r for r in watches if r["種別"] == "監視終了診断"]
    episode_map = {r["エピソードID"]: r for r in episodes}
    setup = {r["固定設定"]["エピソードID"]: r for r in raw if r["入口系統"] == "T突破"}
    reopen = {r["固定設定"]["エピソードID"]: r for r in raw if r["入口系統"] == "T再開"}
    if episode_map.keys() != setup.keys() or not reopen.keys() <= setup.keys():
        raise ValueError("登録/再開/終了episodeの対応が不一致")
    retests = {}
    for row in watches:
        if row["種別"] != "足監視":
            continue
        for name in ("監視前", "監視後"):
            state = row[name]
            if state and state["再テスト"] is not None:
                key, point = state["エピソードID"], state["再テスト"]
                if key in retests and retests[key] != point:
                    raise ValueError("再テストの固定高安が変化")
                retests[key] = point
                checks += 1
    stages, cohorts, paired_entries, preparation = [], [], [], []
    entry_quality = json.loads((STUDY / "入口品質.json").read_text(encoding="utf-8"))
    for period in PERIODS:
        keys = [k for k, r in setup.items() if r["期間"] == period]
        endings = Counter(episode_map[k]["終了理由"] for k in keys)
        stages.append({"期間": period, "設定数": len(keys), "再テスト登録数": sum(k in retests for k in keys),
            "再開価格発動数": sum(k in reopen for k in keys),
            "再開採用数": sum(k in reopen and reopen[k]["戦略判定"]["C0"]["採用"] for k in keys),
            "時間条件外消費数": sum(k in reopen and not reopen[k]["先着評価対象"] for k in keys),
            "終了理由別": dict(endings), "監視中strict内復帰数": sum(episode_map[k]["最初内側終値"] is not None for k in keys)})
        own_quality = [r for r in entry_quality if r["期間"] == period]
        for key in ("設定数", "再テスト登録数", "再開採用数"):
            if stages[-1][key] != sum(r[key] for r in own_quality):
                raise ValueError("終了明細と入口品質の段階件数が不一致: "+key)
            checks += 1
        for left, right in (("再開価格発動数", "再開価格消費数"), ("時間条件外消費数", "先着評価対象外数")):
            if stages[-1][left] != sum(r[right] for r in own_quality):
                raise ValueError("原発動と入口品質の価格消費数が不一致")
            checks += 1
        for reason in sorted(endings):
            own = [setup[k] for k in keys if episode_map[k]["終了理由"] == reason]
            cohorts.append({"期間": period, "終了理由": reason, "突破時の原先着": labels(own)})
        for policy, family in (("B0", "T突破"), ("C0", "T再開"), ("両方", "R1")):
            own = [r for r in raw if r["期間"] == period and r["入口系統"] == family]
            if family == "R1":
                accepted = [r for r in own if r["戦略判定"]["B0"]["採用"]]
                old_accepted = [old_r[r["発動ID"]] for r in own if old_r[r["発動ID"]]["戦略判定"]["S2"]["採用"]]
                preparation.append({"期間": period, "旧22S2_R1採用": labels([{**r, "先着評価対象": True} for r in old_accepted]),
                    "新M23_R1採用": labels(accepted),
                    "30窓等で除外された旧採用": labels([r for r in own if old_r[r["発動ID"]]["戦略判定"]["S2"]["採用"] and not r["戦略判定"]["B0"]["採用"]])})
            for side in (1, -1):
                own_side = [r for r in own if r["side"] == side]
                cohorts.append({"期間": period, "戦略": policy, "系統": family, "side": side, "全原発動": labels(own_side),
                    "採用": labels([r for r in own_side if r["戦略判定"]["B0" if policy == "両方" else policy]["採用"]])})
        matched = [k for k in keys if k in reopen and reopen[k]["戦略判定"]["C0"]["採用"]]
        left, right = [setup[k] for k in matched], [reopen[k] for k in matched]
        filled = [k for k in matched if setup[k]["新規価格"] is not None and reopen[k]["新規価格"] is not None]
        paired_entries.append({"期間": period, "再開採用episode数": len(matched), "同じepisode突破時先着": labels(left),
            "同じepisode再開時先着": labels(right),
            "要求待機分": distribution([(reopen[k]["要求時計秒"]-setup[k]["要求時計秒"])/60 for k in matched]),
            "方向化した仮新規価格差pt_C0引くB0": distribution([setup[k]["side"]*(reopen[k]["新規価格"]-setup[k]["新規価格"]) for k in filled]),
            "限界": "再開できたepisodeだけの条件付き対応。時点/価格/ATRが変わり、待機の因果的優位性や純出口効果を示さない。"})

    # ----------------------------------------
    # 実参加は一建玉で別に抑止される。同じ実新規は同じ出口のままか照合する。
    trades = defaultdict(list)
    for row in details:
        trades[row["候補ID"], row["品質"]["期間"]].extend(row["取引"])
    official = json.loads((STUDY / "結果.json").read_text(encoding="utf-8"))
    results = {r["候補ID"]: r for r in official["結果"]}
    comparisons, protection, realization, episode_trades = [], [], [], []
    for period in PERIODS:
        a, b = "3分_B0_X0", "3分_C0_X0"
        paired = P.compare(trades[a, period], trades[b, period], event_map, True)
        expected = results[b][period]["運用"]["追加0pt純損益円"]-results[a][period]["運用"]["追加0pt純損益円"]
        if paired["全運用純額差円"] != expected:
            raise ValueError("全額差と実参加分解の不一致")
        comparisons.append({"期間": period, "左": a, "右": b, "運用比較": paired})
        checks += 1
        by_policy = {}
        for cid in (a, b):
            own = trades[cid, period]
            armed = [t for t in own if t["追尾起動"]]
            protection.append({"候補ID": cid, "期間": period, "完結数": len(own), "追尾起動数": len(armed),
                "起動後純赤字数": sum(t["基準純損益円"] < 0 for t in armed),
                "起動後同値未満約定数": sum((1 if t["方向"] == "買い" else -1)*(t["返済価格"]-t["新規価格"]) < 0 for t in armed),
                "最終設定未満約定数": sum(t["最終追尾から実返済方向差pt"] < 0 for t in armed),
                "最終設定からの不足pt計": sum(max(0, -t["最終追尾から実返済方向差pt"]) for t in armed)})
            by_policy[cid] = {}
            for role in ("順行", "反転"):
                subset = [t for t in own if event_map[t["入口イベントID"]]["役割"] == role]
                for trade in subset:
                    case = event_map[trade["入口イベントID"]]
                    for field in ("新規時計秒", "新規原板行", "新規価格"):
                        if trade[field] != case[field]:
                            raise ValueError("実新規と仮先着新規の不一致")
                        checks += 1
                    if role == "順行":
                        key = case["固定設定"]["エピソードID"]
                        if key in by_policy[cid]:
                            raise ValueError("同episodeの実参加が重複")
                        by_policy[cid][key] = trade
                winners = [t for t in subset if event_map[t["入口イベントID"]]["ラベル"] == "順行先着"]
                realization.append({"候補ID": cid, "期間": period, "役割": role, "実新規対応数": len(subset),
                    "対応先着250数": len(winners), "先着250だが基準純赤字数": sum(t["基準純損益円"] < 0 for t in winners),
                    "先着250だが250利確以外数": sum(t["返済理由"] != "利確" for t in winners),
                    "基準純額円": sum(t["基準純損益円"] for t in subset),
                    "追加5pt純額円": sum(t["追加滑り5pt純損益円"] for t in subset)})
        left, right = by_policy[a], by_policy[b]
        common = left.keys() & right.keys()
        episode_trades.append({"期間": period, "両運用実参加episode数": len(common),
            "同episode_B0純額円": sum(left[k]["基準純損益円"] for k in common),
            "同episode_C0純額円": sum(right[k]["基準純損益円"] for k in common),
            "B0のみ実参加episode数": len(left.keys()-right.keys()), "C0のみ実参加episode数": len(right.keys()-left.keys()),
            "限界": "同じ設定でも入口時点/価格/ATRと後続経路が違う。純粋な出口比較ではない。"})
    output = {"確認日": "2026-11-05", "全65場既使用": True, "対応集合全件一致": True, "照合項目数": checks,
        "全原発動数": len(raw), "純入口数": len(cases), "全case全戦略属性一致": True,
        "旧22R1発動数": len(old_r), "旧R1照合属性数": len(fields),
        "段階": stages, "発動と監視終了別": cohorts, "旧R1準備差": preparation,
        "同episode入口対応": paired_entries, "運用対応": comparisons, "同episode実参加対応": episode_trades,
        "利益保護": protection, "入口先着と利益回収": realization,
        "数量診断準備": [{"期間": period, "全context数": sum(r["期間"] == period for r in contexts),
            "数量準備足数": sum(r["期間"] == period and bool(r["数量診断"] and r["数量診断"]["数量準備済"]) for r in contexts),
            "売買gate使用": False} for period in PERIODS],
        "コードSHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "結果SHA256": hashlib.sha256((STUDY / "結果.json").read_bytes()).hexdigest(),
        "限界": "全65場は既使用。監視終了理由別の先着は事後の機会診断で、未来を入口へ戻さない。B0/C0の重複R1・同episode・同日を独立標本に加算しない。率上昇/活動減少/平均損益/品質注意を分ける。時間条件外の消費は未約定と別。共通実新規の出口差と異なる新規時点のepisode対応を混同しない。"}
    (STUDY / "対応診断.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({k: output[k] for k in ("対応集合全件一致", "照合項目数", "全原発動数", "純入口数", "旧22R1発動数")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
