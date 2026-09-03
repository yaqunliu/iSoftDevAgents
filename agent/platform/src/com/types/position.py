from dataclasses import dataclass


@dataclass(frozen=True)
class Position:
    x: int
    y: int

    def __iter__(self):
        yield self.x
        yield self.y
