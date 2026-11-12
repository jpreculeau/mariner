import struct
import tempfile
from dataclasses import dataclass
from typing import Any, List
from unittest import TestCase

from pyexpect import expect
from typedstruct import LittleEndianStruct, StructType

from mariner.file_formats import reading
from mariner.file_formats.reading import MalformedFile


@dataclass(frozen=True)
class _Pair(LittleEndianStruct):
    first: int = StructType.uint32()
    second: int = StructType.uint32()


def _point(red: int, green: int, blue: int, repeats: int = 0) -> bytes:
    """One run of the preview encoding: a colour, shown 1 + *repeats* times."""
    color = red | (green << 6) | (blue << 11)
    if repeats:
        return struct.pack("<HH", color | (1 << 5), repeats)
    return struct.pack("<H", color)


def _rows(image: Any) -> List[List[int]]:
    return [list(row) for row in image.rows]


class ReadingTest(TestCase):
    def setUp(self) -> None:
        self.file = tempfile.TemporaryFile()
        self.addCleanup(self.file.close)
        self.file.write(struct.pack("<II", 7, 9) + b"name" + b"tail")
        self.file.flush()

    def test_size_of(self) -> None:
        expect(reading.size_of(self.file)).to_equal(16)

    def test_read_bytes_gives_exactly_what_was_asked_for(self) -> None:
        expect(reading.read_bytes(self.file, 8, 4, "name")).to_equal(b"name")
        expect(reading.read_bytes(self.file, 12, 4, "tail")).to_equal(b"tail")
        expect(reading.read_bytes(self.file, 16, 0, "nothing")).to_equal(b"")

    def test_read_bytes_refuses_what_the_file_does_not_hold(self) -> None:
        for offset, length in ((12, 5), (17, 0), (-1, 2), (0, -1), (0, 2**32)):
            with self.assertRaises(MalformedFile) as raised:
                reading.read_bytes(self.file, offset, length, "the name")
            expect("the name" in str(raised.exception)).to_equal(True)

    def test_read_struct(self) -> None:
        expect(reading.read_struct(self.file, _Pair, 0, "header")).to_equal(
            _Pair(first=7, second=9)
        )
        with self.assertRaises(MalformedFile):
            reading.read_struct(self.file, _Pair, 12, "header")

    def test_read_text(self) -> None:
        expect(reading.read_text(self.file, 8, 4, "name")).to_equal("name")

    def test_passes_stored(self) -> None:
        old, new = 0x12FD0019, 0x12FD0086
        for magic, version, level, passes in (
            (old, 2, 4, 4),
            (old, 3, 16, 16),
            (old, 3, 1, 1),
            (old, 3, 0, 1),
            # The first version has no anti-aliasing; the field is not one.
            (old, 1, 4, 1),
            # Not a number of passes any slicer offers.
            (old, 3, 17, 1),
            # The newer format folds the passes into one image a layer.
            (new, 3, 4, 1),
        ):
            expect(reading.passes_stored(magic, version, level)).to_equal(passes)

    def test_the_layer_ceiling_is_on_layers_not_on_their_passes(self) -> None:
        most = reading.MAX_LAYER_COUNT
        reading.check_layer_count(self.file, most, 0, 0, passes=16)
        with self.assertRaises(MalformedFile) as raised:
            reading.check_layer_count(self.file, most + 1, 0, 0, passes=16)
        expect(f"{most + 1} layers" in str(raised.exception)).to_equal(True)
        # Two layers of eight bytes fit in sixteen; two passes of them do not.
        reading.check_layer_count(self.file, 2, 0, 8)
        with self.assertRaises(MalformedFile):
            reading.check_layer_count(self.file, 2, 0, 8, passes=2)

    def test_read_text_of_no_length_reads_nothing(self) -> None:
        # Wherever it is said to be: some writers leave the place unset.
        expect(reading.read_text(self.file, 0x7FFFFFFF, 0, "name")).to_equal("")

    def test_the_layer_ceiling_is_allowed_and_one_more_is_not(self) -> None:
        reading.check_layer_count(self.file, reading.MAX_LAYER_COUNT, 0, 0)
        with self.assertRaises(MalformedFile):
            reading.check_layer_count(self.file, reading.MAX_LAYER_COUNT + 1, 0, 0)

    def test_read_text_refuses_a_text_too_long_to_be_a_name(self) -> None:
        # Even when the file does hold that many bytes.
        self.file.write(bytes(2 * reading.MAX_TEXT_BYTES))
        self.file.flush()
        reading.read_text(self.file, 0, reading.MAX_TEXT_BYTES, "name")
        with self.assertRaises(MalformedFile):
            reading.read_text(self.file, 0, reading.MAX_TEXT_BYTES + 1, "name")

    def test_read_preview_refuses_a_picture_too_large_as_a_whole(self) -> None:
        # Each side is within bounds; together they are sixteen million points.
        side = reading.MAX_PREVIEW_SIDE
        with self.assertRaises(MalformedFile) as raised:
            reading.read_preview(self.file, side, side, 0, 4)
        expect(f"{side} by {side}" in str(raised.exception)).to_equal(True)

    def test_read_text_survives_bytes_that_are_not_text(self) -> None:
        self.file.seek(8)
        self.file.write(b"\xff\xfe")
        self.file.flush()
        expect(len(reading.read_text(self.file, 8, 4, "name"))).to_equal(4)

    def test_check_layer_count(self) -> None:
        reading.check_layer_count(self.file, 2, 0, 8)
        with self.assertRaises(MalformedFile):
            # Nothing to print.
            reading.check_layer_count(self.file, 0, 0, 8)
        with self.assertRaises(MalformedFile):
            # Three entries of eight bytes do not fit in sixteen.
            reading.check_layer_count(self.file, 3, 0, 8)
        with self.assertRaises(MalformedFile):
            reading.check_layer_count(self.file, 2, 4, 8)
        with self.assertRaises(MalformedFile):
            reading.check_layer_count(self.file, reading.MAX_LAYER_COUNT + 1, 0, 0)

    def test_check_layers_fit(self) -> None:
        reading.check_layers_fit(self.file, [])
        reading.check_layers_fit(self.file, [8, 12, 16])
        with self.assertRaises(MalformedFile) as raised:
            reading.check_layers_fit(self.file, [8, 17, 12])
        expect("layer 2" in str(raised.exception)).to_equal(True)


class DecodePreviewTest(TestCase):
    def test_decodes_points_and_runs(self) -> None:
        data = _point(1, 2, 3) + _point(4, 5, 6, repeats=2) + _point(7, 8, 9)
        image = reading.decode_preview(2, 2, data)
        expect(_rows(image)).to_equal([[1, 2, 3, 4, 5, 6], [4, 5, 6, 4, 5, 6]])
        expect(image.info["bitdepth"]).to_equal(5)

    def test_stops_at_the_height_it_was_given(self) -> None:
        # Four bytes here stand for 4096 points. Unchecked, a few kilobytes
        # of them would ask for a picture of millions of points.
        data = _point(1, 1, 1, repeats=0xFFF) * 1000
        image = reading.decode_preview(4, 3, data)
        expect(_rows(image)).to_equal([[1, 1, 1] * 4] * 3)

    def test_drops_a_last_row_that_is_cut_short(self) -> None:
        data = _point(1, 1, 1, repeats=4)
        expect(_rows(reading.decode_preview(2, 4, data))).to_equal(
            [[1, 1, 1, 1, 1, 1], [1, 1, 1, 1, 1, 1]]
        )

    def test_survives_data_cut_in_the_middle_of_a_run(self) -> None:
        data = _point(1, 1, 1) + _point(2, 2, 2) + _point(3, 3, 3, repeats=5)[:3]
        expect(_rows(reading.decode_preview(2, 2, data))).to_equal([[1, 1, 1, 2, 2, 2]])

    def test_a_large_picture_is_decoded_into_bytes_not_lists(self) -> None:
        # A list entry costs eight times a byte; the difference is what a
        # request for a preview may cost in memory.
        import tracemalloc

        data = _point(3, 3, 3, repeats=0xFFF) * 245
        tracemalloc.start()
        image = reading.decode_preview(1000, 1000, data)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        expect(image.info["height"]).to_equal(1000)
        expect(peak < 8_000_000).to_equal(True)

    def test_data_past_the_picture_is_not_decoded(self) -> None:
        import tracemalloc

        data = _point(3, 3, 3, repeats=0xFFF) * 100_000
        tracemalloc.start()
        image = reading.decode_preview(4, 3, data)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        expect(_rows(image)).to_equal([[3, 3, 3] * 4] * 3)
        expect(peak < 100_000).to_equal(True)

    def test_refuses_data_without_a_complete_row(self) -> None:
        for data in (b"", b"\x01", _point(1, 1, 1)):
            with self.assertRaises(MalformedFile):
                reading.decode_preview(2, 2, data)


class ReadPreviewTest(TestCase):
    def _file(self, data: bytes) -> Any:
        file = tempfile.TemporaryFile()
        self.addCleanup(file.close)
        file.write(data)
        file.flush()
        return file

    def test_reads_the_picture_where_it_is_said_to_be(self) -> None:
        data = _point(1, 2, 3, repeats=3)
        file = self._file(b"head" + data)
        image = reading.read_preview(file, 2, 2, 4, len(data))
        expect(_rows(image)).to_equal([[1, 2, 3, 1, 2, 3]] * 2)

    def test_refuses_a_picture_of_an_absurd_size(self) -> None:
        file = self._file(_point(1, 2, 3, repeats=3))
        side = reading.MAX_PREVIEW_SIDE
        for width, height in (
            (0, 2),
            (2, 0),
            (side + 1, 2),
            (2, side + 1),
            (3000, 3000),
        ):
            with self.assertRaises(MalformedFile):
                reading.read_preview(file, width, height, 0, 4)

    def test_the_ceilings_are_those_of_a_thumbnail(self) -> None:
        # The largest previews slicers embed are a few hundred points a
        # side. Decoding costs memory in proportion to the points, whatever
        # the size of the file, on a board with little of it.
        expect(reading.MAX_PREVIEW_SIDE <= 1024).to_equal(True)
        expect(reading.MAX_PREVIEW_POINTS <= 1_000_000).to_equal(True)

    def test_refuses_more_data_than_the_picture_can_need(self) -> None:
        # Otherwise a header could have the whole file read into memory.
        # Four bytes a point is the most the encoding can spend.
        file = self._file(bytes(64))
        reading.read_preview(file, 2, 2, 0, 16)
        with self.assertRaises(MalformedFile) as raised:
            reading.read_preview(file, 2, 2, 0, 17)
        expect("17 bytes" in str(raised.exception)).to_equal(True)

    def test_refuses_a_picture_the_file_does_not_hold(self) -> None:
        file = self._file(_point(1, 2, 3, repeats=3))
        with self.assertRaises(MalformedFile):
            reading.read_preview(file, 2, 2, 0, 9)
        with self.assertRaises(MalformedFile):
            reading.read_preview(file, 2, 2, 0, 2**31)
