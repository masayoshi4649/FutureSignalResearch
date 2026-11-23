"""恒久167入力だけから固定出生と全26政策を隔離再現する。"""
from pathlib import Path,PurePosixPath
import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
import zipfile

import numpy as np

ROOT=next(parent for parent in Path(__file__).resolve().parents if (parent/'study').is_dir() and (parent/'inputs').is_dir())
TRIAL=ROOT/'study/00167_固定した複合入口を追加七場へ適用する'
INPUT=ROOT/'inputs/00167_追加七場の入口と共用価格索引'


def sha(path: Path) -> str:
    """
    機能: 正式ファイルを全読して物理SHAを返す。
    引数: path(Path)。返り値: str。
    """
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def read(path: Path) -> dict:
    """
    機能: UTF-8の固定JSONを読む。
    引数: path(Path)。返り値: dict。
    """
    return json.loads(path.read_bytes())


def module(path: Path,name: str) -> object:
    """
    機能: 元Sourceを編集せずmain未実行でimportする。
    引数: path(Path)、name(str)。返り値: object。
    """
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec)
    sys.modules[name]=value;spec.loader.exec_module(value);return value


def restore(archive: Path, members: list|None=None) -> int:
    """
    機能: repo内への安全な相対memberだけを復元し既存byte同体を要求する。
    引数: archive(Path)、members(list[str]|None)。返り値: intは確認したmember数。
    """
    count=0
    with zipfile.ZipFile(archive) as source:
        assert source.testzip() is None
        for name in source.namelist():
            if members is not None and name not in members:continue
            relative=PurePosixPath(name);assert not relative.is_absolute() and '..' not in relative.parts
            target=ROOT.joinpath(*relative.parts);assert target.resolve().is_relative_to(ROOT.resolve())
            body=source.read(name)
            if target.exists():assert target.read_bytes()==body,name
            else:target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(body)
            count+=1
    return count


def main() -> None:
    """
    機能: 全正本を照合し、指定時だけ固定ルールを未作成workへ再生する。
    引数: CLI --verify-only、--destination(Path)、--replay。
    返り値: None。原Raw/CSVや別期間選択は実行しない。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--verify-only',action='store_true')
    parser.add_argument('--destination',type=Path)
    parser.add_argument('--replay',action='store_true')
    args=parser.parse_args()
    index=read(TRIAL/'再現資料/保存索引.json')
    for record in index['恒久入力'],index['条件'],index['Source']['archive']:
        path=ROOT/record['path'];assert path.stat().st_size==record['bytes'] and sha(path)==record['sha256']
    for record in read(INPUT/'保存索引.json')['files']:
        path=ROOT/record['path'];assert path.stat().st_size==record['bytes'] and sha(path)==record['sha256']
    archive=ROOT/index['Source']['archive']['path']
    with zipfile.ZipFile(archive) as source:
        assert source.testzip() is None
        for record in index['Source']['members']:
            body=source.read(record['path']);assert len(body)==record['bytes'] and hashlib.sha256(body).hexdigest()==record['sha256']
    if args.verify_only:print('正式入力とSource全memberの指紋照合成功');return
    assert args.destination is not None
    destination=args.destination.resolve()
    assert destination.parent==(ROOT/'work').resolve() and not destination.exists(),'ROOT/work直下の未作成folderを指定する'
    restore(archive)
    old=ROOT/'study/00166_未公表の長期指標を捏造せず局所技術で参加を補う/再現資料/出生と統計正本.zip'
    restore(old,['work/166可用指標の階層化/比較/主案と探索結果.json'])
    destination.mkdir();copy_from=ROOT/'work/167固定入口の別期間'
    for name in ('適用する.py','適用基盤167.py','旧73の同体.json'):
        shutil.copyfile(copy_from/name,destination/name)
    if not args.replay:print('Source復元成功。自然の政策再計算は未実行');return
    sys.path.insert(0,str(destination))
    application=module(destination/'適用する.py','正式再現167')
    application.TRIAL=destination/'試行';application.TRIAL.mkdir()
    shutil.copyfile(TRIAL/'条件.json',application.TRIAL/'条件.json')
    application.generate(INPUT/'入口母集団')
    with np.load(INPUT/'固定二案の出生/固定二案の出生.npz',allow_pickle=False) as expected, np.load(destination/'全出生/固定二案の出生.npz',allow_pickle=False) as actual:
        assert set(expected.files)==set(actual.files)
        for name in expected.files:assert np.array_equal(expected[name],actual[name],equal_nan=True),name
    application.evaluate(INPUT/'入口母集団',INPUT/'自然数値表',INPUT/'生成の完了.json')
    for name in ('全比較と全場.json','全取得参照.json','因果監査.json'):
        assert read(destination/'比較'/name)==read(TRIAL/'成果物'/name),name
    (destination/'再現の確認.json').write_text(json.dumps({'成功':True,'元Source非改変':True,'出生全配列同体':True,
        '26政策と取得参照と因果監査同体':True,'原Raw_CSV再読':False},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('固定出生と26政策の保存数値からの再現が成功')


if __name__=='__main__':main()
