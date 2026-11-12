import math
import pathlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Sequence, Tuple

import png

from mariner.file_formats.reading import MalformedFile


@dataclass(frozen=True)
class SlicedModelFile(ABC):
    filename: str
    bed_size_mm: Tuple[float, float, float]
    height_mm: float
    layer_height_mm: float
    layer_count: int
    resolution: Tuple[int, int]
    print_time_secs: int
    end_byte_offset_by_layer: Sequence[int]
    slicer_version: str
    printer_name: str

    def __post_init__(self) -> None:
        # Not a number, or without end: nothing can be worked out from such
        # a measure, and it cannot be written in an answer.
        measures = (*self.bed_size_mm, self.height_mm, self.layer_height_mm)
        if not all(math.isfinite(measure) for measure in measures):
            raise MalformedFile("a measure of the model is not a number")

    @classmethod
    @abstractmethod
    def read(self, path: pathlib.Path) -> "SlicedModelFile": ...

    @classmethod
    @abstractmethod
    def read_preview(cls, path: pathlib.Path) -> png.Image: ...
