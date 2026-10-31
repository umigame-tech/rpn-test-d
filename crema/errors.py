"""Crema の例外と、制御フロー用のシグナル。"""


class CremaError(Exception):
    """Crema プログラムの実行時・構文エラー。"""

    def __init__(self, msg, pos=None):
        super().__init__(msg)
        self.msg = msg
        self.pos = pos          # (source, line) or None
        self.trace = None       # [(name, (source, line)), ...] 内側が先頭

    def __str__(self):
        return self.msg


class UserError(CremaError):
    """`error` ワードでプログラムが投げたエラー。"""


class ParseError(CremaError):
    pass


class IncompleteInput(ParseError):
    """入力が途中で終わっている (REPL で続きの行を待つために使う)。"""


class ReturnSignal(Exception):
    """`return` で関数から抜ける。"""


class BreakSignal(Exception):
    """`break` でループから抜ける。"""


class ExitSignal(BaseException):
    """`exit` でプログラムを終了する。"""

    def __init__(self, code):
        super().__init__(code)
        self.code = code
