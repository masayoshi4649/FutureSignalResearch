"""指定した日経デイまでの実原板・確定足から、固定199_02の当時入力を新しい作業フォルダへ作る。"""
from argparse import ArgumentParser
from datetime import date
from pathlib import Path
import re
import runpy
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def main() -> None:
    """
    機能：216と同じ起点から指定日までのデイ・ナイトを知得順に通し、199_02の非金融入力を生成する。
    引数：CLIの最終デイ（str）、出力（Path）。元の共用原板と固定194の前史を使う。
    返り値：None。母集団・純入口NPZ・原板索引参照と、取得元・原板・足・生成物の指紋を保存する。
    """
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--最終デイ",required=True,type=date.fromisoformat)
    parser.add_argument("--出力",required=True,type=Path)
    args = parser.parse_args()
    into = args.出力.resolve()
    latest = args.最終デイ.isoformat()+"_Day"
    source = runpy.run_path(str(next((ROOT/"study").glob("00215_*/日経/固定入口を再生する.py"))))
    p = source["previous"]
    data = ROOT.parent/"JP_OSE_Data/future/NK225"
    names = sorted(d.name for d in data.iterdir() if d.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}_(?:Day|Night)",d.name)
                   and "2026-11-17_Night"<=d.name<=latest)
    if into.exists() or not names or names[-1]!=latest:
        parser.error("既存の原板にある最終デイと、未使用の作業フォルダを指定してください。")
    for name in names:
        folder = data/name
        if not all((folder/f).is_file() for f in ("candle_1min.csv","candle_5min.csv")) or not any(
                (folder/f).is_file() for f in ("book.jsonl.gz","book.jsonl")):
            parser.error("場の確定足又は原板が足りません。"+name)
    # ----------------------------------------
    p.OUT,p.NEW = into,tuple(names)
    _,_,appended = p.prepare(True)
    builder = ROOT/"work/今回移植/純入口を作る.py"
    subprocess.run([sys.executable,"-X","utf8",str(builder),"--folder",str(into)],check=True)
    assert [s["session"] for s in appended]==names
    p.save(into/"生成入力.json",{"対象最終場":latest,"前史の最終場":"2026-11-17_Day","通過順":names,
           "母集団計画":p.ref(into/"前史十場と追加二場の母集団計画.json"),
           "板索引参照":p.ref(into/"前史十場と追加二場の索引参照.json"),
           "純入口":p.ref(into/"純入口.npz"),"純入口生成器":p.ref(builder)})


if __name__=="__main__":
    main()
