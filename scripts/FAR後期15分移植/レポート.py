"""80の固定済み小型正本だけを結び、日本語の正式帳票を生成する。"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MODES = ("F0", "P1", "T1")
METHODS = (("NK225_D164_15", "日中"), ("NK225_P164_06", "米国前"), ("NK225_U165_03", "米国後"))
BEGIN = "<!-- ルート担当の結果挿入欄_開始 -->"
END = "<!-- ルート担当の結果挿入欄_終了 -->"
STATUS_OLD = "**本記入時点は実装・人工確認の準備段階で、市場の損益結果は未記入。**"
STATUS_NEW = "**訂正版2の66場・主/追加1秒の結果を記入済み。全66場は既使用で、将来の安定利益は未確認。**"


def need(ok: bool, message: str) -> None:
    """必要な一致条件を検査し、不一致で停止する。

    引数: ok(bool)は検査結果、message(str)は日本語の原因。
    返り値: None。不一致はValueErrorを送出する。
    """
    if not ok:
        raise ValueError(message)


def sha(path: Path) -> str:
    """小型正本の保存バイト列のSHA256を求める。

    引数: path(Path)は市場原板ではない参照ファイル。
    返り値: strは十六進SHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    """小型JSON正本をUTF-8で読み、辞書であることを確認する。

    引数: path(Path)は明示された集計又は照合正本。
    返り値: dictは有限値のみのJSON本文。
    """
    value = json.loads(path.read_text(encoding="utf-8"))
    need(isinstance(value, dict), "JSONの最上位は辞書が必要")
    json.dumps(value, allow_nan=False)
    return value


def number(value: object) -> Decimal:
    """金額又は数量を有限の十進数へ変換する。

    引数: value(object)はJSONのint/float又は内部集計のDecimal。
    返り値: Decimalは比較・足算用の有限数。
    """
    need(type(value) in (int, float, Decimal) and math.isfinite(value), "有限な数値が必要")
    return Decimal(str(value))


def amount(value: object) -> str:
    """金額又は数量を日本語表の桁区切り文字列へ整形する。

    引数: value(object)は有限数値。
    返り値: strは不要な小数末尾を除いた表示値。
    """
    text = format(number(value), ",f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def rate(numerator: int, denominator: int) -> str:
    """利益後赤字の分子・分母を併記して表示する。

    引数: numerator(int)は赤字玉数、denominator(int)は正益を観測した玉数。
    返り値: strは割合又は分母0の判定不能表示。
    """
    return f"{numerator}/{denominator}（{100*numerator/denominator:.1f}%）" if denominator else "0/0（判定不能）"


def link(base: Path, path: Path, label: str) -> str:
    """試行文書から成果物への相対Markdownリンクを作る。

    引数: base(Path)は試行ディレクトリ、path(Path)は成果物、label(str)は表示名。
    返り値: strは相対リンク。
    """
    return f"[{label}](<{Path(os.path.relpath(path, base)).as_posix()}>)"


# ----------------------------------------
def verify_summary(result: dict, sessions: list[str], delay: int) -> None:
    """全66場の小型集計と場別の金額・数量・DDを相互確認する。

    引数: result(dict)は結果.json、sessions(list[str])は台帳順、delay(int)は追加秒。
    返り値: None。売買・指標・市場再生は行わない。
    """
    need(result["場数"] == 66 and result["全場既使用"] is True, "66既使用場の集計が必要")
    need(result["約定追加遅延秒"] == delay and set(result["比較"]) == set(MODES), "遅延又は比較案の差")
    rows = {(r["session"], r["mode"]): r for r in result["場別"]}
    need(len(rows) == len(result["場別"]) == 198, "場別198会計の欠落又は重複")
    need(set(rows) == {(s, m) for s in sessions for m in MODES}, "場別の対象集合差")
    for mode in MODES:
        total = result["比較"][mode]
        selected = [rows[s, mode] for s in sessions]
        need(all(r["open_quantity"] == 0 for r in selected), "未完結所有を正式帳票にできない")
        for key in ("gross_pnl_yen", "total_cost_yen", "commission_yen", "slippage_yen", "entry_quantity", "exit_quantity", "closed_lots", "winning_lots", "losing_lots", "flat_lots", "profit_flags", "flag_after_loss_pieces"):
            need(number(total[key]) == sum((number(r[key]) for r in selected), Decimal(0)), "場別と案別の差:"+mode+key)
        net = sum((number(r["net_pnl_yen"]) for r in selected), Decimal(0))
        need(number(total["費用後損益円"]) == net == number(total["gross_pnl_yen"])-number(total["total_cost_yen"]), "費用後会計の差")
        need(total["entry_quantity"] == total["exit_quantity"], "新規と返済数量の差")
        need(number(total["total_cost_yen"]) == 122*number(total["entry_quantity"]), "主費用122円/往復の差")
        need(number(total["同約定費用0pt損益円"]) == net+100*number(total["entry_quantity"]), "同約定0pt費用差")
        need(number(total["同約定費用10pt損益円"]) == net-100*number(total["entry_quantity"]), "同約定10pt費用差")
        need(total["closed_lots"] == total["winning_lots"]+total["losing_lots"]+total["flat_lots"], "完結玉分類の差")
        values = [number(r["net_pnl_yen"]) for r in selected]
        need((total["赤字場数"], total["黒字場数"], total["無取引又は同値場数"]) == (sum(v<0 for v in values), sum(v>0 for v in values), sum(v==0 for v in values)), "場数の分類差")
        cum = peak = dd = Decimal(0)
        daily = Counter()
        for session, row in zip(sessions, selected):
            dd = max(dd, number(row["max_drawdown_yen"]), peak-(cum+number(row["min_equity_yen"])))
            peak = max(peak, cum+number(row["equity_peak_yen"]))
            cum += number(row["net_pnl_yen"])
            daily[session[:10]] += number(row["net_pnl_yen"])
        need(number(total["最大DD円"]) == dd and dd >= 0, "保存場別によるDD結合差")
        need({d:number(v) for d,v in total["日別円"].items()} == dict(daily), "日別金額の差")
        need(total["赤字日数"] == sum(v<0 for v in daily.values()) and total["日数"] == len(daily), "日数分類の差")
        groups = result["FAR時間帯別"][mode]
        need(set(groups) <= {m for m,_ in METHODS}, "未登録のFAR時間枠")
        need(sum(number(r["損益円"]) for r in groups.values()) == net, "FAR時間枠別金額の差")
        need(sum(r["完結玉"] for r in groups.values()) == total["closed_lots"], "FAR時間枠別玉数の差")
        need(sum(r["新規枚数"] for r in groups.values()) == total["entry_quantity"], "FAR時間枠別数量の差")


def verify_proofs(result: dict, audit: dict, raw: dict, sessions: list[str], manifest_sha: str) -> dict:
    """独立会計と原板全玉照合を同じ66場の指紋へ結び付ける。

    引数: result/audit/raw(dict)は集計・独立会計・原板照合、sessions(list[str])は予定場、manifest_sha(str)は台帳指紋。
    返り値: dictは案別の全玉正益数・正益後赤字数。原板を読まない。
    """
    need(audit["成功"] is True and audit["不一致数"] == 0 and audit["場数"] == 66 and audit["会計数"] == 198, "独立会計未完了")
    need(audit["入力不変"] is True and audit["入力SHA256前"] == audit["入力SHA256後"], "独立会計の入力変化")
    need(set(audit["入力SHA256前"]) == {s+".json" for s in sessions}, "独立会計の場集合差")
    need(audit["集計コードSHA256"] == sha(HERE/"集計.py"), "独立会計が異なる集計版を参照")
    need(raw["成功"] is True and raw["不一致数"] == 0 and not raw["不一致"] and raw["新再生"] == 0, "原板照合未完了")
    need(raw["監査コードSHA256"] == sha(HERE/"原板照合.py"), "原板照合コード版の差")
    need(raw["全玉評価定義"] and manifest_sha in raw["正本SHA256"].values(), "全玉評価又は台帳指紋がない")
    rows = {r["場"]:r for r in raw["対象場"]}
    need(set(rows) == set(sessions) and len(rows) == len(raw["対象場"]) == 66, "全66場の原板照合が必要")
    sums = {m:Counter() for m in MODES}
    for session in sessions:
        row = rows[session]
        need(row["結果SHA256"] == audit["入力SHA256前"][session+".json"], "会計/原板の場結果指紋差")
        need(row["JSON本文走査回数"] == 1 and row["入力照合ファイル数"] == 6, "原板全行又は入力照合数の差")
        need(set(row["全玉費用後評価"]) == set(MODES), "全玉診断の案欠落")
        norm=row["利益床の独立規範"]
        need(set(norm)=={"P1","T1"}, "P1/T1の独立利益床監査が必要")
        norm_keys=("正常保有原行","正益後保有原行","利益床到達原行","125pt到達原行","返済義務原行","予約不足原行","予約不足数量")
        for mode in ("P1","T1"):
            counts=norm[mode]
            need(set(counts)==set(norm_keys) and all(type(counts[k]) is int and counts[k]>=0 for k in norm_keys), "独立利益床監査の件数型差")
            need(counts["予約不足原行"]==counts["予約不足数量"]==0, "同原行の全量返済予約が不足")
            need(counts["正常保有原行"]>=counts["正益後保有原行"]>=counts["利益床到達原行"], "独立床監査の保有件数順序差")
            need(max(counts["利益床到達原行"],counts["125pt到達原行"])<=counts["返済義務原行"]<=counts["利益床到達原行"]+counts["125pt到達原行"], "独立床監査の義務件数差")
            need(counts["正常保有原行"]>=len(row["全玉費用後評価"][mode]), "実玉があるのに独立床監査の原行がない")
            for key in norm_keys:
                sums[mode]["規範_"+key]+=counts[key]
        for mode in MODES:
            lots = row["全玉費用後評価"][mode]
            need(len({p["実玉ID"] for p in lots}) == len(lots), "全玉診断のID重複")
            for lot in lots:
                need(lot["残量"] == 0 and lot["最後全玉純額円"] is not None, "未完結又は未評価の玉")
                final = number(lot["最後全玉純額円"])
                need(final == number(lot["完結部分純額円"]), "完結額と最後全玉評価の差")
                first = lot["全玉初回正益"]
                if first is not None:
                    need(number(first["全玉純額円"]) > 0, "strict正益でない初回全玉旗")
                need(lot["全玉正益後に最後赤字"] is bool(first is not None and final<0), "全玉正益後赤字の差")
                summary = sums[mode]
                summary["玉数"] += 1
                summary["数量"] += lot["初回数量"]
                summary["損益"] += final
                summary["全玉正益"] += first is not None
                summary["全玉後赤字"] += bool(first is not None and final<0)
                summary["残玉正益"] += bool(lot["保存残玉旗"])
                summary["残玉後赤字"] += bool(lot["保存残玉旗"] and final<0)
                residual_first=lot["残玉初回正益"]
                need(bool(lot["保存残玉旗"]) == (residual_first is not None), "残玉初回正益の原板復元欠落")
                if residual_first is not None:
                    need(number(residual_first["残玉単価純額円"])>0, "残玉初回正益がstrict正でない")
                summary["残玉あり損益" if lot["保存残玉旗"] else "残玉なし損益"] += final
                summary["残玉なし赤字"] += bool(not lot["保存残玉旗"] and final<0)
                summary["残玉後赤字損益"] += final if lot["保存残玉旗"] and final<0 else 0
    pairs = (("完結玉","closed_lots"),("新規枚数","entry_quantity"),("費用後損益円","費用後損益円"),("片費用合計円","total_cost_yen"),("利益観測玉","利益観測済み完結玉"),("利益後赤字玉","利益観測後赤字玉"),("同約定0pt円","同約定費用0pt損益円"),("同約定10pt円","同約定費用10pt損益円"))
    for mode in MODES:
        total = result["比較"][mode]
        independent = audit["独立案別"][mode]
        for key, expected in pairs:
            need(number(independent.get(key, 0)) == number(total[expected]), "独立会計案別差:"+mode+key)
        for key, expected in (("玉数","closed_lots"),("数量","entry_quantity"),("損益","費用後損益円"),("残玉正益","利益観測済み完結玉"),("残玉後赤字","利益観測後赤字玉"),("残玉あり損益","残玉正益観測ありの損益円"),("残玉なし損益","残玉正益未観測の損益円"),("残玉なし赤字","残玉正益未観測の赤字玉"),("残玉後赤字損益","残玉正益観測後赤字の損益円")):
            need(number(sums[mode][key]) == number(total[expected]), "原板全玉と集計の差:"+mode+key)
    return sums


def verify_catalog(catalog: dict, sessions: list[str]) -> None:
    """Viewer一覧が全66場・全3案の198資源を持つことを確認する。

    引数: catalog(dict)は保存一覧、sessions(list[str])は台帳の場集合。
    返り値: None。Viewerへの接続は行わない。
    """
    rows = catalog["resources"]
    need(catalog["path_base"] == "catalog" and len(rows) == 198, "Viewer一覧198資源の差")
    need(len({r["id"] for r in rows}) == 198 and {(r["session"],r["method_id"]) for r in rows} == {(s,m) for s in sessions for m in MODES}, "Viewer一覧の重複又は欠落")


def verify_viewer(proof: dict, result_sha: str, catalog_sha: str) -> None:
    """完了した198資源のViewer照合を集計・一覧の指紋へ結ぶ。

    引数: proof(dict)は表示照合正本、result_sha/catalog_sha(str)は保存指紋。
    返り値: None。通信未完了を一致として扱わない。
    """
    need(proof["試行"] == 80 and proof["全件一致"] is True and proof["全資源検証完了"] is True, "Viewer照合未完了")
    need(proof["予定資源数"] == proof["数値取得完了資源数"] == len(proof["資源別"]) == 198, "Viewer数値APIの欠落")
    need(proof["不一致数"] == 0 and not proof["不一致"] and not proof["APIエラー"], "Viewerの数値差又は通信エラー")
    need(proof["入力不変"] is True and proof["入力SHA256前"] == proof["入力SHA256後"], "Viewer照合中の入力変化")
    need(proof["結果SHA256"] == result_sha and proof["一覧SHA256"] == catalog_sha, "Viewerが別の集計又は一覧を参照")


# ----------------------------------------
def context_for(paths: dict[str, Path]) -> dict:
    """明示された小型正本を読み、全ての入力結合を検査する。

    引数: paths(dict[str,Path])は試行・集計・照合・図の固定パス。
    返り値: dictは文章化に必要な要約と読取前指紋。市場原板や取引明細を読まない。
    """
    inputs = {k:v.resolve() for k,v in paths.items() if k != "study"}
    before = {k:sha(p) for k,p in inputs.items()}
    manifest = read_json(inputs["manifest"])
    sessions = [r["id"] for r in manifest["sessions"]]
    need(len(sessions) == len(set(sessions)) == 66, "固定台帳は重複のない66場が必要")
    data = {k:read_json(inputs[k]) for k in ("main","delay","raw_main","raw_delay","audit_main","audit_delay","viewer","viewer_delay","catalog","delay_catalog","revision")}
    revision=data["revision"]
    need(revision["試行"]==80 and revision["採用版"]==2 and revision["初版正式採用"] is False, "接続訂正版2の採用証拠が必要")
    need(revision["主結果SHA256"]==before["main"] and revision["追加1秒結果SHA256"]==before["delay"] and revision["訂正版入力台帳SHA256"]==before["manifest"], "訂正版の集計又は台帳指紋差")
    whole = {}
    for key, delay in (("main",0),("delay",1)):
        verify_summary(data[key], sessions, delay)
        whole[key] = verify_proofs(data[key],data["audit_"+key],data["raw_"+key],sessions,before["manifest"])
    verify_catalog(data["catalog"],sessions)
    verify_catalog(data["delay_catalog"],sessions)
    verify_viewer(data["viewer"],before["main"],before["catalog"])
    verify_viewer(data["viewer_delay"],before["delay"],before["delay_catalog"])
    need(inputs["figure"].suffix.lower() == ".svg" and "<svg" in inputs["figure"].read_text(encoding="utf-8"), "比較SVGが必要")
    need(before == {k:sha(p) for k,p in inputs.items()}, "小型正本の読取中変化")
    return {"paths":{**inputs,"study":paths["study"].resolve()},"inputs":before,"data":data,"whole":whole,"sessions":sessions}


def metrics_table(context: dict) -> str:
    """主結果と追加1秒の損益・損失・費用の比較表を作る。

    引数: context(dict)は確認済み帳票文脈。
    返り値: strはMarkdown表。
    """
    lines = ["| 約定 | 案 | 費用後損益円 | 最大DD円 | 最大場内含み損円 | 赤字場/66 | 赤字日/日数 | 完結玉/新規枚数 | 費用円 | 上位3場利益円 |", "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for key,title in (("main","次正常原行"),("delay","追加1秒")):
        for mode in MODES:
            r=context["data"][key]["比較"][mode]
            lines.append(f"| {title} | {mode} | {amount(r['費用後損益円'])} | {amount(r['最大DD円'])} | {amount(r['最大場内含み損円'])} | {r['赤字場数']}/66 | {r['赤字日数']}/{r['日数']} | {r['closed_lots']}/{amount(r['entry_quantity'])} | {amount(r['total_cost_yen'])} | {amount(r['上位3場利益円'])} |")
    return "\n".join(lines)


def profit_table(context: dict) -> str:
    """残玉旗と全玉旗の正益後赤字を別分母で表示する。

    引数: context(dict)は確認済み帳票文脈。
    返り値: strはMarkdown表と評価定義。
    """
    lines=["| 約定 | 案 | 残玉正益旗後の赤字玉/旗玉 | 全玉正益後の赤字玉/正益玉 | 正益旗後の赤字返済片 | 要求時正益→約定赤字片 | 保存floor飛越片 | その他の片 |", "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for key,title in (("main","次正常原行"),("delay","追加1秒")):
        for mode in MODES:
            r=context["data"][key]["比較"][mode]
            w=context["whole"][key][mode]
            causes=r["利益後赤字の内訳"]
            other=causes.get("対照の利益保護なし",0)+causes.get("費用又は部分配分等",0)
            lines.append(f"| {title} | {mode} | {rate(r['利益観測後赤字玉'],r['利益観測済み完結玉'])} | {rate(w['全玉後赤字'],w['全玉正益'])} | {r['flag_after_loss_pieces']} | {causes.get('要求時正益から約定悪化',0)} | {causes.get('利益床の飛越',0)} | {other} |")
    return "\n".join(lines)+"\n\n残玉旗は、その時点の残玉1枚あたり方向値差×10−122円がstrict正になった記録。全玉旗は、原板監査が約定を当行先に反映し、既返済部分の費用後確定額＋残量×（方向値差×10−122円）がstrict正になった記録。部分赤字返済が先行すれば両旗は異なる。赤字は完結玉の最終費用後損益で判定し、玉の率と返済片の原因件数を混ぜない。"


def decomposition_table(context: dict) -> str:
    """同じ実新規の出口差と参加・入口変更の差を分解表示する。

    引数: context(dict)は確認済み帳票文脈。
    返り値: strは差額が総差に一致するMarkdown表。
    """
    lines=["| 約定 | 比較 | 同実新規玉 | 同実新規の出口差円 | F0だけ玉/損益円 | 比較案だけ玉/損益円 | 共通参照の入口変更玉/残差円 | 総損益差円 |", "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for key,title in (("main","次正常原行"),("delay","追加1秒")):
        result=context["data"][key]
        for mode in ("P1","T1"):
            r=result["入口と出口の分解"][mode+"対F0"]
            exact=number(r["同じ実新規比較案損益円"])-number(r["同じ実新規F0損益円"])
            need(exact==number(r["同じ実新規出口差円"]), "同実新規の出口差不一致")
            diff=number(result["比較"][mode]["費用後損益円"])-number(result["比較"]["F0"]["費用後損益円"])
            exclusive=number(r["比較案だけ損益円"])-number(r["F0だけ損益円"])
            residual=diff-exact-exclusive
            need(r["同じ参照ID"] == r["同じ実新規"]+r["同参照だが新規時点又は枚数変更"], "共通参照の分解差")
            need(r["同じ参照ID"]+r["F0だけ"] == result["比較"]["F0"]["closed_lots"] and r["同じ参照ID"]+r["比較案だけ"] == result["比較"][mode]["closed_lots"], "参加玉数の分解差")
            need(r["同参照だが新規時点又は枚数変更"]>0 or residual==0, "入口変更のない共通参照に残差")
            lines.append(f"| {title} | {mode}−F0 | {r['同じ実新規']} | {amount(exact)} | {r['F0だけ']}/{amount(r['F0だけ損益円'])} | {r['比較案だけ']}/{amount(r['比較案だけ損益円'])} | {r['同参照だが新規時点又は枚数変更']}/{amount(residual)} | {amount(diff)} |")
    return "\n".join(lines)+"\n\n同実新規は同じ場・参照IDで方向、実新規価格、実新規時計、初回枚数が一致する玉。物理新規行まで同じとする定義ではない。総差＝同実新規出口差＋比較案だけ損益−F0だけ損益＋共通参照の入口変更残差。最後の残差には新規時点・枚数とその後の出口が含まれ、純粋な出口効果にしない。P1は入口資格が同じでも早期返済による余力・占有の差で参加が変わり得る。"


def time_table(context: dict) -> str:
    """日中・米国前後の指定手法別に両約定模型を表示する。

    引数: context(dict)は確認済み帳票文脈。
    返り値: strは時間枠別Markdown表。
    """
    lines=["| 約定 | 時間枠・元手法 | 案 | 完結玉 | 新規枚数 | 費用後損益円 | 費用円 |", "| --- | --- | --- | ---: | ---: | ---: | ---: |"]
    for key,title in (("main","次正常原行"),("delay","追加1秒")):
        for method,window in METHODS:
            for mode in MODES:
                r=context["data"][key]["FAR時間帯別"][mode].get(method,{})
                lines.append(f"| {title} | {window}・{method} | {mode} | {r.get('完結玉',0)} | {amount(r.get('新規枚数',0))} | {amount(r.get('損益円',0))} | {amount(r.get('費用円',0))} |")
    return "\n".join(lines)


def cost_table(context: dict) -> str:
    """同じ約定列の費用感応を追加1秒の別売買列から分ける。

    引数: context(dict)は確認済み帳票文脈。
    返り値: strは費用感応Markdown表。
    """
    lines=["| 約定列 | 案 | 滑り0pt・往復22円 | 滑り5pt・往復122円（主） | 滑り10pt・往復222円 |", "| --- | --- | ---: | ---: | ---: |"]
    for key,title in (("main","次正常原行"),("delay","追加1秒")):
        for mode in MODES:
            r=context["data"][key]["比較"][mode]
            lines.append(f"| {title} | {mode} | {amount(r['同約定費用0pt損益円'])} | {amount(r['費用後損益円'])} | {amount(r['同約定費用10pt損益円'])} |")
    return "\n".join(lines)+"\n\n各列は片道手数料11円を含む、既に得られた同じ約定列への費用差引。滑り0ptも手数料0ではない。追加1秒は要求時刻後1秒以降の次正常原行に約定を移した別の再生であり、同約定費用感応と区別する。"


def unflagged_table(context: dict) -> str:
    """残玉正益に届かなかった入口の損失寄与を独立に表示する。

    引数: context(dict)は確認済み帳票文脈。
    返り値: strは残玉旗定義による費用後損益の分解表。
    """
    lines=["| 約定 | 案 | 残玉正益観測あり損益円 | 残玉正益未観測損益円 | 未観測の赤字玉 | 観測後赤字玉の損益円 |", "| --- | --- | ---: | ---: | ---: | ---: |"]
    for key,title in (("main","次正常原行"),("delay","追加1秒")):
        for mode in MODES:
            r=context["data"][key]["比較"][mode]
            lines.append(f"| {title} | {mode} | {amount(r['残玉正益観測ありの損益円'])} | {amount(r['残玉正益未観測の損益円'])} | {r['残玉正益未観測の赤字玉']} | {amount(r['残玉正益観測後赤字の損益円'])} |")
    return "\n".join(lines)+"\n\nこの表は残玉単価の旗による分解で、全玉旗とは異なる。残玉が一度も費用後正益に届かなかった入口には正益起動の利益床が働く機会がなく、その寄与を正益後の取り逃しから分ける。現在条件で機会がなかったという診断であり、別の入口や出口でも防げない損失という断定ではない。"


def protection_table(context: dict) -> str:
    """原板から再構成した保護到達時の同原行全量予約件数を示す。

    引数: context(dict)は全66場の独立床監査を含む確認済み文脈。
    返り値: strは本体の未更新フィールドに依存しない監査表。
    """
    lines=["| 約定 | 案 | 正常保有の玉×原行 | 正益後の玉×原行 | 利益床到達 | 125pt到達 | 全量予約義務 | 予約不足の玉×原行/延べ枚数 |", "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for key,title in (("main","次正常原行"),("delay","追加1秒")):
        for mode in ("P1","T1"):
            row=context["whole"][key][mode]
            fields=[row["規範_"+k] for k in ("正常保有原行","正益後保有原行","利益床到達原行","125pt到達原行","返済義務原行")]
            lines.append("| "+" | ".join((title,mode,*(amount(v) for v in fields),str(row['規範_予約不足原行'])+"/"+str(row['規範_予約不足数量'])))+" |")
    return "\n".join(lines)+"\n\n全fill後の保有残量と独立した方向別最高幅を用い、残玉単価strict正益後に現在幅がmax(20pt,最高幅−保存D)以下、又は−125pt以下なら、当原行・当時計までに残量全ての返済要求があることを原板から確認する。既受理のpendingも全量なら認め、理由は問わない。部分fill後は済数を予約から引き、次原行の要求で過去の不足を補わない。本体の未更新の放置件数フィールド0は根拠に使わない。技法失敗の条件再計算、不正常板・未観測区間の保護達成はこの規範監査の対象外。"


def day_night_table(context: dict) -> str:
    """場別集計から昼夜別の損益・赤字場・数量を要約する。

    引数: context(dict)は確認済み帳票文脈。
    返り値: strは主・追加1秒の昼夜別Markdown表。
    """
    lines=["| 約定 | 場 | 案 | 費用後損益円 | 赤字場/対象場 | 新規枚数 |", "| --- | --- | --- | ---: | ---: | ---: |"]
    for key,title in (("main","次正常原行"),("delay","追加1秒")):
        for kind,label in (("Day","日中"),("Night","夜間")):
            for mode in MODES:
                rows=[r for r in context["data"][key]["場別"] if r["mode"]==mode and r["session"].endswith("_"+kind)]
                pnl=sum((number(r["net_pnl_yen"]) for r in rows),Decimal(0))
                lines.append(f"| {title} | {label} | {mode} | {amount(pnl)} | {sum(r['net_pnl_yen']<0 for r in rows)}/{len(rows)} | {sum(r['entry_quantity'] for r in rows)} |")
    return "\n".join(lines)


# ----------------------------------------
def normalize_status(settings: str) -> str:
    """設定文書の既知の準備段階表示だけを正式結果記入済みへ更新する。

    引数: settings(str)は既存の設定と結果.md全文。
    返り値: strは既知の冒頭状態文だけを正規化した全文。55×9表には触れない。
    """
    need((settings.count(STATUS_OLD),settings.count(STATUS_NEW)) in ((1,0),(0,1)), "設定文書の既知状態文が一意でない")
    return settings.replace(STATUS_OLD,STATUS_NEW)


def documents(context: dict, settings: str) -> tuple[str, str]:
    """確認済み要約からREADMEと55×9表の結果欄だけを構成する。

    引数: context(dict)は確認済み文脈、settings(str)は既存の設定と結果.md全文。
    返り値: tuple[str,str]は新READMEと結果欄だけ更新した設定文書。
    """
    paths=context["paths"]
    study=paths["study"]
    metrics=metrics_table(context)
    profit=profit_table(context)
    decomposition=decomposition_table(context)
    times=time_table(context)
    costs=cost_table(context)
    unflagged=unflagged_table(context)
    protection=protection_table(context)
    day_night=day_night_table(context)
    settings=normalize_status(settings)
    main=context["data"]["main"]["比較"]
    delayed=context["data"]["delay"]["比較"]
    positive="・".join(m for m in MODES if number(main[m]["費用後損益円"])>0)
    headline=("主費用で総損益がstrict正の案は"+positive+"。") if positive else "主費用で総損益がstrict正の案はなかった。"
    headline+="主のP1−F0は"+amount(number(main['P1']['費用後損益円'])-number(main['F0']['費用後損益円']))+"円、T1−P1は"+amount(number(main['T1']['費用後損益円'])-number(main['P1']['費用後損益円']))+"円。追加1秒による各案の総損益変化は"+"、".join(m+" "+amount(number(delayed[m]['費用後損益円'])-number(main[m]['費用後損益円']))+"円" for m in MODES)+"。"
    need(settings.count(BEGIN)==settings.count(END)==1 and settings.index(BEGIN)<settings.index(END), "結果挿入欄の境界差")
    start=settings.index(BEGIN)+len(BEGIN)
    finish=settings.index(END)
    inserted="\n## 正式集計結果\n\n"+metrics+"\n\n"+profit+"\n\n"+decomposition+"\n\n詳細と固定正本は[README](README.md)を参照。55×9表本体と設定IDは変更していない。\n"
    updated=settings[:start]+inserted+settings[finish:]
    refs="、".join(link(study,paths[k],label) for k,label in (("main","主結果"),("delay","追加1秒結果"),("raw_main","主・原板全玉照合"),("raw_delay","追加1秒・原板全玉照合"),("audit_main","主・独立会計"),("audit_delay","追加1秒・独立会計"),("viewer","主198資源Viewer照合"),("viewer_delay","追加1秒198資源Viewer照合")))
    readme=f"""# 00080：FAR後期三手法の15分移植と利益保護

2026-11-07。全66既使用場で、FARの現在状態を15分新規へ移すF0、連続利益保護を加えたP1、複数技法で入口も選別するT1を比較した。旧70%・125/250先着・待ち率50%等による棄却は行わず、費用後利益、損失の偏り、含み益消失を評価する。これは未使用期や将来の安定利益の確認ではない。

初版66場×主/追加1秒はNightの`ExtraAt`・`NightCoreStart`の接続誤りと、P05 Supplementへの`NightCoreStart`誤伝播により正式採用を停止した。元runtimeの`ExtraAt=USOpen+1800`・`NightCoreStart=0`へ合わせ、P05内部の`LegacyCoreStart`設定を保った接続訂正版2だけを以下の正式成績とする。仮説の変更として旧成績へ継ぎ足さず、初版の条件・ログを保持する。{link(study,paths['revision'],'接続訂正と採用指紋')}

## 起点と仮説

起点はFARの2026-10-28運用指定と00166の同値実装資料に載る3手法。日中はNK225_D164_15、米国前はNK225_P164_06、米国後はNK225_U165_03。2026-11-07に最新commit `cf0717daa1eed78759f78a428bce50129e7f705b`の小型資料と兄弟repoの純戦略実装を確認した。[研究方針](../../docs/議論/FAR後期三手法を15分判断へ移す研究方針.md)・[元00166](https://github.com/masayoshi4649/FutureAlgorithmResearch/blob/cf0717daa1eed78759f78a428bce50129e7f705b/アルゴリズム調査/00166_選定三手法のWeb実装/README.md)

元Sourceは全原行で進め、15分時点で生きている参照保有の方向・ID・残量を候補へ写す。過去に消えた通知を復活させず、将来の保有も使わない。新規の時点・実建値・費用・保護が変わるため、原研究と同じ売買列ではない。元資料の利益額を本試行へ合算していない。

仮説は、元の板・二市場支持・速度・価格帯に、複数尺度の方向、勢い改善、同時急変の除外を加え、利益保護を連続化すれば収益の偏りと正益後赤字を抑えられるというもの。一般的な指標説明や心理仮説と、この独自組合せの実測は区別する。

## 条件と入力

| 案 | 入口資格 | 出口 |
| --- | --- | --- |
| F0 | 定時のFAR参照有効玉 | 参照返済と共通安全返済。利益保護の対照 |
| P1 | F0と同じ資格 | 費用込み利益床、ATR追尾、技法失敗返済を追加 |
| T1 | F0候補を確定3/15分の複数技法で選別 | P1と同じ保護 |

NK225/TOPIXラージ原板と元1/5分入力を使用。SourceのEMA15/60・ATR12や公開遅延60秒は継承し、追加3/15分のEMA8/21、3分RSI14・MACD(12,26,9)・ATR14と区別する。Day09:00、Night17:15を飛ばし09:15/17:30以降15分ごとに新規判断する。米国09:30はAmerica/New_YorkでDST変換し、前後15分は静観、境界で返済。場末要求は15:35/05:50。定時は25/49枠。

数量は元の部分配分を保つ片側100micro上限の研究対照であり、実取引の推奨枚数ではない。1micro=10円/pt。片道手数料11円と滑り5ptで往復122円/枚。主約定は要求の物理原行より後にある最初の正常Last・正常BBOの原行で、同秒の後行も許す。買い新規Ask、売り新規Bid、買い玉返済Bid、売り玉返済Ask。別に追加1秒を比較した。

P1/T1は残玉の費用後現在益がstrict正で起動し、悪化余裕を含む20pt床を置く。幅は入口時3分ATR14の5pt切上げ、15..125pt、未知は125pt。既受理返済を延期せず、参照返済・時間枠切替・125pt逆行の共通保護も連続処理する。追加の足は確定・公開済みだけを使い、必要入力未知を0にしない。詳細は[固定計画](検証計画.md)、[条件](条件.json)、[入力台帳](入力台帳.json)、[設定IDと55×9表](設定と結果.md)。

## 費用後の結果

{headline}

{metrics}

最大DDは返済費用込みの全原行評価（現金＋未決済粗益−残玉片道61円）と場をまたぐ累積を結合する。最大場内含み損は残玉往復122円込みの保存最小値で、負符号を保持する。Viewerの未決済表示と同じ定義とは限らず、Viewer照合は全返済後の最終純額と約定を対象にする。上位3場利益は上位3場の損益合計であり、独立した将来再現性の指標ではない。

{link(study,paths['figure'],'比較図SVG')} · {link(study,paths['catalog'],'主Viewer一覧・198資源')} · {link(study,paths['delay_catalog'],'追加1秒Viewer一覧・198資源')}。主・追加1秒それぞれ198資源は保存約定・終数量・累積純損益の数値API照合済み。

## 利益後赤字

{profit}

{unflagged}

{protection}

原因の片分類は要求時正益からの約定悪化を先に、次に保存floor飛越、F0の保護なし、費用又は部分配分等へ分けた保存集計。F0のfloorは共通の−125pt逆行床で、追加利益床ではない。全玉旗の原板診断は別計算であり、元の残玉起動条件を書き換えない。旗から要求までの最大遅れは、この小型集計には保存されておらず未集計。0遅延とみなさない。

## 出口と参加の分解

{decomposition}

## 時間枠別

{day_night}

{times}

日別損益は主・追加1秒の結果JSON内「日別円」、昼夜別と全場の損益・品質は同「場別」を正本とする。時間枠の0玉は完結玉のない区分であり、技法単独の有効性や未使用期の0損益を意味しない。

## 費用と価格時計遅延

{costs}

## 照合と再現

{refs}。原板監査は全物理行を各場1回parseし、同値行を省略せず、時計欠損・場外・後退・Last不良・交差BBOを別判定して最初の約定可能行と方向別価格を照合した。残玉初回正益を返済fill前も観測して保存旗と一致確認し、全玉評価は当行全fill後に行う。独立会計と原板監査の各場結果SHA、台帳SHA、集計とViewerの結果・一覧SHAを生成前に照合した。[生成証拠](レポート生成証拠.json)に小型正本の指紋を保存する。取消時刻と取消理由の原板証明、画像の目視品質、実商品での約定可能性はこの数値照合の範囲外。

固定コードは[実行CLI](../../scripts/FAR後期15分移植/cmd/replay/main.go)、[Source](../../scripts/FAR後期15分移植/source.go)、[実会計](../../scripts/FAR後期15分移植/actual.go)、[技法](../../scripts/FAR後期15分移植/technical.go)。固定入力台帳と同じ実行物で、`replay -manifest <入力台帳.json> -out <新規結果先> -delay 0`、別出力へ`-delay 1`で再現する。兄弟repoの純strategy/rules/e01だけを依存し、実アプリ・設定・注文APIは起動しない。集計.py、集計確認.py、原板照合.py、表示照合.pyの順に別照合を行い、図示.pyの比較SVGを用意した後、レポート.pyの明示引数で`--run`、同引数で`--check`する。原板を再読する工程と小型正本だけを読む帳票生成を分ける。正確な読取パス・コードSHAは生成証拠を参照。

今回の正式実行は[並列CLI](../../scripts/FAR後期15分移植/cmd/batch/main.go)で時間順に事前生成した当時までの指標seedを16workerへ渡し、人工3場×2遅延と本物先頭2場で逐次実行との全文同値を確認した。

## 限界と次の問い

全66場は既使用で、2場の接続確認もこの内数。3案・2約定模型を新しい独立標本と数えない。選定済み手法の移植比較であり、後期原研究の全候補や今回未使用の技法を検証した意味ではない。原価格時計を受信時計の代理とし、次正常ラージ板へのmicro約定・一定滑りを仮定する。深さ消費、実注文遅延、実運用の通信・入力準備、資金・証拠金の制約を実証していない。

追加技法の次場carryは最後の処理時計までに確定公開された足だけで、場末Endへ架空にAdvanceせず、未確定の場末3/15分形成足を次場BeginSessionで破棄する。場末まで全足を確定させてcarryする条件とは次場の指標値・準備が異なり得るため、Endへの明示Advanceは別の派生条件となる。

利益床は次原行の価格飛越を防がず、残玉正益は全玉正益を保証しない。保護が大きい順行を短縮し費用を増やす可能性も、正益になる前の損失も残す。損益・DD・利益集中・追加1秒の変化と、同実新規の出口差を併せて判断し、未使用期間での安定性は別の固定条件で確認する。今回の数値だけで採用や安定利益を認定しない。79は未実行停止のまま、78までの固定成果物は変更していない。

源保有抽出の偏り等の未検証の論点と、定時の現在根拠・部分確定と残玉保護・正益前の技法否定を分けた次候補は、[共通知見と次の問い](../../docs/議論/FAR後期三手法の15分移植と利益保護の比較.md)を参照する。
"""
    return readme,updated


def generate(paths: dict[str, Path], check: bool = False) -> dict:
    """小型正本の確認後に帳票を生成又は保存同値確認する。

    引数: paths(dict[str,Path])は明示入力、check(bool)は書込なしの同値確認。
    返り値: dictは出力指紋・照合成否。55×9表と計画・コードは変更しない。
    """
    context=context_for(paths)
    study=context["paths"]["study"]
    setting_path=study/"設定と結果.md"
    original=setting_path.read_text(encoding="utf-8")
    readme,settings=documents(context,original)
    authorized=normalize_status(original)
    left=authorized.split(BEGIN)[0]
    right=authorized.split(END)[1]
    need(settings.split(BEGIN)[0] == left and settings.split(END)[1] == right, "結果欄外を変更")
    outputs={study/"README.md":readme,setting_path:settings}
    proof={"試行":80,"成功":True,"場数":66,"会計数":198,"入力SHA256":{str(context['paths'][k]):v for k,v in context['inputs'].items()},"入力パス":{k:str(v) for k,v in context['paths'].items()},"生成コードSHA256":sha(Path(__file__)),"設定結果欄外SHA256":hashlib.sha256((left+BEGIN+END+right).encode('utf-8')).hexdigest(),"出力SHA256":{p.name:hashlib.sha256(text.encode('utf-8')).hexdigest() for p,text in outputs.items()},"本処理の原板読取":0,"新再生":0}
    proof_path=study/"レポート生成証拠.json"
    need(context["inputs"] == {k:sha(context["paths"][k]) for k in context["inputs"]}, "文章構成中の正本変更")
    if check:
        need(all(p.exists() and p.read_bytes()==text.encode('utf-8') for p,text in outputs.items()), "保存帳票と再構成の差")
        need(read_json(proof_path)==proof, "保存生成証拠と再構成の差")
    else:
        for path,text in outputs.items():
            path.write_text(text,encoding="utf-8",newline="\n")
        proof_path.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8",newline="\n")
    return {"成功":True,"確認のみ":check,"出力SHA256":proof["出力SHA256"],"原板読取":0,"新再生":0}


# ----------------------------------------
def fixture(folder: Path) -> dict[str, Path]:
    """市場と無関係な66場198会計の小型人工正本を用意する。

    引数: folder(Path)は専用一時ディレクトリ。
    返り値: dict[str,Path]は帳票生成用の人工パス集合。
    """
    paths={"study":folder,"manifest":folder/"入力台帳.json","main":folder/"主結果.json","delay":folder/"追加1秒.json","raw_main":folder/"主原板.json","raw_delay":folder/"追加原板.json","audit_main":folder/"主会計.json","audit_delay":folder/"追加会計.json","viewer":folder/"Viewer.json","viewer_delay":folder/"追加Viewer.json","catalog":folder/"主一覧.json","delay_catalog":folder/"追加一覧.json","figure":folder/"比較.svg","revision":folder/"接続訂正.json"}
    sessions=[(date(2000,1,1)+timedelta(days=d)).isoformat()+"_"+kind for d in range(33) for kind in ("Day","Night")]
    save={"manifest":{"sessions":[{"id":s} for s in sessions]}}
    paths["manifest"].write_text(json.dumps(save["manifest"]),encoding="utf-8")
    for key,delay in (("main",0),("delay",1)):
        totals={}
        all_rows=[]
        raw_rows=[]
        per_method={}
        independent={}
        pins={s+".json":hashlib.sha256((s+str(delay)).encode()).hexdigest() for s in sessions}
        for mode in MODES:
            n=int(mode!="T1")
            net={"F0":78,"P1":-22,"T1":0}[mode]
            row={"gross_pnl_yen":net+122*n,"total_cost_yen":122*n,"commission_yen":22*n,"slippage_yen":100*n,"entry_quantity":n,"exit_quantity":n,"closed_lots":n,"winning_lots":int(net>0),"losing_lots":int(net<0),"flat_lots":0,"profit_flags":n,"flag_after_loss_pieces":int(net<0),"request_before_floor_violations":0,"net_pnl_yen":net,"max_drawdown_yen":max(0,-net),"min_equity_yen":min(0,net),"equity_peak_yen":max(0,net),"open_quantity":0}
            all_rows += [{**row,"session":s,"mode":mode} for s in sessions]
            total={k:v*66 for k,v in row.items() if k not in ("max_drawdown_yen","min_equity_yen","equity_peak_yen","open_quantity")}
            total.update({"費用後損益円":net*66,"最大DD円":max(0,-net*66),"最大場内含み損円":min(0,net),"赤字場数":66*int(net<0),"黒字場数":66*int(net>0),"無取引又は同値場数":66*int(net==0),"日数":33,"赤字日数":33*int(net<0),"日別円":{s[:10]:2*net for s in sessions},"上位3場利益円":3*net,"利益観測済み完結玉":n*66,"利益観測後赤字玉":66*int(net<0),"利益後赤字の内訳":{},"同約定費用0pt損益円":(net+100*n)*66,"同約定費用10pt損益円":(net-100*n)*66})
            total.update({"残玉正益観測ありの損益円":net*66,"残玉正益未観測の損益円":0,"残玉正益未観測の赤字玉":0,"残玉正益観測後赤字の損益円":min(0,net)*66})
            totals[mode]=total
            per_method[mode]={"NK225_D164_15":{"完結玉":n*66,"新規枚数":n*66,"損益円":net*66,"費用円":122*n*66}} if n else {}
            independent[mode]={"完結玉":n*66,"新規枚数":n*66,"費用後損益円":net*66,"片費用合計円":122*n*66,"利益観測玉":n*66,"利益後赤字玉":66*int(net<0),"同約定0pt円":(net+100*n)*66,"同約定10pt円":(net-100*n)*66}
        for session in sessions:
            groups={}
            for mode in MODES:
                net={"F0":78,"P1":-22}[mode] if mode!="T1" else 0
                groups[mode]=[{"実玉ID":"人工1","参照ID":"人工参照1","初回数量":1,"残量":0,"全玉初回正益":{"全玉純額円":10},"最後全玉純額円":net,"完結部分純額円":net,"全玉正益後に最後赤字":net<0,"保存残玉旗":True,"残玉初回正益":{"残玉単価純額円":10}}] if mode!="T1" else []
            norm={m:{"正常保有原行":int(m=="P1"),"正益後保有原行":int(m=="P1"),"利益床到達原行":int(m=="P1"),"125pt到達原行":0,"返済義務原行":int(m=="P1"),"予約不足原行":0,"予約不足数量":0} for m in ("P1","T1")}
            raw_rows.append({"場":session,"結果SHA256":pins[session+".json"],"JSON本文走査回数":1,"入力照合ファイル数":6,"全玉費用後評価":groups,"利益床の独立規範":norm})
        decomposition={}
        for mode in ("P1","T1"):
            common=66 if mode=="P1" else 0
            left=78*common
            right=-22*common
            decomposition[mode+"対F0"]={"同じ参照ID":common,"同じ実新規":common,"同参照だが新規時点又は枚数変更":0,"F0だけ":66-common,"比較案だけ":0,"同じ実新規F0損益円":left,"同じ実新規比較案損益円":right,"同じ実新規出口差円":right-left,"F0だけ損益円":78*(66-common),"比較案だけ損益円":0}
        save[key]={"場数":66,"全場既使用":True,"約定追加遅延秒":delay,"比較":totals,"入口と出口の分解":decomposition,"FAR時間帯別":per_method,"場別":all_rows}
        save["audit_"+key]={"成功":True,"不一致数":0,"場数":66,"会計数":198,"入力不変":True,"入力SHA256前":pins,"入力SHA256後":pins,"集計コードSHA256":sha(HERE/"集計.py"),"独立案別":independent}
        save["raw_"+key]={"成功":True,"不一致数":0,"不一致":[],"新再生":0,"監査コードSHA256":sha(HERE/"原板照合.py"),"全玉評価定義":"人工","正本SHA256":{str(paths['manifest']):sha(paths['manifest'])},"対象場":raw_rows}
    catalog={"path_base":"catalog","resources":[{"id":s+m,"session":s,"method_id":m} for s in sessions for m in MODES]}
    save["catalog"]=save["delay_catalog"]=catalog
    for key,value in save.items():
        paths[key].write_text(json.dumps(value,ensure_ascii=False),encoding="utf-8")
    proof={"試行":80,"全件一致":True,"全資源検証完了":True,"予定資源数":198,"数値取得完了資源数":198,"資源別":[{}]*198,"不一致数":0,"不一致":[],"APIエラー":[],"入力不変":True,"入力SHA256前":{},"入力SHA256後":{},"結果SHA256":sha(paths['main']),"一覧SHA256":sha(paths['catalog'])}
    paths["viewer"].write_text(json.dumps(proof,ensure_ascii=False),encoding="utf-8")
    proof=deepcopy(proof)
    proof["結果SHA256"],proof["一覧SHA256"]=sha(paths['delay']),sha(paths['delay_catalog'])
    paths["viewer_delay"].write_text(json.dumps(proof,ensure_ascii=False),encoding="utf-8")
    paths["revision"].write_text(json.dumps({"試行":80,"採用版":2,"初版正式採用":False,"主結果SHA256":sha(paths['main']),"追加1秒結果SHA256":sha(paths['delay']),"訂正版入力台帳SHA256":sha(paths['manifest'])},ensure_ascii=False),encoding="utf-8")
    paths["figure"].write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>',encoding="utf-8")
    (folder/"設定と結果.md").write_text(STATUS_OLD+"\n人工55×9表本体\n"+BEGIN+"\n未記入\n"+END+"\n固定設定末尾\n",encoding="utf-8")
    return paths


def self_test() -> dict:
    """人工正本だけで文章・境界不変・証拠不一致停止を確認する。

    引数: なし。
    返り値: dictは人工成功件数。本物結果・原板・Viewerの読取は0。
    """
    tests=0
    with tempfile.TemporaryDirectory(prefix="FAR80帳票人工_",dir=ROOT/"work") as temporary:
        paths=fixture(Path(temporary))
        context=context_for(paths)
        before={k:sha(v) for k,v in paths.items() if k!="study"}
        generate(paths)
        generate(paths,True)
        text=(paths["study"]/"README.md").read_text(encoding="utf-8")
        need("0/0（判定不能）" in text and "原研究と同じ売買列ではない" in text and "全66場は既使用" in text, "人工文章の必要説明欠落")
        need(before=={k:sha(v) for k,v in paths.items() if k!="study"}, "生成時の入力改変")
        updated=(paths["study"]/"設定と結果.md").read_text(encoding="utf-8")
        need(STATUS_NEW in updated and STATUS_OLD not in updated and updated.startswith(STATUS_NEW+"\n人工55×9表本体\n"), "設定の状態更新又は55×9表の保存差")
        tests+=2
        for kind in ("viewer_missing","viewer_hash","raw_missing","raw_hash","whole_net","whole_flag","audit_net","summary_dd","summary_fee","decomposition","norm_missing","norm_shortage"):
            broken=deepcopy(context)
            try:
                if kind.startswith("viewer"):
                    p=broken["data"]["viewer"]
                    if kind=="viewer_missing": p["数値取得完了資源数"]=197
                    else: p["結果SHA256"]="0"*64
                    verify_viewer(p,context["inputs"]["main"],context["inputs"]["catalog"])
                elif kind.startswith("summary"):
                    broken["data"]["main"]["比較"]["F0"]["最大DD円" if kind=="summary_dd" else "total_cost_yen"]+=1
                    verify_summary(broken["data"]["main"],context["sessions"],0)
                elif kind=="decomposition":
                    broken["data"]["main"]["入口と出口の分解"]["P1対F0"]["同じ実新規出口差円"]+=1
                    decomposition_table(broken)
                else:
                    raw=broken["data"]["raw_main"]
                    if kind=="raw_missing": raw["対象場"].pop()
                    elif kind=="raw_hash": raw["対象場"][0]["結果SHA256"]="0"*64
                    elif kind=="whole_net": raw["対象場"][0]["全玉費用後評価"]["F0"][0]["最後全玉純額円"]+=1
                    elif kind=="whole_flag": raw["対象場"][0]["全玉費用後評価"]["F0"][0]["全玉初回正益"]["全玉純額円"]=0
                    elif kind=="norm_missing": del raw["対象場"][0]["利益床の独立規範"]
                    elif kind=="norm_shortage": raw["対象場"][0]["利益床の独立規範"]["P1"]["予約不足原行"]=1
                    else: broken["data"]["audit_main"]["独立案別"]["F0"]["費用後損益円"]+=1
                    verify_proofs(broken["data"]["main"],broken["data"]["audit_main"],raw,context["sessions"],context["inputs"]["manifest"])
            except (ValueError,KeyError):
                tests+=1
            else:
                raise AssertionError("不一致を受理:"+kind)
        for kind in ("revision", "marker", "saved_text"):
            try:
                if kind=="revision":
                    value=read_json(paths["revision"])
                    value["採用版"]=1
                    paths["revision"].write_text(json.dumps(value,ensure_ascii=False),encoding="utf-8")
                    context_for(paths)
                elif kind=="marker":
                    documents(context,STATUS_OLD+BEGIN+BEGIN+END)
                else:
                    readme_path=paths["study"]/"README.md"
                    readme_path.write_text(text+"不正な後付け\n",encoding="utf-8")
                    generate(paths,True)
            except ValueError:
                tests+=1
            else:
                raise AssertionError("不一致を受理:"+kind)
            finally:
                if kind=="revision":
                    value["採用版"]=2
                    paths["revision"].write_text(json.dumps(value,ensure_ascii=False),encoding="utf-8")
                elif kind=="saved_text":
                    readme_path.write_text(text,encoding="utf-8",newline="\n")
    return {"成功":True,"人工テスト数":tests,"不一致数":0,"本物結果読取":0,"原板読取":0,"Viewer接続":0,"新再生":0}


def main() -> None:
    """既定は人工検証とし、明示引数のときだけ正式帳票を扱う。

    引数: CLIの--run/--check/--self-test(bool)、--study及び各正本(Path)。
    返り値: None。不一致は例外で停止し、人工時は本物の結果を読まない。
    """
    parser=argparse.ArgumentParser(description="80の小型正本から正式帳票を構成")
    actions=parser.add_mutually_exclusive_group()
    actions.add_argument("--run",action="store_true")
    actions.add_argument("--check",action="store_true")
    actions.add_argument("--self-test",action="store_true")
    parser.add_argument("--study",type=Path)
    for name in ("manifest","main","delay","raw-main","raw-delay","audit-main","audit-delay","viewer","viewer-delay","catalog","delay-catalog","figure","revision"):
        parser.add_argument("--"+name,type=Path)
    args=parser.parse_args()
    if not args.run and not args.check:
        print(json.dumps(self_test(),ensure_ascii=False))
        return
    if args.study is None or any(getattr(args,key) is None for key in ("raw_main","raw_delay","audit_main","audit_delay","viewer","figure")):
        parser.error("正式処理はstudy/raw-main/raw-delay/audit-main/audit-delay/viewer/figureの明示が必要")
    defaults={"manifest":args.study/"入力台帳.json","main":args.study/"主結果"/"結果.json","delay":args.study/"追加1秒"/"結果.json","catalog":args.study/"主結果"/"一覧.resources.json","delay_catalog":args.study/"追加1秒"/"一覧.resources.json","revision":args.study/"接続訂正.json","viewer_delay":args.study/"追加1秒Viewer照合.json"}
    paths={"study":args.study}
    for key in ("manifest","main","delay","raw_main","raw_delay","audit_main","audit_delay","viewer","viewer_delay","catalog","delay_catalog","figure","revision"):
        paths[key]=getattr(args,key) or defaults.get(key)
    print(json.dumps(generate(paths,args.check),ensure_ascii=False))


if __name__ == "__main__":
    main()
