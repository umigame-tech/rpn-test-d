"""コマンドラインインターフェース。

    crema FILE [ARGS...]     ファイルを実行する
    crema -e CODE [ARGS...]  コードを直接実行する
    crema -c FILE            構文チェックのみ行う
    crema -                  標準入力からプログラムを読んで実行する
    crema                    REPL を起動する
"""

import sys

from . import __version__
from .builtins import stack_str
from .errors import CremaError, ExitSignal, IncompleteInput
from .vm import VM, format_error

USAGE = """\
usage: crema [options] [FILE | -e CODE | -] [ARGS...]

Crema - a stack-based programming language in reverse Polish notation.

  crema FILE [ARGS...]     run a Crema program (ARGS are available via 'args')
  crema -e CODE [ARGS...]  run CODE given on the command line
  crema -c FILE            check syntax only
  crema -                  read the program from standard input
  crema                    start the interactive REPL

options:
  -h, --help               show this help and exit
  -v, --version            show version and exit
"""


def _run(vm, fn):
    """fn を実行し、終了コードを返す。"""
    try:
        fn()
    except ExitSignal as e:
        return e.code
    except CremaError as e:
        sys.stdout.flush()
        print(format_error(e), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv:
        if sys.stdin.isatty():
            return repl()
        argv = ["-"]

    opt = argv[0]
    if opt in ("-h", "--help"):
        print(USAGE, end="")
        return 0
    if opt in ("-v", "--version"):
        print(f"crema {__version__}")
        return 0
    if opt == "-e":
        if len(argv) < 2:
            print("crema: -e requires an argument", file=sys.stderr)
            return 2
        vm = VM(argv=argv[2:])
        return _run(vm, lambda: vm.run_source(argv[1], "<command-line>"))
    if opt == "-c":
        if len(argv) < 2:
            print("crema: -c requires a file", file=sys.stderr)
            return 2
        return check(argv[1])
    if opt == "-":
        vm = VM(argv=argv[1:], inp=_EmptyInput())
        src = sys.stdin.read()
        return _run(vm, lambda: vm.run_source(src, "<stdin>"))
    if opt.startswith("-") and len(opt) > 1:
        print(f"crema: unknown option {opt}\n", file=sys.stderr)
        print(USAGE, end="", file=sys.stderr)
        return 2

    vm = VM(argv=argv[1:])

    def go():
        try:
            vm.run_file(opt)
        except OSError as e:
            raise CremaError(f"cannot open {opt}: {e.strerror}")
    return _run(vm, go)


def check(path):
    from .parser import parse
    try:
        with open(path, encoding="utf-8") as f:
            parse(f.read(), path)
    except OSError as e:
        print(f"crema: cannot open {path}: {e.strerror}", file=sys.stderr)
        return 1
    except CremaError as e:
        print(format_error(e), file=sys.stderr)
        return 1
    print(f"{path}: OK")
    return 0


class _EmptyInput:
    """プログラム自体を標準入力から読んだときの read-line 用。"""

    def readline(self):
        return ""

    def read(self):
        return ""


def repl():
    try:
        import readline  # noqa: F401  (行編集と履歴を有効にする)
    except ImportError:
        pass
    vm = VM()
    print(f"Crema {__version__} REPL — type 'bye' or Ctrl-D to exit, '.s' shows the stack")
    buf = []
    while True:
        try:
            line = input("  ...> " if buf else "crema> ")
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print()
            buf = []
            continue
        if not buf and line.strip() == "bye":
            return 0
        buf.append(line)
        src = "\n".join(buf)
        try:
            code = vm.compile(src, "<repl>")
        except IncompleteInput:
            continue
        except CremaError as e:
            print(format_error(e), file=sys.stderr)
            buf = []
            continue
        buf = []
        try:
            vm.execute(code)
        except ExitSignal as e:
            return e.code
        except CremaError as e:
            print(format_error(e), file=sys.stderr)
        except KeyboardInterrupt:
            print("interrupted", file=sys.stderr)
        if vm.stack:
            print(stack_str(vm.stack))
