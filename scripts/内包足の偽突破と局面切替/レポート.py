"""74の保存結果を表示する。入力・学習・先着・運用の再計算は行わない。"""

import argparse
from decimal import Decimal
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00074_内包足の偽突破確認と局面切替"
OLD = ROOT / "study/00073_直近の集中と方向効率を組み合わせる"
V5_PATH = ROOT / "scripts/レポート/カタログ版5.py"
SPEC = importlib.util.spec_from_file_location("内包足74の固定版5純描画", V5_PATH)
V5 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = V5
SPEC.loader.exec_module(V5)
POLICIES = ("Q0", "I0", "H0", "H1")
NEW = ("I0", "H0", "H1")
CONDITIONAL = ("Q0", "H0")
IMMEDIATE = ("I0", "H1")
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = {"学習": "時系列検査20場", "条件選択": "条件選択24場", "後続検査": "既使用後続2場"}
EVALUATIONS = {"Q0": "R01", "I0": "R02", "H0": "R03", "H1": "R04"}
SCHEMA_READY = True
EXPECTED_COUNTS = {"新fit": 0, "新分類器fit": 0, "新モデル": 0,
    "新独立測定": 0, "新運用数": 138, "保存参照運用数": 46, "Viewer資源": 184}
ORIGINS = ("保存Q0", "内包偽突破")
PAIRS = (("Q0", "I0"), ("Q0", "H0"), ("I0", "H1"), ("H0", "H1"))

# ----------------------------------------
def sha(path: Path) -> str:
    """保存出典の内容指紋を求める。

    引数: path(Path)は既存ファイル。
    返り値: strはSHA256。モデルを展開して評価しない。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path: Path) -> dict:
    """小型の正本JSONだけを読む。

    引数: path(Path)は結果・条件・証明等。
    返り値: dictは保存値。gzip・原板・教師個票を開かない。
    """
    return json.loads(path.read_text(encoding="utf-8"))


def cell(value: object) -> str:
    """表セルの区切りと改行をエスケープする。

    引数: value(object)は表示値。
    返り値: strは一行セル。Noneを数値0へ変えない。
    """
    return str(value).replace("|", "&#124;").replace("\n", "<br>")


def table(headers: list, rows: list) -> str:
    """列数をそろえたMarkdown表を作る。

    引数: headers(list[str])は見出し、rows(list[list])は行。
    返り値: strは表。異なる列数は例外にする。
    """
    if any(len(row) != len(headers) for row in rows):
        raise ValueError("74表示の表列数差")
    return "| " + " | ".join(headers) + " |\n| " + " | ".join(["---"] * len(headers)) + " |\n" + "".join(
        "| " + " | ".join(cell(value) for value in row) + " |\n" for row in rows) + "\n"


def money(value: object) -> str:
    """品質未確定のnullと0円を分けて表示する。

    引数: value(int|float|str|None)は保存額。
    返り値: strは円表記又はnull。非有限値は拒否する。
    """
    if value is None:
        return "null（品質・未解消等）"
    amount = Decimal(str(value))
    if not amount.is_finite():
        raise ValueError("74表示の金額非有限")
    return f"{amount:,.2f}"


def rate(value: float | None) -> str:
    """無約定の率と数値0を区別する。

    引数: value(float|None)は保存率。
    返り値: strは百分率又は分母0。率を再計算しない。
    """
    if value is None:
        return "null（分母0）"
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("74表示の率範囲差")
    return f"{100 * value:.2f}%"


def flag(value: bool | None) -> str:
    """保存真偽と目標達成を混同しない表示を返す。

    引数: value(bool|None)は保存フラグ。
    返り値: strは真・偽・未知。Falseを一律に未達と呼ばない。
    """
    if value is not None and type(value) is not bool:
        raise ValueError("74表示の真偽型差")
    return "未知" if value is None else "真" if value else "偽"


def link(path: Path, output: Path, label: str) -> str:
    """出力文書から既存出典への相対リンクを作る。

    引数: path/output(Path)は出典と文書、label(str)は表示名。
    返り値: strはMarkdownリンク。出典を複製しない。
    """
    relative = Path(os.path.relpath(path, output.parent)).as_posix()
    return "[" + label + "](" + relative + ")"


def mechanics(output: Path) -> str:
    """事前固定した価格順序・補助条件・保護・限界を説明する。

    引数: output(Path)は文書出力先。
    返り値: strは計画の説明。結果や心理の実測を捏造しない。
    """
    return ("## 価格パターンと複数技法の役割\n\n"
        "隣接A/I/BのIがAへstrict内包。買いはB.low<I.lowかつB.high<I.high、売りは鏡像。"
        "B後1〜3足の最初の終値が買いI.high超/売りI.low未満ならC。BをCへ兼用しない。"
        "C後の別足で買いclose<=B.low/売りclose>=B.highなら等号込み無効化し、復活させない。"
        "C.endは（予定−900秒,予定］、公開keyは実判断以下。同じCを次枠へ持ち越さず、各方向で新しいC/Bを選ぶ。足内の高安順序は推測しない。\n\n"
        "新HはF02>=0かつF03>0の3分FastKを要求。F01>0はDI順行、F01<0は反転候補として"
        "ADX差有効F52=1・F48<0・実方向15分CLVのF15>0を追加する。raw DI0は新H不採用。"
        "価格パターン自体を必ず反転と呼ばず、価格・勢い・上位方向/強弱・保護幅を別の役割として記録する。"
        "新しい量条件はない。両方向同時適格は入力不整合として停止する。\n\n"
        "新H適格なら優先し、なければ73Q0の保存純判断へfallback。旧の実注文・保有・損益を判断材料にしない。"
        "新H単独の支持へfallback全体の件数を流用しない。"
        + link(OLD / "設定と結果.md", output, "保存Q0の64特徴・閾値・既使用評価")
        + "は保存対照参照であり、今回その全閾値を再転記・再fitしない。\n\n"
        "## 注文と利益保護\n\n"
        "条件型Q0/H0は最新公開完全3分足の高安を凍結し、将来Lastのstrict突破で要求する。"
        "発動前反対端の等号込み否定とT+900取消を維持し、新パターンのI端を注文線へ置き換えない。"
        "即時型I0/H1は定時に要求する。両方式とも要求後1価格秒以上・後原行の最初正常BBOで買ask/売bid、"
        "新規TTL30秒。判断時刻へ約定を遡らせない。\n\n"
        "全方式で固定O49の連続保護。保存現在ATR14のD=clip(5*ceil(ATR/5),5,125)、損失も非緩和。"
        "正常返済BBOの現在費用後益strict正で利益旗/最低名目新規床。pending中のh/L/armは凍結する。"
        "micro代理10円/pt・片道11円＋滑り5pt、主往復122円。0/10ptは同じ約定への費用感応。"
        "名目床は費用後同値や黒字の保証ではない。250先着と実250到達・実回収も別に表示する。\n\n"
        "原典Chesler（Active Trader 2004年4月、[公開原記事PDF](https://www.peterlbrandt.com/wp-content/uploads/2016/06/Hikkake-Dan-Chesler.pdf)）の確認はprice-cross。終値確認・3分/15分・無効化・補助条件・fallbackは独自規約で、"
        "NK225短期や70%の実証を原典から移植しない。市場心理は仮説であり参加主体の実測ではない。\n\n")


def comparison_axes() -> str:
    """4政策を候補と注文方式の2軸に分ける。

    引数: なし。
    返り値: strは比較表。同入口の出口比較と誤読させない。
    """
    return ("## 比較の2×2\n\n" + table(["政策/評価", "定時の純候補", "注文方式", "今回の扱い"], [
        ["Q0/R01", "73Q0保存", "68条件発動", "保存46運用の参考"],
        ["I0/R02", "同じ73Q0保存", "49定時即時要求", "新46運用"],
        ["H0/R03", "新H適格優先・他は保存Q0", "68条件発動", "新46運用"],
        ["H1/R04", "H0と同じ純候補", "49定時即時要求", "新46運用"]])
        + "Q0→H0とI0→H1が新候補の比較、Q0→I0とH0→H1が注文方式の比較。"
        "後者は参加機会・新規時刻・価格も変わり、同じ入口での出口差ではない。"
        "新fit・新木・新独立測定は0。旧測定は同時計/同方向/ATR/D/条件/出口へ厳密結合し、"
        "独立回収合計を一枚戦略利益にしない。全66場既使用で新しい未使用評価ではない。\n\n")


def settings(context: dict) -> list:
    """新規則と旧保存判断の参照セルを版5へ対応させる。

    引数: context(dict)は旧条件metadataを持つ表示文脈。
    返り値: list[dict]は設定ID・手法尺度・短記・適用評価。旧64閾値を複製しない。
    """
    definitions = [
        ("P04", "m03", "A/I内包→B偽抜け→1..3足C終値確認", "R03/R04", "最初C固定、900秒窓、C後B反対端の等号込み無効化"),
        ("I07", "m03", "F02>=0 & F03>0", "R03/R04", "保存3分FastKの中央差と進行。未知を0へ補完しない"),
        ("I08", "m15", "F01>0順行/<0反転・rawDI0不採用", "R03/R04", "DIは役割を分け、価格パターンの名前と同一視しない"),
        ("I08", "m15", "反転:F52=1 & F48<0", "R03/R04", "15分ADX現前変化の有効と減速。水準閾値を追加しない"),
        ("P01", "m15", "反転:F15>0", "R03/R04", "候補方向に正規化した15分CLV。3分確認とは別の役割"),
        ("C07", ["m03", "m15"], "3分形/勢い×15分方向/強弱", "R03/R04", "複数技法の複合規約。独立票又は手法単独効果ではない"),
        ("I09", "m03", "保存ATR14/D5..125", "R01/R02/R03/R04", "旧現在ATRとDを継承。新計算しない"),
        ("C06", ["tick", "m03"], "現在122円strict起動・D非緩和追尾", "R01/R02/R03/R04", "利益旗/名目床と費用後の実回収を分ける"),
        ("E01", "tick", "250/125先着・主/非重複/支持", "R01/R02/R03/R04", "独立仮入口と実一枚の分母を分け、全H支持を流用しない"),
        ("E02", "tick", "最新3分高安Laststrict/反対端否定/T+900", "R01/R03", "68条件入口。新HのI端へ発動線を変えない"),
        ("E02", "tick", "定時要求→+1秒後行BBO/TTL30", "R02/R04", "49即時入口。入口差と出口差を混同しない"),
        ("M01", ["m03","m15"], "保存Q0の複合判断参照・新fit0", "R01/R02/R03/R04", "旧73の保存純判断だけをfallbackへ使う。新しい木や全閾値の転記はない"),
    ]
    rows = [{"設定ID": f"S{i:02d}", "手法ID": [method], "尺度ID": scale if isinstance(scale,list) else [scale], "短記": short,
        "結果短記": evaluation, "説明": description} for i,(method,scale,short,evaluation,description) in enumerate(definitions,1)]
    old_cells = sorted({(meta["method"], meta["scale"]) for meta in context["old_metadata"]})
    for method, scale in old_cells:
        rows.append({"設定ID": f"S{len(rows)+1:02d}", "手法ID": [method], "尺度ID": scale.split("+"),
            "短記": "保存Q0の対照/判断fallback参照", "結果短記": "R01/R02/R03/R04",
            "説明": "73の設定と結果への保存参照。今回この旧特徴を再計算又は単独検定しない"})
    return rows


def validate_result(result: dict) -> None:
    """全予定・由来・比較の分母と回収を保存値同士で復元照合する。

    引数: result(dict)は74正本又は人工辞書。
    返り値: None。不整合を拒否し、不明を数値0で補わない。
    """
    if result.get("試行") != 74 or result.get("全66場既使用") is not True or set(result["候補"]) != set(POLICIES):
        raise ValueError("74の4政策と既使用期間が必要")
    if any(type(result[key]) is not int or result[key] != expected for key,expected in EXPECTED_COUNTS.items()):
        raise ValueError("新fit/木/測定0・138運用・保存46の件数差")
    if len(result["評価場"]) != 46 or len(set(result["評価場"])) != 46:
        raise ValueError("評価46場の件数又は重複")
    if set(result["由来別"]) != set(POLICIES) or set(result["利益保護"]) != set(POLICIES):
        raise ValueError("由来と利益保護の政策集合差")
    for h,scheduled in zip(PERIODS,(740,888,74)):
        for p in POLICIES:
            item=result["候補"][p][h]
            e,o=item["入口"],item["運用"]
            if any(type(e[key]) is not int or e[key]<0 for key in ("候補","約定","250","間引き約定","間引き250")):
                raise ValueError("入口件数の型又は符号差")
            if sum(e["結果別"].values()) != e["候補"] or e["250"] != e["結果別"].get("250",0):
                raise ValueError("入口結果別の復元差")
            if e["約定"] != sum(e["結果別"].get(k,0) for k in ("250","125","期限","不足")):
                raise ValueError("入口の無取引と約定後結果の分離差")
            for win,n,field in (("250","約定","率"),("間引き250","間引き約定","間引き率")):
                if not 0<=e[win]<=e[n] or (e[field] is None)!=(e[n]==0) or e[n] and not math.isclose(e[field],e[win]/e[n],rel_tol=0,abs_tol=1e-12):
                    raise ValueError("先着率の分母又は無約定null差")
            wait,invalid=o["判断別"].get("待ち",0),o["判断別"].get("判定不能",0)
            conservative=wait+invalid+o["条件未約定"]
            if o["予定枠"]!=scheduled or sum(o["判断別"].values())!=scheduled or (o["待ち数"],o["判定不能"])!=(wait,invalid):
                raise ValueError("全予定・待ち・判定不能の復元差")
            if not 0<=conservative<=scheduled or not math.isclose(o["主待ち率"],wait/scheduled,rel_tol=0,abs_tol=1e-12) or not math.isclose(o["待ち率保守上限"],conservative/scheduled,rel_tol=0,abs_tol=1e-12) or o["活動適格"]!=(conservative*2<=scheduled):
                raise ValueError("全予定分母又は保守活動の差")
            if p in IMMEDIATE and (o["条件登録数"]!=0 or o["条件未約定"]!=0):
                raise ValueError("即時方式に条件登録又は未約定が混入")
            for cost in (0,5,10):
                if Decimal(str(o["完結観測額円"][str(cost)])) != Decimal(str(o["完結観測額円"]["0"]))-20*cost*o["完結数"]:
                    raise ValueError("同じ実約定の費用感応差")
                if (o["品質注意場"] or o["未解消"]) and o["全体確定額円"][str(cost)] is not None:
                    raise ValueError("品質注意又は未解消の確定null差")
            if sum(o["役割別完結"][r]["件数"] for r in ("順行","反転"))!=o["完結数"]:
                raise ValueError("DI実役割の件数復元差")
            if item["同時適格"]!=(e["70目標"] and o["活動適格"] and o["費用適格"]):
                raise ValueError("入口・活動・費用の同時条件差")
            origin=result["由来別"][p][h]
            if set(origin)!=set(ORIGINS) or sum(x["純候補"] for x in origin.values())!=e["候補"] or sum(x["実完結"] for x in origin.values())!=o["完結数"]:
                raise ValueError("由来別の候補又は実完結復元差")
            for x in origin.values():
                if x["純候補"]!=x["入口"]["候補"] or sum(x["役割別完結"].values())!=x["実完結"] or not isinstance(x["品質注意場の範囲"],str) or not x["品質注意場の範囲"]:
                    raise ValueError("由来別入口又は実役割の復元差")
            for key in ("約定","250"):
                if sum(x["入口"][key] for x in origin.values())!=e[key]:
                    raise ValueError("由来別の主入口復元差")
            for cost in ("0","5","10"):
                if sum((Decimal(str(x["費用別観測円"][cost])) for x in origin.values()),Decimal(0))!=Decimal(str(o["完結観測額円"][cost])):
                    raise ValueError("由来別観測額の復元差")
            protect=result["利益保護"][p][h]
            if sum(protect[k] for k in ("同値","有利費用負け","不利"))!=protect["旗後赤"] or (protect["利益旗"],protect["旗後赤"])!=(o["利益起動件数"],o["起動後赤字件数5"]):
                raise ValueError("利益旗又は赤字3分類の復元差")
            if sum(x["利益旗"] for x in origin.values())!=protect["利益旗"] or sum(x["旗後赤"] for x in origin.values())!=protect["旗後赤"]:
                raise ValueError("由来別利益旗又は赤字復元差")
        for left,right in PAIRS:
            comparison=result["比較"][left+"対"+right][h]
            pure,actual=comparison["純"],comparison["実"]
            if sum(pure.values())!=scheduled or pure["同方向"]+pure["左のみ"]+pure["反対切替"]!=result["候補"][left][h]["入口"]["候補"] or pure["同方向"]+pure["右のみ"]+pure["反対切替"]!=result["候補"][right][h]["入口"]["候補"]:
                raise ValueError("2×2の同枠純判断復元差")
            lo,ro=(result["候補"][p][h]["運用"] for p in (left,right))
            if (actual["左完結"],actual["右完結"])!=(lo["完結数"],ro["完結数"]) or actual["共通元枠同方向"]+actual["左のみ"]!=actual["左完結"] or actual["共通元枠同方向"]+actual["右のみ"]!=actual["右完結"]:
                raise ValueError("2×2の共通・追加・除外完結復元差")
            difference=sum((Decimal(str(actual[k]))*sign for k,sign in (("共通元枠差額5",1),("左のみ額5",-1),("右のみ額5",1))),Decimal(0))
            if difference!=Decimal(str(ro["完結観測額円"]["5"]))-Decimal(str(lo["完結観測額円"]["5"])):
                raise ValueError("共通/追加/除外額と全体差額の復元差")
            acquisition=comparison["取得差"]
            if acquisition["件数"]!=actual["共通元枠同方向"] or not 0<=actual["厳密同新規"]<=actual["共通元枠同方向"]:
                raise ValueError("取得差の同元枠同方向分母差")
            for key in ("実方向価格差pt","時間差秒"):
                values=acquisition[key]
                if set(values)!={"平均","中央値","最小","最大"} or any((value is None)!=(acquisition["件数"]==0) for value in values.values()):
                    raise ValueError("取得差の無対応null又は統計字段差")
                if acquisition["件数"] and not (values["最小"]<=values["平均"]<=values["最大"] and values["最小"]<=values["中央値"]<=values["最大"]):
                    raise ValueError("取得差統計の範囲差")
        for left,right in (("Q0","I0"),("H0","H1")):
            pure=result["比較"][left+"対"+right][h]["純"]
            if any(pure[key] for key in ("左のみ","右のみ","反対切替")):
                raise ValueError("同じ純候補の注文方式比較に方向差")
            if any(result["由来別"][left][h][origin]["純候補"]!=result["由来別"][right][h][origin]["純候補"] for origin in ORIGINS):
                raise ValueError("同じ純候補の注文方式比較に由来差")
        coverage=result["技法被覆"][h]
        if coverage["定時枠"]!=scheduled or coverage["適格方向"]!=coverage["順行適格"]+coverage["反転適格"] or sum(coverage["状態別"].values())!=coverage["形観測"]:
            raise ValueError("技法被覆の全予定又はDI役割復元差")
        if not 0<=coverage["形unique"]<=coverage["形観測"] or not 0<=coverage["準備済み"]<=scheduled:
            raise ValueError("形unique又は準備の分母差")
        if coverage["適格方向"]!=sum(coverage[k] for k in ("新H追加","新H同方向","新H反対切替")) or coverage["適格方向"]!=result["由来別"]["H0"][h]["内包偽突破"]["純候補"]:
            raise ValueError("新H由来と追加/再確認/反対切替の復元差")
    if result["採用"] != [p for p in NEW if all(result["候補"][p][h]["同時適格"] for h in PERIODS[:2])]:
        raise ValueError("新3政策の最終採用差")


def context_for() -> dict:
    """主結果・正式監査の成功後だけ表示文脈を構築する。

    引数: なし。
    返り値: dictは表示専用文脈。未確定段階では停止する。
    """
    if not SCHEMA_READY:
        raise RuntimeError("74主結果schemaの接続待ち。本物結果を開きません")
    names=("結果.json","保存物確認.json","固定.json","条件.json","検証計画.md","入力台帳.json","一覧.resources.json")
    paths=[STUDY/name for name in names]
    if any(not path.is_file() for path in paths):
        raise FileNotFoundError("74主と正式監査の成功後だけ表示できます")
    result,proof,fixed=read(paths[0]),read(paths[1]),read(paths[2])
    validate_result(result)
    if proof["全件一致"] is not True or proof["不一致数"]!=0 or proof["不一致"]!=[] or proof["結果SHA256"]!=sha(paths[0]) or result["固定SHA256"]!=sha(paths[2]):
        raise ValueError("74主・正式監査・固定のSHA結合差")
    old,old_proof=read(OLD/"結果.json"),read(OLD/"保存物確認.json")
    if old_proof["全件一致"] is not True or old_proof["不一致数"]!=0 or old_proof["結果SHA256"]!=sha(OLD/"結果.json"):
        raise ValueError("73保存Q0の成功証明差")
    if result["候補"]["Q0"]!=old["候補"]["Q0"]:
        raise ValueError("保存Q0の参考結果が変化")
    old_conditions=read(OLD/"条件.json")
    if len(old_conditions["特徴"])!=64:
        raise ValueError("保存Q0の64metadata参照差")
    sources=[*paths,OLD/"結果.json",OLD/"保存物確認.json",OLD/"条件.json",OLD/"設定と結果.md",Path(__file__),V5_PATH,V5.CATALOG,V5.MASTER]
    conditions=read(STUDY/"条件.json")
    if result["設定"]!=conditions:
        raise ValueError("主結果の設定と固定条件JSONの差")
    references=[{**x,"保存段階":kind} for kind,key in (("元学習木","元学習モデル"),("派生木","モデル")) for x in old[key] if x["policy"]=="Q0"]
    if len(references)!=6:
        raise ValueError("保存Q0の元3/派生3参照木が不足")
    for meta in references:
        path=ROOT/meta["path"]
        if sha(path)!=meta["SHA256"]:
            raise ValueError("保存Q0の参照木変更:"+meta["id"])
        sources.append(path)
    resources=read(STUDY/"一覧.resources.json")["resources"]
    if len(resources)!=184 or len({x["id"] for x in resources})!=184:
        raise ValueError("Viewer184の件数又は一意性差")
    return {"result":result,"proof":proof,"conditions":conditions,
        "old_metadata":old_conditions["特徴"],"references":references,"sources":list(dict.fromkeys(sources))}


def result_tables(context: dict) -> str:
    """入口・実運用・由来・比較・保護を異なる表へ表示する。

    引数: context(dict)は保存結果文脈。
    返り値: strは保存数値だけの表。新しい支持や群の待ち率を計算しない。
    """
    result=context["result"]
    entries,operations,costs,roles,origins,origin_costs,protections,supports=[],[],[],[],[],[],[],[]
    for p in POLICIES:
        for h in PERIODS:
            e,o=result["候補"][p][h]["入口"],result["候補"][p][h]["運用"]
            entries.append([p,PERIOD_NAMES[h],e["候補"],e["約定"],e["250"],rate(e["率"]),e["間引き約定"],e["間引き250"],rate(e["間引き率"]),e["日数"],e["場数"],flag(e["支持"]),flag(e["70目標"])])
            operations.append([p,PERIOD_NAMES[h],o["予定枠"],json.dumps(o["判断別"],ensure_ascii=False),o["待ち数"],o["判定不能"],o["条件登録数"],o["条件未約定"],rate(o["主待ち率"]),rate(o["待ち率保守上限"]),flag(o["活動適格"]),o["完結数"]])
            costs.append([p,PERIOD_NAMES[h],*[money(o["完結観測額円"][str(f)]) for f in (0,5,10)],*[money(o["全体確定額円"][str(f)]) for f in (0,5,10)],o["未解消"],json.dumps(o["品質注意場"],ensure_ascii=False)])
            supports.append([p,PERIOD_NAMES[h],o["完結数"],o["買い"],o["売り"],o["日数"],o["場数"],flag(o["費用支持"]),flag(o["費用適格"]),flag(result["候補"][p][h]["同時適格"])])
            for role in ("順行","反転"):
                x=o["役割別完結"][role]
                roles.append([p,PERIOD_NAMES[h],role,x["件数"],money(x["観測純額5"])])
            for name in ORIGINS:
                x=result["由来別"][p][h][name];y=x["入口"]
                origins.append([p,PERIOD_NAMES[h],name,x["純候補"],y["約定"],y["250"],rate(y["率"]),f'{y["間引き250"]}/{y["間引き約定"]}',rate(y["間引き率"]),y["日数"],y["場数"],flag(y["支持"]),x["実完結"],x["役割別完結"]["順行"],x["役割別完結"]["反転"]])
                origin_costs.append([p,PERIOD_NAMES[h],name,*[money(x["費用別観測円"][str(f)]) for f in (0,5,10)],x["利益旗"],x["旗後赤"],json.dumps(x["品質注意場"],ensure_ascii=False)])
            x=result["利益保護"][p][h]
            protections.append([p,PERIOD_NAMES[h],x["利益旗"],x["旗後赤"],x["同値"],x["有利費用負け"],x["不利"],x["先着250前の実退出"]])
    comparisons,actuals,acquisitions=[],[],[]
    for left,right in PAIRS:
        for h in PERIODS:
            x=result["比較"][left+"対"+right][h];p,a,g=x["純"],x["実"],x["取得差"]
            comparisons.append([left+"→"+right,PERIOD_NAMES[h],*[p[k] for k in ("同方向","左のみ","右のみ","反対切替","双方待機")]])
            actuals.append([left+"→"+right,PERIOD_NAMES[h],*[a[k] for k in ("左完結","右完結","共通元枠同方向","左のみ","右のみ")],*[money(a[k]) for k in ("共通元枠差額5","左のみ額5","右のみ額5")],a["厳密同新規"],money(a["厳密同新規出口差5"])])
            acquisitions.append([left+"→"+right,PERIOD_NAMES[h],g["件数"],*[money(g[k][stat]) if g[k][stat] is not None else "null（対応0）" for k in ("実方向価格差pt","時間差秒") for stat in ("平均","中央値","最小","最大")]])
    coverage=[]
    for h in PERIODS:
        x=result["技法被覆"][h]
        coverage.append([PERIOD_NAMES[h],*[x[k] for k in ("定時枠","準備済み","形観測","形unique","適格方向","順行適格","反転適格","新H追加","新H同方向","新H反対切替")],json.dumps(x["状態別"],ensure_ascii=False)])
    quality_scopes=sorted({result["由来別"][p][h][name]["品質注意場の範囲"] for p in POLICIES for h in PERIODS for name in ORIGINS})
    return ("## 入口の主・非重複・支持\n\n入口は独立仮約定の250/125先着。無取引を敗北にせず、無約定率はnull。非重複は群別計算で加算できない。"
        "支持は時系列検査で約定60/6日/10場/非重複20、選択・後続で20/3日/5場/非重複10。支持付き主率と非重複率の両方70%を入口条件とする。\n\n"
        +table(["政策","期間","純候補","仮約定","250","主率","薄化約定","薄化250","薄化率","日","場","支持","入口70条件"],entries)
        +"## 全予定の行動と活動\n\n主待ち=WAIT/全予定。保守=(WAIT＋判定不能＋条件登録後entryなし)/全予定。保有継続/処理中は非待ち。即時型の条件登録/条件未約定は0で、要求の未約定は実判断/注文と区別する。\n\n"
        +table(["政策","期間","全予定","判断別","待ち","判定不能","条件登録","条件未約定","主待ち率","保守上限","活動適格","実完結"],operations)
        +"## 実回収・費用と品質\n\n同じ約定の費用0/5/10感応。品質注意/未解消は全体確定nullを保ち、観測額を無条件確定としない。\n\n"
        +table(["政策","期間","観測0円","観測5円","観測10円","確定0円","確定5円","確定10円","未解消","品質注意場"],costs)
        +"費用支持は実完結/日/場/買/売が時系列で20/6/10/5/5、選択・後続で10/3/6/3/3。主5pt感応の政策全体確定が正で品質に注意がないことを別に要求する。\n\n"
        +table(["政策","期間","実完結","買","売","日","場","費用支持","費用適格","入口/活動/費用同時適格"],supports)
        +table(["政策","期間","DI実役割","実完結","観測5円"],roles)
        +"## 新H由来と保存Q0 fallback\n\n由来は定時の純候補の出典。仮先着・群内支持と実完結を別に表示する。fallback全体の支持を新H単独へ流用しない。由来別の待ち率は計算しない。\n\n"
        +table(["政策","期間","由来","純候補","仮約定","250","主率","薄化250/約定","薄化率","日","場","群内支持","実完結","順行完結","反転完結"],origins)
        +" / ".join(quality_scopes)+"。\n\n"
        +table(["政策","期間","由来","観測0円","観測5円","観測10円","利益旗","旗後赤","完結がある場の注意（部分）"],origin_costs)
        +"## 利益旗と赤字の価格会計\n\n旗後赤はarmかつpnl5<0。同値は実返済価格=実新規、有利費用負けは実方向価格差>0でも費用後負、不利は実方向価格差<0。要求後滑りの分類ではない。250前退出は保存された同入口対応の件数であり、先着成功を実利益としない。\n\n"
        +table(["政策","期間","利益旗","旗後赤","同値","有利費用負け","不利","先着250前実退出"],protections)
        +"## 2×2の純判断と実参加差\n\n共通元枠同方向でも入口時刻/価格は変わり得る。厳密同新規だけを別欄とし、部分群は再運用損益ではない。観測額帰属は各期間の品質を引き継ぐ。\n\n"
        +table(["左→右","期間","両採用同方向","左のみ","右のみ","反対切替","双方不採用"],comparisons)
        +table(["左→右","期間","左完結","右完結","共通元枠同方向","左のみ","右のみ","共通差額5円","左のみ5円","右のみ5円","厳密同新規","同新規出口差5円"],actuals)
        +"取得差は実完結の共通元枠・同方向だけ。実方向価格差=s×（右新規価格−左新規価格）で、正は右の取得が不利、負は右が有利。時間差=右entry_time−左entry_time。平均値から最適閾値や遅延を選ばない。\n\n"
        +table(["左→右","期間","件数","価格平均pt","価格中央値pt","価格最小pt","価格最大pt","時間平均秒","時間中央値秒","時間最小秒","時間最大秒"],acquisitions)
        +"## 技法の被覆と不成立\n\n同じ形の反復観測を含む形観測数とunique形を分ける。この被覆は純/仮約定/実完結の支持ではない。\n\n"
        +table(["期間","全予定","準備","形観測","unique形","適格方向","順行適格","反転適格","新H追加","同方向再確認","反対切替","状態別"],coverage))


def documents(context: dict) -> dict:
    """計画・版5全文と保存結果を二Markdownへ組み立てる。

    引数: context(dict)は正式又は人工の表示文脈。
    返り値: dict[str,str]はREADME/設定と結果。市場の処理を呼ばない。
    """
    detail = STUDY / "設定と結果.md"
    validate_result(context["result"])
    matrix = V5.matrix(V5.load_catalog(), detail, settings(context)).replace("未使用", "未使用・未検証")
    intro = comparison_axes() + mechanics(detail)
    tables = result_tables(context)
    settings_table=table(["設定ID","手法","尺度","短い閾値/状態","複合評価","役割・限定"],[
        [row["設定ID"],"/".join(row["手法ID"]),"/".join(row["尺度ID"]),row["短記"],row["結果短記"],row["説明"]] for row in settings(context)])
    reference_table=table(["保存段階","保存Q0の参照木","phase","保存先","SHA256"],[
        [meta["保存段階"],meta["id"],meta["phase"],link(ROOT/meta["path"],detail,"73保存木"),meta["SHA256"]] for meta in context["references"]])
    result=context["result"]
    headline=table(["政策","条件選択の主先着","非重複先着","実完結","観測5円","確定5円","主待ち率","保守上限"],[
        [p,f'{result["候補"][p]["条件選択"]["入口"]["250"]}/{result["候補"][p]["条件選択"]["入口"]["約定"]}',
        f'{result["候補"][p]["条件選択"]["入口"]["間引き250"]}/{result["候補"][p]["条件選択"]["入口"]["間引き約定"]}',
        result["候補"][p]["条件選択"]["運用"]["完結数"],money(result["候補"][p]["条件選択"]["運用"]["完結観測額円"]["5"]),
        money(result["候補"][p]["条件選択"]["運用"]["全体確定額円"]["5"]),rate(result["候補"][p]["条件選択"]["運用"]["主待ち率"]),
        rate(result["候補"][p]["条件選択"]["運用"]["待ち率保守上限"])] for p in POLICIES])
    decision="新政策の保存された同時適格: "+(" / ".join(result["採用"]) if result["採用"] else "なし（目標未達）")+"。既使用期間の記述結果であり、新しい未使用評価での達成証明ではない。\n\n"
    source_table="## 出典とSHA256\n\n"+table(["保存出典","SHA256"],[[link(path,detail,path.relative_to(ROOT).as_posix()),sha(path)] for path in context["sources"]])
    limits=("## 限界と再現\n\n新fit0・新モデル0・新独立測定0。旧測定の同時計・方向・ATR/D・条件・出口を照合して参照し、138新運用を独立測定合算で代用しない。"
        "全66場既使用、初20学習専用は新評価へ加えない。時系列20/条件選択24/後続2場は同じ相場の反復評価で、4政策と両方向は独立標本ではない。"
        "未使用セルは無効の実証でなく未使用・未検証。複合結果をP04/FastK/DI/ADX等の単独効果としない。"
        "新Hの支持、fallback支持、実一枚の回収、全予定活動を混同しない。確認待ちによる取得差、形の無効化と利益旗後赤字を別の記述として残す。"
        "11月5日DayとFutureAlgorithmResearchの新市場取得は0。条件を結果から選び直さず、次は固定後の未使用期間が必要。\n\n"
        "既存の開始/固定/結果/診断を持つ実行は再起動しない。既存handleと保存証拠を確認する。表示は成功監査に結合した結果JSONだけを読み、以下の後二行は市場や教師を再生しない。\n\n"
        "```powershell\nwork/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/内包足の偽突破と局面切替/検証.py --prepare\n"
        "work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/内包足の偽突破と局面切替/検証.py --preflight\n"
        "work/venvs/technical-tree/Scripts/python.exe -X utf8 work/内包足の偽突破と局面切替/人工を確認する.py\n"
        "work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/内包足の偽突破と局面切替/検証.py --freeze\n"
        "work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/内包足の偽突破と局面切替/検証.py --run\n"
        "work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/内包足の偽突破と局面切替/保存検証.py --run --viewer-url http://127.0.0.1:8092\n"
        "C:/Python314/python.exe -X utf8 scripts/内包足の偽突破と局面切替/レポート.py\n"
        "C:/Python314/python.exe -X utf8 scripts/内包足の偽突破と局面切替/レポート.py --check\n```\n\n")
    short=("# 00074：内包足の偽突破確認と局面切替\n\n内包足の偽突破後に反対端の終値確認を待ち、保存した短期勢い・上位方向/強弱で新候補を分ける。"
        "新H不成立は保存73Q0の純判断へfallbackする。原典のprice-crossに対し、終値確認・定時使用・補助条件は独自適応である。\n\n"
        +decision+comparison_axes()+"## 条件選択24場の要点\n\n"+headline
        +link(detail,STUDY/"README.md","全期間・由来・支持・費用・取得差と55×9表")+" / "
        +link(STUDY/"検証計画.md",STUDY/"README.md","事前計画")+" / "
        +link(STUDY/"一覧.resources.json",STUDY/"README.md","Viewer184資源")+"\n\n"
        +"主待ちと条件未約定込み保守上限、純/仮約定/実完結、利益旗と実回収を別の分母にする。"
        "全66場既使用であり新しい未使用評価ではない。各期の品質注意・未解消は確定nullを維持する。\n\n"
        +limits)
    return {"README.md":short,"設定と結果.md":"# 00074：設定と結果\n\n"+decision+intro
        +"## 手法×尺度・版5全文\n\n55手法×9尺度をコピー。新Hは既存P04の規約で版6を作らない。保存Q0のセルは保存対照参照、新計算と独立票へ数えない。\n\n"
        +matrix+"## 設定IDと複合評価\n\n"+settings_table+"## 保存対照の元3/派生3木参照\n\n新しいraw/派生木は0。旧Q0の全64閾値は73の設定と結果を参照し、ここへ再転記しない。\n\n"
        +reference_table+tables+limits+source_table}


def check_links(text: str, output: Path, generated: set) -> int:
    """生成予定の内部参照を検査する。

    引数: text(str)は本文、output(Path)は保存先、generated(set[Path])は同時生成先。
    返り値: intはリンク数。外部URLへアクセスしない。
    """
    count = 0
    for target in re.findall(r"\]\(([^)]+)\)", text):
        if target.startswith(("http:", "https:", "#", "mailto:")):
            continue
        path = (output.parent / unquote(target.split("#",1)[0])).resolve()
        if path not in generated and not path.exists():
            raise FileNotFoundError("74帳票リンク欠落:" + target)
        count += 1
    return count


def render(check: bool = False) -> dict:
    """正式成功後に二文書を表示又は保存版と同byte照合する。

    引数: check(bool)は書込みなし照合の指定。
    返り値: dictは文書SHA/サイズ/リンク数。schema未確定時は文脈取得で停止する。
    """
    context = context_for()
    before={path.relative_to(ROOT).as_posix():sha(path) for path in context["sources"]}
    output = documents(context)
    generated = {(STUDY / name).resolve() for name in output}
    reports, count = {}, 0
    catalog=V5.load_catalog()
    method_ids={row["id"] for row in catalog["methods"]}
    matrix_rows=[line for line in output["設定と結果.md"].splitlines() if line.startswith("| ") and len(line.split("|"))==13 and line.split("|")[1].strip() in method_ids]
    if len(matrix_rows)!=55 or {line.split("|")[1].strip() for line in matrix_rows}!=method_ids:
        raise ValueError("74の全55手法×9尺度の欠落又は重複")
    for name,text in output.items():
        count+=check_links(text,STUDY/name,generated)
    after={path.relative_to(ROOT).as_posix():sha(path) for path in context["sources"]}
    if before!=after:
        raise ValueError("74表示中の保存入力変更")
    for name,text in output.items():
        path, data = STUDY / name, text.encode("utf-8")
        if check:
            if not path.is_file() or path.read_bytes() != data:
                raise ValueError("74の保存文書と表示に差:" + name)
        else:
            path.write_bytes(data)
        reports[name] = {"bytes":len(data),"SHA256":hashlib.sha256(data).hexdigest()}
    return {"成功":True,"文書":reports,"内部リンク検査":count,"欠落":0,"版":5,"手法":55,"尺度":9,"入力前後不変":True,"参照木数":6,"新モデル":0}


def fixture(active: bool = False) -> dict:
    """正式保存物を読まず、ゼロ分母と由来復元を人工で作る。

    引数: active(bool)は各期に全政策同方向の1件を置く指定。
    返り値: dictは表示用の人工文脈。値は実結果ではない。
    """
    result={"試行":74,"全66場既使用":True,**EXPECTED_COUNTS,"評価場":[f"人工{i}" for i in range(46)],
        "候補":{},"由来別":{},"利益保護":{},"比較":{},"技法被覆":{},"採用":[]}
    n=int(active)
    entry={"候補":n,"約定":n,"250":n,"率":1.0 if n else None,"間引き約定":n,"間引き250":n,"日数":n,"場数":n,
        "間引き率":1.0 if n else None,"支持":False,"70目標":False,"結果別":{"250":1} if n else {}}
    for p in POLICIES:
        result["候補"][p],result["由来別"][p],result["利益保護"][p]={},{},{}
        for h,scheduled in zip(PERIODS,(740,888,74)):
            fees={"0":178.0*n,"5":78.0*n,"10":-22.0*n}
            action="条件登録" if p in CONDITIONAL else "買い新規要求"
            result["候補"][p][h]={"入口":deepcopy(entry),"同時適格":False,"運用":{
                "予定枠":scheduled,"判断別":{action:n,"待ち":scheduled-n},"待ち数":scheduled-n,"判定不能":0,
                "条件登録数":n if p in CONDITIONAL else 0,"条件未約定":0,"主待ち率":(scheduled-n)/scheduled,
                "待ち率保守上限":(scheduled-n)/scheduled,"活動適格":False,"費用適格":False,"完結数":n,
                "完結観測額円":fees,"全体確定額円":deepcopy(fees),"品質注意場":[],"未解消":0,
                "利益起動件数":n,"起動後赤字件数5":0,"買い":n,"売り":0,"日数":n,"場数":n,"費用支持":False,
                "役割別完結":{"順行":{"件数":n,"観測純額5":78.0*n},"反転":{"件数":0,"観測純額5":0.0}}}}
            origins={}
            for name in ORIGINS:
                belongs=name==("内包偽突破" if p in ("H0","H1") else "保存Q0")
                count=n if belongs else 0
                local_entry=deepcopy(entry) if belongs else {**deepcopy(entry),"候補":0,"約定":0,"250":0,"率":None,"間引き約定":0,"間引き250":0,"間引き率":None,"日数":0,"場数":0,"結果別":{}}
                origins[name]={"純候補":count,"入口":local_entry,"実完結":count,
                    "費用別観測円":deepcopy(fees) if belongs else {"0":0.0,"5":0.0,"10":0.0},
                    "利益旗":count,"旗後赤":0,"役割別完結":{"順行":count,"反転":0},"品質注意場":[],
                    "品質注意場の範囲":"同由来の完結がある場の全体品質注意。由来別の未解消を網羅しない。額は観測小計で、確定性は政策全体を参照"}
            result["由来別"][p][h]=origins
            result["利益保護"][p][h]={"利益旗":n,"旗後赤":0,"同値":0,"有利費用負け":0,"不利":0,"先着250前の実退出":n}
    for left,right in PAIRS:
        result["比較"][left+"対"+right]={}
        for h,scheduled in zip(PERIODS,(740,888,74)):
            stats={key:0.0 if active else None for key in ("平均","中央値","最小","最大")}
            result["比較"][left+"対"+right][h]={
                "純":{"同方向":n,"左のみ":0,"右のみ":0,"反対切替":0,"双方待機":scheduled-n},
                "実":{"左完結":n,"右完結":n,"共通元枠同方向":n,"左のみ":0,"右のみ":0,"共通元枠差額5":0.0,"左のみ額5":0.0,"右のみ額5":0.0,"厳密同新規":n,"厳密同新規出口差5":0.0},
                "取得差":{"件数":n,"実方向価格差pt":deepcopy(stats),"時間差秒":deepcopy(stats)}}
    for h,scheduled in zip(PERIODS,(740,888,74)):
        result["技法被覆"][h]={"定時枠":scheduled,"準備済み":n,"形観測":n,"形unique":n,"状態別":{"有効":1} if n else {},
            "適格方向":n,"順行適格":n,"反転適格":0,"新H追加":0,"新H同方向":n,"新H反対切替":0}
    references=[{"保存段階":kind,"id":"人工Q0_"+phase+kind,"phase":phase,"path":Path(__file__).relative_to(ROOT).as_posix(),"SHA256":sha(Path(__file__))}
        for kind in ("元学習木","派生木") for phase in ("W20","W30","F40")]
    return {"result":result,"old_metadata":[{"method":"I05","scale":"m15"},{"method":"P05","scale":"m03"},{"method":"P06","scale":"m03+m30"}],
        "references":references,"sources":[Path(__file__)]}


def self_test() -> dict:
    """schema未確定でも計画の比較軸・版5設定・null表示を人工検査する。

    引数: なし。
    返り値: dictは小型人工結果。本物入力/モデル/結果を読まない。
    """
    context = fixture()
    rows = settings(context)
    if len({row["設定ID"] for row in rows}) != len(rows) or len(rows) != 15:
        raise AssertionError("設定IDの一意性又は保存対照の参照差")
    detail=STUDY/"設定と結果.md"
    catalog=V5.load_catalog()
    text=V5.matrix(catalog,detail,rows)
    ids={row["id"] for row in catalog["methods"]}
    matrix_rows=[line for line in text.splitlines() if line.startswith("| ") and line.split("|")[1].strip() in ids]
    if len(matrix_rows)!=55 or any(len(line.split("|"))!=13 for line in matrix_rows):
        raise AssertionError("全55×9の不足")
    used={row.split("|")[1].strip():row for row in matrix_rows}
    if any("S"+f"{index:02d}" not in used[method] for index,method in ((1,"P04"),(2,"I07"),(3,"I08"),(5,"P01"),(6,"C07"),(7,"I09"),(8,"C06"),(9,"E01"),(10,"E02"))):
        raise AssertionError("版5の使用セルへ設定IDが転記されない")
    if used["P06"].count("保存Q0の対照/判断fallback参照")!=2:
        raise AssertionError("保存参照の複合時間尺度が分解されない")
    if rate(None)==rate(0) or money(None)==money(0) or flag(False)!="偽":
        raise AssertionError("null/0/偽の表示差")
    if any(phrase not in comparison_axes() for phrase in ("Q0→H0", "I0→H1", "Q0→I0", "H0→H1")):
        raise AssertionError("2×2比較の混同")
    if "I端を注文線へ置き換えない" not in mechanics(detail) or "新H単独の支持へfallback全体" not in mechanics(detail):
        raise AssertionError("入口又は由来支持の説明不足")
    for active in (False,True):
        c=fixture(active)
        validate_result(c["result"])
        output=documents(c)
        generated={(STUDY/name).resolve() for name in output}|{(STUDY/"一覧.resources.json").resolve()}
        for name,body in output.items():
            check_links(body,STUDY/name,generated)
    for field in ("新モデル","新独立測定"):
        bad=deepcopy(context["result"]);bad[field]=1
        try:validate_result(bad)
        except ValueError:pass
        else:raise AssertionError("新計算件数の誤値を受理")
    bad=deepcopy(context["result"]);bad["候補"]["H0"]["学習"]["運用"]["品質注意場"]=["人工注意"]
    try:validate_result(bad)
    except ValueError:pass
    else:raise AssertionError("品質注意の確定額を受理")
    bad=deepcopy(context["result"]);bad["由来別"]["H0"]["学習"]["内包偽突破"]["純候補"]=1
    try:validate_result(bad)
    except ValueError:pass
    else:raise AssertionError("新H支持の分母混入を受理")
    links=check_links(text+mechanics(detail),detail,{detail.resolve()})
    return {"成功":True,"テスト件数":12,"内部リンク検査":links,"正式入力読取":False,"schema接続完了":SCHEMA_READY,"fit":0,"市場再生":False}


def main() -> None:
    """純表示CLIの人工・通常表示・同byte検査を選ぶ。

    引数: なし。CLIは--self-test/--check。
    返り値: None。schema接続前は正式表示を明示拒否する。
    """
    parser=argparse.ArgumentParser(description="74の保存結果だけを二MDへ表示する")
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument("--self-test",action="store_true")
    mode.add_argument("--check",action="store_true")
    args=parser.parse_args()
    print(json.dumps(self_test() if args.self_test else render(args.check),ensure_ascii=False))


if __name__=="__main__":
    main()
