"""129の保存正本と小型コードを未作成の作業先へ復元する。Rawは読まない。"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import shutil
import zipfile

FORMAL=Path(__file__).resolve().parent.parent
ROOT=FORMAL.parents[1]


def sha(body: bytes) -> str:
    """
    機能: 保存bytesのSHAを返す。
    引数: body(bytes)。返り値: str。
    """
    return hashlib.sha256(body).hexdigest()


def put(root: Path, relative: str, body: bytes) -> None:
    """
    機能: 作業先内の未作成ファイルだけへ書く。
    引数: root(Path)/relative(str)/body(bytes)。返り値: None。
    """
    path=(root/relative).resolve()
    assert path.is_relative_to(root),relative
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():assert path.read_bytes()==body;return
    with path.open('xb') as stream:stream.write(body)


def main() -> None:
    """
    機能: ZIP/入力/結果/集計を正本SHA照合して新規作業先へ復元する。
    引数: --destination(str)/--inputs-only(bool)。返り値: None。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--destination',required=True,type=Path);parser.add_argument('--inputs-only',action='store_true');args=parser.parse_args()
    dest=args.destination.resolve()
    assert not dest.exists(),'未作成の作業先を指定'
    dest.mkdir(parents=True)
    for name,index in [('129コード.zip','コード復元索引.json'),('検算と保管の追補コード.zip','追補コード索引.json')]:
        folder=FORMAL/'再現資料';manifest=json.loads((folder/index).read_text(encoding='utf-8'));body=(folder/name).read_bytes();assert sha(body)==manifest['ZIP_SHA256']
        with zipfile.ZipFile(folder/name) as z:
            assert z.testzip() is None
            for item in manifest['格納源']:
                b=z.read(item['path']);assert sha(b)==item['sha256'];put(dest,item['path'],b)
    records=json.loads((FORMAL/'保管索引.json').read_text(encoding='utf-8'))['圧縮正本']
    paths={'入力.json.gz':'work/129短期回復の評価/入力.json','新入口結果.json.gz':'work/129短期回復の評価/新入口結果.json','元出生区間対照結果.json.gz':'work/129短期回復の評価/元出生結果.json'}
    for item in records:
        name=Path(item['path']).name
        if name not in paths:continue
        if args.inputs_only and name!='入力.json.gz':continue
        packed=(ROOT/item['path']).read_bytes();assert sha(packed)==item['sha256'];decoded=gzip.decompress(packed);assert sha(decoded)==item['decoded_sha256'];put(dest,paths[name],decoded)
    old=ROOT/'inputs/00128_Raw価格時計の独立出生/gap300入力.json.gz'
    decoded=gzip.decompress(old.read_bytes());assert sha(decoded)=='474455be28a60248c7418fd69e123297738f6f782648b9c52aab076384e3c384'
    put(dest,'work/128Raw時計の評価/gap300入力.json',decoded)
    if not args.inputs_only:
        for src,target in [('新入口集計.json','新入口集計'),('元出生区間対照集計.json','元出生集計')]:put(dest,f'work/129短期回復の評価/{target}/集計.json',(FORMAL/'成果物'/src).read_bytes())
    print(json.dumps({'成功':True,'復元先':str(dest),'原板読取':False,'巨大公表コピー':False,'金融再計算':False,'内容':'小型ソース・固定入力2' if args.inputs_only else '小型ソース・固定入力2・結果2・集計2'},ensure_ascii=False))


if __name__=='__main__':
    main()
