# Crema ☕

**Crema** は逆ポーランド記法 (RPN) を採用した、スタック指向の汎用プログラミング言語です。
Python 3.9 以上だけで動き、外部ライブラリは必要ありません。

```crema
# 階乗を再帰で計算する
: fact ( n -- n! )
  dup 1 <= [ drop 1 ] [ dup 1 - fact * ] if ;

1 10 [ -> n  "{}! = {}" { n n fact } format print ] for
```

## 特徴

| 要件 | Crema での実現 |
| --- | --- |
| スタックベースの実行モデル | すべての値はデータスタックを介して受け渡します。`1 2 +` → `3` |
| ユーザー定義関数 | `: 名前 本体 ;` で定義します。定義は巻き上げられるので、定義順を問わず相互再帰もできます |
| 再帰 | 制御スタックを VM 内に明示的に持つため、Python の再帰制限を受けず、10 万段を超える深い再帰も動きます。末尾呼び出しは最適化されます |
| 条件分岐 | `cond [ then ] [ else ] if`、`when`、`unless` |
| ループ | `while`、`times`、`for`、`loop`、`each`、`map`、`filter`、`fold`、`break`、`return` |
| 文字列 | `+` による連結、`split`、`join`、`format`、`replace`、`slice` などがあります |
| 数値 | 任意精度の整数と浮動小数点数を扱えます。`/` は割り切れれば整数、そうでなければ小数を返します |
| ファイルの読み書き | `read-file`、`write-file`、`append-file`、`read-lines`、`file-exists?`、`delete-file`、`list-dir` |
| CLI | `crema FILE [ARGS...]`、`crema -e CODE`、標準入力からの実行、REPL |

ほかにも、ローカル変数 (`-> x`)、クロージャ、リスト、辞書、例外処理 (`try` / `error`)、
`eval` / `load` / `require` によるメタプログラミングとモジュール分割を備えています。

## インストールと実行

インストールせずにそのまま動かせます。

```bash
bin/crema examples/hello.crema
```

`crema` コマンドとしてインストールする場合は、次のコマンドを実行します。

```bash
pip install .
```

### CLI の使い方

```text
crema FILE [ARGS...]     プログラムを実行する (ARGS は args ワードで受け取れる)
crema -e CODE [ARGS...]  コマンドラインに書いたコードを実行する
crema -c FILE            構文チェックだけを行う
crema -                  標準入力からプログラムを読んで実行する
crema                    対話型の REPL を起動する
crema --help / --version
```

`exit` ワードで終了コードを指定できます。実行時エラーが起きたときは、
ファイル名・行番号・呼び出し履歴を標準エラー出力に表示して、終了コード 1 で終わります。

```text
$ bin/crema -e '1 "a" +'
<command-line>:1: error: +: cannot add int and string
  in <main> (<command-line>:1)
```

ファイルの先頭に `#!/usr/bin/env crema` と書いて実行権限を付ければ、スクリプトとして直接実行することもできます。

## 5 分でわかる Crema

```crema
# コメントは # から行末まで。( ... ) もコメント (スタック効果の注記に使う)

1 2 + print              # 3
10 3 / print             # 3.3333333333333335
10 2 / print             # 5
"Hello, " "Crema" + print

# 関数定義
: square ( n -- n*n ) dup * ;
7 square print           # 49

# ローカル変数: -> で名前を付ける
: hyp ( a b -- c ) -> { a b }  a square b square + sqrt ;
3 4 hyp print            # 5

# 条件分岐: 条件 [ 真のとき ] [ 偽のとき ] if
: sign ( n -- s ) dup 0 < [ drop "negative" ] [ 0 = [ "zero" ] [ "positive" ] if ] if ;
-3 sign print

# ループ
1 5 [ print ] for                        # 1 から 5 まで
3 [ "hi" print ] times
0 -> i  [ i 3 < ] [ i print  i 1 + -> i ] while

# リストと高階関数
{ 1 2 3 4 5 } [ dup * ] map print        # { 1 4 9 16 25 }
{ 1 2 3 4 5 } [ 2 mod 0 = ] filter print # { 2 4 }
{ 1 2 3 4 5 } 0 [ + ] fold print         # 15

# 辞書
dict "apple" 3 put "pear" 5 put -> stock
stock "apple" at print                   # 3

# ファイル
"hello\n" "out.txt" write-file
"world\n" "out.txt" append-file
"out.txt" read-lines print               # { "hello" "world" }

# 例外処理
[ 1 0 / ] [ "caught: " swap + print ] try
```

言語仕様と全組み込みワードの一覧は [docs/LANGUAGE.md](docs/LANGUAGE.md) にまとめています。

## サンプルプログラム

`examples/` に Crema で書いたプログラムを置いています。

| ファイル | 内容 |
| --- | --- |
| `hello.crema` | Hello, World |
| `factorial.crema` | 再帰による階乗 (任意精度整数) |
| `fib.crema` | フィボナッチ数 (素朴な再帰・末尾再帰・メモ化) |
| `fizzbuzz.crema` | FizzBuzz (`for` と `return`) |
| `quicksort.crema` | クイックソート (再帰・クロージャ・`filter`) |
| `hanoi.crema` | ハノイの塔 |
| `primes.crema` | エラトステネスのふるい (`while`) |
| `files.crema` | ファイルの読み書き |
| `wordcount.crema` | 単語の出現頻度 (ファイルまたは標準入力) |
| `errors.crema` | `try` / `error` / `assert` によるエラー処理 |
| `calc.crema` | Crema で書いた RPN 電卓 (標準入力から式を読んで評価する) |
| `brainfuck.crema` | Crema で書いた Brainfuck インタプリタ |

```bash
bin/crema examples/fib.crema
echo "3 4 + 2 *" | bin/crema examples/calc.crema
bin/crema examples/wordcount.crema README.md
bin/crema examples/brainfuck.crema
```

## テスト

```bash
python3 -m unittest discover -s tests
```

## 実装の構成

| ファイル | 役割 |
| --- | --- |
| `crema/lexer.py` | 字句解析 |
| `crema/parser.py` | 構文解析 (トークン → 命令列)。関数定義を集める |
| `crema/vm.py` | 仮想マシン。データスタックと制御スタックを持つ |
| `crema/builtins.py` | 組み込みワード |
| `crema/values.py` | 値の表現・表示・比較 |
| `crema/cli.py` | コマンドラインと REPL |

VM は Python の再帰を使わず、フレームを積んだ制御スタックをループで処理します。
`while` や `map` のような制御構造は「次に実行するクォートを yield するジェネレータ」として実装しているため、
制御構造の中から関数を呼んでも Python のスタックは深くなりません。
