"""78の成功済み小型正本を、固定77の純表示核でMarkdownへ描画する。"""

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00078_ADXの水準と変化を分ける"
OLD = ROOT / "study/00077_押戻し再開の確認を早める"
DISPLAY = STUDY / "表示設定.json"
INPUT_PROOF = ROOT / "work/ADX水準と変化の資格/入力確認.json"
PREVIOUS_PATH = ROOT / "scripts/押戻し再開の確認幅/レポート.py"
PREVIOUS_SHA256 = "a8d858db75f57cbdd5f610ba259f9abaee8565552c151c9cadc7853893e42fc0"
if hashlib.sha256(PREVIOUS_PATH.read_bytes()).hexdigest() != PREVIOUS_SHA256:
    raise ValueError("固定77純表示のSHA256不一致")
SPEC = importlib.util.spec_from_file_location("ADX資格78の固定77純表示", PREVIOUS_PATH)
PREVIOUS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PREVIOUS
SPEC.loader.exec_module(PREVIOUS)
table, rate, money, flag, link, V5 = PREVIOUS.table, PREVIOUS.rate, PREVIOUS.money, PREVIOUS.flag, PREVIOUS.link, PREVIOUS.V5
POLICIES, NEW, PERIODS = ("E0", "E1", "S0", "S1"), ("S0", "S1"), PREVIOUS.PERIODS
PERIOD_NAMES = PREVIOUS.PERIOD_NAMES
PAIRS = (("E0", "S0"), ("E0", "S1"), ("E1", "S1"), ("S0", "S1"))
COUNTS = PREVIOUS.COUNTS
COVERAGE, PARENTS, PLACES, PURE_GROUPS = PREVIOUS.COVERAGE, PREVIOUS.PARENTS, PREVIOUS.PLACES, PREVIOUS.PURE_GROUPS
PROJECTION = dict(zip(POLICIES, PREVIOUS.POLICIES))
GROUPS = ("候補", "利益保護", "技法被覆", "形成別", "場所別")
EXTERNAL = (ROOT / "docs/議論/外部再調査/ADXの水準と変化を入口で分ける.md",)
CHECK_LINKS = PREVIOUS.PREVIOUS.PREVIOUS.check_links
VALIDATE_PROOF = PREVIOUS.PREVIOUS.validate_proof


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
    """政策と入力確認の識別だけを深写しへ射影し、固定77検査へ接続する。

    引数: result(dict)は78正本又は人工辞書。
    返り値: dictは元を変更しない77同型。旧globalsを変更しない。
    """
    value = deepcopy(result)
    value["試行"] = 77
    for group in GROUPS:
        value[group] = {PROJECTION[p]: value[group][p] for p in POLICIES}
    value["比較"] = {PROJECTION[a] + "対" + PROJECTION[b]: value["比較"][a + "対" + b] for a, b in PAIRS}
    value["採用"] = [PROJECTION[p] for p in value["採用"]]
    value["入力確認"]["試行"] = 77
    for p in NEW:
        value["入力確認"][PROJECTION[p] + "方向"] = result["入力確認"][p + "方向"]
    return value


def validate_result(result: dict) -> None:
    """78の識別と純包含を検査し、同じ六集計を固定77へ委譲する。

    引数: result(dict)は小型結果。未知率や金額を0補完しない。
    返り値: None。計測前入力と結果の不一致を拒否する。
    """
    if (result.get("試行") != 78 or set(result.get("候補", {})) != set(POLICIES)
            or not set(result.get("採用", [])) <= set(NEW)):
        raise ValueError("78の試行/政策/採用集合差")
    if set(result.get("比較", {})) != {a + "対" + b for a, b in PAIRS}:
        raise ValueError("78の比較軸差")
    if result.get("入力確認", {}).get("試行") != 78:
        raise ValueError("78入力確認の試行差")
    PREVIOUS.validate_result(project_result(result))
    for h in PERIODS:
        for pair in ("E0対S0", "E0対S1", "E1対S1", "S0対S1"):
            item = result["比較"][pair][h]
            if (item["純"].get("左のみ", 0) or item["純"].get("反対切替", 0)
                    or item["左準備のみ"] or item["右準備のみ"]):
                raise ValueError("78同準備/元純包含の差:" + pair)


def validate_display(display: dict) -> list[dict]:
    """24設定と55手法/9尺度の対応を検査する。

    引数: display(dict)は独立した表示正本。
    返り値: list[dict]は深写しの設定行。条件JSONを編集しない。
    """
    catalog = V5.load_catalog()
    if (display.get("試行") != 78 or display.get("版") != 5
            or [(r["評価ID"], r["政策"]) for r in display["複合評価"]] != [(f"R{i:02d}", p) for i, p in enumerate(POLICIES, 1)]):
        raise ValueError("78表示設定の試行/評価ID/政策差")
    rows = display["設定"]
    methods, scales = {r["id"] for r in catalog["methods"]}, {r["id"] for r in catalog["scales"]}
    if len(rows) != 24 or len({r["設定ID"] for r in rows}) != 24:
        raise ValueError("78表示24設定の重複又は欠落")
    for row in rows:
        if set(row) != {"設定ID", "手法ID", "尺度ID", "短記", "結果短記", "説明"}:
            raise ValueError("78設定の項目差")
        if not row["手法ID"] or not set(row["手法ID"]) <= methods or not row["尺度ID"] or not set(row["尺度ID"]) <= scales:
            raise ValueError("78設定の手法/尺度差")
        if any(not isinstance(row[k], str) or not row[k] for k in ("設定ID", "短記", "結果短記", "説明")):
            raise ValueError("78表示短記の欠測")
    return deepcopy(rows)


# ----------------------------------------


# ----------------------------------------
def axes() -> str:
    """TのADX非減速資格とR追加、純包含と一枚占有を分ける。

    引数: なし。
    返り値: strは比較表と限定。
    """
    return ("## 比較の分離\n\n" + table(["政策/評価", "TのADX資格・形成", "扱い"], [
        ["E0/R01", "F48>=0を保つ終値反応Tのみ", "77保存参考46運用"],
        ["E1/R02", "同じTと同原因R", "77保存参考46運用"],
        ["S0/R03", "F48符号を要求しない同じTのみ", "新46運用"],
        ["S1/R04", "同じ新T資格と元同値R", "新46運用"]])
        + "E0→S0/E1→S1はTのF48>=0だけを要求解除する比較。E0→S1も診断し、S0→S1は同じ親機械へのR追加を分ける。"
        "F48=0は元から許す。純T包含と一枚占有後の実参加包含は別で、実参加の包含は要求しない。\n\n")


def mechanics(output: Path) -> str:
    """ADX水準・変化と不変の価格確認・R・執行を説明する。

    引数: output(Path)は本文リンクの出力先。
    返り値: strは78計画の説明。外部資料から利益を予測しない。
    """
    return ("## ADX資格の一軸\n\nF47=ADX/100、F48=公開15分足のADX現前差/100。S0/S1のTはF48>=0だけを要求しない。"
        "F51=F52=1・F47>=0.20・F01>0は維持し、未知0を既知の減速として通さない。F48=0は元から許可され、上昇必須ではなく非減速必須の解除である。"
        "ADX低下はDI方向の逆転や反転成立ではない。強い流れの調整を拾う可能性と、古い高水準・消耗・弱い波を増やす反例を分ける。"
        "ADXとその差は売買反射で符号反転しない。数値閾値やADX期間は追加探索しない。\n\n"
        "全T/RのF02>=0・F03>0・F07>0・非零DI、正常Last/E*のpremise strict側を維持。F03解除は混ぜない。"
        "RはDI同方向なら順行、逆方向ならF52=1・F48<0・F15>0で、逆向Rの減速条件は解除しない。"
        "F48は観測に残るが新Tの符号gateではない。親・形成・候補・履歴・出生ATR・場所とR資格は77同値を要求する。\n\n"
        "## 出生・確認・取消・寿命は不変\n\n3隣接足a/m/bの2終値差が同方向strict正、s(Cb−Ca)>=出生ATR_bで親を作る。originはa反対端。"
        "一場親1件、親存続中新bなし。最初r/fを固定し、終端/reset足を次aへ兼用せず後続3足で再出生する。"
        "Tはr後の別足でs(Ci−Cprevious)>0かつs(Ci−premise)>0となる最初の終値反応をkとする。"
        "買いpremise=max(origin,r.low)、売りpremise=min(origin,r.high)。k前はoriginだけを保ち、k後はpremise終値等号否定で永久取消する。\n\n"
        "Tのtrigger_lineはr固定端の診断。confirmation_rule='終値反応'、confirmation_previousはk直前SOURCE13、confirmation_lineはprevious.closeを凍結。"
        "これらは注文発動線ではなく、過去kの価格へ取得を戻さない。RとWAITへTの3項目を混ぜない。"
        "origin喪失fはTより優先。Rはf後1〜3別足で最初f実方向端strict終値突破、待機中origin再獲得で終了、同f復活なし。"
        "T戦術取消だけではR成立にしない。Rのpremiseは買max(origin,f.low)/売min(origin,f.high)。\n\n"
        "親期限b.end+1620秒、未確認R期限min(f.end+540秒,親期限)。足end/公開confirm/実判断timeのstrict超を確認より先に終了、等号可。"
        "Rのk後は親期限で、独立900秒gateは未使用。反復は独立イベント数ではない。\n\n"
        "## 同じ準備・価格時計\n\n保存76出生ATRをSOURCE13/hash/keyへ固定参照し、現在ATR_jをbへ戻さない。"
        "価格/出生ATR未知では親とbufferをclearし、新しい完全隣接3準備足で復帰。正常終端後の出生待ちは未知と別。"
        "end<=scheduled、公開key<=実判断を先に適用し、未来suffixや足内高安の順序を補わない。"
        "旧73のfloat64 F01/02/03/07/15/47/48/51/52と現ATR_j/D、55当時quoteを維持。"
        "77readyと同じ準備で、旧OR/履歴/TV等を含む不要履歴の継承限界も残る。前帯は診断のみ、不明でSreadyを落とさない。量0。\n\n"
        "## 執行と費用\n\nDay09:15..15:15、Night17:30..05:30の15分判断。O49一枚即時、+1価格秒・後原行正常BBO、TTL30等号可。"
        "D=5pt切上clip5..125は現在ATR_j由来で出生ATR_bとは別。損失非緩和、主費用後現在益strict正で利益旗、最低名目新規床、返済pending中h/L/arm凍結と強制返済を維持。"
        "micro代理1枚10円/pt、片道11円＋滑り5pt、主往復122円。0/10ptは同じ約定の費用感応で、最低名目床は費用後黒字を保証しない。\n\n"
        + link(EXTERNAL[0], output, "ADX水準と変化の公式再確認・限定")
        + "。公式本文はこの資格解除、3分/15分、250/125や70%を実証していない。後続調査を新gateへ遡及しない。\n\n")


def result_tables(context: dict) -> str:
    """同じ六集計を新政策名とADX資格説明で表示する。

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
    input_fields = ("全予定", "基礎準備", "局所準備", "S0方向", "S1方向", "R追加", "親履歴不変件数", "出生ATR再計算")
    return ("## 入力段階の確認\n\n損益を結ぶ前に保存した準備と純候補。親履歴不変件数は各定時で比較した延べ親数で、unique親数ではない。価格機械/R不変と新T資格の差を分ける。\n\n"
        + table(list(input_fields), [[inp[k] for k in input_fields]])
        + "## 主先着・非重複と支持\n\n純候補→仮約定の250/125先着であり実戦略勝率ではない。仮約定0は率null。時系列は60約定/6日/10場/非重複20、選択・後続は20/3日/5場/非重複10。両率70%と支持を分ける。非重複の群別件数は加算しない。\n\n"
        + table(["政策", "期間", "純候補", "仮約定", "250", "主率", "非重複約定", "非重複250", "非重複率", "日", "場", "支持", "入口70条件"], entries)
        + "## 全予定活動と費用・品質\n\n全予定1702枠を分母に主待ち=WAIT/全予定、保守=(WAIT+判定不能+条件登録後entryなし)/全予定。保有・処理中は非待ち。全政策は即時なので条件登録/条件未約定0。\n\n"
        + table(["政策", "期間", "全予定", "判断別", "待ち", "判定不能", "条件登録", "条件未約定", "主待ち率", "保守上限", "活動適格", "実完結"], actions)
        + "費用0/5/10は同じ約定の片道滑り感応。観測小計と全体確定を分け、品質注意/未解消なら確定null。費用支持は時系列20完結/6日/10場/買売各5、選択・後続10/3日/6場/買売各3。主確定額strict正とは別条件。\n\n"
        + table(["政策", "期間", "観測0円", "観測5円", "観測10円", "確定0円", "確定5円", "確定10円", "未解消", "品質注意場"], costs)
        + table(["政策", "期間", "実完結", "買", "売", "日", "場", "費用支持", "費用適格", "同時適格"], support)
        + table(["政策", "期間", "DI実役割", "実完結", "観測5円"], roles)
        + "## 同じ準備・親と形成と新資格\n\n77readyと新Sreadyを同じ準備で比較する。親/形成の観測は延べ数、unique親/形/採用形と支持は別分母。政策理由とS1代表の共通観測理由も分離する。旧E0/E1の被覆・形成・場所は旧77へ参照し再転記しない。\n\n"
        + table(["政策", "期間", "全予定", "S準備", "形観測", "形unique", "現在active", "純候補", "純順行", "純反転", "採用形unique"], coverage)
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
        + "## 4比較の純判断と実参加\n\n元E純は対応Sへ、S0純TはS1へ同方向で含むが実参加包含は要求しない。親/形成/kは不変で、変化するのは現在T資格だけである。共通元枠同方向と実新規time/line/priceまで一致する厳密同新規を分ける。差額は右−左。Counter不出現だけ0とし未知率・未知回収は補完しない。\n\n"
        + table(["左→右", "期間", "準備共通", "左準備のみ", "右準備のみ", "両同方向", "左純のみ", "右純のみ", "反対変更", "双方待機"], pure)
        + table(["左→右", "期間", "左完結", "右完結", "共通元枠同方向", "左のみ", "右のみ", "共通差額5円", "左のみ5円", "右のみ5円", "厳密同新規", "同新規出口差5円"], actual))


def reproduction() -> str:
    """正式監査後の表示CLIと再利用範囲を示す。

    引数: なし。
    返り値: strはCLI・使用済み期間・移植の限定。
    """
    prefix = "work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/ADX水準と変化の資格/レポート.py"
    return ("## 再現と限界\n\n開始済みの主・監査は再実行せずhandleと証拠を確認し、正式A成功後に表示だけを行う。\n\n```powershell\n"
        + prefix + "\n" + prefix + " --check\n```\n\n"
        "新fit0・モデル0・新独立測定0、新92一枚運用＋77保存参考92、Viewer184。表示は市場・詳細gzip・モデル・教師を読まない。"
        "旧55は同時計/side/ATR_j/Dの即時入口と出口へ厳密結合し、単独回収合算を政策利益にしない。\n\n"
        "全66場既使用。時系列20/条件選択24/既使用後続2場、初20専用を新評価へ加えない。未使用期の全目標確認は未了。"
        "旧OR/履歴/TVを含む旧73readyを継承し、必要最小準備へ広げた比較ではない。量0、前帯は診断のみ。"
        "複数の価格加工を独立票・心理の直測・指標単独効果としない。11月5日Day追加読取・新市場取得0。未使用・未検証セルは無効の証明ではない。\n\n")


# ----------------------------------------
def context_for() -> dict:
    """正式成功と表示設定の固定を小型正本へ結合する。

    引数: なし。
    返り値: dictは純表示文脈。A成功前は停止する。
    """
    paths = [STUDY / name for name in ("結果.json", "条件.json", "保存物確認.json", "表示設定.json", "固定.json")]
    if any(not p.is_file() for p in paths):
        raise FileNotFoundError("78主・正式監査成功後だけ表示する")
    proof = read(paths[2])
    VALIDATE_PROOF(proof, sha(paths[0]))
    result, conditions, display, lock = (read(p) for p in (paths[0], paths[1], paths[3], paths[4]))
    validate_result(result)
    validate_display(display)
    if result["設定"] != conditions or result["固定SHA256"] != sha(paths[4]):
        raise ValueError("78結果と条件/固定SHA差")
    for path in (DISPLAY, INPUT_PROOF):
        if lock["ファイルSHA256"][path.relative_to(ROOT).as_posix()] != sha(path):
            raise ValueError("78表示/入力確認の事前固定SHA差")
    if result["入力確認"] != read(INPUT_PROOF):
        raise ValueError("78入力確認と結果の全文差")
    prior_paths = [OLD / name for name in ("結果.json", "保存物確認.json")]
    prior, prior_proof = (read(p) for p in prior_paths)
    VALIDATE_PROOF(prior_proof, sha(prior_paths[0]))
    if lock["ファイルSHA256"][prior_paths[0].relative_to(ROOT).as_posix()] != sha(prior_paths[0]):
        raise ValueError("78固定と77参考結果SHA差")
    for policy in POLICIES[:2]:
        for group in ("候補", "利益保護"):
            if result[group][policy] != prior[group][policy]:
                raise ValueError("78保存参考と77正本の全文差")
    sources = paths + prior_paths + [INPUT_PROOF, Path(__file__), PREVIOUS_PATH,
        PREVIOUS.PREVIOUS.PREVIOUS.V5_PATH(), V5.CATALOG, V5.MASTER,
        STUDY / "検証計画.md", OLD / "設定と結果.md", *EXTERNAL]
    return {"result": result, "conditions": conditions, "display": display, "proof": proof, "sources": sources}


def documents(context: dict) -> dict[str, str]:
    """保存六集計と独立表示metadataから二本文をメモリ生成する。

    引数: context(dict)は正式又は自己完結の人工文脈。
    返り値: dict[str,str]はREADME/設定と結果本文。ここでは書き込まない。
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
    references = ("## 保存参考と指紋\n\n" + link(OLD / "設定と結果.md", detail, "77 E0/E1の条件・設定・成績")
        + "。R01/R02は保存参考で、旧運用を再生しない。旧Q0全64列や木全閾値を再転記せず、新モデルもない。\n\n"
        + link(DISPLAY, detail, "表セルと短記の表示専用正本") + "から55×9表と全設定を描画し、条件JSONを変更しない。\n\n"
        + table(["保存出典", "SHA256"], [[link(p, detail, p.relative_to(ROOT).as_posix()), sha(p)] for p in context["sources"]]))
    short = ("# 00078：ADXの水準と変化を分ける\n\n同じ価格機械・確認・現在技法・O49を保ち、TのADX非減速F48>=0だけを要求解除する。ADX水準と既知性、R逆DI時の減速条件は維持する。\n\n"
        + decision + axes() + "## 条件選択24場\n\n" + headline
        + link(detail, overview, "全期間・準備/親/形成・支持・費用と55×9表") + " / " + link(STUDY / "検証計画.md", overview, "事前計画")
        + " / " + link(STUDY / "一覧.resources.json", overview, "Viewer184資源")
        + "\n\n全66場既使用。純候補・仮約定・実完結、品質null、利益旗後赤字、全枠活動を分ける。\n\n" + reproduction())
    detail_body = ("# 00078：設定と結果\n\n" + decision + axes() + mechanics(detail)
        + "## 手法×尺度・版5全文\n\n全55手法×9尺度をコピー。旧77 E0/E1の使用セルを保存参考として残し、資格解除を独立した技法票に増やさない。\n\n"
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
        raise ValueError("78版5の55×9表が不完全")
    generated = {(STUDY / name).resolve() for name in bodies}
    links = sum(CHECK_LINKS(body, STUDY / name, generated) for name, body in bodies.items())
    if before != {p.relative_to(ROOT).as_posix(): sha(p) for p in context["sources"]}:
        raise ValueError("78表示中の入力変更")
    if not check and any((STUDY / name).exists() and (STUDY / name).read_bytes() != body.encode("utf-8") for name, body in bodies.items()):
        raise FileExistsError("78の異なる既存文書を上書きしない")
    reports = {}
    for name, body in bodies.items():
        path, data = STUDY / name, body.encode("utf-8")
        if check:
            if not path.is_file() or path.read_bytes() != data:
                raise ValueError("78再表示の同byte差:" + name)
        else:
            path.write_bytes(data)
        reports[name] = {"bytes": len(data), "SHA256": hashlib.sha256(data).hexdigest()}
    return {"成功": True, "文書": reports, "内部リンク検査": links, "欠落": 0, "版": 5, "手法": 55, "尺度": 9, "入力前後不変": True}


# ----------------------------------------


# ----------------------------------------
def fixture(active: bool = False) -> dict:
    """固定77の架空集計だけを78政策へ写す。

    引数: active(bool)は全政策に架空1件又は0件を置くか。
    返り値: dictは本物結果を読まない自己完結文脈。
    """
    old = PREVIOUS.fixture(active)
    r = deepcopy(old["result"])
    inverse = {v: k for k, v in PROJECTION.items()}
    r["試行"] = 78
    for group in GROUPS:
        r[group] = {inverse[p]: value for p, value in r[group].items()}
    r["比較"] = {a + "対" + b: deepcopy(old["result"]["比較"][PROJECTION[a] + "対" + PROJECTION[b]]) for a, b in PAIRS}
    r["設定"] = {"試行": 78, "人工": True}
    r["入力確認"] = deepcopy(old["result"]["入力確認"])
    r["入力確認"]["試行"] = 78
    for p in NEW:
        r["入力確認"][p + "方向"] = r["入力確認"].pop(PROJECTION[p] + "方向")
    return {"result": r, "conditions": deepcopy(r["設定"]), "display": read(DISPLAY), "proof": {"全件一致": True}, "sources": [DISPLAY, PREVIOUS_PATH]}


def self_test() -> dict:
    """人工だけで政策・表全体・null・費用・設定と拒否を検査する。

    引数: なし。
    返り値: dictは成功/テスト件数/照合項目数。本物価格/結果/fitは0。
    """
    checks = tests = 0

    def check(value: bool) -> None:
        """人工条件を数えて偽を拒否する。

        引数: value(bool)は期待比較。
        返り値: None。
        """
        nonlocal checks
        checks += 1
        if not value:
            raise AssertionError("78表示人工の期待差")

    def reject(value: dict) -> None:
        """破壊した小型結果を拒否する。

        引数: value(dict)は人工結果。
        返り値: None。受理したら停止する。
        """
        nonlocal checks
        checks += 1
        try:
            validate_result(value)
        except (ValueError, KeyError):
            return
        raise AssertionError("78の不整合を受理")

    for active in (False, True):
        c = fixture(active)
        before = compact(c["result"])
        docs = documents(c)
        check(before == compact(c["result"]))
        ids = {m["id"] for m in V5.load_catalog()["methods"]}
        matrix = [line for line in docs["設定と結果.md"].splitlines() if line.startswith("| ") and len(line.split("|")) == 13 and line.split("|")[1].strip() in ids]
        check(len(matrix) == 55 and {line.split("|")[1].strip() for line in matrix} == ids)
        check(all(row["設定ID"] in docs["設定と結果.md"] and row["短記"] in docs["設定と結果.md"] for row in c["display"]["設定"]))
        for phrase in ("F48=0は元から", "F51=F52=1", "逆方向ならF52=1・F48<0", "全66場既使用", "量0", "旧OR/履歴/TV", "実参加の包含は要求しない", "previous.close", "F03解除"):
            check(phrase in docs["設定と結果.md"])
        check(all(a + "→" + b in docs["設定と結果.md"] for a, b in PAIRS))
        check("T確認だけを変更" not in docs["設定と結果.md"])
        tests += 1
    base = fixture(True)
    for field in ("rate", "money", "role", "coverage", "input", "trial"):
        c = deepcopy(base["result"])
        if field == "rate":
            c["候補"]["S0"]["学習"]["入口"]["率"] = 0.0
        elif field == "money":
            c["候補"]["S1"]["学習"]["運用"]["完結観測額円"]["10"] += 1
        elif field == "role":
            c["形成別"]["S0"]["学習"]["R"]["純候補"] = 1
        elif field == "coverage":
            c["技法被覆"]["S1"]["学習"]["親unique"] += 2
        elif field == "input":
            c["入力確認"]["親履歴不変件数"] += 1
        else:
            c["入力確認"]["試行"] = 77
        reject(c)
    tests += 1
    c = fixture(False)
    c["result"]["候補"]["S0"]["条件選択"]["入口"]["率"] = 0.0
    reject(c["result"])
    tests += 1
    c = deepcopy(base)
    for h in PERIODS:
        o = c["result"]["候補"]["S0"][h]["運用"]
        o["品質注意場"] = ["人工品質"]
        reject(c["result"])
        o["全体確定額円"] = {str(f): None for f in (0, 5, 10)}
        validate_result(c["result"])
    check("null" in documents(c)["設定と結果.md"])
    tests += 1
    c = deepcopy(base)
    for h in PERIODS:
        o = c["result"]["候補"]["S1"][h]["運用"]
        fees = {str(f): float(-100 - 20 * f) for f in (0, 5, 10)}
        o["完結観測額円"] = deepcopy(fees)
        o["全体確定額円"] = deepcopy(fees)
        o["役割別完結"]["順行"]["観測純額5"] = fees["5"]
        o["起動後赤字件数5"] = 1
        c["result"]["利益保護"]["S1"][h].update(旗後赤=1, 不利=1)
        c["result"]["形成別"]["S1"][h]["T"]["費用別観測円"] = deepcopy(fees)
        c["result"]["場所別"]["S1"][h]["未知"]["費用別観測円"] = deepcopy(fees)
        for left, right in PAIRS:
            if right == "S1":
                c["result"]["比較"][left + "対" + right][h]["実"].update(共通元枠差額5=-1100.0, 厳密同新規出口差5=-1100.0)
    validate_result(c["result"])
    check("-200" in documents(c)["設定と結果.md"])
    tests += 1
    c = deepcopy(base)
    c["result"]["入力確認"]["ラベルによる採否選択"] = True
    reject(c["result"])
    display = deepcopy(c["display"])
    display["設定"][0]["設定ID"] = display["設定"][1]["設定ID"]
    try:
        validate_display(display)
    except ValueError:
        checks += 1
    else:
        raise AssertionError("78表示ID重複を受理")
    tests += 1
    proof = {"全件一致": True, "不一致数": 0, "不一致": [], "結果SHA256": "人工"}
    VALIDATE_PROOF(proof, "人工")
    for key, value in (("全件一致", False), ("不一致数", 1), ("結果SHA256", "別結果")):
        try:
            VALIDATE_PROOF({**proof, key: value}, "人工")
        except ValueError:
            checks += 1
        else:
            raise AssertionError("78の失敗証明を受理")
    tests += 1
    check(sha(PREVIOUS_PATH) == PREVIOUS_SHA256)
    target = STUDY / "設定と結果.md"
    check(CHECK_LINKS(link(DISPLAY, target, "表示正本"), target, set()) == 1)
    try:
        CHECK_LINKS("[不良](存在しない78表示人工リンク.md)", target, set())
    except FileNotFoundError:
        checks += 1
    else:
        raise AssertionError("78表示の不良リンクを受理")
    tests += 1
    check(PREVIOUS.self_test()["成功"] is True)
    tests += 1
    return {"成功": True, "テスト件数": tests, "照合項目数": checks, "不一致数": 0,
        "本物入力": False, "新fit": 0, "市場再生": False, "正式生成": 0}


def main() -> None:
    """人工又は監査成功後の正式純表示を選ぶ。

    引数: CLI --self-test/--check(bool)は排他的。
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
