"""77の成功済み小型正本を、停止76の純表示補助でMarkdownへ描画する。"""

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00077_押戻し再開の確認を早める"
OLD = ROOT / "study/00076_局所波の押戻しと起点喪失を分ける"
DISPLAY = STUDY / "表示設定.json"
INPUT_PROOF = ROOT / "work/押戻し再開の確認幅/入力確認.json"
PREVIOUS_PATH = ROOT / "scripts/局所波の出生と切替/レポート.py"
PREVIOUS_SHA256 = "c6bcaf504e00019b9a99f0497163c69dd153eed220ca6224a96559e735b8d2bc"
if hashlib.sha256(PREVIOUS_PATH.read_bytes()).hexdigest() != PREVIOUS_SHA256:
    raise ValueError("固定76純表示のSHA256不一致")
SPEC = importlib.util.spec_from_file_location("確認幅77の固定76純表示", PREVIOUS_PATH)
PREVIOUS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PREVIOUS
SPEC.loader.exec_module(PREVIOUS)
table, rate, money, flag, link, V5 = PREVIOUS.table, PREVIOUS.rate, PREVIOUS.money, PREVIOUS.flag, PREVIOUS.link, PREVIOUS.V5
POLICIES, NEW, PERIODS = ("L0", "L1", "E0", "E1"), ("E0", "E1"), PREVIOUS.PERIODS
PERIOD_NAMES = PREVIOUS.PERIOD_NAMES
PAIRS = (("L0", "E0"), ("L0", "E1"), ("L1", "E1"), ("E0", "E1"))
COUNTS = PREVIOUS.COUNTS
COVERAGE, PARENTS, PLACES, PURE_GROUPS = PREVIOUS.COVERAGE, PREVIOUS.PARENTS, PREVIOUS.PLACES, PREVIOUS.PURE_GROUPS
PROJECTION = dict(zip(POLICIES, PREVIOUS.POLICIES))
GROUPS = ("候補", "利益保護", "技法被覆", "形成別", "場所別")
EXTERNAL = (ROOT / "docs/議論/外部再調査/確認を待つ遅れと消耗の警告を分ける.md",)


def sha(path: Path) -> str:
    """表示に必要な小型入力のbyte指紋を得る。

    引数: path(Path)はコード又は小型正本。
    返り値: strはSHA256。圧縮詳細・市場を開かない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """許された小型JSONを読む。

    引数: path(Path)は結果/条件/証明/表示設定/固定。
    返り値: dictは保存辞書。
    """
    return json.loads(path.read_text(encoding="utf-8"))


def compact(value: object) -> str:
    """未知を補完せず保存辞書を短く表示する。

    引数: value(object)はJSON値。
    返り値: strはnullを含む固定表記。
    """
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def project_result(result: dict) -> dict:
    """政策名だけを局所辞書へ射影し、固定76検査核へ渡せる形にする。

    引数: result(dict)は77正本又は人工。
    返り値: dictは元辞書を変えない76同型の深写し。旧globalsを変更しない。
    """
    value = deepcopy(result)
    value["試行"] = 76
    for group in GROUPS:
        value[group] = {PROJECTION[p]: value[group][p] for p in POLICIES}
    value["比較"] = {PROJECTION[a] + "対" + PROJECTION[b]: value["比較"][a + "対" + b] for a, b in PAIRS}
    value["採用"] = [PROJECTION[p] for p in value["採用"]]
    return value


def validate_result(result: dict) -> None:
    """77の政策集合を確認し、共通六集計を固定純検査へ接続する。

    引数: result(dict)は77の小型結果。
    返り値: None。未知を0へ補完しない。
    """
    if result.get("試行") != 77 or set(result.get("候補", {})) != set(POLICIES) or not set(result.get("採用", [])) <= set(NEW):
        raise ValueError("77の試行/政策/採用集合差")
    if set(result.get("比較", {})) != {a + "対" + b for a, b in PAIRS}:
        raise ValueError("77の比較軸差")
    PREVIOUS.validate_result(project_result(result))
    for p in POLICIES[:2]:
        if any(result[group][p] for group in ("技法被覆", "形成別", "場所別")):
            raise ValueError("77の保存参考被覆は旧76へ参照する")
    entry = result["入力確認"]
    if (entry.get("試行") != 77 or entry.get("成功") is not True or entry.get("ラベルによる採否選択") is not False
            or any(type(entry.get(k)) is not int or entry[k] != 0 for k in ("出生ATR再計算", "新fit", "新独立測定", "新場内運用"))):
        raise ValueError("77入力段階の成功/計測境界差")
    sums = {"全予定": sum(result["技法被覆"]["E0"][h]["定時枠"] for h in PERIODS),
        "基礎準備": sum(result["技法被覆"]["E0"][h]["基礎準備"] for h in PERIODS),
        "局所準備": sum(result["技法被覆"]["E0"][h]["準備済み"] for h in PERIODS),
        "親履歴不変件数": sum(result["技法被覆"]["E0"][h]["親観測"] for h in PERIODS)}
    for p in NEW:
        sums[p + "方向"] = sum(result["候補"][p][h]["入口"]["候補"] for h in PERIODS)
    sums["R追加"] = sums["E1方向"] - sums["E0方向"]
    if any(type(entry.get(k)) is not int or entry[k] != value for k, value in sums.items()):
        raise ValueError("77入力段階と結果の準備/純方向/延べ親数差")


def validate_display(display: dict) -> list[dict]:
    """24設定と55手法/9尺度の対応を検査する。

    引数: display(dict)は独立した表示正本。
    返り値: list[dict]は深写しの設定行。条件JSONを編集しない。
    """
    catalog = V5.load_catalog()
    if (display.get("試行") != 77 or display.get("版") != 5
            or [(r["評価ID"], r["政策"]) for r in display["複合評価"]] != [(f"R{i:02d}", p) for i, p in enumerate(POLICIES, 1)]):
        raise ValueError("77表示設定の試行/評価ID/政策差")
    rows = display["設定"]
    methods, scales = {r["id"] for r in catalog["methods"]}, {r["id"] for r in catalog["scales"]}
    if len(rows) != 24 or len({r["設定ID"] for r in rows}) != 24:
        raise ValueError("77表示24設定の重複又は欠落")
    for row in rows:
        if set(row) != {"設定ID", "手法ID", "尺度ID", "短記", "結果短記", "説明"}:
            raise ValueError("77設定の項目差")
        if not row["手法ID"] or not set(row["手法ID"]) <= methods or not row["尺度ID"] or not set(row["尺度ID"]) <= scales:
            raise ValueError("77設定の手法/尺度差")
        if any(not isinstance(row[k], str) or not row[k] for k in ("設定ID", "短記", "結果短記", "説明")):
            raise ValueError("77表示短記の欠測")
    return deepcopy(rows)


# ----------------------------------------
def axes() -> str:
    """旧端突破と新終値反応、純包含と実参加を分ける。

    引数: なし。
    返り値: strは比較表と限定。
    """
    return ("## 比較の分離\n\n" + table(["政策/評価", "候補", "扱い"], [
        ["L0/R01", "76のr端突破Tのみ", "保存参考46運用"], ["L1/R02", "76の同親T/R", "保存参考46運用"],
        ["E0/R03", "最初の終値反応で確認するTのみ", "新46運用"], ["E1/R04", "同じ新親履歴のT/R", "新46運用"]])
        + "L0→E0/L1→E1はT確認だけの比較。L0→E1も診断し、E0→E1は同じ親機械へのR追加を分ける。"
        "E0純TはE1に同方向で含まれるが、一枚占有により実参加の包含は要求しない。親ID・形成ID一致だけでは同じkや同一売買ではない。\n\n")


def mechanics(output: Path) -> str:
    """T確認の変更と不変の因果入力・取消・執行を説明する。

    引数: output(Path)は本文リンクの出力先。
    返り値: strは77計画の説明。結果を予測しない。
    """
    return ("## T確認の一軸\n\n最初の押戻しrを固定し、その後の別の正常・隣接・期限内公開足iで、s(Ci−Cprevious)>0かつs(Ci−premise)>0となる最初の足をTのkとする。"
        "終値差0・premise等号は確認しない。買いpremise=max(origin,r.low)、売りpremise=min(origin,r.high)。最初rや初回kを取り直さない。"
        "小さな反応を早く確認して永久取消され、旧確認なら残った波を失う反例も比較に含む。\n\n"
        "Tのtrigger_lineはr固定端を診断として保持し、新確認線ではない。confirmation_rule='終値反応'、confirmation_previousはk直前SOURCE13、confirmation_lineはprevious.close。"
        "未確認ではprevious/lineはnull、確認後は凍結する。この3項目は親T・形成一覧・候補・採用Tへ接続する。RとWAITへ新T項目を混ぜない。"
        "どちらの線も注文発動線ではなく、O49の定時即時要求で現在BBOから取得する。過去kの価格へ新規を戻さない。\n\n"
        "## 出生・R・前提・寿命は不変\n\n3隣接足a/m/bの2終値差が同方向strict正、s(Cb−Ca)>=出生ATR_bで親を作る。originはa反対端。"
        "一場親1件、親存続中新bなし。最初r/fを固定し、終端/reset足を次aへ兼用せず後続3足で再出生する。"
        "Tのk前はoriginを保てばr反対端の一時喪失を許し、k後は同じpremiseの終値等号否定で永久取消。同じrから復活しない。\n\n"
        "origin喪失fはT確認より先。Rはf後1〜3別足の最初f実方向端strict終値突破を確認し、待機中のorigin再獲得を優先して終了する。"
        "Rの全辞書を76と厳密比較し、新T項目を追加しない。R確認後のpremiseは買max(origin,f.low)/売min(origin,f.high)。"
        "T戦術取消だけでは親を終了せず、同原因の起点喪失待ちを保つ。\n\n"
        "親期限はb.end+1620秒、未確認R期限はmin(f.end+540秒,親期限)。足end/公開confirm/実判断timeのstrict超を確認より先に終了、等号可。"
        "Rのk後は親期限、独立900秒gateは未使用。反復は独立イベント数ではない。\n\n"
        "## 同じ準備と現在の複数技法\n\n保存76の出生ATR参照を同じSOURCE13/hash/keyへ結び、再計算・複製しない。現在ATR_jを過去bへ戻さない。"
        "価格/出生ATR未知では親とbufferをclearし、新しい完全隣接3準備足で復帰する。正常終端後の出生待ちは未知と別である。"
        "end<=scheduled、公開key<=実判断を先に適用し、未来suffixや足内高安の順序を補完しない。\n\n"
        "旧73のfloat64 F01/02/03/07/15/47/48/51/52と現ATR_j/D、55当時quoteを維持。全T/RはF02>=0・F03>0・F07>0・非零DI。"
        "TはF01>0・F51=F52=1・F47>=0.20・F48>=0。F47はADX/100。RはDI同方向なら順行、逆ならF52=1・F48<0・F15>0を要する。"
        "価格T/RとDI役割を分け、F03解除を今回の確認変更と混ぜない。\n\n"
        "Last/E*（買ask/売bid）は正常でpremise strict側。距離<=D・中央250余地・新量gateは0。前帯は診断のみ、不明でもEreadyを下げない。"
        "76readyと同じ準備を要求するが、旧OR/15本履歴/TV等も継承する限界がある。量0。\n\n"
        "## 執行と費用\n\nDay09:15..15:15、Night17:30..05:30の15分判断。O49一枚即時、+1価格秒・後原行正常BBO、TTL30。"
        "D=5pt切上clip5..125は現在ATR_jによる値で、出生ATR_bとは別。損失非緩和、主費用後現在益strict正の利益旗と最低名目新規床、pending中h/L/arm凍結、強制返済を維持。"
        "micro代理1枚10円/pt、片道11円＋滑り5pt、主往復122円。0/10ptは同一約定の感応で、最低名目床は費用後黒字を保証しない。\n\n"
        + link(EXTERNAL[0], output, "確認遅れと消耗警告の一次資料・限定")
        + "。原典はこの確認式、3分/15分、250pt/125ptや70%を実証していない。追加外部調査も新gateへ遡及しない。\n\n")


def result_tables(context: dict) -> str:
    """同じ六集計を新政策名と新しい確認説明で表示する。

    引数: context(dict)は結果を含む純文脈。
    返り値: strは入口/費用/支持/被覆/利益保護/比較の全表。
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
    inp = r["入力確認"]
    input_fields = ("全予定", "基礎準備", "局所準備", "E0方向", "E1方向", "R追加", "親履歴不変件数", "出生ATR再計算")
    return ("## 入力段階の確認\n\n損益を結ぶ前に保存した準備と純候補。親履歴不変件数は各定時で比較した延べ親数で、unique親数ではない。出生/R不変と新T確認の差を分ける。\n\n"
        + table(list(input_fields), [[inp[k] for k in input_fields]])
        + "## 主先着・非重複と支持\n\n純候補→仮約定の250/125先着であり実戦略勝率ではない。仮約定0は率null。時系列は60約定/6日/10場/非重複20、選択・後続は20/3日/5場/非重複10。両率70%と支持を分ける。非重複の群別件数は加算しない。\n\n"
        + table(["政策", "期間", "純候補", "仮約定", "250", "主率", "非重複約定", "非重複250", "非重複率", "日", "場", "支持", "入口70条件"], entries)
        + "## 全予定活動と費用・品質\n\n全予定1702枠を分母に主待ち=WAIT/全予定、保守=(WAIT+判定不能+条件登録後entryなし)/全予定。保有・処理中は非待ち。全政策は即時なので条件登録/条件未約定0。\n\n"
        + table(["政策", "期間", "全予定", "判断別", "待ち", "判定不能", "条件登録", "条件未約定", "主待ち率", "保守上限", "活動適格", "実完結"], actions)
        + "費用0/5/10は同じ約定の片道滑り感応。観測小計と全体確定を分け、品質注意/未解消なら確定null。費用支持は時系列20完結/6日/10場/買売各5、選択・後続10/3日/6場/買売各3。主確定額strict正とは別条件。\n\n"
        + table(["政策", "期間", "観測0円", "観測5円", "観測10円", "確定0円", "確定5円", "確定10円", "未解消", "品質注意場"], costs)
        + table(["政策", "期間", "実完結", "買", "売", "日", "場", "費用支持", "費用適格", "同時適格"], support)
        + table(["政策", "期間", "DI実役割", "実完結", "観測5円"], roles)
        + "## 新確認の準備・親と形成\n\n76readyと新Ereadyを同じ準備で比較する。親/形成の観測は延べ数、unique親/形/採用形と支持は別分母。政策理由とE1代表の共通観測理由も分離する。旧L0/L1の被覆・形成・場所は旧76へ参照し再転記しない。\n\n"
        + table(["政策", "期間", "全予定", "E準備", "形観測", "形unique", "現在active", "純候補", "純順行", "純反転", "採用形unique"], coverage)
        + table(["政策", "期間", "基礎準備", "追加未準備", "親観測", "親unique", "起点喪失f観測", "遅いf観測", "採用親unique", "reset観測", "出生拒否観測", "同形成最大反復枠"], parents)
        + "起点喪失f観測は全f、遅いfは残0/1本の専用理由付き。各枠で見える過去履歴の反復であり独立イベント数ではない。\n\n"
        + table(["政策", "期間", "政策理由別", "共通観測理由別", "親状態別", "形成状態別", "T/R純採用", "基本不適格理由観測"], reasons)
        + table(["政策", "期間", "採用時診断", "平均", "中央値", "最小", "最大"], ages)
        + "k経過はactual−k.confirm、k終了経過はscheduled−k.end。tip距離は元親tip_before_rとk終値の方向差で、T/Rで同じ回復を意味しない。採用0は全統計null。年齢/距離を後から採否へ戻さない。\n\n"
        + "## 形成T/Rと実帰属\n\n価格RとDI反転を区別。群内支持を全体支持から補わず、群の観測額を別戦略の再運用利益としない。\n\n"
        + table(["政策", "期間", "形成", "純候補", "形unique", "仮約定", "250", "主率", "非重複約定", "非重複250", "非重複率", "日", "場", "群内支持", "実完結", "順行完結", "反転完結"], forms)
        + table(["政策", "期間", "形成", "観測0円", "観測5円", "観測10円"], formcost)
        + "## 前帯位置の保存診断\n\n当時の採用方向E*で帰属。不明は未知のまま。場所はgateでなく、群内非重複は非加算、群の円は実完結帰属のみ。全体品質の留保を継承し、未知を無限余地としない。\n\n"
        + table(["政策", "期間", "場所", "純候補", "仮約定", "250", "主率", "非重複約定", "非重複250", "非重複率", "日", "場", "群内支持", "実完結"], places)
        + table(["政策", "期間", "場所", "観測0円", "観測5円", "観測10円"], placecost)
        + "## 利益旗後赤と独立250前の退出\n\narmかつpnl5<0を、実価格同値/実方向価格差>0の有利費用負け/同差<0の不利に分ける。要求から約定までの滑り分類ではない。同入口の独立250前の実退出も別に示す。\n\n"
        + table(["政策", "期間", "利益旗", "旗後赤", "同値", "有利費用負け", "不利", "先着250前実退出"], protects)
        + "## 4比較の純判断と実参加\n\nE0純TはE1へ包含するが実参加包含は要求しない。旧/新Tは同じ親IDでもkが変わり得る。共通元枠同方向と実新規time/line/priceまで一致する厳密同新規を分ける。差額は右−左。Counter不出現だけ0とし未知率・未知回収は補完しない。\n\n"
        + table(["左→右", "期間", "準備共通", "左準備のみ", "右準備のみ", "両同方向", "左純のみ", "右純のみ", "反対変更", "双方待機"], pure)
        + table(["左→右", "期間", "左完結", "右完結", "共通元枠同方向", "左のみ", "右のみ", "共通差額5円", "左のみ5円", "右のみ5円", "厳密同新規", "同新規出口差5円"], actual))


def reproduction() -> str:
    """正式成功後の純表示手順と移植の限界を示す。

    引数: なし。
    返り値: strはCLIと限定。
    """
    prefix = "work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/押戻し再開の確認幅/レポート.py"
    return ("## 再現と限界\n\n開始済みの主・監査は再実行せずhandleと証拠を確認する。正式A成功後、純表示だけを実行する。\n\n```powershell\n"
        + prefix + "\n" + prefix + " --check\n```\n\n"
        "新fit0・モデル0・新独立測定0、新92一枚運用＋76保存参考92、Viewer184。市場・詳細gzip・モデル・教師は表示で読まない。"
        "旧55は同時計/side/ATR_j/Dの即時入口と出口へ厳密結合し、単独回収合算を政策利益にしない。\n\n"
        "全66場既使用。時系列20/条件選択24/既使用後続2場、初20専用を新評価へ加えない。新しい未使用期の確認は未了。"
        "旧OR/履歴/TVを含む旧73readyを継承し、必要最小準備へ広げた比較ではない。量0、前帯は診断のみ。"
        "複数の価格加工を独立票・心理の直測・指標単独の効果としない。11月5日Day追加読取・新市場取得0。未使用セルは未使用・未検証であり無効の証明ではない。\n\n")


# ----------------------------------------
def context_for() -> dict:
    """正式成功と表示設定の事前固定を確認して小型正本を読む。

    引数: なし。
    返り値: dictは表示文脈。正式A成功前は停止する。
    """
    paths = [STUDY / name for name in ("結果.json", "条件.json", "保存物確認.json", "表示設定.json", "固定.json")]
    if any(not p.is_file() for p in paths):
        raise FileNotFoundError("77主・正式監査成功後だけ表示する")
    proof = read(paths[2])
    PREVIOUS.validate_proof(proof, sha(paths[0]))
    result, conditions, display, lock = (read(p) for p in (paths[0], paths[1], paths[3], paths[4]))
    validate_result(result)
    validate_display(display)
    if result["設定"] != conditions or result["固定SHA256"] != sha(paths[4]):
        raise ValueError("77結果と条件/固定SHA差")
    if lock["ファイルSHA256"][DISPLAY.relative_to(ROOT).as_posix()] != sha(DISPLAY):
        raise ValueError("77表示設定の事前固定SHA差")
    if result["入力確認"] != read(INPUT_PROOF) or lock["ファイルSHA256"][INPUT_PROOF.relative_to(ROOT).as_posix()] != sha(INPUT_PROOF):
        raise ValueError("77保存入力確認と固定結果の結合差")
    prior_paths = [OLD / name for name in ("結果.json", "保存物確認.json")]
    prior, prior_proof = (read(p) for p in prior_paths)
    PREVIOUS.validate_proof(prior_proof, sha(prior_paths[0]))
    if lock["ファイルSHA256"][prior_paths[0].relative_to(ROOT).as_posix()] != sha(prior_paths[0]):
        raise ValueError("77固定と76参考結果SHA差")
    for policy in POLICIES[:2]:
        for group in ("候補", "利益保護"):
            if result[group][policy] != prior[group][policy]:
                raise ValueError("77保存参考と76正本の全文差")
    sources = paths + prior_paths + [INPUT_PROOF, Path(__file__), PREVIOUS_PATH, PREVIOUS.PREVIOUS.V5_PATH(), V5.CATALOG, V5.MASTER,
        STUDY / "検証計画.md", OLD / "設定と結果.md", *EXTERNAL]
    return {"result": result, "conditions": conditions, "display": display, "proof": proof, "sources": sources}


def documents(context: dict) -> dict[str, str]:
    """小型正本・表示metadataから二本文だけをメモリ生成する。

    引数: context(dict)は正式又は自己完結の人工文脈。
    返り値: dict[str,str]はREADME.md/設定と結果.md。ここでは書き込まない。
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
        money(r["候補"][p]["条件選択"]["運用"]["全体確定額円"]["5"]), rate(r["候補"][p]["条件選択"]["運用"]["主待ち率"]), rate(r["候補"][p]["条件選択"]["運用"]["待ち率保守上限"])] for p in POLICIES])
    settings = table(["設定ID", "手法", "尺度", "短い閾値/状態", "複合評価", "役割・限定"], [[x["設定ID"], "/".join(x["手法ID"]), "/".join(x["尺度ID"]), x["短記"], x["結果短記"], x["説明"]] for x in rows])
    references = ("## 保存参考と指紋\n\n" + link(OLD / "設定と結果.md", detail, "76 L0/L1の条件・設定・成績")
        + "。R01/R02は成功保存参考で、旧運用を再生しない。旧Q0全64列や全木閾値を再転記せず、新モデルもない。\n\n"
        + link(DISPLAY, detail, "表セルと短記の表示専用正本") + "から55×9表と全設定を描画し、条件JSONを変更しない。\n\n"
        + table(["保存出典", "SHA256"], [[link(p, detail, p.relative_to(ROOT).as_posix()), sha(p)] for p in context["sources"]]))
    short = ("# 00077：押戻し再開の確認を早める\n\n同じ出生・r・起点・寿命・現在技法・O49を保ち、Tの確認だけをr端突破から最初の実方向終値反応と前提維持へ変える。早期取消と定時取得の遅れも比較する。\n\n"
        + decision + axes() + "## 条件選択24場\n\n" + headline
        + link(detail, overview, "全期間・準備/親/形成・支持・費用と55×9表") + " / " + link(STUDY / "検証計画.md", overview, "事前計画")
        + " / " + link(STUDY / "一覧.resources.json", overview, "Viewer184資源") + "\n\n全66場既使用。純候補・仮約定・実完結、品質null、利益旗後赤字、全枠活動を分ける。\n\n" + reproduction())
    detail_body = ("# 00077：設定と結果\n\n" + decision + axes() + mechanics(detail)
        + "## 手法×尺度・版5全文\n\n全55手法×9尺度をコピー。旧76 L0/L1の使用セルを保存参考として残し、新確認を独立した技法票に増やさない。\n\n"
        + matrix + "## 設定IDと複合評価\n\n" + settings + result_tables(context) + reproduction() + references)
    return {"README.md": short, "設定と結果.md": detail_body}


def render(check: bool = False) -> dict:
    """正式成功後だけ文書を保存又は同byte検査する。

    引数: check(bool)は書き込みなしの再現確認。
    返り値: dictは文書SHA/リンク/表/入力不変の小型結果。
    """
    context = context_for()
    before = {p.relative_to(ROOT).as_posix(): sha(p) for p in context["sources"]}
    bodies = documents(context)
    ids = {m["id"] for m in V5.load_catalog()["methods"]}
    matrix = [line for line in bodies["設定と結果.md"].splitlines() if line.startswith("| ") and len(line.split("|")) == 13 and line.split("|")[1].strip() in ids]
    if len(matrix) != 55 or {line.split("|")[1].strip() for line in matrix} != ids:
        raise ValueError("77版5の55×9表が不完全")
    generated = {(STUDY / name).resolve() for name in bodies}
    links = sum(PREVIOUS.PREVIOUS.check_links(body, STUDY / name, generated) for name, body in bodies.items())
    if before != {p.relative_to(ROOT).as_posix(): sha(p) for p in context["sources"]}:
        raise ValueError("77表示中の入力変更")
    if not check and any((STUDY / name).exists() and (STUDY / name).read_bytes() != body.encode("utf-8") for name, body in bodies.items()):
        raise FileExistsError("77の異なる既存文書を上書きしない")
    reports = {}
    for name, body in bodies.items():
        path, data = STUDY / name, body.encode("utf-8")
        if check:
            if not path.is_file() or path.read_bytes() != data:
                raise ValueError("77再表示の同byte差:" + name)
        else:
            path.write_bytes(data)
        reports[name] = {"bytes": len(data), "SHA256": hashlib.sha256(data).hexdigest()}
    return {"成功": True, "文書": reports, "内部リンク検査": links, "欠落": 0, "版": 5, "手法": 55, "尺度": 9, "入力前後不変": True}


# ----------------------------------------
def fixture(active: bool = False) -> dict:
    """旧純人工の架空集計を政策名だけ77へ写す。

    引数: active(bool)は全政策に架空1件又は0件を置くか。
    返り値: dictは実結果を読まない自己完結文脈。
    """
    old = PREVIOUS.fixture(active)
    r = deepcopy(old["result"])
    inverse = {v: k for k, v in PROJECTION.items()}
    r["試行"] = 77
    for group in GROUPS:
        r[group] = {inverse[p]: value for p, value in r[group].items()}
    r["比較"] = {a + "対" + b: old["result"]["比較"][PROJECTION[a] + "対" + PROJECTION[b]] for a, b in PAIRS}
    r["設定"] = {"試行": 77, "人工": True}
    r["入力確認"] = {"試行": 77, "成功": True, "全予定": 1702, "基礎準備": 3 * int(active), "局所準備": 3 * int(active),
        "E0方向": 3 * int(active), "E1方向": 3 * int(active), "R追加": 0, "親履歴不変件数": 3 * int(active),
        "出生ATR再計算": 0, "新fit": 0, "新独立測定": 0, "新場内運用": 0, "ラベルによる採否選択": False}
    return {"result": r, "conditions": deepcopy(r["設定"]), "display": read(DISPLAY), "proof": {"全件一致": True}, "sources": [DISPLAY, PREVIOUS_PATH]}


def self_test() -> dict:
    """人工だけで表・分母・null・品質・政策対応と拒否を確認する。

    引数: なし。
    返り値: dictは成功/テスト件数/照合項目数。本物価格・結果・fitは0。
    """
    checks = tests = 0

    def check(value: bool) -> None:
        """人工の必要条件を比較する。

        引数: value(bool)は条件。
        返り値: None。偽なら停止する。
        """
        nonlocal checks
        checks += 1
        if not value:
            raise AssertionError("77表示人工の期待差")

    def reject(value: dict) -> None:
        """破壊した保存集計の受理を拒否する。

        引数: value(dict)は一箇所の不整合を持つ人工結果。
        返り値: None。
        """
        nonlocal checks
        checks += 1
        try:
            validate_result(value)
        except (ValueError, KeyError):
            return
        raise AssertionError("77の不整合を受理")

    for active in (False, True):
        c = fixture(active)
        before = compact(c["result"])
        docs = documents(c)
        check(compact(c["result"]) == before)
        ids = {m["id"] for m in V5.load_catalog()["methods"]}
        matrix = [line for line in docs["設定と結果.md"].splitlines() if line.startswith("| ") and len(line.split("|")) == 13 and line.split("|")[1].strip() in ids]
        check(len(matrix) == 55 and {line.split("|")[1].strip() for line in matrix} == ids)
        check(all(row["設定ID"] in docs["設定と結果.md"] and row["短記"] in docs["設定と結果.md"] for row in c["display"]["設定"]))
        for phrase in ("confirmation_previous", "previous.close", "r固定端", "実参加の包含は要求しない", "全66場既使用", "量0", "旧OR/履歴/TV", "F03解除"):
            check(phrase in docs["設定と結果.md"])
        check("E0→E1" in docs["設定と結果.md"] and "L0→E0" in docs["設定と結果.md"])
        tests += 1
    base = fixture(True)
    for field in ("rate", "money", "pure", "role", "coverage"):
        c = deepcopy(base["result"])
        if field == "rate":
            c["候補"]["E0"]["学習"]["入口"]["率"] = 0.0
        elif field == "money":
            c["候補"]["E1"]["学習"]["運用"]["完結観測額円"]["10"] += 1
        elif field == "pure":
            c["比較"]["E0対E1"]["学習"]["純"]["左のみ"] = 1
        elif field == "role":
            c["形成別"]["E0"]["学習"]["R"]["純候補"] = 1
        else:
            c["技法被覆"]["E1"]["学習"]["親unique"] += 2
        reject(c)
    tests += 1
    c = deepcopy(base)
    c["result"]["入力確認"]["親履歴不変件数"] += 1
    reject(c["result"])
    c = deepcopy(base)
    c["result"]["入力確認"]["ラベルによる採否選択"] = True
    reject(c["result"])
    tests += 1
    c = fixture(False)
    c["result"]["候補"]["E0"]["条件選択"]["入口"]["率"] = 0.0
    reject(c["result"])
    tests += 1
    c = deepcopy(base)
    for h in PERIODS:
        o = c["result"]["候補"]["E0"][h]["運用"]
        o["品質注意場"] = ["人工品質"]
        reject(c["result"])
        o["全体確定額円"] = {str(f): None for f in (0, 5, 10)}
        validate_result(c["result"])
    check("null" in documents(c)["設定と結果.md"])
    tests += 1
    c = deepcopy(base)
    for h in PERIODS:
        o = c["result"]["候補"]["E1"][h]["運用"]
        fees = {str(f): float(-100 - 20 * f) for f in (0, 5, 10)}
        o["完結観測額円"] = deepcopy(fees)
        o["全体確定額円"] = deepcopy(fees)
        o["役割別完結"]["順行"]["観測純額5"] = fees["5"]
        o["起動後赤字件数5"] = 1
        c["result"]["利益保護"]["E1"][h].update(旗後赤=1, 不利=1)
        c["result"]["形成別"]["E1"][h]["T"]["費用別観測円"] = deepcopy(fees)
        c["result"]["場所別"]["E1"][h]["未知"]["費用別観測円"] = deepcopy(fees)
        for left, right in PAIRS:
            if right == "E1":
                c["result"]["比較"][left + "対" + right][h]["実"].update(共通元枠差額5=-1100.0, 厳密同新規出口差5=-1100.0)
    validate_result(c["result"])
    check("-200" in documents(c)["設定と結果.md"])
    tests += 1
    display = deepcopy(base["display"])
    display["設定"][0]["設定ID"] = display["設定"][1]["設定ID"]
    try:
        validate_display(display)
    except ValueError:
        checks += 1
    else:
        raise AssertionError("77表示ID重複を受理")
    tests += 1
    proof = {"全件一致": True, "不一致数": 0, "不一致": [], "結果SHA256": "人工"}
    PREVIOUS.validate_proof(proof, "人工")
    for key, value in (("全件一致", False), ("不一致数", 1), ("結果SHA256", "別結果")):
        try:
            PREVIOUS.validate_proof({**proof, key: value}, "人工")
        except ValueError:
            checks += 1
        else:
            raise AssertionError("77の失敗証明を受理")
    tests += 1
    check(sha(PREVIOUS_PATH) == PREVIOUS_SHA256)
    target = STUDY / "設定と結果.md"
    check(PREVIOUS.PREVIOUS.check_links(link(DISPLAY, target, "表示正本"), target, set()) == 1)
    try:
        PREVIOUS.PREVIOUS.check_links("[不良](存在しない77表示人工リンク.md)", target, set())
    except FileNotFoundError:
        checks += 1
    else:
        raise AssertionError("77表示の不良リンクを受理")
    tests += 1
    return {"成功": True, "テスト件数": tests, "照合項目数": checks, "不一致数": 0, "本物入力": False, "新fit": 0, "市場再生": False, "正式生成": 0}


def main() -> None:
    """人工又は正式成功後の純表示を選ぶ。

    引数: CLI --self-test/--check(bool)は排他的な処理。
    返り値: None。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()
    print(json.dumps(self_test() if args.self_test else render(args.check), ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
