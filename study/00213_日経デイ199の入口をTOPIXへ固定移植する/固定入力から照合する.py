"""保存した純入口・原板指紋・固定ソースから、取引明細を別の出力先に再生する。"""
from argparse import ArgumentParser
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import subprocess
import sys

from 比較する import CASES, ROOT, HERE, digest


# ----------------------------------------
def main() -> None:
    """
    機能：原板と銘柄・場の対応を確認し、再生済みの四口座と全取引を比較する。
    引数：CLI --indices（Path）は原行索引、--output（Path）は検算作業先。
    返り値：None。異なるパスに復元した資源も、原板・索引の物理指紋と価格・取引結果で照合する。
    """
    parser = ArgumentParser()
    parser.add_argument('--indices', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    scratch = args.output.resolve()
    scratch.mkdir(parents=True,exist_ok=True)
    assets = next((ROOT/'inputs').glob('00213_*'))
    subprocess.run([sys.executable,str(assets/'純入力を展開.py'),'--output',str(scratch)],check=True)
    records = json.loads((args.indices/'manifest.json').read_bytes())['scenes']
    raw = json.loads((assets/'原板と分足の指紋.json').read_bytes())
    frozen = json.loads((HERE/'原行索引の指紋.json').read_bytes())
    scenes = []
    for ref, record in zip(raw,records,strict=True):
        scene = ref['場']
        assert scene==record['session']
        item = record['index']
        assert record['actual_raw_sha256']==ref['raw']['sha256']
        assert item['sha256']==frozen[scene]
        item['path'] = str((args.indices/item['path']).resolve())
        assert digest(Path(item['path']))==item['sha256']
        day = scene.endswith('_Day')
        midnight = datetime.fromisoformat(scene[:10]).replace(tzinfo=timezone(timedelta(hours=9)))
        start = midnight+timedelta(hours=8,minutes=45) if day else midnight+timedelta(hours=17)
        end = midnight+timedelta(hours=15,minutes=45) if day else midnight+timedelta(days=1,hours=6)
        scenes.append({'session':scene,'start':start.timestamp(),'end':end.timestamp()})
    for name, rows in [('索引計画.json',scenes),('原行索引/manifest.json',records)]:
        path = scratch/name
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({'scenes':rows},ensure_ascii=False),encoding='utf-8')
    seal = json.loads((HERE/'移植金融前の条件.json').read_bytes())['指紋']
    for name, pure, scale in CASES:
        assert digest(scratch/pure)==seal['work/今回移植/'+pure]
        replay = scratch/(name+'.json.gz')
        subprocess.run([sys.executable,str(HERE/'金融再生.py'),'--input',str(scratch),
                        '--pure',str(scratch/pure),'--scale',str(scale),'--out',str(replay)],check=True)
        assert digest(replay)==digest(HERE/'金融正本'/replay.name),name
    print('保存した全四口座の約定・決済・損益・未参加場・予約の記録が一致しました。')


if __name__=='__main__':
    main()
