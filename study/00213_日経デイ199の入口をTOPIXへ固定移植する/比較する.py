"""条件・当時入力・物理索引を照合し、固定した四つの口座を再生する。"""
from argparse import ArgumentParser
from pathlib import Path
import hashlib
import json
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / 'work/今回移植'
CASES = (
    ('213_01額面そのまま', '純入口.npz', 1),
    ('213_02出口幅のみ換算', '純入口.npz', 0.05),
    ('213_03入口出口呼値換算', '呼値換算/純入口.npz', 0.05),
    ('213_04保留導入前の呼値換算', '呼値換算/基準179.npz', 0.05),
)


# ----------------------------------------
def digest(path: Path) -> str:
    """
    機能：実行に使うファイルをSHA256で識別する。
    引数：path（Path）は固定資源。
    返り値：strは物理SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


# ----------------------------------------
def main() -> None:
    """
    機能：保存済み条件との一致を確認し、四口座を指定先に独立に再計算する。
    引数：CLI --out（Path）は金融結果の保存先。
    返り値：None。集計とCSV表示に先立つ取引単位の結果を生成する。
    """
    parser = ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    paths = [HERE / name for name in ('比較条件.md','金融再生.py','比較する.py')]
    paths += [ROOT / 'work' / name for name in ('173追加なしの因果再生/engine173.py',
              '179終了前決済/early179.py','163任意幅の数値化/arrays163.py')]
    paths += [SOURCE / name for name in ('索引計画.json','原行索引/manifest.json','純入口を作る.py',
              '呼値を揃える.py','母集団.py','純部品の依存.json','呼値換算/純部品の依存.json')]
    paths.extend(SOURCE / name for _,name,_ in CASES)
    body = {'条件':list(CASES), '指紋':{p.relative_to(ROOT).as_posix():digest(p) for p in paths}}
    seal = HERE / '移植金融前の条件.json'
    if seal.exists():
        assert json.loads(seal.read_bytes()) == json.loads(json.dumps(body))
    else:
        seal.write_text(json.dumps(body,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for name, pure, scale in CASES:
        subprocess.run([sys.executable, str(HERE/'金融再生.py'), '--input', str(SOURCE),
                        '--pure',str(SOURCE/pure),'--scale',str(scale),'--out',str(args.out/(name+'.json.gz'))],
                       check=True)


if __name__=='__main__':
    main()
