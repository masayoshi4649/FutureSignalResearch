"""00011の保存済み8入口・24運用を、共通設定表と結果文書へ写す。"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00011_順行と反転のチャート構造と利益回収"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = {"学習": "学習40場", "条件選択": "条件選択24場", "後続検査": "既使用11/4デイ1場"}
LABELS = ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定")


def shared() -> Any:
    """共通カタログの表示関数だけを読み込む。

    引数: なし。
    返り値: Any は既存のmatrix・リンク・表・SHA関数。
    """
    spec = importlib.util.spec_from_file_location("循環帳票の共通表示", ROOT / "scripts/レポート/設定結果レポート.py")
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


G = shared()


def number(value: float | int | None) -> str:
    """数値のゼロと未算出を区別して表示する。

    引数: value (float | int | None) は保存値。
    返り値: str は桁区切りの数値または未算出。
    """
    if value is None:
        return "未算出"
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"


def definitions(config: dict) -> list[dict]:
    """条件の固定順で8入口と24複合評価IDを列挙する。

    引数: config (dict) は固定条件。
    返り値: list[dict] はR01からR24の定義。新規候補は追加しない。
    """
    sources = [{"入口ID": f"{size}分_{family}", "入口系統": family, "時間足分": size,
                "名称": detail["名称"], "役割": detail["役割"]}
               for size in config["時間足分"] for family, detail in config["入口系統"].items()]
    if len(sources) != 8 or config["出口"] != [{"出口ID": key} for key in ("X0", "X1", "X2")]:
        raise ValueError("固定8入口×3出口と異なります")
    result = [{"候補ID": source["入口ID"]+"_"+policy["出口ID"], "入口": source, "出口": policy}
              for source in sources for policy in config["出口"]]
    for index, row in enumerate(result, 1):
        row["評価ID"] = f"R{index:02d}"
    return result


def validate_entry(item: dict) -> None:
    """五ラベル・全約定率・間引き率を独立に確認する。

    引数: item (dict) は一入口一期間の保存値。
    返り値: None。不一致は例外。
    """
    if item["候補数"] != sum(item[k] for k in LABELS) or item["約定候補数"] != item["候補数"]-item["未約定"]:
        raise ValueError("入口ラベルと分母が不一致")
    for success, total, rate in (("順行先着", "約定候補数", "確認率"),
                                ("30分間引き_順行先着", "30分間引き_約定候補数", "30分間引き_確認率")):
        expected = item[success]/item[total] if item[total] else None
        if (expected is None) != (item[rate] is None) or expected is not None and not math.isclose(expected, item[rate], abs_tol=1e-12):
            raise ValueError("入口率と件数が不一致")


def representative_key(row: dict) -> tuple:
    """旧二期間だけで表示順位の整合を確認する。

    引数: row (dict) は運用候補。
    返り値: tuple は追加5pt平均の最小側が大きい順、同値ID順。
    """
    return (-min(row[p]["運用"]["追加5pt平均円"] if row[p]["運用"]["追加5pt平均円"] is not None else -math.inf for p in PERIODS[:2]), row["候補ID"])


def validate(config: dict, report: dict, rules: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    """定義・分母・費用・新規集合・表示固定を照合する。

    引数: config/report (dict) は条件・結果、rules (list[dict]) は24定義。
    返り値: tuple[dict[str,dict],dict[str,dict]] は入口ID別と候補ID別の正本値。
    """
    if config["全65場既使用"] is not True or report["全65場既使用"] is not True or report["入口125250評価の変更"] is not False:
        raise ValueError("既使用範囲・入口評価の状態が不一致")
    entries = {r["入口ID"]: r for r in report["入口評価"]}
    values = {r["候補ID"]: r for r in report["結果"]}
    source_map = {r["入口"]["入口ID"]: r["入口"] for r in rules}
    if len(entries) != 8 or len(report["入口評価"]) != 8 or entries.keys() != source_map.keys() or len(values) != 24 or len(report["結果"]) != 24 or values.keys() != {r["候補ID"] for r in rules}:
        raise ValueError("固定8入口・24運用と異なる集合")
    for source_id, entry in entries.items():
        if any(entry[k] != value for k, value in source_map[source_id].items()):
            raise ValueError("入口定義が条件と不一致")
        for period in PERIODS:
            validate_entry(entry[period])
        support = all(all(entry[p][k] >= limit for k, limit in limits.items()) for p, limits in config["入口支持"].items())
        goal = support and all(entry[p]["確認率"] >= config["目標確認率"] and entry[p]["30分間引き_約定候補数"] >= config["間引き必要件数"][p]
                               and entry[p]["30分間引き_確認率"] >= config["目標確認率"] for p in PERIODS[:2])
        if (entry["入口支持"], entry["70目標"]) != (support, bool(goal)):
            raise ValueError("入口支持・目標の保存判定が不一致")
    for definition in rules:
        row = values[definition["候補ID"]]
        source_id = row["入口"]["入口ID"]
        if row["入口"] != definition["入口"] or row["出口"] != definition["出口"]:
            raise ValueError("候補の固定定義が不一致")
        for period, sessions in zip(PERIODS, (40, 24, 1)):
            if row[period]["入口"] != entries[source_id][period]:
                raise ValueError("同じ入口の出口間で先着集約が変化")
            item = row[period]["運用"]
            n = item["完結取引数"]
            if item["入力場数"] != sessions or item["活動場数"]+item["無取引場数"] != sessions or item["買い取引数"]+item["売り取引数"] != n or not 0 <= item["黒字取引数"] <= n:
                raise ValueError("運用件数と期間・売買の内訳が不一致")
            for slip in (0, 5, 10):
                net, average = item[f"追加{slip}pt純損益円"], item[f"追加{slip}pt平均円"]
                if not math.isclose(net, item["追加0pt純損益円"]-2*slip*config["運用"]["倍率"]*n, abs_tol=1e-8):
                    raise ValueError("追加費用の控除が不一致")
                if (average is None) != (n == 0) or n and not math.isclose(average, net/n, abs_tol=1e-8):
                    raise ValueError("平均損益の分母が不一致")
            previous = n
            for level in ("20pt", "50pt", "100pt"):
                reached, red = item[level+"到達取引"], item[level+"後純赤字"]
                if not 0 <= red <= reached <= previous:
                    raise ValueError("MFE到達・赤字化件数が不一致")
                previous = reached
            if not 0 <= item["1ATR後純赤字"] <= item["1ATR到達取引"] <= n:
                raise ValueError("1ATR赤字化が不一致")
            if item["利益床使用"]:
                if item["床起動取引数"]+item["床未起動取引数"] != n or not math.isclose(item["床起動済純損益円"]+item["床未起動純損益円"], item["追加0pt純損益円"], abs_tol=1e-8):
                    raise ValueError("利益床の分解が不一致")
            pair, base = item["共通新規比較"], values[source_id+"_X0"][period]["運用"]
            if pair["共通実新規"]+pair["元のみ新規"] != base["完結取引数"] or pair["共通実新規"]+pair["変更のみ新規"] != n:
                raise ValueError("共通実新規と集合差の件数が不一致")
            if not math.isclose(item["追加0pt純損益円"]-base["追加0pt純損益円"], pair["共通新規の純損益差円"]+pair["変更のみ純損益円"]-pair["元のみ純損益円"], abs_tol=1e-8):
                raise ValueError("共通実新規と集合差の損益が不一致")
        qualified = all(all(row[p]["運用"][k] >= limit for k, limit in limits.items()) and row[p]["運用"]["品質注意場数"] == 0 and row[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        if row["費用資格"] != qualified:
            raise ValueError("費用資格の保存判定が不一致")
    fixed = []
    for source_id in source_map:
        variants = [r for r in values.values() if r["入口"]["入口ID"] == source_id]
        fixed.extend((source_id+"_X0", min(variants, key=representative_key)["候補ID"]))
    if report["表示固定ID"] != list(dict.fromkeys(fixed)) or report["入口70目標達成数"] != sum(r["70目標"] for r in entries.values()) or report["費用資格数"] != sum(r["費用資格"] for r in values.values()):
        raise ValueError("表示固定IDまたは合格集計が不一致")
    return entries, values


# ----------------------------------------
# 入口8集合と運用24経路を別表へ写し、ゼロ・欠測・対象外を区別する。

def entry_table(entries: dict[str, dict]) -> str:
    """入口先着と30分間引き、支持を8入口単位で表示する。

    引数: entries (dict[str,dict]) は保存された8入口。
    返り値: str は三期間24行の表。
    """
    rows = []
    for source_id, entry in entries.items():
        for period in PERIODS:
            item = entry[period]
            rows.append([source_id, PERIOD_NAMES[period], item["候補数"], item["約定候補数"], *[item[k] for k in LABELS], G.pct(item["確認率"]),
                         f"{item['30分間引き_順行先着']}/{item['30分間引き_約定候補数']}・{G.pct(item['30分間引き_確認率'])}",
                         f"{item['約定開始日数']}日/{item['約定場数']}場", "充足" if entry["入口支持"] else "未達", "達成" if entry["70目標"] else "未達"])
    return "## 8入口の125/250pt先着評価\n\n主率は順行250pt先着/全約定。逆行125pt・期限未達・観測不足を分母へ残し、未約定を別記する。支持と70目標は旧二期間を合わせた固定規則の判定を各行へ再掲し、11/4一場単独の判定ではない。30分間引きは場・方向別の要求時点で行い、将来ラベルで間引かない。\n" + G.table(["入口", "期間", "候補", "約定", "順", "逆", "期限", "不足", "未約定", "主率", "間引き順/約定・率", "約定日/場", "旧二期間支持", "旧二期間70目標"], rows)


def operation_tables(rows: list[dict], values: dict[str, dict], refs: dict[str, str], config: dict, detailed: bool = True) -> str:
    """費用・保有・MFE・床・共通新規差を別々に表示する。

    引数: rows (list[dict]) は表示候補、values (dict[str,dict]) は全24、refs (dict[str,str]) はR参照、
    config (dict) は費用、detailed (bool) は全補助表も表示するか。
    返り値: str はMarkdown。未実行と0取引を混同しない。
    """
    operations, holdings, mfe, floors, pairs = [], [], [], [], []
    for row in rows:
        for period in PERIODS:
            item, prefix = row[period]["運用"], [refs[row["候補ID"]], PERIOD_NAMES[period]]
            n = item["完結取引数"]
            operations.append(prefix+[n, f"{item['黒字取引数']}/{n}・{G.pct(item['黒字取引数']/n if n else None)}", f"{item['買い取引数']}/{item['売り取引数']}",
                f"{item['活動場数']}/{item['入力場数']}", item["無取引場数"], *[number(item[f"追加{s}pt純損益円"]) for s in (0, 5, 10)],
                "未確定" if item["追加0pt確定対象円"] is None else number(item["追加0pt確定対象円"]),
                f"{item['品質注意場数']}/{item['EOF期限未達場数']}/{item['未解消場数']}", number(item["期間内最大場内DD円"])])
            average_pt = (item["追加0pt純損益円"]+2*config["運用"]["片道手数料円"]*n)/(n*config["運用"]["倍率"]) if n else None
            holdings.append(prefix+[number(item["追加0pt平均円"]), number(average_pt), number(item["保有分合計"]/n if n else None),
                                    G.pct(item["保有時間率_観測"]), G.pct(item["活動場赤字率"]), G.pct(item["黒字場利益の最大場寄与"])])
            mfe.append(prefix+[f"{item[key+'後純赤字']}/{item[key+'到達取引']}・{G.pct(item[key+'後純赤字']/item[key+'到達取引'] if item[key+'到達取引'] else None)}" for key in ("20pt", "50pt", "100pt", "1ATR")])
            floor_values = [number(item[k]) if item["利益床使用"] else "対象外" for k in ("床未起動取引数", "床未起動赤字取引数", "床未起動純損益円", "床起動済純損益円")]
            floors.append(prefix+["あり" if item["利益床使用"] else "なし", item["床起動取引数"], *floor_values, item["中心線超過新規数"], number(item["最悪場内時価円"])])
            pair = item["共通新規比較"]
            base = values[row["入口"]["入口ID"]+"_X0"][period]["運用"]
            pairs.append(prefix+[number(item["追加0pt純損益円"]-base["追加0pt純損益円"]), pair["共通実新規"], pair["元のみ新規"], pair["変更のみ新規"],
                number(pair["共通新規の純損益差円"]), number(pair["変更のみ純損益円"]-pair["元のみ純損益円"]), pair["元赤字から黒字"], pair["元黒字から赤字"], number(pair["元黒字だった共通新規の純額差円"])])
    text = "## 単一建玉の運用と費用\n\n金額は円。黒字は追加0ptの完結取引純損益>0。最大場内DDは期間で最大だった一場の観測含み込みDDで、全場累積DDではない。0取引も実行済みであり、率・平均は未算出。\n"
    text += G.table(["評価", "期間", "完結", "黒字/全・率", "買/売", "活動/入力場", "無取引場", "追加0pt", "追加5pt", "追加10pt", "0pt確定対象", "注意/EOF/未解消場", "最大場内DD"], operations)
    if not detailed:
        return text
    text += "### 1取引の値幅と保有長\n\n手数料前平均ptは（基準純額＋往復手数料×完結数）/倍率/完結数。平均値であり利確幅・平均の勝ち幅ではない。X1/X2は固定TP250なしで、大きな勝ちも小さな回帰利確も生じ得る。入口の250pt先着とは別の量である。\n"
    text += G.table(["評価", "期間", "基準平均円", "手数料前平均pt", "平均保有分", "観測保有率", "活動場赤字率", "最大黒字場寄与"], holdings)
    text += "### MFE到達後の赤字化\n\nセルは『基準純赤字取引/当MFE到達取引・率』。実新規から実返済までの返済側正常BBOを使う。出口によって窓が変わるため、同じ将来経路の捕捉率ではない。1ATRは入口判断時の固定ATR14。\n"
    text += G.table(["評価", "期間", "20pt後赤字", "50pt後赤字", "100pt後赤字", "1ATR_e後赤字"], mfe)
    text += "### 利益床起動前と中心超過新規\n\n床は反転X2だけ。未起動純額には初期SL以外の通常出口・期限も含み、初期SL損失だけの値ではない。順行2ATR追尾を床起動件数へ数えない。中心超過新規は入口を取り消さず、同原行で返済要求して待機後に返す。\n"
    text += G.table(["評価", "期間", "反転ATR床", "床起動取引", "未起動取引", "未起動赤字", "未起動純額", "起動済純額", "中心超過新規", "最悪場内時価"], floors)
    text += "### 同じ実新規と新規集合の差\n\n基準は同入口X0。共通はイベントID・新規時計・原行・価格が全て一致した完結取引。全純額差＝共通新規差＋変更のみ純額−元のみ純額。未解消があれば、全新規を網羅する会計差とはしない。\n"
    text += G.table(["評価", "期間", "全純額差", "共通実新規", "元のみ", "変更のみ", "共通純額差", "集合差純額", "元赤字→黒字", "元黒字→赤字", "元黒字だった共通新規の純額差"], pairs)
    return text


# ----------------------------------------
# 汎用表は準備だけの使用と、発動・出口での使用を設定明細で区別する。

def settings(rules: list[dict]) -> list[dict]:
    """実際の24条件を51手法×9尺度の使用セルへ対応させる。

    引数: rules (list[dict]) は24定義。
    返り値: list[dict] は設定IDとR参照を持つmatrix用設定。
    """
    result, groups = [], []
    for size in (3, 5):
        same = [r for r in rules if r["入口"]["時間足分"] == size]
        trend = [r for r in same if r["入口"]["役割"] == "順行"]
        reversal = [r for r in same if r["入口"]["役割"] == "反転"]
        scale = [f"m{size:02d}"]
        groups += [
            (["I01", "I08", "I09", "I05"], scale, same, "EMA20/ADX14/ATR14/BB20・共通準備", "全4系統の母集団を揃える準備。ATR>0、同場6連続足。計算した各指標の単独効果ではない"),
            (["I01", "P08"], scale, [r for r in same if r["入口"]["入口系統"] == "T1"], "前C≤前E→今C>今E>前E", "上位方向を前・現の両時点で保持し今C>前C。売りは対称"),
            (["P03", "P07", "P10"], scale, [r for r in same if r["入口"]["入口系統"] == "T2"], "6本端突破→1〜3足再テスト", "突破足を除く6本端を固定、最新登録だけ。買LはR±5pt内、C>R+5、上位方向一致。終値水準失効・満了・消費・同足禁止"),
            (["P03", "P09"], scale, [r for r in same if r["入口"]["入口系統"] == "R1"], "L<Q<C≤R・ADX<20", "当足を除く直前6本の安Q/高R、今C>前C、中心M>C。売りは対称"),
            (["I05"], scale, [r for r in same if r["入口"]["入口系統"] == "R2"], "BB20・2σ外→内・中心未満", "母標準偏差。前C<前下帯、今下帯≤今C<今M、今C>前C、ADX<20。売りは対称"),
            (["I08"], scale, reversal, "WilderADX14<20", "R1/R2の反転環境。DI交差・ADX上昇条件は使わない"),
            (["I01"], scale, [r for r in trend if r["出口"]["出口ID"] != "X0"], "確定C≤EMA20の失効", "保有後公開された同尺度の確定終値で等号を含む反対側。遅延>30秒を使わない"),
            (["I01"], scale, [r for r in reversal if r["出口"]["出口ID"] != "X0"], "入口判断時SMA20固定目標", "中心を将来値へ更新しない。実新規が中心以上なら同原行で返済要求。BB帯への利確ではない"),
            (["I09", "C06"], scale, [r for r in trend if r["出口"]["出口ID"] == "X2"], "固定2ATR_eの単調追尾", "実新規以後の最高Bid/最低Ask。買max/売min、買下丸め/売上丸め。ATRや建玉前高安を差し替えない。Chandelier原典の再現ではない"),
            (["I09"], scale, [r for r in reversal if r["出口"]["出口ID"] == "X2"], "1ATR_e起動→0.5ATR_e床", "入口ATR14固定。返済側MFE到達後の固定利益床。実現利益の保証ではない"),
            (["C07"], scale+["m15"], trend, f"{size}分と確定15分方向", "T1は前現とも整合、T2は再テスト発動時整合。上位足終了・確認時計/原行を守る"),
        ]
    groups += [
        (["I01"], ["m15"], rules, "当場公開済EMA20・前値準備", "全4系統の共通準備。方向条件を使うのはT1/T2。未準備を中立へ変換しない"),
        (["B01"], ["tick"], rules, "ラージBBOでmicro1枚代理", "新規買Ask/売Bid、返済買Bid/売Ask。+1価格時計秒待機。数量偏りは使用しない"),
        (["E01"], ["tick"], rules, "順250/逆125pt先着・8入口共有", "8入口を出口と独立評価しX0/X1/X2へ共有。期限/不足も全約定分母。24独立入口の成果とはしない"),
        (["E02"], ["tick"], rules, "X0固定幅、X1/X2チャート出口", "全案SL125・期限。X0だけTP250、X1/X2は固定TPなし。X2は順行追尾/反転床。ソフト監視模型"),
    ]
    for methods, scales, applies, short, detail in groups:
        if applies:
            refs = [r["評価ID"] for r in applies]
            result.append({"設定ID": f"S{len(result)+1:02d}", "手法ID": methods, "尺度ID": scales,
                           "短記": short, "結果短記": "・".join(refs), "説明": detail, "適用評価": refs})
    return result


def audits(study: Path, output: Path) -> tuple[str, list[Path]]:
    """保存された明示判定だけを検査状態として示す。

    引数: study/output (Path) は試行と出力。
    返り値: tuple[str,list[Path]] は状態表と実在する出典。
    """
    rows, sources = [], []
    for name, label in (("合成検証.json", "合成検証"), ("独立監査.json", "独立監査"),
                        ("出口独立確認.json", "出口実例の局所独立確認"), ("Viewer照合.json", "Viewer照合")):
        path = study / name
        if not path.exists():
            rows.append([label, "未完・結果未保存", "未算出", "なし"])
            continue
        value = G.read_json(path)
        sources.append(path)
        verdict, count = value.get("全件一致"), value.get("照合項目数")
        if label == "合成検証":
            parts = list(value.get("結果", {}).values())
            verdict = all(v.get("全件成功") is True for v in parts) if parts else value.get("全件成功")
            count = sum(v.get("件数", v.get("検証件数", 0)) for v in parts) if parts else value.get("検証件数")
        elif label == "Viewer照合" and verdict is None:
            checks = value.get("照合", [])
            verdict, count = (all(v.get("一致") is True for v in checks) if checks else None), len(checks)
        state = "合格" if verdict is True else "不一致・失敗" if verdict is False else "資料あり・明示判定未確認"
        rows.append([label, state, number(count), G.link(path, output)])
    text = "## 検査の状態\n\n数値集約の保存と独立監査は別状態。未保存を合格としない。出口実例の局所照合は親監査でも参照されるため、件数を別の独立標本として加算しない。入口生成漏れや全出口要求の全面的な独立再実装まで保証した監査ではない。詳細は各正本の範囲・限界を参照する。\n"
    return text+G.table(["範囲", "状態", "項目数", "正本"], rows), sources


def findings(entries: dict[str, dict], values: dict[str, dict]) -> str:
    """全固定候補の傾向だけを記し、追加選定をしない。

    引数: entries/values (dict[str,dict]) は8入口・24運用。
    返り値: str は実証範囲付きの要点。
    """
    rows = []
    for source_id, entry in entries.items():
        base = values[source_id+"_X0"]
        cells = [source_id]
        for exit_id in ("X1", "X2"):
            changed = values[source_id+"_"+exit_id]
            cells.append(" / ".join(number(changed[p]["運用"]["追加5pt純損益円"]-base[p]["運用"]["追加5pt純損益円"]) for p in PERIODS[:2]))
        rows.append(cells)
    text = "## X0対照から何が変わったか\n\n同入口X0との差を、旧学習/条件選択の順に円で表示する。出口によって後続の新規参加も変わる全運用差であり、共通実新規だけの純粋な出口効果ではない。\n"
    text += G.table(["入口", "X1：追加5pt後全差 学習/選択", "X2：追加5pt後全差 学習/選択"], rows)
    both_positive = [row["候補ID"] for row in values.values() if all(row[p]["運用"]["追加5pt純損益円"] > 0 for p in PERIODS[:2])]
    text += "両旧期間で追加5pt後の観測純損益が正の候補：" + ("、".join(both_positive) if both_positive else "なし") + "。観測黒字と支持・品質を含む費用資格は別。全候補が赤字だったという要約はしない。\n\n"
    candidate, source = values["5分_R2_X0"], entries["5分_R2"]
    text += (f"5分_R2_X0は学習{candidate['学習']['運用']['完結取引数']}取引で基準/追加5pt後"
             f"{number(candidate['学習']['運用']['追加0pt純損益円'])}/{number(candidate['学習']['運用']['追加5pt純損益円'])}円、"
             f"条件選択{candidate['条件選択']['運用']['完結取引数']}取引で"
             f"{number(candidate['条件選択']['運用']['追加0pt純損益円'])}/{number(candidate['条件選択']['運用']['追加5pt純損益円'])}円だった。"
             f"学習に品質注意{candidate['学習']['運用']['品質注意場数']}場を含み、全体の確定対象額は"
             f"{'未確定' if candidate['学習']['運用']['追加0pt確定対象円'] is None else number(candidate['学習']['運用']['追加0pt確定対象円'])}。"
             f"入口先着は学習{source['学習']['順行先着']}/{source['学習']['約定候補数']}、"
             f"条件選択{source['条件選択']['順行先着']}/{source['条件選択']['約定候補数']}であり、"
             "学習の支持条件を満たさない。同じ骨格のX1/X2との差は上表へ全件残し、観測黒字だけを採用根拠にしない。\n\n")
    small = values["3分_R2_X2"]["条件選択"]["運用"]
    text += (f"3分_R2_X2は条件選択の黒字取引{small['黒字取引数']}/{small['完結取引数']}="
             f"{G.pct(small['黒字取引数']/small['完結取引数'] if small['完結取引数'] else None)}でも、追加5pt後は"
             f"{number(small['追加5pt純損益円'])}円だった。小幅利確の黒字率70%超と入口70%目標・費用後黒字を混同しない。\n\n")
    single = values["3分_T1_X1"]
    text += (f"3分_T1_X1は既使用11/4デイだけでは基準{number(single['後続検査']['運用']['追加0pt純損益円'])}円だが、"
             f"旧二期間の基準純額は{number(single['学習']['運用']['追加0pt純損益円'])}/"
             f"{number(single['条件選択']['運用']['追加0pt純損益円'])}円。すでに使用済みの一場の大勝ちで表示代表や条件を選び直さない。\n\n")
    return text+"X1/X2は固定TP250を外しており、利益保護だけを足した効果とはしない。反転は中心まで戻る小幅利確、順行はEMA出口まで伸ばす保有となり得る。黒字率・平均利益・保有長・MFE赤字化・費用を合わせて読む。全65場は既使用で、11/4一場を新しい未見確認へ数えない。\n\n"


def attention_note(study: Path, output: Path) -> str:
    """注意経路の追加診断が保存された場合だけ参照を置く。

    引数: study/output (Path) は試行とMarkdown。
    返り値: str は診断リンクと解釈の境界。未保存なら空文字。
    """
    path = study/"注意経路診断.json"
    if not path.exists():
        return ""
    return ("## 注意経路の追加診断\n\n5分_R2_X0の学習注意2場の経路は"+G.link(path, output)+
            "を参照する。観測された注意取引や注意部分の事後除外は、空白中を復元した成績でも、未見の別標本でもない。"
            "全体の確定対象額は未確定のままとし、注意除外の参考値を全体の代用にしない。\n\n")


def stability_note(study: Path, output: Path) -> str:
    """追加の利益集中診断が同じ固定結果に基づく場合だけ参照する。

    引数: study/output (Path) は試行とMarkdown。
    返り値: str は参考診断のリンクと限界。診断未保存なら空文字。
    """
    path = study/"安定性診断.json"
    if not path.exists():
        return ""
    diagnostic = G.read_json(path)
    if diagnostic["固定結果SHA256"] != G.sha(study/"結果.json"):
        raise ValueError("安定性診断と固定結果の指紋が異なります")
    return ("## 利益集中と日単位の追加診断\n\n"+G.link(study/"安定性診断.md", output)+
            "に全24候補・旧二期間・追加費用0/5/10ptを保存した。5分_R2_X0は両期間で観測黒字だが、"
            "上位3黒字場を事後に除く参考額は赤字で、日単位復元抽出の95参考区間も0をまたぐ。"
            "事後除外は実行可能な回避規則ではなく、参考区間も多重比較・候補選択・日をまたぐ依存・観測空白を解消しない。"
            "安定収益や将来の成功確率を確認したとはしない。\n\n")


# ----------------------------------------
# 固定実装・原板には触れず、保存済み集約だけから文書を再生成する。

def run(study: Path, output: Path) -> list[Path]:
    """数値正本からREADME・設定表・全候補結果を生成する。

    引数: study/output (Path) は正式試行と任意の表示確認先。
    返り値: list[Path] は3文書。結果未保存は例外で停止する。
    """
    config, report = G.read_json(study/"条件.json"), G.read_json(study/"結果.json")
    rules = definitions(config)
    entries, values = validate(config, report, rules)
    fixed = G.read_json(study/"固定.json")
    for name, digest in fixed["ファイルSHA256"].items():
        if G.sha(ROOT/name) != digest:
            raise ValueError("実行前固定の入力・コードが変更されています")
    pointer = G.read_json(study/"入力台帳.json")
    manifest_path = (study/pointer["参照"]).resolve()
    if G.sha(manifest_path) != pointer["SHA256"]:
        raise ValueError("参照台帳SHA256が不一致")
    manifest = G.read_json(manifest_path)
    catalog = G.read_json(G.CATALOG)
    if (len(catalog["methods"]), len(catalog["scales"])) != (51, 9):
        raise ValueError("共通表の51×9構成が変化")
    output.mkdir(parents=True, exist_ok=True)
    readme, setting_path, all_path = [output/name for name in ("README.md", "設定と結果.md", "全候補結果.md")]
    refs = {r["候補ID"]: r["評価ID"] for r in rules}
    intro = "NK225の8入口×3出口＝24運用を、既使用65場（学習40・条件選択24・既使用11/4デイ1）で比較した。新しい未見確認ではない。内部キー『後続検査』もここでは既使用11/4デイを指す。結果の正本は数値JSONであり、この生成器は原板・作業特徴を再読せず、候補追加・閾値変更・再選定をしない。\n\n"
    conclusion = f"**入口70目標の達成は{report['入口70目標達成数']}/8、探索用費用資格は{report['費用資格数']}/24。** 表示代表は採用ではなく、支持未達・品質注意を残す。\n\n"
    limits = "micro1枚をラージBBOで代理、倍率10円/pt、片道11円は比較仮定。追加片道5/10ptは同じ完結往復への100/200円控除で、追加滑りで入口や出口を再発動した計算ではない。CurrentPriceTimeは受信時計ではなく、1秒待機は実通信遅延の実測ではない。全体に品質注意・EOF・未解消があれば確定収益と呼ばない。\n\n"
    definition_rows = [[r["評価ID"], r["候補ID"], r["入口"]["名称"], r["入口"]["役割"], r["入口"]["時間足分"], r["出口"]["出口ID"], "あり" if r["候補ID"] in report["表示固定ID"] else "なし", "充足" if values[r["候補ID"]]["費用資格"] else "未達"] for r in rules]
    definition_table = "## 24複合評価の対応\n"+G.table(["評価", "候補", "入口", "役割", "足分", "出口", "正式約定表示", "費用資格"], definition_rows)
    thresholds = "## 固定した閾値と役割\n"+G.table(["入口系統", "保存設定"], [[key, G.describe(value)] for key, value in config["入口系統"].items()])
    thresholds += G.table(["出口", "保存定義"], [[key, value] for key, value in config["出口定義"].items()])
    thresholds += "全4系統にEMA20/ATR14>0/ADX14/BB20・同場6連続足・当場準備済み確定15分EMA20を共通要求。T1は前現の上位方向保持、T2は最新の直前6本突破を登録し1〜3本の再テストで一度だけ消費する。現在足自身の突破を再テストにせず、終値水準失効と欠足で登録を切る。R1/R2はADX<20、中心が方向側にあることを要求する。\n\n"
    thresholds += "X0はTP250/SL125。X1/X2は固定TP250なし、SL125と期限を維持。順行通常出口は保有後の確定終値がEMA20の反対側または等号。反転は入口判断時SMA20固定目標で、中心越え新規も約定取消にせず同原行から返済要求。X2順行は建玉後の実最高/最低返済BBOから2ATR_eの単調線、反転は1ATR_e到達後0.5ATR_e床。買下丸め・売上丸め。入口判断時ATRを固定し、建玉前高安や将来値を混ぜない。\n\n"
    thresholds += "新規は要求+1価格時計秒以上・30秒以内、残り60分以上。期限15:35/翌05:50、300秒超正常板空白・EOF不足を区別。逆行の正しい条件は方向付き返済値幅d≤−125pt。"+G.link(study/"計画の表記補足.md", readme, "計画の表記補足")+"を参照する。\n\n"
    fixed_text = "## 表示固定ID\n\n各入口X0と、旧二期間の追加5pt後1取引平均の低い側が最大の一出口、同値候補ID順を保存する。11/4一場を順位に使わない。結果を見て追加候補を選ばず、表示目的の固定IDを採用候補と呼ばない。\n"
    fixed_text += G.table(["評価", "保存ID"], [[refs[cid], cid] for cid in report["表示固定ID"]])
    audit_readme, audit_paths = audits(study, readme)
    viewer = "## 入力・閲覧・再現\n\n"+G.link(study/"入力台帳.json", readme)+" / "+G.link(manifest_path, readme, "参照元00008台帳")+"\n\n"
    viewer += f"市場root：`{manifest['source_root']}`。Viewerのresource_rootは本repo。`path_base=catalog`でpnl_pathは一覧の親、market_pathは市場rootからの相対。原板は複製せず、Viewerは追加滑り0ptの表示固定IDだけを含む。\n\n"
    for name in ("一覧.resources.json", "固定候補_取引.csv", "固定候補_注文.csv", "全候補_場別.csv", "入力品質.json", "入口品質.json", "作業成果物.json", "Viewer照合.json"):
        if (study/name).exists():
            viewer += G.link(study/name, readme)+"\n\n"
    viewer += "集約の再表示：\n\n```powershell\npython -X utf8 scripts/テクニカル循環/レポート.py\n```\n\n数値再生は固定版の`検証.py --study 検証用保存先 --work 検証用作業先`。正式結果の上書き・固定後コード変更は拒否する。\n\n"
    viewer += "再現コード："+" / ".join(G.link(ROOT/"scripts/テクニカル循環"/name, readme) for name in ("入口.py", "検証.py", "運用.py", "入口検証.py", "合成検証.py", "レポート.py"))+"。\n\n"
    links = " / ".join(G.link(study/name, readme) for name in ("計画.md", "計画の表記補足.md", "条件.json", "固定.json", "結果.json"))
    summary = "# 試行00011：順行と反転のチャート構造と利益回収\n\n状態：固定24候補の集約保存済み。\n\n"+intro+links+" / "+G.link(setting_path, readme)+" / "+G.link(all_path, readme)+"\n\n"+conclusion+limits
    summary += findings(entries, values)+attention_note(study, readme)+stability_note(study, readme)+entry_table(entries)+fixed_text+operation_tables([values[cid] for cid in report["表示固定ID"]], values, refs, config, detailed=False)+audit_readme+viewer
    common = settings(rules)
    setting = "# 試行00011：設定と結果\n\n"+intro+conclusion+G.link(G.MASTER, setting_path, "コピー元の汎用表")+" / "+G.link(readme, setting_path)+" / "+G.link(all_path, setting_path)+"\n\n"
    setting += "## 手法×時間スケール\n\n51手法×9尺度を保持。共通準備だけの使用と実際の発動・出口をS明細で分ける。R01〜R24は複合運用で、指標単独効果ではない。未使用はデータ不存在を意味しない。RSI/数量は本試行の条件に使わない。\n\n"+G.matrix(catalog, setting_path, common)
    setting += "## 設定明細\n"+G.table(["設定", "手法/尺度", "短記", "閾値と役割", "適用評価"], [[s["設定ID"], "/".join(s["手法ID"])+"・"+"/".join(s["尺度ID"]), s["短記"], s["説明"], "・".join(s["適用評価"])] for s in common])
    setting += thresholds.replace(G.link(study/"計画の表記補足.md", readme, "計画の表記補足"), G.link(study/"計画の表記補足.md", setting_path, "計画の表記補足"))+definition_table
    setting += "各Rの全3期間の結果は"+G.link(all_path, setting_path)+"、正本は"+G.link(study/"結果.json", setting_path)+"。8入口の先着結果を出口へ共有しており、24の独立した入口成績ではない。\n\n"+limits
    audit_all, _ = audits(study, all_path)
    all_text = "# 試行00011：全候補結果\n\n"+intro+conclusion+G.link(readme, all_path)+" / "+G.link(setting_path, all_path)+"\n\n"+limits+definition_table
    all_text += thresholds.replace(G.link(study/"計画の表記補足.md", readme, "計画の表記補足"), G.link(study/"計画の表記補足.md", all_path, "計画の表記補足"))
    all_text += findings(entries, values)+attention_note(study, all_path)+stability_note(study, all_path)+entry_table(entries)+operation_tables([values[r["候補ID"]] for r in rules], values, refs, config)+audit_all
    sources = [Path(__file__), ROOT/"scripts/レポート/設定結果レポート.py", G.CATALOG, study/"計画.md", study/"計画の表記補足.md", study/"条件.json", study/"固定.json", study/"入力台帳.json", manifest_path, study/"結果.json"]
    sources += [ROOT/"scripts/テクニカル循環"/name for name in ("入口.py", "検証.py", "運用.py", "入口検証.py", "合成検証.py")]+audit_paths
    if (study/"注意経路診断.json").exists():
        sources.append(study/"注意経路診断.json")
    if (study/"安定性診断.json").exists():
        sources += [study/"安定性診断.json", study/"安定性診断.md", ROOT/"scripts/テクニカル循環/安定性診断.py"]
    for path, text in ((readme, summary), (setting_path, setting), (all_path, all_text)):
        path.write_text(text+G.provenance(sources, path), encoding="utf-8")
    return [readme, setting_path, all_path]


def main() -> None:
    """試行と任意の表示確認先を受け取り文書を生成する。

    引数: なし。--study/--outputを読む。
    返り値: None。生成先をJSONで出力する。
    """
    parser = argparse.ArgumentParser(description="00011の8入口と24運用を表示")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    study = args.study.resolve()
    print(json.dumps({"生成": [str(p) for p in run(study, (args.output or study).resolve())]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
