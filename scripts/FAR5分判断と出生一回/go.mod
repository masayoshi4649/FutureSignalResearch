module github.com/masayoshi4649/SessionTradeExecuter/minigrid

go 1.24.0

require (
 github.com/masayoshi4649/SessionTradeExecuter/mininative v0.0.0
 github.com/masayoshi4649/SessionTradeExecuter/miniprotect v0.0.0
 github.com/masayoshi4649/SessionTradeExecuter v0.0.0
 github.com/BurntSushi/toml v1.5.0
 github.com/expr-lang/expr v1.17.8
)

replace github.com/masayoshi4649/SessionTradeExecuter/mininative => ../FAR元三手法のmini連続再現
replace github.com/masayoshi4649/SessionTradeExecuter => ../../../SessionTradeExecuter

replace github.com/masayoshi4649/SessionTradeExecuter/miniprotect => ../FAR連続出生と個別利益追尾
