"""Viewerの実HTTP照合後、現在の案内と研究の境界を仕上げる。"""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / 'study/00116_突破根拠の維持から失効への遷移で離脱する'


def reference(path: Path) -> dict:
    """機能: 明示成果物とコードのSHAを記録する。

    引数: path(Path)は小metadata/文書/コード。
    返り値: dictは絶対pathとSHA。原板・Nativeは渡さない。
    """
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def main() -> None:
    """機能: 凍結済み版2の結果案内へ、実際に開けた一覧を追補する。

    引数: なし。
    返り値: None。金融・停止・CSV・初回保存を変更しない。
    """
    viewer = json.loads((STUDY / '検査/Viewer確認.json').read_text(encoding='utf-8'))
    if viewer['成功'] is not True or (viewer['一覧'], viewer['実GET']) != (2520, 72):
        raise ValueError('Viewerの実HTTP完了')
    document_code = ROOT / 'work/116進行/結果文書を更新する_版2.py'
    request = json.loads((STUDY / '検査/正式保存の要求.json').read_text(encoding='utf-8'))
    expected = [r['ref']['sha256'] for r in request['code_refs'] if Path(r['ref']['path']) == document_code]
    if expected != [reference(document_code)['sha256']]:
        raise ValueError('凍結済み文書コード')
    subprocess.run([sys.executable, '-X', 'utf8', str(document_code)], check=True)
    readme = STUDY / 'README.md'
    text = readme.read_text(encoding='utf-8').replace('[閲覧一覧](成果物/一覧.resources.json)', '[閲覧一覧](成果物/閲覧用_市場絶対参照.resources.json)')
    text += '\nViewerでは価格の相対基準が常にdata_rootであるため、[市場参照の補正](検査/Viewer市場参照の補正.json)で同じ70市場への絶対参照一覧を追補した。初回保存の一覧と確認は履歴として不変。閲覧には上の補正版を使う。[専用Viewerを開く](http://127.0.0.1:8100/?catalog=成果物/閲覧用_市場絶対参照.resources.json)。\n'
    readme.write_text(text, encoding='utf-8', newline='\n')

    # ----------------------------------------
    knowledge = ROOT / 'docs/議論/増玉と短期保護を調べて分かったこと.md'
    text = knowledge.read_text(encoding='utf-8')
    old = '**116の正式結果への恒久リンクはRootによる後段追記待ちであり、ここでは116の数値を追加転記しない。**'
    new = '[116の全70結果](../../study/00116_突破根拠の維持から失効への遷移で離脱する/README.md)と[同入口2例の当時値](../../study/00116_突破根拠の維持から失効への遷移で離脱する/診断/2例の実退出と当時の根拠.md)へ接続した。追加退出は全体を改善せず、この2例を一般的な判別規則の実証とは扱わない。'
    if old not in text:
        raise ValueError('共通知見の追記位置')
    knowledge.write_text(text.replace(old, new), encoding='utf-8', newline='\n')
    csv_readme = ROOT / 'outputs/01a1889f-f2af-7943-a047-543275ee9ed2/116損益CSV/README.md'
    with csv_readme.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write('\nViewerの実接続は試行READMEの補正版一覧を使う。初回保存の市場相対参照は当時記録として残し、同一70入力への明示絶対参照へ追補した。損益CSVと金融結果は不変。\n')

    # ----------------------------------------
    check_source = ROOT / 'work/116進行/保存後を確認する.py'
    code = check_source.read_text(encoding='utf-8')
    if code.count("catalog_path = STUDY / '成果物/一覧.resources.json'") != 1:
        raise ValueError('所在検査の固定一覧1箇所')
    check_path = ROOT / 'work/116進行/保存後を確認する_閲覧用補正版.py'
    with check_path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(code.replace("catalog_path = STUDY / '成果物/一覧.resources.json'", "catalog_path = STUDY / '成果物/閲覧用_市場絶対参照.resources.json'"))
    subprocess.run([sys.executable, '-X', 'utf8', str(check_path)], check=True)
    own = Path(__file__).resolve()
    copies = [(own, STUDY / '再現資料/閲覧接続後の文書を仕上げる.py'),
              (check_path, STUDY / '再現資料/保存後の所在確認_閲覧用補正版.py')]
    for source, target in copies:
        with source.open('rb') as src, target.open('xb') as dst:
            shutil.copyfileobj(src, dst)
        if reference(source)['sha256'] != reference(target)['sha256']:
            raise ValueError('後段コードの同bytes保管')
    state_path = ROOT / 'work/116進行/現在.json'
    state = json.loads(state_path.read_text(encoding='utf-8'))
    state.update({'段階': '116全70の金融・独立・Raw・CSV・正式保存・Viewer HTTP・文書を完了。117は短期複合保護の未固定案まで。',
                  '正式保存': True, 'Viewer確認': True, '実行中': [],
                  '当ゴールターン分類': '進捗。116の全70会計/Raw最初性/CSV/可逆保管/正式保存/Viewerを完了。S0対P100の利益損失、初期枚数対増玉、W>0床と短期複合案を整理。追加退出は改善せず、研究目標未達。',
                  '11月09読取': False, '採用': False, '研究目標達成': False})
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    refs = {name: reference(STUDY / path) for name, path in {
        '正式保存': '検査/正式保存の確認.json', '独立保存': '成果物/保存会計の確認.json',
        '全70原行': '検査/raw_check.json', 'CSV再読': '検査/csv_check.json', 'ViewerHTTP': '検査/Viewer確認.json',
        'Viewer市場補正': '検査/Viewer市場参照の補正.json', '所在と文書': '検査/所在と文書の最終確認.json'}.items()}
    out = STUDY / '検査/116の完了.json'
    value = {'試行': 116, '成功': True, 'refs': refs, '文書後段コード': [reference(target) for _, target in copies],
             '金融条件変更': False, 'CSV再生成': False, '11月09読取': False,
             '次の研究': 'W>0取得価格床・取得後1分構造/MACD/反対TRの複合保護。未固定・未実装・金融未実行。',
             '採用': False, '研究目標達成': False}
    with out.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'成功': True, '完了': reference(out)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
