"""Crema: 逆ポーランド記法のスタック指向プログラミング言語。"""

__version__ = "0.1.0"

from .errors import CremaError  # noqa: E402
from .vm import VM  # noqa: E402

__all__ = ["VM", "CremaError", "__version__"]
