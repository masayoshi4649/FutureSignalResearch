"""共通原板の旧価格と呼値換算値を85場・全原行、全分足について照合する。"""
from argparse import ArgumentParser
from pathlib import Path
import csv
import gzip
import json
import numpy as np


# ----------------------------------------
def main() -> None:
    """
    機能：変換の数値を別の構造化配列読込とCSV列読込で調べる。
    引数：CLIの--input（Path）は作業先、--output（Path）は観測件数の記録先。
    返り値：None。価格以外の変化又は価格倍率の不一致は検査エラー。
    """
    parser = ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    plain = json.loads((args.input/'母集団計画.json').read_bytes())
    equivalent = json.loads((args.input/'呼値換算/母集団計画.json').read_bytes())
    dtype=np.dtype([('time','<f8'),('line','<i8'),('last','<f8'),('bid','<f8'),('ask','<f8'),('ok','<u8')])
    totals={'場数':0,'原行':0,'1分足行':0,'5分足行':0}
    for a,b in zip(plain['scenes'],equivalent['scenes'],strict=True):
        for k in ('session','contract','start','end','expected_quality','raw'):
            assert a[k]==b[k]
        totals['場数']+=1
        original, converted = [np.frombuffer(gzip.decompress(Path(s['quote_index']['path']).read_bytes()),
                                             dtype=dtype,offset=8) for s in (a,b)]
        for k in dtype.names:
            expected=original[k]*20 if k in ('last','bid','ask') else original[k]
            np.testing.assert_array_equal(expected,converted[k])
        totals['原行']+=len(original)
        for key, label in (('csv_1m','1分足行'),('csv_5m','5分足行')):
            with Path(a[key]['path']).open(encoding='utf-8-sig') as in_a, Path(b[key]['path']).open(encoding='utf-8-sig') as in_b:
                for old,new in zip(csv.DictReader(in_a),csv.DictReader(in_b),strict=True):
                    for k,value in old.items():
                        if k in ('open','high','low','close') and value.strip():
                            assert float(new[k])==float(value)*20
                        else:
                            assert new[k]==value
                    totals[label]+=1
    args.output.write_text(json.dumps({'成功':True,**totals},ensure_ascii=False,indent=1)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
