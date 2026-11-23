"""Source通知の同じ一走査で88公開足・Last不良・呼出順を原板へ結ぶ。"""

from collections import Counter
import importlib.util
from pathlib import Path


PATH = Path(__file__).with_name("イベント保存照合.py")
SPEC = importlib.util.spec_from_file_location("event88_saved_for_raw", PATH)
EVENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVENT)


class RawEvents:
    """固定指標の出力を使う範囲を明示し、価格足と失効原行を別計算する。"""

    def __init__(self, saved: dict, start: float, end: float, core: set, us: float, audit: object, check: object) -> None:
        """
        機能: 一場の原板結合を初期化し、疎な入力をordinalへ索引する。
        引数: saved(dict)、start/end/us(float)、core(set)、audit/check(object)は保存・時計・照合。
        返り値: None。原板を自ら再走査せず呼出元の同じ原行を受ける。
        """
        self.saved, self.start, self.end, self.core, self.us, self.audit, self.check = saved, start, end, core, us, audit, check
        self.begin, self.count, self.bad, self.high, self.low, self.close = start, 0, False, 0., 0., 0.
        seed = saved["seed_view"]
        EVENT.validate_technical(start, seed)
        input_end = saved["input_end"]
        EVENT.require(input_end is None or (set(input_end) == {"time", "reference", "source_line"}
                      and EVENT.finite(input_end["time"]) and start <= input_end["time"] < end
                      and input_end["reference"] in ("NK225", "TOPIX") and type(input_end["source_line"]) is int and input_end["source_line"] > 0), "統合入力終端のschema/範囲")
        self.previous_close = seed["close3"] if seed["close3"] > 0 else None
        self.published_close, self.published_tr, self.bar_end, self.bar15_end, self.published_valid = 0., 0., 0., 0., False
        self.ordinal, self.used, self.tracker = 0, set(), EVENT.Sequence()
        self.records = {}
        for row in saved["entry_observations"]:
            ordinal = row["input"]["ordinal"]
            EVENT.require(type(ordinal) is int and ordinal not in self.records, "入口trace ordinal重複")
            self.records[ordinal] = row
        self.last_call, self.eof, self.counters = None, False, Counter()
        self.profits = {}
        for row in saved["profit_contexts"]:
            index = row["quote"]["index"]
            EVENT.require(index not in self.profits, "利益context原行の重複")
            self.profits[index] = row
        self.profit_seen = set()

    def window(self, at: float) -> tuple[str, float]:
        """
        機能: 旧Sourceを進めず独立eventの時間窓/epochを別式で構成する。
        引数: at(float)は公開時計。
        返り値: tuple[str,float]は窓名とepoch開始。
        """
        if at >= self.end-600:
            return "場末", self.end-600
        if self.saved["session"].endswith("_Day"):
            return "D164_15", self.start
        if at < self.us-900:
            return "P164_06", self.start
        if at < self.us+900:
            return "静観", self.us-900
        return "U165_03", self.us+900

    def advance(self, at: float) -> None:
        """
        機能: 原板Lastから形成した全180秒足を補完せず確定する。
        引数: at(float)は原行又は公開clock。
        返り値: None。空/不良足は前Closeと公開値をresetする。
        """
        while self.begin+180 <= at:
            end = self.begin+180
            self.published_valid = self.count > 0 and not self.bad
            if self.published_valid:
                self.published_close = self.close
                tr = self.high-self.low
                if self.previous_close is not None:
                    tr = max(tr, abs(self.high-self.previous_close), abs(self.low-self.previous_close))
                self.published_tr, self.previous_close = tr, self.close
                self.counters["正常3分足"] += 1
            else:
                self.published_close, self.published_tr, self.previous_close = 0., 0., None
                self.counters["空又は不良3分足"] += 1
            self.bar_end, self.begin, self.count, self.bad = end, end, 0, False
            self.high, self.low, self.close = 0., 0., 0.
        if at-self.start >= 900:
            self.bar15_end = self.start + int((at-self.start)//900)*900

    def call(self, at: float, origin: str, q: dict) -> None:
        """
        機能: 全call ordinalを別計算し、新足/Last0/窓/期限の記録欠落も検査する。
        引数: at(float)、origin(str)、q(dict)は当時処理と原気配。
        返り値: None。保存readyだけを入力へして見逃しを無視しない。
        """
        self.ordinal += 1
        window, epoch = self.window(at)
        end = self.saved["input_end"]
        after_eof = end is None or at > end["time"]
        epoch_changed = self.last_call is None or (window, epoch) != self.last_call["epoch"]
        bar_changed = self.last_call is None or self.bar_end != self.last_call["end"]
        expires = any(s["event"] is not None and at-s["event"]["confirmation"]["bar_end"] >= 900 for s in self.tracker.states)
        needed = (epoch_changed or bar_changed or origin == "quote" and q["last"] <= 0
                  or after_eof and not self.eof or expires)
        record = self.records.get(self.ordinal)
        EVENT.require(not needed or record is not None, "新足/Last不良/窓/期限/EOFのtrace欠落")
        if record is not None:
            x, v = record["input"], record["input"]["technical"]
            self.check(self.audit, "入口traceの公開時計/元/窓/EOFと原板気配", {k:x[k] for k in ("ordinal","at","origin","window","epoch_start","after_eof","quote")},
                       {"ordinal":self.ordinal,"at":float(at),"origin":origin,"window":window,"epoch_start":float(epoch),"after_eof":after_eof,"quote":q})
            self.check(self.audit, "入口3分Close/TR/公開終端の原板別計算", {k:v[k] for k in ("close3","tr3","bar3_end","bar15_end")},
                       {"close3":self.published_close,"tr3":self.published_tr,"bar3_end":self.bar_end,"bar15_end":self.bar15_end})
            if not self.published_valid:
                self.check(self.audit, "不良/空足とLast0の全指標既知旗reset", {k:v[k] for k in EVENT.TECH_FLAGS}, {k:False for k in EVENT.TECH_FLAGS})
            self.tracker.feed(record)
            self.used.add(self.ordinal)
            self.counters["原板結合trace"] += 1
        self.last_call, self.eof = {"epoch":(window,epoch),"end":self.bar_end}, after_eof
        self.counters[origin] += 1

    def clock(self, at: float, q: dict) -> None:
        """
        機能: 同時計の3分公開→旧core公開を別ordinalとして配送する。
        引数: at(float)、q(dict)は合成clockと最後の実原行。
        返り値: None。Source/金融のfillやlastを進めない。
        """
        self.advance(at)
        if at > self.start and (at-self.start)%180 == 0:
            self.call(at,"three_timer",q)
        if at in self.core:
            self.call(at,"core_timer",q)

    def quote(self, q: dict, source_index: int) -> None:
        """
        機能: 当原行Lastの足形成/失効を反映し、旗snapshotの気配も同時結合する。
        引数: q(dict)、source_index(int)は全受理原行と別の正Last源Index。
        返り値: None。同じ原板一走査の現在行だけを使う。
        """
        self.advance(q["time"])
        if q["last"] <= 0:
            self.bad, self.previous_close, self.published_valid = True, None, False
            self.published_close, self.published_tr = 0., 0.
            self.counters["Last不良入力"] += 1
        else:
            if self.count == 0:
                self.high = self.low = q["last"]
            else:
                self.high, self.low = max(self.high,q["last"]), min(self.low,q["last"])
            self.close, self.count = q["last"], self.count+1
        self.call(q["time"],"quote",q)
        if q["index"] in self.profits:
            row = self.profits[q["index"]]
            self.check(self.audit,"初回利益snapshotの原板気配全文",row["quote"],q)
            v = row["technical"]
            self.check(self.audit,"初回利益の公開Close/TR/足時計",{k:v[k] for k in ("close3","tr3","bar3_end","bar15_end")},
                       {"close3":self.published_close,"tr3":self.published_tr,"bar3_end":self.bar_end,"bar15_end":self.bar15_end})
            if row["current"] is not None:
                c = row["current"]
                self.check(self.audit,"利益Current抜粋の当時源時計/別Index/物理行",{k:c[k] for k in ("reference","time","received","source_index","source_line")},
                           {"reference":"NK225","time":q["time"],"received":q["time"],"source_index":source_index,"source_line":q["line"]})
            self.profit_seen.add(q["index"])

    def finish(self, last: dict) -> dict:
        """
        機能: trace全件/利益全件と統合EOF依存の限定を検査し要約する。
        引数: last(dict)はNKの最後の受理原行。
        返り値: dictは一走査内の結合件数と依存範囲。
        """
        EVENT.require(self.used == set(self.records), "未結合又は架空ordinalの入口trace")
        EVENT.require(self.profit_seen == set(self.profits), "未結合初回利益snapshot")
        end = self.saved["input_end"]
        if end is None:
            EVENT.require(last["index"] < 0, "NK入力があるのに統合EOFがnull")
        else:
            EVENT.require(end["time"] >= last["time"], "統合EOFがNK終端より過去")
            if end["reference"] == "NK225":
                self.check(self.audit,"NK由来統合EOFの原板終端完全一致",end,{"time":last["time"],"reference":"NK225","source_line":last["line"]})
        tech = self.saved["technical_equivalence"]
        self.check(self.audit,"旧Technical比較の全call件数",{k:tech[k] for k in ("core_calls","quote_calls")},
                   {"core_calls":self.counters["core_timer"],"quote_calls":self.counters["quote"]})
        return {"処理完了":True,"全call":self.ordinal,"原板結合trace":len(self.used),"利益snapshot":len(self.profit_seen),
                "内訳":dict(self.counters),"入力終端":end,"seed依存":"BeginSession前SeedViewの前Close。元指標全前史の独立実装ではない",
                "統合EOF限定":"TOPIX由来終端は固定Runtime/入力SHA/Source同値依存。TOPIX終端本文の追加独立走査は行わない"}
