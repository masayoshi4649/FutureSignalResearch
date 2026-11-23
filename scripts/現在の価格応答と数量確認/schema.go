// 84派生元: work/84入口試作/schema.go
// 84派生元SHA256: 452b1c684f74a024ff79f7e682316ee982a2380bb302d65474d0377c9fce2119

package far84

import (
	"crypto/sha256"
	"fmt"
	"reflect"
	"strings"

	far82 "github.com/masayoshi4649/SessionTradeExecuter/research82"
)

const acceptedSchemaSHA256 = "4a252a43ee85ba459e526a3dcfcfea41f765bdb084af39af4483369474e53e9a"

// OldSchemaSHA256 は既存82の公開保存型全体の構造指紋を計算します。
//
// 引数: ありません。型情報だけを使い、市場値を読みません。
// 返り値: stringは公開field・順序・タグ・型を再帰的に結んだSHA256です。
func OldSchemaSHA256() string {
	var description strings.Builder
	describeType(reflect.TypeOf(far82.EntryDecision{}), &description, map[reflect.Type]bool{})
	return fmt.Sprintf("%x", sha256.Sum256([]byte(description.String())))
}

// describeType は再帰型を有限に止めながら型構造を一意の文字列へ追記します。
//
// 引数: kind(reflect.Type)、out(*strings.Builder)、seen(map[reflect.Type]bool)は型と出力と訪問集合です。
// 返り値: ありません。公開構造fieldの名前・順序・埋込・全タグも記録します。
func describeType(kind reflect.Type, out *strings.Builder, seen map[reflect.Type]bool) {
	fmt.Fprintf(out, "(%q,%q,%q", kind.PkgPath(), kind.Name(), kind.Kind())
	if seen[kind] {
		out.WriteString(",再参照)")
		return
	}
	seen[kind] = true
	switch kind.Kind() {
	case reflect.Struct:
		for i := 0; i < kind.NumField(); i++ {
			field := kind.Field(i)
			fmt.Fprintf(out, ",%q,%q,%t", field.Name, string(field.Tag), field.Anonymous)
			describeType(field.Type, out, seen)
		}
	case reflect.Map:
		describeType(kind.Key(), out, seen)
		describeType(kind.Elem(), out, seen)
	case reflect.Slice, reflect.Pointer:
		describeType(kind.Elem(), out, seen)
	case reflect.Array:
		fmt.Fprintf(out, ",%d", kind.Len())
		describeType(kind.Elem(), out, seen)
	}
	out.WriteString(")")
}
