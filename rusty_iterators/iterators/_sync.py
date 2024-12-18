from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional, Self, final, overload, override

from ._async import AIter
from ._shared import CopyIterInterface

if TYPE_CHECKING:
    from ._types import (
        FilterCallable,
        FilterMapCallable,
        ForEachCallable,
        InspectCallable,
        MapCallable,
        StandardIterable,
        StandardIterableClass,
    )

type EnumerateItem[T] = tuple[int, T]


class IterInterface[T](CopyIterInterface, ABC):
    """An interface that every iterator should implement.

    Provides a lot of default implementations, that should be correct
    in most of the custom iterators. Implements an interface allowing
    for Python iterations and most of the Rust stdlib methods.
    """

    __slots__ = ()

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> T:
        return self.next()

    @override
    def __repr__(self) -> str:
        return self.__str__()

    @abstractmethod
    def next(self) -> T:
        raise NotImplementedError

    def advance_by(self, n: int) -> Self:
        if n < 0:
            raise ValueError("Amount to advance by must be greater or equal to 0.")
        for _ in range(n):
            try:
                self.next()
            except StopIteration:
                break
        return self

    def all(self) -> bool:
        return all(self)

    def any(self) -> bool:
        return any(self)

    def as_async(self) -> AIter[T]:
        return AIter(self)

    def chain(self, other: IterInterface[T]) -> Chain[T]:
        return Chain(self, other)

    def collect(self) -> list[T]:
        return list(self)

    @overload
    def collect_into(self, factory: type[list[T]]) -> list[T]: ...
    @overload
    def collect_into(self, factory: type[tuple[T, ...]]) -> tuple[T, ...]: ...
    @overload
    def collect_into(self, factory: type[set[T]]) -> set[T]: ...
    @overload
    def collect_into(self, factory: type[frozenset[T]]) -> frozenset[T]: ...

    def collect_into(self, factory: StandardIterableClass[T]) -> StandardIterable[T]:
        return factory(self)

    def count(self) -> int:
        ctr = 0
        for _ in self:
            ctr += 1
        return ctr

    def cycle(self) -> CycleCached[T] | CycleCopy[T]:
        return CycleCopy(self) if self.can_be_copied() else CycleCached(self)

    def enumerate(self) -> Enumerate[T]:
        return Enumerate(self)

    def filter(self, f: FilterCallable[T]) -> Filter[T]:
        return Filter(self, f)

    def filter_map[R](self, f: FilterMapCallable[T, R]) -> FilterMap[T, R]:
        return FilterMap(self, f)

    def for_each(self, f: ForEachCallable[T]) -> None:
        for item in self:
            f(item)

    def inspect(self, f: Optional[InspectCallable[T]] = None) -> Inspect[T]:
        return Inspect(self, f)

    def last(self) -> T:
        last = self.next()
        for item in self:
            last = item
        return last

    def map[R](self, f: MapCallable[T, R]) -> Map[T, R]:
        return Map(self, f)

    def nth(self, n: int) -> T:
        return self.advance_by(n).next()

    def step_by(self, step_size: int) -> StepBy[T]:
        return StepBy(self, step_size)

    def take(self, size: int) -> Take[T]:
        return Take(self, size)

    def try_sum(self) -> T:
        summed = self.next()
        for item in self:
            # I don't know how to statically ensure that this will work.
            summed += item  # type: ignore[operator]
        return summed

    def windows(self, size: int) -> Windows[T]:
        return Windows(self, size)


@final
class CycleCached[T](IterInterface[T]):
    """An iterator allowing user infinitely cycle over iterator values.

    Keeps a cache of original elements and uses it when original iter
    is depleted.

    Attributes:
        cache: An array of pointers to elements that were cosumed from
            the original iterator.
        it: An original iterator that cycle is going to use to create
            the cache and reuse its' items.
        ptr: A pointer used to retrieve the elements from the cache.
            Initialized by the first element - `0`.
    """

    __slots__ = ("cache", "it", "ptr", "use_cache")

    def __init__(self, it: IterInterface[T]) -> None:
        self.cache: list[T] = []
        self.it = it
        self.ptr = 0
        self.use_cache = False

    @override
    def __str__(self) -> str:
        return f"CycleCached(ptr={self.ptr}, cache={len(self.cache)}, it={self.it})"

    @override
    def can_be_copied(self) -> bool:
        return self.it.can_be_copied()

    @override
    def copy(self) -> CycleCached[T]:
        obj = CycleCached(self.it.copy())
        obj.cache = self.cache
        obj.ptr = self.ptr
        obj.use_cache = self.use_cache
        return obj

    @override
    def next(self) -> T:
        if self.use_cache:
            self.ptr = self.ptr % len(self.cache)
            item = self.cache[self.ptr]
            self.ptr += 1
            return item
        try:
            item = self.it.next()
            self.cache.append(item)
            return item
        except StopIteration:
            self.use_cache = True
            return self.next()


@final
class CycleCopy[T](IterInterface[T]):
    """An iterator allowing user infinitely cycle over iterator values.

    Keeps a reference to the original iterator with its' original state
    and copies it when cycle is completed to start over.

    Attributes:
        it: A current copy of the original iterator that is being used
            to consume the current cycle.
        orig: An original iterator that cycle is going to use to create
            copies when one cycle is completed.
    """

    __slots__ = ("it", "orig")

    def __init__(self, it: IterInterface[T]) -> None:
        self.it = it.copy()
        self.orig = it

    @override
    def __str__(self) -> str:
        return f"CycleCopy(it={self.it}, orig={self.orig})"

    @override
    def can_be_copied(self) -> bool:
        return self.it.can_be_copied()

    @override
    def copy(self) -> CycleCopy[T]:
        obj = CycleCopy(self.it.copy())
        obj.orig = self.orig.copy()
        return obj

    @override
    def next(self) -> T:
        try:
            return self.it.next()
        except StopIteration:
            self.it = self.orig.copy()
            return self.it.next()


@final
class Chain[T](IterInterface[T]):
    """An iterator allowing user to chain two iterators.

    Depletes a first iterator and then depletes the second.

    Attributes:
        first: The preceding iterator that should be evaluated before the
            next iterator is used.
        second: A second iterator used when first one is depleted.
        use_second: A flag used to determine which iterator should be
            used when `next()` is called.
    """

    __slots__ = ("first", "second", "use_second")

    def __init__(self, first: IterInterface[T], second: IterInterface[T]) -> None:
        self.first = first
        self.second = second
        self.use_second = False

    @override
    def __str__(self) -> str:
        return f"Chain(use_second={self.use_second}, first={self.first}, second={self.second})"

    @override
    def can_be_copied(self) -> bool:
        return self.first.can_be_copied() and self.second.can_be_copied()

    @override
    def copy(self) -> Chain[T]:
        obj = Chain(self.first.copy(), self.second.copy())
        obj.use_second = self.use_second
        return obj

    @override
    def next(self) -> T:
        if self.use_second:
            return self.second.next()
        try:
            return self.first.next()
        except StopIteration:
            self.use_second = True
            return self.next()


@final
class Enumerate[T](IterInterface[EnumerateItem[T]]):
    """An iterator calculating and returning the amount of yielded items.

    Attributes:
        curr_idx: Keeps track of the amount of yielded items.
        it: The preceding iterator that should be evaluated before the
            enumeration is applied.
    """

    __slots__ = ("curr_idx", "it")

    def __init__(self, it: IterInterface[T]) -> None:
        self.curr_idx = 0
        self.it = it

    @override
    def __str__(self) -> str:
        return f"Enumerate(curr_idx={self.curr_idx}, it={self.it})"

    @override
    def can_be_copied(self) -> bool:
        return self.it.can_be_copied()

    @override
    def copy(self) -> Enumerate[T]:
        obj = Enumerate(self.it.copy())
        obj.curr_idx = self.curr_idx
        return obj

    @override
    def count(self) -> int:
        return self.it.count()

    @override
    def next(self) -> EnumerateItem[T]:
        item = self.it.next()
        result = (self.curr_idx, item)
        self.curr_idx += 1
        return result


@final
class Filter[T](IterInterface[T]):
    """A filtering iterator, yields only items that fit the requirements.

    Modifies the content of the iterator, not elements themselves.

    Attributes:
        f: A callable taking one argument of type `T` and returning a
            boolean informing wether the item is valid.
        it: The preceding iterator that should be evaluated before the
            filter is applied.
    """

    __slots__ = ("f", "it")

    def __init__(self, it: IterInterface[T], f: FilterCallable[T]) -> None:
        self.f = f
        self.it = it

    @override
    def __str__(self) -> str:
        return f"Filter(it={self.it})"

    @override
    def can_be_copied(self) -> bool:
        return self.it.can_be_copied()

    @override
    def copy(self) -> Filter[T]:
        return Filter(self.it.copy(), self.f)

    @override
    def next(self) -> T:
        while True:
            if self.f(item := self.it.next()):
                return item


@final
class FilterMap[T, R](IterInterface[R]):
    """An iterator combining filter and map for simpler interface.

    Attributes:
        f: A callable taking one argument of type `T` and returning a
            `Maybe[R]` which is used to deduce if value fits the filter
            or it should be ignored.
        it: The preceding iterator that should be evaluated before the
            filter map is applied.
    """

    __slots__ = ("f", "it")

    def __init__(self, it: IterInterface[T], f: FilterMapCallable[T, R]) -> None:
        self.f = f
        self.it = it

    @override
    def __str__(self) -> str:
        return f"FilterMap(it={self.it})"

    @override
    def can_be_copied(self) -> bool:
        return self.it.can_be_copied()

    @override
    def copy(self) -> FilterMap[T, R]:
        return FilterMap(self.it.copy(), self.f)

    @override
    def next(self) -> R:
        while True:
            if (item := self.f(self.it.next())).exists:
                return item.value


@final
class Inspect[T](IterInterface[T]):
    """An iterator allowing user to inject something between other iterators.

    Mainly should be used for debugging, does not implement any iteration
    skipping logic, to ensure that user has access to items in correct
    order of execution. If you want to call a function on every element
    and need perf, use `for_each`.

    Attributes:
        f: A callable injected into every `next()` call. Should return
            nothing and shouldn't change the item.
        it: The preceding iterator that should be evaluated before the
            inspect callable is applied.
    """

    __slots__ = ("f", "it")

    def __init__(self, it: IterInterface[T], f: Optional[InspectCallable[T]] = None) -> None:
        self.f = f or (lambda x: print(f"{self} -> {type(x)}: {x}", flush=True))
        self.it = it

    @override
    def __str__(self) -> str:
        return f"Inspect(it={self.it})"

    @override
    def can_be_copied(self) -> bool:
        return self.it.can_be_copied()

    @override
    def copy(self) -> Inspect[T]:
        return Inspect(self.it.copy(), self.f)

    @override
    def next(self) -> T:
        item = self.it.next()
        self.f(item)
        return item


@final
class Map[T, R](IterInterface[R]):
    """A mapping iterator, applying changes to the iterator elements.

    Modifies the elements, but not the size of the iterator itself.

    Attributes:
        f: A callable taking one argument of type `T` and returning value
            of type `R` used to modify the iterator elements.
        it: The preceding iterator that should be evaluated before the
            map is applied.
    """

    __slots__ = ("f", "it")

    def __init__(self, it: IterInterface[T], f: MapCallable[T, R]) -> None:
        self.f = f
        self.it = it

    @override
    def __str__(self) -> str:
        return f"Map(it={self.it})"

    @override
    def can_be_copied(self) -> bool:
        return self.it.can_be_copied()

    @override
    def copy(self) -> Map[T, R]:
        return Map(self.it.copy(), self.f)

    @override
    def count(self) -> int:
        return self.it.count()

    @override
    def next(self) -> R:
        return self.f(self.it.next())


@final
class StepBy[T](IterInterface[T]):
    """An iterator allowing user to take every nth item.

    Always starts by returning the first item of the preceding iterator.

    Attributes:
        first_take: A boolean indicating if initial element was already
            taken out of the underlying iterator.
        it: The preceding iterator that should be evaluated before the
            step is calculated.
        step_minus_one: Amount of items that we have to skip to get the
            correct item in the next call.
    """

    __slots__ = ("first_take", "it", "step_minus_one")

    def __init__(self, it: IterInterface[T], step_size: int) -> None:
        if step_size <= 0:
            raise ValueError("Step size has to be greater than 0.")

        self.first_take = True
        self.it = it
        self.step_minus_one = step_size - 1

    @override
    def __str__(self) -> str:
        return f"StepBy(first_take={self.first_take}, step_size={self.step_minus_one + 1}, it={self.it})"

    @override
    def can_be_copied(self) -> bool:
        return self.it.can_be_copied()

    @override
    def copy(self) -> StepBy[T]:
        obj = StepBy(self.it.copy(), self.step_minus_one + 1)
        obj.first_take = self.first_take
        return obj

    @override
    def next(self) -> T:
        if not self.first_take:
            for _ in range(self.step_minus_one):
                self.it.next()
        else:
            self.first_take = False

        return self.it.next()


@final
class Take[T](IterInterface[T]):
    """An iterator allowing user to limit iterator size.

    Returns items from preceding iterator until the limit is hit.

    Attributes:
        it: The preceding iterator that should be evaluated before the
            take iterator is depleted.
        size: An amount of elements that will be taken out of the preceding
            iterator before end.
        take: An amount of items that were already consumed.
    """

    __slots__ = ("it", "size", "taken")

    def __init__(self, it: IterInterface[T], size: int) -> None:
        self.it = it
        self.size = size
        self.taken = 0

    @override
    def __str__(self) -> str:
        return f"Take(size={self.size}, taken={self.taken}, it={self.it})"

    @override
    def can_be_copied(self) -> bool:
        return self.it.can_be_copied()

    @override
    def copy(self) -> Take[T]:
        obj = Take(self.it.copy(), self.size)
        obj.taken = self.taken
        return obj

    @override
    def next(self) -> T:
        if self.taken == self.size:
            raise StopIteration
        item = self.it.next()
        self.taken += 1
        return item


@final
class Windows[T](IterInterface[list[T]]):
    """An iterator returning windows of n element size.

    Attributes:
        it: An original iterator that will be consumed to create windows.
        cache: A circular buffer cache, used to store elements returned
            by the future windows.
        size: A size of the window.
        ptr: A current position in the cache.
    """

    __slots__ = ("cache", "it", "ptr", "size")

    def __init__(self, it: IterInterface[T], size: int) -> None:
        self.it = it
        self.size = size
        self.cache: list[T] = []
        self.ptr = 0

    @override
    def __str__(self) -> str:
        return f"Windows(size={self.size}, cache={self.cache}, it={self.it})"

    @override
    def can_be_copied(self) -> bool:
        return self.it.can_be_copied()

    @override
    def copy(self) -> Windows[T]:
        obj = Windows(self.it.copy(), self.size)
        obj.cache = self.cache[::]
        obj.ptr = self.ptr
        return obj

    @override
    def count(self) -> int:
        # Windows always return the original count without the last
        # element. We can skip running more costly `.next()`.
        return max(0, self.it.count() - 1)

    @override
    def next(self) -> list[T]:
        if len(self.cache) == self.size:
            self.ptr = self.ptr % self.size
            self.cache[self.ptr] = self.it.next()
            self.ptr += 1

            result = []
            for _ in range(self.size):
                self.ptr = self.ptr % self.size
                result.append(self.cache[self.ptr])
                self.ptr += 1
            return result

        for _ in range(self.size):
            self.cache.append(self.it.next())
        return self.cache[::]
