"""正式116の価格参照・CSV所在・今回文書のリンクを確認する。"""

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / 'study/00116_突破根拠の維持から失効への遷移で離脱する'


def load(path: Path) -> dict:
    """機能: 検査対象の保存metadataを読む。

    引数: path(Path)は明示JSON。
    返り値: dict。価格・Native・CSV本文を読まない。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main() -> None:
    """機能: 正式Viewerの市場所在と文書リンクを別処理で確認する。

    引数: なし。
    返り値: None。金融・Raw・CSV再演算はしない。
    """
    proof = load(STUDY / '検査/正式保存の確認.json')
    if proof['成功'] is not True or proof['前後不変'] is not True:
        raise ValueError('正式保存成功')
    catalog_path = STUDY / '成果物/閲覧用_市場絶対参照.resources.json'
    catalog = load(catalog_path)
    rows = catalog['resources']
    if len(rows) != 2520 or len({r['id'] for r in rows}) != 2520:
        raise ValueError('Viewer資源数')
    sessions = set()
    markets = set()
    for row in rows:
        sessions.add(row['session'])
        if row['session'] > '2026-11-06_Night':
            raise ValueError('入力範囲')
        pnl = (catalog_path.parent / row['pnl_path']).resolve()
        if pnl.parent != catalog_path.parent or not pnl.is_file():
            raise ValueError('実tradesは正式内')
        market = (catalog_path.parent / row['market_path']).resolve()
        if market.is_relative_to(ROOT / 'work') or not market.is_file():
            raise ValueError('価格は共有又は恒久入力: ' + str(market))
        markets.add(str(market))
    if len(sessions) != 70 or len(markets) != 70:
        raise ValueError('場と価格参照の一対一')
    csv_refs = load(STUDY / '再現資料/CSV所在と確認.json')['CSV']
    for name, ref in csv_refs.items():
        path = Path(ref['path'])
        if not path.is_relative_to(ROOT / 'outputs') or path.name != name:
            raise ValueError('CSV唯一正本')
        if hashlib.sha256(path.read_bytes()).hexdigest() != ref['sha256']:
            raise ValueError('CSV保存時SHA不変')

    # ----------------------------------------
    documents = [ROOT / 'AGENTS.md', ROOT / 'README.md', ROOT / 'docs/README.md', ROOT / 'study/README.md',
                 ROOT / 'docs/technical-analysis/README.md', ROOT / 'docs/議論/README.md',
                 ROOT / 'docs/議論/外部再調査/README.md', STUDY / 'README.md', STUDY / '設定と結果.md',
                 ROOT / 'docs/議論/枚数と取得位置と短期利益保護を分けて検証する.md',
                 ROOT / 'docs/議論/増玉と短期保護を調べて分かったこと.md',
                 ROOT / 'outputs/01a1889f-f2af-7943-a047-543275ee9ed2/116損益CSV/README.md']
    missing = []
    count = 0
    for path in documents:
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', path.read_text(encoding='utf-8-sig')):
            target = unquote(target.strip('<>')).split('#')[0]
            if not target or re.match(r'^(https?|mailto):', target):
                continue
            count += 1
            if not (path.parent / target).resolve().exists():
                missing.append({'文書': str(path), '参照': target})
    if missing:
        raise ValueError(json.dumps({'リンク欠落': missing}, ensure_ascii=False))
    out = STUDY / '検査/所在と文書の最終確認.json'
    result = {'成功': True, '試行': 116, 'Viewer資源': len(rows), '場': len(sessions), '恒久市場参照': len(markets),
              '実tradesのwork依存': 0, '市場参照のwork依存': 0, '文書数': len(documents), '相対リンク数': count,
              'CSV唯一正本SHA不変': True, '価格CSV_Raw_Nativeの本文読取': 0, 'CSVはSHA照合のみ': 2,
              '金融再実行': False, '採用': False, '研究目標達成': False}
    with out.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
