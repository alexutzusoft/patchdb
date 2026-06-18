"""Query and Condition builders for PatchDB."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Tuple


class Query:
    """Builder for document paths to construct query conditions."""

    def __init__(self, path: Tuple[Any, ...] = ()) -> None:
        """Initialize Query with a path tuple."""
        self.path = path

    def __getattr__(self, name: str) -> Query:
        """Access subfield on the document path via attribute access."""
        return Query(self.path + (name,))

    def __getitem__(self, name: Any) -> Query:
        """Access subfield on the document path via index/key access."""
        return Query(self.path + (name,))

    def _value(self, document: Mapping[str, Any]) -> Tuple[bool, Any]:
        """Traverse the document path to retrieve the value.
        
        Returns a tuple: (found, value).
        """
        current: Any = document
        for part in self.path:
            if isinstance(current, Mapping) and part in current:
                current = current[part]
            else:
                return False, None
        return True, current

    def exists(self) -> Condition:
        """Create a condition asserting that the path exists in the document."""
        return Condition(self.path, "exists")

    def test(self, func: Callable[[Any], bool]) -> Condition:
        """Create a condition asserting that a callable evaluates to True for the path value."""
        return Condition(self.path, "test", func)

    def __eq__(self, other: Any) -> Condition:
        """Create an equality comparison condition."""
        return Condition(self.path, "==", other)

    def __ne__(self, other: Any) -> Condition:
        """Create an inequality comparison condition."""
        return Condition(self.path, "!=", other)

    def __lt__(self, other: Any) -> Condition:
        """Create a less-than comparison condition."""
        return Condition(self.path, "<", other)

    def __le__(self, other: Any) -> Condition:
        """Create a less-than-or-equal comparison condition."""
        return Condition(self.path, "<=", other)

    def __gt__(self, other: Any) -> Condition:
        """Create a greater-than comparison condition."""
        return Condition(self.path, ">", other)

    def __ge__(self, other: Any) -> Condition:
        """Create a greater-than-or-equal comparison condition."""
        return Condition(self.path, ">=", other)

    def __and__(self, other: Condition) -> Condition:
        """Combine this path's existence constraint and another condition with logical AND."""
        return AndCondition(self.exists(), other)

    def __or__(self, other: Condition) -> Condition:
        """Combine this path's existence constraint and another condition with logical OR."""
        return OrCondition(self.exists(), other)

    def __invert__(self) -> Condition:
        """Invert the existence constraint of this path."""
        return NotCondition(self.exists())


class Condition:
    """Represents a filtering constraint applied to a document."""

    def __init__(self, path: Tuple[Any, ...], op: str, expected: Any = None) -> None:
        """Initialize the condition with path, operator, and comparison value."""
        self.path = path
        self.op = op
        self.expected = expected

    def path_str(self) -> str:
        """Return a dot-separated string representation of the path."""
        return ".".join(str(p) for p in self.path)

    def __str__(self) -> str:
        """Return a human-readable query string format for LLM context reading."""
        if self.op == "exists":
            return f"exists({self.path_str()})"
        if self.op == "test":
            expected_repr = getattr(self.expected, "__name__", str(self.expected))
            return f"test({self.path_str()}, {expected_repr})"
        return f"{self.path_str()} {self.op} {repr(self.expected)}"

    def matches(self, document: Mapping[str, Any]) -> bool:
        """Determine whether the document satisfies the condition."""
        found, value = Query(self.path)._value(document)
        if self.op == "exists":
            return found
        if not found:
            return False
        if self.op == "test":
            if not callable(self.expected):
                return False
            return bool(self.expected(value))
        if self.op == "==":
            return bool(value == self.expected)
        if self.op == "!=":
            return bool(value != self.expected)
        try:
            if self.op == "<":
                return bool(value < self.expected)
            if self.op == "<=":
                return bool(value <= self.expected)
            if self.op == ">":
                return bool(value > self.expected)
            if self.op == ">=":
                return bool(value >= self.expected)
        except TypeError:
            return False
        return False

    def __and__(self, other: Condition) -> Condition:
        """Logical AND with another condition."""
        return AndCondition(self, other)

    def __or__(self, other: Condition) -> Condition:
        """Logical OR with another condition."""
        return OrCondition(self, other)

    def __invert__(self) -> Condition:
        """Logical NOT of this condition."""
        return NotCondition(self)


class AndCondition(Condition):
    """Combines two conditions using logical AND."""

    def __init__(self, left: Condition, right: Condition) -> None:
        """Initialize with left and right child conditions."""
        super().__init__((), "and")
        self.left = left
        self.right = right

    def __str__(self) -> str:
        """String representation of logical AND."""
        return f"({self.left} and {self.right})"

    def matches(self, document: Mapping[str, Any]) -> bool:
        """Evaluate logical AND matches."""
        return self.left.matches(document) and self.right.matches(document)


class OrCondition(Condition):
    """Combines two conditions using logical OR."""

    def __init__(self, left: Condition, right: Condition) -> None:
        """Initialize with left and right child conditions."""
        super().__init__((), "or")
        self.left = left
        self.right = right

    def __str__(self) -> str:
        """String representation of logical OR."""
        return f"({self.left} or {self.right})"

    def matches(self, document: Mapping[str, Any]) -> bool:
        """Evaluate logical OR matches."""
        return self.left.matches(document) or self.right.matches(document)


class NotCondition(Condition):
    """Negates a condition using logical NOT."""

    def __init__(self, inner: Condition) -> None:
        """Initialize with the condition to negate."""
        super().__init__((), "not")
        self.inner = inner

    def __str__(self) -> str:
        """String representation of logical NOT."""
        return f"not({self.inner})"

    def matches(self, document: Mapping[str, Any]) -> bool:
        """Evaluate logical NOT match."""
        return not self.inner.matches(document)
