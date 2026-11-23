package lighttape97

import (
	"compress/gzip"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"

	actual "github.com/masayoshi4649/SessionTradeExecuter/minichart"
)

// LoadCache は明示された完成Tape指紋だけを読みます。
//
// 引数: path/expected(string)は保存Tapeと構築時SHA256です。
// 返り値: Tape/errorは再ロード又は破損。Raw/CSV/Features/Sourceへアクセスしません。
func LoadCache(path, expected string) (Tape, error) {
	var out Tape
	sha, err := Digest(path)
	if err != nil {
		return out, err
	}
	if sha != expected {
		return out, fmt.Errorf("保存TapeのSHA差")
	}
	f, err := os.Open(path)
	if err != nil {
		return out, err
	}
	defer f.Close()
	g, err := gzip.NewReader(f)
	if err != nil {
		return out, err
	}
	defer g.Close()
	err = json.NewDecoder(g).Decode(&out)
	return out, err
}

// VerifyCache は保存Tapeの逐次再ロードと二並列再生を元96へ結びます。
//
// 引数: path/expected/baseline(string)は完成Tape/SHA/元96JSONだけです。
// 返り値: map[string]any/errorは全8Book除外0の証拠。IOはこの2ファイルだけです。
func VerifyCache(path, expected, baseline string) (map[string]any, error) {
	tape, err := LoadCache(path, expected)
	if err != nil {
		return nil, err
	}
	abs, err := filepath.Abs(baseline)
	if err != nil {
		return nil, err
	}
	nativeSHA, err := Digest(abs)
	if err != nil {
		return nil, err
	}
	if tape.Provenance[abs] != nativeSHA {
		return nil, fmt.Errorf("Tape出典と元96SHAの不一致")
	}
	body, err := os.ReadFile(abs)
	if err != nil {
		return nil, err
	}
	var base actual.ReplayResult
	if err = json.Unmarshal(body, &base); err != nil {
		return nil, err
	}
	sequential, err := Replay(tape)
	if err != nil {
		return nil, err
	}
	if err = CompareEight(sequential, base); err != nil {
		return nil, err
	}
	target, _ := json.Marshal(sequential)
	type result struct {
		data []byte
		err  error
	}
	channel := make(chan result, 2)
	for i := 0; i < 2; i++ {
		go func() {
			b, e := Replay(tape)
			if e == nil {
				e = CompareEight(b, base)
			}
			data, _ := json.Marshal(b)
			channel <- result{data, e}
		}()
	}
	for i := 0; i < 2; i++ {
		r := <-channel
		if r.err != nil {
			return nil, r.err
		}
		if string(r.data) != string(target) {
			return nil, fmt.Errorf("同Tape逐次/二並列JSONが相違")
		}
	}
	after, err := Digest(path)
	if err != nil {
		return nil, err
	}
	current, err := Digest(abs)
	if err != nil {
		return nil, err
	}
	if after != expected || current != nativeSHA {
		return nil, fmt.Errorf("再ロード入力の前後変化")
	}
	return map[string]any{"成功": true, "session": tape.Session.ID, "旧96全文一致Book": 8, "逐次/二並列JSON全文一致": true, "IO対象": []string{path, abs}, "Raw/CSV直接読取": 0, "Features/Source/助走再運転": 0, "H/新条件損益計算": 0, "入力前後不変": true, "tape_SHA256": expected, "native_SHA256": nativeSHA}, nil
}
