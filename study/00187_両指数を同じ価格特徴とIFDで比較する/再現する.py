"""187の正式Source/恒久入力だけを別作業先へ配置し、固定結果を再現する。"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile

TRIAL=Path(__file__).resolve().parent
REPOSITORY=TRIAL.parents[1]
RELATIVE=Path('study')/TRIAL.name


def read(path):
    """
    機能: 正式JSON又はgzip JSONを読む。
    引数: path(Path)。
    返り値: objectは解析値。
    """
    raw=path.read_bytes();return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)


def digest(path):
    """
    機能: 実ファイルのSHA256を計算する。
    引数: path(Path)。
    返り値: strは16進指紋。
    """
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def attach(source,target):
    """
    機能: 読取専用入力をハードリンクし、異なるボリュームなら一時コピーする。
    引数: source/target(Path)。
    返り値: strは配置方法。生成コードは入力へ書き込まない。
    """
    target.parent.mkdir(parents=True,exist_ok=True)
    try:os.link(source,target);return 'ハードリンク'
    except OSError:shutil.copyfile(source,target);return '一時コピー'


def main():
    """
    機能: 旧workに依存せず純特徴・18金融・診断・独立監査を再実行する。
    引数: CLI --root(str)は空の別作業先、--proof(str|None)は確認票の新規保存先。
    返り値: None。正式Source/入力/金融は変更しない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--proof');args=parser.parse_args()
    target=Path(args.root).resolve();assert target!=REPOSITORY
    assert not target.exists() or not any(target.iterdir()),'作業先は空である必要がある'
    target.mkdir(parents=True,exist_ok=True)
    archive=TRIAL/'Source.zip';source=read(TRIAL/'Sourceと依存.json');assert digest(archive)==source['archive']['sha256']
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            path=(target/info.filename).resolve();assert path.is_relative_to(target)
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(z.read(info.filename))
    for ref in source['members']:assert digest(target/ref['path'])==ref['sha256']
    condition=read(TRIAL/'条件.json');needed={}
    for entries in condition['inputs'].values():
        for entry in entries:
            needed[entry['path']]=entry['sha256'];manifest=entry['manifest'];needed[manifest['path']]=manifest['sha256']
    methods={}
    for name,sha in needed.items():
        original=REPOSITORY/name;assert digest(original)==sha
        how=attach(original,target/name);methods[how]=methods.get(how,0)+1
    here=target/'work/187共通対照';shutil.copyfile(TRIAL/'人工確認187.json',here/'人工確認187.json')
    commands=[['実行187.py','--pure'],['実行187.py','--finance'],['共通条件の差を診断する.py'],['固定口座を独立検査する.py']]
    for command in commands:
        completed=subprocess.run([sys.executable,'-X','utf8',str(here/command[0]),*command[1:]],cwd=target,
            check=True,text=True,encoding='utf-8',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        print(json.dumps({'完了':command,'出力最終行':completed.stdout.splitlines()[-1][:250]},ensure_ascii=False),flush=True)
    checks=[('条件.json',target/RELATIVE/'条件.json'),('純入口の封印.json',here/'純入口の封印.json'),
        ('金融開始前固定.json',here/'金融開始前固定.json'),('全18組安定性.json.gz',here/'全18組安定性.json.gz'),
        ('全18組短表.json',here/'全18組短表.json'),('形成可用性と有効足記憶の診断.json.gz',here/'形成可用性と有効足記憶の診断.json.gz'),
        ('共通尺度と局面構成の診断.json.gz',here/'共通尺度と局面構成の診断.json.gz'),('全18口座の独立確認.json',here/'全18口座の独立確認.json')]
    checks += [('金融正本/'+p.name,here/'金融正本'/p.name) for p in sorted((TRIAL/'金融正本').glob('*.gz'))]
    compared=[]
    for name,path in checks:
        expected=digest(TRIAL/name);assert digest(path)==expected,name;compared.append({'path':name,'bytes':path.stat().st_size,'sha256':expected})
    for product in ('NK225','TOPIX'):
        original=REPOSITORY/'inputs/00187_共通価格特徴'/(product+'.json.gz');actual=here/'純特徴'/(product+'.json.gz')
        expected=digest(original);assert digest(actual)==expected;compared.append({'path':'純特徴/'+product+'.json.gz','bytes':actual.stat().st_size,'sha256':expected})
    proof={'成功':True,'旧work依存':False,'正式Source展開':True,'恒久入力配置':methods,'同体出力数':len(compared),
        '実行環境':sys.version,'比較':compared,'注意':'純生成実測の壁時計時間は再現の同体対象に含めない。原板の恒久複製を作らない。'}
    if args.proof:
        path=Path(args.proof);assert not path.exists();path.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in proof.items() if k!='比較'},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
