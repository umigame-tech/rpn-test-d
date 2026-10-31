"""Crema の仮想マシン。

データスタックとは別に「制御スタック」(フレームの列) を明示的に持ち、
Python の再帰を使わずに実行する。これにより深い再帰も実行でき、
末尾呼び出しはフレームを積まずに済む (末尾呼び出し最適化)。

フレームには 2 種類ある:
  * コードフレーム: 命令列 code と実行位置 pc を持つ
  * ジェネレータフレーム: while や map などの組み込みが返すジェネレータ。
    実行してほしい Quote を yield し、その実行が終わると再開される。
"""

import os
import sys

from .errors import (BreakSignal, CremaError, ExitSignal, ReturnSignal,
                     UserError)
from .parser import (OP_BIND, OP_BINDN, OP_LBRACE, OP_PUSH, OP_QUOTE,
                     OP_RBRACE, OP_WORD, parse)
from .values import Env, Quote, type_name

DEFAULT_MAX_DEPTH = 1_000_000


class Frame:
    __slots__ = ("code", "pc", "env", "name", "is_func", "gen", "loop", "handler")

    def __init__(self, code, env, name=None, is_func=False, gen=None,
                 loop=False, handler=None):
        self.code = code
        self.pc = 0
        self.env = env
        self.name = name          # 関数名 (スタックトレース用)
        self.is_func = is_func    # return の戻り先になる境界か
        self.gen = gen            # ジェネレータフレームならジェネレータ
        self.loop = loop          # break の対象になるループか
        self.handler = handler    # try のハンドラ (Quote, スタック深さ, マーク深さ)

    @classmethod
    def for_quote(cls, q):
        return cls(q.code, q.env)

    @classmethod
    def for_gen(cls, gen, loop=False, handler=None):
        return cls(None, None, gen=gen, loop=loop, handler=handler)


class VM:
    def __init__(self, argv=None, out=None, inp=None, max_depth=DEFAULT_MAX_DEPTH):
        from .builtins import BUILTINS
        self.builtins = BUILTINS
        self.stack = []
        self.cs = []                  # 制御スタック
        self.marks = []               # { ... } の開始位置
        self.functions = {}
        self.globals = Env()
        self.argv = list(argv or [])
        self.out = out if out is not None else sys.stdout
        self.inp = inp if inp is not None else sys.stdin
        self.max_depth = max_depth
        self.cur_frame = None
        self.loaded = set()           # require 済みのファイル

    # ------------------------------------------------------------------
    # スタック操作のヘルパ (組み込みワードから使う)

    def push(self, v):
        self.stack.append(v)

    def pop(self):
        if not self.stack:
            raise CremaError("stack underflow")
        return self.stack.pop()

    def peek(self):
        if not self.stack:
            raise CremaError("stack underflow")
        return self.stack[-1]

    def _expect(self, v, ok, what):
        if not ok:
            raise CremaError(f"expected {what}, got {type_name(v)}")
        return v

    def pop_num(self):
        v = self.pop()
        t = type(v)
        return self._expect(v, t is int or t is float, "number")

    def pop_int(self):
        v = self.pop()
        if type(v) is float and v.is_integer():
            return int(v)
        return self._expect(v, type(v) is int, "integer")

    def pop_str(self):
        v = self.pop()
        return self._expect(v, type(v) is str, "string")

    def pop_list(self):
        v = self.pop()
        return self._expect(v, type(v) is list, "list")

    def pop_dict(self):
        v = self.pop()
        return self._expect(v, type(v) is dict, "dict")

    def pop_quote(self):
        v = self.pop()
        return self._expect(v, type(v) is Quote, "quote")

    # ------------------------------------------------------------------
    # コンパイルと実行

    def compile(self, src, source="<input>"):
        """ソースを解析し、関数定義を登録してトップレベルのコードを返す。"""
        code, functions = parse(src, source)
        self.functions.update(functions)
        return code

    def run_source(self, src, source="<input>"):
        self.execute(self.compile(src, source))

    def run_file(self, path):
        with open(path, encoding="utf-8") as f:
            src = f.read()
        self.loaded.add(os.path.abspath(path))
        self.run_source(src, path)

    def execute(self, code, env=None, name="<main>"):
        base = len(self.cs)
        self.cs.append(Frame(code, env or self.globals, name, is_func=True))
        try:
            self._run(base)
        finally:
            del self.cs[base:]
            if self.cur_frame is not None and base == 0:
                self.cur_frame = None

    def call_quote(self, q):
        """Python 側からクォートを呼び出す (テストや埋め込み用)。"""
        self.execute(q.code, q.env, name="<call>")

    def _run(self, base):
        cs = self.cs
        stack = self.stack
        push = stack.append
        functions = self.functions
        builtins = self.builtins
        globals_env = self.globals

        while len(cs) > base:
            f = cs[-1]
            try:
                gen = f.gen
                if gen is not None:
                    try:
                        q = next(gen)
                    except StopIteration:
                        cs.pop()
                        continue
                    cs.append(Frame(q.code, q.env))
                    continue

                code = f.code
                pc = f.pc
                if pc >= len(code):
                    cs.pop()
                    continue
                op, arg, _pos = code[pc]
                f.pc = pc + 1

                if op == OP_WORD:
                    # 1. 変数  2. ユーザー定義関数  3. 組み込み の順に探す
                    e = f.env
                    while e is not None:
                        vs = e.vars
                        if arg in vs:
                            push(vs[arg])
                            break
                        e = e.parent
                    else:
                        fn = functions.get(arg)
                        if fn is not None:
                            new = Frame(fn.code, Env(globals_env), fn.name, True)
                            if f.pc >= len(code):
                                cs.pop()          # 末尾呼び出し
                            elif len(cs) >= self.max_depth:
                                raise CremaError(
                                    f"call stack overflow (depth {self.max_depth})")
                            cs.append(new)
                            continue
                        b = builtins.get(arg)
                        if b is None:
                            raise CremaError(f"unknown word '{arg}'")
                        self.cur_frame = f
                        try:
                            new = b(self)
                        except (ReturnSignal, BreakSignal, UserError):
                            raise
                        except CremaError as err:
                            if not err.msg.startswith(arg + ": "):
                                err.msg = f"{arg}: {err.msg}"
                            raise
                        except Exception as exc:
                            err = self._convert_exception(exc)
                            err.msg = f"{arg}: {err.msg}"
                            raise err from exc
                        if new is not None:
                            if f.pc >= len(code) and cs[-1] is f:
                                cs.pop()          # 末尾呼び出し
                                new.is_func = new.is_func or f.is_func
                                new.name = new.name or f.name
                            cs.append(new)
                elif op == OP_PUSH:
                    push(arg)
                elif op == OP_QUOTE:
                    push(Quote(arg, f.env))
                elif op == OP_BIND:
                    if not stack:
                        raise CremaError(f"-> {arg}: stack underflow")
                    f.env.vars[arg] = stack.pop()
                elif op == OP_BINDN:
                    n = len(arg)
                    if len(stack) < n:
                        raise CremaError(
                            f"-> {{ {' '.join(arg)} }}: stack underflow")
                    vs = f.env.vars
                    vals = stack[-n:]
                    del stack[-n:]
                    for name, v in zip(arg, vals):
                        vs[name] = v
                elif op == OP_LBRACE:
                    self.marks.append(len(stack))
                elif op == OP_RBRACE:
                    m = self.marks.pop()
                    if m > len(stack):
                        raise CremaError("'}': stack underflow inside { ... }")
                    items = stack[m:]
                    del stack[m:]
                    push(items)

            except ReturnSignal:
                self._unwind_return(base)
            except BreakSignal:
                try:
                    self._unwind_break(base)
                except CremaError as err:
                    self._handle_error(err, base)
            except CremaError as err:
                self._handle_error(err, base)
            except RecursionError:
                self._handle_error(CremaError("data structure too deeply nested"), base)
            except ExitSignal:
                raise
            except Exception as exc:  # Python 側の例外を Crema のエラーに変換する
                self._handle_error(self._convert_exception(exc), base)

    # ------------------------------------------------------------------
    # 制御の巻き戻し

    def _unwind_return(self, base):
        cs = self.cs
        while len(cs) > base:
            fr = cs.pop()
            if fr.is_func:
                return

    def _unwind_break(self, base):
        cs = self.cs
        for i in range(len(cs) - 1, base - 1, -1):
            fr = cs[i]
            if fr.loop:
                del cs[i:]
                return
            if fr.is_func:
                break
        raise CremaError("break: not inside a loop")

    def _trace(self, base):
        trace = []
        for fr in reversed(self.cs[base:]):
            if fr.gen is None and fr.pc > 0:
                pos = fr.code[fr.pc - 1][2]
                trace.append((fr.name, pos))
        # 名前のないフレーム (クォート) は直近の関数名を引き継ぐ
        named = []
        for i, (name, pos) in enumerate(trace):
            if name is None:
                for later_name, _ in trace[i + 1:]:
                    if later_name is not None:
                        name = later_name
                        break
            named.append((name or "<main>", pos))
        return named

    def _handle_error(self, err, base):
        cs = self.cs
        if err.trace is None:
            err.trace = self._trace(base)
            if err.pos is None and err.trace:
                err.pos = err.trace[0][1]
        for i in range(len(cs) - 1, base - 1, -1):
            fr = cs[i]
            if fr.handler is not None:
                q, depth, mdepth = fr.handler
                del cs[i:]
                del self.stack[depth:]
                del self.marks[mdepth:]
                self.stack.append(err.msg)
                nf = Frame(q.code, q.env, fr.name, fr.is_func)
                cs.append(nf)
                return
        del cs[base:]
        self.marks.clear()
        raise err

    @staticmethod
    def _convert_exception(exc):
        if isinstance(exc, ZeroDivisionError):
            return CremaError("division by zero")
        if isinstance(exc, IndexError):
            return CremaError("index out of range")
        if isinstance(exc, KeyError):
            return CremaError(f"key not found: {exc.args[0]!r}")
        if isinstance(exc, FileNotFoundError):
            return CremaError(f"file not found: {exc.filename}")
        if isinstance(exc, OSError):
            msg = exc.strerror or str(exc)
            return CremaError(f"{msg}: {exc.filename}" if exc.filename else msg)
        if isinstance(exc, OverflowError):
            return CremaError("numeric overflow")
        return CremaError(f"{type(exc).__name__}: {exc}")


def format_error(err):
    """エラーメッセージとスタックトレースを人間向けに整形する。"""
    lines = []
    if err.pos:
        src, line = err.pos
        lines.append(f"{src}:{line}: error: {err.msg}")
    else:
        lines.append(f"error: {err.msg}")
    trace = err.trace or []
    for name, (src, line) in trace[:20]:
        lines.append(f"  in {name} ({src}:{line})")
    if len(trace) > 20:
        lines.append(f"  ... {len(trace) - 20} more frames")
    return "\n".join(lines)
