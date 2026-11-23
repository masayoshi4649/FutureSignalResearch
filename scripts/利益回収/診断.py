"""00008の完結取引から、含み益の消失と返済要求後の変化を事後診断する。"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00009_含み益の赤字化と決済時点の診断"
SOURCE = ROOT / "study/00008_外部研究を共通尺度へ移して探索"
WORK = ROOT / "work/外部研究/探索00008"
LIMITS = (5, 20, 50, 100)
REPRESENTATIVES = ("対照_3分開始15分失敗復帰_ADX20未満", "3分_RSI再加速_3_役割別", "5分_RSI回復_40_なし")
ROLES = {REPRESENTATIVES[0]: "開始幅の突破失敗からの反転仮説", REPRESENTATIVES[1]: "RSI再加速による順行仮説",
         REPRESENTATIVES[2]: "RSI回復による反転仮説"}
JST = timezone(timedelta(hours=9))


def sha(path: Path) -> str:
    """原板以外の小型入力のSHA256を求める。

    引数: path (Path) は対象。
    返り値: str はSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> Any:
    """日本語JSONを読む。

    引数: path (Path) は対象。
    返り値: Any はJSON値。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path: Path, value: Any) -> None:
    """日本語JSONを保存する。

    引数: path (Path) は保存先、value (Any) はJSON値。
    返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def load_helper() -> Any:
    """独立監査の正常板選別だけを再利用する。

    引数: なし。
    返り値: Any は補助。運用・指標・選定コードは読み込まない。
    """
    path = ROOT / "scripts/外部探索/運用独立監査.py"
    spec = importlib.util.spec_from_file_location("利益回収の正常板入力", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def first(mask: np.ndarray, offset: int = 0) -> int | None:
    """条件を満たす最初の位置を返す。

    引数: mask (np.ndarray) は真偽列、offset (int) は位置加算値。
    返り値: int|None は最初の位置または欠測。
    """
    positions = np.flatnonzero(mask)
    return int(positions[0]) + offset if len(positions) else None


def clock_jst(value: float | None) -> str | None:
    """任意の価格時計秒を閲覧用JST表記にする。

    引数: value (float|None) はUnix秒または欠測。
    返り値: str|None はJSTのISO表記または欠測。
    """
    return None if value is None else datetime.fromtimestamp(value, JST).isoformat()


def stats(values: list[float]) -> dict:
    """値幅や時間の記述統計を作る。

    引数: values (list[float]) は有限数列。
    返り値: dict は件数・最小・四分位・中央値・平均・最大。空集合は欠測。
    """
    keys = ("最小", "第1四分位", "中央値", "平均", "第3四分位", "最大")
    if not values:
        return {"件数": 0, **{k: None for k in keys}}
    a = np.asarray(values, dtype=float)
    return {"件数": len(a), **dict(zip(keys, map(float, (np.min(a), np.quantile(a, .25), np.median(a),
                                                             np.mean(a), np.quantile(a, .75), np.max(a)))))}


# ----------------------------------------
# 保有区間を原行で切り、返済側BBOを直接走査する。同時計も原行順を維持する。

def diagnose(trade: dict, q: dict) -> dict:
    """一完結取引の峰・初正益・赤字再訪・返済待機を診断する。

    引数: trade (dict) は保存取引、q (dict) は一場の正常板。
    返り値: dict は元取引と診断値。仮想の再約定や再参加は計算しない。
    """
    side = 1 if trade["方向"] == "買い" else -1
    start, end = q["at"][trade["新規原板行"]], q["at"][trade["返済原板行"]]
    if start > end:
        raise ValueError("返済原行が新規より前")
    now, lines = q["now"][start:end + 1], q["line"][start:end + 1]
    mark = (q["bid"] if side == 1 else q["ask"])[start:end + 1]
    distance = side * (mark - trade["新規価格"])
    mfe, mae = float(max(0, np.max(distance))), float(max(0, -np.min(distance)))
    if mfe != trade["観測最大順行pt"] or mae != trade["観測最大逆行pt"]:
        raise ValueError("保存MFE/MAEと両端を含む原行再計算が不一致")
    final_pt = trade["粗損益円"] / 10
    if float(distance[-1]) != final_pt or trade["基準純損益円"] != trade["粗損益円"] - 22:
        raise ValueError("保存会計と返済気配が不一致")
    peak = int(np.argmax(distance))
    last_peak = int(np.flatnonzero(distance == distance[peak])[-1])
    pos = first(distance > 0)
    net_pos = first(distance * 10 - 22 > 0)
    red = first(distance[pos + 1:] < 0, pos + 1) if pos is not None else None
    net_red = first(distance[net_pos + 1:] * 10 - 22 < 0, net_pos + 1) if net_pos is not None else None

    # ----------------------------------------
    # 期限要求は原行0の予約注入。同時計の後続板を既知の要求時価格にしない。
    request_line, request_time = trade["返済要求原板行"], trade["返済要求時計秒"]
    request_at = q["at"][request_line] if request_line else int(np.searchsorted(q["now"], request_time, side="left")) - 1
    request_mark = float((q["bid"] if side == 1 else q["ask"])[request_at]) if request_at >= 0 else None
    request_pt = side * (request_mark - trade["新規価格"]) if request_mark is not None else None
    result = {**trade, "診断ID": trade["手法"] + "/" + trade["場"] + "/" + trade["建玉ID"],
              "手法の役割仮説": ROLES.get(trade["手法"], "00008の複合条件"),
              "保存MFE一致": True, "保存MAE一致": True, "追跡正常板数": len(distance),
              "実現粗pt": final_pt, "最大観測返済差pt": float(distance[peak]),
              "観測峰時計秒": float(now[peak]), "観測峰最終時計秒": float(now[last_peak]), "観測峰原板行": int(lines[peak]),
              "初正粗益時計秒": None if pos is None else float(now[pos]),
              "初正純額時計秒": None if net_pos is None else float(now[net_pos]),
              "正粗益後の初粗赤字時計秒": None if red is None else float(now[red]),
              "正純額後の初純赤字時計秒": None if net_red is None else float(now[net_red]),
              "峰までのMAEpt": float(max(0, -np.min(distance[:peak + 1]))),
              "初正粗益までのMAEpt": None if pos is None else float(max(0, -np.min(distance[:pos + 1]))),
              "新規要求から約定秒_再計算": trade["新規時計秒"] - trade["新規要求時計秒"],
              "返済要求から約定秒_再計算": trade["返済時計秒"] - request_time,
              "峰から返済秒": trade["返済時計秒"] - float(now[peak]),
              "峰から返済の返し幅pt": float(distance[peak] - final_pt), "MFEから返済の差pt": mfe - final_pt,
              "失った正含み益pt": max(0, mfe - max(0, final_pt)),
              "失った正含み益換算円": max(0, mfe - max(0, final_pt)) * 10,
              "返済要求参照の返済差pt": request_pt,
              "返済要求参照板の古さ秒": None if request_at < 0 else request_time - float(q["now"][request_at]),
              "期限要求の直前板参考": request_line == 0,
              "返済要求参照から約定の差pt": None if request_pt is None else final_pt - request_pt,
              "返済待機で粗黒字から粗赤字": request_pt is not None and request_pt > 0 and final_pt < 0,
              "返済待機で純黒字から純赤字": request_pt is not None and request_pt * 10 - 22 > 0 and trade["基準純損益円"] < 0}
    for limit in LIMITS:
        reach = first(distance >= limit)
        after = reach + 1 if reach is not None else len(distance)
        r = first(distance[after:] < 0, after)
        n = first(distance[after:] * 10 - 22 < 0, after)
        result.update({f"{limit}pt初到達時計秒": None if reach is None else float(now[reach]),
                       f"{limit}pt後の初粗赤字時計秒": None if r is None else float(now[r]),
                       f"{limit}pt後の初純赤字時計秒": None if n is None else float(now[n])})
    for field in ("観測峰時計秒", "初正粗益時計秒", "初正純額時計秒", "正粗益後の初粗赤字時計秒", "正純額後の初純赤字時計秒"):
        result[field.replace("時計秒", "時計JST")] = clock_jst(result[field])
    return result


def aggregate(trades: list[dict], method: str, phase: str, sessions: int) -> dict:
    """一手法・期間のMFE到達後の最終赤字と途中再訪を集計する。

    引数: trades (list[dict]) は対象取引、method/phase (str) は名称、sessions (int) は入力場数。
    返り値: dict は固定4閾値の件数率、粗純額、値幅統計。
    """
    thresholds = []
    for limit in LIMITS:
        reached = [t for t in trades if t["観測最大順行pt"] >= limit]
        gross = [t for t in reached if t["粗損益円"] < 0]
        net = [t for t in reached if t["基準純損益円"] < 0]
        path_gross = [t for t in reached if t[f"{limit}pt後の初粗赤字時計秒"] is not None]
        path_net = [t for t in reached if t[f"{limit}pt後の初純赤字時計秒"] is not None]
        thresholds.append({"到達pt": limit, "到達取引数": len(reached), "最終粗赤字数": len(gross), "最終純赤字数": len(net),
                           "最終粗赤字率": len(gross) / len(reached) if reached else None, "最終純赤字率": len(net) / len(reached) if reached else None,
                           "途中粗赤字再訪数": len(path_gross), "途中純赤字再訪数": len(path_net),
                           "途中粗赤字再訪率": len(path_gross) / len(reached) if reached else None, "途中純赤字再訪率": len(path_net) / len(reached) if reached else None,
                           "途中純赤字後に黒字完結数": sum(t["基準純損益円"] > 0 for t in path_net),
                           "到達取引の経路注意数": sum(t["観測経路注意"] for t in reached),
                           "途中純赤字再訪未観測だが経路注意数": sum(t["観測経路注意"] and t[f"{limit}pt後の初純赤字時計秒"] is None for t in reached),
                           "失った正含み益換算円_到達全件": sum(t["失った正含み益換算円"] for t in reached),
                           "失った正含み益換算円_最終純赤字": sum(t["失った正含み益換算円"] for t in net),
                           "観測峰から返済返し幅pt": stats([t["峰から返済の返し幅pt"] for t in reached])})
    negative = [t for t in trades if t["基準純損益円"] < 0]
    return {"手法": method, "役割仮説": ROLES.get(method), "期間": phase, "実行済み入力場数": sessions, "完結取引数": len(trades),
            "観測経路注意取引数": sum(t["観測経路注意"] for t in trades),
            "実現粗損益円": sum(t["粗損益円"] for t in trades), "実現純損益円": sum(t["基準純損益円"] for t in trades),
            "純赤字取引数": len(negative), "粗赤字取引数": sum(t["粗損益円"] < 0 for t in trades),
            "粗0かつ費用で純赤字取引数": sum(t["粗損益円"] == 0 for t in negative),
            "正粗含み益を一度も観測しない終了赤字数": sum(t["観測最大順行pt"] == 0 for t in negative),
            "正粗含み益未観測かつ最終粗赤字数": sum(t["観測最大順行pt"] == 0 and t["粗損益円"] < 0 for t in negative),
            "正粗含み益後の終了赤字数": sum(t["観測最大順行pt"] > 0 for t in negative),
            "返済待機で純黒字から純赤字数": sum(t["返済待機で純黒字から純赤字"] for t in trades),
            "返済要求から約定秒": stats([t["返済要求から約定秒_再計算"] for t in trades]),
            "MFEpt": stats([t["観測最大順行pt"] for t in trades]), "MAEpt": stats([t["観測最大逆行pt"] for t in trades]),
            "実現粗額円": stats([t["粗損益円"] for t in trades]), "実現純額円": stats([t["基準純損益円"] for t in trades]), "到達後の赤字": thresholds}


# ----------------------------------------
# 小事例は固定規則で最大約10件。事後の説明例であり新たな戦略選定ではない。

def examples(trades: list[dict]) -> list[dict]:
    """代表3手法の3機序と既使用新1の実取引を選ぶ。

    引数: trades (list[dict]) は診断済み全取引。
    返り値: list[dict] は重複を避けた説明例。
    """
    chosen, used = [], set()
    for method in REPRESENTATIVES:
        group = [t for t in trades if t["手法"] == method and t["期間"] != "既使用11月4日"]
        plans = (("20pt以上の含み益から最終純赤字", lambda t: t["観測最大順行pt"] >= 20 and t["基準純損益円"] < 0, "峰から返済の返し幅pt"),
                 ("正粗含み益なしの終了赤字", lambda t: t["観測最大順行pt"] == 0 and t["基準純損益円"] < 0, "観測最大逆行pt"),
                 ("返済要求後の不利変化が大きい例", lambda t: t["返済要求参照から約定の差pt"] is not None, "返済待機不利幅pt"))
        for purpose, accept, key in plans:
            group2 = [{**t, "返済待機不利幅pt": max(0, -(t["返済要求参照から約定の差pt"] or 0))} for t in group if accept(t) and t["診断ID"] not in used]
            if group2:
                item = sorted(group2, key=lambda t: (-t[key], t["新規時計秒"], t["診断ID"]))[0]
                chosen.append({"選択理由": purpose, **item})
                used.add(item["診断ID"])
    chosen.extend({"選択理由": "既使用11月4日の全実取引", **t} for t in trades if t["期間"] == "既使用11月4日")
    return chosen


def make_readme(result: dict, count: int) -> str:
    """定義・代表結果・限界・再現手順をMarkdownへまとめる。

    引数: result (dict) は集計正本、count (int) は小事例数。
    返り値: str は日本語Markdown。
    """
    text = """# 含み益の赤字化と決済時点の診断

00008の保存済み完結取引を診断した。「利確が遅い」を前提にせず、正含み益を観測しなかった損失、利益の消失、返済要求後の気配変化を分ける。新しい出口の損益比較や最適化は行っていない。

## 入力と区分

旧64場の全33候補2,956取引と、固定済み11月4日デイの新候補1取引を使う。学習40場、条件選択24場、既使用11月4日1場を分ける。11月4日は00008で開封済みで、未使用検証ではない。後続未実行の31候補を0取引にしない。候補間には同一入口・経路の重複があり、33候補を独立な試行数や期待収益として合算しない。

正本は00008の入力台帳と作業詳細gzip。参照とSHAは[条件.json](条件.json)・[集計.json](集計.json)。原板を複製せず、既存cacheの正常板を直接走査し、全2,957完結取引の保存MFE/MAEと一致した。

## 定義

買いはBid、売りはAskの返済側気配に対し d=方向×(返済BBO−新規価格)、粗換算額10×d、往復費用込み参考額10×d−22円とする。実際のmicro板・約定数量・通信/取引所遅延を復元した額ではない。

MFE=max(0,max d)、MAE=max(0,−min d)。新規/返済原行を両端とも含み、同価格時計の変化も原行で切る。全観測が赤字ならMFE=0でも0ptの返済機会があった意味ではない。実際の最大dとその時計も別保存する。

5/20/50/100pt到達取引を分母に、最終粗赤字・最終純赤字、最初の到達原行より後の途中粗/純赤字再訪を別集計する。赤字は0未満。5pt刻みではd=0でも往復22円控除後は純赤字になる。途中赤字から黒字完結した件数も区別する。

「峰から返済の返し幅」は実際のmax d−最終d。「失った正含み益」はMFE−max(最終d,0)で、赤字領域へ進んだ追加損失を含めない。未来の峰はその時点では未知で、+1秒後に回収できた額を保証しない。

## 代表3手法の20pt到達後

順行/反転は入口の役割の仮説。RSI再加速を順行、RSI回復と開始幅失敗を反転候補として分け、個別経路のトレンドを断定しない。

| 手法 | 区分 | 完結 | 20pt到達 | 最終純赤字 | その率 | 途中純赤字再訪 | 観測純額円 |
|---|---|---:|---:|---:|---:|---:|---:|
"""
    for row in result["手法別期間別"]:
        if row["手法"] in REPRESENTATIVES:
            t = next(v for v in row["到達後の赤字"] if v["到達pt"] == 20)
            rate = "—" if t["最終純赤字率"] is None else f'{t["最終純赤字率"]:.1%}'
            text += f'| {row["手法"]} | {row["期間"]} | {row["完結取引数"]} | {t["到達取引数"]} | {t["最終純赤字数"]} | {rate} | {t["途中純赤字再訪数"]} | {row["実現純損益円"]:,.0f} |\n'
    text += f"""

全33手法・4閾値・値幅分布は集計JSON。観測経路注意を勝手に除外せず件数を併記する。純額は00008の観測代理会計であり、注意を含む全体の確定利益ではない。

## 直接診断した小事例

[事例.csv](事例.csv)は{count}件。代表3手法ごとに①20pt以上から最終純赤字の返し幅最大、②正益なしの赤字でMAE最大、③未選択から返済待機不利最大を選んだ。同率は新規時計・ID順。既使用11月4日の実取引も全件載せる。事後の説明例で、頻度や収益性の証拠にしない。

峰の最初/最終時計、初正益/赤字化時計、峰前MAE、注文遅延、要求後の気配差を残す。価格時計はCurrentPriceTimeであり正確な受信・判断・取引所約定時刻ではない。期限要求は原行0の予約注入なので、要求時計より厳密に前の板だけを参考にし古さを併記する。同時計の後続板を要求時に既知と扱わない。

## 解釈と次の検証

利益が消えた事実だけでは早期利確が優位とはいえない。早い決済は後の250pt到達を失い、費用・待機・一建玉の機会・再参加が変わる。次の出口案は幅と発動を事前固定し逐次再生する。初期逆行を避ける入口変更と利益保護は分ける。

MFEは返済までの未来を使う事後値。終了後の経路や仮想再参加は診断しない。300秒超空白は観測できず、経路注意を保持する。途中赤字再訪は観測されたものだけを数え、空白のある区間で再訪を観測しなかったことを「赤字化しなかった」とは扱わない。閾値到達取引の経路注意数、途中純赤字再訪未観測だが注意ありの件数も残す。完結取引の診断で未解消損失を説明したとは主張しない。

## 再現

~~~powershell
python -X utf8 scripts/利益回収/診断.py
~~~

Python 3とNumPyを使用する。cacheのSHA/statを検査し原板を全読みしない。作業gzipがなければ00008の固定再現出力が必要で、原板複製で代替しない。コード・依存・入力SHAを集計へ保存する。

合成境界検証は python -X utf8 scripts/利益回収/診断検証.py で行う。[診断合成検証.json](診断合成検証.json)へ明示合否を残す。到達前の赤字との分離、同時計の返済後原行除外、粗0/純赤字、売買鏡像、MFE初期0、期限原行0の既知板などを確認する。

独立確認は python -X utf8 scripts/利益回収/診断独立確認.py 。[独立確認.json](独立確認.json)に、元gzipからの68群×4閾値の到達/終了赤字/粗純額と、10例中3例の峰・途中赤字・要求板の直接走査を記録する。全取引の途中経路を独立に二重再生した意味ではない。期限例が小CSVにないため、別の保存期限取引の厳密過去板とコード境界を確認した範囲も明記する。

確認日：2026-11-04。一次資料：[00008](../00008_外部研究を共通尺度へ移して探索/README.md)、[運用コード](../../scripts/広域研究/運用検証.py)、[データ形式](../../docs/データと閲覧形式.md)。共通表は[設定と結果.md](設定と結果.md)へ記録する。
"""
    return text


def run() -> dict:
    """全保存完結取引を小型の診断集計と事例へまとめる。

    引数: なし。新たな注文や元結果変更を行わない。
    返り値: dict は診断正本。不一致・入力変更なら停止する。
    """
    STUDY.mkdir(parents=True, exist_ok=True)
    helper = load_helper()
    manifest = SOURCE / "入力台帳.json"
    entries = {e["session"]: e for e in read(manifest)["entries"]}
    inputs = {"探索": WORK / "探索_運用詳細.jsonl.gz", "既使用11月4日": WORK / "後続_運用詳細.jsonl.gz"}
    config = {"版": 1, "試行": "00009", "用途": "00008保存完結取引の事後診断。最適化ではない",
              "入力": {p: {"path": v.relative_to(ROOT).as_posix(), "SHA256": sha(v)} for p, v in inputs.items()},
              "入力台帳": {"参照": "../" + SOURCE.name + "/入力台帳.json", "SHA256": sha(manifest)},
              "期間": {"学習": 40, "条件選択": 24, "既使用11月4日": 1}, "到達閾値pt": list(LIMITS),
              "倍率": 10, "往復費用円": 22, "代表手法": list(REPRESENTATIVES),
              "赤字定義": "粗/純0未満。最終赤字と最初の到達原行より後の途中再訪を区別",
              "例の規則": "代表3手法×20pt後終了赤字の返し幅最大/正益なし赤字MAE最大/残りから返済待機不利最大。同率は時計・ID順。既使用新1実取引を全件追加"}
    config_path = STUDY / "条件.json"
    if config_path.exists() and read(config_path) != config:
        raise ValueError("固定した診断条件/入力が変わったため上書きしない")
    write(config_path, config)
    write(STUDY / "入力台帳.json", config["入力台帳"])
    cached, trades, coverage = {}, [], []
    for phase, path in inputs.items():
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for raw in stream:
                d = json.loads(raw)
                method, session = d["候補ID"], d["場"]
                if (phase == "探索" and session >= "2026-11-04") or (phase != "探索" and session != "2026-11-04_Day"):
                    raise ValueError("診断入力の区分外")
                period = d["品質"]["期間"] if phase == "探索" else phase
                coverage.append((method, period, session))
                if d["取引"] and session not in cached:
                    cached[session] = helper.quotes(entries[session], True)
                for trade in d["取引"]:
                    trades.append(diagnose({**trade, "期間": period}, cached[session]))
    if len(trades) != 2957:
        raise ValueError("固定元の2957完結取引でない")
    groups = sorted({(m, p) for m, p, s in coverage})
    summaries = [aggregate([t for t in trades if (t["手法"], t["期間"]) == (m, p)], m, p,
                           len({s for a, b, s in coverage if (a, b) == (m, p)})) for m, p in groups]
    selected = examples(trades)
    columns = ["選択理由", "診断ID", "手法", "手法の役割仮説", "期間", "場", "方向", "入口イベントID", "建玉ID",
               "新規時計JST", "新規時計秒", "新規原板行", "返済時計JST", "返済時計秒", "返済原板行", "返済理由",
               "観測最大順行pt", "観測最大逆行pt", "粗損益円", "基準純損益円", "最大観測返済差pt",
               "観測峰時計秒", "観測峰最終時計秒", "観測峰原板行", "初正粗益時計秒", "初正純額時計秒",
               "正粗益後の初粗赤字時計秒", "正純額後の初純赤字時計秒", "峰までのMAEpt", "初正粗益までのMAEpt",
               "新規要求から約定秒_再計算", "返済要求から約定秒_再計算", "峰から返済秒",
               "峰から返済の返し幅pt", "MFEから返済の差pt", "失った正含み益pt", "失った正含み益換算円",
               "返済要求参照の返済差pt", "返済要求参照板の古さ秒", "期限要求の直前板参考",
               "返済要求参照から約定の差pt", "返済待機で粗黒字から粗赤字", "返済待機で純黒字から純赤字",
               "観測経路注意", "追跡正常板数"]
    columns += ["観測峰時計JST", "初正粗益時計JST", "初正純額時計JST", "正粗益後の初粗赤字時計JST", "正純額後の初純赤字時計JST"]
    columns += [f"{limit}pt{tail}" for limit in LIMITS for tail in ("初到達時計秒", "後の初粗赤字時計秒", "後の初純赤字時計秒")]
    with (STUDY / "事例.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(selected)
    result = {"版": 1, "確認日": "2026-11-04", "全MFE_MAE一致": True, "完結取引数": len(trades),
              "保存MFE_MAE照合項目数": 2 * len(trades), "入力出所": config["入力"], "条件SHA256": sha(config_path),
              "入力台帳SHA256": sha(manifest), "コードSHA256": sha(Path(__file__)),
              "正常板選別補助SHA256": sha(ROOT / "scripts/外部探索/運用独立監査.py"),
              "選別補助の汎用部SHA256": sha(ROOT / "scripts/広域研究/運用独立監査.py"),
              "環境": {"Python": sys.version, "NumPy": np.__version__},
              "手法別期間別": summaries, "小事例数": len(selected), "小事例SHA256": sha(STUDY / "事例.csv"),
              "後続未実行": "既使用11月4日は固定RSI回復と対照だけ。他31候補は未実行であり0取引としない。",
              "限界": ["保存完結取引の事後診断。入口・出口を最適化していない。", "未来のMFEは回収可能益ではない。",
                       "候補間に重複入口・同経路があり、独立標本として合算しない。", "経路注意を除外せず件数併記。価格時計は受信時計ではない。"]}
    write(STUDY / "集計.json", result)
    (STUDY / "README.md").write_text(make_readme(result, len(selected)), encoding="utf-8")
    print(json.dumps({"完結取引数": len(trades), "全MFE_MAE一致": True, "手法期間群": len(summaries), "小事例数": len(selected)}, ensure_ascii=False))
    return result


if __name__ == "__main__":
    run()
