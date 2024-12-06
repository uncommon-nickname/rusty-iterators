from __future__ import annotations

import itertools
from collections.abc import Callable
from typing import Iterator, Protocol, Self, Sequence, final, override

from .option import NoValue, Value

type Option[T] = Value[T] | NoValue
type EnumerateItem[T] = tuple[int, T]


class IterInterface[T](Protocol):
    def advance_by(self, n: int) -> Self:
        if n < 0:
            raise ValueError("Amount to advance by must be greater or equal to 0.")
        for _ in range(n):
            # We can ignore some iterations if iterator is depleted.
            if not self.next().exists:
                break
        return self

    def collect(self) -> list[T]:
        result = []
        while (item := self.next()).exists:
            result.append(item.value)
        return result

    def copy(self) -> IterInterface[T]:
        raise NotImplementedError

    def count(self) -> int:
        ctr = 0
        while self.next().exists:
            ctr += 1
        return ctr

    def cycle(self) -> Cycle[T]:
        return Cycle(self)

    def enumerate(self) -> Enumerate[T]:
        return Enumerate(self)

    def last(self) -> Option[T]:
        last: Option[T] = NoValue()
        while (curr := self.next()).exists:
            last = curr
        return last

    def map[R](self, f: Callable[[T], R]) -> Map[T, R]:
        return Map(self, f)

    def next(self) -> Option[T]:
        raise NotImplementedError

    def nth(self, n: int) -> Option[T]:
        if n < 0:
            raise ValueError("Nth index must be greater or equal to 0.")
        for _ in range(n):
            # We can ignore some iterations if iterator is depleted.
            if not (item := self.next()).exists:
                return item
        return self.next()

    def filter(self, f: Callable[[T], bool]) -> Filter[T]:
        return Filter(self, f)


@final
class Iter[T](IterInterface[T]):
    def __init__(self, gen: Iterator[T]) -> None:
        self.gen = gen

    @classmethod
    def from_items(cls, *items: T) -> Self:
        return cls(item for item in items)

    @classmethod
    def from_iterable(cls, iter: Sequence[T]) -> Self:
        return cls(item for item in iter)

    @override
    def copy(self) -> Iter[T]:
        # Generators in python are a simple wrappers around stack frames
        # and Python interface does not really have a way to copy a
        # stack frame. It is theoretically possible from CPython level,
        # but it is not currently supported from Python interface. As a
        # workaround we can rebuild both the original and copied
        # iterators from ground up.
        self.gen, new_copy = itertools.tee(self.gen)
        return Iter(new_copy)

    @override
    def next(self) -> Option[T]:
        try:
            return Value(next(self.gen))
        except StopIteration:
            return NoValue()


@final
class Map[T, R](IterInterface[R]):
    def __init__(self, iter: IterInterface[T], f: Callable[[T], R]) -> None:
        self.iter = iter
        self.f = f

    @override
    def copy(self) -> Map[T, R]:
        # We can reuse a function pointer, no need to create a copy.
        return Map(self.iter.copy(), self.f)

    @override
    def count(self) -> int:
        # Map doesn't influence the iterator size. We consume the
        # iterator anyway, so we can avoid unnecessary computation
        # by skipping the map evaluation and using the underlying
        # iterator directly.
        return self.iter.count()

    @override
    def next(self) -> Option[R]:
        if (item := self.iter.next()).exists:
            return Value(self.f(item.value))
        return item


@final
class Filter[T](IterInterface[T]):
    def __init__(self, iter: IterInterface[T], f: Callable[[T], bool]) -> None:
        self.iter = iter
        self.f = f

    @override
    def copy(self) -> Filter[T]:
        # We can reuse a function pointer, no need to create a copy.
        return Filter(self.iter.copy(), self.f)

    @override
    def next(self) -> Option[T]:
        while (item := self.iter.next()).exists:
            if self.f(item.value):
                return item
        return item


@final
class Cycle[T](IterInterface[T]):
    def __init__(self, iter: IterInterface[T]) -> None:
        self.orig = iter
        self.iter = iter.copy()

    @override
    def copy(self) -> Cycle[T]:
        return Cycle(self.iter.copy())

    @override
    def next(self) -> Option[T]:
        if (item := self.iter.next()).exists:
            return item
        self.iter = self.orig.copy()
        return self.iter.next()


@final
class Enumerate[T](IterInterface[EnumerateItem[T]]):
    def __init__(self, iter: IterInterface[T]) -> None:
        self.iter = iter
        self.curr_item = 0

    @override
    def copy(self) -> Enumerate[T]:
        return Enumerate(self.iter.copy())

    @override
    def count(self) -> int:
        return self.iter.count()

    @override
    def next(self) -> Option[EnumerateItem[T]]:
        if (item := self.iter.next()).exists:
            result = (self.curr_item, item.value)
            self.curr_item += 1
            return Value(result)
        return item

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> EnumerateItem[T]:
        if (item := self.next()).exists:
            return item.value
        raise StopIteration
