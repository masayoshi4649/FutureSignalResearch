"""169の正式統計から前48だけを抜き、null選択を再現する。"""
from pathlib import Path
from io import BytesIO
import argparse
import hashlib
import importlib.util
import json
import sys
import tempfile
import zipfile

import numpy as np

ROOT=next(parent for parent in Path(__file__).resolve().parents if (parent/'study').is_dir() and (parent/'inputs').is_dir())
TRIAL=ROOT/'study/00169_数量枠の下で技術近傍と任意幅を再探索する'
PREFIX='work/169数量枠と技術近傍/'


def sha(path: Path) -> str:
    """
    機能: 全物理SHAを照合する。
    引数: path(Path)。返り値: str。
    """
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main() -> None:
    """
    機能: ZIP/全memberを確認し、指定時に前48統計だけで選択A/Bを再生する。
    引数: CLI --selector-replay。返り値: None。自然価格/追加7/自然注文を再読しない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--selector-replay',action='store_true');args=parser.parse_args()
    index=json.loads((TRIAL/'再現資料/保存索引.json').read_bytes())
    archive_by_name={}
    for group in index['正本']:
        ref=group['archive'];path=ROOT/ref['path'];assert sha(path)==ref['sha256'] and path.stat().st_size==ref['bytes']
        archive_by_name[path.name]=path
        with zipfile.ZipFile(path) as source:
            assert source.testzip() is None
            for member in group['members']:
                body=source.read(member['path']);assert len(body)==member['bytes'] and hashlib.sha256(body).hexdigest()==member['sha256']
    if not args.selector_replay:print('169の全Source/統計member照合成功');return
    book=json.loads((TRIAL/'条件.json').read_bytes());assert sha(TRIAL/'条件.json')==index['条件']['sha256']
    with zipfile.ZipFile(archive_by_name['統計正本.zip']) as source:
        axes=json.loads(source.read(PREFIX+'旧73探索/統計軸.json'))
        sealed=json.loads(source.read(PREFIX+'旧73探索/前半固定AとBの封印.json'))
        with np.load(BytesIO(source.read(PREFIX+'旧73探索/数量枠探索の統計配列.npz')),allow_pickle=False) as arrays:
            assert arrays['metrics'].shape==tuple(axes['shape']) and arrays['bands'].shape==tuple(axes['bands_shape'])
            front=arrays['metrics'].reshape(-1,3,len(axes['fields']))[:,axes['periods'].index('前48場')].copy()
            bands=arrays['bands'].reshape(-1,3,2,3,len(axes['fields']))[:,axes['periods'].index('前48場'),axes['band_clocks'].index('q0')].copy()
    with tempfile.TemporaryDirectory(prefix='169selector_') as temporary:
        path=Path(temporary)/'selector169.py'
        with zipfile.ZipFile(archive_by_name['Source.zip']) as source:path.write_bytes(source.read(PREFIX+'selector169.py'))
        spec=importlib.util.spec_from_file_location('正式selector169',path);selector=importlib.util.module_from_spec(spec)
        sys.modules[spec.name]=selector;spec.loader.exec_module(selector)
        result=selector.select_front48(front,bands,axes['fields'],book)
    assert sealed['選択']=={'A':None,'B':None}
    assert all(result[name]['position'] is None and not result[name]['eligible'].any() for name in ('A','B'))
    proof={'成功':True,'前48のみ':True,'後25又は追加7を引数に含めない':True,'A':None,'B':None,
           '政策数':len(front),'条件SHA256':sha(TRIAL/'条件.json'),'自然再生':False}
    print(json.dumps(proof,ensure_ascii=False))


if __name__=='__main__':main()
