"""字句解析器: ソース文字列をトークン列に変換する。"""

import re

from .errors import IncompleteInput, ParseError

# 区切り文字。空白がなくてもトークンとして切り出される。
DELIMS = "[]{}"

_INT_RE = re.compile(r"[+-]?\d+\Z")
_HEX_RE = re.compile(r"[+-]?0[xX][0-9a-fA-F]+\Z")
_FLOAT_RE = re.compile(r"[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?\Z")

_ESCAPES = {
    "n": "\n", "t": "\t", "r": "\r", "0": "\0",
    "\\": "\\", '"': '"', "'": "'", "e": "\x1b",
}


class Token:
    __slots__ = ("kind", "value", "line")

    def __init__(self, kind, value, line):
        self.kind = kind    # "num" | "str" | "word" | "[" | "]" | "{" | "}"
        self.value = value
        self.line = line

    def __repr__(self):
        return f"Token({self.kind!r}, {self.value!r}, line={self.line})"


def parse_number(text):
    """数値リテラルなら int/float を、そうでなければ None を返す。"""
    if _INT_RE.match(text):
        return int(text)
    if _HEX_RE.match(text):
        return int(text, 16)
    if _FLOAT_RE.match(text) and any(c.isdigit() for c in text):
        return float(text)
    return None


def tokenize(src, source="<input>"):
    tokens = []
    i, n, line = 0, len(src), 1
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
        elif c.isspace():
            i += 1
        elif c == "#":
            # 行コメント (シバン行 #! も含む)
            while i < n and src[i] != "\n":
                i += 1
        elif c == "(" and (i + 1 >= n or src[i + 1].isspace()):
            # スタック効果コメント ( a b -- c ) 。入れ子も可。
            start_line, depth = line, 0
            while i < n:
                ch = src[i]
                if ch == "\n":
                    line += 1
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            if i >= n:
                raise IncompleteInput(
                    f"unterminated comment starting at line {start_line}",
                    (source, start_line))
            i += 1
        elif c in DELIMS:
            tokens.append(Token(c, c, line))
            i += 1
        elif c == '"':
            start_line = line
            i += 1
            buf = []
            while True:
                if i >= n:
                    raise IncompleteInput(
                        f"unterminated string starting at line {start_line}",
                        (source, start_line))
                ch = src[i]
                if ch == '"':
                    i += 1
                    break
                if ch == "\n":
                    line += 1
                if ch == "\\":
                    if i + 1 >= n:
                        raise IncompleteInput(
                            f"unterminated string starting at line {start_line}",
                            (source, start_line))
                    esc = src[i + 1]
                    if esc in _ESCAPES:
                        buf.append(_ESCAPES[esc])
                        i += 2
                    elif esc == "u":
                        hexdigits = src[i + 2:i + 6]
                        if len(hexdigits) != 4 or not all(
                                h in "0123456789abcdefABCDEF" for h in hexdigits):
                            raise ParseError(
                                f"invalid \\u escape at line {line}", (source, line))
                        buf.append(chr(int(hexdigits, 16)))
                        i += 6
                    elif esc == "\n":
                        # 行末の \ で改行を無視する
                        line += 1
                        i += 2
                    else:
                        raise ParseError(
                            f"unknown escape '\\{esc}' at line {line}", (source, line))
                else:
                    buf.append(ch)
                    i += 1
            tokens.append(Token("str", "".join(buf), start_line))
        else:
            j = i
            while j < n and not src[j].isspace() and src[j] not in DELIMS and src[j] != '"':
                j += 1
            text = src[i:j]
            num = parse_number(text)
            if num is not None:
                tokens.append(Token("num", num, line))
            else:
                tokens.append(Token("word", text, line))
            i = j
    return tokens
