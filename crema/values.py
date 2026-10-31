"""Crema の値の表現と、表示・比較などの共通処理。

Crema の値と Python の対応:
    数値      int / float
    文字列    str
    真偽値    bool (true / false)
    nil       None
    リスト    list
    辞書      dict
    クォート  Quote
"""


class Env:
    """変数のスコープ。関数呼び出しごとに作られ、親はグローバル。"""
    __slots__ = ("vars", "parent")

    def __init__(self, parent=None):
        self.vars = {}
        self.parent = parent


class Quote:
    """クォーテーション [ ... ]。作られた場所のスコープを捕捉する (クロージャ)。"""
    __slots__ = ("code", "env")

    def __init__(self, code, env):
        self.code = code
        self.env = env


def type_name(v):
    if v is None:
        return "nil"
    t = type(v)
    if t is bool:
        return "bool"
    if t is int:
        return "int"
    if t is float:
        return "float"
    if t is str:
        return "string"
    if t is list:
        return "list"
    if t is dict:
        return "dict"
    if t is Quote:
        return "quote"
    return t.__name__


def truthy(v):
    """false, nil, 0, 0.0 が偽。それ以外はすべて真。"""
    if v is False or v is None:
        return False
    t = type(v)
    if (t is int or t is float) and v == 0:
        return False
    return True


def _fmt_float(v):
    if v != v:
        return "nan"
    if v in (float("inf"), float("-inf")):
        return "inf" if v > 0 else "-inf"
    return repr(v)


def show(v):
    """print などで使う表示形式。文字列は引用符なしで表示する。"""
    if type(v) is str:
        return v
    return rep(v)


def rep(v):
    """ソース上のリテラルに近い表示形式。"""
    if v is None:
        return "nil"
    if v is True:
        return "true"
    if v is False:
        return "false"
    t = type(v)
    if t is int:
        return str(v)
    if t is float:
        return _fmt_float(v)
    if t is str:
        out = ['"']
        for ch in v:
            if ch == '"':
                out.append('\\"')
            elif ch == "\\":
                out.append("\\\\")
            elif ch == "\n":
                out.append("\\n")
            elif ch == "\t":
                out.append("\\t")
            elif ch == "\r":
                out.append("\\r")
            elif ord(ch) < 32:
                out.append(f"\\u{ord(ch):04x}")
            else:
                out.append(ch)
        out.append('"')
        return "".join(out)
    if t is list:
        if not v:
            return "{ }"
        return "{ " + " ".join(rep(x) for x in v) + " }"
    if t is dict:
        if not v:
            return "dict{ }"
        return "dict{ " + ", ".join(f"{rep(k)}: {rep(x)}" for k, x in v.items()) + " }"
    if t is Quote:
        from .parser import code_to_str
        inner = code_to_str(v.code)
        return f"[ {inner} ]" if inner else "[ ]"
    return repr(v)


def equal(a, b):
    """値の等価比較。true と 1 は等しくない。リスト・辞書は中身で比較する。"""
    ta, tb = type(a), type(b)
    if ta is bool or tb is bool or a is None or b is None:
        return a is b
    if ta is list:
        return tb is list and len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    if ta is dict:
        return (tb is dict and a.keys() == b.keys()
                and all(equal(a[k], b[k]) for k in a))
    if ta is Quote or tb is Quote:
        return a is b
    if (ta is str) != (tb is str):
        return False
    return a == b
