# 連続出生を固定した個別利益追尾

固定93の公開Adapterをmini nativeShadowとしてimportし、独立Actor12口座へ通知を配送する。Sourceの全状態・費用0判断へActorの退出/利益を戻さない。5分新規・新Entry gateはこの版へ追加しない。

S0/P0/P1×追加滑り0/5pt×要求後0/1価格秒。S0は元通知退出のみ。P0は費用後単価益u>0で最低名目建値＋取得時固定2ATR、P1は同じ幅へ残玉単価の費用回収床を重ねる。ATRは元公開5分TR平滑12、3本目から最低20pt、終端＋60秒。未知は最低床を先に起動し、最初の既知ATRで幅を一度固定する。

`input.go`は93の入力部だけを同体派生しpackageを変更。`replay.go`はShadowを一度更新してD/P/U batchを束ね、Actorを一原行に一度だけ進める。締切timer、Last0未供給、CSV公開順は93のまま。Actorは全Source取消→fill前MTM→既予約fill→源close→出生受理→fill後MTM/保護を実行する。timerでは市場評価/即時約定を作らない。

`actual.go`は別会計の新規実装。Signal/Hold/注文IDを型で分け、返済予約を二重化しない。SourcecloseはBefore比率を実未予約残へ切上げ、全残通知は全量、未取得newは全取消。半円費用を保持し、両方向それぞれ予約込み10枚。既存返済は取消・延期しない。

`mirror_check.go`はS0_D0の全実Fillを元Sourceの所有別・原行別に比較する。Shadowの全文は93の固定GZIPと完了指紋に照合する。金額だけの相殺一致では通さない。Source側の元FAR完全同値を新たに主張しない。

正本には全注文・取消・Fill・配賦と少数の初回/極値点を保存し、全原板MTMの複製を避ける。u/W、同原行のfill前/後、P/U合算口座DD、予約中の正益観測を分ける。独立検算は保存会計と全正常原行のRaw監査で分担する。

Go1.24.2/CGO=0、Python3.14.3標準ライブラリ。Go依存はgo.mod/go.sumと固定93、純戦略は固定80台帳の43項目。実口座通信・WebSocket送信・注文API呼出しはない。結果先は未作成フォルダだけを許可する。

再生CLIは`--manifest --baseline --baseline-proof --out`が必須、`--limit 2`は固定54場の先頭接続用。全54場未満を最終648資源の成功へ読み替えない。完成後の正式READMEで実行CLIと証拠を参照する。
