module github.com/masayoshi4649/SessionTradeExecuter/research84

go 1.24.0

require (
	github.com/BurntSushi/toml v1.5.0
	github.com/expr-lang/expr v1.17.8
	github.com/masayoshi4649/SessionTradeExecuter v0.0.0
	github.com/masayoshi4649/SessionTradeExecuter/research80 v0.0.0
	github.com/masayoshi4649/SessionTradeExecuter/research81 v0.0.0
	github.com/masayoshi4649/SessionTradeExecuter/research82 v0.0.0
	github.com/masayoshi4649/SessionTradeExecuter/research83 v0.0.0
)

replace github.com/masayoshi4649/SessionTradeExecuter => ../../../SessionTradeExecuter

replace github.com/masayoshi4649/SessionTradeExecuter/research80 => ../FAR後期15分移植

replace github.com/masayoshi4649/SessionTradeExecuter/research81 => ../定時の現在根拠と部分利益保護

replace github.com/masayoshi4649/SessionTradeExecuter/research82 => ../チャートの現在性と補助確認

replace github.com/masayoshi4649/SessionTradeExecuter/research83 => ../構造否定と利益配分
