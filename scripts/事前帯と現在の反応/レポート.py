"""75の成功済み小型正本から二文書を純描画する。市場や教師を再計算しない。"""

from __future__ import annotations

import argparse
from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00075_事前帯の外保持と内回帰を判別"
OLD = ROOT / "study/00073_直近の集中と方向効率を組み合わせる"
PREVIOUS_PATH = ROOT / "scripts/内包足の偽突破と局面切替/レポート.py"
SPEC = importlib.util.spec_from_file_location("事前帯75の固定74純表示", PREVIOUS_PATH)
PREVIOUS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PREVIOUS
SPEC.loader.exec_module(PREVIOUS)
V5 = PREVIOUS.V5
table, rate, money, flag, link = PREVIOUS.table, PREVIOUS.rate, PREVIOUS.money, PREVIOUS.flag, PREVIOUS.link
POLICIES = ("Q0", "O0", "P0", "P1")
NEW = ("O0", "P0", "P1")
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = {"学習": "時系列検査20場", "条件選択": "条件選択24場", "後続検査": "既使用後続2場"}
PAIRS = (("Q0", "O0"), ("O0", "P0"), ("P0", "P1"))
COUNTS = {"新fit": 0, "新分類器fit": 0, "新モデル": 0, "新独立測定": 0,
          "新運用数": 138, "保存参照運用数": 46, "Viewer資源": 184}
PURE_GROUPS = ("同方向", "左のみ", "右のみ", "反対切替", "双方待機")
EXTERNAL = ROOT / "docs/議論/外部再調査/事前のセッション参照帯と当日の反応を分ける.md"


def sha(path: Path) -> str:
    """表示の保存入力を内容SHAで識別する。

    引数: path(Path)は既存ファイル。
    返り値: strはSHA256。価格やgzipを開かない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """結果・条件・成功証明の小型JSONを読む。

    引数: path(Path)は三正本のいずれか。
    返り値: dictは保存内容。正式生成以外からは呼ばない。
    """
    return json.loads(path.read_text(encoding="utf-8"))


def _count(value: object) -> int:
    """保存件数の整数型と非負性を検査する。

    引数: value(object)は件数。
    返り値: intは元件数。不正なら例外。
    """
    if type(value) is not int or value < 0:
        raise ValueError("75の件数は非負整数が必要です")
    return value


def _entry(value: dict) -> None:
    """主先着と非重複先着の分母・nullを検査する。

    引数: value(dict)は保存入口集計。
    返り値: None。無取引と125敗北の混同を拒否する。
    """
    for name in ("候補", "約定", "250", "間引き約定", "間引き250", "日数", "場数"):
        _count(value[name])
    for count in value["結果別"].values():
        _count(count)
    if sum(value["結果別"].values()) != value["候補"] or value["結果別"].get("250", 0) != value["250"]:
        raise ValueError("75入口結果別の復元差")
    if sum(value["結果別"].get(k, 0) for k in ("250", "125", "期限", "不足")) != value["約定"]:
        raise ValueError("75未約定と約定後の先着を混同しています")
    for win, denominator, field in (("250", "約定", "率"), ("間引き250", "間引き約定", "間引き率")):
        if not 0 <= value[win] <= value[denominator] or (value[field] is None) != (value[denominator] == 0):
            raise ValueError("75先着の分母又はnull差")
        if value[denominator] and not math.isclose(value[field], value[win] / value[denominator], abs_tol=1e-12, rel_tol=0):
            raise ValueError("75保存先着率の差")
    if value["間引き約定"] > value["約定"] or type(value["支持"]) is not bool or type(value["70目標"]) is not bool:
        raise ValueError("75非重複又は支持の型差")


def validate_result(result: dict) -> None:
    """全予定・費用・形成・比較の保存集計を相互照合する。

    引数: result(dict)は75正本又は人工辞書。
    返り値: None。不明を補完せず、不整合なら例外。
    """
    if result.get("試行") != 75 or result.get("全66場既使用") is not True or set(result["候補"]) != set(POLICIES):
        raise ValueError("75政策集合又は既使用期間の差")
    if any(type(result[k]) is not int or result[k] != v for k, v in COUNTS.items()):
        raise ValueError("75新計測/学習0又は運用件数の差")
    if len(result["評価場"]) != 46 or len(set(result["評価場"])) != 46:
        raise ValueError("75評価46場の差")
    if set(result["利益保護"]) != set(POLICIES) or set(result["比較"]) != {a + "対" + b for a, b in PAIRS}:
        raise ValueError("75保護又は比較の政策集合差")
    for period, scheduled in zip(PERIODS, (740, 888, 74)):
        for policy in POLICIES:
            item = result["候補"][policy][period]
            entry, operation = item["入口"], item["運用"]
            _entry(entry)
            for key in ("予定枠", "待ち数", "判定不能", "条件登録数", "条件未約定", "完結数", "未解消"):
                _count(operation[key])
            for value in operation["判断別"].values():
                _count(value)
            wait = operation["判断別"].get("待ち", 0)
            invalid = operation["判断別"].get("判定不能", 0)
            conservative = wait + invalid + operation["条件未約定"]
            if operation["予定枠"] != scheduled or sum(operation["判断別"].values()) != scheduled or (wait, invalid) != (operation["待ち数"], operation["判定不能"]):
                raise ValueError("75全予定と判断別の復元差")
            if not 0 <= conservative <= scheduled or not math.isclose(operation["主待ち率"], wait / scheduled, abs_tol=1e-12, rel_tol=0) or not math.isclose(operation["待ち率保守上限"], conservative / scheduled, abs_tol=1e-12, rel_tol=0) or operation["活動適格"] != (conservative * 2 <= scheduled):
                raise ValueError("75主待ち又は保守活動の分母差")
            if policy in NEW and (operation["条件登録数"] or operation["条件未約定"]):
                raise ValueError("75即時政策に条件入口が混入")
            for fee in (0, 5, 10):
                observed = Decimal(str(operation["完結観測額円"][str(fee)]))
                if not observed.is_finite() or observed != Decimal(str(operation["完結観測額円"]["0"])) - 20 * fee * operation["完結数"]:
                    raise ValueError("75同約定費用感応の差")
                fixed = operation["全体確定額円"][str(fee)]
                if (operation["品質注意場"] or operation["未解消"]) and fixed is not None:
                    raise ValueError("75品質注意/未解消の確定null差")
                if fixed is not None and not Decimal(str(fixed)).is_finite():
                    raise ValueError("75確定額の非有限値")
            roles = operation["役割別完結"]
            if sum(_count(roles[r]["件数"]) for r in ("順行", "反転")) != operation["完結数"] or sum((Decimal(str(roles[r]["観測純額5"])) for r in roles), Decimal(0)) != Decimal(str(operation["完結観測額円"]["5"])):
                raise ValueError("75実役割の件数又は観測額復元差")
            protect = result["利益保護"][policy][period]
            for value in protect.values():
                _count(value)
            if sum(protect[k] for k in ("同値", "有利費用負け", "不利")) != protect["旗後赤"] or (protect["利益旗"], protect["旗後赤"]) != (operation["利益起動件数"], operation["起動後赤字件数5"]):
                raise ValueError("75利益旗と赤字3分類の復元差")
            if protect["旗後赤"] > protect["利益旗"] or protect["利益旗"] > operation["完結数"] or protect["先着250前の実退出"] > min(entry["250"], operation["完結数"]):
                raise ValueError("75旗又は250前退出の分母差")
            if item["同時適格"] != (entry["70目標"] and operation["活動適格"] and operation["費用適格"]):
                raise ValueError("75同時適格の復元差")
            if policy == "Q0":
                continue
            coverage = result["技法被覆"][policy][period]
            for key in ("定時枠", "準備済み", "形観測", "形unique", "現在active観測", "適格方向", "順行", "反転", "採用形unique", "基本適格形成観測", "位置除外形成観測"):
                _count(coverage[key])
            if coverage["定時枠"] != scheduled or not 0 <= coverage["準備済み"] <= scheduled or sum(coverage["理由別"].values()) != scheduled or sum(coverage["状態別"].values()) != coverage["形観測"]:
                raise ValueError("75native準備又は形成状態の復元差")
            if coverage["形unique"] > coverage["形観測"] or coverage["採用形unique"] > coverage["適格方向"] or coverage["適格方向"] != entry["候補"] or coverage["順行"] + coverage["反転"] != entry["候補"] or sum(coverage["形成別採用"].values()) != entry["候補"]:
                raise ValueError("75形成反復/unique又は純役割の分母差")
            if coverage["位置除外形成観測"] > coverage["基本適格形成観測"]:
                raise ValueError("75位置除外形成の分母差")
            for field in ("基本不適格理由観測", "位置除外理由観測"):
                for count in coverage[field].values():
                    _count(count)
            age = coverage["採用k経過秒"]
            if set(age) != {"平均", "中央値", "最小", "最大"} or any((v is None) != (entry["候補"] == 0) for v in age.values()):
                raise ValueError("75採用k経過の採用0/null又は項目差")
            if entry["候補"] and (any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in age.values()) or not age["最小"] <= age["平均"] <= age["最大"] or not age["最小"] <= age["中央値"] <= age["最大"]):
                raise ValueError("75採用k経過の数値範囲差")
            repeat = _count(coverage["同形成最大反復枠"])
            if (repeat == 0) != (entry["候補"] == 0) or repeat > entry["候補"]:
                raise ValueError("75同形成反復の純候補分母差")
            formations = result["形成別"][policy][period]
            if set(formations) != {"T", "R"} or sum(x["純候補"] for x in formations.values()) != entry["候補"] or sum(x["実完結"] for x in formations.values()) != operation["完結数"]:
                raise ValueError("75T/R形成別の候補又は完結復元差")
            for kind, value in formations.items():
                _entry(value["入口"])
                if value["純候補"] != value["入口"]["候補"] or value["純候補"] != coverage["形成別採用"].get(kind, 0) or value["形unique"] > value["純候補"] or sum(value["役割別完結"].values()) != value["実完結"]:
                    raise ValueError("75形成の純/先着/実役割分母差")
            for key in ("約定", "250"):
                if sum(x["入口"][key] for x in formations.values()) != entry[key]:
                    raise ValueError("75形成別の主先着復元差")
            for fee in ("0", "5", "10"):
                if sum((Decimal(str(x["費用別観測円"][fee])) for x in formations.values()), Decimal(0)) != Decimal(str(operation["完結観測額円"][fee])):
                    raise ValueError("75形成別の観測額復元差")
        for left, right in PAIRS:
            comparison = result["比較"][left + "対" + right][period]
            pure, actual = comparison["純"], comparison["実"]
            if any(key not in PURE_GROUPS for key in pure) or sum(pure.values()) != scheduled:
                raise ValueError("75同枠純比較の全予定復元差")
            for value in pure.values():
                _count(value)
            le, re = (result["候補"][p][period] for p in (left, right))
            if pure.get("同方向", 0) + pure.get("左のみ", 0) + pure.get("反対切替", 0) != le["入口"]["候補"] or pure.get("同方向", 0) + pure.get("右のみ", 0) + pure.get("反対切替", 0) != re["入口"]["候補"]:
                raise ValueError("75純追加/除外/反対変更の復元差")
            for key in ("準備共通", "左準備のみ", "右準備のみ"):
                _count(comparison[key])
            if sum(comparison[k] for k in ("準備共通", "左準備のみ", "右準備のみ")) > scheduled:
                raise ValueError("75native準備比較の分母差")
            if left in NEW and comparison["準備共通"] + comparison["左準備のみ"] != result["技法被覆"][left][period]["準備済み"]:
                raise ValueError("75左準備の復元差")
            if comparison["準備共通"] + comparison["右準備のみ"] != result["技法被覆"][right][period]["準備済み"]:
                raise ValueError("75右準備の復元差")
            if left == "P0" and (pure.get("右のみ", 0) or pure.get("反対切替", 0) or comparison["左準備のみ"] or comparison["右準備のみ"]):
                raise ValueError("75P0/P1の同準備・同方向又はWAITに矛盾")
            lo, ro = le["運用"], re["運用"]
            if actual["左完結"] != lo["完結数"] or actual["右完結"] != ro["完結数"] or actual["共通元枠同方向"] + actual["左のみ"] != actual["左完結"] or actual["共通元枠同方向"] + actual["右のみ"] != actual["右完結"] or not 0 <= actual["厳密同新規"] <= actual["共通元枠同方向"]:
                raise ValueError("75共通/追加/除外実完結の復元差")
            change = Decimal(str(actual["共通元枠差額5"])) - Decimal(str(actual["左のみ額5"])) + Decimal(str(actual["右のみ額5"]))
            if change != Decimal(str(ro["完結観測額円"]["5"])) - Decimal(str(lo["完結観測額円"]["5"])):
                raise ValueError("75実参加帰属と全体差額の復元差")
    if result["採用"] != [p for p in NEW if all(result["候補"][p][h]["同時適格"] for h in PERIODS[:2])]:
        raise ValueError("75保存採用政策の差")


# ----------------------------------------
# 表の設定IDと固定条件。旧Q0の使用セルは参照として残し、旧閾値を複写しない。

def settings(context: dict) -> list[dict]:
    """新しい帯・複合条件と保存参考セルを版5へ対応させる。

    引数: context(dict)は条件と表示用小型文脈。
    返り値: list[dict]は一意な設定IDの使用セル。未使用セルを採用へ変えない。
    """
    definitions = [
        ("P03", ["tick", "m30", "session"], "正常Last帯/OR30・前収録全区間", "R02/R03/R04", "m30/sessionは観測帯の集約区間。旧3分/30分足OHLC又は公式全sessionOHLCではなく、3分反応はP04/P10へ分ける"),
        ("P04", "m03", "外保持T:端+5以上の終値2本", "R02/R03/R04", "両端鏡像。同じ端の外側を維持している間だけ有効"),
        ("P10", "m03", "外試行→3足内f→3足内別足k", "R02/R03/R04", "内回帰Rはf反対端のstrict終値確認。最初fを固定し否定/期限で消費"),
        ("I07", "m03", "F02>=0 & F03>0", "R02/R03/R04", "3分FastK中央差と進行、未知を0へ補完しない"),
        ("P05", "m03", "F07>0", "R02/R03/R04", "実方向終値変化。F03と関連する価格加工で独立票ではない"),
        ("I08", "m15", "T:F01>0/F51=F52=1/F47>=0.20/F48>=0", "R02/R03/R04", "DIとADX。F47=ADX/100なので0.20はADX20、20を直接比較しない"),
        ("I08", "m15", "R:F01>0又は逆向F52=1/F48<0", "R02/R03/R04", "同方向Rは順行、逆方向Rは反転。raw DI0は不採用"),
        ("P01", "m15", "逆向R:F15>0", "R02/R03/R04", "実方向15分CLV。反転確認の補助で独立した将来情報ではない"),
        ("C07", ["m03", "m15"], "固定端反応×勢い×上位方向/強弱", "R02/R03/R04", "価格形成T/RとDI実役割を分ける"),
        ("P01", ["tick", "m03"], "Last/E*は前提線strict外・P1距離<=D", "R02/R03/R04", "P1のみ0<s(E*-line)<=D。Rのみ算術中央への余地>=250。実約定価格ではない"),
        ("I09", "m03", "保存ATR14/D5..125", "R01/R02/R03/R04", "現ATRの5pt切上げD。新指標計算なし"),
        ("C06", ["tick", "m03"], "現在122円strict起動・非緩和追尾", "R01/R02/R03/R04", "pending中凍結・名目新規床。費用後黒字を保証しない"),
        ("E01", "tick", "250/125先着・主/非重複/支持", "R01/R02/R03/R04", "先着と実回収/全予定活動を区別"),
        ("E02", "tick", "新3政策:定時要求→+1秒後行BBO/TTL30", "R02/R03/R04", "旧Q0は保存68条件入口。注文も異なるためQ0対O0を帯単独効果としない"),
    ]
    result = [{"設定ID": f"S{i:02d}", "手法ID": [method], "尺度ID": scale if isinstance(scale, list) else [scale],
               "短記": short, "結果短記": evaluation, "説明": explanation}
              for i, (method, scale, short, evaluation, explanation) in enumerate(definitions, 1)]
    cells = context["conditions"]["保存参考セル"]
    if not cells or any(set(item) != {"method", "scale"} for item in cells):
        raise ValueError("75条件の保存参考セルmethod/scaleが必要です")
    for method, scale in sorted({(item["method"], item["scale"]) for item in cells}):
        result.append({"設定ID": f"S{len(result) + 1:02d}", "手法ID": [method], "尺度ID": scale.split("+"),
                       "短記": "保存参考Q0・旧73設定参照", "結果短記": "R01",
                       "説明": "旧保存純判断の使用セル。今回の新規則/量票へ再利用せず全64閾値は旧73へリンク"})
    return result


def mechanics(output: Path) -> str:
    """事前帯・形成・価格位置・執行の固定規約を説明する。

    引数: output(Path)はリンクを持つ文書の出力先。
    返り値: strは条件説明。原典を収益実証へ読み替えない。
    """
    return ("## 帯と公開時計\n\n正常BBOかつ有限正Lastだけの観測OHLC。Day[08:45,15:40)、Night[17:00,翌05:55)の半開区間で、公式セッション高安・引け板寄せ・受信時計ではない。"
        "2観測以上、開始/終了端の空白と正常観測間の最大空白が全て300秒以下を要求する。H=Lは既知の平坦帯として保存し、反応戦略では対象外WAIT。"
        "O0は当場最初1800秒だけを集約し、最初に終端へ達した価格時計/原行で公開する。公開前に価格や被覆を参照しない。"
        "P0/P1は直前収録の異種場・同実限月・前end<現startを要求し、終了境界timerで公開、line=None。前帯不良を古いgood帯へ代替しない。"
        "週末等の収録空白は古さを保存し、直前公式市場セッションの保証とはしない。当場全区間の帯を当日extractへ渡さない。\n\n"
        "## 外保持T・内回帰RとDI実役割\n\n上端d=+1/下端d=-1、q=d(C-K)、buffer5ptで鏡像。Tは外側q>=5の完全隣接終値2本、以後も外側維持中だけ有効。"
        "Rは同じ外試行の最後外足後1〜3足の最初q<=-5をfに固定し、f後1〜3の別足で内側維持かつ実方向へf反対端を終値でstrict突破したkを確認する。"
        "f後の内側逸脱/期限、k後の内側逸脱/前提線否定で消費し、都合のよいfへの交換や同試行の復活をしない。"
        "ORに使った足は反応へ兼用せず、帯end以降に開始する足だけを使う。既知の欠足/不正はreset、未来・同秒後行を除外した後で判定する。"
        "有効な形は次の定時にも残し、uniqueと反復観測を分ける。適格集合の最新k、同keyならTを優先する。\n\n"
        "全候補はF02>=0・F03>0・F07>0と非零DI。TはF01>0、F51=F52=1、F47>=0.20、F48>=0。F47はADX/100、従って0.20がADX20に相当する。"
        "RのF01>0は順行、F01<0はF52=1・F48<0・F15>0を追加して反転とする。価格形成Rが常に運用反転になるわけではない。"
        "F03とF07は関連する価格加工で、独立票として数えない。旧Q0以外では出来高を採否に使わず、b/rの古い量を現在反応へ流用しない。\n\n"
        "## 判断気配の位置と連続保護\n\nE*は当時買ask/売bid、将来約定ではない。最新LastとE*の両方が前提線の実方向strict外にあることを要求する。"
        "P1のみ0<s(E*-line)<=D、Rのみs(M-E*)>=250を追加する。M=(H+L)/2は算術中央で、POC/value areaとは呼ばない。Tにはこの帯から250pt先の目標を定義しない。"
        "P0/P1は同準備で、P1純方向はP0同方向又は待機。実一枚の建玉占有は変わるため実完結の包含を要求しない。\n\n"
        "新3政策は定時即時要求→1価格秒以上・後行の正常BBO、TTL30秒。旧Q0は保存68条件入口である。全政策でO49の非緩和連続追尾、現在返済BBO費用後益strict正で利益旗と最低名目新規床、pending中h/L/arm凍結。"
        "現3分ATR14からD=clip(5ceil(ATR/5),5,125)。ラージBBOによるmicro代理1枚10円/pt、片道11円＋滑り5ptで主往復122円。0/10ptは同一約定への費用感応。名目床は費用後黒字の保証ではない。\n\n"
        + link(EXTERNAL, output, "事前帯と反応の原典・心理仮説と独自規約の区別")
        + "。原典は今回の2本/3本、300秒、NK225短期の70%を実証していない。心理は参加者の直測ではない。\n\n")


def comparison_axes() -> str:
    """保存参考・帯変更・位置条件の比較範囲を分ける。

    引数: なし。
    返り値: strは4政策と比較の限定。
    """
    return ("## 比較の分離\n\n" + table(["政策/評価", "候補と帯", "注文", "扱い"], [
        ["Q0/R01", "73保存Q0", "保存68条件入口", "旧46運用の保存参考"],
        ["O0/R02", "当場OR30×外保持/内回帰×複数技法", "49即時", "新46運用"],
        ["P0/R03", "前収録の終了済み帯×同じ反応/補助条件", "49即時", "新46運用"],
        ["P1/R04", "P0＋前提距離、Rのみ中央余地", "49即時", "新46運用"]])
        + "Q0→O0は候補/準備/注文も異なる保存参考比較。O0→P0は帯の範囲・公開時刻・準備被覆を含む比較で、値だけの単独効果ではない。P0→P1は同準備で位置/余地条件の有無。新規則はQ0へfallbackしない。\n\n")


# ----------------------------------------
# 保存集計の表示。未来ラベルは結果説明だけに使い、候補入力へ返さない。

def result_tables(context: dict) -> str:
    """入口・実回収・形成・準備差・位置除外を別の分母で表示する。

    引数: context(dict)は保存結果の文脈。
    返り値: strは小型正本だけの表。価格集約や群別運用を再実行しない。
    """
    result = context["result"]
    entries, activities, costs, support, roles, protection = [], [], [], [], [], []
    coverage, reasons, diagnostics, formations, formation_costs = [], [], [], [], []
    for policy in POLICIES:
        for period in PERIODS:
            label = PERIOD_NAMES[period]
            item = result["候補"][policy][period]
            e, o = item["入口"], item["運用"]
            entries.append([policy, label, e["候補"], e["約定"], e["250"], rate(e["率"]),
                            e["間引き約定"], e["間引き250"], rate(e["間引き率"]), e["日数"], e["場数"], flag(e["支持"]), flag(e["70目標"])])
            activities.append([policy, label, o["予定枠"], json.dumps(o["判断別"], ensure_ascii=False), o["待ち数"], o["判定不能"],
                               o["条件登録数"], o["条件未約定"], rate(o["主待ち率"]), rate(o["待ち率保守上限"]), flag(o["活動適格"]), o["完結数"]])
            costs.append([policy, label, *[money(o["完結観測額円"][str(f)]) for f in (0, 5, 10)],
                          *[money(o["全体確定額円"][str(f)]) for f in (0, 5, 10)], o["未解消"], json.dumps(o["品質注意場"], ensure_ascii=False)])
            support.append([policy, label, o["完結数"], o["買い"], o["売り"], o["日数"], o["場数"], flag(o["費用支持"]), flag(o["費用適格"]), flag(item["同時適格"])])
            for role in ("順行", "反転"):
                value = o["役割別完結"][role]
                roles.append([policy, label, role, value["件数"], money(value["観測純額5"])])
            value = result["利益保護"][policy][period]
            protection.append([policy, label, *[value[k] for k in ("利益旗", "旗後赤", "同値", "有利費用負け", "不利", "先着250前の実退出")]])
            if policy not in NEW:
                continue
            x = result["技法被覆"][policy][period]
            coverage.append([policy, label, *[x[k] for k in ("定時枠", "準備済み", "形観測", "形unique", "現在active観測", "適格方向", "順行", "反転", "採用形unique", "基本適格形成観測", "位置除外形成観測")]])
            reasons.append([policy, label, json.dumps(x["理由別"], ensure_ascii=False), json.dumps(x["状態別"], ensure_ascii=False), json.dumps(x["形成別採用"], ensure_ascii=False)])
            diagnostics.append([policy, label, json.dumps(x["基本不適格理由観測"], ensure_ascii=False), json.dumps(x["位置除外理由観測"], ensure_ascii=False),
                                *[money(x["採用k経過秒"][k]) if x["採用k経過秒"][k] is not None else "null（採用0）" for k in ("平均", "中央値", "最小", "最大")], x["同形成最大反復枠"]])
            for kind in ("T", "R"):
                x = result["形成別"][policy][period][kind]
                y = x["入口"]
                formations.append([policy, label, kind, x["純候補"], x["形unique"], y["約定"], y["250"], rate(y["率"]),
                                   y["間引き約定"], y["間引き250"], rate(y["間引き率"]), y["日数"], y["場数"], flag(y["支持"]), x["実完結"],
                                   x["役割別完結"]["順行"], x["役割別完結"]["反転"]])
                formation_costs.append([policy, label, kind, *[money(x["費用別観測円"][str(f)]) for f in (0, 5, 10)]])
    pure, actual = [], []
    for left, right in PAIRS:
        for period in PERIODS:
            value = result["比較"][left + "対" + right][period]
            x, y = value["純"], value["実"]
            pure.append([left + "→" + right, PERIOD_NAMES[period], *[value[k] for k in ("準備共通", "左準備のみ", "右準備のみ")],
                         *[x.get(k, 0) for k in PURE_GROUPS]])
            actual.append([left + "→" + right, PERIOD_NAMES[period], *[y[k] for k in ("左完結", "右完結", "共通元枠同方向", "左のみ", "右のみ")],
                           *[money(y[k]) for k in ("共通元枠差額5", "左のみ額5", "右のみ額5")], y["厳密同新規"], money(y["厳密同新規出口差5"])])
    return ("## 入口の主・非重複・支持\n\n独立仮入口の250/125先着で、実戦略の勝率ではない。無取引を125敗北にせず、仮約定0の率はnull。支持は時系列で約定60/6日/10場/非重複20、選択・後続で20/3日/5場/非重複10。支持付き主率と非重複率の両方70%が入口条件である。\n\n"
        + table(["政策", "期間", "純候補", "仮約定", "250", "主率", "非重複約定", "非重複250", "非重複率", "日", "場", "支持", "入口70条件"], entries)
        + "## 全予定の行動と活動\n\nDay25/Night49枠、全予定1,702。主待ち=WAIT/全予定、保守=(WAIT＋判定不能＋条件登録後entryなし)/全予定。保有継続・処理中は非待ち。新即時3政策の条件登録/条件未約定は0で、即時要求の失効とは区別する。\n\n"
        + table(["政策", "期間", "全予定", "判断別", "待ち", "判定不能", "条件登録", "条件未約定", "主待ち率", "保守上限", "活動適格", "実完結"], activities)
        + "## 費用と実回収・品質\n\n0/5/10は同じ実約定の片道滑り感応。観測小計と政策全体の確定額を分け、品質注意/未解消は全体確定nullを維持する。費用支持は時系列で実完結20/6日/10場/買売各5、選択・後続で10/3日/6場/買売各3。主5ptの政策全体確定額が正であることを別に要求する。\n\n"
        + table(["政策", "期間", "観測0円", "観測5円", "観測10円", "確定0円", "確定5円", "確定10円", "未解消", "品質注意場"], costs)
        + table(["政策", "期間", "実完結", "買", "売", "日", "場", "費用支持", "費用適格", "同時適格"], support)
        + table(["政策", "期間", "DI実役割", "実完結", "観測5円"], roles)
        + "## native準備・形成とP1位置除外\n\n準備は各政策本来の可知集合。ORと前帯の準備差を帯の値だけの効果としない。形観測は同じ形成の反復を含み、uniqueは独立した約定支持ではない。現在active・基本適格・位置条件不可も形成観測の分母で、純候補やuniqueと加算しない。保存項目の位置除外形成観測は基本適格だがP1位置条件が不可だった観測数。O0/P0では位置条件を仮に当てた診断で採否除外ではなく、実際に除外へ使うのはP1だけである。平坦帯と不明帯も理由別で分ける。\n\n"
        + table(["政策", "期間", "全予定", "準備", "形観測", "形unique", "現在active", "純候補", "純順行", "純反転", "採用形unique", "基本適格形成観測", "位置条件不可（実除外P1のみ）"], coverage)
        + table(["政策", "期間", "準備/候補理由別", "形成状態別", "T/R採用別"], reasons)
        + "基本不適格理由と位置除外理由は同じ形成観測に複数理由が重複するため、理由件数を独立候補数へ足さない。位置理由もO0/P0では仮診断、実作用はP1のみ。k経過は純採用枠の判断time−最初k.confirmで、実新規遅延や最適な許容年齢ではない。採用0では全統計null、最大反復は同じ形成IDの採用枠数である。\n\n"
        + table(["政策", "期間", "基本不適格理由観測", "位置条件不可理由観測", "採用k平均秒", "採用k中央値秒", "採用k最小秒", "採用k最大秒", "同形成最大反復枠"], diagnostics)
        + "## 価格形成T/Rと運用role\n\nT/Rは固定端に対する価格形成、順行/反転は上位DIとの関係で別の分類。RでもDI同方向なら順行である。群内の非重複入口は加算できず、全体支持を小群へ流用しない。形成別の観測額は既存実完結の帰属であり、群だけで再運用した利益ではない。各期間の政策全体品質を引き継ぎ、群額を無条件確定としない。\n\n"
        + table(["政策", "期間", "形成", "純候補", "形unique", "仮約定", "250", "主率", "非重複約定", "非重複250", "非重複率", "日", "場", "群内支持", "実完結", "順行完結", "反転完結"], formations)
        + table(["政策", "期間", "形成", "観測0円", "観測5円", "観測10円"], formation_costs)
        + "## 利益旗と赤字の価格会計\n\n旗後赤はarmかつpnl5<0。同値=実返済価格と実新規が等しい、有利費用負け=実方向価格差は正だが費用後負、不利=実方向価格差が負。要求から約定までの滑りの3分類ではない。先着250前の実退出は同入口の保存終端keyとの比較であり、250先着を実現益へ読み替えない。\n\n"
        + table(["政策", "期間", "利益旗", "旗後赤", "同値", "有利費用負け", "不利", "先着250前実退出"], protection)
        + "## 同枠の準備・純方向と実参加差\n\n未出現のCounter項目だけを構造上の件数0として表示する。未知率や未知回収を0へ補完しない。共通元枠同方向でも入口時刻/原行/価格は別であり、厳密同新規を別欄にする。差額は右−左、帰属には政策全体の品質留保を引き継ぐ。\n\n"
        + table(["左→右", "期間", "準備共通", "左準備のみ", "右準備のみ", "両同方向", "左純のみ", "右純のみ", "反対変更", "双方待機"], pure)
        + table(["左→右", "期間", "左完結", "右完結", "共通元枠同方向", "左のみ", "右のみ", "共通差額5円", "左のみ5円", "右のみ5円", "厳密同新規", "同新規出口差5円"], actual))


def reproduction() -> str:
    """主工程と純表示の再現経路を明記する。

    引数: なし。
    返り値: strはコマンド案内。開始済みの再実行を指示しない。
    """
    prefix = "work/venvs/technical-tree/Scripts/python.exe -X utf8 "
    commands = [prefix + "scripts/事前帯と現在の反応/検証.py --" + phase for phase in ("prepare", "preflight", "freeze", "run")]
    commands.insert(2, prefix + "work/事前帯と現在の反応/人工を確認する.py")
    commands += [prefix + "scripts/事前帯と現在の反応/保存検証.py --run --viewer-url http://127.0.0.1:8092",
                 "C:/Python314/python.exe -X utf8 scripts/事前帯と現在の反応/レポート.py",
                 "C:/Python314/python.exe -X utf8 scripts/事前帯と現在の反応/レポート.py --check"]
    return ("## 再現と限界\n\n既存の準備/開始/固定/結果がある工程は再実行せず、既存handle・完了証拠を確認する。以下は初回の工程順で、表示の後2行だけは市場や教師を再生しない。\n\n```powershell\n"
            + "\n".join(commands) + "\n```\n\n新fit0・新モデル0・新独立測定0、新一枚運用138＋保存参考46。旧55の独立測定は同時計/方向/ATR/D/入口/出口の厳密結合で参照する。先着ラベルや未来回収は結果説明にだけ使い、候補入力へ戻さない。単独測定の合計は同時実行可能な戦略利益ではない。\n\n"
            "全66場既使用。初20専用を新評価へ加えず、時系列20/条件選択24/既使用後続2場で評価する。新しい未使用期での確認は未了。両方向・各政策・同形反復は独立標本ではない。未使用セルは無効の証拠でなく未使用・未検証。複合成績を帯/FastK/DI/ADX等の単独効果としない。TOPIX等の小数価格へこの算術を一般化する前に、中点丸め契約を別途確認する。11月5日Day追加読取・FutureAlgorithmResearchの新市場取得は0。\n\n")


def context_for() -> dict:
    """正式監査成功と結果SHA結合後だけ小型文脈を読む。

    引数: なし。
    返り値: dictは結果/条件/証明と表示出典。本物価格・モデル・詳細gzipは読まない。
    """
    paths = [STUDY / name for name in ("結果.json", "条件.json", "保存物確認.json")]
    if any(not p.is_file() for p in paths):
        raise FileNotFoundError("75主と正式監査の成功後に表示してください")
    proof = read(paths[2])
    if proof["全件一致"] is not True or proof["不一致数"] != 0 or proof["不一致"] != [] or proof["結果SHA256"] != sha(paths[0]):
        raise ValueError("75正式監査の成功又は結果SHA結合差")
    result, conditions = read(paths[0]), read(paths[1])
    validate_result(result)
    if result["設定"] != conditions:
        raise ValueError("75結果と条件JSONの差")
    sources = paths + [Path(__file__), PREVIOUS_PATH, V5_PATH()]
    sources += [V5.CATALOG, V5.MASTER, STUDY / "検証計画.md"]
    return {"result": result, "conditions": conditions, "proof": proof, "sources": sources}


def V5_PATH() -> Path:
    """再用する版5純描画の出典を返す。

    引数: なし。
    返り値: Pathは固定カタログ描画コード。
    """
    return ROOT / "scripts/レポート/カタログ版5.py"


def documents(context: dict) -> dict[str, str]:
    """保存値と固定説明から二Markdownをメモリへ組み立てる。

    引数: context(dict)は正式又は人工の表示文脈。
    返り値: dict[str,str]はREADME.mdと設定と結果.md。ここでは保存しない。
    """
    result = context["result"]
    validate_result(result)
    detail, overview = STUDY / "設定と結果.md", STUDY / "README.md"
    rows = settings(context)
    matrix = V5.matrix(V5.load_catalog(), detail, rows).replace("未使用", "未使用・未検証")
    decision = "新3政策の保存同時適格: " + (" / ".join(result["採用"]) if result["採用"] else "なし（目標未達）") + "。既使用期間の記述結果であり、未知期間での達成証明ではない。\n\n"
    headline = table(["政策", "選択主先着", "非重複先着", "実完結", "観測5円", "確定5円", "主待ち", "保守上限"], [
        [p, f'{result["候補"][p]["条件選択"]["入口"]["250"]}/{result["候補"][p]["条件選択"]["入口"]["約定"]}',
         f'{result["候補"][p]["条件選択"]["入口"]["間引き250"]}/{result["候補"][p]["条件選択"]["入口"]["間引き約定"]}',
         result["候補"][p]["条件選択"]["運用"]["完結数"], money(result["候補"][p]["条件選択"]["運用"]["完結観測額円"]["5"]),
         money(result["候補"][p]["条件選択"]["運用"]["全体確定額円"]["5"]), rate(result["候補"][p]["条件選択"]["運用"]["主待ち率"]),
         rate(result["候補"][p]["条件選択"]["運用"]["待ち率保守上限"])] for p in POLICIES])
    setting_table = table(["設定ID", "手法", "尺度", "短い閾値/状態", "複合評価", "役割・限定"], [
        [r["設定ID"], "/".join(r["手法ID"]), "/".join(r["尺度ID"]), r["短記"], r["結果短記"], r["説明"]] for r in rows])
    references = ("## 保存参考と出典\n\n" + link(OLD / "設定と結果.md", detail, "旧73Q0の全64特徴・閾値・木")
        + "。R01だけの保存参考で、今回の新3政策にfallbackしない。旧木の全閾値や教師IDを再転記せず、新しいraw/派生木は作らない。\n\n"
        + table(["保存出典", "SHA256"], [[link(p, detail, p.relative_to(ROOT).as_posix()), sha(p)] for p in context["sources"]]))
    short = ("# 00075：事前帯の外保持と内回帰を判別\n\n正常気配を伴うLast観測帯に対する外保持/内回帰を、短期勢い・上位方向/強弱・当時の価格位置と組み合わせる。"
             "新規則は保存Q0へfallbackせず、公式セッション高安や算術中央の合意価格を仮定しない。\n\n"
             + decision + comparison_axes() + "## 条件選択24場の要点\n\n" + headline
             + link(detail, overview, "全期間・準備差・形成/role・支持・位置除外・費用と55×9表") + " / "
             + link(STUDY / "検証計画.md", overview, "事前計画") + " / "
             + link(STUDY / "一覧.resources.json", overview, "Viewer184資源") + "\n\n"
             "純候補・仮約定・実一枚完結を分け、品質null、条件未約定込みの保守活動、利益旗後赤字を別に記録する。全66場既使用、新しい未使用期確認は未了。\n\n" + reproduction())
    return {"README.md": short, "設定と結果.md": "# 00075：設定と結果\n\n" + decision + comparison_axes() + mechanics(detail)
            + "## 手法×尺度・版5全文\n\n55手法×9尺度を全コピー。新しい指標版を作らず、帯/反応を既存の価格構造へ記録する。旧Q0セルはR01保存参考であり、新規則に未使用の旧量等を現在の票にしない。\n\n"
            + matrix + "## 設定IDと複合評価\n\n" + setting_table + result_tables(context) + reproduction() + references}


def check_links(text: str, output: Path, generated: set) -> int:
    """表示予定文書の内部リンクを保存先基準で検査する。

    引数: text(str)は本文、output(Path)は保存先、generated(set)は同時生成予定の絶対path。
    返り値: intは内部リンク件数。外部webを取得しない。
    """
    return PREVIOUS.check_links(text, output, generated)


def render(check: bool = False) -> dict:
    """正式成功後の二文書を一度保存又は保存版と同byte照合する。

    引数: check(bool)は書込みなし照合。
    返り値: dictはSHA/サイズ/リンク/表件数。固定JSON・市場データは変更しない。
    """
    context = context_for()
    before = {p.relative_to(ROOT).as_posix(): sha(p) for p in context["sources"]}
    bodies = documents(context)
    generated = {(STUDY / name).resolve() for name in bodies}
    catalog = V5.load_catalog()
    identifiers = {r["id"] for r in catalog["methods"]}
    matrix = [line for line in bodies["設定と結果.md"].splitlines() if line.startswith("| ") and len(line.split("|")) == 13 and line.split("|")[1].strip() in identifiers]
    if len(matrix) != 55 or {line.split("|")[1].strip() for line in matrix} != identifiers:
        raise ValueError("75の版5全55×9表が不完全です")
    links = sum(check_links(body, STUDY / name, generated) for name, body in bodies.items())
    if before != {p.relative_to(ROOT).as_posix(): sha(p) for p in context["sources"]}:
        raise ValueError("75表示中の入力変更")
    reports = {}
    if not check and any((STUDY / name).exists() and (STUDY / name).read_bytes() != body.encode("utf-8") for name, body in bodies.items()):
        raise FileExistsError("75既存の異なる文書を上書きしません")
    for name, body in bodies.items():
        path, data = STUDY / name, body.encode("utf-8")
        if check:
            if not path.is_file() or path.read_bytes() != data:
                raise ValueError("75保存文書と再表示の差:" + name)
        else:
            path.write_bytes(data)
        reports[name] = {"bytes": len(data), "SHA256": hashlib.sha256(data).hexdigest()}
    return {"成功": True, "文書": reports, "内部リンク検査": links, "欠落": 0, "版": 5,
            "手法": 55, "尺度": 9, "新モデル": 0, "入力前後不変": True}


# ----------------------------------------
# 人工辞書だけで表示の復元・null・比較を確認する。正式context_forは呼ばない。

def fixture(active: bool = False) -> dict:
    """架空の0件又は1件を置いて75の保存集計形を作る。

    引数: active(bool)は各政策各期へ架空の同方向1件を置く指定。
    返り値: dictは人工文脈。固定74の純fixture以外に結果を読まない。
    """
    legacy = PREVIOUS.fixture(active)["result"]
    mapping = {"Q0": "Q0", "O0": "I0", "P0": "I0", "P1": "I0"}
    result = {"試行": 75, "全66場既使用": True, **COUNTS, "評価場": [f"人工{i}" for i in range(46)],
              "候補": {}, "利益保護": {}, "技法被覆": {p: {} for p in POLICIES},
              "形成別": {p: {} for p in POLICIES}, "比較": {}, "採用": []}
    n = int(active)
    for policy, old in mapping.items():
        result["候補"][policy] = deepcopy(legacy["候補"][old])
        result["利益保護"][policy] = deepcopy(legacy["利益保護"][old])
        if policy == "Q0":
            continue
        for period, scheduled in zip(PERIODS, (740, 888, 74)):
            coverage = {"定時枠": scheduled, "準備済み": n, "理由別": {"準備済み": n, "人工不明": scheduled - n},
                        "形観測": n, "形unique": n, "状態別": {"有効": n} if n else {},
                        "現在active観測": n, "適格方向": n, "順行": n, "反転": 0,
                        "採用形unique": n, "形成別採用": {"T": n} if n else {},
                        "基本適格形成観測": n, "位置除外形成観測": 0,
                        "基本不適格理由観測": {}, "位置除外理由観測": {},
                        "採用k経過秒": {k: 0. if n else None for k in ("平均", "中央値", "最小", "最大")}, "同形成最大反復枠": n}
            result["技法被覆"][policy][period] = coverage
            item = result["候補"][policy][period]
            result["形成別"][policy][period] = {}
            for kind in ("T", "R"):
                entry = deepcopy(item["入口"])
                if kind == "R":
                    entry.update(候補=0, 約定=0, 率=None, 間引き約定=0, 間引き率=None, 日数=0, 場数=0, 結果別={})
                    entry["250"], entry["間引き250"] = 0, 0
                count = n if kind == "T" else 0
                result["形成別"][policy][period][kind] = {"純候補": count, "形unique": count,
                    "入口": entry, "実完結": count, "費用別観測円": deepcopy(item["運用"]["完結観測額円"]) if kind == "T" else {"0": 0., "5": 0., "10": 0.},
                    "役割別完結": {"順行": count, "反転": 0}}
    for left, right in PAIRS:
        result["比較"][left + "対" + right] = {}
        for period in PERIODS:
            value = deepcopy(legacy["比較"]["Q0対I0"][period])
            value.pop("取得差")
            value.update(準備共通=n, 左準備のみ=0, 右準備のみ=0)
            result["比較"][left + "対" + right][period] = value
    conditions = {"試行": 75, "保存参考セル": [{"method": "I05", "scale": "m15"},
        {"method": "P05", "scale": "m03"}, {"method": "P06", "scale": "m03+m30"}]}
    result["設定"] = deepcopy(conditions)
    return {"result": result, "conditions": conditions, "proof": {"全件一致": True}, "sources": [PREVIOUS_PATH]}


def self_test() -> dict:
    """人工文脈で分母・null・費用・形成・比較の誤値拒否と全文表を検査する。

    引数: なし。正式結果・価格・教師・モデルは読み込まない。
    返り値: dictはテスト件数と照合/リンク成功の要約。
    """
    groups, checks, links = 0, 0, 0

    def equal(actual: object, expected: object) -> None:
        """人工の実値と期待値を比較する。

        引数: actual/expected(object)は比較値。
        返り値: None。不一致なら例外。
        """
        nonlocal checks
        checks += 1
        assert actual == expected, (actual, expected)

    def rejects(value: dict) -> None:
        """不整合な人工集計が拒否されることを確認する。

        引数: value(dict)は誤値を一つ含む人工結果。
        返り値: None。拒否されない場合は例外。
        """
        nonlocal checks
        checks += 1
        try:
            validate_result(value)
        except ValueError:
            return
        raise AssertionError("75表示が不整合な人工値を受理しました")

    for active in (False, True):
        context = fixture(active)
        validate_result(context["result"])
        bodies = documents(context)
        identifiers = {row["id"] for row in V5.load_catalog()["methods"]}
        matrix = [line for line in bodies["設定と結果.md"].splitlines() if line.startswith("| ") and len(line.split("|")) == 13 and line.split("|")[1].strip() in identifiers]
        equal(len(matrix), 55)
        equal({line.split("|")[1].strip() for line in matrix}, identifiers)
        generated = {(STUDY / name).resolve() for name in bodies} | {(STUDY / "一覧.resources.json").resolve()}
        for name, body in bodies.items():
            links += check_links(body, STUDY / name, generated)
        groups += 1
    context = fixture()
    definitions = settings(context)
    equal(definitions[0]["尺度ID"], ["tick", "m30", "session"])
    equal(len({r["設定ID"] for r in definitions}), len(definitions))
    equal(all(r["結果短記"] == "R01" for r in definitions[14:]), True)
    equal(any(r["尺度ID"] == ["m03", "m30"] for r in definitions[14:]), True)
    groups += 1

    equal(rate(None) == rate(0), False)
    equal(money(None) == money(0), False)
    equal(flag(False), "偽")
    base = fixture(True)["result"]
    bad = deepcopy(base)
    bad["候補"]["P0"]["学習"]["入口"]["率"] = None
    rejects(bad)
    bad = deepcopy(context["result"])
    bad["候補"]["P0"]["学習"]["入口"]["率"] = 0.
    rejects(bad)
    groups += 1

    bad = deepcopy(base)
    bad["候補"]["O0"]["学習"]["運用"]["品質注意場"] = ["人工注意"]
    rejects(bad)
    good = deepcopy(bad)
    good["候補"]["O0"]["学習"]["運用"]["全体確定額円"] = {"0": None, "5": None, "10": None}
    validate_result(good)
    equal("null（品質・未解消等）" in result_tables({"result": good}), True)
    groups += 1

    bad = deepcopy(base)
    bad["候補"]["P0"]["学習"]["運用"]["完結観測額円"]["10"] += 1
    rejects(bad)
    bad = deepcopy(base)
    bad["形成別"]["P0"]["学習"]["T"]["費用別観測円"]["5"] += 1
    rejects(bad)
    groups += 1

    for key in ("純候補", "実完結", "形unique"):
        bad = deepcopy(base)
        bad["形成別"]["P0"]["学習"]["T"][key] += 1
        rejects(bad)
    bad = deepcopy(base)
    bad["技法被覆"]["P0"]["学習"]["順行"] = 0
    rejects(bad)
    groups += 1

    bad = deepcopy(base)
    bad["比較"]["O0対P0"]["学習"]["純"]["左のみ"] = 1
    rejects(bad)
    bad = deepcopy(base)
    bad["比較"]["O0対P0"]["学習"]["実"]["共通元枠差額5"] = 1
    rejects(bad)
    bad = deepcopy(base)
    bad["比較"]["P0対P1"]["学習"]["右準備のみ"] = 1
    rejects(bad)
    groups += 1

    bad = deepcopy(base)
    bad["候補"]["P1"]["学習"]["運用"]["主待ち率"] = 0.
    rejects(bad)
    bad = deepcopy(base)
    bad["利益保護"]["P1"]["学習"]["同値"] = 1
    rejects(bad)
    groups += 1

    sparse = deepcopy(base)
    for comparison in sparse["比較"].values():
        for item in comparison.values():
            item["純"] = {k: v for k, v in item["純"].items() if v}
    validate_result(sparse)
    equal(result_tables({"result": sparse}), result_tables({"result": base}))
    groups += 1

    native = deepcopy(context["result"])
    native["技法被覆"]["O0"]["学習"].update(準備済み=1, 理由別={"準備済み": 1, "人工不明": 739})
    native["比較"]["Q0対O0"]["学習"]["右準備のみ"] = 1
    native["比較"]["O0対P0"]["学習"]["左準備のみ"] = 1
    validate_result(native)
    diagnostic = deepcopy(base)
    diagnostic["技法被覆"]["O0"]["学習"]["位置除外形成観測"] = 1
    diagnostic["技法被覆"]["P0"]["学習"]["位置除外形成観測"] = 1
    diagnostic["技法被覆"]["O0"]["学習"]["位置除外理由観測"] = {"仮の位置不適格": 1}
    diagnostic["技法被覆"]["P0"]["学習"]["位置除外理由観測"] = {"仮の位置不適格": 1}
    validate_result(diagnostic)
    equal("O0/P0では位置条件を仮に当てた診断で採否除外ではなく" in result_tables({"result": diagnostic}), True)
    bad = deepcopy(context["result"])
    bad["技法被覆"]["P0"]["学習"]["採用k経過秒"]["平均"] = 0.
    rejects(bad)
    bad = deepcopy(base)
    bad["技法被覆"]["P0"]["学習"]["同形成最大反復枠"] = 2
    rejects(bad)
    groups += 1

    text = mechanics(STUDY / "設定と結果.md")
    for phrase in ("F47>=0.20", "F47はADX/100", "line=None", "公式セッション高安", "P1のみ", "正常観測間", "同試行の復活をしない"):
        equal(phrase in text, True)
    for phrase in ("新規則はQ0へfallbackしない", "準備被覆", "同準備"):
        equal(phrase in comparison_axes(), True)
    groups += 1

    return {"成功": True, "人工成功": True, "テスト件数": groups, "照合項目数": checks,
            "不一致数": 0, "不一致": [], "内部リンク検査": links, "正式入力読取": False,
            "新fit": 0, "市場再生": False}


def main() -> None:
    """人工・通常生成・同byte照合を排他的に選ぶ。

    引数: CLIの--self-test又は--checkは任意の排他的な旗。
    返り値: None。通常生成は正式監査成功前に停止する。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true")
    group.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    result = self_test() if args.self_test else render(args.check)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
