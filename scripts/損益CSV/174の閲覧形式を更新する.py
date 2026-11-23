"""174の混在CSVを候補別表示へ移し、元byteは書式履歴ZIPに残す。"""
from pathlib import Path
from datetime import datetime, timezone
import csv
import hashlib
import json
import shutil
import zipfile

ROOT=Path(__file__).resolve().parents[2]
OUTPUT=ROOT/'outputs/00174_追加禁止と両中央値の比較'
TRIAL=ROOT/'study/00174_共同条件を残して単一建玉の入口を広げる'
NAMES={'候補比較':'集計','デイ':'デイ','ナイト_米前':'ナイト_米前','ナイト_米後':'ナイト_米後'}
ROLES={'174:全期_J002':'174 全期主案','174:全期_J003':'174 全期近傍',
       '174:前48_J000':'174 前48主案','174:前48_J001':'174 前48近傍',
       '173:全期_J016':'173 全期固定対照1','173:全期_J017':'173 全期固定対照2',
       '173:前48_J026':'173 前48固定対照1','173:前48_J027':'173 前48固定対照2'}


def physical(path: Path) -> dict:
    """
    機能: 保存物の位置・サイズ・SHA256を返す。
    引数: path(Path)はリポジトリ内の実ファイル。
    返り値: dictはpath/bytes/sha256。
    """
    return {'path':path.relative_to(ROOT).as_posix(),'bytes':path.stat().st_size,
        'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def read_csv(path: Path) -> list:
    """
    機能: UTF-8 BOM付きCSVを文字列の行列として読む。
    引数: path(Path)。
    返り値: list[list[str]]は空欄を保持した全セル。
    """
    with path.open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.reader(stream))


def main() -> None:
    """
    機能: 32分割CSVの全セルを旧4CSVと照合してから、旧表示をZIP履歴へ移す。
    引数: なし。固定の174閲覧表示だけを変更する。
    返り値: None。売買条件・金融正本・既存研究ZIPは変更しない。
    """
    proof_path=ROOT/'work/174候補別CSV/著作確認/作成確認.json'
    proof=json.loads(proof_path.read_text(encoding='utf-8'))
    assert proof['成功'] and proof['候補数']==8 and len(proof['files'])==32
    previous={name:read_csv(OUTPUT/(name+'.csv')) for name in NAMES}
    old_files=[OUTPUT/(name+'.csv') for name in NAMES]
    old_bytes={p:p.read_bytes() for p in old_files}
    cells=0;new_files=[]
    for item in proof['files']:
        target=(OUTPUT/item['相対path']).resolve()
        assert target.is_relative_to(OUTPUT.resolve())
        assert physical(target)['sha256']==item['sha256']
        rows=read_csv(target)
        source=previous[item['元表']]
        expected=[source[0],*[row for row in source[1:] if row[0]==item['候補']]]
        assert rows==expected and {row[0] for row in rows[1:]}=={item['候補']}
        assert len(rows)==(5 if item['元表']=='候補比較' else 41)
        cells+=len(rows)*len(rows[0]);new_files.append(physical(target))
    assert cells==20720
    # ----------------------------------------
    archive_path=TRIAL/'再現資料/旧混在CSV.zip'
    assert not archive_path.exists()
    with zipfile.ZipFile(archive_path,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for old_path,body in old_bytes.items():
            archive.writestr(old_path.relative_to(ROOT).as_posix(),body)
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        for old_path,body in old_bytes.items():
            assert archive.read(old_path.relative_to(ROOT).as_posix())==body
    old_refs=[physical(p) for p in old_files]
    manifest={'成功':True,'確認日':'2026-11-16','UTC':datetime.now(timezone.utc).isoformat(),
        '変更':'ユーザー指示により一候補一フォルダ、一CSV一候補へ分割。数値・空欄・元の候補内行順は不変。',
        '候補数':8,'CSV数':32,'全セル照合':cells,'作成票':physical(proof_path),
        '分割元の履歴ZIP':physical(archive_path),'分割前のCSV':old_refs,'現在のCSV':new_files,
        'Source':[physical(Path(__file__).resolve()),physical(ROOT/'scripts/損益CSV/候補別に出力する.mjs')],
        '旧検査と保存索引':'旧4CSVのpath/SHAは当時の記録として保持。元byteは本履歴ZIPの同名memberへ移した。新表示はこの索引を参照。'}
    manifest_path=TRIAL/'再現資料/候補別CSV索引.json'
    assert not manifest_path.exists()
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    # ----------------------------------------
    # ZIPの同体確認後、検査済みの旧CSV四本だけを非再帰で除く。
    for old_path,body in old_bytes.items():
        assert old_path.resolve().parent==OUTPUT.resolve() and old_path.read_bytes()==body
        old_path.unlink()
    shutil.copyfile(proof_path,TRIAL/'検査/候補別CSV作成確認.json')
    # ----------------------------------------
    intro='''# 候補別の損益CSV

2026-11-16。**別候補を同じCSVに混在させない形式へ変更した。まず174全期主案のフォルダを開く。** 各候補に集計4行、デイ40行、ナイト米前40行、ナイト米後40行の4CSVを置く。

|候補|フォルダと条件|集計|デイ|ナイト米前|ナイト米後|
|---|---|---|---|---|---|
'''
    for candidate,role in ROLES.items():
        folder=candidate.replace(':','_')
        intro+=f'|{role}|[{candidate}]({folder}/README.md)|[集計]({folder}/集計.csv)|[デイ]({folder}/デイ.csv)|[米前]({folder}/ナイト_米前.csv)|[米後]({folder}/ナイト_米後.csv)|\n'
        study='00174_共同条件を残して単一建玉の入口を広げる' if candidate.startswith('174:') else '00173_追加建てを禁止し両中央値で入口を再探索する'
        readme=f'''# {role}：{candidate}

このフォルダのCSVは全て `{candidate}` だけを収録する。要求mini1枚、保有と未決予約を買売合計一件までとした固定条件。売買条件と損益は分割前から変更していない。

- [集計](集計.csv)：同一候補のDAY/NIGHT/PRE/POST、4行。
- [デイ](デイ.csv)：全40Day。
- [ナイト米前](ナイト_米前.csv)：全40NightのPRE。
- [ナイト米後](ナイト_米後.csv)：全40NightのPOST。

[費用・未知・集計の読み方](../README.md)。[条件と研究結果](../../../study/{study}/README.md)。[他候補の一覧](../README.md)。
'''
        (OUTPUT/folder/'README.md').write_text(readme,encoding='utf-8')
    intro+='''
各ファイルは候補IDが一種類だけ。173の固定対照と174の主案・近傍・前48選択を別々に保持し、同じ損益になった近傍も合算しない。全8候補でDay/Nightの取引0セッションなし。PRE/POSTはNight内の小帯で、各小帯の取得は強制しない。

金額はmini1枚/要求、税込片道38.5円＋追加片道5pt滑り、実BBO spreadを反映。利益・損失は既知分、損失は正の絶対額。金融未知がある当日の全件収支と、それ以後の全件累計は空欄。既知分収支・累計・金融未知件数を別欄に残す。

先着率はF/(F+A)。Nの期限決済も金融と中央値に含め、Cと金融未知を0円返済に置換しない。両中央値の必須判定はDAY/NIGHTで、0取引場も0円で全場中央値に含む。NIGHTはPRE＋POSTの合計なので重複加算しない。新規q0の帯に取引全体を帰属し、決済帯には分け直さない。

[研究結果](../../study/00174_共同条件を残して単一建玉の入口を広げる/README.md)、[分割索引](../../study/00174_共同条件を残して単一建玉の入口を広げる/再現資料/候補別CSV索引.json)。全80は既使用。追加期間の悪化・未知・低頻度は引き続き残る。分割前の4混在CSVは書式履歴ZIPへ元byteで保存し、現行の閲覧対象から外した。xlsxは作成しない。
'''
    (OUTPUT/'README.md').write_text(intro,encoding='utf-8')
    formal=intro.replace('](','](../../outputs/00174_追加禁止と両中央値の比較/')
    formal=formal.replace('../../outputs/00174_追加禁止と両中央値の比較/../../study/00174_共同条件を残して単一建玉の入口を広げる/','')
    (TRIAL/'閲覧資料.md').write_text(formal,encoding='utf-8')
    print(json.dumps({'成功':True,'候補数':8,'CSV数':32,'全セル照合':cells,'混在CSVの履歴':physical(archive_path)},ensure_ascii=False))


if __name__=='__main__':
    main()
