"""00015の保存結果から12入口・12X0の三文書と51×9表を作る。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00015_RSIの山谷と価格構造"
DISPLAY = ROOT/"scripts/数量反転/レポート.py"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = {"学習": "学習40場", "条件選択": "条件選択24場", "後続検査": "既使用11/4デイ1場"}
FAMILIES = {"反転乖離": "反転", "押し戻り継続": "順行"}
EXTRAS = ("なし", "ネック位置確認")


def display_helper() -> Any:
    """旧帳票の汎用検算と表描画だけを読み込む。

    引数: なし。
    返り値: Any は12件の保存集計検算と表示補助。価格・入口・数量・売買は再生しない。
    """
    spec = importlib.util.spec_from_file_location("RSI構造の共通帳票表示", DISPLAY)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


BASE = display_helper()
G, P, number = BASE.G, BASE.P, BASE.number


def definitions(config: dict) -> list[dict]:
    """固定三尺度・二極値関係・二追加確認を評価IDへ対応付ける。

    引数: config (dict) は条件正本。
    返り値: list[dict] は12入口と全X0のR01〜R12。
    """
    if config["時間足分"] != [1, 3, 5] or config["入口系統"] != list(FAMILIES) or config["補助"] != list(EXTRAS) or config["出口"] != [{"出口ID": "X0"}]:
        raise ValueError("固定三尺度・二系統・二補助・X0と異なる")
    if config["極値条件"] != {"左足本数": 2, "右足本数": 2, "中心間隔下限本数": 3, "中心間隔上限本数": 20, "RSI期間": 14} or (config["逆行pt"], config["順行pt"]) != (125, 250):
        raise ValueError("左右2本・間隔3〜20本・RSI14・125/250と異なる")
    rows = []
    for size in config["時間足分"]:
        for family, role in FAMILIES.items():
            for extra in EXTRAS:
                source = {"入口ID": f"{size}分_{family}_{extra}", "入口系統": family, "時間足分": size,
                          "補助": extra, "名称": family, "役割": role}
                rows.append({"候補ID": source["入口ID"]+"_X0", "入口": source, "出口": {"出口ID": "X0"}, "評価ID": f"R{len(rows)+1:02d}"})
    return rows


# ----------------------------------------
# 公開足と全pivot・隣接対・発動を混ぜずに保存品質を集計する。

def pivot_tables(study: Path) -> str:
    """保存入口品質から全極値と不採用理由を表示する。

    引数: study (Path) は正式試行。
    返り値: str は尺度別・期間別の状態数。理由は複数併記なので段階的な減算に使わない。
    """
    path = study/"入口品質.json"
    if not path.exists():
        return "## 全極値と入口準備\n\n入口品質は未保存。\n\n"
    totals, reasons, triggers = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
    for row in G.read_json(path):
        key = row["時間足分"], row["期間"]
        totals[key].update({k: v for k, v in row.items() if isinstance(v, (int, float)) and k != "時間足分"})
        reasons[key].update(row.get("極値除外理由", {}))
        triggers[key].update(row.get("系統別発動数", {}))
    rows, rejected = [], []
    for size in (1, 3, 5):
        for period in PERIODS:
            item = totals[(size, period)]
            lows, highs = item["確定安値数"], item["確定高値数"]
            rows.append([size, PERIOD_NAMES[period], item["公開足"], f"{lows}/{highs}", lows+highs,
                         item["隣接対数"], item["距離適合対数"], item["中心RSI準備対数"], item["価格RSI型適合対数"],
                         item["共通準備可極値数"], item["共通時間条件可極値数"],
                         sum(v for k, v in triggers[(size, period)].items() if k.endswith("_なし")),
                         sum(v for k, v in triggers[(size, period)].items() if k.endswith("_ネック位置確認"))])
            rejected.append([size, PERIOD_NAMES[period], G.describe(dict(reasons[(size, period)])),
                             item["連続窓リセット"], item["非公開リセット"], item["確認遅延超過発動"]])
    text = "## 全極値と入口準備\n\n全pivotは価格だけで確定した安値/高値で、入口の準備・時間・距離・RSI不成立でも保存・更新する。隣接対は各側の直前一極値との対で、古い極値を探し直さない。距離適合・中心RSI準備・型適合・共通準備はそれぞれ別条件の集計で、左から右へ減っていく漏斗ではない。なし/ネック入口は二系統合計で、同じ発動は両側に重複し得る。\n"
    text += G.table(["足分", "期間", "公開足", "安値/高値pivot", "全pivot", "隣接対", "距離適合対", "中心RSI準備対", "価格RSI型適合対", "共通準備可pivot", "共通時間可pivot", "なし入口", "ネック入口"], rows)
    text += "### 不成立理由と連続性\n\n理由は一pivotへ複数付く。ネック不成立は同足の追加選別にだけ適用し、下表のbaseline理由に重複加算しない。30秒超の確認遅延発動は入口候補として保存するが、先着ラベルは未約定、運用も新規対象外になる。\n"
    return text + G.table(["足分", "期間", "追加確認前の除外理由・重複あり", "欠枠/index飛越reset", "非公開reset", "確認遅延超過発動"], rejected)


def findings(entries: dict, values: dict) -> str:
    """同足ネック位置条件の有無を旧二期間の全六組で表示する。

    引数: entries/values (dict) は保存入口/運用のID別集計。
    返り値: str は記述表。候補の選び直しや閾値の最適化はしない。
    """
    rows = []
    for size in (1, 3, 5):
        for family in FAMILIES:
            for period in PERIODS[:2]:
                a, b = [entries[f"{size}分_{family}_{extra}"][period] for extra in EXTRAS]
                qa, qb = [values[f"{size}分_{family}_{extra}_X0"][period]["運用"] for extra in EXTRAS]
                rows.append([size, family, PERIOD_NAMES[period], f"{a['順行先着']}/{a['約定候補数']}・{G.pct(a['確認率'])}",
                             f"{b['順行先着']}/{b['約定候補数']}・{G.pct(b['確認率'])}",
                             f"{a['約定候補数']}/{b['約定候補数']}", number(qa["追加5pt純損益円"]), number(qb["追加5pt純損益円"]),
                             f"{qa['品質注意場数']}/{qb['品質注意場数']}"])
    text = "## 同足ネック位置条件のあり・なし\n\nなし側の発動を同じ判断足の終値位置で選別する比較。ネックの将来突破を待たず、条件不成立でもpivotは更新する。率の上昇だけで支持件数や費用資格を代替しない。11/4デイは全候補結果へ別掲し、旧二期間の支持・資格へ用いない。\n"
    text += G.table(["足分", "型", "期間", "なし：順/仮約定・率", "ネック：順/仮約定・率", "仮約定数 なし/ネック", "なし：追加5pt純額", "ネック：追加5pt純額", "注意場 なし/ネック"], rows)
    positive = sum(all(row[p]["運用"]["追加5pt純損益円"] > 0 for p in PERIODS[:2]) for row in values.values())
    text += "学習・条件選択の両方で追加片道5pt後の観測純額が正だった候補は" + number(positive) + "/12。ネック追加で仮約定数は減り、条件選択の先着率や費用後額も一貫した改善にはならなかった。この結果は今回の左右2本・隣接二極値・同足位置条件・固定X0と既使用期間の組合せについての結果で、RSIや反転一般の有効性まで否定するものではない。\n\n"
    return text + "反転乖離は15分準備だけ、押し戻り継続は方向一致も要求するため、型の差には上位条件の差も含む。RSIと価格は同じ価格情報に由来し、独立の注文フローではない。隣接極値・左右2本・間隔3〜20本は今回固定した定義で、作者教材の唯一の式やNK225の最適値とはしない。\n\n"


def auxiliary_diagnosis(study: Path, output: Path) -> str:
    """同じ仮約定の対応と単一建玉の参加集合差を表示する。

    引数: study/output (Path) は試行/表示先。
    返り値: str は任意保存された18群の診断。未保存なら空文字列。
    """
    path = study/"補助対応診断.json"
    if not path.exists():
        return ""
    data, rows = G.read_json(path), []
    if data["結果SHA256"] != G.sha(study/"結果.json") or len(data["結果"]) != 18:
        raise ValueError("補助診断の結果SHAまたは18群が不一致")
    for row in data["結果"]:
        item = row["運用比較"]
        if row["補助なし入口数"]-row["ネック位置不成立で除く入口数"] != row["ネック条件入口数"]:
            raise ValueError("ネック位置選別の集合数が不一致")
        difference = item["ネック条件のみ純額円"]-item["なし側のみ純額円"]
        if not math.isclose(item["全運用純額差円"], item["共通実新規純額差円"]+difference, abs_tol=1e-8):
            raise ValueError("参加集合差の会計が不一致")
        rows.append([row["足分"], row["系統"], PERIOD_NAMES[row["期間"]], row["補助なし入口数"], row["ネック条件入口数"], row["ネック位置不成立で除く入口数"],
                     f"{item['共通実新規数']}/{item['なし側のみ実新規数']}/{item['ネック条件のみ実新規数']}",
                     number(item["共通実新規純額差円"]), number(difference), number(item["全運用純額差円"])])
    text = "## 同じ仮約定と参加集合\n\n" + G.link(path, output) + "は" + ("全件一致" if data.get("対応集合全件一致") is True else "不一致または未確認") + "、" + number(data["同じ仮約定の照合項目数"]) + "項目。共通仮約定・先着を重複した独立標本としない。\n\n"
    text += "全運用差＝共通実新規純額差＋ネック側のみ純額−なし側のみ純額。X0が同じでも、入口を絞ると保有中抑止と後続参加が変わる。入口集合の包含と、実運用取引集合の包含は別に確認する。以下は基準費用の円。\n"
    return text + G.table(["足分", "型", "期間", "なし入口", "ネック入口", "位置条件で除外", "共通/なしのみ/ネックのみ実新規", "共通純額差", "参加集合純額差", "全純額差"], rows)


# ----------------------------------------
# 指標の準備・極値構造・追加選別・執行を汎用表の異なる設定として表示する。

def settings(rules: list[dict]) -> list[dict]:
    """使用したセルに時点と閾値と複合評価を対応付ける。

    引数: rules (list[dict]) は固定12評価。
    返り値: list[dict] は汎用表用のS設定。計算しただけの未使用指標は使用へ分類しない。
    """
    groups = []
    for size in (1, 3, 5):
        scale = [f"m{size:02d}"]
        same = [r for r in rules if r["入口"]["時間足分"] == size]
        regular = [r for r in same if r["入口"]["入口系統"] == "反転乖離"]
        hidden = [r for r in same if r["入口"]["入口系統"] == "押し戻り継続"]
        neck = [r for r in same if r["入口"]["補助"] != "なし"]
        groups += [
            (["I04", "I09"], scale, same, "現RSI14有限・ATR14>0", "下位EMA/ADX/BB/数量はgateに使わない。中心RSIと判断RSIを分ける"),
            (["P02"], scale, same, "左右2本・左strict/右inclusive", "価格極値中心iをi+2公開時だけ確定。隣接同側・間隔3〜20、未準備でも更新"),
            (["I04", "P13"], scale, regular, "価格更新・中心RSIは逆向き", "買は第2L<第1LかつRSI2>RSI1、売り対称。15分方向を制約しない"),
            (["I04", "P13", "P04"], scale, hidden, "価格切上げ/切下げ・RSI逆向き", "買は第2L>第1LかつRSI2<RSI1、売り対称。15分方向一致が必要"),
            (["P01"], scale, same, "判断Cが前Cより有利側strict", "判断足j=i+2の終値改善。中心価格での新規を仮定しない"),
            (["P03", "P07"], scale, neck, "両中心を除く間の高安よりCが有利側strict", "同足の現在位置選別。交差条件や翌足以後の突破待ちではない")]
    hidden = [r for r in rules if r["入口"]["入口系統"] == "押し戻り継続"]
    groups += [
        (["I01", "C07"], ["m15"], rules, "当場公開済みEMA20と前値の準備", "上位終了時計と公開時計/原行は判断足以下。反転乖離は方向不問"),
        (["I01", "C07"], ["m15"], hidden, "買C>EMA20>前EMA20・売り逆", "押し戻り継続だけ上位方向一致。単なる準備と区別"),
        (["B01"], ["tick"], rules, "ラージBBO・+1価格時計秒", "micro1枚代理。新規買Ask/売Bid・返済買Bid/売Ask、価格時計は受信時計ではない"),
        (["E01"], ["tick"], rules, "全12入口の逆125/順250先着", "全仮約定分母へ期限/不足を残し未約定を別記。運用の建玉中抑止とは別"),
        (["E02"], ["tick"], rules, "全X0：TP250/SL125・期限", "旧11固定出口。要求+1秒後最初正常BBO、空白/EOF/未解消を記録")]
    return [{"設定ID": f"S{i:02d}", "手法ID": methods, "尺度ID": scales, "短記": short, "説明": detail,
             "結果短記": "・".join(r["評価ID"] for r in applies), "適用評価": [r["評価ID"] for r in applies]}
            for i, (methods, scales, applies, short, detail) in enumerate(groups, 1)]


def audits(study: Path, output: Path) -> tuple[str, list[Path]]:
    """保存された主監査・状態監査・Viewerの明示合否を表示する。

    引数: study/output (Path) は試行/表示先。
    返り値: tuple[str,list[Path]] は検査表と出典。未保存は未完のままとする。
    """
    rows, sources = [], []
    for name, label in (("合成検証.json", "境界合成"), ("独立監査.json", "先着・会計・集計"),
                        ("状態独立確認.json", "全pivot・全発動集合"), ("補助対応診断.json", "補助対応"), ("Viewer照合.json", "Viewer")):
        path = study/name
        if not path.exists():
            rows.append([label, "未完・結果未保存", "未算出", "なし"])
            continue
        data = G.read_json(path)
        sources.append(path)
        verdict, count = data.get("全件一致"), data.get("照合項目数")
        if label == "境界合成":
            verdict, count = data.get("全件成功"), data.get("検証件数", data.get("件数"))
        elif label == "補助対応":
            verdict, count = data.get("対応集合全件一致"), data.get("同じ仮約定の照合項目数")
        elif label == "Viewer" and verdict is None:
            parts = data.get("照合", [])
            verdict, count = (all(v.get("一致") is True for v in parts) if parts else None), len(parts)
        rows.append([label, "合格" if verdict is True else "不一致・失敗" if verdict is False else "資料あり・明示合否未確認", number(count), G.link(path, output)])
    text = "## 検査の状態\n\n保存結果と独立照合は別状態。主監査が状態監査を参照するときは両者の項目数を合算せず別掲する。同じ市場観測や同じ仮約定を独立標本へ重複加算しない。入力品質と将来収益の立証は検査合格と別に扱う。\n"
    text += G.table(["範囲", "状態", "項目数", "正本"], rows)
    state_path = study/"状態独立確認.json"
    if state_path.exists():
        data = G.read_json(state_path)
        text += "状態側は原cacheから全" + number(data["独立pivot数"]) + "pivotと" + number(data["独立入口数"]) + "入口の全集合を再構築し、中心/確認の公開キー・隣接更新・不採用理由も確認した。主監査はこの状態監査を参照するため、両件数を独立標本として合計しない。\n\n"
    return text, sources


# ----------------------------------------
# 正式再生は呼ばず、結果が保存された後だけMarkdownを生成する。

def run(study: Path, output: Path) -> list[Path]:
    """固定保存結果から三文書を生成する。

    引数: study/output (Path) は試行と表示先。
    返り値: list[Path] はREADME/設定と結果/全候補結果。正本不足や固定変化では生成しない。
    """
    for name in ("条件.json", "固定.json", "結果.json", "入力台帳.json"):
        if not (study/name).is_file():
            raise ValueError(name+"が未保存のため数値文書を生成しない")
    config, report = G.read_json(study/"条件.json"), G.read_json(study/"結果.json")
    rules = definitions(config)
    entries, values = BASE.validate(config, report, rules)
    for name, expected in G.read_json(study/"固定.json")["ファイルSHA256"].items():
        if G.sha(ROOT/name) != expected:
            raise ValueError("固定されたcore・条件・入力が変更されている")
    pointer = G.read_json(study/"入力台帳.json")
    manifest_path = (study/pointer["参照"]).resolve()
    if G.sha(manifest_path) != pointer["SHA256"]:
        raise ValueError("入力台帳参照が不一致")
    manifest, catalog = G.read_json(manifest_path), G.read_json(G.CATALOG)
    if (len(catalog["methods"]), len(catalog["scales"])) != (51, 9):
        raise ValueError("共通表51×9が変化")
    output.mkdir(parents=True, exist_ok=True)
    readme, setting_path, all_path = [output/name for name in ("README.md", "設定と結果.md", "全候補結果.md")]
    refs = {r["候補ID"]: r["評価ID"] for r in rules}
    intro = "NK225の1/3/5分×反転乖離/押し戻り継続×追加確認なし/ネック位置確認＝12入口を、全X0固定12運用で比較した。全65場は既使用（学習40・条件選択24・既使用11/4デイ1）。内部キー『後続検査』も未見確認ではない。保存JSONの表示だけを行い、原板・指標・入口・売買を再生しない。\n\n"
    conclusion = f"**入口70目標は{report['入口70目標達成数']}/12、探索用費用資格は{report['費用資格数']}/12。** 全12表示を採用と呼ばない。\n\n"
    timing = "## 極値中心と知れる時点\n\n価格極値の中心iと、極値と知れるi+2の公開時計・原行を区別する。中心足自身の公開キーは保存資料の『中心足公開時計秒/原行』、右2足後のキーは『極値確認時計秒/原行』。要求は後者で、中心の安値/高値へ約定を描き戻さない。RSIは両中心に対応する値を比較し、判断時のRSI準備とは別に保存する。\n\n"
    timing += "左2本はstrict、右2本はinclusiveの価格極値。同値の並びでは先頭側を選ぶ。同側の隣接極値だけを比較し、RSI未準備・中心間隔外・時間外・発動不成立でも必ず更新する。欠枠・index飛越・非公開足で窓と前極値をリセットする。3〜20は中心間隔の足本数で、1/3/5分の尺度と混同しない。\n\n"
    timing += "現判断足のRSI14有限・ATR14有限正と当場15分EMA20/前値の準備を要求する。下位EMA20・ADX・BB・数量は入口gateへ使わない。共通コードが計算していても、この試行での使用を意味しない。反転乖離は上位方向不問、押し戻り継続だけ方向一致。ネックは両中心を除く間の高安に対する現終値のstrictな位置選別で、交差検出や後続突破待ちではない。\n\n"
    psychology = "価格更新とRSI非更新を勢いの変化、価格を維持したRSI調整を押し戻りと読むのは仮説で、利確・手仕舞い・追随注文の主体を測った結果ではない。RSIは終値の加工であり価格と独立のフロー情報ではない。" + G.link(ROOT/"docs/議論/RSIと価格の山谷を時点どおりに比較する.md", readme, "資料と心理仮説") + "の一般説明と、この固定定義の研究結果を区別する。\n\n"
    limits = "ラージBBOでmicro1枚を代理し倍率10円/pt・片道11円を仮定。追加片道5/10ptは同じ完結往復から100/200円控除する感度で、滑りによる発動・再参加の再計算ではない。価格時計は受信時計ではなく1秒待機は通信遅延の実測ではない。正常板空白・EOF・未解消を含む全体を確定利益へ置き換えない。運用確定対象欄の『未算出』は品質上の未確定（正本null）を表し、無取引の平均・率とは理由が異なる。\n\n"
    thresholds = "## 固定した条件\n" + G.table(["項目", "設定"], [[k, G.describe(config[k])] for k in ("極値条件", "価格条件", "共通準備", "出口定義", "入口支持", "間引き必要件数", "費用支持", "運用")])
    thresholds += "新規要求+1価格時計秒以上30秒以内、残り60分以上、既存の停止/期限。返済も要求+1秒以上後の最初正常BBO。出口は旧00011のX0：TP250/SL125・期限だけ。全pivot/入口の判定に保有状態や後の先着ラベルを使わず、実運用の建玉中抑止を別に記録する。\n\n"
    definition_table = "## 固定12評価\n" + G.table(["評価", "候補", "足分", "型", "役割", "追加確認", "出口", "費用資格"],
        [[r["評価ID"], r["候補ID"], r["入口"]["時間足分"], r["入口"]["入口系統"], r["入口"]["役割"], r["入口"]["補助"], "X0固定", "充足" if values[r["候補ID"]]["費用資格"] else "未達"] for r in rules])
    audit_readme, audit_paths = audits(study, readme)
    links = " / ".join(G.link(study/name, readme) for name in ("計画.md", "条件.json", "固定.json", "結果.json"))
    summary = "# 試行00015：RSIの山谷と価格構造\n\n状態：固定12案の集約保存済み。\n\n" + intro + links + " / " + G.link(setting_path, readme) + " / " + G.link(all_path, readme) + "\n\n" + conclusion + timing + psychology + limits + findings(entries, values) + pivot_tables(study) + auxiliary_diagnosis(study, readme) + definition_table + audit_readme
    viewer = "## 入力・閲覧・再現\n\n" + G.link(study/"入力台帳.json", readme) + " / " + G.link(manifest_path, readme, "00008参照台帳") + "\n\n"
    viewer += f"市場root：{manifest['source_root']}。market_pathはこの設定root基準、pnl_pathはpath_base=catalogで一覧親基準。Viewerは全12の追加滑り0ptを表示する。原板を複製せず、全pivot/入口/運用詳細gzipはworkへ、正式には集計・台帳・必要な約定を残す。\n\n"
    for name in ("一覧.resources.json", "固定候補_取引.csv", "固定候補_注文.csv", "全候補_場別.csv", "入口品質.json", "入力品質.json", "作業成果物.json", "Viewer照合.json"):
        if (study/name).exists():
            viewer += G.link(study/name, readme)+"\n\n"
    names = ["入口.py", "検証.py", "合成検証.py", "レポート.py"]
    names += [n for n in ("独立監査.py", "状態独立確認.py", "補助対応診断.py") if (ROOT/"scripts/RSI構造"/n).exists()]
    viewer += "コード：" + " / ".join(G.link(ROOT/"scripts/RSI構造"/n, readme) for n in names) + " / " + G.link(ROOT/"scripts/テクニカル循環/運用.py", readme, "読取利用するX0") + "。\n\n"
    fence = chr(96)*3
    viewer += "保存結果の再表示：\n\n" + fence + "powershell\npython -X utf8 scripts/RSI構造/レポート.py\n" + fence + "\n\n数値再生は検証.pyへ別の保存先/作業先を指定する。正式結果の上書き・固定後変更は拒否する。\n\n"
    common = settings(rules)
    method_ids, scale_ids = {row["id"] for row in catalog["methods"]}, {row["id"] for row in catalog["scales"]}
    if any(set(row["手法ID"])-method_ids or set(row["尺度ID"])-scale_ids for row in common):
        raise ValueError("設定明細に汎用表へ対応しない手法または尺度がある")
    setting = "# 試行00015：設定と結果\n\n" + intro + conclusion + G.link(G.MASTER, setting_path, "コピー元の汎用表") + " / " + G.link(readme, setting_path) + " / " + G.link(all_path, setting_path) + "\n\n"
    setting += "## 手法×時間スケール\n\n51手法×9尺度を保持。Sは準備/極値とRSI関係/同足ネック位置/執行、R01〜R12は複合運用であり指標単独効果ではない。1/3/5分と15分準備・方向だけを使用し、30分間引きは30分足の計算ではない。下位EMA/ADX/BB/数量をgateに使わず、未使用はデータ不存在を意味しない。\n\n" + G.matrix(catalog, setting_path, common)
    setting += "## 設定明細\n" + G.table(["設定", "手法/尺度", "短記", "閾値と役割", "適用評価"], [[s["設定ID"], "/".join(s["手法ID"])+"・"+"/".join(s["尺度ID"]), s["短記"], s["説明"], "・".join(s["適用評価"])] for s in common])
    setting += thresholds + timing + psychology + definition_table + "全数値は" + G.link(all_path, setting_path) + "、正本は" + G.link(study/"結果.json", setting_path) + "。\n\n" + limits
    audit_all, _ = audits(study, all_path)
    all_text = "# 試行00015：全候補結果\n\n" + intro + conclusion + G.link(readme, all_path) + " / " + G.link(setting_path, all_path) + "\n\n" + limits + timing + psychology + thresholds + definition_table + pivot_tables(study) + findings(entries, values) + auxiliary_diagnosis(study, all_path)
    all_text += P.entry_table(entries).replace("8純入口", "12純入口") + P.operation_tables(values, refs, config).replace("8固定運用", "12固定運用") + audit_all
    paths = [Path(__file__), DISPLAY, ROOT/"scripts/収縮反転/レポート.py", ROOT/"scripts/レポート/設定結果レポート.py", G.CATALOG, G.MASTER,
             study/"計画.md", study/"条件.json", study/"固定.json", study/"入力台帳.json", manifest_path, study/"結果.json", *audit_paths]
    paths += [ROOT/"scripts/RSI構造"/n for n in names if n != "レポート.py"]
    paths += [study/"入口品質.json", ROOT/"docs/議論/RSIと価格の山谷を時点どおりに比較する.md", ROOT/"scripts/テクニカル循環/入口.py", ROOT/"scripts/テクニカル循環/運用.py"]
    for path, text in ((readme, summary+viewer), (setting_path, setting), (all_path, all_text)):
        path.write_text(text+G.provenance(paths, path), encoding="utf-8")
    return [readme, setting_path, all_path]


def main() -> None:
    """正式試行と任意表示先を読み取り三文書を生成する。

    引数: なし。--study/--outputを読む。
    返り値: None。数値再生を呼ばず、未保存結果は生成しない。
    """
    parser = argparse.ArgumentParser(description="RSIの極値確認と12固定運用の表示")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    study = args.study.resolve()
    print(json.dumps({"生成": [str(p) for p in run(study, (args.output or study).resolve())]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
