module github.com/masayoshi4649/SessionTradeExecuter/minibcheck99

go 1.24.0

require (
 github.com/masayoshi4649/SessionTradeExecuter/mininative v0.0.0
 github.com/masayoshi4649/SessionTradeExecuter/miniprotect v0.0.0
 github.com/masayoshi4649/SessionTradeExecuter v0.0.0
 github.com/BurntSushi/toml v1.5.0
 github.com/expr-lang/expr v1.17.8
)

replace github.com/masayoshi4649/SessionTradeExecuter/mininative => ../../scripts/FAR元三手法のmini連続再現
replace github.com/masayoshi4649/SessionTradeExecuter => ../../../SessionTradeExecuter

replace github.com/masayoshi4649/SessionTradeExecuter/miniprotect => ../../scripts/FAR連続出生と個別利益追尾

require (
 github.com/masayoshi4649/SessionTradeExecuter/minigrid v0.0.0
 github.com/masayoshi4649/SessionTradeExecuter/chartwarmup96 v0.0.0
 github.com/masayoshi4649/SessionTradeExecuter/research80 v0.0.0
 github.com/masayoshi4649/SessionTradeExecuter/research81 v0.0.0
 github.com/masayoshi4649/SessionTradeExecuter/research82 v0.0.0
)
replace github.com/masayoshi4649/SessionTradeExecuter/minigrid => ../../scripts/FAR5分判断と出生一回
replace github.com/masayoshi4649/SessionTradeExecuter/chartwarmup96 => ../../scripts/複数尺度チャートの助走
replace github.com/masayoshi4649/SessionTradeExecuter/research80 => ../../scripts/FAR後期15分移植
replace github.com/masayoshi4649/SessionTradeExecuter/research81 => ../../scripts/定時の現在根拠と部分利益保護
replace github.com/masayoshi4649/SessionTradeExecuter/research82 => ../../scripts/チャートの現在性と補助確認

require github.com/masayoshi4649/SessionTradeExecuter/minichart v0.0.0
replace github.com/masayoshi4649/SessionTradeExecuter/minichart => ../../scripts/FAR5分枠の順行反転と数量
