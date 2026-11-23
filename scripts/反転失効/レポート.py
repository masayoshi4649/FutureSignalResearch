"""00016の保存結果から12入口・12X0の三文書と51×9表を作る。"""

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
STUDY = ROOT/"study/00016_反転不成立からの継続"
DISPLAY = ROOT/"scripts/数量反転/レポート.py"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = {"学習": "学習40場", "条件選択": "条件選択24場", "後続検査": "既使用11/4デイ1場"}
FAMILIES = {"単純逆向き": "順行", "価格失効待ち": "順行"}
EXTRAS = ("なし", "15分方向一致")


def display_helper() -> Any:
    """旧帳票の汎用検算と表描画だけを読み込む。

    引数: なし。
    返り値: Any は12件の保存集計検算と表示補助。価格・入口・数量・売買は再生しない。
    """
    spec = importlib.util.spec_from_file_location("反転失効の共通帳票表示", DISPLAY)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


BASE = display_helper()
G, P, number = BASE.G, BASE.P, BASE.number


def definitions(config: dict) -> list[dict]:
    """固定三尺度・二方式・二上位条件を評価IDへ対応付ける。

    引数: config (dict) は条件正本。
    返り値: list[dict] は12入口と全X0のR01〜R12。
    """
    if config["時間足分"] != [1, 3, 5] or config["入口系統"] != list(FAMILIES) or config["補助"] != list(EXTRAS) or config["出口"] != [{"出口ID": "X0"}]:
        raise ValueError("固定三尺度・二方式・二補助・X0と異なる")
    if config["監視条件"] != {"下限本数": 1, "上限本数": 6, "最新一件": True, "同足発動": False} or (config["逆行pt"], config["順行pt"], config["確認遅延上限秒"]) != (125, 250, 30):
        raise ValueError("次1〜6本・最新一件・125/250・遅延30秒と異なる")
    rows = []
    for size in config["時間足分"]:
        for family, role in FAMILIES.items():
            for extra in EXTRAS:
                source = {"入口ID": f"{size}分_{family}_{extra}", "入口系統": family, "時間足分": size,
                          "補助": extra, "名称": family, "役割": role}
                rows.append({"候補ID": source["入口ID"]+"_X0", "入口": source, "出口": {"出口ID": "X0"}, "評価ID": f"R{len(rows)+1:02d}"})
    return rows


# ----------------------------------------
# 元準備と最新一件監視・失効後の実発動を混ぜずに保存品質を集計する。

def monitor_tables(study: Path) -> str:
    """保存入口品質から準備・最新一件監視・抑止を表示する。

    引数: study (Path) は正式試行。
    返り値: str は期間別の監視状態。場末の設定と実建玉の未解消を区別する。
    """
    path = study/"入口品質.json"
    if not path.exists():
        return "## 全準備と監視状態\n\n入口品質は未保存。\n\n"
    totals, reasons, triggers = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
    for row in G.read_json(path):
        key = row["時間足分"], row["期間"]
        totals[key].update({k: v for k, v in row.items() if isinstance(v, (int, float)) and k != "時間足分"})
        reasons[key].update(row.get("発動除外理由_補助別重複あり", {}))
        triggers[key].update(row.get("系統別発動数", {}))
    rows, rejected = [], []
    for size in (1, 3, 5):
        for period in PERIODS:
            item, members = totals[(size, period)], triggers[(size, period)]
            if item["元準備信号数"] != item["準備遅延共通除外数"]+item["利用可能準備信号数"] or item["監視登録"]+item["監視置換"] != item["利用可能準備信号数"]:
                raise ValueError("準備数と遅延除外・登録置換数が不一致")
            rows.append([size, PERIOD_NAMES[period], item["公開足"], item["元準備信号数"], item["準備遅延共通除外数"],
                         item["利用可能準備信号数"], f"{item['監視登録']}/{item['監視置換']}", item["監視判定"], item["失効消費"],
                         item["監視満了"], item["状態リセット"], item["場末未消費終了"],
                         f"{members[f'{size}分_単純逆向き_なし']}/{members[f'{size}分_単純逆向き_15分方向一致']}",
                         f"{members[f'{size}分_価格失効待ち_なし']}/{members[f'{size}分_価格失効待ち_15分方向一致']}"])
            rejected.append([size, PERIOD_NAMES[period], G.describe(dict(reasons[(size, period)]))])
    text = "## 全準備と監視状態\n\n元準備は旧00015の反転乖離・なし。確認遅延30秒超は両方式から共通除外し、監視の登録・置換にも使わない。最新とは、この除外後に登録可能な準備の最新一件を指す。旧監視を先に判定し、現足の新しい準備を最後に登録する。\n"
    text += G.table(["足分", "期間", "公開足", "元準備", "遅延共通除外", "利用可能準備", "登録/置換", "監視判断", "失効消費", "7本目満了", "欠枠等reset", "場末未消費設定", "単純 なし/上位", "失効 なし/上位"], rows)
    text += "失効消費は実際に発動できなかった場合も含む。監視判断は一準備あたり最大6回あり、準備件数や実取引数とは異なる。場末未消費設定は監視の残存で、建玉未解消ではない。状態リセットは監視なしの場合も記録し、欠枠・番号飛越・非公開を理由として残す。\n\n"
    text += "### 実発動の抑止\n\n下表の理由は二つの補助それぞれで複数付くため、足・準備・消費の一意件数へ加算しない。上位不一致は実入口sideと比較する。共通準備・時間・遅延が不成立でも失効は消費される。実建玉による抑止はこの後の運用集計へ分ける。\n"
    return text + G.table(["足分", "期間", "発動除外理由・補助別重複あり"], rejected)


def findings(entries: dict, values: dict) -> str:
    """方式別に15分方向条件の有無を旧二期間で表示する。

    引数: entries/values (dict) は保存入口/運用のID別集計。
    返り値: str は全六組の記述比較。方式間の異なる入口時計を同一取引差としない。
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
    text = "## 方式別の15分方向条件\n\n方向条件は現在入る側への追加選別。補助なしにも当場の上位準備は必要。単純逆向きと価格失効待ちは要求時点が異なり、同じ価格でsideだけを変えた比較や同一取引の出口差ではない。11/4デイは全候補結果へ別掲し、旧二期間の支持・資格へ使わない。\n"
    text += G.table(["足分", "方式", "期間", "なし：順/仮約定・率", "上位一致：順/仮約定・率", "仮約定数 なし/上位", "なし：追加5pt純額", "上位：追加5pt純額", "注意場 なし/上位"], rows)
    positive = sum(all(row[p]["運用"]["追加5pt純損益円"] > 0 for p in PERIODS[:2]) for row in values.values())
    text += "両期間とも追加片道5pt後の観測純額が正の候補は" + number(positive) + "/12。入口率・支持件数・費用・品質を合わせて判断し、既使用期間の良い一部分だけを採用根拠にしない。元の反転準備の失敗率を、新しい逆向き入口の成功率へ読み替えない。\n\n"
    sample = values["3分_価格失効待ち_15分方向一致_X0"]
    a, b = [sample[p] for p in PERIODS[:2]]
    text += "3分の失効待ち＋15分方向一致は追加片道5pt後に学習" + number(a["運用"]["追加5pt純損益円"]) + "円、条件選択" + number(b["運用"]["追加5pt純損益円"]) + "円。追加10ptでは条件選択" + number(b["運用"]["追加10pt純損益円"]) + "円で、入口は学習" + str(a["入口"]["順行先着"]) + "/" + str(a["入口"]["約定候補数"]) + "、条件選択" + str(b["入口"]["順行先着"]) + "/" + str(b["入口"]["約定候補数"]) + "に限られる。入口支持・70目標・費用資格を満たす結果ではない。これは固定された今回の準備/監視/費用/期間での結果で、反転失効一般の可否へ広げない。\n\n"
    return text


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
        if row["補助なし入口数"]-row["方向不一致で除く入口数"] != row["方向一致入口数"]:
            raise ValueError("上位方向選別の集合数が不一致")
        difference = item["方向一致のみ純額円"]-item["なし側のみ純額円"]
        if not math.isclose(item["全運用純額差円"], item["共通実新規純額差円"]+difference, abs_tol=1e-8):
            raise ValueError("参加集合差の会計が不一致")
        rows.append([row["足分"], row["系統"], PERIOD_NAMES[row["期間"]], row["補助なし入口数"], row["方向一致入口数"], row["方向不一致で除く入口数"],
                     f"{item['共通実新規数']}/{item['なし側のみ実新規数']}/{item['方向一致のみ実新規数']}",
                     number(item["共通実新規純額差円"]), number(difference), number(item["全運用純額差円"])])
    text = "## 同じ仮約定と参加集合\n\n" + G.link(path, output) + "は" + ("全件一致" if data.get("対応集合全件一致") is True else "不一致または未確認") + "、" + number(data["同じ仮約定の照合項目数"]) + "項目。共通仮約定・先着を重複した独立標本としない。\n\n"
    text += "全運用差＝共通実新規純額差＋方向一致側のみ純額−なし側のみ純額。X0が同じでも、入口を絞ると保有中抑止と後続参加が変わる。入口集合の包含と、実運用取引集合の包含は別に確認する。以下は基準費用の円。\n"
    return text + G.table(["足分", "型", "期間", "なし入口", "方向一致入口", "方向条件で除外", "共通/なしのみ/方向一致のみ実新規", "共通純額差", "参加集合純額差", "全純額差"], rows)


# ----------------------------------------
# 指標の準備・極値構造・追加選別・執行を汎用表の異なる設定として表示する。

def settings(rules: list[dict]) -> list[dict]:
    """元準備・監視発動・上位補助・執行を汎用セルへ対応付ける。

    引数: rules (list[dict]) は固定12評価。
    返り値: list[dict] はS設定。下位EMA/ADX/BB/数量を使用へ分類しない。
    """
    groups = []
    for size in (1, 3, 5):
        scale = [f"m{size:02d}"]
        same = [r for r in rules if r["入口"]["時間足分"] == size]
        simple = [r for r in same if r["入口"]["入口系統"] == "単純逆向き"]
        wait = [r for r in same if r["入口"]["入口系統"] == "価格失効待ち"]
        groups += [
            (["I04", "P02", "P13"], scale, same, "固定15反転乖離なしを準備へ", "旧15条件read。中心とi+2確認キー・隣接3〜20・中心RSI/改善/上位準備を同値利用、遅延>30は共通除外"),
            (["I04", "I09"], scale, same, "実発動RSI14有限・ATR14>0", "準備ATRと実発動ATRを分離。下位EMA/ADX/BB/数量の追加gateなし"),
            (["P13", "P04"], scale, simple, "準備と同足で元side逆向き", "未来の失効を待たない対照。元の成功率の補数を逆向き成功率としない"),
            (["P02", "P07", "P04"], scale, wait, "次1〜6本で第2極値をCがstrict更新", "最新一件global。旧監視判定→新登録、7本満了、抑止時も消費、等号では失効しない")]
    direction = [r for r in rules if r["入口"]["補助"] != "なし"]
    groups += [
        (["I01", "C07"], ["m15"], rules, "当場公開済みEMA20と前値の準備", "準備時も実発動時も利用可能な上位足だけ。終了時計/公開キーは現足以下"),
        (["I01", "C07"], ["m15"], direction, "実入口sideと15分方向一致", "買C>EMA20>前EMA20・売り逆。方向0不一致、元準備sideと取り違えない"),
        (["B01"], ["tick"], rules, "ラージBBO・+1価格時計秒", "micro1枚代理。新規買Ask/売Bid・返済買Bid/売Ask。価格時計は受信時計ではない"),
        (["E01"], ["tick"], rules, "12入口の逆125/順250先着", "全仮約定分母に期限/不足を残し未約定を別記。待機した異なる起点から再判定"),
        (["E02"], ["tick"], rules, "全X0：TP250/SL125・期限", "旧11固定出口。要求+1秒後最初正常BBO、正常板空白/EOF/未解消を記録")]
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
                        ("状態独立確認.json", "全準備・監視・発動集合"), ("補助対応診断.json", "補助対応"), ("Viewer照合.json", "Viewer")):
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
        counts = [(label, data[key]) for key, label in (("独立準備数", "準備"), ("独立監視行数", "監視記録"), ("独立入口数", "入口")) if key in data]
        text += "状態側は原cacheから準備・監視・全発動集合を再構成し、旧15準備同値・現在属性・状態原順を確認した。" + ("保存集計："+"、".join(number(value)+label for label, value in counts)+"。" if counts else "") + "主監査がこの状態監査を参照するため、両件数を独立標本として合計しない。\n\n"
        if "旧15固定準備数" in data:
            text += "旧15固定" + number(data["旧15固定準備数"]) + "準備との元信号全文同値（生成後の期間/JST表記と先着ラベル列を除く）と、原価格からの独立再構成を別に確認した。確認遅延30秒超の共通除外は" + number(data["準備30秒超除外数"]) + "件。\n\n"

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
    intro = "NK225の1/3/5分×単純逆向き/価格失効待ち×補助なし/確定15分方向一致＝12入口を、全X0固定12運用で比較した。全65場は既使用（学習40・条件選択24・既使用11/4デイ1）。内部キー『後続検査』も未見確認ではない。保存JSONの表示だけを行い、原板・指標・入口・売買を再生しない。\n\n"
    conclusion = f"**入口70目標は{report['入口70目標達成数']}/12、探索用費用資格は{report['費用資格数']}/12。** 全12表示を採用と呼ばない。\n\n"
    timing = "## 準備と実発動を分ける\n\n準備は固定00015条件で再生成した反転乖離・なし。元の中心/確認・隣接・RSI/ATR・改善・上位準備・時間条件を変えず、確認遅延30秒超だけを両方式共通で除外する。00016条件を旧generateへ渡さない。元の中心足公開とi+2極値確認の区別も準備参照へ保存する。\n\n"
    timing += "単純逆向きは準備を知った同足で逆sideへ要求。価格失効待ちは登録した最新一件だけを次1〜6連続公開足で監視し、元買い準備ならC<第2Lで売り、元売りならC>第2Hで買う。等号では失効せず、7本目で満了。各足で旧監視を判定してから新準備を登録/置換し、新準備は同足で失効判定しない。欠枠・番号飛越・非公開・場間でresetする。\n\n"
    timing += "失効したらRSI/ATR・上位準備・時間・遅延・追加方向が不成立でも消費する。実際の建玉状態では監視を変えない。実発動の時計/原行/ATR/RSI/上位キーは現在足、準備の時計/原行/ATRと第2極値は不変copyの別属性。場末未消費の監視設定は建玉未解消と別である。下位EMA/ADX/BB/数量は追加gateへ使わない。上位方向は元準備sideでなく実入口sideと比較する。\n\n"
    psychology = "## 逆向きの率は補数にならない\n\n250pt順行/125pt逆行は非対称なので、元が逆行先着でも、逆向きが順行先着とは限らない。BBOと新規要求時計も異なる。旧15の運用純額の符号反転や、元成功率の1からの差で今回の率を作らず、全入口を各実起点から追跡する。\n\n"
    psychology += "第2極値更新を反転狙いの解消や元方向の追随と読むのは仮説。誰の注文かを測らず、追随が遅れて往復する反例もある。" + G.link(ROOT/"docs/議論/反転の失敗を継続の入口へ使う.md", readme, "一次資料と心理仮説") + "の一般説明と今回固定した次1〜6本の研究結果を区別する。\n\n"
    limits = "ラージBBOでmicro1枚を代理し倍率10円/pt・片道11円を仮定。追加片道5/10ptは同じ完結往復から100/200円控除する感度で、滑りによる発動・再参加の再計算ではない。価格時計は受信時計ではなく1秒待機は通信遅延の実測ではない。正常板空白・EOF・未解消を含む全体を確定利益へ置き換えない。運用確定対象欄の『未算出』は品質上の未確定（正本null）を表し、無取引の平均・率とは理由が異なる。\n\n"
    thresholds = "## 固定した条件\n" + G.table(["項目", "設定"], [[k, G.describe(config[k])] for k in ("準備条件参照", "監視条件", "価格条件", "共通準備", "出口定義", "入口支持", "間引き必要件数", "費用支持", "運用")])
    thresholds += "新規要求+1価格時計秒以上30秒以内、残り60分以上、既存の停止/期限。返済も要求+1秒以上後の最初正常BBO。出口は旧00011のX0：TP250/SL125・期限だけ。準備と監視には実保有や未来ラベルを使わず、運用の建玉中抑止を別記する。異なる入口時点を同じ取引の出口差とはしない。\n\n"
    definition_table = "## 固定12評価\n" + G.table(["評価", "候補", "足分", "型", "役割", "追加確認", "出口", "費用資格"],
        [[r["評価ID"], r["候補ID"], r["入口"]["時間足分"], r["入口"]["入口系統"], r["入口"]["役割"], r["入口"]["補助"], "X0固定", "充足" if values[r["候補ID"]]["費用資格"] else "未達"] for r in rules])
    audit_readme, audit_paths = audits(study, readme)
    links = " / ".join(G.link(study/name, readme) for name in ("計画.md", "条件.json", "固定.json", "結果.json"))
    summary = "# 試行00016：反転不成立からの継続\n\n状態：固定12案の集約保存済み。\n\n" + intro + links + " / " + G.link(setting_path, readme) + " / " + G.link(all_path, readme) + "\n\n" + conclusion + timing + psychology + limits + findings(entries, values) + monitor_tables(study) + auxiliary_diagnosis(study, readme) + definition_table + audit_readme
    viewer = "## 入力・閲覧・再現\n\n" + G.link(study/"入力台帳.json", readme) + " / " + G.link(manifest_path, readme, "00008参照台帳") + "\n\n"
    viewer += f"市場root：{manifest['source_root']}。market_pathはこの設定root基準、pnl_pathはpath_base=catalogで一覧親基準。Viewerは全12の追加滑り0ptを表示する。原板を複製せず、全準備/全監視/入口/運用詳細gzipはworkへ、正式には集計・台帳・必要な約定を残す。\n\n"
    for name in ("一覧.resources.json", "固定候補_取引.csv", "固定候補_注文.csv", "全候補_場別.csv", "入口品質.json", "入力品質.json", "作業成果物.json", "Viewer照合.json"):
        if (study/name).exists():
            viewer += G.link(study/name, readme)+"\n\n"
    names = ["入口.py", "検証.py", "合成検証.py", "レポート.py"]
    names += [n for n in ("独立監査.py", "状態独立確認.py", "補助対応診断.py") if (ROOT/"scripts/反転失効"/n).exists()]
    viewer += "コード：" + " / ".join(G.link(ROOT/"scripts/反転失効"/n, readme) for n in names) + " / " + G.link(ROOT/"scripts/テクニカル循環/運用.py", readme, "読取利用するX0") + "。\n\n"
    fence = chr(96)*3
    viewer += "保存結果の再表示：\n\n" + fence + "powershell\npython -X utf8 scripts/反転失効/レポート.py\n" + fence + "\n\n数値再生は検証.pyへ別の保存先/作業先を指定する。正式結果の上書き・固定後変更は拒否する。\n\n"
    common = settings(rules)
    method_ids, scale_ids = {row["id"] for row in catalog["methods"]}, {row["id"] for row in catalog["scales"]}
    if any(set(row["手法ID"])-method_ids or set(row["尺度ID"])-scale_ids for row in common):
        raise ValueError("設定明細に汎用表へ対応しない手法または尺度がある")
    setting = "# 試行00016：設定と結果\n\n" + intro + conclusion + G.link(G.MASTER, setting_path, "コピー元の汎用表") + " / " + G.link(readme, setting_path) + " / " + G.link(all_path, setting_path) + "\n\n"
    setting += "## 手法×時間スケール\n\n51手法×9尺度を保持。Sは固定15準備/最新監視と失効/実入口側の上位補助/執行、R01〜R12は複合運用であり指標単独効果ではない。1/3/5分と15分準備・方向だけを使用し、30分間引きは30分足の計算ではない。下位EMA/ADX/BB/数量をgateに使わず、未使用はデータ不存在を意味しない。\n\n" + G.matrix(catalog, setting_path, common)
    setting += "## 設定明細\n" + G.table(["設定", "手法/尺度", "短記", "閾値と役割", "適用評価"], [[s["設定ID"], "/".join(s["手法ID"])+"・"+"/".join(s["尺度ID"]), s["短記"], s["説明"], "・".join(s["適用評価"])] for s in common])
    setting += thresholds + timing + psychology + definition_table + "全数値は" + G.link(all_path, setting_path) + "、正本は" + G.link(study/"結果.json", setting_path) + "。\n\n" + limits
    audit_all, _ = audits(study, all_path)
    all_text = "# 試行00016：全候補結果\n\n" + intro + conclusion + G.link(readme, all_path) + " / " + G.link(setting_path, all_path) + "\n\n" + limits + timing + psychology + thresholds + definition_table + monitor_tables(study) + findings(entries, values) + auxiliary_diagnosis(study, all_path)
    all_text += P.entry_table(entries).replace("8純入口", "12純入口") + P.operation_tables(values, refs, config).replace("8固定運用", "12固定運用") + audit_all
    paths = [Path(__file__), DISPLAY, ROOT/"scripts/収縮反転/レポート.py", ROOT/"scripts/レポート/設定結果レポート.py", G.CATALOG, G.MASTER,
             study/"計画.md", study/"条件.json", study/"固定.json", study/"入力台帳.json", manifest_path, study/"結果.json", *audit_paths]
    paths += [ROOT/"scripts/反転失効"/n for n in names if n != "レポート.py"]
    paths += [study/"入口品質.json", ROOT/"docs/議論/反転の失敗を継続の入口へ使う.md", ROOT/"scripts/RSI構造/入口.py", ROOT/"study/00015_RSIの山谷と価格構造/条件.json", ROOT/"scripts/テクニカル循環/運用.py"]
    for path, text in ((readme, summary+viewer), (setting_path, setting), (all_path, all_text)):
        path.write_text(text+G.provenance(paths, path), encoding="utf-8")
    return [readme, setting_path, all_path]


def main() -> None:
    """正式試行と任意表示先を読み取り三文書を生成する。

    引数: なし。--study/--outputを読む。
    返り値: None。数値再生を呼ばず、未保存結果は生成しない。
    """
    parser = argparse.ArgumentParser(description="反転準備と価格失効後の12固定運用の表示")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    study = args.study.resolve()
    print(json.dumps({"生成": [str(p) for p in run(study, (args.output or study).resolve())]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
