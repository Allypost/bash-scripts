from itertools import chain
from typing import TypeAlias, TypeVar

T = TypeVar("T")
Listish: TypeAlias = list[T] | tuple[T, ...]
MaybeList: TypeAlias = T | Listish[T]


def flatten(
    lst: MaybeList[Listish[T]],
) -> list[T]:
    if isinstance(lst, list) or isinstance(lst, tuple):
        return list(chain.from_iterable(flatten(x) for x in lst))  # type: ignore
    return [lst]
