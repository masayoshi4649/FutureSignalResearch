"""95の入力・旧固定基準・新実装を市場実行の前後で照合する。"""

import argparse
import hashlib
import json
from pathlib import Path


ROOT=Path(__file__).resolve().parents[2]
MANIFEST=ROOT/"study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json"
MANIFEST_SHA="b939bc91b33fd86e933534c3b991d844b8a0200a5f14710e1bd5004edc1aab42"
BASE93=ROOT/"study/00093_元三手法のmini連続再現と費用"
BASE94=ROOT/"study/00094_連続出生を固定した個別利益追尾"
PROOF93="e811571a876f3fdc2f5ba7c09b3906c84db9e380ef89c24b920e5c3f199a2a37"
PROOF94="ccbc365b647c8225f5ef238f707778e9fbff01c5decba721c2843cb3f1972f80"


def digest(path: Path) -> str:
    """
    機能: ファイルを分割読取して内容指紋を取得する。
    引数: path(Path)は明示された入力/コード。
    返り値: strはSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def load(path: Path) -> dict:
    """
    機能: 正式保存JSONを読み込む。
    引数: path(Path)は保存先。
    返り値: dictは保存本文。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def fixed_files(base: Path, expected: dict) -> dict:
    """
    機能: 正式自己除外台帳の全ファイルを指紋照合する。
    引数: base(Path)、expected(dict[str,str])は正式dirと期待指紋。
    返り値: dictは実一致指紋。不一致は例外。
    """
    result={name:digest(base/Path(name)) for name in expected}
    assert result==expected
    return result


def collect() -> dict:
    """
    機能: 同54場の324入力と旧93/94/純戦略・95コードを検査する。
    引数: なし。
    返り値: dictは群別の実一致指紋。
    """
    assert digest(MANIFEST)==MANIFEST_SHA
    assert digest(BASE93/"完了記録.json")==PROOF93 and digest(BASE94/"完了記録.json")==PROOF94
    manifest=load(MANIFEST)
    selected=[s for s in manifest["sessions"] if "2026-09-21"<=s["id"][:10]<= "2026-10-27"]
    assert len(selected)==54 and len({s["id"] for s in selected})==54
    raw={}
    for session in selected:
        assert len(session["files"])==6
        for item in session["files"].values():
            path=Path(manifest["source_root"])/item["path"]
            actual=digest(path)
            assert actual==item["sha256"] and path.stat().st_size==item["size"],path
            raw[str(path)]=actual
    pure={name:digest(Path(manifest["純戦略repo"])/name) for name in manifest["純戦略SHA256"]}
    assert pure==manifest["純戦略SHA256"] and len(pure)==43
    old93=dict(load(BASE93/"条件.json")["コードSHA256"])
    amend93=load(BASE93/"集計形式訂正.json")
    old93[amend93["変更ファイル"]]=amend93["新SHA256"]
    code93={name:digest(ROOT/name) for name in old93}
    assert code93==old93 and len(code93)==11
    old94=load(BASE94/"完了記録.json")["現行金融接続コード指紋"]
    code94={name:digest(ROOT/name) for name in old94}
    assert code94==old94 and len(code94)==13
    files93=fixed_files(BASE93,load(BASE93/"完了記録.json")["自己を除く正式指紋"])
    files94=fixed_files(BASE94,load(BASE94/"完了記録.json")["自己を除く正式指紋"])
    assert len(files93)==313 and len(files94)==726
    here=Path(__file__).resolve().parent
    code={p.relative_to(ROOT).as_posix():digest(p) for p in sorted(here.rglob("*")) if p.is_file() and (p.suffix in (".go",".py") or p.name in ("go.mod","go.sum","README.md"))}
    assert len(raw)==324
    return {"試行":95,"場数":54,"台帳SHA256":MANIFEST_SHA,"固定93完了SHA256":PROOF93,"固定94完了SHA256":PROOF94,
            "原入力":raw,"純戦略":pure,"固定93コード":code93,"固定94コード":code94,"固定93正本":files93,"固定94正本":files94,"コード":code}


def main() -> None:
    """
    機能: 市場前/後の固定入力照合を新規証拠へ保存する。
    引数: --out(Path)は新規先、--before(Path、省略可)は前の証拠。
    返り値: None。不一致/上書きは失敗。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--before",type=Path)
    args=parser.parse_args()
    value=collect()
    if args.before:
        assert value==load(args.before),"固定入力/旧基準/実装が前後で変化"
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    print(json.dumps({"成功":True,"場数":54,"原入力":324,"純戦略":43,"旧93正本":313,"旧94正本":726,"95コード数":len(value["コード"]),"前後検査":bool(args.before)},ensure_ascii=False))


if __name__=="__main__":
    main()
