"""76の成功済み小型正本と表示設定から二Markdownだけを純描画する。"""

import argparse
from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00076_局所波の押戻しと起点喪失を分ける"
OLD = ROOT / "study/00075_事前帯の外保持と内回帰を判別"
DISPLAY = STUDY / "表示設定.json"
PREVIOUS_PATH = ROOT / "scripts/事前帯と現在の反応/レポート.py"
PREVIOUS_SHA256 = "5c678b9f6a3f9be2b6fa5a052844d1f6fa99e8647c2effded0652b554c266907"
if hashlib.sha256(PREVIOUS_PATH.read_bytes()).hexdigest() != PREVIOUS_SHA256:
    raise ValueError("固定75純表示のSHA256不一致")
SPEC = importlib.util.spec_from_file_location("局所波76の固定75純表示", PREVIOUS_PATH)
PREVIOUS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PREVIOUS
SPEC.loader.exec_module(PREVIOUS)
table, rate, money, flag, link, V5 = PREVIOUS.table, PREVIOUS.rate, PREVIOUS.money, PREVIOUS.flag, PREVIOUS.link, PREVIOUS.V5
POLICIES, NEW, PERIODS = ("O0", "P0", "L0", "L1"), ("L0", "L1"), ("学習", "条件選択", "後続検査")
PERIOD_NAMES = {"学習": "時系列検査20場", "条件選択": "条件選択24場", "後続検査": "既使用後続2場"}
PAIRS = (("O0", "L0"), ("O0", "L1"), ("P0", "L1"), ("L0", "L1"))
PURE_GROUPS = ("同方向", "左のみ", "右のみ", "反対切替", "双方待機")
COUNTS = {"新fit": 0, "新分類器fit": 0, "新モデル": 0, "新独立測定": 0,
          "新運用数": 92, "保存参照運用数": 92, "Viewer資源": 184}
COVERAGE = ("定時枠", "準備済み", "形観測", "形unique", "現在active観測", "適格方向", "順行", "反転", "採用形unique")
PARENTS = ("基礎準備", "追加未準備", "親観測", "親unique", "起点喪失f観測", "遅いf観測", "採用親unique", "reset観測", "出生拒否観測")
PLACES = ("上外", "上端", "帯内", "下端", "下外", "未知")
EXTERNAL = (ROOT / "docs/議論/外部再調査/広い帯の内側と局所の波を分ける.md",
            ROOT / "docs/議論/外部再調査/局所波の押戻しと確認時点を分ける.md")


def sha(path: Path) -> str:
    """表示の小型入力又は純コードのbyte指紋を得る。

    引数: path(Path)はファイル。
    返り値: strはSHA256。市場・圧縮詳細は開かない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """表示に許された小型JSONを読む。

    引数: path(Path)は結果/条件/証明/表示設定。
    返り値: dictは保存辞書。
    """
    return json.loads(path.read_text(encoding="utf-8"))


def compact(value: object) -> str:
    """診断の保存値を未知を補完せず短いJSONで表示する。

    引数: value(object)はJSON値。
    返り値: strはnullを含む元値の表記。
    """
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def count(value: object) -> int:
    """非負整数件数を真偽値や率と区別する。

    引数: value(object)は保存件数。
    返り値: intは元件数。不正ならValueError。
    """
    if type(value) is not int or value < 0:
        raise ValueError("76の件数は非負整数")
    return value


def entry_check(value: dict) -> None:
    """仮約定分母・非重複・結果別と率nullを照合する。

    引数: value(dict)はC49互換入口集計。
    返り値: None。未約定を125敗北にする不整合を拒否。
    """
    for key in ("候補", "約定", "250", "間引き約定", "間引き250", "日数", "場数"):
        count(value[key])
    for n in value["結果別"].values():
        count(n)
    if sum(value["結果別"].values()) != value["候補"] or value["結果別"].get("250", 0) != value["250"]:
        raise ValueError("76先着結果別の復元差")
    if sum(value["結果別"].get(k, 0) for k in ("250", "125", "期限", "不足")) != value["約定"]:
        raise ValueError("76入口の約定/無取引分母差")
    for win, total, field in (("250", "約定", "率"), ("間引き250", "間引き約定", "間引き率")):
        if value[win] > value[total] or (value[field] is None) != (value[total] == 0):
            raise ValueError("76先着率の分母又はnull差")
        if value[total] and not math.isclose(value[field], value[win] / value[total], abs_tol=1e-12, rel_tol=0):
            raise ValueError("76保存先着率の差")
    if value["間引き約定"] > value["約定"] or any(type(value[k]) is not bool for k in ("支持", "70目標")):
        raise ValueError("76非重複又は支持の型差")


def validate_display(display: dict) -> list[dict]:
    """表示設定正本のID・短記・手法・尺度を検査する。

    引数: display(dict)は表示専用metadata。
    返り値: list[dict]は深い写しの設定行。条件JSONは更新しない。
    """
    catalog = V5.load_catalog()
    if display["試行"] != 76 or display["版"] != 5 or [(x["評価ID"], x["政策"]) for x in display["複合評価"]] != [(f"R{i:02d}", p) for i, p in enumerate(POLICIES, 1)]:
        raise ValueError("76表示設定の試行/政策差")
    methods, scales = {x["id"] for x in catalog["methods"]}, {x["id"] for x in catalog["scales"]}
    rows = display["設定"]
    if not rows or len({r["設定ID"] for r in rows}) != len(rows):
        raise ValueError("76表示設定IDの重複又は空")
    for row in rows:
        if set(row) != {"設定ID", "手法ID", "尺度ID", "短記", "結果短記", "説明"}:
            raise ValueError("76表示設定の項目差")
        if not row["手法ID"] or not set(row["手法ID"]) <= methods or not row["尺度ID"] or not set(row["尺度ID"]) <= scales:
            raise ValueError("76表示設定の手法/尺度差")
        if any(not isinstance(row[k], str) or not row[k] for k in ("設定ID", "短記", "結果短記", "説明")):
            raise ValueError("76表示短記の欠測")
    return deepcopy(rows)


def validate_result(result: dict) -> None:
    """政策・分母・費用・形成帰属・比較の保存値を相互照合する。

    引数: result(dict)は76正本又は自己完結の人工辞書。
    返り値: None。未知を0へ補完せず不整合を停止する。
    """
    if result.get("試行") != 76 or result.get("全66場既使用") is not True or set(result["候補"]) != set(POLICIES):
        raise ValueError("76の試行/既使用/政策差")
    if any(type(result[k]) is not int or result[k] != n for k, n in COUNTS.items()):
        raise ValueError("76の新fit0/新92/保存92/Viewer184差")
    if len(result["評価場"]) != 46 or len(set(result["評価場"])) != 46:
        raise ValueError("76評価46場の差")
    if set(result["比較"]) != {a + "対" + b for a, b in PAIRS}:
        raise ValueError("76比較軸の差")
    for period, scheduled in zip(PERIODS, (740, 888, 74)):
        for policy in POLICIES:
            item = result["候補"][policy][period]
            e, o = item["入口"], item["運用"]
            entry_check(e)
            for key in ("予定枠", "待ち数", "判定不能", "条件登録数", "条件未約定", "完結数", "未解消"):
                count(o[key])
            for n in o["判断別"].values():
                count(n)
            wait, invalid = o["判断別"].get("待ち", 0), o["判断別"].get("判定不能", 0)
            conservative = wait + invalid + o["条件未約定"]
            if o["予定枠"] != scheduled or sum(o["判断別"].values()) != scheduled or (wait, invalid) != (o["待ち数"], o["判定不能"]):
                raise ValueError("76全予定の行動分母差")
            if not 0 <= conservative <= scheduled or not math.isclose(o["主待ち率"], wait / scheduled, abs_tol=1e-12, rel_tol=0) or not math.isclose(o["待ち率保守上限"], conservative / scheduled, abs_tol=1e-12, rel_tol=0) or o["活動適格"] != (2 * conservative <= scheduled):
                raise ValueError("76主待ち/保守活動の差")
            if o["条件登録数"] or o["条件未約定"]:
                raise ValueError("76即時政策に条件登録が混入")
            for fee in (0, 5, 10):
                observed, fixed = Decimal(str(o["完結観測額円"][str(fee)])), o["全体確定額円"][str(fee)]
                if not observed.is_finite() or observed != Decimal(str(o["完結観測額円"]["0"])) - 20 * fee * o["完結数"]:
                    raise ValueError("76同約定費用感応の差")
                if (o["品質注意場"] or o["未解消"]) and fixed is not None:
                    raise ValueError("76品質注意の確定null差")
                if fixed is not None and not Decimal(str(fixed)).is_finite():
                    raise ValueError("76確定額の非有限値")
            roles = o["役割別完結"]
            if sum(count(roles[r]["件数"]) for r in ("順行", "反転")) != o["完結数"] or sum((Decimal(str(roles[r]["観測純額5"])) for r in roles), Decimal(0)) != Decimal(str(o["完結観測額円"]["5"])):
                raise ValueError("76役割帰属の件数/金額差")
            p = result["利益保護"][policy][period]
            for n in p.values():
                count(n)
            if sum(p[k] for k in ("同値", "有利費用負け", "不利")) != p["旗後赤"] or (p["利益旗"], p["旗後赤"]) != (o["利益起動件数"], o["起動後赤字件数5"]):
                raise ValueError("76利益旗の赤字3分類差")
            if not p["旗後赤"] <= p["利益旗"] <= o["完結数"] or p["先着250前の実退出"] > min(e["250"], o["完結数"]):
                raise ValueError("76利益旗/250前退出の分母差")
            if item["同時適格"] != (e["70目標"] and o["活動適格"] and o["費用適格"]):
                raise ValueError("76同時適格差")
            if policy not in NEW:
                continue
            x = result["技法被覆"][policy][period]
            for key in COVERAGE:
                count(x[key])
            if x["定時枠"] != scheduled or x["準備済み"] > scheduled or sum(x["理由別"].values()) != scheduled or sum(x["状態別"].values()) != x["形観測"]:
                raise ValueError("76native準備/状態の復元差")
            if x["形unique"] > x["形観測"] or x["採用形unique"] > x["適格方向"] or x["適格方向"] != e["候補"] or x["順行"] + x["反転"] != e["候補"] or sum(x["形成別採用"].values()) != e["候補"]:
                raise ValueError("76形成unique/反復/役割の差")
            for key in PARENTS:
                count(x[key])
            if not x["準備済み"] <= x["基礎準備"] <= scheduled or x["追加未準備"] != x["基礎準備"] - x["準備済み"]:
                raise ValueError("76旧基礎readyと局所readyの差")
            if sum(x["観測理由別"].values()) != scheduled or sum(x["親状態別"].values()) != x["親観測"] or x["親unique"] > x["親観測"] or not x["遅いf観測"] <= x["起点喪失f観測"] <= x["親観測"] or x["採用親unique"] > x["採用形unique"]:
                raise ValueError("76親観測/unique/f/latefの差")
            for field in ("採用k経過秒", "採用k終了経過秒", "採用tip距離pt"):
                values = x[field]
                if set(values) != {"平均", "中央値", "最小", "最大"} or any((v is None) != (e["候補"] == 0) for v in values.values()):
                    raise ValueError("76採用分布の項目/null差")
                if e["候補"] and (any(type(v) not in (int, float) or not math.isfinite(v) for v in values.values()) or not values["最小"] <= values["平均"] <= values["最大"] or not values["最小"] <= values["中央値"] <= values["最大"]):
                    raise ValueError("76採用分布の有限値/順序差")
                if e["候補"] and field != "採用tip距離pt" and values["最小"] < 0:
                    raise ValueError("76公開済みkの経過が負")
            repeat = count(x["同形成最大反復枠"])
            if (repeat == 0) != (e["候補"] == 0) or repeat > e["候補"]:
                raise ValueError("76同形成反復の分母差")
            formations = result["形成別"][policy][period]
            if set(formations) != {"T", "R"} or sum(v["純候補"] for v in formations.values()) != e["候補"] or sum(v["実完結"] for v in formations.values()) != o["完結数"]:
                raise ValueError("76T/R帰属の復元差")
            if policy == "L0" and (formations["R"]["純候補"] or formations["R"]["実完結"]):
                raise ValueError("76T限定L0へRが混入")
            for kind, value in formations.items():
                entry_check(value["入口"])
                if value["純候補"] != value["入口"]["候補"] or value["純候補"] != x["形成別採用"].get(kind, 0) or value["形unique"] > value["純候補"] or sum(value["役割別完結"].values()) != value["実完結"]:
                    raise ValueError("76形成内の純/実分母差")
            if any(sum(v["入口"][k] for v in formations.values()) != e[k] for k in ("約定", "250")):
                raise ValueError("76形成内の主先着差")
            for fee in ("0", "5", "10"):
                if sum((Decimal(str(v["費用別観測円"][fee])) for v in formations.values()), Decimal(0)) != Decimal(str(o["完結観測額円"][fee])):
                    raise ValueError("76形成内の観測額差")
            places = result["場所別"][policy][period]
            if set(places) != set(PLACES) or sum(v["純候補"] for v in places.values()) != e["候補"] or sum(v["実完結"] for v in places.values()) != o["完結数"]:
                raise ValueError("76場所診断の純/実復元差")
            for value in places.values():
                entry_check(value["入口"])
                if value["純候補"] != value["入口"]["候補"]:
                    raise ValueError("76場所内の先着分母差")
            if any(sum(v["入口"][k] for v in places.values()) != e[k] for k in ("約定", "250")):
                raise ValueError("76場所別主先着の復元差")
            if any(sum((Decimal(str(v["費用別観測円"][f])) for v in places.values()), Decimal(0)) != Decimal(str(o["完結観測額円"][f])) for f in ("0", "5", "10")):
                raise ValueError("76場所別観測額の復元差")
        shared = (*COVERAGE[:5], "基礎準備", "追加未準備", "観測理由別", "親観測", "親unique", "親状態別", "起点喪失f観測", "遅いf観測", "reset観測", "出生拒否観測")
        if any(result["技法被覆"]["L0"][period][k] != result["技法被覆"]["L1"][period][k] for k in shared):
            raise ValueError("76L0/L1共通親観測の差")
        for left, right in PAIRS:
            v = result["比較"][left + "対" + right][period]
            pure, actual = v["純"], v["実"]
            if not set(pure) <= set(PURE_GROUPS) or sum(count(n) for n in pure.values()) != scheduled:
                raise ValueError("76純比較の全予定分母差")
            le, re = (result["候補"][p][period] for p in (left, right))
            common, reverse = pure.get("同方向", 0), pure.get("反対切替", 0)
            if common + pure.get("左のみ", 0) + reverse != le["入口"]["候補"] or common + pure.get("右のみ", 0) + reverse != re["入口"]["候補"]:
                raise ValueError("76純追加/除外/反対切替差")
            for key in ("準備共通", "左準備のみ", "右準備のみ"):
                count(v[key])
            if sum(v[k] for k in ("準備共通", "左準備のみ", "右準備のみ")) > scheduled:
                raise ValueError("76native準備比較差")
            if left == "L0" and (pure.get("左のみ", 0) or reverse or v["左準備のみ"] or v["右準備のみ"]):
                raise ValueError("76L0純T包含/同準備差")
            if v["準備共通"] + v["右準備のみ"] != result["技法被覆"][right][period]["準備済み"]:
                raise ValueError("76右native準備の復元差")
            if left in NEW and v["準備共通"] + v["左準備のみ"] != result["技法被覆"][left][period]["準備済み"]:
                raise ValueError("76左native準備の復元差")
            lo, ro = le["運用"], re["運用"]
            if actual["左完結"] != lo["完結数"] or actual["右完結"] != ro["完結数"] or actual["共通元枠同方向"] + actual["左のみ"] != actual["左完結"] or actual["共通元枠同方向"] + actual["右のみ"] != actual["右完結"] or not 0 <= actual["厳密同新規"] <= actual["共通元枠同方向"]:
                raise ValueError("76実参加の集合差")
            delta = Decimal(str(actual["共通元枠差額5"])) - Decimal(str(actual["左のみ額5"])) + Decimal(str(actual["右のみ額5"]))
            if delta != Decimal(str(ro["完結観測額円"]["5"])) - Decimal(str(lo["完結観測額円"]["5"])):
                raise ValueError("76実参加帰属と全体差額の差")
    if result["採用"] != [p for p in NEW if all(result["候補"][p][h]["同時適格"] for h in PERIODS[:2])]:
        raise ValueError("76採用欄の差")


# ----------------------------------------
def mechanics(output: Path) -> str:
    """出生・切替・公開時計・複数技法・取得保護を説明する。

    引数: output(Path)はリンクの出力先。
    返り値: strは事前条件の説明。一般資料を収益実証へ読み替えない。
    """
    return ("## 同じ親の出生・押戻し・起点喪失\n\n完全隣接3足a/m/bで2終値差が同じs方向へstrict正、s(Cb−Ca)>=ATR_bなら出生。originはaの反対端で、完成pivotではない。一場親1件、存続中新bなし。終端/reset足を次aへ兼用せず、後続3足から再登録する。\n\n"
        "Tはb後最初のs(C_i−C_previous)<0のrを固定し、別足でr実方向端をstrict終値突破したkを確認。終値差0はrではない。k前はoriginを維持すればr反対端の一時喪失を許す。k後のpremiseは買max(origin,r.low)/売min(origin,r.high)、終値等号否定で永久取消。確認端そのものへの戻りだけで取り消さない。\n\n"
        "最初のs(C−origin)<=0をfとし、Tのr/kより優先して同原因Rへ進む。f後1〜3別足でf実R方向端をstrict終値突破した最初kを確認する。待機中origin再獲得は確認より優先して終了。Rのk後のpremiseは買max(origin,f.low)/売min(origin,f.high)で、f確認端の維持は追加しない。Tの戦術線だけの否定はR成立ではない。\n\n"
        "親期限はb.end+1620秒、R未確認期限はmin(f.end+540秒,親期限)。足end/confirmと判断timeが期限以内であることを要求し、strict超を確認より先に終了、等号は許す。R確認後は親期限まで。独立900秒gateは未使用。k経過と同親/同形成の反復を診断し、反復を独立支持へ替えない。\n\n"
        "## 出生ATRと判断時入力\n\n出生ATR_bは固定49 NumericBank(3).buildを元66場順・同限月carryで再用し、SOURCE13全文指紋/index/end/公開keyへ結合する。最初14TR平均後のWilder更新を保持。現在ATR_jを過去bへ戻さず、a/m ATR水準で選別しない。価格又は出生ATR未知は親/bufferをclear、新しい完全隣接3準備足から再準備する。旧73基礎readyとL実readyの差を残す。正常な親終端後の出生待ちは、未知による準備待ちと別である。\n\n"
        "end<=scheduledかつ公開key<=実判断の足だけを先に選別し、未来の価格・件数・resetを参照しない。足内high/lowの発生順は推測しない。判断の9値は旧73float64のF01/02/03/07/15/47/48/51/52をそのまま再用。全候補F02>=0/F03>0/F07>0・非零F01/rawDI。TはF01>0/F51=F52=1/F47>=0.20/F48>=0。RはDI同方向なら順行、逆方向ならF52=1/F48<0/F15>0を要求する。F47=ADX/100なので0.20はADX20。価格T/RとDI実役割は別で、関連する価格加工を独立票にしない。\n\n"
        "## 当時取得と前帯の場所診断\n\nE*=判断買ask/売bid。正常BBOと正有限Lastが必要で、LastとE*の両方がpremiseの実方向strict側であることを確認する。k価格へ約定を戻さない。最新k公開key、同keyT優先。L0は同じ機械のTだけ、L1はT/Rを使う。前提距離<=Dや中央250余地、新量gateは追加しない。\n\n"
        "前収録帯は75保存の終了済み正常BBO+正Last観測帯で、公式session高安ではない。E*別の内外/H/L/Mへの前方距離と古さを診断するだけで、未知でもLreadyを落とさず、未知余地を無限としない。数量0。旧73readyの未使用OR/15本履歴/TV等も継承するため、新規則に必要な準備だけへ広げた比較ではない。\n\n"
        "## 15分判断と連続保護\n\nDay09:15〜15:15、Night17:30〜05:30の全予定25/49枠。新92運用はO49即時要求→1価格秒以上かつ後原行正常BBO、TTL30。現在ATR_jによるD=5pt切上clip5..125を維持し、出生ATR_bで置換しない。利益・損失の連続非緩和追尾、正常返済BBOの主費用後益strict正で利益旗と最低名目新規床、pending中h/L/arm凍結を保つ。名目床は費用後黒字の保証ではない。micro代理一枚10円/pt、片道手数料11円＋滑り5pt、主往復122円。0/10ptは同約定の費用感応。\n\n"
        + " / ".join(link(p, output, p.stem) for p in EXTERNAL)
        + "。原典は3足/1ATR/27分や日経短期70%を実証していない。心理は推論であり参加者を直測しない。\n\n")


def axes() -> str:
    """保存参考と新規則・純包含と実参加を区別する。

    引数: なし。
    返り値: strは比較の説明と4政策表。
    """
    return ("## 比較の分離\n\n" + table(["政策/評価", "候補", "扱い"], [
        ["O0/R01", "75当場OR30のT/R", "保存参考46運用"], ["P0/R02", "75前収録帯のT/R", "保存参考46運用"],
        ["L0/R03", "新しい同親局所波のTのみ", "新46運用"], ["L1/R04", "同じ全履歴のT/R", "新46運用"]])
        + "O0→L0/O0→L1/P0→L1は出生・前提線・寿命・準備を含む政策比較。L0→L1は親機械を変えずRを追加する。L0純TはL1へ同方向で含まれるが、一枚占有により実参加の包含は要求しない。旧保存判断へのfallbackも新しい木/fitもない。\n\n")


def result_tables(context: dict) -> str:
    """保存集計から入口・活動・費用・形成・比較を分母別に表示する。

    引数: context(dict)は結果を含む純文脈。
    返り値: strは表。価格・予測・運用・群別反実仮想を再計算しない。
    """
    r = context["result"]
    entries, actions, costs, support, roles, protects, coverage, reasons, parents, ages, forms, formcost, places, placecost = ([] for _ in range(14))
    for policy in POLICIES:
        for period in PERIODS:
            label, item = PERIOD_NAMES[period], r["候補"][policy][period]
            e, o = item["入口"], item["運用"]
            entries.append([policy, label, e["候補"], e["約定"], e["250"], rate(e["率"]), e["間引き約定"], e["間引き250"], rate(e["間引き率"]), e["日数"], e["場数"], flag(e["支持"]), flag(e["70目標"])])
            actions.append([policy, label, o["予定枠"], compact(o["判断別"]), o["待ち数"], o["判定不能"], o["条件登録数"], o["条件未約定"], rate(o["主待ち率"]), rate(o["待ち率保守上限"]), flag(o["活動適格"]), o["完結数"]])
            costs.append([policy, label, *[money(o["完結観測額円"][str(f)]) for f in (0, 5, 10)], *[money(o["全体確定額円"][str(f)]) for f in (0, 5, 10)], o["未解消"], compact(o["品質注意場"])])
            support.append([policy, label, o["完結数"], o["買い"], o["売り"], o["日数"], o["場数"], flag(o["費用支持"]), flag(o["費用適格"]), flag(item["同時適格"])])
            for role in ("順行", "反転"):
                v = o["役割別完結"][role]
                roles.append([policy, label, role, v["件数"], money(v["観測純額5"])])
            p = r["利益保護"][policy][period]
            protects.append([policy, label, *[p[k] for k in ("利益旗", "旗後赤", "同値", "有利費用負け", "不利", "先着250前の実退出")]])
            if policy not in NEW:
                continue
            x = r["技法被覆"][policy][period]
            coverage.append([policy, label, *[x[k] for k in COVERAGE]])
            reasons.append([policy, label, compact(x["理由別"]), compact(x["観測理由別"]), compact(x["親状態別"]), compact(x["状態別"]), compact(x["形成別採用"]), compact(x["基本不適格理由観測"])])
            parents.append([policy, label, *[x[k] for k in PARENTS], x["同形成最大反復枠"]])
            for field in ("採用k経過秒", "採用k終了経過秒", "採用tip距離pt"):
                ages.append([policy, label, field, *[money(x[field][k]) for k in ("平均", "中央値", "最小", "最大")]])
            for kind in ("T", "R"):
                v = r["形成別"][policy][period][kind]
                y = v["入口"]
                forms.append([policy, label, kind, v["純候補"], v["形unique"], y["約定"], y["250"], rate(y["率"]), y["間引き約定"], y["間引き250"], rate(y["間引き率"]), y["日数"], y["場数"], flag(y["支持"]), v["実完結"], v["役割別完結"]["順行"], v["役割別完結"]["反転"]])
                formcost.append([policy, label, kind, *[money(v["費用別観測円"][str(f)]) for f in (0, 5, 10)]])
            for where in PLACES:
                v = r["場所別"][policy][period][where]
                y = v["入口"]
                places.append([policy, label, where, v["純候補"], y["約定"], y["250"], rate(y["率"]), y["間引き約定"], y["間引き250"], rate(y["間引き率"]), y["日数"], y["場数"], flag(y["支持"]), v["実完結"]])
                placecost.append([policy, label, where, *[money(v["費用別観測円"][str(f)]) for f in (0, 5, 10)]])
    pure, actual = [], []
    for left, right in PAIRS:
        for period in PERIODS:
            v = r["比較"][left + "対" + right][period]
            a = v["実"]
            pure.append([left + "→" + right, PERIOD_NAMES[period], *[v[k] for k in ("準備共通", "左準備のみ", "右準備のみ")], *[v["純"].get(k, 0) for k in PURE_GROUPS]])
            actual.append([left + "→" + right, PERIOD_NAMES[period], *[a[k] for k in ("左完結", "右完結", "共通元枠同方向", "左のみ", "右のみ")], *[money(a[k]) for k in ("共通元枠差額5", "左のみ額5", "右のみ額5")], a["厳密同新規"], money(a["厳密同新規出口差5"])])
    return ("## 主先着・非重複と支持\n\n純候補から仮約定した入口の250/125先着。実戦略勝率ではなく、無取引を125敗北にしない。仮約定0の率はnull。時系列支持は約定60/6日/10場/非重複20、選択・後続は20/3日/5場/非重複10。両率70%と支持を別に確認する。非重複は保存entry/end key規約であり一定時間の間引きではない。\n\n"
        + table(["政策", "期間", "純候補", "仮約定", "250", "主率", "非重複約定", "非重複250", "非重複率", "日", "場", "支持", "入口70条件"], entries)
        + "## 全予定活動と費用・品質\n\n全予定1,702枠を分母に、主待ち=WAIT/全予定、保守=(WAIT＋判定不能＋条件登録後entryなし)/全予定。保有・処理中は非待ち。本試行は即時入口なので条件登録/条件未約定0。新規要求の失効とは別である。\n\n"
        + table(["政策", "期間", "全予定", "判断別", "待ち", "判定不能", "条件登録", "条件未約定", "主待ち率", "保守上限", "活動適格", "実完結"], actions)
        + "観測小計と政策全体確定額を分離し、品質注意/未解消では確定nullを維持。費用0/5/10は同一約定の片道滑り感応。費用支持は時系列20完結/6日/10場/買売各5、選択・後続10完結/3日/6場/買売各3。主確定額strict正と別評価する。\n\n"
        + table(["政策", "期間", "観測0円", "観測5円", "観測10円", "確定0円", "確定5円", "確定10円", "未解消", "品質注意場"], costs)
        + table(["政策", "期間", "実完結", "買", "売", "日", "場", "費用支持", "費用適格", "同時適格"], support)
        + table(["政策", "期間", "DI実役割", "実完結", "観測5円"], roles)
        + "## 新局所波の準備・親と形成\n\n旧73基礎readyと出生機械を含むL実readyを区別する。親/形成観測は反復を含み、unique親・unique形成・採用形unique・入口支持は異なる分母。準備待ち、出生待ち、T戦術取消後の起点喪失待ち、期限/品質resetを理由別で残す。前帯の場所は診断のみで準備や採否gateへ使わない。\n\n"
        + table(["政策", "期間", "全予定", "L準備", "形観測", "形unique", "現在active", "純候補", "純順行", "純反転", "採用形unique"], coverage)
        + table(["政策", "期間", "基礎準備", "追加未準備", "親観測", "親unique", "起点喪失f観測", "遅いf観測", "採用親unique", "reset観測", "出生拒否観測", "同形成最大反復枠"], parents)
        + "起点喪失f観測は全f、遅いf観測は確認残り0/1本の専用理由を持つものだけ。親/形成/f/reset/出生拒否は各枠で見える全履歴の反復観測で、独立イベント数ではない。旧O0/P0の被覆・形成・場所は再集計せず旧75を参照する。\n\n"
        + table(["政策", "期間", "政策理由別", "共通観測理由別", "親状態別", "形成状態別", "T/R純採用", "基本不適格理由観測"], reasons)
        + table(["政策", "期間", "採用時診断", "平均", "中央値", "最小", "最大"], ages)
        + "採用k経過秒は判断time−k.confirm、採用k終了経過秒は予定scheduled−k.end。tip距離は元親のtip_before_r−k終値を採用方向で符号付けた値で、TとRで同じ回復を意味しない。採用0は全統計null。最適年齢/距離を後から選んで採否へ戻さず、理由件数も複数重複を独立候補数へ足さない。\n\n"
        + "## 価格形成T/R別の先着と実帰属\n\n価格RはDI逆方向とは限らない。群内非重複は加算できず、政策全体の支持を群へ流用しない。観測円は既存実完結の帰属で、群だけを再運用した利益ではない。政策全体の品質留保を継承する。\n\n"
        + table(["政策", "期間", "形成", "純候補", "形unique", "仮約定", "250", "主率", "非重複約定", "非重複250", "非重複率", "日", "場", "群内支持", "実完結", "順行完結", "反転完結"], forms)
        + table(["政策", "期間", "形成", "観測0円", "観測5円", "観測10円"], formcost)
        + "## 前帯に対する場所の保存診断\n\n採用方向E*の位置で6群へ帰属。未知前帯も未知群として残す。場所は採否条件でなく、群内先着・非重複・支持と実完結は別の母数。群の観測額は実完結の帰属だけで、政策全体の品質注意/nullを継承し、群だけで再運用した額ではない。帯内/外を後付けの採用基準へ変更しない。\n\n"
        + table(["政策", "期間", "場所", "純候補", "仮約定", "250", "主率", "非重複約定", "非重複250", "非重複率", "日", "場", "群内支持", "実完結"], places)
        + table(["政策", "期間", "場所", "観測0円", "観測5円", "観測10円"], placecost)
        + "## 利益旗後赤字と独立250前の退出\n\n旗後赤はarmかつpnl5<0。同値は実返済価格=実新規、有利費用負けは実方向価格差>0かつ費用後負、不利は実方向価格差<0。要求から約定までの滑りの分類ではない。同一入口の250終端より前の実退出を分け、250先着を実現益と呼ばない。\n\n"
        + table(["政策", "期間", "利益旗", "旗後赤", "同値", "有利費用負け", "不利", "先着250前実退出"], protects)
        + "## 同枠の準備・純判断と実参加\n\nL0純TはL1へ包含する。実参加は一枚占有で変わるため包含を要求しない。共通元枠同方向と、実新規時刻/行/価格まで一致する厳密同新規を分ける。差額は右−左。Counterの不出現件数だけを0表示し、未知率・未知回収は補完しない。\n\n"
        + table(["左→右", "期間", "準備共通", "左準備のみ", "右準備のみ", "両同方向", "左純のみ", "右純のみ", "反対変更", "双方待機"], pure)
        + table(["左→右", "期間", "左完結", "右完結", "共通元枠同方向", "左のみ", "右のみ", "共通差額5円", "左のみ5円", "右のみ5円", "厳密同新規", "同新規出口差5円"], actual))


def reproduction() -> str:
    """純表示の再現手順と研究の限界を案内する。

    引数: なし。
    返り値: strは開始済み工程を再実行させないCLIと限定。
    """
    prefix = "work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/局所波の出生と切替/レポート.py"
    return ("## 再現と限界\n\n主・入力・監査の開始済み工程は再実行せず既存handleと証拠を確認する。正式主と監査成功後、次の純表示だけが結果/条件/証明/表示設定の小型JSONを読む。市場、詳細gzip、モデル、教師は開かない。\n\n```powershell\n"
        + prefix + "\n" + prefix + " --check\n```\n\n新fit0・新モデル0・新独立測定0、新一枚運用92＋保存参考92、Viewer184。旧55の先着/単独回収は同時計/方向/ATR_j/D/即時入口/出口へ厳密結合し、単体回収合算を実政策利益としない。未来ラベルは結果説明だけに使う。\n\n"
        "全66場既使用。初20専用を新評価に加えず、時系列20/条件選択24/既使用後続2場で評価する。新しい未使用期の確認は未了。売買両方向・政策間・同親/同形反復は独立標本ではない。旧readyには不要なOR/履歴/TVも含む。量0、前帯は診断のみ。複合結果をFastK/DI/ADX/ATR等の単独効果や心理の直測にしない。11月5日Day追加読取・新市場取得0。未使用セルは未使用・未検証であり無効の証拠ではない。\n\n")


# ----------------------------------------
def validate_proof(proof: dict, result_sha: str) -> None:
    """監査成功を結果指紋へ結合する。

    引数: proof(dict)は正式監査証明、result_sha(str)は結果bytesのSHA256。
    返り値: None。失敗・差・別結果を拒否する。
    """
    if proof["全件一致"] is not True or proof["不一致数"] != 0 or proof["不一致"] != [] or proof["結果SHA256"] != result_sha:
        raise ValueError("76の正式監査成功/結果SHA結合差")


def context_for() -> dict:
    """正式成功証明と結果SHAを結んでから小型正本を読む。

    引数: なし。
    返り値: dictは表示文脈。本物価格・モデル・圧縮詳細は読まない。
    """
    paths = [STUDY / name for name in ("結果.json", "条件.json", "保存物確認.json", "表示設定.json", "固定.json")]
    if any(not p.is_file() for p in paths):
        raise FileNotFoundError("76主と正式監査の成功後に表示すること")
    proof = read(paths[2])
    validate_proof(proof, sha(paths[0]))
    result, conditions, display = read(paths[0]), read(paths[1]), read(paths[3])
    validate_result(result)
    validate_display(display)
    if result["設定"] != conditions:
        raise ValueError("76結果と固定条件JSONの差")
    lock = read(paths[4])
    if result["固定SHA256"] != sha(paths[4]) or lock["ファイルSHA256"][DISPLAY.relative_to(ROOT).as_posix()] != sha(DISPLAY):
        raise ValueError("76表示設定の事前固定指紋差")
    sources = paths + [Path(__file__), PREVIOUS_PATH, PREVIOUS.V5_PATH(), V5.CATALOG, V5.MASTER,
                       STUDY / "検証計画.md", OLD / "設定と結果.md", *EXTERNAL]
    return {"result": result, "conditions": conditions, "display": display, "proof": proof, "sources": sources}


def documents(context: dict) -> dict[str, str]:
    """正本数値・表示metadata・固定説明から二本文をメモリ生成する。

    引数: context(dict)は正式又は人工文脈。
    返り値: dict[str,str]はREADME.mdと設定と結果.md。保存はしない。
    """
    r, detail, overview = context["result"], STUDY / "設定と結果.md", STUDY / "README.md"
    validate_result(r)
    rows = validate_display(context["display"])
    matrix = V5.matrix(V5.load_catalog(), detail, rows).replace("未使用", "未使用・未検証")
    decision = "新2政策の保存同時適格: " + (" / ".join(r["採用"]) if r["採用"] else "なし（目標未達）") + "。既使用期間の結果であり未使用期の達成証明ではない。\n\n"
    headline = table(["政策", "選択主先着", "非重複先着", "実完結", "観測5円", "確定5円", "主待ち", "保守上限"], [[p,
        str(r["候補"][p]["条件選択"]["入口"]["250"]) + "/" + str(r["候補"][p]["条件選択"]["入口"]["約定"]),
        str(r["候補"][p]["条件選択"]["入口"]["間引き250"]) + "/" + str(r["候補"][p]["条件選択"]["入口"]["間引き約定"]),
        r["候補"][p]["条件選択"]["運用"]["完結数"], money(r["候補"][p]["条件選択"]["運用"]["完結観測額円"]["5"]),
        money(r["候補"][p]["条件選択"]["運用"]["全体確定額円"]["5"]), rate(r["候補"][p]["条件選択"]["運用"]["主待ち率"]),
        rate(r["候補"][p]["条件選択"]["運用"]["待ち率保守上限"])] for p in POLICIES])
    settings_table = table(["設定ID", "手法", "尺度", "短い閾値/状態", "複合評価", "役割・限定"],
        [[x["設定ID"], "/".join(x["手法ID"]), "/".join(x["尺度ID"]), x["短記"], x["結果短記"], x["説明"]] for x in rows])
    references = ("## 保存参考と指紋\n\n" + link(OLD / "設定と結果.md", detail, "旧75 O0/P0の条件・設定・成績")
        + "。R01/R02の保存参考であり、新親波の条件ではない。旧Q0全64列・全木閾値を再転記せず、raw/派生モデルも新作しない。\n\n"
        + link(DISPLAY, detail, "表と短記の表示専用正本") + "から表セルと設定明細を同時に描画する。売買条件JSONは変更しない。\n\n"
        + table(["保存出典", "SHA256"], [[link(p, detail, p.relative_to(ROOT).as_posix()), sha(p)] for p in context["sources"]]))
    short = ("# 00076：局所波の押戻しと起点喪失を分ける\n\n当場の公開3足から親波を出生させ、起点が残る押戻し後Tと、同じ起点を失った後の反対確認Rを分ける。出生ATRと現在の取得・保護尺度を分離し、前帯は場所診断に限る。\n\n"
        + decision + axes() + "## 条件選択24場\n\n" + headline
        + link(detail, overview, "全期間・準備/親/形成・支持・費用と55×9表") + " / " + link(STUDY / "検証計画.md", overview, "事前計画")
        + " / " + link(STUDY / "一覧.resources.json", overview, "Viewer184資源") + "\n\n全66場既使用。純候補・仮約定・実完結を分け、品質null、利益旗後赤字、全予定活動を別評価する。\n\n" + reproduction())
    return {"README.md": short, "設定と結果.md": "# 00076：設定と結果\n\n" + decision + axes() + mechanics(detail)
        + "## 手法×尺度・版5全文\n\n全55手法×9尺度をコピーする。出生/押戻し/起点喪失は既存の価格構造へ記録し、新しい独立票とはしない。旧75 O0/P0の使用セルを保存参考として残す。\n\n"
        + matrix + "## 設定IDと複合評価\n\n" + settings_table + result_tables(context) + reproduction() + references}


def render(check: bool = False) -> dict:
    """正式成功後に二MDを保存又は再表示同byte照合する。

    引数: check(bool)は書込みなしの一致確認。
    返り値: dictは文書SHA/サイズ/リンク/表/入力不変の証明。
    """
    context = context_for()
    before = {p.relative_to(ROOT).as_posix(): sha(p) for p in context["sources"]}
    bodies = documents(context)
    catalog = V5.load_catalog()
    ids = {x["id"] for x in catalog["methods"]}
    matrix = [line for line in bodies["設定と結果.md"].splitlines() if line.startswith("| ") and len(line.split("|")) == 13 and line.split("|")[1].strip() in ids]
    if len(matrix) != 55 or {line.split("|")[1].strip() for line in matrix} != ids:
        raise ValueError("76版5の全55×9表が不完全")
    generated = {(STUDY / name).resolve() for name in bodies}
    links = sum(PREVIOUS.check_links(body, STUDY / name, generated) for name, body in bodies.items())
    if before != {p.relative_to(ROOT).as_posix(): sha(p) for p in context["sources"]}:
        raise ValueError("76表示中の入力変更")
    if not check and any((STUDY / name).exists() and (STUDY / name).read_bytes() != body.encode("utf-8") for name, body in bodies.items()):
        raise FileExistsError("76の異なる既存文書を上書きしない")
    reports = {}
    for name, body in bodies.items():
        path, data = STUDY / name, body.encode("utf-8")
        if check:
            if not path.is_file() or path.read_bytes() != data:
                raise ValueError("76再表示の同byte差:" + name)
        else:
            path.write_bytes(data)
        reports[name] = {"bytes": len(data), "SHA256": hashlib.sha256(data).hexdigest()}
    return {"成功": True, "文書": reports, "内部リンク検査": links, "欠落": 0, "版": 5, "手法": 55, "尺度": 9, "入力前後不変": True}


# ----------------------------------------
def fixture(active: bool = False) -> dict:
    """結果・原板を開かず0件又は1件の自己完結集計を作る。

    引数: active(bool)は全政策へ架空の同方向1件を置く指定。
    返り値: dictは市場と独立した表示文脈。
    """
    n = int(active)
    r = {"試行": 76, "全66場既使用": True, **COUNTS, "評価場": ["人工" + str(i) for i in range(46)],
         "候補": {}, "利益保護": {}, "技法被覆": {}, "形成別": {}, "場所別": {}, "比較": {}, "採用": []}
    for policy in POLICIES:
        r["候補"][policy], r["利益保護"][policy], r["技法被覆"][policy], r["形成別"][policy], r["場所別"][policy] = {}, {}, {}, {}, {}
        for period, scheduled in zip(PERIODS, (740, 888, 74)):
            e = {"候補": n, "約定": n, "250": n, "率": 1.0 if n else None, "間引き約定": n, "間引き250": n,
                 "間引き率": 1.0 if n else None, "日数": n, "場数": n, "支持": False, "70目標": False, "結果別": {"250": n} if n else {}}
            fees = {str(f): float(n * (1000 - 20 * f)) for f in (0, 5, 10)}
            o = {"予定枠": scheduled, "判断別": {"待ち": scheduled - n, "新規": n}, "待ち数": scheduled - n, "判定不能": 0,
                 "条件登録数": 0, "条件未約定": 0, "主待ち率": (scheduled - n) / scheduled, "待ち率保守上限": (scheduled - n) / scheduled,
                 "活動適格": False, "完結数": n, "未解消": 0, "完結観測額円": fees, "全体確定額円": deepcopy(fees), "品質注意場": [],
                 "役割別完結": {"順行": {"件数": n, "観測純額5": fees["5"]}, "反転": {"件数": 0, "観測純額5": 0.0}},
                 "利益起動件数": n, "起動後赤字件数5": 0, "買い": n, "売り": 0, "日数": n, "場数": n, "費用支持": False, "費用適格": False}
            r["候補"][policy][period] = {"入口": e, "運用": o, "同時適格": False}
            r["利益保護"][policy][period] = {"利益旗": n, "旗後赤": 0, "同値": 0, "有利費用負け": 0, "不利": 0, "先着250前の実退出": 0}
            if policy not in NEW:
                continue
            r["技法被覆"][policy][period] = {"定時枠": scheduled, "準備済み": n, "形観測": n, "形unique": n, "現在active観測": n,
                "適格方向": n, "順行": n, "反転": 0, "採用形unique": n, "理由別": {"人工準備": n, "人工不明": scheduled - n},
                "状態別": {"T有効": n} if n else {}, "形成別採用": {"T": n} if n else {}, "基礎準備": n, "追加未準備": 0,
                "親観測": n, "親unique": n, "親状態別": {"T有効": n} if n else {}, "起点喪失f観測": 0, "遅いf観測": 0,
                "観測理由別": {"人工準備": n, "人工不明": scheduled - n}, "基本不適格理由観測": {}, "採用親unique": n,
                "採用k経過秒": {k: 0.0 if n else None for k in ("平均", "中央値", "最小", "最大")}, "同形成最大反復枠": n,
                "採用k終了経過秒": {k: 0.0 if n else None for k in ("平均", "中央値", "最小", "最大")},
                "採用tip距離pt": {k: -1.0 if n else None for k in ("平均", "中央値", "最小", "最大")}, "reset観測": 0, "出生拒否観測": 0}
            r["形成別"][policy][period] = {}
            for kind in ("T", "R"):
                y = deepcopy(e)
                if kind == "R":
                    y.update(候補=0, 約定=0, 率=None, 間引き約定=0, 間引き250=0, 間引き率=None, 日数=0, 場数=0, 結果別={})
                    y["250"] = 0
                k = n if kind == "T" else 0
                r["形成別"][policy][period][kind] = {"純候補": k, "形unique": k, "入口": y, "実完結": k,
                    "費用別観測円": deepcopy(fees) if kind == "T" else {"0": 0.0, "5": 0.0, "10": 0.0}, "役割別完結": {"順行": k, "反転": 0}}
            r["場所別"][policy][period] = {}
            for where in PLACES:
                value = deepcopy(r["形成別"][policy][period]["T" if where == "未知" else "R"])
                r["場所別"][policy][period][where] = {key: value[key] for key in ("純候補", "入口", "実完結", "費用別観測円")}
    for left, right in PAIRS:
        r["比較"][left + "対" + right] = {period: {"準備共通": n, "左準備のみ": 0, "右準備のみ": 0,
            "純": {"同方向": n, "双方待機": scheduled - n}, "実": {"左完結": n, "右完結": n, "共通元枠同方向": n,
            "左のみ": 0, "右のみ": 0, "共通元枠差額5": 0.0, "左のみ額5": 0.0, "右のみ額5": 0.0,
            "厳密同新規": n, "厳密同新規出口差5": 0.0}} for period, scheduled in zip(PERIODS, (740, 888, 74))}
    conditions = {"試行": 76, "人工": True}
    r["設定"] = deepcopy(conditions)
    return {"result": r, "conditions": conditions, "display": read(DISPLAY), "proof": {"全件一致": True}, "sources": [DISPLAY, PREVIOUS_PATH]}


def self_test() -> dict:
    """市場0の人工で分母・費用・null・純包含・形成復元・全表を確認する。

    引数: なし。
    返り値: dictは成功/テスト件数/照合項目数/不一致数。
    """
    checks = tests = 0

    def check(condition: bool) -> None:
        """人工の必要条件を数える。

        引数: condition(bool)は満たすべき条件。
        返り値: None。偽ならAssertionError。
        """
        nonlocal checks
        checks += 1
        assert condition

    def reject(context: dict) -> None:
        """不整合な人工結果が表示前に拒否されることを確認する。

        引数: context(dict)は一箇所を壊した人工文脈。
        返り値: None。受理すればAssertionError。
        """
        nonlocal checks
        checks += 1
        try:
            validate_result(context["result"])
        except ValueError:
            return
        raise AssertionError("76不整合集計を受理")

    for active in (False, True):
        c = fixture(active)
        before = compact(c["result"])
        bodies = documents(c)
        check(before == compact(c["result"]))
        ids = {x["id"] for x in V5.load_catalog()["methods"]}
        matrix = [line for line in bodies["設定と結果.md"].splitlines() if line.startswith("| ") and len(line.split("|")) == 13 and line.split("|")[1].strip() in ids]
        check(len(matrix) == 55 and {line.split("|")[1].strip() for line in matrix} == ids)
        check(all(row["短記"] in bodies["設定と結果.md"] and row["設定ID"] in bodies["設定と結果.md"] for row in c["display"]["設定"]))
        check("出生ATR_b" in bodies["設定と結果.md"] and "実参加の包含は要求しない" in bodies["設定と結果.md"])
        tests += 1
    base = fixture(True)
    c = deepcopy(base)
    c["result"]["候補"]["L1"]["学習"]["入口"]["率"] = 0.0
    reject(c)
    c = fixture(False)
    c["result"]["候補"]["L0"]["条件選択"]["入口"]["率"] = 0.0
    reject(c)
    tests += 1
    for field in ("主待ち率", "完結観測額円"):
        c = deepcopy(base)
        o = c["result"]["候補"]["L0"]["学習"]["運用"]
        if field == "主待ち率":
            o[field] = 0.0
        else:
            o[field]["10"] += 1
        reject(c)
    c = deepcopy(base)
    o = c["result"]["候補"]["L0"]["学習"]["運用"]
    o["品質注意場"] = ["人工品質"]
    reject(c)
    o["全体確定額円"] = {str(f): None for f in (0, 5, 10)}
    validate_result(c["result"])
    check("null" in documents(c)["設定と結果.md"])
    tests += 1
    c = deepcopy(base)
    c["result"]["形成別"]["L1"]["条件選択"]["T"]["費用別観測円"]["5"] += 1
    reject(c)
    c = deepcopy(base)
    c["result"]["利益保護"]["L0"]["学習"]["同値"] = 1
    reject(c)
    c = deepcopy(base)
    c["result"]["比較"]["L0対L1"]["学習"]["実"]["共通元枠差額5"] = 1.0
    reject(c)
    tests += 1
    display = deepcopy(base["display"])
    display["設定"][1]["設定ID"] = display["設定"][0]["設定ID"]
    try:
        validate_display(display)
    except ValueError:
        checks += 1
    else:
        raise AssertionError("表示ID重複を受理")
    tests += 1
    c = deepcopy(base)
    for period in PERIODS:
        o = c["result"]["候補"]["L1"][period]["運用"]
        for key in ("完結数", "買い", "売り", "日数", "場数", "利益起動件数"):
            o[key] = 0
        for field in ("完結観測額円", "全体確定額円"):
            o[field] = {str(f): 0.0 for f in (0, 5, 10)}
        o["役割別完結"] = {role: {"件数": 0, "観測純額5": 0.0} for role in ("順行", "反転")}
        c["result"]["利益保護"]["L1"][period]["利益旗"] = 0
        for group in (c["result"]["形成別"]["L1"][period], c["result"]["場所別"]["L1"][period]):
            for value in group.values():
                value["実完結"] = 0
                value["費用別観測円"] = {str(f): 0.0 for f in (0, 5, 10)}
                if "役割別完結" in value:
                    value["役割別完結"] = {"順行": 0, "反転": 0}
        for left, right in PAIRS:
            if right == "L1":
                c["result"]["比較"][left + "対" + right][period]["実"].update(
                    右完結=0, 共通元枠同方向=0, 左のみ=1, 右のみ=0, 共通元枠差額5=0.0,
                    左のみ額5=900.0, 右のみ額5=0.0, 厳密同新規=0, 厳密同新規出口差5=0.0)
    validate_result(c["result"])
    check(c["result"]["比較"]["L0対L1"]["学習"]["実"]["左のみ"] == 1)
    tests += 1
    p = {"全件一致": True, "不一致数": 0, "不一致": [], "結果SHA256": "人工結果"}
    validate_proof(p, "人工結果")
    for key, value in (("全件一致", False), ("不一致数", 1), ("不一致", ["人工差"]), ("結果SHA256", "別結果")):
        bad = {**p, key: value}
        try:
            validate_proof(bad, "人工結果")
        except ValueError:
            checks += 1
        else:
            raise AssertionError("失敗又は別結果の証明を受理")
    output = STUDY / "設定と結果.md"
    check(PREVIOUS.check_links(link(DISPLAY, output, "表示正本"), output, set()) == 1)
    try:
        PREVIOUS.check_links("[不良](存在しない表示人工リンク.md)", output, set())
    except FileNotFoundError:
        checks += 1
    else:
        raise AssertionError("不良リンクを受理")
    tests += 1
    return {"成功": True, "テスト件数": tests, "照合項目数": checks, "不一致数": 0, "本物入力": False, "市場再生": False}


def main() -> None:
    """純描画・同byte確認又は市場0人工を選ぶ。

    引数: CLIの--check/--self-test(bool)は排他的な処理。
    返り値: None。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true")
    group.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    print(json.dumps(self_test() if args.self_test else render(args.check), ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
