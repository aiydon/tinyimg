import pathlib as p
import typing as t

type Effort = t.Literal["fast", "balanced", "max"]
type PathLike = str | p.Path
type Quality = t.Literal["auto", "lossless"] | int
