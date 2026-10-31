"""構文解析器: トークン列を命令列 (コード) に変換する。

命令はタプル (opcode, 引数, 位置) で表す。位置は (ソース名, 行番号)。
"""

from .errors import IncompleteInput, ParseError
from .lexer import tokenize, parse_number

OP_PUSH = 0     # 値を積む
OP_WORD = 1     # ワード (変数・関数・組み込み) を呼ぶ
OP_QUOTE = 2    # クォーテーション [ ... ] を積む
OP_BIND = 3     # -> name : スタックトップをローカル変数に束縛
OP_BINDN = 4    # -> { a b c } : 複数の値をまとめて束縛
OP_LBRACE = 5   # { : リスト構築の開始
OP_RBRACE = 6   # } : リスト構築の終了

RESERVED = {":", ";", "->", "true", "false", "nil"}
LITERALS = {"true": True, "false": False, "nil": None}


class Function:
    __slots__ = ("name", "code", "pos")

    def __init__(self, name, code, pos):
        self.name = name
        self.code = code
        self.pos = pos


class Parser:
    def __init__(self, tokens, source):
        self.toks = tokens
        self.i = 0
        self.source = source
        self.functions = {}

    def error(self, msg, tok, incomplete=False):
        cls = IncompleteInput if incomplete else ParseError
        return cls(msg, (self.source, tok.line))

    def next_name(self, after_tok, what):
        if self.i >= len(self.toks):
            raise self.error(f"expected {what} after '{after_tok.value}'", after_tok, True)
        t = self.toks[self.i]
        self.i += 1
        if t.kind != "word" or t.value in RESERVED or t.value.startswith("'"):
            raise self.error(f"invalid {what}: {t.value!r}", t)
        return t.value

    def parse_seq(self, end=None, opener=None, toplevel=False):
        code = []
        toks = self.toks
        while True:
            if self.i >= len(toks):
                if end is None:
                    return code
                raise self.error(
                    f"missing '{end}' for '{opener.value}' opened at line {opener.line}",
                    opener, incomplete=True)
            t = toks[self.i]
            self.i += 1
            pos = (self.source, t.line)
            kind = t.kind
            if kind == "num" or kind == "str":
                code.append((OP_PUSH, t.value, pos))
            elif kind == "[":
                code.append((OP_QUOTE, self.parse_seq("]", t), pos))
            elif kind == "{":
                code.append((OP_LBRACE, None, pos))
                code.extend(self.parse_seq("}", t))
                code.append((OP_RBRACE, None, pos))
            elif kind == "]" or kind == "}":
                if end == kind:
                    return code
                raise self.error(f"unexpected '{kind}'", t)
            else:
                w = t.value
                if w == ";":
                    if end == ";":
                        return code
                    raise self.error("unexpected ';' (no matching ':')", t)
                if w in LITERALS:
                    code.append((OP_PUSH, LITERALS[w], pos))
                elif w == ":":
                    if not toplevel:
                        raise self.error(
                            "function definitions (':') are only allowed at top level", t)
                    name = self.next_name(t, "function name")
                    body = self.parse_seq(";", t)
                    self.functions[name] = Function(name, body, pos)
                elif w == "->":
                    if self.i < len(toks) and toks[self.i].kind == "{":
                        brace = toks[self.i]
                        self.i += 1
                        names = []
                        while True:
                            if self.i >= len(toks):
                                raise self.error("missing '}' in '-> { ... }'", brace, True)
                            nt = toks[self.i]
                            if nt.kind == "}":
                                self.i += 1
                                break
                            names.append(self.next_name(t, "variable name"))
                        code.append((OP_BINDN, tuple(names), pos))
                    else:
                        code.append((OP_BIND, self.next_name(t, "variable name"), pos))
                elif len(w) > 1 and w[0] == "'":
                    # 'name は [ name ] の省略形
                    code.append((OP_QUOTE, [(OP_WORD, w[1:], pos)], pos))
                else:
                    code.append((OP_WORD, w, pos))


def parse(src, source="<input>"):
    """ソースを解析して (トップレベルのコード, 関数定義の辞書) を返す。"""
    p = Parser(tokenize(src, source), source)
    code = p.parse_seq(toplevel=True)
    return code, p.functions


def code_to_str(code):
    """コードをソース風の文字列に戻す (表示用)。"""
    from .values import rep
    parts = []
    for op, arg, _ in code:
        if op == OP_PUSH:
            parts.append(rep(arg))
        elif op == OP_WORD:
            parts.append(arg)
        elif op == OP_QUOTE:
            inner = code_to_str(arg)
            parts.append(f"[ {inner} ]" if inner else "[ ]")
        elif op == OP_BIND:
            parts.append(f"-> {arg}")
        elif op == OP_BINDN:
            parts.append("-> { " + " ".join(arg) + " }")
        elif op == OP_LBRACE:
            parts.append("{")
        elif op == OP_RBRACE:
            parts.append("}")
    return " ".join(parts)


__all__ = ["parse", "parse_number", "Function", "code_to_str"]
