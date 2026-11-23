"""50の保存結果だけを、参照対照と新二候補を分けた二文書へ表示する。"""

import argparse
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
STUDY = ROOT / "study/00050_15分定時の局所再開"
OLD = ROOT / "study/00049_15分定時の序盤帯反応"
POLICIES = ("S1", "P0", "P1")
NEW_POLICIES = ("P0", "P1")
PERIODS = ("学習", "条件選択", "後続検査")
ROLES = ("順行", "反転")
EVALUATIONS = {"S1": "R01", "P0": "R02", "P1": "R03"}
SPEC = importlib.util.spec_from_file_location("局所再開の固定版5描画", ROOT / "scripts/レポート/カタログ版5.py")
V5 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = V5
SPEC.loader.exec_module(V5)


def sha(path: Path) -> str:
    """保存出典の内容指紋を得る。

    引数: path(Path)は保存ファイル。
    返り値: strはSHA256。原板/cacheを読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    """有限JSONの小型正本だけを読む。

    引数: path(Path)は結果・条件等。
    返り値: dictはJSON。市場/先着/運用を生成しない。
    """
    def invalid(value: str) -> None:
        """非標準の非有限JSON値を拒否する。

        引数: value(str)は不正表記。
        返り値: None。必ずValueError。
        """
        raise ValueError("非有限JSON: " + value)
    value = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=invalid)
    if not isinstance(value, dict):
        raise ValueError("JSON正本は辞書が必要")
    return value


def cell(value: object) -> str:
    """値をMarkdown表の一セルへ写す。

    引数: value(object)は保存値。
    返り値: strは改行と縦棒を処理した表示。
    """
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":")) if isinstance(value, (dict, list)) else str(value)
    return text.replace("|", "&#124;").replace("\r", "").replace("\n", "<br>")


def number(value: float | int | None, digits: int = 0) -> str:
    """未保存値を0へ補完せず数値を表示する。

    引数: value(float|int|None)は値、digits(int)は小数桁。
    返り値: strは数値又は対象なし。
    """
    return "対象なし" if value is None else f"{value:,.{digits}f}"


def percent(value: float | None) -> str:
    """率の分母0を未実行と区別して表示する。

    引数: value(float|None)は保存率。
    返り値: strは百分率又は対象なし。
    """
    return "対象なし（分母0）" if value is None else f"{100 * value:.2f}%"


def flag(value: bool) -> str:
    """保存した資格の真偽を表示する。

    引数: value(bool)は判定。
    返り値: strは充足又は未達。
    """
    if type(value) is not bool:
        raise ValueError("資格はboolが必要")
    return "充足" if value else "未達"


def money(value: float | None) -> str:
    """品質により確定できない額を計算漏れと混同しない。

    引数: value(float|None)は確定対象額。
    返り値: strは円又は確定不能の表示。
    """
    return "確定不能（品質注意）" if value is None else number(value)


def table(headers: list[str], rows: list[list]) -> str:
    """列数を検査して小型のMarkdown表を作る。

    引数: headers(list[str])は見出し、rows(list[list])は保存値。
    返り値: strは表。
    """
    if any(len(row) != len(headers) for row in rows):
        raise ValueError("帳票の列数不一致")
    return "| " + " | ".join(headers) + " |\n| " + " | ".join("---" for _ in headers) + " |\n" + "".join("| " + " | ".join(cell(v) for v in row) + " |\n" for row in rows) + "\n"


def link(path: Path, output: Path, label: str | None = None) -> str:
    """同じ出典を指す相対リンクを作る。

    引数: path(Path)は参照先、output(Path)は出力文書、label(str|None)は名前。
    返り値: strはMarkdownリンク。
    """
    return "[" + (label or path.name) + "](" + os.path.relpath(path, output.parent).replace("\\", "/") + ")"


def validate_result(result: dict, old: dict) -> None:
    """旧S1の完全な数値対照と、全候補の分母/品質/資格を検査する。

    引数: result/old(dict)は50/49保存結果。
    返り値: None。値を再推定せず差を拒否する。
    """
    if result.get("試行") != 50 or result.get("全66場既使用") is not True or set(result["候補"]) != set(POLICIES):
        raise ValueError("試行/候補/既使用表示の差")
    if result["候補"]["S1"] != old["候補"]["S1"] or result["役割別入口"]["S1"] != old["役割別入口"]["S1"]:
        raise ValueError("49S1完全対照の数値差")
    # ----------------------------------------
    # 保存した候補別の分母・費用・活動と資格だけを検査する。
    for policy in POLICIES:
        for period in PERIODS:
            current = result["候補"][policy][period]
            e, o = current["入口"], current["運用"]
            n, count = e["約定"], o["予定枠"]
            if sum(e["結果別"].values()) != e["候補"] or e["候補"] - e["結果別"].get("未約定", 0) != n:
                raise ValueError("入口の候補/仮約定分母差")
            if (e["率"] is None) != (n == 0) or n and not math.isclose(e["率"], e["250"] / n, abs_tol=1e-12, rel_tol=0):
                raise ValueError("入口率の分母差")
            if count != old["候補"]["S1"][period]["運用"]["予定枠"] or sum(o["判断別"].values()) != count:
                raise ValueError("全予定枠又は判断分類差")
            wait, invalid = o["判断別"].get("待ち", 0), o["判断別"].get("判定不能", 0)
            if (o["待ち数"], o["判定不能"], o["全枠判定可能"], o["活動適格"]) != (wait, invalid, invalid == 0, count > 0 and 2 * (wait + invalid) <= count):
                raise ValueError("待ち/判定不能/保守活動条件差")
            if count and (not math.isclose(o["主待ち率"], wait / count, abs_tol=1e-12, rel_tol=0) or not math.isclose(o["待ち率保守上限"], (wait + invalid) / count, abs_tol=1e-12, rel_tol=0)):
                raise ValueError("活動の率分母差")
            if o["買い"] + o["売り"] != o["完結数"]:
                raise ValueError("実完結の売買分母差")
            for fee in (0, 5, 10):
                key = str(fee)
                expected = o["完結観測額円"]["0"] - 20 * fee * o["完結数"]
                if not math.isclose(o["完結観測額円"][key], expected, abs_tol=1e-8, rel_tol=0):
                    raise ValueError("同約定費用差")
                if o["品質注意場"] and o["全体確定額円"][key] is not None:
                    raise ValueError("品質注意時の確定null差")
            if current["同時適格"] != (e["70目標"] and o["活動適格"] and o["費用適格"]):
                raise ValueError("総合資格差")
            for role in ROLES:
                result["役割別入口"][policy][period][role]
                o["役割別完結"][role]
    expected_adopted = [p for p in NEW_POLICIES if all(result["候補"][p][s]["同時適格"] for s in PERIODS[:2])]
    if result["採用"] != expected_adopted:
        raise ValueError("採用は新P候補の両期だけ")
    for policy in NEW_POLICIES:
        for period in PERIODS:
            d = result["被覆診断"][policy][period]
            if sum(d["入口理由"].values()) != d["予定枠"] or sum(d["実判断"].values()) != d["予定枠"] or sum(d["純入口役割"].values()) != d["純入口"]:
                raise ValueError("被覆診断の全枠/純入口/実参加分母差")
            for direction in ("実方向", "逆方向"):
                if d["同時刻基準"][direction]["候補"] != d["純入口"]:
                    raise ValueError("同じ対象枠の両方向比較が不一致")


def settings() -> list[dict]:
    """版5の使用セルへ、対照と新T/Rの役割を対応する。

    引数: なし。
    返り値: list[dict]は設定。新入口の詳細閾値は計画/条件正本へ接続する。
    """
    all_ids, new_ids = list(EVALUATIONS.values()), [EVALUATIONS[p] for p in NEW_POLICIES]
    rows = [
        (["P03"], ["m03"], all_ids, "OR30/3分10本・固定旧端±5pt", "49と同じ当場序盤帯と公開時計を使う。30分足・注文集中の実測としない"),
        (["I07"], ["m03"], all_ids, "FastK14現前/精密差・役割別の問い", "49の水準/進行選別と、新Tの逆行から再開・新Rの帰還時変化を区別する"),
        (["I08", "C07"], ["m15"], all_ids, "当時15分DI14・実方向背景", "Tは実方向DI差>0、Rは>=0。公開済み最新上位の準備/鮮度を確認。ADXは診断のみ、独立した複数票ではない"),
        (["P06", "P07", "P09"], ["m03"], [EVALUATIONS["S1"]], "旧49S1のT/R全属性対照", "旧Tの3終値外側残留と旧Rの外到達/後2終値内復帰。保存結果/先着/運用を参照し再生しない"),
        (["P04", "P07"], ["m03"], new_ids, "新T：逆行b後の局所終値再開j", "OR外・上位DI背景で、終値差/ΔK逆行から後足の前高安終値突破へ。新TはK50水準を要求しない。失効・定時消費は計画正本"),
        (["P06", "P09"], ["m03"], [EVALUATIONS["P0"]], "P0のRは旧49S1方式", "新Tだけを変更する比較。Rは各定時の旧49S1入口関数で判定し、T/R競合を正本規約で扱う"),
        (["P04", "P07", "P09"], ["m03"], [EVALUATIONS["P1"]], "新R：外cross b→帰還f→別足k", "bはDI不要。fで反転ΔK>0、f/k/定時で実方向DI差>=0を確認。f逆端突破を待ち、旧外端再獲得は等号を含め先取消"),
        (["P04"], ["m03"], new_ids, "初可視定時一回消費・年齢/公開key", "新T/Rの監視寿命・900秒鮮度・背景無効化を入口正本へ。保有抑止と価格機械の消費を別にする"),
        (["I09"], ["m03"], all_ids, "ATR14→D5..125・定時要求時固定", "実注文時の定時最新3分ATRからDを固定。j/kのATRは診断のみ。旧49Oの追尾式を変更しない"),
        (["B01"], ["tick"], all_ids, "定時初イベント/正常flag/+1秒TTL30", "Day25/Night49全枠。30秒等号可、初BBO不正は後行救済なし。数量flagを含む正常性と価格時計を区別"),
        (["E02"], ["tick"], all_ids, "連続損失/利益追尾・現在正味益122円strict", "h/L/arm・名目床・pending凍結と場末timerは固定49O。固定250TPなし、終了は半開区間"),
        (["E01"], ["tick"], all_ids, "仮125/250・force同秒最初正常行inclusive", "期限同秒後行へ進まない。全仮約定分母、非重複間引き。純先着と実占有/回収を別にする"),
    ]
    return [{"設定ID": f"S{i:02d}", "手法ID": methods, "尺度ID": scales, "短記": short, "説明": detail, "結果短記": "/".join(applies), "適用評価": applies} for i, (methods, scales, applies, short, detail) in enumerate(rows, 1)]


def entry_table(result: dict) -> str:
    """対照と新二候補の入口支持・先着を表示する。

    引数: result(dict)は50結果。
    返り値: strは主/非重複率と結果内訳。
    """
    rows = []
    for policy in POLICIES:
        for period in PERIODS:
            e = result["候補"][policy][period]["入口"]
            rows.append([policy, period, e["候補"], e["約定"], e["結果別"].get("未約定", 0), f"{e['250']}/{e['約定']}", percent(e["率"]), f"{e['間引き250']}/{e['間引き約定']}", percent(e["間引き率"]), f"{e['日数']}/{e['場数']}", flag(e["支持"]), flag(e["70目標"])])
    return table(["案", "期間", "純候補", "仮約定", "未約定", "250/主分母", "主率", "250/非重複分母", "非重複率", "日/場", "支持", "70目標"], rows)


def operation_tables(result: dict) -> str:
    """完結・台帳・全体確定と活動を別に表示する。

    引数: result(dict)は保存結果。
    返り値: strは費用・全枠・起動/回収の表。
    """
    cash, activity, recovery, roles = [], [], [], []
    for policy in POLICIES:
        for period in PERIODS:
            current = result["候補"][policy][period]
            o = current["運用"]
            cash.append([policy, period, o["完結数"], f"{o['買い']}/{o['売り']}", *[number(o["台帳観測額円"][str(f)]) for f in (0, 5, 10)], *[money(o["全体確定額円"][str(f)]) for f in (0, 5, 10)], len(o["品質注意場"]), o["未解消"], flag(o["費用支持"]), flag(o["費用適格"]), flag(current["同時適格"])])
            activity.append([policy, period, o["予定枠"], o["待ち数"], percent(o["主待ち率"]), o["判定不能"], percent(o["待ち率保守上限"]), flag(o["活動適格"]), "はい" if o["全枠判定可能"] else "いいえ", percent(o["空き枠待ち率"])])
            recovery.append([policy, period, o["利益起動件数"], o["起動後赤字件数5"], o["実250到達件数"], o["定時外返済件数"], number(o["平均保有秒"], 1), o["返済理由"], o["完結観測額円"], o["品質注意場"]])
            for role in ROLES:
                e = result["役割別入口"][policy][period][role]
                actual = o["役割別完結"][role]
                roles.append([policy, period, role, e["候補"], f"{e['250']}/{e['約定']}", percent(e["率"]), flag(e["支持"]), flag(e["70目標"]), actual["件数"], number(actual["観測純額5"])])
    return ("## 実運用・同約定費用\n\n完結観測額と、未解消新規の片道費用を含む台帳観測額を分ける。品質注意時は全体確定額がnullであり、観測額で埋めない。追加滑りは片道pt、約定価格へ二重加算しない。\n\n"
            + table(["案", "期間", "実完結", "買/売", "台帳観測0", "台帳観測5", "台帳観測10", "全体確定0", "全体確定5", "全体確定10", "注意場数", "未解消", "費用支持", "費用適格", "全条件"], cash)
            + "## 全予定枠と活動\n\n主待ち率=待ち/全予定枠。保有継続は非待ち。判定不能を全て待ちとした保守上限≤50%を活動適格とし、全枠判定可能の旗を分ける。空き枠待ち率は診断のみ。\n\n"
            + table(["案", "期間", "全枠", "待ち", "主待ち率", "判定不能", "保守上限", "活動適格", "全枠判定可能", "空き枠待ち率"], activity)
            + "## 役割別の入口と実回収\n\n対象T/R6群を別表示し、空群は分母0として扱う。混合支持を片役割へ代用しない。役割別実額も観測値で、全体品質を離れて確定利益とは呼ばない。後続2場は支持の代替ではない。\n\n"
            + table(["案", "期間", "実役割", "純候補", "仮250/仮約定", "仮率", "役割支持", "役割70", "実完結", "実完結観測5円"], roles)
            + "## 利益保護と品質の保存診断\n\n現在正味益122円strict起動と、起動後追加5pt純赤字を分ける。実MFE250は固定250利確の実績ではない。\n\n"
            + table(["案", "期間", "現在益起動", "起動後赤字5", "実MFE250", "定時外返済", "平均保有秒", "返済理由", "完結観測0/5/10", "品質注意場"], recovery))


def coverage_table(result: dict) -> str:
    """新候補の被覆と同一対象枠の両方向を表示する。

    引数: result(dict)は保存被覆診断。
    返り値: strは純入口/実判断/同時刻基準。逆方向を補数にしない。
    """
    rows, extra = [], []
    for policy in NEW_POLICIES:
        for period in PERIODS:
            d = result["被覆診断"][policy][period]
            cells = []
            for direction in ("実方向", "逆方向"):
                e = d["同時刻基準"][direction]
                cells.extend((f"{e['250']}/{e['約定']}", percent(e["率"])))
            rows.append([policy, period, d["予定枠"], d["純入口"], d["純入口役割"], d["入口理由"], d["実判断"], *cells])
            for key, value in d.items():
                if key not in {"予定枠", "純入口", "純入口役割", "入口理由", "実判断", "同時刻基準"}:
                    extra.append([policy, period, key, {"個数": len(value), "説明": "全件は結果正本を参照"} if isinstance(value, list) and len(value) > 24 else value])
    text = "## 新入口の被覆と同時刻比較\n\n全予定→入口理由→純入口→実判断は別分母。同じ新候補の対象枠/要求時計で、49保存B±の実方向と逆方向を比較する。買いask/売りbidで新規価格は異なり、率は補数でない。逆向きの別運用をした成績ではなく、時刻構成の異なる全枠基準との単純比較も避ける。\n\n" + table(["案", "期間", "全枠", "純入口", "純T/R", "入口理由", "実分類", "実方向250/仮約定", "実方向率", "逆方向250/仮約定", "逆方向率"], rows)
    if extra:
        text += "### 追加の保存段階診断\n\n取消・消費・発動年齢等は保存された集計だけを示す。P0の足遷移には、実入口に採用しない新Rの共有監視も含まれる。共通観測をP0/P1で足し合わせず、P0のR実入口は旧49S1方式として区別する。共有監視の動作数をP0Rの発動件数/先着率へ代用しない。消費数はP0が新T、P1が新T/Rであり、消費時有効は未失効を意味する。正常BBOや実採用を意味せず、判定不能・競合・保有抑止等は別にある。機会段階の全枠分類、足遷移、消費ID、実採用時の発動年齢も別分母。新しい閾値や別運用を足さない。\n\n" + table(["案", "期間", "保存項目", "集計値"], extra)
    return text


def session_summary(result: dict) -> str:
    """新132場候補の保存品質と判断枠を日夜別に要約する。

    引数: result(dict)は場別保存値。
    返り値: strは小型表。旧S1の場別詳細は49正本へ参照する。
    """
    rows = []
    for policy in NEW_POLICIES:
        for period in PERIODS:
            for kind in ("Day", "Night"):
                chosen = [r for r in result["場別"] if r["候補"] == policy and r["期間"] == period and r["場"].endswith("_" + kind)]
                quality = {r["場"]: r["運用品質"]["損益注意理由"] for r in chosen if not r["運用品質"]["損益確定可能"]}
                rows.append([policy, period, kind, len(chosen), sum(r["運用集計"]["予定枠数"] for r in chosen), sum(r["運用集計"]["完結数"] for r in chosen), quality,
                             {r["場"]: r["入力品質"] for r in chosen if r["入力品質"]}])
    return "## 新規計算した場別保存値の要約\n\n新P0/P1の132場候補だけ。S1を再計算した場別データは作らず49詳細を参照する。時計除外件数と損益注意は別で、入力注意の存在をそのまま損益確定不能へ数えない。\n\n" + table(["案", "期間", "場種", "場数", "予定枠", "実完結", "損益注意場・理由", "入力品質の保存値"], rows)


def audit_table(study: Path) -> str:
    """旧129差保全と期限補足、新50証明を別行で表示する。

    引数: study(Path)は50正式先。
    返り値: strは証明状態。旧audit falseを成功へ変更しない。
    """
    rows = []
    for path, label in ((OLD / "保存物確認.json", "49元確認・129差を保全"), (OLD / "期限同秒確認.json", "49期限同秒補足・別証明"), (study / "保存物確認.json", "50保存物確認")):
        if path.is_file():
            proof = read_json(path)
            rows.append([label, "一致" if proof.get("全件一致") is True else "不一致あり・原証明保持", proof.get("照合項目数", "未記載"), proof.get("不一致数", "未記載"), link(path, study / "README.md")])
        else:
            rows.append([label, "未保存", "未保存", "未保存", "未保存"])
    return "## 保存確認の範囲\n\n元49確認と後続の期限同秒補足は別証明。50の合否を旧証明の改稿で作らない。\n\n" + table(["証明", "保存合否", "照合項目", "不一致", "正本"], rows)


def context_for(study: Path) -> dict:
    """結果と条件・固定・参照対照を小型正本だけで結ぶ。

    引数: study(Path)は50正式先。
    返り値: dictは描画文脈。結果未存在では生成しない。
    """
    required = [study / n for n in ("結果.json", "検証計画.md", "条件.json", "固定.json", "一覧.resources.json")]
    for path in required:
        if not path.is_file():
            raise FileNotFoundError("結果完成後だけ表示可能: " + str(path))
    result, config = read_json(required[0]), read_json(study / "条件.json")
    if result["固定SHA256"] != sha(study / "固定.json"):
        raise ValueError("結果/固定の版差")
    reference = result["対照参照"]
    old_path = (ROOT / reference["結果"]).resolve()
    if old_path != (OLD / "結果.json").resolve() or reference["候補"] != "S1" or reference["再計算"] is not False or reference["結果SHA256"] != sha(old_path):
        raise ValueError("49S1保存対照への参照差")
    old = read_json(old_path)
    validate_result(result, old)
    # ----------------------------------------
    # Viewerは小さな一覧と参照先の存在だけを検査する。
    catalog = read_json(study / "一覧.resources.json")
    if catalog.get("path_base") not in (None, "") or len(catalog["resources"]) != 198:
        raise ValueError("Viewerはresource_root相対の198資源")
    if len({r["id"] for r in catalog["resources"]}) != 198 or {r["method_id"] for r in catalog["resources"]} != set(POLICIES):
        raise ValueError("Viewer資源id/候補集合差")
    for policy in POLICIES:
        if sum(r["method_id"] == policy for r in catalog["resources"]) != 66:
            raise ValueError("Viewerは各候補66場")
    for row in catalog["resources"]:
        path = (ROOT / row["pnl_path"]).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError("Viewer約定参照の欠落/親抜け")
    # ----------------------------------------
    # 小型出典のリンクと指紋を、保存結果へ付ける。
    paths = [*required, *[study / n for n in ("入力台帳.json", "保存物確認.json", "人工確認.json", "対照確認.json") if (study / n).is_file()], old_path, OLD / "固定.json", OLD / "保存物確認.json", OLD / "期限同秒確認.json", Path(__file__),
             ROOT / "scripts/定時帯反応/運用.py", ROOT / "scripts/定時帯反応/検証.py", ROOT / "scripts/定時帯反応/保存物確認.py", ROOT / "scripts/定時帯反応/期限同秒確認.py", V5.CATALOG, V5.MASTER]
    paths += [HERE / n for n in ("入口.py", "入口仕様.md", "検証.py", "保存物確認.py", "README.md") if (HERE / n).is_file()]
    paths += [ROOT / p for p in ("docs/議論/15分判断と連続追尾の研究条件.md", "docs/議論/15分判断の心理仮説カード.md", "docs/議論/外部再調査/局所の調整完了と再開の条件.md") if (ROOT / p).is_file()]
    return {"study": study, "result": result, "config": config, "old": old, "sources": list(dict.fromkeys(paths))}


def documents(context: dict) -> dict[str, str]:
    """保存正本から二文書の文字列だけを組み立てる。

    引数: context(dict)は読取済み文脈。
    返り値: dict[str,str]はREADME/設定と結果。ファイルを書かない。
    """
    study, result, config = context["study"], context["result"], context["config"]
    readme, mapping = study / "README.md", study / "設定と結果.md"
    groups = settings()
    adopted = result["採用"]
    intro = ("保存実行日時：" + result["実行日時"] + "。全NK66場は既使用（学習40/条件選択24/後続2）、未見の性能確認ではない。\n\n"
             "S1は固定49の完全保存対照で再計算しない。P0は新T＋旧49S1R、P1は新T＋新R。新二候補だけを同じ15分格子と固定49Oで計算する。新T/Rは独自の価格機械であり、原典や指標単独の収益効果とはしない。\n\n"
             + ("新候補で学習・条件選択の入口70/活動/品質付き費用を同時達成：" + "、".join(adopted) + "。\n\n" if adopted else "**新候補の両期同時適格は0/2。** 支持・率・活動・費用のどこが未達かを下表で分ける。\n\n"))
    conditions = ("## 条件の読み方と限界\n\n"
                  "新Tは序盤帯外の方向背景の中で短期逆行bを知り、後足の前高安終値突破jを局所再開として扱い、K50水準を要求しない。新Rは外cross b→内側帰還f→別足kの価格確認を分ける。監視の背景失効、初可視定時での一回消費、寿命と900秒鮮度、発動後の否定線は検証計画と入口仕様を正本とする。有効な複数発動だけを競合待機とし、失効した発動の消費とは区別する。新候補のRと旧49S1Rを同じ規則だと扱わない。\n\n"
                  "指標値が変化しただけで心理を証明せず、価格・公開時計・勢い・上位方向・損失許容を別の役割にする。OHLCで足内順序や連続滞在を推定しない。待機と判定不能・保有抑止と価格機械の消費を分け、後付けで未約定や待ちを除いて活動率を作らない。\n\n"
                  "判断はDay09:15〜15:15の25枠、Night17:30〜翌05:30の49枠。初イベントは予定以後30秒等号まで、非正常BBOを後行で救済しない。新規は+1価格秒・後原行・TTL30秒等号可。全予定枠分母で保有継続は非待ち、保守待ち率=(待ち+判定不能)/全枠≤50%。\n\n"
                  "運用は固定49O。ATR/Dは実注文時の定時最新3分足から固定し、j/k時の値は診断のみ。現在正常返済BBOの実方向含み益pt×10円/pt−122円>0strictでarm、最低名目entry床。初期損失線L=max(−125,−D)、h=max(前h,0,r)、L=max(前L,−125,h−D)、arm後L≥0。返済pending中h/L/armを凍結する。実MFEはpending中も測るためhと別。固定250TPなし、15:35/翌05:50強制timer、終了15:40/05:55は半開区間。名目床は費用後同値や遅延後同値約定を保証しない。\n\n"
                  "入口先着は仮約定後の−125/+250、期限/不足も全仮約定分母、未約定は別。間引きは先行仮結果終点の後に新規した非重複集合で、30分間引きではない。force同秒の最初正常原行を含め、その後の同秒行へ進まない。入口支持は学習60仮約定/6日/10場/非重複20、選択20/3日/5場/非重複10、主/非重複とも70%を要求する。\n\n"
                  "手数料11円/片道、micro10円/pt、同約定費用0/5/10。費用支持は学習20完結/6日/10場/買売各5、選択10/3日/6場/各3。品質注意なし・主追加5ptの両期黒字と活動/入口70を同時に要求する。後続2場は両期支持を代用しない。\n\n"
                  "49初回の保存物確認は129不一致のまま保全し、別の期限同秒確認が全先着の正本規約と期間集計の一致を補足した。元audit falseを50の成功へ書き換えない。50固有の確認範囲は50証明の記載に限り、全tick保護/原指標の独立再生を追加実施したと誇張しない。\n\n"
                  "ラージBBOはmicro執行の代理。数量競合・受信時計・通信遅延の実測ではない。同じ純入口でも保有占有が違えば実参加集合は変わる。役割名だけの変更や同時刻逆方向率を、独立した収益機会の証明にしない。未予約11/5Day両商品を開かない。\n\n")
    note = "純候補は実建玉占有と独立した発動。主率は仮250/全仮約定で、実取引の黒字率ではない。S1欄は49保存結果の該当部分をそのまま参照する。\n\n"
    source_table = table(["保存出典", "SHA256"], [[link(p, readme), "`" + sha(p) + "`"] for p in context["sources"]])
    reproduction = ("## 再表示と閲覧\n\n" + link(study / "検証計画.md", readme) + " / " + link(study / "条件.json", readme) + " / " + link(study / "結果.json", readme) + " / " + link(study / "一覧.resources.json", readme) + "。Viewer198資源は旧S1の66参照＋新132。path_baseを省略し、pnl_pathはresource_root相対で旧49約定を複製しない。新詳細は定時判断と運用/入口先着の2gzip。\n\n"
                    "結果未完成では生成せず、帳票は小型保存値だけを読む。市場・先着・主/独立監査の再実行をしない。\n\n```powershell\nC:/Python314/python.exe -X utf8 scripts/局所再開/レポート.py\nC:/Python314/python.exe -X utf8 scripts/局所再開/レポート.py --check\n```\n\n")
    body = intro + "## 入口先着・支持\n\n" + note + entry_table(result) + operation_tables(result) + coverage_table(result) + session_summary(result) + conditions + audit_table(study) + reproduction + "## 保存出典\n\n" + source_table
    # ----------------------------------------
    # 正式の版5へ設定を明示引数で渡し、旧globalは変更しない。
    matrix = V5.matrix(V5.load_catalog(), mapping, groups)
    settings_table = table(["設定", "手法/尺度", "短記", "役割と限定", "複合評価"], [[g["設定ID"], "/".join(g["手法ID"]) + "・" + "/".join(g["尺度ID"]), g["短記"], g["説明"], "/".join(g["適用評価"])] for g in groups])
    evaluations = table(["評価", "候補", "構成", "状態"], [[EVALUATIONS[p], p, {"S1": "固定49S1完全保存対照", "P0": "新T＋旧49S1R", "P1": "新T＋新R"}[p], "参照対照・新採用集合には含めない" if p == "S1" else "採用" if p in adopted else "未達"] for p in POLICIES])
    mapped_source = table(["保存出典", "SHA256"], [[link(p, mapping), "`" + sha(p) + "`"] for p in context["sources"]])
    mapped = (intro + "カタログ版5、55手法×9尺度を保持。R01=S1対照、R02=P0、R03=P1。15分判断を15分足のみに限定せず、OR30を30分足へ転記しない。未使用/未検証は今回の使用範囲の表示。\n\n"
              + matrix + "\n## 設定明細\n\n" + settings_table + "## 複合評価\n\n" + evaluations + "## 全固定条件\n\n"
              + table(["項目", "固定値"], [[k, v] for k, v in config.items()]) + "## 入口先着・支持\n\n" + note + entry_table(result) + operation_tables(result) + coverage_table(result) + session_summary(result) + conditions + audit_table(study) + reproduction + "## 保存出典\n\n" + mapped_source)
    return {"README.md": "# 00050：15分定時の局所再開\n\n" + body.rstrip() + "\n", "設定と結果.md": "# 設定と結果：15分定時の局所再開\n\n" + mapped.rstrip() + "\n"}


def check_links(text: str, document: Path, generated: set[Path]) -> int:
    """生成文書のローカルリンク欠落を検査する。

    引数: text(str)は本文、document(Path)は出力先、generated(set[Path])は同時生成2MD。
    返り値: intはローカルリンク数。外部ページは再取得しない。
    """
    count = 0
    for target in re.findall(r"\]\(([^)]+)\)", text):
        if target.startswith(("http:", "https:", "#", "mailto:")):
            continue
        count += 1
        path = (document.parent / unquote(target.split("#", 1)[0])).resolve()
        if path not in generated and not path.exists():
            raise FileNotFoundError("帳票リンク欠落: " + target)
    return count


def render(study: Path = STUDY, check: bool = False) -> dict:
    """正式結果完成後に保存二MDだけを生成又は同byte点検する。

    引数: study(Path)は50正式先、check(bool)は書込みなし照合。
    返り値: dictは文書bytes/SHAとリンク検査件数。計算モジュールを呼ばない。
    """
    study = study.resolve()
    rendered = documents(context_for(study))
    generated = {(study / name).resolve() for name in rendered}
    output, linked = {}, 0
    for name, text in rendered.items():
        path, data = study / name, text.encode("utf-8")
        linked += check_links(text, path, generated)
        if check:
            if not path.is_file() or path.read_bytes() != data:
                raise ValueError("保存MDと再表示が不一致: " + name)
        else:
            path.write_bytes(data)
        output[name] = {"bytes": len(data), "SHA256": hashlib.sha256(data).hexdigest()}
    return {"文書": output, "リンク検査件数": linked, "欠落リンク": [], "市場再計算": False}


def main() -> None:
    """結果後の二MD表示又は非書込み点検をCLIへ公開する。

    引数: --study(Path)/--check(bool)をargparseで取得。
    返り値: None。結果前の未確定成績を描画しない。
    """
    parser = argparse.ArgumentParser(description="50局所再開の保存結果帳票")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    print(json.dumps(render(args.study, args.check), ensure_ascii=False))


if __name__ == "__main__":
    main()
