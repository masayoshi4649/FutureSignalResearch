# 105で生成したNK225原板gzipの恒久保管

2026-11-10、Root明示許可で一度だけ保存した。11/05 Night・11/06 Day/Nightの3gzip、合計20,791,765bytes。旧105は共有JSONLをgzip化し解凍SHA同体を確認したが、その生成gzipだけがworkに残っていた。ここでは既固定gzipを解凍せず同bytesコピーし、元前後と新先のSHA/sizeを確認した。

由来・106共有manifestの902c固定Ref・元JSONLの既記録SHA・元work path・恒久pathは[保存確認](保存の確認.json)に保持する。元work、金融F1、共有入力台帳、旧正式保存は変更していない。Viewerだけが新所在へ結ぶ。金融再現は固定条件の元絶対work pathが必要なため、この恒久コピーから未作成の元pathへ同bytes復元しSHA/sizeを照合する。ここを他試行へ重複コピーしない。
