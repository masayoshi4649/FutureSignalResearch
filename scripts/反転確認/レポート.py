"""00012の4純入口と8運用を、保存済みJSONだけから文書へ写す。"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00012_BB反転の確認と構造リスク"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = {"学習": "学習40場", "条件選択": "条件選択24場", "後続検査": "既使用11/4デイ1場"}
LABELS = ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定")


def shared() -> Any:
    """汎用表の表示関数だけを読み込む。

    引数: なし。
    返り値: Any はmatrix・表・リンク・SHAを持つモジュール。
    """
    spec = importlib.util.spec_from_file_location("反転確認帳票の共通表示", ROOT/"scripts/レポート/設定結果レポート.py")
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


G = shared()


def number(value: float | int | None) -> str:
    """ゼロと未算出を区別し、数値を桁区切りにする。

    引数: value (float | int | None) は保存値。
    返り値: str は数値または未算出。
    """
    if value is None:
        return "未算出"
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"


def definitions(config: dict) -> list[dict]:
    """条件の順序で4入口とR01〜R08を列挙する。

    引数: config (dict) は固定条件。
    返り値: list[dict] は8運用の定義。新条件を追加しない。
    """
    if config["時間足分"] != [3, 5] or config["確認方式"] != ["即時", "次足確認"] or config["出口"] != [{"出口ID": key} for key in ("固定", "構造")]:
        raise ValueError("固定2足×2確認×2保護と異なります")
    sources = [{"入口ID": f"{size}分_{mode}", "確認方式": mode, "時間足分": size, "名称": "BB内復帰・"+mode, "役割": "反転"}
               for size in config["時間足分"] for mode in config["確認方式"]]
    rules = [{"候補ID": source["入口ID"]+"_"+policy["出口ID"], "入口": source, "出口": policy}
             for source in sources for policy in config["出口"]]
    for index, row in enumerate(rules, 1):
        row["評価ID"] = f"R{index:02d}"
    return rules


def validate_entry(item: dict) -> None:
    """入口の五分類・分母・率を照合する。

    引数: item (dict) は一入口一期間の保存集約。
    返り値: None。不一致は例外。
    """
    if item["候補数"] != sum(item[k] for k in LABELS) or item["約定候補数"] != item["候補数"]-item["未約定"]:
        raise ValueError("入口ラベルと分母が不一致")
    for success, total, rate in (("順行先着", "約定候補数", "確認率"), ("30分間引き_順行先着", "30分間引き_約定候補数", "30分間引き_確認率")):
        expected = item[success]/item[total] if item[total] else None
        if (expected is None) != (item[rate] is None) or expected is not None and not math.isclose(expected, item[rate], abs_tol=1e-12):
            raise ValueError("入口率と件数が不一致")


def validate(config: dict, result: dict, rules: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    """定義・支持・費用・構造取消・共通新規差を照合する。

    引数: config/result (dict) は条件・結果、rules (list[dict]) は固定8定義。
    返り値: tuple[dict[str,dict],dict[str,dict]] は4入口別・8運用別の正本値。
    """
    if result["全65場既使用"] is not True or result["入口125250評価の変更"] is not False:
        raise ValueError("既使用性または入口評価の状態が不一致")
    entries = {r["入口ID"]: r for r in result["入口評価"]}
    values = {r["候補ID"]: r for r in result["結果"]}
    sources = {r["入口"]["入口ID"]: r["入口"] for r in rules}
    if len(entries) != 4 or len(result["入口評価"]) != 4 or entries.keys() != sources.keys() or len(values) != 8 or len(result["結果"]) != 8 or values.keys() != {r["候補ID"] for r in rules}:
        raise ValueError("固定4入口・8運用と異なる集合")
    for source_id, entry in entries.items():
        if any(entry[k] != value for k, value in sources[source_id].items()):
            raise ValueError("入口定義が不一致")
        for period in PERIODS:
            validate_entry(entry[period])
        support = all(all(entry[p][k] >= limit for k, limit in limits.items()) for p, limits in config["入口支持"].items())
        goal = support and all(entry[p]["確認率"] >= config["目標確認率"] and entry[p]["30分間引き_約定候補数"] >= config["間引き必要件数"][p]
                               and entry[p]["30分間引き_確認率"] >= config["目標確認率"] for p in PERIODS[:2])
        if (entry["入口支持"], entry["70目標"]) != (support, bool(goal)):
            raise ValueError("入口の支持・目標判定が不一致")
    for definition in rules:
        row = values[definition["候補ID"]]
        source_id = row["入口"]["入口ID"]
        if row["入口"] != definition["入口"] or row["出口"] != definition["出口"]:
            raise ValueError("運用定義が条件と不一致")
        for period, sessions in zip(PERIODS, (40, 24, 1)):
            if row[period]["入口"] != entries[source_id][period]:
                raise ValueError("構造取消によって純入口集約が変化")
            item = row[period]["運用"]
            n = item["完結取引数"]
            if item["入力場数"] != sessions or item["活動場数"]+item["無取引場数"] != sessions or item["買い取引数"]+item["売り取引数"] != n or not 0 <= item["黒字取引数"] <= n:
                raise ValueError("運用の期間・件数が不一致")
            for slip in (0, 5, 10):
                net, average = item[f"追加{slip}pt純損益円"], item[f"追加{slip}pt平均円"]
                if not math.isclose(net, item["追加0pt純損益円"]-2*slip*config["運用"]["倍率"]*n, abs_tol=1e-8):
                    raise ValueError("費用感度が不一致")
                if (average is None) != (n == 0) or n and not math.isclose(average, net/n, abs_tol=1e-8):
                    raise ValueError("平均額の分母が不一致")
            prior = n
            for level in (20, 50, 100):
                reached, red = item[f"{level}pt到達取引"], item[f"{level}pt後純赤字"]
                if not 0 <= red <= reached <= prior:
                    raise ValueError("MFE到達・赤字化件数が不一致")
                prior = reached
            cancellations = item["構造無効新規取消数"]+item["構造未確認新規取消数"]
            if not 0 <= cancellations <= entries[source_id][period]["候補数"] or not 0 <= item["構造保護返済数"] <= n:
                raise ValueError("構造取消・返済件数が不一致")
            if row["出口"]["出口ID"] == "固定" and (cancellations or item["構造保護返済数"] or item["構造保護使用"]):
                raise ValueError("固定側に構造保護の集計が混入")
            base, pair = values[source_id+"_固定"][period]["運用"], item["共通新規比較"]
            if pair["共通実新規"]+pair["元のみ新規"] != base["完結取引数"] or pair["共通実新規"]+pair["変更のみ新規"] != n:
                raise ValueError("共通新規の集合件数が不一致")
            if not math.isclose(item["追加0pt純損益円"]-base["追加0pt純損益円"], pair["共通新規の純損益差円"]+pair["変更のみ純損益円"]-pair["元のみ純損益円"], abs_tol=1e-8):
                raise ValueError("共通新規差と集合差の損益が不一致")
            if not 0 <= pair["元赤字の損失縮小件数"] <= pair["共通実新規"] or not 0 <= pair["構造退出後に元固定利確要求"] <= pair["共通実新規"]:
                raise ValueError("損失縮小・早期退出件数が不一致")
        qualified = all(all(row[p]["運用"][k] >= limit for k, limit in limits.items()) and row[p]["運用"]["品質注意場数"] == 0 and row[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        if row["費用資格"] != qualified:
            raise ValueError("費用資格判定が不一致")
    if result["表示固定ID"] != [r["候補ID"] for r in rules] or result["入口70目標達成数"] != sum(r["70目標"] for r in entries.values()) or result["費用資格数"] != sum(r["費用資格"] for r in values.values()):
        raise ValueError("全8表示IDまたは資格集計が不一致")
    return entries, values


# ----------------------------------------
# 純入口4集合と単一建玉8経路を別々の分母で表示する。

def entry_table(entries: dict[str, dict]) -> str:
    """構造取消を除かない4入口の先着・支持を表示する。

    引数: entries (dict[str,dict]) は4純入口。
    返り値: str は3期間12行の表。
    """
    rows = []
    for source_id, entry in entries.items():
        for period in PERIODS:
            item = entry[period]
            rows.append([source_id, PERIOD_NAMES[period], item["候補数"], item["約定候補数"], *[item[k] for k in LABELS], G.pct(item["確認率"]),
                f"{item['30分間引き_順行先着']}/{item['30分間引き_約定候補数']}・{G.pct(item['30分間引き_確認率'])}", f"{item['約定開始日数']}日/{item['約定場数']}場",
                "充足" if entry["入口支持"] else "未達", "達成" if entry["70目標"] else "未達"])
    return "## 4純入口の125/250pt先着\n\n主率は順行250pt先着/全約定。逆行125pt・期限未達・観測不足を分母へ残す。構造の送信前取消を後付けで除外しない。仮想保有は重複し得る。支持/70目標は旧二期間の固定規則を各期間へ再掲し、11/4単独の判定ではない。\n"+G.table(["入口", "期間", "候補", "約定", "順", "逆", "期限", "不足", "未約定", "主率", "間引き順/約定・率", "約定日/場", "旧二期間支持", "旧二期間70目標"], rows)


def operation_tables(values: dict[str, dict], refs: dict[str, str], config: dict) -> str:
    """全8運用の費用・取消・早期返済・集合差を表示する。

    引数: values (dict[str,dict]) は8運用、refs (dict[str,str]) はR参照、config (dict) は費用。
    返り値: str は各3期間24行のMarkdown表。
    """
    operations, structure, pairs, holdings = [], [], [], []
    for cid, row in values.items():
        for period in PERIODS:
            item, prefix = row[period]["運用"], [refs[cid], PERIOD_NAMES[period]]
            n = item["完結取引数"]
            operations.append(prefix+[n, f"{item['黒字取引数']}/{n}・{G.pct(item['黒字取引数']/n if n else None)}", f"{item['買い取引数']}/{item['売り取引数']}", f"{item['活動場数']}/{item['入力場数']}", item["無取引場数"],
                *[number(item[f"追加{s}pt純損益円"]) for s in (0, 5, 10)], "未確定" if item["追加0pt確定対象円"] is None else number(item["追加0pt確定対象円"]),
                f"{item['品質注意場数']}/{item['EOF期限未達場数']}/{item['未解消場数']}", number(item["期間内最大場内DD円"])])
            structure.append(prefix+[item["構造無効新規取消数"], item["構造未確認新規取消数"], item["構造保護返済数"], item["初期125保護返済数"], item["基準赤字取引数"]])
            pair = item["共通新規比較"]
            base = values[row["入口"]["入口ID"]+"_固定"][period]["運用"]
            pairs.append(prefix+[number(item["追加0pt純損益円"]-base["追加0pt純損益円"]), pair["共通実新規"], pair["元のみ新規"], pair["変更のみ新規"], number(pair["共通新規の純損益差円"]),
                number(pair["変更のみ純損益円"]-pair["元のみ純損益円"]), pair["元赤字の損失縮小件数"], number(pair["元赤字の損失縮小純額差円"]), pair["元赤字から黒字"], pair["元黒字から赤字"], pair["構造退出後に元固定利確要求"], number(pair["元黒字だった共通新規の純額差円"])])
            average_pt = (item["追加0pt純損益円"]+2*config["運用"]["片道手数料円"]*n)/(config["運用"]["倍率"]*n) if n else None
            holdings.append(prefix+[number(item["追加0pt平均円"]), number(average_pt), number(item["保有分合計"]/n if n else None), G.pct(item["保有時間率_観測"]),
                *[f"{item[f'{k}pt後純赤字']}/{item[f'{k}pt到達取引']}" for k in (20, 50, 100)], G.pct(item["活動場赤字率"]), number(item["最悪場内時価円"])])
    text = "## 8運用の費用と活動\n\n金額は円。黒字率は追加0ptの完結取引純損益>0/全完結取引で、入口先着率とは異なる。最大場内DDは期間で最大だった一場の観測含み込みDDで、全期間累積DDではない。0取引も実行済みで、率・平均は未算出。\n"
    text += G.table(["評価", "期間", "完結", "黒字/全・率", "買/売", "活動/入力場", "無取引場", "追加0pt", "追加5pt", "追加10pt", "0pt確定対象", "注意/EOF/未解消場", "最大場内DD"], operations)
    text += "### 送信前取消と保護返済\n\n構造無効と、BBOなし/鮮度超過による構造未確認を分ける。要求時点に既知の正常板だけで送信前判定し、送信後の+1秒約定板を見た費用0取消は行わない。送信後に破綻すれば実新規・同原行保護要求・更に1秒以上後の返済と往復料を残す。\n"
    text += G.table(["評価", "期間", "構造無効の送信前取消", "構造未確認の送信前取消", "構造保護返済", "125pt非常保護返済", "基準赤字取引"], structure)
    text += "### 共通する実新規と早期返済の反例\n\n基準は同入口の固定。共通はイベントID/新規時計/原行/価格が一致した完結取引。全純額差＝共通純額差＋変更のみ純額−元のみ純額。元赤字の損失縮小は純額が改善した共通取引で黒字化も含む。元固定TP要求が構造の実返済後だった件数も残すが、これは事後診断で将来の利確判断には使わない。未解消があれば全新規集合を網羅する差とはしない。\n"
    text += G.table(["評価", "期間", "全純額差", "共通新規", "元のみ", "変更のみ", "共通純額差", "集合差純額", "元赤字の縮小件数", "同純額差", "元赤字→黒字", "元黒字→赤字", "構造返済後の元TP要求", "元黒字だった共通新規の純額差"], pairs)
    text += "### 保有長・平均値幅・MFE後の赤字\n\n手数料前平均ptは（基準純額＋往復手数料×完結数）/倍率/完結数。平均の勝ち幅や目標幅ではない。MFE欄は『基準赤字/そのMFE到達取引』。観測窓は実新規から実返済で出口により変わり、同じ将来経路ではない。\n"
    text += G.table(["評価", "期間", "基準平均円", "手数料前平均pt", "平均保有分", "観測保有率", "MFE20pt後赤字", "MFE50pt後赤字", "MFE100pt後赤字", "活動場赤字率", "最悪場内時価"], holdings)
    return text


# ----------------------------------------
# 共通準備・BB発動・設定足構造と原板監視を、別の役割として表へ置く。

def settings(rules: list[dict]) -> list[dict]:
    """実際に使った尺度と閾値だけへS/R参照を付ける。

    引数: rules (list[dict]) は固定8定義。
    返り値: list[dict] は汎用matrix用設定。
    """
    result, groups = [], []
    for size in (3, 5):
        same = [r for r in rules if r["入口"]["時間足分"] == size]
        confirmed = [r for r in same if r["入口"]["確認方式"] == "次足確認"]
        protected = [r for r in same if r["出口"]["出口ID"] == "構造"]
        scale = [f"m{size:02d}"]
        groups += [
            (["I01", "I08", "I09", "I05"], scale, same, "EMA20/ADX14/ATR14/BB20・共通準備", "同場6連続足、ATR14>0、当場準備済み15分EMA20と前値。指標単独効果ではない"),
            (["I05", "I08", "P05"], scale, same, "BB20×2内復帰・ADX<20", "前C<前下帯、今下帯≤今C<今SMA20、今C>前C。母標準偏差。売りは対称。確認方式では設定足の条件"),
            (["P01", "P07"], scale, confirmed, "次の1連続足C>設定H", "買C>設定H/売C<設定L。確認足でもADX<20・共通準備・時間条件、設定中心が有利側。帯内復帰を二度要求しない"),
            (["P03"], scale, protected, "設定L−5/H＋5の構造", "設定足を固定し125ptより不利へ広げない。確認方式も設定足を使う。原板での送信前判定と保護へ渡す"),
        ]
    groups += [
        (["I01"], ["m15"], rules, "準備済み確定15分EMA20・前値", "共通準備だけ。上位の買売方向フィルタは加えない"),
        (["B01"], ["tick"], rules, "ラージBBO・+1価格時計秒", "micro1枚代理、新規買Ask/売Bid・返済買Bid/売Ask。価格時計は受信時計ではない"),
        (["E01"], ["tick"], rules, "純入口4の順250/逆125pt先着", "構造送信前取消を後付け除外しない。期限/観測不足を全約定分母へ残し、8独立入口の成績としない"),
        (["E02"], ["tick"], rules, "TP250/非常SL125・構造有無", "全案固定TP250と期限を維持。構造は要求時既知板・鮮度30秒以内で審査、送信後の破綻は有償実約定後に返済要求。ソフト監視模型"),
    ]
    for methods, scales, applies, short, detail in groups:
        if applies:
            refs = [r["評価ID"] for r in applies]
            result.append({"設定ID": f"S{len(result)+1:02d}", "手法ID": methods, "尺度ID": scales, "短記": short,
                           "結果短記": "・".join(refs), "説明": detail, "適用評価": refs})
    return result


def audits(study: Path, output: Path) -> tuple[str, list[Path]]:
    """保存された明示合否を検査状態として表示する。

    引数: study/output (Path) は試行と文書。
    返り値: tuple[str,list[Path]] は表と実在する出典。
    """
    rows, sources = [], []
    for name, label in (("合成検証.json", "合成検証"), ("独立監査.json", "独立監査"),
                        ("構造独立確認.json", "構造の全経路確認"), ("Viewer照合.json", "Viewer照合")):
        path = study/name
        if not path.exists():
            rows.append([label, "未完・結果未保存", "未算出", "なし"])
            continue
        value = G.read_json(path)
        sources.append(path)
        verdict, count = value.get("全件一致"), value.get("照合項目数")
        if label == "合成検証":
            verdict, count = value.get("全件成功"), value.get("検証件数", value.get("件数"))
            if verdict is None:
                parts = list(value.get("結果", {}).values())
                verdict = all(p.get("全件成功") is True for p in parts) if parts else None
                count = sum(p.get("検証件数", p.get("件数", 0)) for p in parts) if parts else None
        elif label == "Viewer照合" and verdict is None:
            checks = value.get("照合", [])
            verdict, count = (all(v.get("一致") is True for v in checks) if checks else None), len(checks)
        state = "合格" if verdict is True else "不一致・失敗" if verdict is False else "資料あり・明示判定未確認"
        rows.append([label, state, number(count), G.link(path, output)])
    return "## 検査の状態\n\n集約保存と独立監査は別状態。未保存の監査を合格にしない。構造の全経路確認は主監査でも参照しており、別の市場標本として件数を加算しない。確認範囲・生成漏れ・局所経路再構成の限界は各正本を参照する。\n"+G.table(["範囲", "状態", "項目数", "正本"], rows), sources


def comparison(values: dict[str, dict]) -> str:
    """4入口それぞれの固定対照差を旧二期間で記述する。

    引数: values (dict[str,dict]) は全8運用。
    返り値: str は追加5pt後の全差・共通差。新候補を選ばない。
    """
    rows = []
    for row in values.values():
        if row["出口"]["出口ID"] != "構造":
            continue
        source_id = row["入口"]["入口ID"]
        base = values[source_id+"_固定"]
        cells = [source_id]
        for period in PERIODS[:2]:
            changed, original = row[period]["運用"], base[period]["運用"]
            cells += [number(changed["追加5pt純損益円"]-original["追加5pt純損益円"]), number(changed["共通新規比較"]["共通新規の純損益差円"])]
        rows.append(cells)
    return "## 同じ入口の固定保護からの差\n\n全差は追加5pt後、共通新規差は追加0ptの純額。共通新規は件数が同じなので追加費用差は相殺する。取消と再参加により全差は共通新規差と一致しない。次足確認と即時の比較には判断時計・新規価格の変化も含まれ、同じ時点のフィルタ効果だけではない。\n"+G.table(["入口", "学習：構造の全差", "学習：共通新規差", "選択：構造の全差", "選択：共通新規差"], rows)


def findings(entries: dict[str, dict], values: dict[str, dict]) -> str:
    """全固定候補から確認と構造の結果を範囲付きで記す。

    引数: entries/values (dict[str,dict]) は4入口・8運用の正本値。
    返り値: str は記述的な所見。追加候補の選定や最適化はしない。
    """
    rows = []
    for size in (3, 5):
        immediate, confirmed = entries[f"{size}分_即時"], entries[f"{size}分_次足確認"]
        for period in PERIODS[:2]:
            base, changed = immediate[period], confirmed[period]
            rows.append([size, PERIOD_NAMES[period], f"{base['順行先着']}/{base['約定候補数']}・{G.pct(base['確認率'])}",
                         f"{changed['順行先着']}/{changed['約定候補数']}・{G.pct(changed['確認率'])}", "充足" if confirmed["入口支持"] else "未達"])
    text = "## 今回の結果から読めること\n\n次の一足を確認すれば常に入口率が改善する、という結果ではなかった。確認で機会数と入口時計・価格が変わるため、率と支持を一緒に読む。\n"
    text += G.table(["足分", "期間", "即時：順/約定・率", "次足確認：順/約定・率", "次足確認の旧二期間支持"], rows)
    text += "### 全8案の観測損益と資格\n\n数値は0/5/10pt追加費用の順、円。観測黒字と支持・品質を含む費用資格は別であり、全候補が赤字だったとは要約しない。\n"
    rows = []
    for cid, row in values.items():
        cells = [cid]
        for period in PERIODS[:2]:
            item = row[period]["運用"]
            cells.append(f"{item['完結取引数']}取引："+" / ".join(number(item[f"追加{k}pt純損益円"]) for k in (0, 5, 10)))
        cells += [f"{row['学習']['運用']['品質注意場数']}/{row['条件選択']['運用']['品質注意場数']}", "充足" if row["費用資格"] else "未達"]
        rows.append(cells)
    text += G.table(["候補", "学習：取引数・0/5/10pt純額", "条件選択：取引数・0/5/10pt純額", "注意場 学習/選択", "費用資格"], rows)
    candidate = values["3分_即時_構造"]
    text += (f"3分_即時_構造は追加5pt後の観測純額が学習{number(candidate['学習']['運用']['追加5pt純損益円'])}円・"
             f"条件選択{number(candidate['条件選択']['運用']['追加5pt純損益円'])}円だったが、品質注意は"
             f"{candidate['学習']['運用']['品質注意場数']}/{candidate['条件選択']['運用']['品質注意場数']}場。"
             "全体を確定収益とせず、表示を採用へ読み替えない。\n\n")
    rows = []
    for period in PERIODS[:2]:
        item = values["5分_即時_構造"][period]["運用"]
        pair = item["共通新規比較"]
        rows.append([PERIOD_NAMES[period], pair["元赤字の損失縮小件数"], number(pair["元赤字の損失縮小純額差円"]),
                     number(pair["元黒字だった共通新規の純額差円"]), pair["構造退出後に元固定利確要求"], number(item["追加0pt純損益円"])])
    text += "5分_即時では構造保護で元の赤字を縮めた共通取引がある一方、元の黒字の取り分を失い、観測経路上で構造退出後に元固定TP要求へ届いた例もあった。損失縮小件数だけを改善としない。\n"
    text += G.table(["期間", "元赤字縮小件数", "縮小純額差", "元黒字部分の純額差", "構造退出後の元TP要求", "構造側の基準全純額"], rows)
    if all(entry["後続検査"]["候補数"] == 0 for entry in entries.values()):
        text += "既使用11/4デイは全4入口・8運用とも0件だった。未実行ではなく発動のない一場であり、支持や未見確認が増えたとは扱わない。\n\n"
    return text+"これらは既使用65場・固定8案の結果である。次足確認・構造保護一般の有効性や不可能性へ広げず、入口70%と費用後損益・品質を別の要件として残す。\n\n"


# ----------------------------------------
# 結果未保存なら停止し、固定済みcore・条件・計画には書き込まない。

def run(study: Path, output: Path) -> list[Path]:
    """保存数値の正本から正式3文書を再生成する。

    引数: study/output (Path) は試行と任意の表示確認先。
    返り値: list[Path] は3文書。結果未保存・固定不一致は例外。
    """
    config, result = G.read_json(study/"条件.json"), G.read_json(study/"結果.json")
    rules = definitions(config)
    entries, values = validate(config, result, rules)
    for name, digest in G.read_json(study/"固定.json")["ファイルSHA256"].items():
        if G.sha(ROOT/name) != digest:
            raise ValueError("固定されたコード・条件・入力が変更されています")
    pointer = G.read_json(study/"入力台帳.json")
    manifest_path = (study/pointer["参照"]).resolve()
    if G.sha(manifest_path) != pointer["SHA256"]:
        raise ValueError("入力台帳参照が不一致")
    manifest, catalog = G.read_json(manifest_path), G.read_json(G.CATALOG)
    if (len(catalog["methods"]), len(catalog["scales"])) != (51, 9):
        raise ValueError("汎用表51×9構成が変化")
    output.mkdir(parents=True, exist_ok=True)
    readme, setting_path, all_path = [output/name for name in ("README.md", "設定と結果.md", "全候補結果.md")]
    refs = {r["候補ID"]: r["評価ID"] for r in rules}
    intro = "NK225の3/5分×即時/次足確認による4純入口と、固定/構造保護による8運用を比較した。全65場は既使用（学習40・条件選択24・既使用11/4デイ1）。内部キー『後続検査』も新しい未見確認ではない。正本は数値JSONであり、この生成器は原板・作業特徴を再読せず、条件変更や選び直しをしない。\n\n"
    conclusion = f"**入口70目標は{result['入口70目標達成数']}/4、探索用費用資格は{result['費用資格数']}/8。** 固定した全8を表示し、表示対象を採用と呼ばない。\n\n"
    limits = "ラージBBOでmicro1枚代理、倍率10円/pt、片道11円は比較用仮定。追加片道5/10ptは同じ完結往復から100/200円を控除する感度で、滑りによる再発動・再参加の再計算ではない。CurrentPriceTimeは受信時計ではなく、1秒待機は実通信遅延の実測値ではない。経路注意・EOF・未解消を含む全体を確定収益としない。\n\n"
    definitions_table = "## 8運用の対応\n"+G.table(["評価", "候補", "足分", "確認方式", "保護", "費用資格"], [[r["評価ID"], r["候補ID"], r["入口"]["時間足分"], r["入口"]["確認方式"], r["出口"]["出口ID"], "充足" if values[r["候補ID"]]["費用資格"] else "未達"] for r in rules])
    thresholds = "## 固定した条件\n"+G.table(["項目", "設定"], [[key, G.describe(config[key])] for key in ("設定条件", "共通準備", "確認条件", "signal参照", "出口定義", "構造送信前審査", "入口支持", "間引き必要件数", "費用支持")])
    thresholds += "設定R2は00011を継承。即時はその足、確認は次の連続1足だけで買C>設定H/売C<設定Lを要求し、確認時のADX<20・共通準備・時間を再要求する。帯外→内を二度要求しない。ATRは確認足、中心と構造は設定足を保持する。旧設定の判定・満了後に現足の新R2を登録し、欠足で切る。\n\n"
    thresholds += "全運用でTP250/125pt非常保護・期限を維持。構造は要求時点以下の最後正常BBO、同時計原行以下、鮮度30秒以内で送信前審査。無効/未確認を別取消にし、未来の約定板で不利な新規だけを費用0で取り消さない。送信後に構造が崩れれば実約定→保護要求→更に1秒以上後の返済で往復料を負担する。\n\n"
    audit_readme, audit_paths = audits(study, readme)
    links = " / ".join(G.link(study/name, readme) for name in ("計画.md", "条件.json", "固定.json", "結果.json"))
    summary = "# 試行00012：BB反転の確認と構造リスク\n\n状態：固定8案の集約保存済み。\n\n"+intro+links+" / "+G.link(setting_path, readme)+" / "+G.link(all_path, readme)+"\n\n"+conclusion+limits+findings(entries, values)+comparison(values)+entry_table(entries)+definitions_table
    summary += "全8運用の費用・取消・早期返済・共通新規差は"+G.link(all_path, readme)+"へ掲載する。構造取消は入口先着率から除外していない。\n\n"+audit_readme
    viewer = "## 入力・閲覧・再現\n\n"+G.link(study/"入力台帳.json", readme)+" / "+G.link(manifest_path, readme, "00008参照台帳")+"\n\n"
    viewer += f"市場root：`{manifest['source_root']}`。Viewerのresource_rootは本repo。path_base=catalogでpnl_pathは一覧親、market_pathは市場rootからの相対。全8運用の追加滑り0ptだけを表示し原板を複製しない。\n\n"
    for name in ("一覧.resources.json", "固定候補_取引.csv", "固定候補_注文.csv", "全候補_場別.csv", "入力品質.json", "入口品質.json", "作業成果物.json", "Viewer照合.json"):
        if (study/name).exists():
            viewer += G.link(study/name, readme)+"\n\n"
    viewer += "帳票の再表示：\n\n```powershell\npython -X utf8 scripts/反転確認/レポート.py\n```\n\n数値再生は固定版の`検証.py --study 検証用保存先 --work 検証用作業先`。正式結果上書きと固定後のコード変更を拒否する。\n\n"
    viewer += "コード："+" / ".join(G.link(ROOT/"scripts/反転確認"/name, readme) for name in ("入口.py", "検証.py", "運用.py", "合成検証.py", "レポート.py"))+"。\n\n"
    summary += viewer
    common = settings(rules)
    setting = "# 試行00012：設定と結果\n\n"+intro+conclusion+G.link(G.MASTER, setting_path, "コピー元の汎用表")+" / "+G.link(readme, setting_path)+" / "+G.link(all_path, setting_path)+"\n\n"
    setting += "## 手法×時間スケール\n\n51手法×9尺度を保持。Sは準備・発動・保護の役割、R01〜R08は複合運用で指標単独効果ではない。4純入口を保護2案へ共有しており8独立入口ではない。未使用はデータ不存在を意味しない。RSI・MACD・数量・別BB倍率は未使用。\n\n"+G.matrix(catalog, setting_path, common)
    setting += "## 設定明細\n"+G.table(["設定", "手法/尺度", "短記", "閾値と役割", "適用評価"], [[s["設定ID"], "/".join(s["手法ID"])+"・"+"/".join(s["尺度ID"]), s["短記"], s["説明"], "・".join(s["適用評価"])] for s in common])
    setting += thresholds+definitions_table+"全期間の数値は"+G.link(all_path, setting_path)+"、正本は"+G.link(study/"結果.json", setting_path)+"。構造取消を先着分母へ後付け反映しない。\n\n"+limits
    audit_all, _ = audits(study, all_path)
    all_text = "# 試行00012：全候補結果\n\n"+intro+conclusion+G.link(readme, all_path)+" / "+G.link(setting_path, all_path)+"\n\n"+limits+thresholds+definitions_table+findings(entries, values)+comparison(values)+entry_table(entries)+operation_tables(values, refs, config)+audit_all
    paths = [Path(__file__), ROOT/"scripts/レポート/設定結果レポート.py", G.CATALOG, study/"計画.md", study/"条件.json", study/"固定.json", study/"入力台帳.json", manifest_path, study/"結果.json"]
    paths += [ROOT/"scripts/反転確認"/name for name in ("入口.py", "検証.py", "運用.py", "合成検証.py")]+audit_paths
    for path, text in ((readme, summary), (setting_path, setting), (all_path, all_text)):
        path.write_text(text+G.provenance(paths, path), encoding="utf-8")
    return [readme, setting_path, all_path]


def main() -> None:
    """試行と任意の表示確認先から帳票を生成する。

    引数: なし。--study/--outputを読む。
    返り値: None。生成先をJSON表示する。
    """
    parser = argparse.ArgumentParser(description="00012の4純入口と8運用を表示")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    study = args.study.resolve()
    print(json.dumps({"生成": [str(p) for p in run(study, (args.output or study).resolve())]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
