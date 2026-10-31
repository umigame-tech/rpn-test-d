"""組み込みワード。

各ワードは VM を受け取る関数で、スタックを直接操作する。
クォートを実行したいワードは Frame を返す (VM がそれを制御スタックに積む)。
ループ系のワードはジェネレータを包んだ Frame を返し、
ジェネレータは実行してほしい Quote を yield する。
"""

import math
import os
import random as _random
import time

from .errors import BreakSignal, CremaError, ExitSignal, ReturnSignal, UserError
from .values import Quote, equal, rep, show, truthy, type_name
from .vm import Frame

BUILTINS = {}


def word(*names):
    def deco(fn):
        for n in names:
            BUILTINS[n] = fn
        return fn
    return deco


def _is_num(v):
    t = type(v)
    return t is int or t is float


# ======================================================================
# スタック操作

@word("dup")
def _dup(vm):
    vm.push(vm.peek())


@word("drop")
def _drop(vm):
    vm.pop()


@word("swap")
def _swap(vm):
    b = vm.pop()
    a = vm.pop()
    vm.push(b)
    vm.push(a)


@word("over")
def _over(vm):
    b = vm.pop()
    a = vm.peek()
    vm.push(b)
    vm.push(a)


@word("rot")
def _rot(vm):  # ( a b c -- b c a )
    c, b, a = vm.pop(), vm.pop(), vm.pop()
    vm.stack.extend((b, c, a))


@word("-rot")
def _mrot(vm):  # ( a b c -- c a b )
    c, b, a = vm.pop(), vm.pop(), vm.pop()
    vm.stack.extend((c, a, b))


@word("nip")
def _nip(vm):
    b = vm.pop()
    vm.pop()
    vm.push(b)


@word("tuck")
def _tuck(vm):  # ( a b -- b a b )
    b, a = vm.pop(), vm.pop()
    vm.stack.extend((b, a, b))


@word("2dup")
def _2dup(vm):
    b, a = vm.pop(), vm.pop()
    vm.stack.extend((a, b, a, b))


@word("2drop")
def _2drop(vm):
    vm.pop()
    vm.pop()


@word("pick")
def _pick(vm):  # ( ... n -- ... x ) 0 pick == dup
    n = vm.pop_int()
    if n < 0 or n >= len(vm.stack):
        raise CremaError("stack underflow")
    vm.push(vm.stack[-1 - n])


@word("depth")
def _depth(vm):
    vm.push(len(vm.stack))


@word("clear")
def _clear(vm):
    vm.stack.clear()


# ======================================================================
# 算術

@word("+")
def _add(vm):
    b, a = vm.pop(), vm.pop()
    ta, tb = type(a), type(b)
    if _is_num(a) and _is_num(b):
        vm.push(a + b)
    elif ta is str and tb is str:
        vm.push(a + b)
    elif ta is list and tb is list:
        vm.push(a + b)
    else:
        raise CremaError(f"cannot add {type_name(a)} and {type_name(b)}")


@word("-")
def _sub(vm):
    b, a = vm.pop_num(), vm.pop_num()
    vm.push(a - b)


@word("*")
def _mul(vm):
    b, a = vm.pop(), vm.pop()
    if _is_num(a) and _is_num(b):
        vm.push(a * b)
    elif type(a) in (str, list) and type(b) is int:
        vm.push(a * b)
    else:
        raise CremaError(f"cannot multiply {type_name(a)} and {type_name(b)}")


@word("/")
def _div(vm):
    b, a = vm.pop_num(), vm.pop_num()
    if b == 0:
        raise CremaError("division by zero")
    if type(a) is int and type(b) is int and a % b == 0:
        vm.push(a // b)
    else:
        vm.push(a / b)


@word("div")
def _idiv(vm):
    b, a = vm.pop_num(), vm.pop_num()
    if b == 0:
        raise CremaError("division by zero")
    vm.push(a // b)


@word("mod")
def _mod(vm):
    b, a = vm.pop_num(), vm.pop_num()
    if b == 0:
        raise CremaError("division by zero")
    vm.push(a % b)


@word("pow")
def _pow(vm):
    b, a = vm.pop_num(), vm.pop_num()
    vm.push(a ** b)


def _unary(name, fn):
    def impl(vm):
        vm.push(fn(vm.pop_num()))
    BUILTINS[name] = impl


_unary("neg", lambda x: -x)
_unary("abs", abs)
_unary("inc", lambda x: x + 1)
_unary("dec", lambda x: x - 1)
_unary("floor", math.floor)
_unary("ceil", math.ceil)
_unary("round", round)
_unary("trunc", math.trunc)
_unary("sin", math.sin)
_unary("cos", math.cos)
_unary("tan", math.tan)
_unary("exp", math.exp)


@word("sqrt")
def _sqrt(vm):
    x = vm.pop_num()
    if x < 0:
        raise CremaError("square root of negative number")
    r = math.sqrt(x)
    vm.push(int(r) if type(x) is int and r.is_integer() else r)


@word("log")
def _log(vm):
    x = vm.pop_num()
    if x <= 0:
        raise CremaError("logarithm of non-positive number")
    vm.push(math.log(x))


@word("min")
def _min(vm):
    b, a = vm.pop(), vm.pop()
    vm.push(b if _less(b, a) else a)


@word("max")
def _max(vm):
    b, a = vm.pop(), vm.pop()
    vm.push(b if _less(a, b) else a)


@word("pi")
def _pi(vm):
    vm.push(math.pi)


def _bitop(name, fn):
    def impl(vm):
        b, a = vm.pop_int(), vm.pop_int()
        vm.push(fn(a, b))
    BUILTINS[name] = impl


_bitop("band", lambda a, b: a & b)
_bitop("bor", lambda a, b: a | b)
_bitop("bxor", lambda a, b: a ^ b)
_bitop("shl", lambda a, b: a << b)
_bitop("shr", lambda a, b: a >> b)


# ======================================================================
# 比較・論理

def _less(a, b):
    if _is_num(a) and _is_num(b):
        return a < b
    if type(a) is str and type(b) is str:
        return a < b
    if type(a) is list and type(b) is list:
        for x, y in zip(a, b):
            if _less(x, y):
                return True
            if _less(y, x):
                return False
        return len(a) < len(b)
    raise CremaError(f"cannot compare {type_name(a)} and {type_name(b)}")


@word("=")
def _eq(vm):
    b, a = vm.pop(), vm.pop()
    vm.push(equal(a, b))


@word("!=")
def _ne(vm):
    b, a = vm.pop(), vm.pop()
    vm.push(not equal(a, b))


@word("<")
def _lt(vm):
    b, a = vm.pop(), vm.pop()
    vm.push(_less(a, b))


@word(">")
def _gt(vm):
    b, a = vm.pop(), vm.pop()
    vm.push(_less(b, a))


@word("<=")
def _le(vm):
    b, a = vm.pop(), vm.pop()
    vm.push(not _less(b, a))


@word(">=")
def _ge(vm):
    b, a = vm.pop(), vm.pop()
    vm.push(not _less(a, b))


@word("and")
def _and(vm):
    b, a = vm.pop(), vm.pop()
    vm.push(truthy(a) and truthy(b))


@word("or")
def _or(vm):
    b, a = vm.pop(), vm.pop()
    vm.push(truthy(a) or truthy(b))


@word("not")
def _not(vm):
    vm.push(not truthy(vm.pop()))


@word("nil?")
def _is_nil(vm):
    vm.push(vm.pop() is None)


# ======================================================================
# 制御構造

@word("call")
def _call(vm):
    return Frame.for_quote(vm.pop_quote())


@word("if")
def _if(vm):  # ( cond [then] [else] -- )
    qf, qt = vm.pop_quote(), vm.pop_quote()
    return Frame.for_quote(qt if truthy(vm.pop()) else qf)


@word("when")
def _when(vm):  # ( cond [then] -- )
    q = vm.pop_quote()
    if truthy(vm.pop()):
        return Frame.for_quote(q)
    return None


@word("unless")
def _unless(vm):  # ( cond [else] -- )
    q = vm.pop_quote()
    if not truthy(vm.pop()):
        return Frame.for_quote(q)
    return None


@word("while")
def _while(vm):  # ( [cond] [body] -- )
    body, cond = vm.pop_quote(), vm.pop_quote()

    def gen():
        while True:
            yield cond
            if not truthy(vm.pop()):
                return
            yield body
    return Frame.for_gen(gen(), loop=True)


@word("loop")
def _loop(vm):  # ( [body] -- )  break で抜けるまで繰り返す
    body = vm.pop_quote()

    def gen():
        while True:
            yield body
    return Frame.for_gen(gen(), loop=True)


@word("times")
def _times(vm):  # ( n [body] -- )
    body = vm.pop_quote()
    n = vm.pop_int()

    def gen():
        for _ in range(n):
            yield body
    return Frame.for_gen(gen(), loop=True)


@word("for")
def _for(vm):  # ( from to [body] -- )  from から to まで (to を含む)。body にはカウンタが渡される
    body = vm.pop_quote()
    end, start = vm.pop_int(), vm.pop_int()
    push = vm.push

    def gen():
        for i in range(start, end + 1):
            push(i)
            yield body
    return Frame.for_gen(gen(), loop=True)


def _iter_items(seq):
    t = type(seq)
    if t is list:
        return list(seq)
    if t is str:
        return list(seq)
    if t is dict:
        return [[k, v] for k, v in seq.items()]
    raise CremaError(f"expected list, string or dict, got {type_name(seq)}")


@word("each")
def _each(vm):  # ( seq [body] -- )  辞書の場合は { key value } が渡される
    body = vm.pop_quote()
    items = _iter_items(vm.pop())
    push = vm.push

    def gen():
        for x in items:
            push(x)
            yield body
    return Frame.for_gen(gen(), loop=True)


@word("map")
def _map(vm):  # ( seq [f] -- list )
    f = vm.pop_quote()
    items = _iter_items(vm.pop())

    def gen():
        out = []
        for x in items:
            vm.push(x)
            yield f
            out.append(vm.pop())
        vm.push(out)
    return Frame.for_gen(gen(), loop=True)


@word("filter")
def _filter(vm):  # ( seq [pred] -- list )
    f = vm.pop_quote()
    items = _iter_items(vm.pop())

    def gen():
        out = []
        for x in items:
            vm.push(x)
            yield f
            if truthy(vm.pop()):
                out.append(x)
        vm.push(out)
    return Frame.for_gen(gen(), loop=True)


@word("fold")
def _fold(vm):  # ( seq init [f] -- acc )  f: ( acc x -- acc )
    f = vm.pop_quote()
    init = vm.pop()
    items = _iter_items(vm.pop())

    def gen():
        vm.push(init)
        for x in items:
            vm.push(x)
            yield f
    return Frame.for_gen(gen(), loop=True)


@word("sort-by")
def _sort_by(vm):  # ( list [key] -- list )
    f = vm.pop_quote()
    items = _iter_items(vm.pop())

    def gen():
        keys = []
        for x in items:
            vm.push(x)
            yield f
            keys.append(vm.pop())
        order = _stable_sort(list(range(len(items))), lambda i: keys[i])
        vm.push([items[i] for i in order])
    return Frame.for_gen(gen())


@word("dip")
def _dip(vm):  # ( x [q] -- ... x )  x を退避して q を実行し、x を戻す
    q = vm.pop_quote()
    x = vm.pop()

    def gen():
        yield q
        vm.push(x)
    return Frame.for_gen(gen())


@word("keep")
def _keep(vm):  # ( x [q] -- ... x )  x を q に渡したうえで、あとで x を戻す
    q = vm.pop_quote()
    x = vm.peek()

    def gen():
        yield q
        vm.push(x)
    return Frame.for_gen(gen())


@word("try")
def _try(vm):  # ( [body] [handler] -- )  エラー時は handler にメッセージが渡される
    handler, body = vm.pop_quote(), vm.pop_quote()

    def gen():
        yield body
    return Frame.for_gen(gen(), handler=(handler, len(vm.stack), len(vm.marks)))


@word("error")
def _error(vm):  # ( msg -- )
    raise UserError(show(vm.pop()))


@word("assert")
def _assert(vm):  # ( cond msg -- )
    msg = vm.pop()
    if not truthy(vm.pop()):
        raise UserError(f"assertion failed: {show(msg)}")


@word("return")
def _return(vm):
    raise ReturnSignal()


@word("break")
def _break(vm):
    raise BreakSignal()


# ======================================================================
# 型・変換

@word("type")
def _type(vm):
    vm.push(type_name(vm.pop()))


@word("str")
def _str(vm):
    vm.push(show(vm.pop()))


@word("repr")
def _repr(vm):
    vm.push(rep(vm.pop()))


@word("num")
def _num(vm):  # ( string|number -- number )
    from .lexer import parse_number
    v = vm.pop()
    if _is_num(v):
        vm.push(v)
        return
    if type(v) is not str:
        raise CremaError(f"cannot convert {type_name(v)} to number")
    n = parse_number(v.strip())
    if n is None:
        raise CremaError(f"not a number: {rep(v)}")
    vm.push(n)


@word("int")
def _int(vm):
    v = vm.pop()
    if type(v) is str:
        vm.push(v)
        _num(vm)
        v = vm.pop()
    if type(v) is bool:
        vm.push(1 if v else 0)
    elif _is_num(v):
        vm.push(int(v))
    else:
        raise CremaError(f"cannot convert {type_name(v)} to int")


@word("float")
def _float(vm):
    vm.push(vm.pop())
    _num(vm)
    vm.push(float(vm.pop()))


@word("number?")
def _is_number(vm):
    vm.push(_is_num(vm.pop()))


@word("string?")
def _is_string(vm):
    vm.push(type(vm.pop()) is str)


@word("list?")
def _is_list(vm):
    vm.push(type(vm.pop()) is list)


@word("dict?")
def _is_dict(vm):
    vm.push(type(vm.pop()) is dict)


@word("quote?")
def _is_quote(vm):
    vm.push(type(vm.pop()) is Quote)


# ======================================================================
# シーケンス (リスト・文字列) 共通

def _pop_seq(vm):
    v = vm.pop()
    if type(v) not in (list, str):
        raise CremaError(f"expected list or string, got {type_name(v)}")
    return v


@word("len")
def _len(vm):
    v = vm.pop()
    if type(v) not in (list, str, dict):
        raise CremaError(f"expected list, string or dict, got {type_name(v)}")
    vm.push(len(v))


@word("empty?")
def _empty(vm):
    vm.push(len(_pop_seq_or_dict(vm)) == 0)


def _pop_seq_or_dict(vm):
    v = vm.pop()
    if type(v) not in (list, str, dict):
        raise CremaError(f"expected list, string or dict, got {type_name(v)}")
    return v


def _index(seq, i):
    if type(i) is not int:
        raise CremaError(f"index must be an integer, got {type_name(i)}")
    n = len(seq)
    if not -n <= i < n:
        raise CremaError(f"index {i} out of range (length {n})")
    return i


@word("at", "nth")
def _at(vm):  # ( list|string i -- x ) / ( dict key -- x )
    k = vm.pop()
    c = vm.pop()
    if type(c) is dict:
        if k not in c:
            raise CremaError(f"key not found: {rep(k)}")
        vm.push(c[k])
    elif type(c) in (list, str):
        vm.push(c[_index(c, k)])
    else:
        raise CremaError(f"expected list, string or dict, got {type_name(c)}")


@word("put", "set-nth")
def _put(vm):  # ( list i x -- list ) / ( dict key x -- dict )  その場で書き換える
    x = vm.pop()
    k = vm.pop()
    c = vm.pop()
    if type(c) is dict:
        _check_key(k)
        c[k] = x
    elif type(c) is list:
        c[_index(c, k)] = x
    else:
        raise CremaError(f"expected list or dict, got {type_name(c)}")
    vm.push(c)


@word("first")
def _first(vm):
    s = _pop_seq(vm)
    vm.push(s[_index(s, 0)])


@word("last")
def _last(vm):
    s = _pop_seq(vm)
    vm.push(s[_index(s, -1)])


@word("rest")
def _rest(vm):
    vm.push(_pop_seq(vm)[1:])


@word("slice")
def _slice(vm):  # ( seq from to -- sub )  to は含まない
    end, start = vm.pop_int(), vm.pop_int()
    vm.push(_pop_seq(vm)[start:end])


@word("reverse")
def _reverse(vm):
    vm.push(_pop_seq(vm)[::-1])


@word("contains?")
def _contains(vm):  # ( seq x -- bool ) / ( dict key -- bool )
    x = vm.pop()
    c = vm.pop()
    t = type(c)
    if t is str:
        if type(x) is not str:
            raise CremaError(f"expected string, got {type_name(x)}")
        vm.push(x in c)
    elif t is list:
        vm.push(any(equal(y, x) for y in c))
    elif t is dict:
        vm.push(x in c)
    else:
        raise CremaError(f"expected list, string or dict, got {type_name(c)}")


@word("has?")
def _has(vm):
    _contains(vm)


@word("index-of")
def _index_of(vm):  # ( seq x -- i )  見つからなければ -1
    x = vm.pop()
    c = _pop_seq(vm)
    if type(c) is str:
        if type(x) is not str:
            raise CremaError(f"expected string, got {type_name(x)}")
        vm.push(c.find(x))
    else:
        for i, y in enumerate(c):
            if equal(y, x):
                vm.push(i)
                return
        vm.push(-1)


# ======================================================================
# リスト

@word("append")
def _append(vm):  # ( list x -- list )  その場で末尾に追加する
    x = vm.pop()
    lst = vm.pop_list()
    lst.append(x)
    vm.push(lst)


@word("pop")
def _pop(vm):  # ( list -- list x )  その場で末尾を取り出す
    lst = vm.pop_list()
    if not lst:
        raise CremaError("list is empty")
    x = lst.pop()
    vm.push(lst)
    vm.push(x)


@word("insert")
def _insert(vm):  # ( list i x -- list )
    x = vm.pop()
    i = vm.pop_int()
    lst = vm.pop_list()
    lst.insert(i, x)
    vm.push(lst)


@word("remove-at")
def _remove_at(vm):  # ( list i -- list )
    i = vm.pop_int()
    lst = vm.pop_list()
    del lst[_index(lst, i)]
    vm.push(lst)


@word("copy")
def _copy(vm):
    v = vm.pop()
    if type(v) is list:
        vm.push(list(v))
    elif type(v) is dict:
        vm.push(dict(v))
    else:
        vm.push(v)


@word("range")
def _range(vm):  # ( from to -- list )  to は含まない
    end, start = vm.pop_int(), vm.pop_int()
    vm.push(list(range(start, end)))


def _stable_sort(items, key=lambda x: x):
    import functools

    def cmp(a, b):
        ka, kb = key(a), key(b)
        if _less(ka, kb):
            return -1
        if _less(kb, ka):
            return 1
        return 0
    return sorted(items, key=functools.cmp_to_key(cmp))


@word("sort")
def _sort(vm):
    vm.push(_stable_sort(vm.pop_list()))


@word("sum")
def _sum(vm):
    lst = vm.pop_list()
    total = 0
    for x in lst:
        if not _is_num(x):
            raise CremaError(f"expected list of numbers, found {type_name(x)}")
        total += x
    vm.push(total)


@word("unpack")
def _unpack(vm):  # ( list -- x1 x2 ... xn )
    vm.stack.extend(vm.pop_list())


@word("pack")
def _pack(vm):  # ( x1 ... xn n -- list )
    n = vm.pop_int()
    if n < 0 or n > len(vm.stack):
        raise CremaError("stack underflow")
    items = vm.stack[len(vm.stack) - n:]
    del vm.stack[len(vm.stack) - n:]
    vm.push(items)


# ======================================================================
# 辞書

def _check_key(k):
    if type(k) not in (str, int, float, bool) and k is not None:
        raise CremaError(f"{type_name(k)} cannot be used as a dict key")


@word("dict")
def _dict(vm):  # ( -- dict )
    vm.push({})


@word("to-dict")
def _to_dict(vm):  # ( { { k v } ... } -- dict )
    lst = vm.pop_list()
    d = {}
    for pair in lst:
        if type(pair) is not list or len(pair) != 2:
            raise CremaError("expected list of { key value } pairs")
        _check_key(pair[0])
        d[pair[0]] = pair[1]
    vm.push(d)


@word("get")
def _get(vm):  # ( dict key default -- x )
    default = vm.pop()
    k = vm.pop()
    d = vm.pop_dict()
    vm.push(d.get(k, default) if type(k) is not list else default)


@word("remove")
def _remove(vm):  # ( dict key -- dict )
    k = vm.pop()
    d = vm.pop_dict()
    d.pop(k, None)
    vm.push(d)


@word("keys")
def _keys(vm):
    vm.push(list(vm.pop_dict().keys()))


@word("values")
def _values(vm):
    vm.push(list(vm.pop_dict().values()))


@word("pairs")
def _pairs(vm):
    vm.push([[k, v] for k, v in vm.pop_dict().items()])


# ======================================================================
# 文字列

@word("upper")
def _upper(vm):
    vm.push(vm.pop_str().upper())


@word("lower")
def _lower(vm):
    vm.push(vm.pop_str().lower())


@word("trim")
def _trim(vm):
    vm.push(vm.pop_str().strip())


@word("split")
def _split(vm):  # ( str sep -- list )  sep が "" なら空白で区切る
    sep = vm.pop_str()
    s = vm.pop_str()
    vm.push(s.split() if sep == "" else s.split(sep))


@word("join")
def _join(vm):  # ( list sep -- str )
    sep = vm.pop_str()
    lst = vm.pop_list()
    vm.push(sep.join(show(x) for x in lst))


@word("chars")
def _chars(vm):
    vm.push(list(vm.pop_str()))


@word("lines")
def _lines(vm):
    vm.push(vm.pop_str().splitlines())


@word("replace")
def _replace(vm):  # ( str old new -- str )
    new = vm.pop_str()
    old = vm.pop_str()
    vm.push(vm.pop_str().replace(old, new))


@word("starts-with?")
def _starts_with(vm):
    p = vm.pop_str()
    vm.push(vm.pop_str().startswith(p))


@word("ends-with?")
def _ends_with(vm):
    p = vm.pop_str()
    vm.push(vm.pop_str().endswith(p))


@word("ord")
def _ord(vm):
    s = vm.pop_str()
    if len(s) != 1:
        raise CremaError(f"expected a single character, got {rep(s)}")
    vm.push(ord(s))


@word("chr")
def _chr(vm):
    vm.push(chr(vm.pop_int()))


@word("pad-left")
def _pad_left(vm):  # ( v width -- str )
    w = vm.pop_int()
    vm.push(show(vm.pop()).rjust(w))


@word("pad-right")
def _pad_right(vm):  # ( v width -- str )
    w = vm.pop_int()
    vm.push(show(vm.pop()).ljust(w))


@word("format")
def _format(vm):  # ( template { args } -- str )  {} を順に置き換える
    args = vm.pop_list()
    tmpl = vm.pop_str()
    parts = tmpl.split("{}")
    if len(parts) - 1 != len(args):
        raise CremaError(
            f"template has {len(parts) - 1} placeholders but {len(args)} values were given")
    out = [parts[0]]
    for a, p in zip(args, parts[1:]):
        out.append(show(a))
        out.append(p)
    vm.push("".join(out))


# ======================================================================
# 入出力

@word("print", ".")
def _print(vm):
    vm.out.write(show(vm.pop()) + "\n")


@word("write")
def _write(vm):
    vm.out.write(show(vm.pop()))


@word("eprint")
def _eprint(vm):
    import sys
    sys.stderr.write(show(vm.pop()) + "\n")


@word("nl")
def _nl(vm):
    vm.out.write("\n")


@word(".s")
def _dot_s(vm):
    vm.out.write(stack_str(vm.stack) + "\n")


def stack_str(stack):
    return f"<{len(stack)}> " + " ".join(rep(v) for v in stack) if stack else "<0>"


@word("read-line")
def _read_line(vm):  # ( -- str|nil )  入力の終わりでは nil
    line = vm.inp.readline()
    if line == "":
        vm.push(None)
    else:
        vm.push(line[:-1] if line.endswith("\n") else line)


@word("read-all")
def _read_all(vm):
    vm.push(vm.inp.read())


# ======================================================================
# ファイル

@word("read-file")
def _read_file(vm):  # ( path -- str )
    with open(vm.pop_str(), encoding="utf-8") as f:
        vm.push(f.read())


@word("read-lines")
def _read_lines(vm):  # ( path -- list )
    with open(vm.pop_str(), encoding="utf-8") as f:
        vm.push(f.read().splitlines())


@word("write-file")
def _write_file(vm):  # ( content path -- )
    path = vm.pop_str()
    content = show(vm.pop())
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


@word("append-file")
def _append_file(vm):  # ( content path -- )
    path = vm.pop_str()
    content = show(vm.pop())
    with open(path, "a", encoding="utf-8") as f:
        f.write(content)


@word("file-exists?")
def _file_exists(vm):
    vm.push(os.path.exists(vm.pop_str()))


@word("delete-file")
def _delete_file(vm):
    os.remove(vm.pop_str())


@word("list-dir")
def _list_dir(vm):
    vm.push(sorted(os.listdir(vm.pop_str())))


@word("make-dir")
def _make_dir(vm):
    os.makedirs(vm.pop_str(), exist_ok=True)


# ======================================================================
# システム・メタ

@word("args")
def _args(vm):
    vm.push(list(vm.argv))


@word("exit")
def _exit(vm):  # ( code -- )
    raise ExitSignal(vm.pop_int())


@word("now")
def _now(vm):
    vm.push(time.time())


@word("random")
def _random_word(vm):  # ( -- float )  0 以上 1 未満
    vm.push(_random.random())


@word("random-int")
def _random_int(vm):  # ( from to -- n )  to を含む
    b, a = vm.pop_int(), vm.pop_int()
    vm.push(_random.randint(a, b))


@word("getenv")
def _getenv(vm):  # ( name -- str|nil )
    vm.push(os.environ.get(vm.pop_str()))


def _current_dir(vm):
    f = vm.cur_frame
    if f is not None and f.code and f.pc > 0:
        src = f.code[f.pc - 1][2][0]
        if os.path.isfile(src):
            return os.path.dirname(os.path.abspath(src))
    return os.getcwd()


def _resolve(vm, path):
    return path if os.path.isabs(path) else os.path.join(_current_dir(vm), path)


@word("eval")
def _eval(vm):  # ( source -- ... )  現在のスコープで文字列をプログラムとして実行する
    code = vm.compile(vm.pop_str(), "<eval>")
    return Frame(code, vm.cur_frame.env, "<eval>", is_func=True)


@word("load")
def _load(vm):  # ( path -- )  ファイルを読み込んで実行する (呼び出し元からの相対パス)
    path = _resolve(vm, vm.pop_str())
    with open(path, encoding="utf-8") as f:
        src = f.read()
    vm.loaded.add(os.path.abspath(path))
    code = vm.compile(src, os.path.relpath(path))
    return Frame(code, vm.globals, "<load>", is_func=True)


@word("require")
def _require(vm):  # ( path -- )  まだ読み込んでいなければ load する
    path = _resolve(vm, vm.pop_str())
    if os.path.abspath(path) in vm.loaded:
        return None
    vm.push(path)
    return _load(vm)


@word("defined?")
def _defined(vm):  # ( name -- bool )
    name = vm.pop_str()
    vm.push(name in vm.functions or name in BUILTINS)


@word("words")
def _words(vm):  # ( -- list )  ユーザー定義関数と組み込みワードの一覧
    vm.push(sorted(set(vm.functions) | set(BUILTINS)))
