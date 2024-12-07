from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Protocol, Self, final, overload, override

from rusty_iterators.maybe import Maybe, NoValue, Value

if TYPE_CHECKING:
    from collections.abc import Callable

    type FilterCallable[T] = Callable[[T], bool]
    type MapCallable[T, R] = Callable[[T], R]
    type FilterMapCallable[T, R] = Callable[[T], Maybe[R]]
    type ForEachCallable[T] = Callable[[T], None]
    type InspectCallable[T] = ForEachCallable[T]

    type StandardIterable[T] = list[T] | tuple[T, ...] | set[T] | frozenset[T]
    type StandardIterableClass[T] = type[StandardIterable[T]]

# This type is needed in runtime for generic inheritance.
type EnumerateItem[T] = tuple[int, T]


class IterInterface[T](Protocol):
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

    def advance_by(self, n: int) -> Self:
        if n < 0:
            raise ValueError("Amount to advance by must be greater or equal to 0.")
        for _ in range(n):
            try:
                self.next()
            except StopIteration:
                break
        return self

    def chain(self, other: IterInterface[T]) -> Chain[T]:
        return Chain(self, other)

    def collect(self) -> list[T]:
        return [item for item in self]

    @overload
    def collect_into(self, factory: type[list[T]]) -> list[T]: ...
    @overload
    def collect_into(self, factory: type[tuple[T, ...]]) -> tuple[T, ...]: ...
    @overload
    def collect_into(self, factory: type[set[T]]) -> set[T]: ...
    @overload
    def collect_into(self, factory: type[frozenset[T]]) -> frozenset[T]: ...

    def collect_into(self, factory: StandardIterableClass[T]) -> StandardIterable[T]:
        return factory(item for item in self)

    def count(self) -> int:
        ctr = 0
        for _ in self:
            ctr += 1
        return ctr

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

    def last(self) -> Maybe[T]:
        last: Maybe[T] = NoValue()
        for item in self:
            last = Value(item)
        return last

    def map[R](self, f: MapCallable[T, R]) -> Map[T, R]:
        return Map(self, f)

    def next(self) -> T:
        raise NotImplementedError

    def nth(self, n: int) -> Maybe[T]:
        try:
            return Value(self.advance_by(n).next())
        except StopIteration:
            return NoValue()

    def step_by(self, step_size: int) -> StepBy[T]:
        return StepBy(self, step_size)

    def take(self, size: int) -> Take[T]:
        return Take(self, size)


@final
class Map[T, R](IterInterface[R]):
    """A mapping iterator, applying changes to the iterator elements.

    Modifies the elements, but not the size of the iterator itself.

    Attributes:
        f: A callable taking one argument of type `T` and returning value
            of type `R` used to modify the iterator elements.
        iter: The preceding iterator that should be evaluated before the
            map is applied.
    """

    __slots__ = ("f", "iter")

    def __init__(self, iter: IterInterface[T], f: MapCallable[T, R]) -> None:
        self.f = f
        self.iter = iter

    @override
    def __str__(self) -> str:
        return f"Map(id={id(self)}, iter={self.iter})"

    @override
    def count(self) -> int:
        return self.iter.count()

    @override
    def next(self) -> R:
        return self.f(self.iter.next())


@final
class Filter[T](IterInterface[T]):
    """A filtering iterator, yields only items that fit the requirements.

    Modifies the content of the iterator, not elements themselves.

    Attributes:
        f: A callable taking one argument of type `T` and returning a
            boolean informing wether the item is valid.
        iter: The preceding iterator that should be evaluated before the
            filter is applied.
    """

    __slots__ = ("f", "iter")

    def __init__(self, iter: IterInterface[T], f: FilterCallable[T]) -> None:
        self.f = f
        self.iter = iter

    @override
    def __str__(self) -> str:
        return f"Filter(id={id(self)}, iter={self.iter})"

    @override
    def next(self) -> T:
        while True:
            if self.f(item := self.iter.next()):
                return item


@final
class Enumerate[T](IterInterface[EnumerateItem[T]]):
    """An iterator calculating and returning the amount of yielded items.

    Attributes:
        curr_idx: Keeps track of the amount of yielded items.
        iter: The preceding iterator that should be evaluated before the
            enumeration is applied.
    """

    __slots__ = ("curr_idx", "iter")

    def __init__(self, iter: IterInterface[T]) -> None:
        self.curr_idx = 0
        self.iter = iter

    @override
    def __str__(self) -> str:
        return f"Enumerate(id={id(self)}, curr_idx={self.curr_idx}, iter={self.iter})"

    @override
    def count(self) -> int:
        return self.iter.count()

    @override
    def next(self) -> EnumerateItem[T]:
        item = self.iter.next()
        result = (self.curr_idx, item)
        self.curr_idx += 1
        return result


@final
class FilterMap[T, R](IterInterface[R]):
    """An iterator combining filter and map for simpler interface.

    Attributes:
        f: A callable taking one argument of type `T` and returning a
            `Maybe[R]` which is used to deduce if value fits the filter
            or it should be ignored.
        iter: The preceding iterator that should be evaluated before the
            filter map is applied.
    """

    __slots__ = ("f", "iter")

    def __init__(self, iter: IterInterface[T], f: FilterMapCallable[T, R]) -> None:
        self.f = f
        self.iter = iter

    @override
    def __str__(self) -> str:
        return f"FilterMap(id={id(self)}, iter={self.iter})"

    @override
    def next(self) -> R:
        while True:
            if (item := self.f(self.iter.next())).exists:
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
        iter: The preceding iterator that should be evaluated before the
            inspect callable is applied.
    """

    __slots__ = ("f", "iter")

    def __init__(self, iter: IterInterface[T], f: Optional[InspectCallable[T]] = None) -> None:
        self.f = f or (lambda x: print(f"{self} -> {type(x)} {x}", flush=True))
        self.iter = iter

    @override
    def __str__(self) -> str:
        return f"Inspect(id={id(self)}, on={self.iter})"

    @override
    def next(self) -> T:
        item = self.iter.next()
        self.f(item)
        return item


@final
class StepBy[T](IterInterface[T]):
    """An iterator allowing user to take every nth item.

    Always starts by returning the first item of the preceding iterator.

    Attributes:
        first_take: A boolean indicating if initial element was already
            taken out of the underlying iterator.
        iter: The preceding iterator that should be evaluated before the
            step is calculated.
        step_minus_one: Amount of items that we have to skip to get the
            correct item in the next call.
    """

    __slots__ = ("first_take", "iter", "step_minus_one")

    def __init__(self, iter: IterInterface[T], step_size: int) -> None:
        if step_size <= 0:
            raise ValueError("Step size has to be greater than 0.")

        self.first_take = True
        self.iter = iter
        self.step_minus_one = step_size - 1

    @override
    def __str__(self) -> str:
        return f"StepBy(id={id(self)}, step_size={self.step_minus_one + 1}, iter={self.iter})"

    @override
    def next(self) -> T:
        if not self.first_take:
            for _ in range(self.step_minus_one):
                self.iter.next()
        else:
            self.first_take = False

        return self.iter.next()


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
        return f"Chain(id={id(self)}, first={self.first}, second={self.second})"

    @override
    def next(self) -> T:
        if self.use_second:
            return self.second.next()
        try:
            return self.first.next()
        except StopIteration:
            self.use_second = True
            return self.second.next()


@final
class Take[T](IterInterface[T]):
    """An iterator allowing user to limit iterator size.

    Returns items from preceding iterator until the limit is hit.

    Attributes:
        iter: The preceding iterator that should be evaluated before the
            take iterator is depleted.
        size: An amount of elements that will be taken out of the preceding
            iterator before end.
        take: An amount of items that were already consumed.
    """

    __slots__ = ("iter", "size", "taken")

    def __init__(self, iter: IterInterface[T], size: int) -> None:
        self.iter = iter
        self.size = size
        self.taken = 0

    @override
    def __str__(self) -> str:
        return f"Take(id={id(self)}, size={self.size}, taken={self.taken}, iter={self.iter})"

    @override
    def next(self) -> T:
        if self.taken == self.size:
            raise StopIteration
        item = self.iter.next()
        self.taken += 1
        return item
