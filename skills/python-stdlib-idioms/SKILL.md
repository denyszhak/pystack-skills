---
name: python-stdlib-idioms
description: |
  Use when iterating over collections, building lazy pipelines, or modeling tree /
  recursive structures (filesystems, ASTs, query builders, UI trees). Triggers on
  imports of `itertools`, `collections.abc`; on `for ... yield ...`, `__iter__`,
  generators; on tree-shaped data, leaf/composite distinctions, recursive
  traversal. Encodes: generators over hand-rolled iterators, `itertools` for
  composition, `AsyncIterator[T]` for async, `Protocol` + dataclass for tree
  shapes, recursive generators for traversal, `match` for visitor dispatch.
  Do NOT use for: type-system idioms (use python-typing-idioms); domain
  primitives (use python-value-objects); aggregates (use python-aggregate-and-repo).
---

# Stdlib idioms — iteration and tree composition

Two common-but-distinct Python data idioms that don't fit the typing-idioms or value-objects skills, bundled here because each on its own is too thin to be a standalone skill. Use the section that matches your task.

- **Iteration** — generators, `itertools`, lazy pipelines, async iteration
- **Tree composition** — modeling leaf/composite structures with `Protocol` + dataclass, recursive traversal

## When to use this skill

- Writing any `for ... in ...` loop
- Producing a sequence of values lazily
- Composing transformations on a stream
- Iterating async results from a DB query, HTTP stream, message queue
- Modeling a filesystem, expression tree, AST, UI tree
- Building a query DSL where conditions combine (`A AND (B OR C)`)
- Implementing the visitor pattern on a tree

---

## Part 1 — Iteration

The GoF Iterator pattern exists for languages without first-class iteration. Python has had the iterator protocol (`__iter__` / `__next__`), generators, and `itertools` since 2.2. There is almost never a reason to write a class with `__next__` by hand.

### 1. Generators over hand-rolled iterators

```python
# Good — three lines, all the iterator machinery is implicit
def line_numbers(lines: Iterable[str]) -> Iterator[tuple[int, str]]:
    for i, line in enumerate(lines, start=1):
        yield i, line

# Bad — implementing the protocol when generators would do it
class LineNumberIterator:
    def __init__(self, lines: Iterable[str]) -> None:
        self._lines = iter(lines)
        self._i = 0
    def __iter__(self) -> "LineNumberIterator":
        return self
    def __next__(self) -> tuple[int, str]:
        self._i += 1
        return self._i, next(self._lines)
```

Generators are the iterator protocol with the right defaults. `yield` makes a function pause and resume; the generator object handles `__iter__`, `__next__`, `StopIteration`, and `send`/`throw` for free.

### 2. `itertools` for stream composition

```python
from itertools import chain, groupby, islice, takewhile, pairwise

combined = chain(orders_today, orders_yesterday)     # concatenate lazily
first_100 = islice(big_iter, 100)                    # first 100 only
for status, group in groupby(orders, key=lambda o: o.status):
    print(status, list(group))                       # consecutive runs by key
```

Memorize: `chain`, `islice`, `takewhile`, `dropwhile`, `groupby`, `accumulate`, `pairwise`, `tee`. Composing them is usually faster *and* clearer than nested `for` loops with `if`s.

### 3. Lazy pipelines with generator expressions

```python
totals = (order.total for order in orders if order.status == "placed")
big = (t for t in totals if t > Decimal("1000"))
result = sum(big)
```

Each generator expression is a lazy stream. They compose by being passed to each other. Reach for `list(...)` only when you genuinely need a list (multiple passes, indexing, length).

### 4. Async iteration with `AsyncIterator[T]` and `async for`

```python
from collections.abc import AsyncIterator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def stream_orders(session: AsyncSession) -> AsyncIterator[Order]:
    stmt = select(Order)
    result = await session.stream_scalars(stmt)
    async for order in result:
        yield order


async for order in stream_orders(session):
    print(order.id)
```

`async def ... yield ...` makes an async generator. Use this for any production-sized result set — `stream_scalars` doesn't buffer everything in memory.

### 5. Type with `Iterable[T]` for inputs, `Iterator[T]` for outputs

```python
from collections.abc import Iterable, Iterator

def line_numbers(lines: Iterable[str]) -> Iterator[tuple[int, str]]:
    for i, line in enumerate(lines, start=1):
        yield i, line
```

`Iterable[T]` is widest (everything that supports `iter()`). Use it for parameters — be liberal in what you accept. `Iterator[T]` is what generators return — use it for return types. Avoid `list[T]` parameters when you only need to iterate; it forces callers to materialize.

For async: `AsyncIterable[T]` for input, `AsyncIterator[T]` for output.

### 6. Generator delegation with `yield from`

```python
def all_lines(files: list[Path]) -> Iterator[str]:
    for path in files:
        with path.open() as f:
            yield from f
```

`yield from` flattens nested iteration. Equivalent to `for line in f: yield line` but shorter and more efficient.

### 7. `next()` with a default

```python
first_active = next((u for u in users if u.is_active), None)
```

Clean for "find one or fall back" — no `try/except StopIteration`.

### 8. `__iter__` on your own class only when the class IS a collection

```python
from collections.abc import Iterator

class Inventory:
    def __init__(self) -> None:
        self._items: dict[ProductId, int] = {}

    def __iter__(self) -> Iterator[tuple[ProductId, int]]:
        return iter(self._items.items())

    def __len__(self) -> int:
        return len(self._items)
```

Fine to implement `__iter__` when iteration over the object's contents makes natural sense (`for product, qty in inventory:`). Don't write a class whose only purpose is `__next__` — use a generator function.

### When to break iteration rules

- For very deep recursion (10,000+ levels), Python's recursion limit will bite — use an explicit stack/queue.
- If you genuinely need multiple passes inside a function, accept `Sequence[T]` or `list[T]`.

---

## Part 2 — Tree composition

When data is recursive (filesystem, AST, query tree, UI hierarchy), the Pythonic shape is `Protocol` interface + dataclass leaves and composites. Same shape as the GoF Composite pattern, less ceremony.

### 1. `Protocol` for the shared interface

```python
from typing import Protocol


class FileSystemNode(Protocol):
    name: str

    def size(self) -> int: ...
    def display(self, indent: int = 0) -> None: ...
```

Every leaf and every composite has the same shape from the caller's perspective. `Protocol` types by shape — no inheritance required. A `File` and a `Directory` both satisfy `FileSystemNode` without sharing a base class.

### 2. Leaves are simple dataclasses

```python
from dataclasses import dataclass


@dataclass(slots=True, kw_only=True)
class File:
    name: str
    bytes: int

    def size(self) -> int:
        return self.bytes

    def display(self, indent: int = 0) -> None:
        print(" " * indent + f"📄 {self.name} ({self.bytes}B)")
```

No special "leaf" decoration. Just a class with the methods the Protocol requires.

### 3. Composites hold children and delegate

```python
@dataclass(slots=True, kw_only=True)
class Directory:
    name: str
    children: list[FileSystemNode]

    def size(self) -> int:
        return sum(child.size() for child in self.children)

    def display(self, indent: int = 0) -> None:
        print(" " * indent + f"📁 {self.name}/")
        for child in self.children:
            child.display(indent + 2)
```

The composite's methods recursively delegate to children. Callers don't know or care whether they're holding a `File` or a `Directory` — they just call `node.size()`.

### 4. Recursive traversal as a separate generator

```python
from collections.abc import Iterator


def walk(node: FileSystemNode) -> Iterator[FileSystemNode]:
    yield node
    if isinstance(node, Directory):
        for child in node.children:
            yield from walk(child)
```

Don't put traversal on every leaf as a no-op. Walk is a free function (or lives with the composite). Use generators — lazy, composable, cheap.

### 5. Operations on the whole tree go on the composite, not the leaf

```python
@dataclass(slots=True, kw_only=True)
class Directory:
    ...
    def find_by_name(self, name: str) -> FileSystemNode | None:
        for node in walk(self):
            if node.name == name:
                return node
        return None
```

`find_by_name` only makes sense on a directory (a tree root). Don't push it to the Protocol; not every leaf needs it.

### 6. Use PEP 695 generics if the tree has typed payloads

```python
@dataclass(slots=True, kw_only=True)
class Leaf[T]:
    value: T


@dataclass(slots=True, kw_only=True)
class Node[T]:
    children: list["Leaf[T] | Node[T]"]

    def values(self) -> Iterator[T]:
        for child in self.children:
            if isinstance(child, Leaf):
                yield child.value
            else:
                yield from child.values()
```

Generic composites are useful for expression trees over typed values (`Tree[int]`, `Tree[Expr]`).

### 7. Use `field(default_factory=list)`, not `[]`, for mutable defaults

```python
@dataclass
class Leaf:
    tags: list[str] = field(default_factory=list)   # not = []
```

Dataclasses catch the mutable-default case, but the lesson generalizes.

### 8. Visitor pattern: a function with `match` per node type

```python
def to_html(node: FileSystemNode) -> str:
    match node:
        case File(name=name):
            return f"<a>{name}</a>"
        case Directory(name=name, children=children):
            inner = "".join(to_html(c) for c in children)
            return f"<ul><li>{name}{inner}</li></ul>"
```

`match` on dataclasses is the modern visitor: exhaustiveness checking, clean syntax, no `accept(visitor)` ceremony.

### When to break tree-composition rules

- **`Protocol` vs `ABC`** — use `ABC` if you need shared method implementations across all node types (rare for trees).
- **Recursive method calls** — for deep trees (10,000+ levels), use an explicit stack/queue, not recursion.
- **For DAGs (multi-parent), use a visited set** — `walk` with cycle protection. `set[id(node)]` is fine for unhashable nodes.

---

## Anti-patterns these displaces

- **GoF Iterator class** — a class with `__iter__` returning `self` and `__next__` doing the work, when a generator function would have produced the same iterator in three lines.
- **List comprehensions where generators would do** — `[t for t in totals if t > 1000]` builds a full list before consuming. Use `(t for t in totals if t > 1000)` if you only need to iterate / sum / pass through.
- **Abstract `Component` class with `add_child` / `remove_child` on every node** — the GoF approach. Leaves don't need those methods; making the interface include them sacrifices type safety for false symmetry.
- **`isinstance` checks scattered through the codebase** — dispatch with `match` or pull behavior up to the Protocol.

## See also

- `python-typing-idioms` — `Protocol`, PEP 695 generics, `Iterable[T]`, `AsyncIterator[T]`
- `python-aggregate-and-repo` — `AsyncIterator[T]` return types on repo methods
- `python-antipatterns-cheatsheet` — GoF Iterator / Visitor / Abstract Factory redirects
