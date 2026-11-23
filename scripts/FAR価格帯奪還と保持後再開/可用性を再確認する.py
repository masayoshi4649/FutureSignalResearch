"""純価格器と字句射影だけで、保存したnoPnL可用性を再確認する。

価格算法・指標算法は複写せず、同フォルダの価格構造.pyへ委譲する。
字句射影の由来SHA256: d63944ca10cd271e719b4867ea349029b5dd3db974394da03902a459e42e50c0
可用性adapter由来SHA256: 5fefd139c883cf82a2fdd3c4659fe58981fb242c324fbb7530c3511174936785
上の由来は履歴であり、実行時work依存は持たない。
"""

from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime,timezone
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
PRICE_PATH = Path(__file__).with_name("価格構造.py")
_SPEC = importlib.util.spec_from_file_location("可用性再確認の純価格", PRICE_PATH)
PRICE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = PRICE
_SPEC.loader.exec_module(PRICE)
BASE = PRICE.BASE
require = BASE.require
DECODER = json.JSONDecoder()


def skip_space(text: str, pos: int) -> int:
    """
    機能: JSONの空白だけを読み飛ばす。
    引数: text(str)、pos(int)は本文と位置。
    返り値: intは次の非空白位置。
    """
    while pos < len(text) and text[pos].isspace():
        pos += 1
    return pos

def skip_value(text: str, pos: int) -> int:
    """
    機能: 不許可のJSON値を数値・辞書へ変換せず字句だけ飛ばす。
    引数: text(str)、pos(int)は値の開始位置。
    返り値: intは値の直後。括弧・引用符の不整合は拒否する。
    """
    pos = skip_space(text, pos)
    if text[pos] not in '{["':
        while pos < len(text) and text[pos] not in ",}]\r\n":
            pos += 1
        return pos
    if text[pos] == '"':
        end = pos + 1
        while end < len(text):
            if text[end] == "\\":
                end += 2
            elif text[end] == '"':
                return end + 1
            else:
                end += 1
        raise AssertionError("JSON文字列の終端欠落")
    stack = [text[pos]]
    pos += 1
    while stack:
        require(pos < len(text), "JSON入れ子の終端欠落")
        char = text[pos]
        if char == '"':
            pos = skip_value(text, pos)
            continue
        if char in "{[":
            stack.append(char)
        elif char in "}]":
            require(stack.pop() == {"}": "{", "]": "["}[char], "JSON括弧不整合")
        pos += 1
    return pos

def object_spans(text: str, start: int = 0) -> dict:
    """
    機能: field名だけを展開して各値の字句区間を得る。
    引数: text(str)、start(int)はJSON objectと開始。
    返り値: dict[str,tuple[int,int]]は値区間。値本体は未展開。
    """
    pos = skip_space(text, start)
    require(text[pos] == "{", "object開始")
    spans = {}
    pos = skip_space(text, pos + 1)
    while text[pos] != "}":
        name, pos = DECODER.raw_decode(text, pos)
        require(type(name) is str and name not in spans, "field名又は重複")
        pos = skip_space(text, pos)
        require(text[pos] == ":", "field区切り")
        pos = skip_space(text, pos + 1)
        end = skip_value(text, pos)
        spans[name] = (pos, end)
        pos = skip_space(text, end)
        if text[pos] == "}":
            break
        require(text[pos] == ",", "object値区切り")
        pos = skip_space(text, pos + 1)
    return spans

def array_spans(text: str, start: int) -> list:
    """
    機能: 配列を値へ変換せず各要素の区間へ分ける。
    引数: text(str)、start(int)は配列位置。
    返り値: list[tuple[int,int]]は各要素区間。
    """
    require(text[start] == "[", "array開始")
    pos, spans = skip_space(text, start + 1), []
    while text[pos] != "]":
        end = skip_value(text, pos)
        spans.append((pos, end))
        pos = skip_space(text, end)
        if text[pos] == "]":
            break
        require(text[pos] == ",", "array区切り")
        pos = skip_space(text, pos + 1)
    return spans

def decode_fields(text: str, fields: dict, names: tuple) -> dict:
    """
    機能: 許可したfieldだけをJSON値に変換する。
    引数: text(str)、fields(dict)、names(tuple[str])は字句と許可名。
    返り値: dictは許可値だけ。欠落fieldを補完しない。
    """
    require(all(k in fields for k in names), "許可fieldの欠落")
    return {k: json.loads(text[slice(*fields[k])]) for k in names}

def project_line(line: str) -> dict:
    """
    機能: 共有gzからRecordと技法・Source定時だけを読み出す。
    引数: line(str)は一場のJSON本文。
    返り値: dictは3topとC0の技法入力だけ。不許可値は未展開。
    """
    top = object_spans(line)
    result = decode_fields(line, top, ("session", "entry_observations"))
    result["grid_decisions"] = []
    for begin, _ in array_spans(line, top["grid_decisions"][0]):
        fields = object_spans(line, begin)
        g = decode_fields(line, fields, ("at", "window", "clock_allowed", "block_reason", "entry", "events", "source"))
        c0 = object_spans(line, fields["c0"][0])
        base = object_spans(line, c0["base"][0])
        g["published"] = decode_fields(line, base, ("quote", "technical", "chart_pair"))
        require(g["source"]["closes"] == [], "定時Source通知は空")
        result["grid_decisions"].append(g)
    return result

def before_grid(record: dict, grid: dict) -> bool:
    """
    機能: 同時計の将来原行を要求時の履歴へ混ぜない。
    引数: record/grid(dict)は公開点と定時。
    返り値: boolは要求時までに公開済みなら真。
    """
    x, gq = record["input"], grid["published"]["quote"]
    if x["at"] != grid["at"]:
        return x["at"] < grid["at"]
    q = x["quote"]
    return q["index"] <= gq["index"] and q["line"] <= gq["line"]

def availability(data: dict) -> dict:
    """
    機能: 一場の公開Recordを旧照合と独立finderへ別々に渡す。
    引数: data(dict)は損益を含まない共有射影。
    返り値: dictは分母・完成出典・定時候補だけ。
    """
    finder, legacy, cursor = PRICE.PriceTracker(data["session"]), BASE.Sequence(), 0
    records, grids, rows = data["entry_observations"], data["grid_decisions"], []
    for index, g in enumerate(grids):
        while cursor < len(records) and before_grid(records[cursor], g):
            legacy.feed(records[cursor])
            finder.feed(records[cursor], index)
            cursor += 1
        require(legacy.snapshot(g["at"]) == g["events"], "独立計数時の旧event全文")
        pub, at = g["published"], g["at"]
        require(BASE.evaluate(at, pub["quote"], pub["technical"], pub["chart_pair"], g["events"]) == g["entry"], "独立計数時の旧entry全文")
        snap = finder.snapshot(at)
        for state, old in zip(snap["directions"], g["entry"]["directions"], strict=True):
            side = state["side"]
            require(side == old["side"], "独立/旧方向の結合")
            e = finder.states[side].episode
            complete = e is not None and e.v is not None
            band_known = next(c["known"] for c in old["checks"] if c["id"] == "当時新規気配") and state["high"] is not None
            held = bool(band_known and min(side*pub["quote"]["bid"], side*pub["quote"]["ask"]) > side*state["high"]["close"])
            refs = [r["reference"] for r in g["source"]["lots"] if r["reference"]["side"] == side and r["reference"]["quantity"] > 0]
            live = [r for r in refs if not r["closing"]]
            row = {"session": data["session"], "at": at, "side": side, "時計許可": g["clock_allowed"],
                   "旧E0資格": old["e0_allowed"], "旧E0既知": old["current_known"], "旧E1資格": old["e1_allowed"],
                   "独立既知": state["known"], "stage": state["stage"], "完成現在維持": complete,
                   "独立v期限内": state["trigger_valid"], "H帯既知": band_known, "H両BBO保持": held,
                   "独立技法資格": state["trigger_valid"] and old["e0_allowed"] and held,
                   "Source同方向": len(refs), "Source非closing": len(live),
                   "Source非closing_ID": [r["id"] for r in live],
                   "現在未知check": [c["id"] for c in old["checks"] if not c["known"]],
                   "現在不成立check": [c["id"] for c in old["checks"] if c["known"] and not c["passed"]],
                   "独立snapshot": state}
            rows.append(row)
            for c in finder.completions:
                if c["side"] == side and c["次定時番号"] == index and c["最初の定時"] is None:
                    active = complete and c is e.completion
                    c["最初の定時"] = {"at": at, "時計許可": g["clock_allowed"], "同完成を維持": active,
                                       "失効": c["失効"], "v期限内": at-c["v"]["bar_end"] < 900,
                                       "旧E0資格": old["e0_allowed"], "旧E1資格": old["e1_allowed"],
                                       "H両BBO保持": bool(active and held), "Source非closing": len(live)}
    while cursor < len(records):
        legacy.feed(records[cursor])
        finder.feed(records[cursor])
        cursor += 1
    return {"finder": finder, "rows": rows, "全定時": len(grids), "時計許可定時": sum(g["clock_allowed"] for g in grids)}

def summarize(sessions: list) -> dict:
    """
    機能: 完成・定時・現在資格・Sourceの分母を別々に合算する。
    引数: sessions(list[dict])は一場ごとの独立観測。
    返り値: dictは可用性countsと小型出典だけ。
    """
    finders = [s["finder"] for s in sessions]
    episodes = [e for f in finders for e in f.episodes]
    completions = [c for f in finders for c in f.completions]
    rows = [r for s in sessions for r in s["rows"] if r["時計許可"]]
    first = [c["最初の定時"] for c in completions if c["最初の定時"] is not None]
    counters = sum((f.diagnostic_counts for f in finders), Counter())
    phase_counts = sum((e.counts for e in episodes), Counter())
    ready = [r for r in rows if r["独立技法資格"]]
    levels = Counter(e.status for e in episodes)
    statuses = ("可用", "構造H<=L", "足不足", "連続足欠落", "公開又はClose未知", "point出典不一致")
    return {"場数": len(sessions), "全定時": sum(s["全定時"] for s in sessions),
            "時計許可定時": sum(s["時計許可定時"] for s in sessions), "時計許可定時方向": len(rows),
            "Record等counter": dict(counters), "価格段階counter": dict(phase_counts),
            "i/p別episode版": len(episodes), "H/L状態": {k: levels[k] for k in statuses},
            "完成attempt": len(completions), "完成後次定時あり": len(first),
            "完成後次定時なし": len(completions)-len(first),
            "最初の定時で失効": dict(Counter(g["失効"] or "維持" for g in first)),
            "最初の定時v期限切れ": sum(not g["v期限内"] for g in first),
            "定時段階": dict(Counter(r["stage"] for r in rows)),
            "時計許可の分母別": {
                "旧E0資格": sum(r["旧E0資格"] for r in rows), "旧E0未知": sum(not r["旧E0既知"] for r in rows),
                "旧E1資格": sum(r["旧E1資格"] for r in rows), "独立必要未知": sum(not r["独立既知"] for r in rows),
                "Source同方向あり": sum(r["Source同方向"] > 0 for r in rows),
                "完成現在維持": sum(r["完成現在維持"] for r in rows),
                "v期限内": sum(r["独立v期限内"] for r in rows),
                "v期限内かつE0": sum(r["独立v期限内"] and r["旧E0資格"] for r in rows),
                "独立技法資格": len(ready), "独立資格かつ非closingSource": sum(r["Source非closing"] > 0 for r in ready),
                "独立資格の非closingSource延べID": sum(r["Source非closing"] for r in ready),
                "独立資格かつ旧E1資格": sum(r["旧E1資格"] for r in ready),
                "独立資格かつ旧E1不成立": sum(not r["旧E1資格"] for r in ready)},
            "完成維持方向の現在未知check重複": dict(Counter(c for r in rows if r["完成現在維持"] for c in r["現在未知check"])),
            "完成維持方向の現在不成立check重複": dict(Counter(c for r in rows if r["完成現在維持"] for c in r["現在不成立check"])),
            "完成出典": completions, "資格候補出典": ready}


def normalize_diagnostic_counts(counts: dict) -> dict:
    """
    機能: 純APIで具体化した失効名をhistorical可用性の表示名へ写す。
    引数: counts(dict)は純器の診断counter。
    返り値: dictは同じ現象の旧表示名。価格・候補選択は変更しない。
    """
    reasons = {"静観又は場末のため失効":"窓停止", "確定足の必要値又は鮮度が未知":"必要値又は鮮度未知",
               "15分背景が同方向を支持しない":"15分背景が同方向でない", "Source時間窓を開始":"窓epoch変更",
               "原板終端後のため失効":"EOF", "Last不良で必要値を失効":"Last不良",
               "確定3分の欠足又は前値結合が不成立":"3分欠足又は前値不整合"}
    out = Counter()
    for key,value in counts.items():
        if key in ("bars", "expired_triggers"):
            continue
        prefix="文脈破棄:"
        if key.startswith(prefix):
            name=key.removeprefix(prefix);key=prefix+reasons.get(name,name)
        out[key]+=value
    return dict(out)


def completion_identity(row: dict) -> dict:
    """
    機能: 全完成の価格点と公開出典だけを小型射影する。
    引数: row(dict)は固定可用性又は純器の完成。
    返り値: dictはi/p/b/P/h/v・H/L等を含む同一性射影。
    """
    keys=("session","id","side","window","epoch_start","i_birth","i","p","H","L","b","P","h_first","h","v")
    return {k:row[k] for k in keys}


def candidate_identity(row: dict) -> dict:
    """
    機能: reasonの表示具体化だけを除き候補の全公開値を比較する。
    引数: row(dict)は定時資格候補。
    返り値: dictはSource IDs・現在資格・価格状態・期限の全値。
    """
    out=deepcopy(row)
    out["独立snapshot"].pop("reason")
    return out


def parser_artificial() -> dict:
    """
    機能: 禁止top値をJSON展開しないことと同時計の後原行除外を確認する。
    引数: なし。
    返り値: dictは4人工の成功。価格器を人工のために変更しない。
    """
    line='{"session":"人工","entry_observations":[],"grid_decisions":[],"profit_contexts":{"禁止値":THIS_IS_NOT_JSON},"closed":{"禁止値":THIS_IS_NOT_JSON}}'
    require(project_line(line)=={"session":"人工","entry_observations":[],"grid_decisions":[]},"禁止値を値へ展開しない")
    grid={"at":900,"published":{"quote":{"index":4,"line":7}}}
    require(before_grid({"input":{"at":899,"quote":{"index":3,"line":6}}},grid),"過去公開を含める")
    require(before_grid({"input":{"at":900,"quote":{"index":4,"line":7}}},grid),"同時計公開済行を含める")
    require(not before_grid({"input":{"at":900,"quote":{"index":5,"line":8}}},grid),"同時計の後原行を含めない")
    return {"成功":True,"照合数":4,"範囲":"禁止値の字句skipと同時計Quote境界。指標/価格算法の新実装なし"}


def sha(path: Path) -> str:
    """
    機能: 明示入力と計算器の不変指紋を得る。
    引数: path(Path)は保存先。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """
    機能: parser人工の後、共有判断を1走査しhistorical可用性へ結ぶ。
    引数: --input/--expected/--out(Path)は共有gz・固定可用性・新証拠。
    返り値: None。不一致・入力変化・出力既存時は停止する。
    """
    parser=argparse.ArgumentParser(description="損益を展開せず独立価格可用性を再確認")
    for key in ("input","expected","out"):
        parser.add_argument("--"+key,type=Path,required=True)
    args=parser.parse_args()
    require(not args.out.exists(),"新しい証拠出力先が必要")
    watched=[args.input,args.expected,Path(__file__),PRICE_PATH,PRICE.AUDIT_PATH]
    before={str(p.resolve()):sha(p) for p in watched}
    art=parser_artificial()
    expected=json.loads(args.expected.read_text(encoding="utf-8"))
    require(expected["成功"] and expected["入力SHA256"]==sha(args.input),"可用性正本の対象入力SHA")
    sessions=[]
    with gzip.open(args.input,"rt",encoding="utf-8") as stream:
        for line in stream:
            sessions.append(availability(project_line(line)))
    actual=summarize(sessions)
    original=expected["可用性"]
    compare_fields=("場数","全定時","時計許可定時","時計許可定時方向","価格段階counter","i/p別episode版","H/L状態",
                    "完成attempt","完成後次定時あり","完成後次定時なし","最初の定時で失効","最初の定時v期限切れ",
                    "定時段階","時計許可の分母別","完成維持方向の現在未知check重複","完成維持方向の現在不成立check重複")
    for key in compare_fields:
        require(actual[key]==original[key],"可用性分母/段階同値:"+key)
    require(normalize_diagnostic_counts(actual["Record等counter"])==original["Record等counter"],"Record/出生/失効の歴史表示射影")
    completions=[completion_identity(row) for row in actual["完成出典"]]
    require(completions==[completion_identity(row) for row in original["完成出典"]],"全完成の全i/p/b/P/h/v価格出典")
    candidates=[candidate_identity(row) for row in actual["資格候補出典"]]
    require(candidates==[candidate_identity(row) for row in original["資格候補出典"]],"全資格候補の価格/量/Source/現在資格/期限")
    require(before=={str(p.resolve()):sha(p) for p in watched},"明示入力と純器/指標依存の前後一致")
    counters=Counter();resets=Counter()
    for session in sessions:
        value=session["finder"].counts();resets.update(value.pop("resets"));counters.update(value)
    price_counts=dict(counters);price_counts["resets"]=dict(resets)
    result={"成功":True,"確認時刻UTC":datetime.now(timezone.utc).isoformat(),"scope":"既使用共有判断のnoPnL射影。原板/新指標/新価格算法/金融を運転しない",
            "parser人工":art,"入力と依存SHA256":before,"前後不変":True,"場数":len(sessions),
            "旧event全文同値枠":actual["全定時"],"旧entry二方向全文同値枠":actual["全定時"],
            "分母と段階比較":list(compare_fields),"全完成の価格出典同値":len(completions),"全資格候補同値":len(candidates),
            "時計許可の分母別":actual["時計許可の分母別"],"純API全66場counter":price_counts,
            "表示差の扱い":"reasonの具体化だけを候補比較から除き、診断失効名は明示写像。全価格点・現在資格・Source IDs・枚数・期限は完全一致",
            "禁止操作":{"損益又はClosed展開":0,"取引診断読取":0,"新原板読取":0,"金融又は市場再生":0,"閾値変更":0}}
    with args.out.open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write("\n")
    print(json.dumps({"成功":True,"parser人工":4,"場":len(sessions),"旧照合枠":actual["全定時"],"完成出典":len(completions),"候補":len(candidates)},ensure_ascii=False))


if __name__=="__main__":
    main()
