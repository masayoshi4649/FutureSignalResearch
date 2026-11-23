"""00020の保存結果を複合切替・共通助走・必須利益追尾に分けて表示する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00020_テクニカル局面による順行反転の切替"
DISPLAY = ROOT/"scripts/VWAP復帰/レポート.py"
POLICIES = ("B1", "B2", "S0", "S1", "S2")
EXITS = ("X0", "X1", "X2")
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = {"学習": "学習40場", "条件選択": "条件選択24場", "後続検査": "既使用11/4デイ1場"}


def display_helper() -> Any:
    """固定19の表示・汎用表・件数検査だけを読み込む。

    引数: なし。
    返り値: Any は表示module。数値結果や価格を読み取って再生しない。
    """
    spec = importlib.util.spec_from_file_location("複合局面帳票の固定19表示", DISPLAY)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


H = display_helper()
P, G, number = H.P, H.G, H.number


def definitions(config: dict) -> list[dict]:
    """三尺度五戦略三出口を15入口と45複合評価へ対応付ける。

    引数: config (dict) は固定条件。
    返り値: list[dict] はR01〜R45。対照と複合本命を区別する。
    """
    if config["時間足分"] != [1, 3, 5] or config["戦略"] != list(POLICIES) or config["出口"] != [{"出口ID": x} for x in EXITS]:
        raise ValueError("固定15入口/45運用と異なる")
    if config["必須追尾"]["起動幅pt"] != 5 or (config["逆行pt"], config["順行pt"]) != (125, 250):
        raise ValueError("全出口A5追尾/125-250先着と異なる")
    rows = []
    for size in (1, 3, 5):
        for policy in POLICIES:
            source = {"入口ID": f"{size}分_{policy}", "戦略": policy, "時間足分": size,
                      "名称": policy, "役割": "混合", "複合本命": policy in ("S1", "S2")}
            for exit_id in EXITS:
                rows.append({"候補ID": source["入口ID"]+"_"+exit_id, "入口": source,
                             "出口": {"出口ID": exit_id}, "評価ID": f"R{len(rows)+1:02d}"})
    return rows


def validate(config: dict, report: dict, rules: list[dict]) -> tuple[dict, dict]:
    """保存結果の件数・費用・支持・本命資格と事前表示を検算する。

    引数: config/report (dict) は条件/結果、rules (list[dict]) は固定定義。
    返り値: tuple[dict,dict] は入口/運用のID別正本。市場価格は再計算しない。
    """
    if report["全65場既使用"] is not True or report["入口125250評価の変更"] is not False:
        raise ValueError("既使用性または先着条件が不一致")
    entries, values = {r["入口ID"]: r for r in report["入口評価"]}, {r["候補ID"]: r for r in report["結果"]}
    if len(entries) != 15 or len(report["入口評価"]) != 15 or len(values) != 45 or len(report["結果"]) != 45:
        raise ValueError("全15入口/45運用と異なる")
    if set(entries) != {r["入口"]["入口ID"] for r in rules} or set(values) != {r["候補ID"] for r in rules}:
        raise ValueError("入口/運用ID集合が不一致")
    for rule in rules:
        entry, row = entries[rule["入口"]["入口ID"]], values[rule["候補ID"]]
        if any(entry[k] != v for k, v in rule["入口"].items()) or row["入口"] != rule["入口"] or row["出口"] != rule["出口"]:
            raise ValueError("保存戦略/役割/本命の定義が不一致")
        for period, sessions in zip(PERIODS, (40, 24, 1)):
            P.validate_entry(entry[period])
            if row[period]["入口"] != entry[period]:
                raise ValueError("出口によって入口先着が変化")
            item, n = row[period]["運用"], row[period]["運用"]["完結取引数"]
            if item["入力場数"] != sessions or item["活動場数"]+item["無取引場数"] != sessions or item["買い取引数"]+item["売り取引数"] != n or sum(item["役割別完結数"].values()) != n:
                raise ValueError("場/方向/固定役割別の数が不一致")
            if not 0 <= item["起動後純赤字取引数"] <= item["追尾起動取引数"] <= n:
                raise ValueError("追尾起動と赤字件数が不一致")
            for slip in (0, 5, 10):
                net, average = item[f"追加{slip}pt純損益円"], item[f"追加{slip}pt平均円"]
                if not math.isclose(net, item["追加0pt純損益円"]-20*slip*n, abs_tol=1e-8):
                    raise ValueError("同じ完結往復への費用感度が不一致")
                if (average is None) != (n == 0) or n and not math.isclose(average, net/n, abs_tol=1e-8):
                    raise ValueError("平均額が不一致")
                if item["品質注意場数"] and item[f"追加{slip}pt確定対象円"] is not None:
                    raise ValueError("品質注意を含む全体が確定額になっている")
        support = all(all(entry[p][k] >= limit for k, limit in limits.items()) for p, limits in config["入口支持"].items())
        goal = support and all(entry[p]["確認率"] >= config["目標確認率"] and entry[p]["30分間引き_約定候補数"] >= config["間引き必要件数"][p] and entry[p]["30分間引き_確認率"] >= config["目標確認率"] for p in PERIODS[:2])
        qualified = rule["入口"]["複合本命"] and all(all(row[p]["運用"][k] >= limit for k, limit in limits.items()) and row[p]["運用"]["品質注意場数"] == 0 and row[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        if (entry["入口支持"], entry["70目標"], row["費用資格"]) != (support, bool(goal), bool(qualified)):
            raise ValueError("支持/70/本命費用資格が不一致")
    displayed = [r["候補ID"] for r in rules if r["入口"]["時間足分"] == 3 and r["出口"]["出口ID"] in ("X0", "X2")]
    if report["表示固定ID"] != displayed or report["入口70目標達成数"] != sum(e["70目標"] for e in entries.values()) or report["費用資格数"] != sum(r["費用資格"] for r in values.values()):
        raise ValueError("事前3分10表示/全体資格数が不一致")
    return entries, values


# ----------------------------------------
# 本命を対照と共通助走で比較し、先着と運用と追尾を別の分母で表示する。

def switching_table(entries: dict, values: dict) -> str:
    """事前表示尺度3分の五戦略を同じ二出口で並べる。

    引数: entries/values (dict) は正本入口/運用。
    返り値: str は20行の旧二期間比較。本命の選び直しは行わない。
    """
    rows = []
    for policy in POLICIES:
        source = f"3分_{policy}"
        for period in PERIODS[:2]:
            entry = entries[source][period]
            for exit_id in ("X0", "X2"):
                item = values[source+"_"+exit_id][period]["運用"]
                rows.append([policy, "本命" if policy in ("S1", "S2") else "対照", exit_id, PERIOD_NAMES[period],
                    f"{entry['順行先着']}/{entry['約定候補数']}・{G.pct(entry['確認率'])}",
                    f"{entry['30分間引き_順行先着']}/{entry['30分間引き_約定候補数']}・{G.pct(entry['30分間引き_確認率'])}",
                    item["完結取引数"], number(item["追加5pt純損益円"]), f"{item['活動場数']}/{item['入力場数']}",
                    item["品質注意場数"], f"{item['起動後純赤字取引数']}/{item['追尾起動取引数']}"])
    text = "## 事前3分表示での切替比較\n\n同じMと同じ必須追尾のB1/B2/S0対照に対し、S1/S2だけ複合数値条件で選択する。採用/見送りは当時の情報で決め、先着ラベルは事後評価へだけ使う。先着分母は各入口の仮約定、追尾後赤字分母は実際に起動して完結した建玉で別の集合。X1を含む全45の数値は結果.json/全候補_場別.csvへ保存する。\n"+G.table(["戦略", "区分", "出口", "期間", "250先着/仮約定・率", "30分間引き順/仮約定・率", "完結", "追加5pt純額円", "活動/入力場", "注意場", "起動後赤字/起動"], rows)
    main = [r for r in values.values() if r["入口"]["複合本命"]]
    positive = [r["候補ID"] for r in main if all(r[p]["運用"]["追加5pt純損益円"] > 0 for p in PERIODS[:2])]
    ranges = [f"{PERIOD_NAMES[p]}{min(r[p]['運用']['完結取引数'] for r in main)}〜{max(r[p]['運用']['完結取引数'] for r in main)}完結/候補" for p in PERIODS[:2]]
    text += "複合本命18運用の実参加は"+"、".join(ranges)+"。両旧期間で追加5pt後純額が正の本命は"+("、".join(positive) if positive else "なし")+"。0取引や少数取引の0円を利益改善へ読み替えず、支持不足と切替で除いた機会を併せて読む。\n\n"
    return text


def diagnosis(study: Path, output: Path) -> str:
    """局面手法・段階・同実新規の正式診断へ要約リンクを作る。

    引数: study/output (Path) は試行/文書出力先。
    返り値: str は任意診断の明示状態。未保存なら未完のまま表示する。
    """
    path = study/"対応診断.json"
    if not path.exists():
        return "## 局面・見送り・参加集合の診断\n\n未完・正式対応診断は未保存。見送りの将来先着を消さず、M/局面/EMA/RSI/急変/競合、避けた逆行と逃した順行、S0との同実新規/参加集合差を保存後に反映する。\n\n"
    data = G.read_json(path)
    if "結果SHA256" in data and data["結果SHA256"] != G.sha(study/"結果.json"):
        raise ValueError("対応診断の結果SHA不一致")
    verdict = data.get("全件一致", data.get("対応集合全件一致"))
    text = "## 局面・見送り・参加集合の診断\n\n"+G.link(path, output)+"："+("全件一致" if verdict is True else "不一致または明示合否未確認")+f"、照合{number(data['照合項目数'])}項目。全Q{number(data['全Q候補数'])}発動・選択後{number(data['純入口数'])}入口集合を保存した。選択入口は戦略間で同じQが重複し独立な新標本ではない。全15分局面{number(data['全15分局面数'])}足・下位context{number(data['全複合context数'])}足、S1/S2の切替は{data['局面切替回数']['S1']}/{data['局面切替回数']['S2']}回。初回分類/resetは切替回数と別。\n\n"
    text += "局面×Q手法×side×期間の採否五ラベルと全段階は正本へ残し、以下は事前3分の旧二期間だけを要約する。見送りの先着は仮参加の事後評価で、実現損益や因果的な損失回避額ではない。将来ラベルを分類へ戻さない。\n"
    buckets = defaultdict(lambda: {"全Q": Counter(), "採用": Counter(), "見送り": Counter()})
    labels = ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定")
    for row in data["局面機会表"]:
        if row["足分"] == 3 and row["期間"] in PERIODS[:2]:
            bucket = buckets[(row["戦略"], row["期間"])]
            for name in bucket:
                bucket[name].update({k: row[name][k] for k in ("候補数", "約定候補数", *labels)})
    rows = []
    for (policy, period), bucket in buckets.items():
        rows.append([policy, PERIOD_NAMES[period], bucket["全Q"]["候補数"],
            "/".join(str(bucket["採用"][k]) for k in labels),
            bucket["見送り"]["順行先着"], bucket["見送り"]["逆行先着"],
            "/".join(str(bucket["見送り"][k]) for k in ("期限未達", "観測不足", "未約定"))])
    text += G.table(["戦略", "期間", "全Q候補", "採用：順/逆/期限/不足/未約定", "逃した250先着", "見送った125先着", "見送り期限/不足/未約定"], rows)
    stage_rows = []
    names = ["全Q", "共通M", "局面と方向", "EMA一致または収束", "RSI持続または戻り", "急変警戒なし", "競合除外後"]
    for row in data["段階別"]:
        if row["足分"] != 3 or row["期間"] not in PERIODS[:2]:
            continue
        stages = {s["段階"]: s for s in row["段階"]}
        stage_rows.append([row["戦略"], row["系統"], PERIOD_NAMES[row["期間"]],
            *[f"{stages[n]['候補数']}件・{stages[n]['順行先着']}/{stages[n]['約定候補数']}" for n in names]])
    text += "### 段階のどこで減ったか\n\n各欄は候補数・250先着/仮約定。順序を固定した段階診断であり、各条件の独立した因果効果ではない。Q2は現RSI側<=60と急変現>=70が両立しないため、反転の急変除外を独立の追加効果として数えない。\n"
    text += G.table(["戦略", "Q", "期間", *names], stage_rows)
    text += "3分S1の条件選択Q1は、共通Mで16/44先着→局面/方向で2/3→EMA条件で0/1となった。局面だけの少数高率をそのまま採用できず、その後の条件追加も勝ちを残す保証にならなかった。Q2も局面11/55→収束4/27→RSI戻り0/1で、改善を積み上げる設計どおりに成績が単調上昇したわけではない。これは固定した順序の保存標本の記述で、EMA/RSI一般の有効性を否定する結果へ広げない。\n\n"
    matched = []
    for row in data["運用対応"]:
        if row["足分"] != 3 or row["比較"] != "複合切替" or row["期間"] not in PERIODS[:2] or row["左"].split("_")[-1] not in ("X0", "X2"):
            continue
        part = row["運用比較"]
        participation = part["右側のみ純額円"]-part["左側のみ純額円"]
        if not math.isclose(part["全運用純額差円"], part["共通実新規純額差円"]+participation, abs_tol=1e-8):
            raise ValueError("共通実新規と参加集合の会計分解が不一致")
        matched.append([row["左"], row["右"], PERIOD_NAMES[row["期間"]],
            f"{part['共通実新規数']}/{part['左側のみ実新規数']}/{part['右側のみ実新規数']}",
            number(part["共通実新規純額差円"]), number(participation), number(part["全運用純額差円"])])
    text += "### S0との差は回収改善か参加消失か\n\n基準費用の右−左純額。全差=共通新規の出口差＋右側だけ純額−左側だけ純額。見送って活動をなくした差を、同じ新規の利益回収が改善した額とはしない。\n"
    text += G.table(["左対照", "右本命", "期間", "共通/左のみ/右のみ新規", "共通出口差円", "参加集合差円", "全純額差円"], matched)
    text += "この事前3分比較の共通新規は各2件、共通出口差は全て0円で、見かけの総額改善は参加集合の消失による。損失機会を見送る一方で250先着も逃し、本命自身の費用後黒字・支持付き70%には至らなかった。\n\n"
    protection = [r for r in data["利益保護"] if (r["候補ID"] == "3分_S0_X0" or r["候補ID"].startswith(("3分_S1_", "3分_S2_")) and r["候補ID"].endswith(("_X0", "_X2"))) and r["期間"] in PERIODS[:2]]
    text += "### 保護を設定した後の実約定\n\n起動後純赤字は費用込み、同値未満/最終設定未満は返済価格側で別に記録する。設定と実返済の不足は待機/gapだけでなく先行通常出口等も含むため、純粋な滑り量とはしない。\n"
    text += G.table(["候補", "期間", "完結", "起動", "起動後純赤字", "起動後同値未満約定", "最終設定未満約定", "設定からの不足pt計"],
        [[r["候補ID"], PERIOD_NAMES[r["期間"]], r["完結数"], r["追尾起動数"], r["起動後純赤字数"], r["起動後同値未満約定数"], r["最終設定未満約定数"], number(r["最終設定からの不足pt計"])] for r in protection])
    text += "3分S1/S2のX0/X2・条件選択24場では、各1件の追尾起動で設定未満約定0でも純赤字が残る。保護価格を守ることと費用後黒字は別の条件として評価する。これは全45や対照S0にも設定不足がないという意味ではない。\n\n"
    for item in protection:
        if item["候補ID"] == "3分_S0_X0":
            text += f"3分S0_X0の{PERIOD_NAMES[item['期間']]}では{item['追尾起動数']}起動中、純赤字{item['起動後純赤字数']}件・同値未満約定{item['起動後同値未満約定数']}件・最終設定未満{item['最終設定未満約定数']}件。設定同値が実現同値を保証しない反例を残す。\n\n"
    text += "全45の保護不足とMFE20/50/100後赤字は対応診断.json/結果.jsonを参照する。\n\n"
    return text


# ----------------------------------------
# 使った尺度と条件を記し、共通準備と本命だけの追加条件を区別する。

def settings(rules: list[dict]) -> list[dict]:
    """51×9表へ全45評価の使用指標・閾値・出口を対応付ける。

    引数: rules (list[dict]) は全45固定評価。
    返り値: list[dict] はS設定。指標単独の効果とはしない。
    """
    groups = []
    for size in (1, 3, 5):
        scale = [f"m{size:02d}"]
        same = [r for r in rules if r["入口"]["時間足分"] == size]
        main = [r for r in same if r["入口"]["複合本命"]]
        groups += [
            (["I12"], scale, same, "固定19の方向追加なしQ1/Q2・native N4", "再獲得順行/1ATR乖離内復帰反転。固定18 as-of/epoch/同原行・四点を維持"),
            (["I01", "I09"], scale, same, "共通M：EMA10/20/前EMA20有限・ATR正", "入口/公開15/60分に同じ準備。対照側も同Mを待ち、助走差を選別効果としない"),
            (["I04"], scale, same, "共通M：同場連続公開RSI14五本", "欠枠/非公開/index飛越/RSI欠測clear。五本目以前の遅延gateは新規追加しない"),
            (["I01", "I09", "I04"], scale, main, "順行：三s側>=.02・CがEMA20有利側・RSI側三本>=50", "s=(EMA20−前EMA20)/その尺度ATR。買RSI/売100−RSIで鏡像。EMA/RSIは独立票でない"),
            (["I01", "I09", "I04"], scale, main, "反転：二尺度収束・前RSI側<=40→現30〜60改善", "収束=EMA10/20間隔/ATR<=.25かつabs(s)<=.10。価格Q2も必要、収束単独で反転しない"),
            (["I04"], scale, main, "急変：現>=70/前差>=12/過去4の>=65が<=1", "三条件全成立なら複合候補を抑止。持続高RSIだけは除外せず、将来反落の確認とは呼ばない"),
        ]
    main = [r for r in rules if r["入口"]["複合本命"]]
    groups += [
        (["I01", "I09", "C07"], ["m15", "m60"], rules, "公開key/end以下の最新上位・EMA10/20/ATR", "未確定上位を使わず、現在未準備を古正常へfallbackしない。60分足を15分足や本数と混同しない"),
        (["I08", "I01", "C04"], ["m15"], rules, "共通15M：C/EMA20/前値/ADX14/±DI14有限", "下位で何度参照しても15分局面の更新は一回、場/欠枠/非公開/未準備で記憶reset"),
        (["I08", "I01", "C04"], ["m15"], main, "S1/S2：ADX<=20レンジ、>=25方向一致トレンド", "S2はrangeを25未満・trendをADX>20同方向で保持。方向不一致/境界間は待機し逆側へ自動参入しない"),
        (["I12", "V01"], ["tick"], rules, "最新rawの量時計/内部比率/identity確認", "nativeの入力整合条件。RVOLや出来高フローは使わず、固有時計・受信時計は未収録"),
        (["B01"], ["tick"], rules, "全要求+1価格時計秒・ラージBBO代理", "新規買Ask/売Bid、返済買Bid/売Ask。役割は実新規signalへ固定し一建玉・一注文"),
        (["E01"], ["tick"], rules, "125逆行前250順行・純入口15集合", "全仮約定分母に期限/不足を残す。30分間引きは30分足でなく、運用黒字率と別"),
        (["I09", "C06", "E02"], ["tick"], rules, "全XでA=5/D=ceil(入口ATR/5)×5>=5追尾", "正常返済BBOで起動、最低同値/買ceil売floor/非緩和。pending中更新停止、設定価格で即約定しない"),
        (["I12", "E02"], ["tick"], [r for r in rules if r["出口"]["出口ID"] != "X0"], "X1入口native固定/X2有効公開native更新", "実fill役割の順行逆抜け<=0/反転到達>=0。hard125/250→追尾→通常線、期限/既pending優先"),
    ]
    return [{"設定ID": f"S{i:02d}", "手法ID": methods, "尺度ID": scales, "短記": short, "説明": detail,
             "結果短記": "・".join(r["評価ID"] for r in applies), "適用評価": [r["評価ID"] for r in applies]}
            for i, (methods, scales, applies, short, detail) in enumerate(groups, 1)]


def audits(study: Path, output: Path) -> tuple[str, list[Path]]:
    """正式合成と四監査・対応の明示合否を保存範囲別に表示する。

    引数: study/output (Path) は試行/文書出力先。
    返り値: tuple[str,list[Path]] は状態表/出典。主と子の項目数は非加算。
    """
    checks = [("合成検証.json", "最終43合成・編集終了"), ("独立監査.json", "主会計・先着・正式成果物"),
        ("状態独立確認.json", "全局面・共通M・複合採否・shadow"), ("追尾独立確認.json", "全X追尾と役割別通常出口"),
        ("対応診断.json", "見送り・段階・共通新規/参加集合"), ("Viewer照合.json", "事前3分表示のAPI照合")]
    rows, paths = [], []
    for name, title in checks:
        path = study/name
        if not path.exists():
            rows.append([title, "未完・未保存", "未算出", "なし"])
            continue
        data = G.read_json(path)
        verdict, count = data.get("全件一致"), data.get("照合項目数")
        if name == "合成検証.json":
            verdict, count = data.get("全件成功") is True and data.get("合成編集終了") is True, data["検証件数"]
        elif name == "対応診断.json" and verdict is None:
            verdict = data.get("対応集合全件一致")
        elif name == "Viewer照合.json" and verdict is None:
            cases = data.get("照合", [])
            verdict, count = (all(c.get("一致") is True for c in cases) if cases else None), len(cases)
        rows.append([title, "合格" if verdict is True else "不一致/失敗" if verdict is False else "明示合否未確認", number(count), G.link(path, output)])
        paths.append(path)
    text = "## 検査の状態\n\n最終43合成・合成編集終了true・関係6SHA実一致を確認して固定。主・状態・追尾は同じデータや参照を含むため件数を加算して独立標本としない。存在だけで合格とせず明示判定を読む。未保存は未完を維持して再生成する。\n"+G.table(["範囲", "明示判定", "件/項目数", "正本"], rows)
    text += "照合合格は模型と保存成果物の一致であり、空白内の真の経路、固有受信時計、今後の収益性を証明しない。\n\n"
    state_path, trail_path = study/"状態独立確認.json", study/"追尾独立確認.json"
    if state_path.exists():
        data = G.read_json(state_path)
        text += f"状態側は原価格cacheから1/3/5/15/60分OHLC・EMA10/20・ATR/RSI/ADX/DMI・局面/M/複合採否を別計算し、参照{number(data['保存参照足数'])}足・shadow{number(data['保存shadow数'])}候補・入口{number(data['保存入口数'])}集合を確認。補助nativeは固定18/19の独立確認済み参照を同値利用し、原板全行を新しく別抽出した証明ではない。\n\n"
    if trail_path.exists():
        data = G.read_json(trail_path)
        text += f"追尾側は保存された実新規・実返済の区間を固定し、{number(data['対象場候補数'])}場候補・{number(data['対象完結取引数'])}完結・{number(data['保存通常追尾行数'])}全ログを独立順走査。受注/一建玉/約定/会計は主監査と分担し、子の件数は主へ非加算。人工の監査準備proofも正式43合成へ加算しない。\n\n"
    viewer_path = study/"Viewer照合.json"
    if viewer_path.exists():
        data = G.read_json(viewer_path)
        text += "### Viewerでの代表確認\n\n"+str(data["接続先"])+"・設定 "+str(data["設定"])+"・"+str(data["WindowStyle"])+"起動。市場rootはViewer設定のdata_root基準。事前3分五戦略×X0/X2の代表を照合し、採用選択とはしない。PNG追加"+str(data["追加PNG数"])+"枚。\n"
        text += G.table(["候補", "場", "研究/API実現円", "API買/売保有", "数値指紋", "一致"],
            [[r["手法"], r["場"], f"{number(r['研究側純損益円'])}/{number(r['API最終状態']['realized_pnl_yen'])}",
              f"{r['API最終状態']['long_qty']}/{r['API最終状態']['short_qty']}",
              "一致" if r["数値本文SHA256一致"] else "不一致", "一致" if r["一致"] else "不一致"] for r in data["照合"]])
    return text, paths


# ----------------------------------------
# 実行済み結果の完成通知後だけ呼び、比較要約と必須の設定表へ絞る。

def run(study: Path, output: Path) -> list[Path]:
    """保存済み結果をREADMEの比較要約と必須の設定表へ表示する。

    引数: study/output (Path) は正式試行/文書出力先。
    返り値: list[Path] は二文書。単なる全件転記は作らず正本を参照する。
    """
    for name in ("条件.json", "計画.md", "固定.json", "結果.json", "入力台帳.json", "補助入力台帳.json"):
        if not (study/name).is_file():
            raise ValueError(name+"未保存のため数値文書を生成しない")
    config, report = G.read_json(study/"条件.json"), G.read_json(study/"結果.json")
    rules = definitions(config)
    entries, values = validate(config, report, rules)
    if any(G.sha(ROOT/name) != sha for name, sha in G.read_json(study/"固定.json")["ファイルSHA256"].items()):
        raise ValueError("固定core/合成/条件/入力SHAの変化")
    pointer, aux = G.read_json(study/"入力台帳.json"), G.read_json(study/"補助入力台帳.json")
    manifest_path = (study/pointer["参照"]).resolve()
    aux_paths = [(study/aux[key]).resolve() for key in ("参照", "作業台帳参照")]
    if G.sha(manifest_path) != pointer["SHA256"] or any(G.sha(path) != aux[key] for path, key in zip(aux_paths, ("SHA256", "作業台帳SHA256"))):
        raise ValueError("入力台帳の参照SHA不一致")
    catalog = G.read_json(G.CATALOG)
    if (len(catalog["methods"]), len(catalog["scales"])) != (51, 9):
        raise ValueError("51×9カタログが変化")
    output.mkdir(parents=True, exist_ok=True)
    readme, mapping_path = [output/name for name in ("README.md", "設定と結果.md")]
    intro = "NK225の1/3/5分×五戦略＝15入口集合、各X0/X1/X2＝45運用。B1/B2/S0は共通助走・必須追尾付き対照、S1/S2は複合候補。全65場は既使用（学習40・条件選択24・既使用11/4デイ1）。内部の後続検査も未見確認ではない。保存数値の表示だけを行い入力・売買を再生しない。\n\n"
    main_goals = sum(r["複合本命"] and r["70目標"] for r in entries.values())
    conclusion = f"**支持付き入口70目標は全体{report['入口70目標達成数']}/15、複合本命{main_goals}/6。費用資格は{report['費用資格数']}/18本命運用。** 対照27運用は採用候補へ繰り上げない。先着70%と小利確を含む運用黒字率は別。\n\n"
    methods = "## 局面・手法・待機をどう分けたか\n\n全戦略は同じMを待つ。Mは旧15分C/EMA20/前値/ADX/±DI有限、入口/15/60分のEMA10/20/前EMA20有限・ATR正、同場連続公開RSI五本。過去の五本の一部だけで始めず、欠枠/非公開/index飛越/RSI欠測で履歴を切る。上位は公開keyと足endが下位判断以下の最新値だけを用い、現在未準備を古正常値へ戻さない。\n\n"
    methods += G.table(["戦略", "共通M後の許可", "区分"], [["B1", "固定19 Q1だけ", "対照"], ["B2", "固定19 Q2だけ", "対照"], ["S0", "Q1/Q2常時混合", "対照"], ["S1", "即時局面＋三尺度EMA/RSI/急変条件", "複合本命"], ["S2", "履歴保持局面＋同じ複合条件", "複合本命"]])
    methods += "15分方向はC>EMA20>前EMAかつ+DI>−DIで買1、鏡像で売−1、他0。S1はADX<=20レンジ、ADX>=25かつ方向一致でトレンド、他待機。S2はレンジを25未満で、トレンドをADX>20かつ前と同方向で保持し、他は同じ20/25境界へ従う。15分新公開足ごと一回だけ更新し、場/欠枠/非公開/未準備で記憶を初期化する。未準備と予測としての待機を分ける。\n\n"
    methods += "方向側RSIは買RSI/売100−RSI。順行は局面トレンドとside一致、三尺度s=(EMA20−前EMA20)/その尺度ATRがside×s>=0.02、下位CがEMA20の有利側、RSI側直近3本>=50を全要求。反転はレンジ、abs(EMA10−EMA20)/ATR<=0.25かつabs(s)<=0.10の収束が三尺度中2以上、前RSI側<=40、現30〜60かつ改善を全要求する。\n\n"
    methods += "現RSI側>=70・前差>=12・過去4本で65以上が1本以下の全成立を急変警戒とし、S1/S2のQ1/Q2を抑止する。高RSI持続だけでは除外せず、将来反落を確認した名称にはしない。反転の現RSI上限60と急変下限70は両立しないため、range側急変除外を独立の追加効果へ数えない。EMA/RSIの追加条件は本命だけで、対照も同じMは要求。Q1/Q2は固定19の方向追加なしを読取再用し、native四点/epoch/ATR/終値改善/125-250条件を変えない。WAITを反対側参入へ自動変換しない。\n\n"
    trailing = "## 全45で必須の利益追尾\n\n実新規後・返済要求前の正常返済BBOでMFE>=5ptを初観測したら起動。D=max(5,ceil(入口ATR/5)×5)を固定し、side方向の保護利益=max(0,MFE−D)。価格変換後は買ceil/売floorの5pt丸め、起動後は最低新規同値・前設定より緩めない。\n\n"
    trailing += "全Xでhard125保護/TP250/期限を維持。X0も追尾必須、X1は入口要求native固定通常線、X2は有効公開native更新通常線を追加する。通常は実新規役割固定の順行逆抜け<=0/反転到達>=0。保有中の局面だけで役割変更/ドテン/返済はしない。\n\n"
    trailing += "順序は期限/既存待機約定→hard125→TP250→追尾→通常線、同原行はquote→bar→signal。返済pending中は追尾の起動/線更新も止め要求を上書きしない。TP等が先に要求された取引は後のMFEが5を越えても起動漏れとはしない。全要求後1価格時計秒以上の最初正常BBOで約定し、同値設定でもgap/待機/費用で赤字を残す。\n\n"
    limits = "## 条件と解釈の限界\n\nラージBBOでmicro1枚代理、倍率10円/pt・片道11円・呼値5pt、新規有効30秒・停止前・期限残60分。新規買Ask/売Bid・返済買Bid/売Ask。追加片道5/10ptは同じ完結往復から100/200円を控除する感度で、価格を滑らせた再参加の再生ではない。正常BBO空白300秒超/EOF/未解消がある全体の確定対象額はnullのまま。\n\n"
    limits += "本試行と00019の直接金額差には共通M・追尾追加も含まれ、局面分類だけの効果とはしない。本命/対照は同じM・追尾で比較し、見送りで失った順行と避けた逆行、共通実新規の出口差と片側だけ参加を分ける。件数消失を高勝率達成と呼ばず、同じ市場観測からの派生を独立標本へ加算しない。EMA/ADX/RSIは価格由来の関連特徴で独立した票ではない。\n\n"
    limits += "MFE後赤字は事後の観測峰と最終純額の関係で、その峰で実際に回収できた証明ではない。通常出口で保有期間が短くなる効果も含む。配信VWAP/代金固有時計・正確な受信時計は未収録で、repeat全長はオフライン出典metadataとして保存するだけ。心理/需給の説明を観測済み事実としない。全65既使用の追加開発であり、採用には将来の別確認が必要。\n\n"
    thresholds = "## 条件の要約と固定値\n"+G.table(["項目", "固定条件"], [[k, G.describe(v)] for k, v in config.items()])
    definitions_text = "## 全45評価と表示代表\n\n事前Viewerは3分五戦略×X0/X2の10運用。X1/1分/5分を未実行とはせず全数値を正式JSON/CSVへ残す。\n"+G.table(["評価", "候補", "区分", "Viewer", "費用資格"], [[r["評価ID"], r["候補ID"], "本命" if r["入口"]["複合本命"] else "対照", "表示" if r["候補ID"] in report["表示固定ID"] else "work明細・正式集計", "充足" if values[r["候補ID"]]["費用資格"] else "未達" if r["入口"]["複合本命"] else "採用対象外"] for r in rules])
    audit_text, audit_paths = audits(study, readme)
    summary = "# 試行00020：複数手法による局面切替と利益追尾\n\n"+intro+" / ".join(G.link(study/n, readme) for n in ("計画.md", "条件.json", "結果.json", "固定.json"))+" / "+G.link(mapping_path, readme)+"\n\n"+conclusion+methods+trailing+switching_table(entries, values)+diagnosis(study, readme)+limits+audit_text
    common = settings(rules)
    method_ids, scale_ids = {m["id"] for m in catalog["methods"]}, {s["id"] for s in catalog["scales"]}
    if any(set(s["手法ID"])-method_ids or set(s["尺度ID"])-scale_ids for s in common):
        raise ValueError("使用設定の手法/尺度が51×9に対応しない")
    mapping = "# 試行00020：設定と結果\n\n"+intro+conclusion+G.link(G.MASTER, mapping_path, "コピー元の汎用表")+" / "+G.link(readme, mapping_path)+" / "+G.link(study/"結果.json", mapping_path, "全45数値の正本")+"\n\n## 手法×時間スケール\n\n51手法×9尺度。Sは共通準備/本命だけの複合判別/追尾と執行、R01〜R45は複合評価で指標単独の成績ではない。共通Mを待つ対照と本命の条件を区別する。30分間引きは30分足ではない。\n\n"+G.matrix(catalog, mapping_path, common)
    mapping += "## 設定明細\n"+G.table(["設定", "手法/尺度", "短記", "条件と役割", "適用評価"], [[s["設定ID"], "/".join(s["手法ID"])+"・"+"/".join(s["尺度ID"]), s["短記"], s["説明"], "・".join(s["適用評価"])] for s in common])+thresholds+methods+trailing+definitions_text+limits+audits(study, mapping_path)[0]
    files = ("入力台帳.json", "補助入力台帳.json", "一覧.resources.json", "固定候補_取引.csv", "固定候補_注文.csv", "全候補_場別.csv", "局面品質.json", "入口品質.json", "参照品質.json", "入力品質.json", "作業成果物.json")
    viewing = "## 閲覧と再現\n\n"+" / ".join(G.link(study/n, readme) for n in files if (study/n).exists())+"\n\nViewer market_pathは設定の市場root基準、pnl_pathはpath_base=catalogの一覧親基準。原板を複製せず追加滑り0ptを表示する。全明細/全shadow/上下位足/局面/通常線ログはGit外work、正式には展開内容SHAを正本として記録。\n\n"
    names = ("局面.py", "入口.py", "運用.py", "検証.py", "合成検証.py", "レポート.py", "独立監査.py", "状態独立確認.py", "追尾独立確認.py", "対応診断.py")
    sources = [ROOT/"scripts/局面切替"/n for n in names if (ROOT/"scripts/局面切替"/n).exists()]
    doc = ROOT/"docs/議論/複数手法で局面を判別し利益を追尾する.md"
    viewing += "コード："+" / ".join(G.link(p, readme) for p in sources)+"。背景："+G.link(doc, readme)+"。\n\n"
    fence = chr(96)*3
    viewing += "保存結果の再表示：\n\n"+fence+"powershell\npython -X utf8 scripts/局面切替/レポート.py\n"+fence+"\n\n数値再生は検証.pyへ別の保存先/作業先を指定する。合成検証.py --finalは固定後変更を拒否し、追加検査は別ファイルへ保存する。\n\n"
    paths = [Path(__file__), DISPLAY, ROOT/"scripts/収縮反転/レポート.py", ROOT/"scripts/レポート/設定結果レポート.py", G.CATALOG, G.MASTER,
        *[study/n for n in ("計画.md", "条件.json", "固定.json", "結果.json", *files) if (study/n).exists()], manifest_path, *aux_paths, *audit_paths, *sources, doc]
    paths = list(dict.fromkeys(paths))
    for path, text in ((readme, summary+viewing), (mapping_path, mapping)):
        path.write_text(text+G.provenance(paths, path), encoding="utf-8")
    return [readme, mapping_path]


def main() -> None:
    """完成通知後の保存済み結果から比較要約と設定表を生成する。

    引数: なし。--study/--outputは任意の試行/文書先。
    返り値: None。市場データ再生・候補選び直しは行わない。
    """
    parser = argparse.ArgumentParser(description="複合局面切替と必須利益追尾の保存帳票")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print("\n".join(str(p) for p in run(args.study, args.output or args.study)))


if __name__ == "__main__":
    main()
