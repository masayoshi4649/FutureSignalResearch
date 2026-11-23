# Source三手法の内側入口と親episodeの照合

確認日：2026-11-12。非金融監査を完了した。**初期系456通知と、そのうち138 P0に含まれる420通知には、同じ内側entry/同じengine内episodeの重複は見つからなかった。** 138/139の条件・頻度・結果は変更していない。

|対象|通知数|session+engine+source_idの一意数|session+engine+parentの一意数|cross-method同source_id|
|---|---:|---:|---:|---:|
|全通知|558|558|456|0|
|初期/遅延初期|456|456|456|0|
|138 P0に含むFAR初期系|420|420|420|0|

全558はinitial353・delayed_initial103・source_add102。反復する同engine episodeは102群あり、各群は初期系1件とsource_add1件の2通知だった。Source_addは別の内側entry IDを持つが同じ親episodeの追加であり、138では既に全102を独立初期頻度から除外している。初期系だけにすると、同原行以外の再通知を含めた同source_id/同episodeの反復は0だった。

## 名前だけの親一致と、実際の内側IDを分ける

凍結111のコードと、115の参照索引に残る同SHAの接続では、各Adapterが別Portfolioを構築し、次のShadowを作る。

|外側wrapper|内側Shadow Method|比較のscope|
|---|---|---|
|D164_15|S01|同じDay/session内のS01源|
|P164_06|P05|同じNight/session内のP05源|
|U165_03|D07|同じNight/session内のD07源|

`stepSelectedSource`はShadowの元Signal.IDをSourceIDへ渡し、Parentを元Owner/Campaignから作る。従って内側entryの比較にはsession/engine/source_id、episodeにはsession/engine/parentを使う。

**保存列internal_idは、名前に反してShadowの玉IDではなかった。** `fillSelected`がSelectedLot.IDへ外側fill.ExecutionIDを入れ、Source111のAdapterがそれをHoldLedger.InternalIDとして写している。558件全てでinternal_id=外側ExecutionID=wrapper通知ID+「-参照約定」を確認した。これだけがcross-methodで違っても内側の独立性の根拠にはならないため、実際のShadow元通知IDであるsource_idを別に照合した。

`parent`の文字列だけをsession内で比較すると、cross-method一致が26群あった。全558では80通知、初期456とP0由来420では各52通知を含む。しかし実engineが異なり、source_idも異なる。たとえば同じ`episode/0`でも、P164の`…-P05-000001`とU165の`…-episode-000002`は別源である。親の表面一致だけで統合すると、異なる源を誤って一つにする。

session内の生source_id、internal_idのcross-method一致は全対象で0。外側出生原行とSourcefill原行のcross-method一致も0だった。wrapper名を外した疑似IDや、近い時計だけから同一入口を作っていない。

## 入力と再現

許可された118入力77,606,890BのSHA `574771f654937036b48c78eceadb46a4c5ff3c10265f60b0ec7879efb0d862c3`を検査した。選択JSON読取器は指定したID/親/出生/Sourcefill時計の経路だけを値化し、価格・PnL・数量・公表本文・Evidenceは字句/括弧構造だけで読み飛ばす。価格/損益をPython値として取り出して比較・表示・保存していない。Raw・Native・価格CSV・追加2場は開いていない。

既存のSource558種別台帳と全件ID結合し、Sourcefill/holdのStampも一致した。固定138 manifestは各originのfamily/session/idだけを選択読取し、420件へ結合した。manifestの価格・結果は使っていない。

`識別子だけを抽出する.py`は許可入力から小型台帳を作る。次に`同一性を監査する.py`が旧種別台帳・138 manifest・凍結コードを照合する。どちらも既存出力を上書きしないため、再実行は同じ依存を元相対位置に置いた別作業先で行う。未知項目の価格値を変更しても選択出力が同体、文字列内括弧/escape/null、選択key重複拒否、別engine同parentと真の再通知/追加の区別を人工確認した。

[内側IDの監査.json](内側IDの監査.json.gz)に全重複群・コード参照・入力SHAを残す。[完了.json](完了.json)が最終停止票。558件の許可識別台帳は`558通知の識別と時計.json`に保存し、77MB入力自体は複写しない。

## 限界と次の扱い

これは通知/entry/episodeの識別同一性の監査で、異なるエンジンが経済的に同じ機会を捉えたか、相関が高いか、統計的に独立かを証明しない。保存した出生とSourcefillは外側通知の時計であり、delayed_initialより前のShadow生通知の時刻や保有終了を復元したものではない。価格を使わない今回の範囲では、似たsetupや重複保有の実口座効果は未判定である。

今回確認できた420件を減らす識別上の根拠は見つからなかったが、既存138/139を改善した結果とはしない。今後同じSource/episodeの再通知が見つかった場合の単位変更は140以降へ分ける。

保存注記：結果/条件は原文のまま、JSONリンクだけgzip先へ調整した。原文MDと監査コードは追補ZIPへ保存した。
