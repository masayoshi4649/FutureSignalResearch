"""固定96の正式54場と元台帳を結び、停止済みの構築本文を一場ずつ呼ぶ。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SOURCE_PATH=Path(__file__).with_name("許可済み保存入力を作る.py")
SOURCE_SHA="766d6ee06ae8059526946b7724d1577b9845d3f03b42ec37cb4b785b40eab176"
if hashlib.sha256(SOURCE_PATH.read_bytes()).hexdigest()!=SOURCE_SHA:
    raise ValueError("停止済み54gzip外周と旧計算本文のSHA差")
SPEC=importlib.util.spec_from_file_location("停止済みの正式gzip構築本文",SOURCE_PATH)
SOURCE=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SOURCE)


def metadata_catalog() -> dict[str,dict]:
    """
    機能: 固定96の54gzip許可集合と固定80台帳の対応54場を束縛する。
    引数: なし。完了記録と台帳のメタデータだけを読む。
    返り値: dict[str,dict]は場IDごとの正式Nativeと原入力宣言。原板/CSV/Native本文は開かない。
    """
    allowed=SOURCE.selected_catalog(SOURCE.COMPLETION)
    SOURCE.need(SOURCE.sha(SOURCE.MANIFEST)==SOURCE.MANIFEST_SHA,"固定80台帳SHA差")
    manifest=SOURCE.load(SOURCE.MANIFEST)
    entries={}
    for entry in manifest["sessions"]:
        SOURCE.need(entry["id"] not in entries,"元台帳の場ID重複")
        entries[entry["id"]]=entry
    SOURCE.need(len(allowed)==54 and set(allowed)<=set(entries),"固定54場と元台帳の対応不足")
    result={}
    for session,sha in allowed.items():
        entry=entries[session]
        for tag in ("NK225_book","NK225_candle_300"):
            value=entry["files"][tag]
            SOURCE.need(isinstance(value["path"],str) and bool(value["path"]) and len(value["sha256"])==64 and value["size"]>0,"原入力宣言の不足:"+tag)
        result[session]={"session":session,"native_path":str((SOURCE.COMPLETION.parent/"成果物"/(session+".json.gz")).resolve()),"native_sha256":sha,"manifest_entry":entry,"source_root":manifest["source_root"]}
    return result


def select_metadata(session: str,native_dir: Path) -> dict:
    """
    機能: 一場の所属と正式gzip配置を選び、対象外や別配置を拒否する。
    引数: session(str)、native_dir(Path)は明示した場と正式96成果物dir。
    返り値: dictは選択されたメタデータ。Nativeの現在SHAは実buildで検査する。
    """
    catalog=metadata_catalog()
    SOURCE.need(session in catalog,"固定96の54場許可集合に無い場")
    SOURCE.need(native_dir.resolve()==(SOURCE.COMPLETION.parent/"成果物").resolve(),"固定96の正式gzip配置以外は不可")
    return catalog[session]


def build(session: str,native_dir: Path,out: Path) -> dict:
    """
    機能: 選択済み一場を停止済みの価格/ATR/clock/cancel本文へそのまま渡す。
    引数: session(str)、native_dir/out(Path)は場ID/正式Native dir/新規構築入力。
    返り値: dictは旧構築証拠にwrapper指紋を加えた値。Rawを読むのはこの実行時だけ。
    """
    selected=select_metadata(session,native_dir)
    dependencies=(Path(__file__).resolve(),SOURCE_PATH,SOURCE.OLD_PATH,SOURCE.FIXED,SOURCE.COMPLETION,SOURCE.MANIFEST)
    before={str(path):SOURCE.sha(path) for path in dependencies}
    result=SOURCE.build(session,native_dir,out)
    SOURCE.need(all(SOURCE.sha(Path(path))==sha for path,sha in before.items()),"構築wrapperの依存指紋が前後で変化")
    result["wrapper依存SHA256"]=before
    result["正式54集合からの選択"]={"session":selected["session"],"native_path":selected["native_path"],"native_sha256":selected["native_sha256"]}
    result["価格/ATR/clock/cancel計算本文"]="SHA固定した許可済み保存入力を作る.pyのbuildを直接再用。本文複製/変更0。"
    return result


def main() -> None:
    """
    機能: --runで明示した一場だけの構築入力と証拠を新規保存する。
    引数: CLI --session/--native/--out/--proofは対象場/正式Native dir/新規保存先。
    返り値: None。Source判断/Features/助走や新金融を再運転しない。
    """
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",action="store_true",required=True)
    parser.add_argument("--session",required=True)
    parser.add_argument("--native",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--proof",type=Path,required=True)
    args=parser.parse_args()
    SOURCE.need(not args.out.exists() and not args.proof.exists(),"構築入力と証拠は新規保存先だけ")
    result=build(args.session,args.native,args.out)
    args.proof.parent.mkdir(parents=True,exist_ok=True)
    args.proof.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({key:result[key] for key in ("成功","session","Scalar行","grid","Force","取消Origin")},ensure_ascii=False))


if __name__=="__main__":main()
