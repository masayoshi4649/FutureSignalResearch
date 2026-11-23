"""試行49の保存結果だけから概要と全手法表付き設定を生成する。

市場・指標・先着・運用の計算モジュールをimportしない。
正式結果完成後だけREADME.mdと設定と結果.mdを書き込む。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00049_15分定時の序盤帯反応"
CATALOG = ROOT / "docs/議論/手法と時間スケールの汎用表_版5.md"
PERIODS = ("学習", "条件選択", "後続検査")
POLICIES = ("S0", "S1")
SCALES = ("原板・逐次", "1分", "3分", "5分", "15分", "30分", "60分", "セッション足", "日足")
FENCE = chr(96) * 3


def sha(path: Path) -> str:
    """小型の帳票出典ファイルを指紋化する。

    引数: path(Path)はJSON、コード又は文書。
    返り値: strはSHA256。市場キャッシュは読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    """保存JSONを読み、非有限数の使用を拒否する。

    引数: path(Path)は小型正本。
    返り値: dictは保存値。指標・取引を再構築しない。
    """
    def invalid(value: str) -> None:
        """JSONの非標準数値を拒否する。

        引数: value(str)は非有限数の表記。
        返り値: None。常にValueErrorを送出する。
        """
        raise ValueError("非有限JSON値: " + value)
    value = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=invalid)
    if not isinstance(value, dict):
        raise ValueError("JSON正本は辞書が必要")
    return value


def cell(value: object) -> str:
    """保存値をMarkdownの一セルへ整える。

    引数: value(object)は文字、数又は補助辞書。
    返り値: strは改行・縦棒をエスケープした表示。
    """
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value).replace("|", r"\|").replace("\n", " ")


def number(value: int | float | None, digits: int = 0) -> str:
    """件数、秒又は金額を表示する。

    引数: value(int|float|None)は保存値、digits(int)は小数桁。
    返り値: strは3桁区切り又は欠測記号。
    """
    if value is None:
        return "—"
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("数値欄の型不正")
    return f"{value:,.{digits}f}"


def percent(value: float | None) -> str:
    """保存率を百分率へ表示変換する。

    引数: value(float|None)は0〜1の率。
    返り値: strは百分率。分母0を0%へ埋めない。
    """
    return "—" if value is None else f"{100 * value:.2f}%"


def flag(value: bool) -> str:
    """保存済みの適格旗を日本語にする。

    引数: value(bool)は保存旗。
    返り値: strは充足又は未達。帳票側で条件を変更しない。
    """
    if type(value) is not bool:
        raise ValueError("適格旗はboolが必要")
    return "充足" if value else "未達"


def money(value: float | None) -> str:
    """観測金額と確定不能を区別して表示する。

    引数: value(float|None)は保存額。
    返り値: strは円又は明示的なnull。
    """
    return "null（確定不能）" if value is None else number(value)


def table(headers: list[str], rows: list[list]) -> str:
    """平行な記録をMarkdown表へ変換する。

    引数: headers(list[str])は列名、rows(list[list])は表示行。
    返り値: strは空行付きの表。
    """
    if any(len(row) != len(headers) for row in rows):
        raise ValueError("表の列数不一致")
    lines = ["|" + "|".join(headers) + "|", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["|" + "|".join(cell(value) for value in row) + "|" for row in rows]
    return "\n" + "\n".join(lines) + "\n"


def relative_link(path: Path, study: Path) -> str:
    """正式studyからの相対リンクを作る。

    引数: path(Path)は出典、study(Path)は文書保存先。
    返り値: strはスラッシュ区切りの相対パス。
    """
    return Path(os.path.relpath(path, study)).as_posix()


def catalog_copy(text: str, study: Path) -> tuple[str, list[str]]:
    """版5の全55手法・9尺度を保持し、使用セルだけ注記する。

    引数: text(str)は版5全文、study(Path)は文書保存先。
    返り値: tuple[str,list[str]]は補正した全表と元順の手法ID。
    """
    block = text.split("## 手法×時間スケール", 1)[1].split("## 設定明細", 1)[0]
    block = block.replace(
        "全セルは未設定・未検証。足の時間尺度と計算期間・間引き間隔・VWAPの起算点を区別する。",
        "未使用セルは未使用・未検証。15分は判断頻度。3分10本のOR30を30分足へ記入しない。")
    block = block.replace("未設定・未検証", "未使用・未検証")
    uses = {
        ("I07", "3分"): "S02 FastK14・50/ΔK／R01,R02",
        ("I08", "15分"): "S04 DI14：R01診断/R02準備・値、ADX診断",
        ("I09", "3分"): "S05 ATR14→D5..125／R01,R02",
        ("P03", "3分"): "S01 OR30=3分10本・±5／R01,R02",
        ("P06", "3分"): "S03 RのOR内半分・中央WAIT／R01,R02",
        ("P07", "3分"): "S03 固定OR外の3終値T／R01,R02",
        ("P09", "3分"): "S03 外到達→後2終値R／R01,R02",
        ("B01", "原板・逐次"): "S06 BBO/+1秒/TTL30／R01,R02",
        ("E01", "原板・逐次"): "S08 仮約定後+250前−125／R01,R02",
        ("E02", "原板・逐次"): "S07 連続追尾/122円strict／R01,R02",
    }
    output, ids = [], []
    for line in block.strip().splitlines():
        match = re.match(r"^\|\s*([A-Z]\d{2})\s*\|", line)
        if match:
            row = [value.strip() for value in line.strip().strip("|").split("|")]
            if len(row) != 11:
                raise ValueError("汎用表の尺度数不一致")
            identifier = match.group(1)
            ids.append(identifier)
            for index, scale in enumerate(SCALES, 2):
                row[index] = uses.get((identifier, scale), row[index])
            line = "| " + " | ".join(row) + " |"
        output.append(line)
    if len(ids) != 55 or len(set(ids)) != 55:
        raise ValueError("版5の55手法を保持できていない")
    def replace_link(match: re.Match) -> str:
        """表の元相対リンクをstudy基準へ移す。

        引数: match(re.Match)はMarkdownリンク。
        返り値: strは同じ参照先を指すリンク。
        """
        label, target = match.group(1), match.group(2)
        if "://" in target or target.startswith("#"):
            return match.group(0)
        path, separator, anchor = target.partition("#")
        relative = relative_link((CATALOG.parent / path).resolve(), study)
        return "[" + label + "](" + relative + (separator + anchor if separator else "") + ")"
    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", replace_link, "\n".join(output)), ids


def validate_result(result: dict) -> None:
    """帳票に必要な保存スキーマとnullの整合を検査する。

    引数: result(dict)は試行49結果。
    返り値: None。欠けた項目を推計値で補わない。
    """
    if result.get("試行") != 49 or result.get("全66場既使用") is not True or set(result["候補"]) != set(POLICIES):
        raise ValueError("試行番号・既使用表示・候補集合の不一致")
    for policy in POLICIES:
        for period in PERIODS:
            current = result["候補"][policy][period]
            entry, operation = current["入口"], current["運用"]
            for name in ("候補", "約定", "250", "率", "間引き約定", "間引き250", "間引き率",
                         "日数", "場数", "支持", "70目標", "結果別"):
                entry[name]
            for name in ("予定枠", "判断別", "待ち数", "主待ち率", "判定不能", "待ち率保守上限",
                         "全枠判定可能", "活動適格", "空き枠待ち率", "完結数", "買い", "売り",
                         "日数", "場数", "品質注意場", "未解消", "完結観測額円", "台帳観測額円",
                         "全体確定額円", "費用支持", "費用適格", "利益起動件数", "起動後赤字件数5",
                         "実250到達件数", "定時外返済件数", "返済理由", "平均保有秒", "役割別完結"):
                operation[name]
            if operation["品質注意場"] and any(v is not None for v in operation["全体確定額円"].values()):
                raise ValueError("品質注意時の確定額がnullではない")
            for role in ("順行", "反転"):
                operation["役割別完結"][role]["件数"]
                operation["役割別完結"][role]["観測純額5"]
                result["役割別入口"][policy][period][role]
            result["上位追加の対応"][period]["除外群先着"]
            current["同時適格"]


# ----------------------------------------
# 保存集計の表示。価格系列や詳細gzipを走査しない。

def entry_table(result: dict) -> str:
    """二候補・三期間の仮想先着を表示する。

    引数: result(dict)は保存結果。
    返り値: strは主/間引き/支持の表。
    """
    rows = []
    for policy in POLICIES:
        for period in PERIODS:
            e = result["候補"][policy][period]["入口"]
            rows.append([policy, period, number(e["候補"]), number(e["約定"]), number(e["結果別"].get("未約定", 0)),
                         number(e["250"]) + "/" + number(e["約定"]), percent(e["率"]),
                         number(e["間引き250"]) + "/" + number(e["間引き約定"]), percent(e["間引き率"]),
                         number(e["日数"]) + "/" + number(e["場数"]), flag(e["支持"]), flag(e["70目標"])])
    return table(["案", "期間", "純候補", "仮約定", "未約定", "250/主分母", "主率",
                  "250/間引き分母", "間引き率", "日/場", "支持", "70目標"], rows)


def operation_table(result: dict) -> str:
    """実完結・観測額・全体確定額を分離する。

    引数: result(dict)は保存結果。
    返り値: strは主追加5pt費用の表。
    """
    rows = []
    for policy in POLICIES:
        for period in PERIODS:
            o = result["候補"][policy][period]["運用"]
            rows.append([policy, period, number(o["完結数"]), number(o["買い"]) + "/" + number(o["売り"]),
                         number(o["完結観測額円"]["5"]), number(o["台帳観測額円"]["5"]),
                         money(o["全体確定額円"]["5"]), number(len(o["品質注意場"])), number(o["未解消"]),
                         flag(o["費用支持"]), flag(o["費用適格"]), flag(result["候補"][policy][period]["同時適格"])])
    return table(["案", "期間", "実完結", "買/売", "完結観測円5", "台帳観測円5", "全体確定円5",
                  "注意場数", "未解消", "費用支持", "費用適格", "全条件"], rows)


def activity_table(result: dict) -> str:
    """全予定枠の待ち・判定不能と保守上限を表示する。

    引数: result(dict)は保存結果。
    返り値: strは活動条件と診断値の表。
    """
    rows = []
    for policy in POLICIES:
        for period in PERIODS:
            o = result["候補"][policy][period]["運用"]
            rows.append([policy, period, number(o["予定枠"]), number(o["待ち数"]), percent(o["主待ち率"]),
                         number(o["判定不能"]), percent(o["待ち率保守上限"]), flag(o["活動適格"]),
                         "はい" if o["全枠判定可能"] else "いいえ", percent(o["空き枠待ち率"])])
    return table(["案", "期間", "全枠", "待ち", "主待ち率", "判定不能", "保守上限",
                  "活動適格", "全枠判定可能", "空き枠待ち率・診断"], rows)


def role_table(result: dict) -> str:
    """役割別の仮想先着と実完結を別分母で表示する。

    引数: result(dict)は保存結果。
    返り値: strはT/R別集計。
    """
    rows = []
    for policy in POLICIES:
        for period in PERIODS:
            o = result["候補"][policy][period]["運用"]
            for role, label in (("順行", "T"), ("反転", "R")):
                e = result["役割別入口"][policy][period][role]
                actual = o["役割別完結"][role]
                rows.append([policy, period, label, number(e["候補"]), number(e["250"]) + "/" + number(e["約定"]),
                             percent(e["率"]), number(actual["件数"]), number(actual["観測純額5"])])
    return table(["案", "期間", "役割", "純候補", "仮250/仮約定", "仮主率", "実完結", "実完結観測円5"], rows)


def exclusion_table(result: dict) -> str:
    """S0純採用からS1が除く同一枠の群を表示する。

    引数: result(dict)は保存された対応集計。
    返り値: strは理由別と除外群の仮先着表。
    """
    rows = []
    for period in PERIODS:
        group = result["上位追加の対応"][period]
        e = group["除外群先着"]
        rows.append([period, number(group["S0採用"]), number(group["S1除外"]), group["除外理由"],
                     number(e["250"]) + "/" + number(e["約定"]), percent(e["率"]), e["結果別"]])
    return table(["期間", "S0純採用", "S1除外", "除外理由別", "除外群仮250/仮約定", "仮主率", "仮結果別"], rows)


def settings_table() -> str:
    """設定IDと複合評価の対応を表示する。

    引数: なし。
    返り値: strは8設定の内容。
    """
    rows = [
        ["S01", "P03・3分", "固定帯", "当場index0〜9の完全公開10本。高安を場内固定", "OR±5pt、strict外側", "R01/R02"],
        ["S02", "I07・3分", "勢い", "FastK14、元OHLCをFraction。現前差", "T:実方向(K−50)>0かつ実方向ΔK≥0、R:実方向ΔK>0", "R01/R02"],
        ["S03", "P06/P07/P09・3分", "構造と実役割", "Tは3終値、Rは10本内の先行外到達と後2終値", "最新CのOR内半分、中央WAIT。外到達index<最新−1", "R01/R02"],
        ["S04", "I08・15分", "方向優勢", "DMI14。TR正・DM両0はDI0。ADX14診断のみ", "T:実方向(DI+−DI−)>0、R:同≥0", "R01診断／R02準備と値"],
        ["S05", "I09・3分", "幅", "ATR14 Wilder。最初TR=H−Lを含む14TR種", "D=clip(ceil(ATR/5)×5,5,125)、新規判断時固定", "R01/R02"],
        ["S06", "B01・逐次", "判断・執行", "予定+0〜30秒の最初の有限非後退価格。要求+1秒・後行正常BBO", "新規TTL30秒等号可。初BBO不正は後行救済なし", "R01/R02"],
        ["S07", "E02・逐次", "損失/利益保護", "h=max(前h,0,r)、L=max(前L,−125,h−D)。返済pending凍結", "現在10r−122>0後はL≥0。r≤Lで要求。TPなし", "R01/R02"],
        ["S08", "E01・逐次", "入口尺度", "実占有とは独立した仮約定後の正常返済BBO", "+250前−125。期限/不足も仮約定分母、未約定別記", "R01/R02"],
    ]
    return table(["設定ID", "手法・尺度", "役割", "入力・計算", "条件・等号", "複合評価"], rows)


def provenance(context: dict) -> str:
    """参照した小型正本のリンクと指紋を表示する。

    引数: context(dict)は出典情報。
    返り値: strはSHA表。
    """
    return table(["保存出典", "SHA256"], [
        ["[" + x["name"] + "](" + x["link"] + ")", x["sha"]] for x in context["sources"]])


def documents(result: dict, context: dict) -> dict[str, str]:
    """保存集計だけから二文書の文字列を決定的に作る。

    引数: result(dict)は結果、context(dict)は表・保存先・出典。
    返り値: dict[str,str]は2文書。ファイルへ書かない。
    """
    validate_result(result)
    matrix, _ = catalog_copy(context["catalog"], context["study"])
    adopted = result["採用"]
    outcome = ("学習・条件選択で入口70目標、活動、品質付き費用条件を同時に満たす候補は0/2。"
               if not adopted else "保存判定で学習・条件選択の全条件を同時に満たす候補：" + "、".join(adopted) + "。")
    intro = (
        "# 00049：15分定時の序盤帯反応\n\n保存実行日時：" + result["実行日時"]
        + "。全66場は既使用（学習40/条件選択24/後続2）。未見性能ではない。\n\n" + outcome
        + " 後続検査は既使用2場の参考で、学習・選択の支持を代替しない。\n\n"
        "固定帯外の終値残留Tと、先行外到達後の内復帰Rを、公開済み価格・FastK・ATRで判別する。"
        "S1だけに上位DI方向を加える。複合成績を指標単独の効果や注文心理の直接測定とはしない。\n\n"
        "[計画](検証計画.md)／[条件](条件.json)／[結果JSON](結果.json)／[固定](固定.json)／"
        "[全設定と55手法表](設定と結果.md)／[Viewer一覧](一覧.resources.json)\n")
    entry_note = (
        "仮250先着は実取引の勝率ではない。純候補は保有占有から独立した定時発動。主分母は仮約定全件"
        "（125・期限・不足を含む）、未約定は別記。間引きは前の仮結果終点より後の仮約定を"
        "同一場内で選ぶ。新規要求の30分間引きではない。\n\n"
        "支持：学習は仮約定60・6日・10場・間引き20、選択は20・3日・5場・間引き10。"
        "支持と主/間引き両率70%以上を分ける。\n")
    operation_note = (
        "実回収は同時1建玉・1pendingで、仮候補とは集合が異なる。完結観測額は完結取引だけ、"
        "台帳観測額は未解消新規の片道費用も含む。品質注意時は全体確定額をnullとし、観測額で埋めない。"
        "役割別額も観測値であり、全体品質を離れて確定利益とはしない。\n\n"
        "micro1枚・10円/pt・手数料11円/片。主追加5pt/片と合わせて往復122円。"
        "同約定で追加0/5/10を比較し、価格へ滑りを二重加算しない。"
        "費用支持は学習20完結・6日・10場・買売各5、選択10完結・3日・6場・買売各3。\n")
    activity_note = (
        "主待ち率=空きの見送り/全予定枠。保有継続は非待ち、処理中・判定不能は別分類。"
        "活動適格は結果前に固定した保守上限=(待ち+判定不能)/全枠≤50%で判定。"
        "全枠判定可能の旗とは別。空き枠待ち率は診断で、追加制約ではない。\n")
    mechanics = (
        "## 時計・入口・連続保護\n\n"
        "- デイ09:15〜15:15の25枠、ナイト17:30〜翌05:30の49枠。09:00/17:15は除外。"
        "ナイト適用は日中例からの解釈。新規判断は15分ごと、保護は正常BBOごと。\n"
        "- 足end≤予定T、公開key≤実判断key。3分足の古さ180秒以内、上位15分900秒以内。"
        "未公開の予定端は前の確定足可。見えた最新の不正/未準備を古い良好値で救済しない。\n"
        "- OR30は08:45/17:00から3分10本の集計で、30分足ではない。全10本が公開済みでなければ判定不能。"
        "直近3本必須、Rだけ10本の連続公開窓。外到達はOR後かつ後2終値復帰より前の別足。\n"
        "- ATR/Fast/DMIは同限月carry。場替自体では切らずNP/missing/部分/不正等で解除。"
        "gap後missing0完全当足は新種可。先頭場も準備できた枠から評価。\n"
        "- T：3終値がOR高+5超又はOR低−5未満、K>50/<50・実方向ΔK≥0。"
        "R：最新Cが帯内半分、先行外到達と後2終値の片端内復帰、実方向ΔK>0。中央等号・競合はWAIT。\n"
        "- 初期L=max(−125,−D)、以後L=max(前L,−125,h−D)、h=max(前h,0,r)。"
        "現在10r−122>0のstrict正で利益旗を立て、以後L≥0。r≤Lで要求、返済pendingで線凍結。"
        "要求+1秒・後行正常BBOで返済。最低名目床は費用後黒字を保証しない。\n"
        "- 固定250TPなし。250/125は入口評価のみ。旧残り60分制限は廃止。"
        "15:35/翌05:50に強制要求し15:40/05:55の連続終了前まで待つ。引け板寄せは使わない。\n")
    external = (
        "## 外部根拠と独自の機械化\n\n"
        "Fisherの序盤レンジ・外側滞在の着想は[出版社公開章](https://catalogimages.wiley.com/images/db/pdf/E0471215511.01.pdf)、"
        "近年のOR30例は[Chuk著者原稿](https://justinchukmarkets.com/papers/orb_paper.pdf)を"
        "2026-11-06に[実装上の隔たり](../../docs/議論/外部再調査/定時観測と序盤レンジの実装上の隔たり.md)で確認した。"
        "3終値は連続滞在の証明ではなく、参加者がORを共有することも実測していない。"
        "NQ・買い・5分初回・1:1出口の再現でもない。OR30/5pt/Fast14/DI14/定時判断/反転/連続追尾の独自条件である。\n\n"
        "[心理と注文資料](../../docs/議論/外部再調査/市場心理と価格構造.md)と"
        "[日本先物の時間帯](../../docs/議論/外部再調査/日本先物の時間帯と参加構造.md)を背景にする。"
        "注文意図・ストップの実在・国籍を8列から復元したとはしない。\n")
    limits = (
        "## 限界\n\n"
        "全66場は過去研究で既使用。未予約11/5Dayの両商品を開かず、未見の改善検証を代替しない。"
        "ラージBBOはmicro執行の代理で、数量競合や真の受信順を再現しない。価格時計+1秒は通信遅延の実測ではない。"
        "OHLCから足内高安順序や9分の連続滞在を推測しない。正常気配300秒超空白・未解消は確定性を妨げる。"
        "同帯の再参加を許すため純候補の経路が重なる。S1純候補が部分集合でも実参加・出口は同一集合ではない。"
        "DI除外群の事後成績を新しい条件として後付けしない。\n")
    reproduction = (
        "## 再現と閲覧\n\n"
        "市場計算は固定後一回だけ。結果・実行開始記録がある状態で再起動しない。帳票は保存結果の読取だけ。\n\n"
        + FENCE + "powershell\n"
        "C:/Python314/python.exe -X utf8 scripts/定時帯反応/入口人工テスト.py\n"
        "C:/Python314/python.exe -X utf8 scripts/定時帯反応/運用人工テスト.py\n"
        "C:/Python314/python.exe -X utf8 scripts/定時帯反応/先着人工テスト.py\n"
        "# 未実行状態でだけ固定と本計算\n"
        "C:/Python314/python.exe -X utf8 scripts/定時帯反応/検証.py --freeze\n"
        "C:/Python314/python.exe -X utf8 scripts/定時帯反応/検証.py --run\n"
        "# 結果後の帳票生成・同byte点検\n"
        "C:/Python314/python.exe -X utf8 scripts/定時帯反応/レポート.py\n"
        "C:/Python314/python.exe -X utf8 scripts/定時帯反応/レポート.py --check\n"
        + FENCE + "\n\n"
        "[Viewer一覧](一覧.resources.json)に場別・候補別約定を接続。"
        "[定時判断と運用](../../work/定時帯反応/00049/定時判断と運用.jsonl.gz)／"
        "[入口先着](../../work/定時帯反応/00049/入口先着.jsonl.gz)が詳細正本。原板は複写しない。\n")
    readme = (intro + "\n## 入口の250先着\n\n" + entry_note + entry_table(result)
              + "\n## 実運用と費用\n\n" + operation_note + operation_table(result)
              + "\n## 活動条件\n\n" + activity_note + activity_table(result)
              + mechanics + external + limits + reproduction + "\n## 保存出典\n" + provenance(context))
    setting = (
        "# 設定と結果：15分定時の序盤帯反応\n\n"
        "カタログ版5・全55手法×9尺度。全行順序とリンク先を保持する。R01=S0、R02=S1。"
        "未使用・未検証は今回の範囲についての表示であり、過去試行全体を未検証とする意味ではない。\n\n"
        + matrix + "\n\n## 設定明細\n" + settings_table() + "\n## 複合評価\n"
        + table(["評価ID", "候補", "構成", "採用判定"], [
            ["R01", "S0", "S01/S02/S03/S05/S06/S07/S08。S04は診断", "採用" if "S0" in adopted else "未達"],
            ["R02", "S1", "R01＋S04の上位DI準備と方向値", "採用" if "S1" in adopted else "未達"]])
        + "\n" + outcome + "\n\n## 入口主評価・支持\n\n" + entry_note + entry_table(result)
        + "\n## 実運用・費用・品質\n\n" + operation_note + operation_table(result)
        + "\n## 活動と全予定枠\n\n" + activity_note + activity_table(result)
        + "\n## 役割別：仮想入口と実完結\n\n"
        "T/Rの仮想と実参加は別の分母。実完結額にも期間全体の品質注意を適用し、仮250率を実勝率と呼ばない。\n"
        + role_table(result) + "\n## DI追加で除外された純入口\n\n"
        "同じslot_idでS0採用・S1不採用となった群。準備不足とDI不一致を理由別に残す。"
        "純入口の対応であり、実参加差や利益の因果分解ではない。\n" + exclusion_table(result))
    fee_rows, action_rows, protection_rows, outcome_rows = [], [], [], []
    for policy in POLICIES:
        for period in PERIODS:
            o = result["候補"][policy][period]["運用"]
            outcome_rows.append([policy, period, result["候補"][policy][period]["入口"]["結果別"]])
            fee_rows.append([policy, period, *[number(o["台帳観測額円"][str(f)]) for f in (0, 5, 10)],
                             *[money(o["全体確定額円"][str(f)]) for f in (0, 5, 10)], o["品質注意場"]])
            action_rows.append([policy, period, o["判断別"]])
            protection_rows.append([policy, period, number(o["利益起動件数"]), number(o["起動後赤字件数5"]),
                                    number(o["実250到達件数"]), number(o["定時外返済件数"]),
                                    number(o["平均保有秒"], 1), o["返済理由"]])
    setting += (
        "\n## 仮想入口の結果内訳\n\n期限・不足も仮約定分母へ含め、未約定を別に残す。\n"
        + table(["案", "期間", "仮想結果別件数"], outcome_rows)
        + "\n## 同約定の費用ストレス\n\n追加滑りは片道pt。台帳観測額と品質付き全体確定額を別列にする。\n"
        + table(["案", "期間", "観測0", "観測5", "観測10", "確定0", "確定5", "確定10", "注意場"], fee_rows)
        + "\n## 判断分類と保護の診断\n" + table(["案", "期間", "全予定枠の分類"], action_rows)
        + table(["案", "期間", "現在費用後正の起動", "起動後純赤字5", "実MFE250以上", "定時外返済", "平均保有秒", "返済理由"], protection_rows)
        + "\n起動後純赤字は利益旗が立った実完結の件数。最低床・遅延・費用で純赤字になり得る。"
        "実MFE250以上は保有経路の到達で、固定250利確のない今回の実回収とは別である。\n")
    baseline_rows = []
    for policy, label in (("B+", "常時仮買い"), ("B-", "常時仮売り")):
        for period in PERIODS:
            e = result["時刻基準"][policy][period]
            baseline_rows.append([label, period, number(e["250"]) + "/" + number(e["約定"]), percent(e["率"]),
                                  number(e["間引き250"]) + "/" + number(e["間引き約定"]), percent(e["間引き率"])])
    setting += (
        "\n## 方向無選別の時刻基準\n\n正常な定時イベントで両方向を別々に仮想評価する診断。"
        "実運用候補でも、後から良い方向だけを選ぶ基準でもない。\n"
        + table(["基準", "期間", "仮250/仮約定", "主率", "間引き250/約定", "間引き率"], baseline_rows)
        + mechanics + external + limits + reproduction + "\n## 保存出典\n" + provenance(context))
    return {"README.md": readme.rstrip() + "\n", "設定と結果.md": setting.rstrip() + "\n"}


def context_for(study: Path) -> dict:
    """正本JSONと出典の小型情報を読み出す。

    引数: study(Path)は正式保存先。
    返り値: dictは結果、表全文、SHAとリンク。巨大詳細は読まない。
    """
    paths = [study / "結果.json", study / "検証計画.md", study / "条件.json", study / "固定.json",
             CATALOG, Path(__file__)]
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
    result = read_json(paths[0])
    if result["固定SHA256"] != sha(study / "固定.json"):
        raise ValueError("結果が参照する固定SHA不一致")
    return {"study": study, "result": result, "catalog": CATALOG.read_text(encoding="utf-8"),
            "sources": [{"name": p.name, "link": relative_link(p, study), "sha": sha(p)} for p in paths]}


def render(study: Path = STUDY, check: bool = False) -> dict:
    """保存結果から正式2MDだけを生成、又は同byteを確認する。

    引数: study(Path)は正式保存先、check(bool)は非書込点検。
    返り値: dictは生成先別bytes/SHA。市場計算を起動しない。
    """
    study = Path(study).resolve()
    context = context_for(study)
    rendered = documents(context["result"], context)
    summary = {}
    for name, text in rendered.items():
        path, data = study / name, text.encode("utf-8")
        if check:
            if not path.is_file() or path.read_bytes() != data:
                raise ValueError("保存MDと再表示が不一致: " + name)
        else:
            path.write_bytes(data)
        summary[name] = {"bytes": len(data), "SHA256": hashlib.sha256(data).hexdigest()}
    return summary


def main() -> None:
    """結果完成後の帳票生成又は同byte点検を実行する。

    引数: なし。CLIの--study/--checkを受け取る。
    返り値: None。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    print(json.dumps(render(args.study, args.check), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
