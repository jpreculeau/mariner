"""What the parsers share: reading with bounds, and decoding previews.

A sliced model file says of itself where its parts are and how large. None
of that can be taken at its word: a file cut short by a failed transfer, or
one made to that end, would otherwise have Mariner read far past what it
needs or build a picture of millions of points, on a board with little
memory. Every size and count read from a file is therefore checked before
it is acted on: against the size of the file, and where that is not enough,
as for the preview, against a ceiling set from what real files hold.
"""

import dataclasses
import os
import struct
from typing import BinaryIO, List, Type, TypeVar

import png
from typedstruct import Struct

# A print of 100 000 layers at the finest layer height in use, a hundredth
# of a millimetre, would be a metre tall.
MAX_LAYER_COUNT = 100_000
# The largest previews slicers embed are a few hundred points a side: 400
# by 300 is usual. Decoding one costs time and memory in proportion to its
# points, not to the bytes it is stored in, so the ceiling is kept near
# what is real.
MAX_PREVIEW_SIDE = 1024
MAX_PREVIEW_POINTS = 1_000_000
# The most the encoding can spend on a point: a colour and a repeat count.
MAX_PREVIEW_BYTES_PER_POINT = 4
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
    """The text of *length* bytes stored in *file* at *offset*.

    A text of no length is empty wherever it is said to be: its place may
    have been left unset.
    """
    if length == 0:
        return ""
    if length > MAX_TEXT_BYTES:
        raise MalformedFile(f"{what} is {length} bytes long")
    return read_bytes(file, offset, length, what).decode("utf-8", errors="replace")


def check_layer_count(
    file: BinaryIO,
    layer_count: int,
    table_offset: int,
    entry_size: int,
    passes: int = 1,
) -> None:
    """Refuse a layer table that is empty, absurdly long, or outside the file.

    The table holds an entry for each layer in each of the *passes* the
    file stores (see ``passes_stored``).
    """
    if layer_count == 0:
        raise MalformedFile("the file holds no layer")
    if layer_count > MAX_LAYER_COUNT:
        raise MalformedFile(f"the file claims {layer_count} layers")
    if table_offset + layer_count * passes * entry_size > size_of(file):
        raise MalformedFile("the layer table lies outside the file")


# The format of .cbddlp and .photon files. From its version 2 on, a file
# sliced with anti-aliasing stores every layer once per pass: the table
# holds all the layers of the first pass, then all those of the second, and
# so on.
_MAGIC_ONE_IMAGE_PER_PASS = 0x12FD0019
_MAX_PASSES = 16


def passes_stored(magic: int, version: int, anti_alias_level: int) -> int:
    """How many times the file stores each of its layers."""
    if (
        magic == _MAGIC_ONE_IMAGE_PER_PASS
        and version >= 2
        and 1 < anti_alias_level <= _MAX_PASSES
    ):
        return anti_alias_level
    return 1


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


_ENTRIES_PER_READ = 4096


def _ends_format(struct_type: Type[Struct]) -> struct.Struct:
    """Reads, of an entry of the layer table, where its image is and how long."""
    layout = struct_type.FORMAT_PREFIX
    for field in dataclasses.fields(struct_type):
        field_format = field.metadata["format"]
        if field.name in ("image_offset", "image_length"):
            layout += field_format
        else:
            layout += f"{struct.calcsize(struct_type.FORMAT_PREFIX + field_format)}x"
    return struct.Struct(layout)


def read_layer_ends(
    file: BinaryIO,
    struct_type: Type[Struct],
    table_offset: int,
    layer_count: int,
    passes: int = 1,
) -> List[int]:
    """Where each layer ends in *file*, from its layer table.

    The table at *table_offset* holds one *struct_type* for each layer in
    each of the *passes* the file stores (see ``passes_stored``). The ends
    given are those of the first pass, which is what following a print
    takes; every entry is checked to end within the file, as in
    ``check_layers_fit``.

    The table is read a few thousand entries at a time, and only the two
    numbers needed are taken from each: entry by entry, the longest table
    allowed took seconds to read.
    """
    entry = _ends_format(struct_type)
    check_layer_count(file, layer_count, table_offset, entry.size, passes)
    size = size_of(file)
    total = layer_count * passes
    ends: List[int] = []
    read = 0
    while read < total:
        count = min(_ENTRIES_PER_READ, total - read)
        block = read_bytes(
            file, table_offset + read * entry.size, count * entry.size, "layer table"
        )
        for image_offset, image_length in entry.iter_unpack(block):
            read += 1
            end = image_offset + image_length
            if end > size:
                layer = (read - 1) % layer_count + 1
                which = f"layer {layer} of {layer_count}"
                if passes > 1:
                    which += f" (pass {(read - 1) // layer_count + 1} of {passes})"
                raise MalformedFile(
                    f"{which} lies outside the file: the file is incomplete"
                )
            if read <= layer_count:
                ends.append(end)
    return ends


def read_preview(
    file: BinaryIO, width: int, height: int, offset: int, length: int
) -> png.Image:
    """The preview picture stored in *file*, checked before it is decoded."""
    if not (0 < width <= MAX_PREVIEW_SIDE and 0 < height <= MAX_PREVIEW_SIDE):
        raise MalformedFile(f"the preview claims to be {width} by {height}")
    if width * height > MAX_PREVIEW_POINTS:
        raise MalformedFile(f"the preview claims to be {width} by {height}")
    if length > MAX_PREVIEW_BYTES_PER_POINT * width * height:
        # Bounded by the file alone, the whole of a large file could be read
        # into memory on the word of a few bytes.
        raise MalformedFile(
            f"the preview claims {length} bytes for {width} by {height}"
        )
    return decode_preview(width, height, read_bytes(file, offset, length, "preview"))


_REPEAT_RGB15_MASK: int = 1 << 5


def decode_preview(width: int, height: int, data: bytes) -> png.Image:
    """Decode a run-length encoded RGB15 preview of *width* by *height*.

    Each point is 16 bits; when bit 5 is set, the next 16 bits say how many
    more times it repeats. Decoding stops once *height* rows are complete,
    whatever *data* still holds: a run can stand for thousands of points,
    so a few bytes could otherwise ask for a picture of any size.

    The picture is built as bytes, three a point: as lists of numbers it
    would take several times the memory.

    Raises MalformedFile if *data* holds no complete row.
    """
    row_bytes = 3 * width
    wanted = row_bytes * height
    points = bytearray()
    position = 0
    last = len(data) - 1
    while position < last and len(points) < wanted:
        color16 = data[position] | (data[position + 1] << 8)
        position += 2
        repeat = 1
        if color16 & _REPEAT_RGB15_MASK:
            if position >= last:
                break
            repeat += (data[position] | (data[position + 1] << 8)) & 0xFFF
            position += 2
        points += (
            bytes((color16 & 0x1F, (color16 >> 6) & 0x1F, (color16 >> 11) & 0x1F))
            * repeat
        )

    # A last row that was cut short is dropped, and so is what a run added
    # past the last row.
    rows = min(len(points), wanted) // row_bytes
    if not rows:
        raise MalformedFile("the preview holds no complete row")
    view = memoryview(points)
    return png.from_array(
        [view[start:][:row_bytes] for start in range(0, rows * row_bytes, row_bytes)],
        "RGB;5",
        info={"width": width, "height": rows},
    )
