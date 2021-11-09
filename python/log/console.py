import sys
from typing import Generator, Iterable, TypeVar


T = TypeVar("T")


def flatten(coll: Iterable[T]) -> Generator[T, None, None]:
    for i in coll:
        if isinstance(i, Iterable) and not isinstance(i, str):
            for subc in flatten(i):
                yield subc
        else:
            yield i


class Chalk:
    bg_blue_bright = '104m'
    bg_yellow_bright = '103m'
    bg_red = '41m'
    bg_green = '42m'

    dim = '2m'
    black = '30m'
    white = '37m'

    bold = '1m'
    italic = '3m'

    @staticmethod
    def esc(string):
        return f'\x1B[{string}'

    @staticmethod
    def badge(text: str, *colours: list[str]) -> str:
        return f"{Chalk.colour(colours)} {text} {Chalk.esc('0m')}"

    @staticmethod
    def colour(*colours: list[str]) -> str:
        return ''.join([Chalk.esc(c) for c in flatten(colours)])


class Console:
    @staticmethod
    def write(*text):
        out = ''.join(text)
        sys.stdout.write(out)
        return out

    @staticmethod
    def esc(string):
        return f'\x1B[{string}'

    @staticmethod
    def move_up(lines):
        return Console.write(Console.esc(f'{lines}A'), '\r')

    @staticmethod
    def _clear_line():
        return Console.esc('K')

    @staticmethod
    def clear_line():
        return Console.write(Console._clear_line())

    @staticmethod
    def log(*text):
        return Console.write(
            Console._clear_line(),
            *text,
            '\r\n',
        )

    @staticmethod
    def log_and_return(text):
        lines = str(text).split("\n")
        lines_written = len(lines)
        for line in lines:
            Console.log(line)
        Console.move_up(lines_written)

    @staticmethod
    def dim(text: str) -> str:
        return Chalk.colour(Chalk.italic, Chalk.dim) + text + Console.esc("0m")

    @staticmethod
    def log_dim(text: str, *, return_line: bool = False) -> str:
        t = Console.dim(text)

        if return_line:
            return Console.log_and_return(t)
        else:
            return Console.log(t)

    @staticmethod
    def log_error(*text: list[str]) -> str:
        return Console.log(
            Chalk.badge('✘', Chalk.bold, Chalk.white, Chalk.bg_red),
            " ",
            *text
        )

    @staticmethod
    def log_success(*text: str) -> str:
        return Console.log(
            Chalk.badge('✔', Chalk.bold, Chalk.white, Chalk.bg_green),
            " ",
            *text
        )
