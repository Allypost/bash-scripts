from typing import List, Tuple, TypeVar, Union

T = TypeVar("T")
Listish = List[T] | Tuple[T]
MaybeList = T | Listish[T]


def flatten(l: MaybeList[T] | Listish[MaybeList[T]]) -> List[T]:
    if l == []:
        return l
    if isinstance(l[0], list):
        return flatten(l[0]) + flatten(l[1:])
    return l[:1] + flatten(l[1:])
