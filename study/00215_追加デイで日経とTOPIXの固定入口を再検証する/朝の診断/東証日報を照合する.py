"""11月19日の寄り前TOPIX買いの事後診断として、現物4銘柄の前場を確認する。"""
from pathlib import Path
from urllib.request import urlopen
from statistics import mean
import hashlib
import json
import sys
import pymupdf

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(next((ROOT/'study').glob('00214_*'))))
from 現物の午前値動き import 前場価格, 対象銘柄


# ----------------------------------------
def main() -> None:
    """
    機能：前回と同じ東証相場表の午前始値・終値を抽出し、買い方向との一致を記録する。
    引数：なし。東証の11月19日分のPDFを共用作業域に取得する。
    返り値：None。出典URL・指紋・ページ番号・価格を含むJSONを保存する。
    """
    url = 'https://www.jpx.co.jp/automation/markets/statistics-equities/daily/files/202611/stq_20261119.pdf'
    path = ROOT/'work/215朝/2026-11-19.pdf'
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(url, timeout=40) as response:
            data = response.read()
        assert data.startswith(b'%PDF-')
        path.write_bytes(data)
    with pymupdf.open(path) as report:
        assert '2026年11月19日' in report[0].get_text()
    prices = 前場価格(path)
    for code, values in prices.items():
        values['銘柄'] = 対象銘柄[code]
        values['前場騰落率%'] = 100*(values['終値']/values['始値']-1)
    # ----------------------------------------
    result = {'対象日':'2026-11-19','資料確認日':'2026-11-20','東証URL':url,'PDFバイト数':path.stat().st_size,
              'PDFのSHA256':hashlib.sha256(path.read_bytes()).hexdigest(),'PyMuPDF':pymupdf.VersionBind,
              '現物4銘柄':prices, '半導体2社の等ウェート平均%':mean(prices[c]['前場騰落率%'] for c in ('6857','8035'))}
    (HERE/'東証の前場.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


if __name__ == '__main__':
    main()
