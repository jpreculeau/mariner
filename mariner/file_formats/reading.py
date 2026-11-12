"""What the parsers share: reading with bounds, and decoding previews.

A sliced model file says of itself where its parts are and how large. None
of that can be taken at its word: a file cut short by a failed transfer, or
one made to that end, would otherwise have Mariner read far past what it
needs or build a picture of millions of points, on a board with little
memory. Every size and count read from a file is therefore checked against
the size of the file, or against a ceiling no real file comes near, before
it is acted on.
"""

import os
import struct
from typing import BinaryIO, List, Type, TypeVar

import png
from typedstruct import Struct

# No real file comes near these. A print of 100 000 layers at the finest
# layer height in use would be two metres tall; the largest previews slicers
# embed are a few hundred points a side.
MAX_LAYER_COUNT = 100_000
MAX_PREVIEW_SIDE = 4096
MAX_PREVIEW_POINTS = 4_000_000
MAX_TEXT_BYTES = 1024


class MalformedFile(ValueError):
    """The file is not what its format says it should be.

    Cut short, damaged, made by a slicer version Mariner does not know, or
    made to mislead. The message says which part did not hold.
    """


TStruct = TypeVar("TStruct", bound=Struct)


def size_of(file: BinaryIO) -> int:
    """The size of the open *file*, in bytes."""
    return os.fstat(file.fileno()).st_size


def read_bytes(file: BinaryIO, offset: int, length: int, what: str) -> bytes:
    """Exactly *length* bytes of *file* from *offset*.

    Raises MalformedFile, naming *what* was being read, if the file does
    not hold them.
    """
    if offset < 0 or length < 0 or offset + length > size_of(file):
        raise MalformedFile(f"{what} lies outside the file")
    file.seek(offset)
    data = file.read(length)
    if len(data) != length:
        raise MalformedFile(f"{what} is cut short")
    return data


def read_struct(
    file: BinaryIO, struct_type: Type[TStruct], offset: int, what: str
) -> TStruct:
    """The *struct_type* stored in *file* at *offset*."""
    data = read_bytes(file, offset, struct_type.get_size(), what)
    try:
        return struct_type.unpack(data)
    except struct.error as error:
        raise MalformedFile(f"{what} cannot be read") from error


def read_text(file: BinaryIO, offset: int, length: int, what: str) -> str:
    """The text of *length* bytes stored in *file* at *offset*."""
    if length > MAX_TEXT_BYTES:
        raise MalformedFile(f"{what} is {length} bytes long")
    return read_bytes(file, offset, length, what).decode("utf-8", errors="replace")


def check_layer_count(
    file: BinaryIO, layer_count: int, table_offset: int, entry_size: int
) -> None:
    """Refuse a layer table the file is too small to hold, or absurdly long."""
    if layer_count > MAX_LAYER_COUNT:
        raise MalformedFile(f"the file claims {layer_count} layers")
    if table_offset + layer_count * entry_size > size_of(file):
        raise MalformedFile("the layer table lies outside the file")


def check_layers_fit(file: BinaryIO, end_byte_offset_by_layer: List[int]) -> None:
    """Refuse a file that ends before one of its layers does.

    The headers and the layer table come first, so a transfer that stopped
    part of the way leaves a file that looks whole from the start: it would
    be listed, started, and print until the data ran out.
    """
    size = size_of(file)
    for layer, end in enumerate(end_byte_offset_by_layer, start=1):
        if end > size:
            raise MalformedFile(
                f"layer {layer} of {len(end_byte_offset_by_layer)} "
                "lies outside the file: the file is incomplete"
            )


def read_preview(
    file: BinaryIO, width: int, height: int, offset: int, length: int
) -> png.Image:
    """The preview picture stored in *file*, checked before it is decoded."""
    if not (0 < width <= MAX_PREVIEW_SIDE and 0 < height <= MAX_PREVIEW_SIDE):
        raise MalformedFile(f"the preview claims to be {width} by {height}")
    if width * height > MAX_PREVIEW_POINTS:
        raise MalformedFile(f"the preview claims to be {width} by {height}")
    return decode_preview(width, height, read_bytes(file, offset, length, "preview"))


_REPEAT_RGB15_MASK: int = 1 << 5


def decode_preview(width: int, height: int, data: bytes) -> png.Image:
    """Decode a run-length encoded RGB15 preview of *width* by *height*.

    Each point is 16 bits; when bit 5 is set, the next 16 bits say how many
    more times it repeats. Decoding stops once *height* rows are complete,
    whatever *data* still holds: a run can stand for thousands of points,
    so a few bytes could otherwise ask for a picture of any size.

    Raises MalformedFile if *data* holds no complete row.
    """
    rows: List[List[int]] = [[]]
    position = 0
    while position + 2 <= len(data) and len(rows) <= height:
        color16 = int(struct.unpack_from("<H", data, position)[0])
        position += 2
        repeat = 1
        if color16 & _REPEAT_RGB15_MASK:
            if position + 2 > len(data):
                break
            repeat += int(struct.unpack_from("<H", data, position)[0]) & 0xFFF
            position += 2

        point = [(color16 >> 0) & 0x1F, (color16 >> 6) & 0x1F, (color16 >> 11) & 0x1F]
        while repeat > 0 and len(rows) <= height:
            rows[-1] += point
            repeat -= 1
            if len(rows[-1]) == 3 * width:
                rows.append([])

    # The last row is the one being filled: empty after a complete picture,
    # partial after one that was cut short.
    rows.pop()
    if not rows:
        raise MalformedFile("the preview holds no complete row")
    return png.from_array(rows, "RGB;5")
