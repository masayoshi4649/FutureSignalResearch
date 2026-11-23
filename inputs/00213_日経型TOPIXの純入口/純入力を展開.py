"""保存した四つの固定入口を決済計算用の元の配列形式へ展開する。"""
from pathlib import Path
from argparse import ArgumentParser
import hashlib
import json
import numpy as np


# ----------------------------------------
def main() -> None:
    """
    機能：恒久入力の指紋を検査し、重複保存を省いた共通列を4候補に展開する。
    引数：CLI --output（Path）は作業用の出力先。
    返り値：None。既存npzがあれば全列を照合する。
    """
    parser=ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    here=Path(__file__).resolve().parent
    index=json.loads((here/'保存索引.json').read_bytes())
    for item in index['入力']:
        data=(here/item['path']).read_bytes()
        assert hashlib.sha256(data).hexdigest()==item['sha256'] and len(data)==item['bytes']
    forms=json.loads((here/'候補列.json').read_bytes())
    with np.load(here/'全純入口.npz',allow_pickle=False) as stored:
        for mode, directory in [('額面',args.output),('呼値',args.output/'呼値換算')]:
            directory.mkdir(parents=True,exist_ok=True)
            for name in ('純入口','基準179'):
                arrays={k:stored[key] for k,key in forms[mode+name].items()}
                path=directory/(name+'.npz')
                if path.exists():
                    with np.load(path,allow_pickle=False) as expected:
                        assert list(expected.files)==list(arrays)
                        for k, values in arrays.items():
                            assert values.dtype==expected[k].dtype
                            np.testing.assert_array_equal(values,expected[k])
                else:
                    np.savez_compressed(path,**arrays)


if __name__=='__main__':
    main()
