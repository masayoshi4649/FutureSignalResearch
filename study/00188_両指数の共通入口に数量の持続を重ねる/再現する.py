"""恒久入力と保存Sourceだけで188の全108口座を別作業領域へ再現する。"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).parent


def literal(value):
    """
    機能: PowerShellの単一引用符へパスを安全に渡す。
    引数: value(Path)は既に検証したパス。
    返り値: strは単一引用符リテラル。
    """
    return "'"+str(value).replace("'","''")+"'"


def main():
    """
    機能: 元workを参照せず純量・金融・診断・独立監査を再生成して正本へ照合する。
    引数: CLI --out(str)はリポジトリwork配下の未作成フォルダ。
    返り値: None。原入力は読み取り参照し、研究成果を上書きしない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--out',default='work/188恒久再現')
    args=parser.parse_args();target=(ROOT/args.out).resolve();workspace=(ROOT/'work').resolve()
    assert target.is_relative_to(workspace) and target!=workspace and not target.exists(),target
    target.mkdir(parents=True)
    with zipfile.ZipFile(HERE/'Source.zip') as archive:
        for info in archive.infolist():
            assert (target/info.filename).resolve().is_relative_to(target)
        archive.extractall(target)
    # ----------------------------------------
    # 大きな原板/共用入力は複製しない。再現器が書き込む先は別workだけ。
    subprocess.run(['powershell.exe','-NoProfile','-Command',
        'New-Item -ItemType Junction -Path '+literal(target/'inputs')+' -Target '+literal(ROOT/'inputs')+' | Out-Null'],check=True)
    trial187='00187_両指数を同じ価格特徴とIFDで比較する'
    condition_dir=target/'study'/trial187;condition_dir.mkdir(parents=True)
    shutil.copy2(ROOT/'study'/trial187/'条件.json',condition_dir/'条件.json')
    base=target/'work/187共通対照';price=base/'純特徴';price.mkdir(parents=True)
    for product in ('NK225','TOPIX'):
        shutil.copy2(ROOT/'inputs/00187_共通価格特徴'/(product+'.json.gz'),price/(product+'.json.gz'))
    shutil.copytree(ROOT/'study'/trial187/'金融正本',base/'金融正本')
    work=target/'work/188数量比較'
    shutil.copy2(HERE/'人工確認188.json',work/'人工確認188.json')
    for script,args in ((work/'実行188.py',['--pure']),(work/'実行188.py',['--finance']),
                        (work/'診断188.py',[]),(base/'数量188を独立検査する.py',[])):
        subprocess.run([sys.executable,'-X','utf8',str(script),*args],cwd=target,check=True)
    checks=[]
    for name in ('全108組安定性.json.gz','全108組短表.json','原因診断188.json.gz','旧18対照同体.json'):
        a=(HERE/name).read_bytes();b=(work/name).read_bytes();assert a==b,name
        checks.append({'path':name,'sha256':hashlib.sha256(a).hexdigest(),'bytes':len(a)})
    for product in ('NK225','TOPIX'):
        assert (ROOT/'inputs/00188_共通価格入口の純数量'/(product+'.json.gz')).read_bytes()==(work/'純数量'/(product+'.json.gz')).read_bytes()
    original=json.loads((HERE/'独立確認.json').read_text(encoding='utf-8'))
    reproduced=json.loads((base/'188全108口座の独立確認.json').read_text(encoding='utf-8'))
    assert original==reproduced
    result={'成功':True,'元work使用':False,'全108正本同体':checks,'純量2商品同体':True,'独立監査同体':True}
    (target/'再現確認.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
