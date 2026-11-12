"""Files that are not what they claim: cut short, or made to mislead."""

import dataclasses
import pathlib
import struct
import tempfile
from typing import Any, Type
from unittest import TestCase

from pyexpect import expect

from mariner.file_formats import ctb_encrypted
from mariner.file_formats.ctb import CTBFile, CTBHeader, CTBPreview, CTBSlicer
from mariner.file_formats.ctb_encrypted import (
    CTBEncryptedFile,
    CTBEncryptedHeader,
    CTBEncryptedSlicer,
)
from mariner.file_formats.fdg import FDGFile, FDGHeader, FDGPreview
from mariner.file_formats.photon import PhotonFile, PhotonHeader, PhotonPreview
from mariner.file_formats.reading import MalformedFile
from mariner.file_formats.utils import UnsupportedFileFormat, get_file_format

SAMPLES = pathlib.Path(__file__).parent.absolute()

# Sample, parser, header, preview header.
PLAIN = (
    ("stairs.ctb", CTBFile, CTBHeader, CTBPreview),
    ("pyramid.cbddlp", CTBFile, CTBHeader, CTBPreview),
    ("stairs.fdg", FDGFile, FDGHeader, FDGPreview),
    ("stairs.photon", PhotonFile, PhotonHeader, PhotonPreview),
)


def _offset_of(struct_type: Type[Any], name: str) -> int:
    """Where the field *name* starts within *struct_type*."""
    before = ""
    for field in dataclasses.fields(struct_type):
        if field.name == name:
            return struct.calcsize(struct_type.FORMAT_PREFIX + before)
        before += field.metadata["format"]
    raise KeyError(name)


class MalformedFileTest(TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def _copy(self, sample: str, contents: bytes) -> pathlib.Path:
        path = pathlib.Path(self.directory.name) / sample
        path.write_bytes(contents)
        return path

    def _with(self, sample: str, offset: int, patch: bytes) -> pathlib.Path:
        contents = bytearray((SAMPLES / sample).read_bytes())
        end = offset + len(patch)
        contents[offset:end] = patch
        return self._copy(sample, bytes(contents))

    # ---- every format ----

    def test_a_file_cut_short_is_refused(self) -> None:
        for sample, parser, _, _ in PLAIN + (
            ("bolts.ctb", CTBEncryptedFile, None, None),
        ):
            whole = (SAMPLES / sample).read_bytes()
            for kept in (0, 10, 64, len(whole) // 2):
                path = self._copy(sample, whole[:kept])
                with self.assertRaises(MalformedFile):
                    parser.read(path)
            for kept in (0, 10, 64):
                path = self._copy(sample, whole[:kept])
                with self.assertRaises(MalformedFile):
                    parser.read_preview(path)

    def test_a_layer_count_the_file_cannot_hold_is_refused(self) -> None:
        for sample, parser, header, _ in PLAIN:
            for count in (0xFFFFFFFF, 100_001):
                path = self._with(
                    sample, _offset_of(header, "layer_count"), struct.pack("<I", count)
                )
                with self.assertRaises(MalformedFile):
                    parser.read(path)

    def test_a_file_missing_the_end_of_its_layers_is_refused(self) -> None:
        # The headers and the layer table come first, so a transfer that
        # stopped part of the way leaves a file that looks whole from the
        # start. It would print until the data ran out.
        for sample, parser, _, _ in PLAIN + (
            ("bolts.ctb", CTBEncryptedFile, None, None),
            ("bracket.ctb", CTBEncryptedFile, None, None),
        ):
            whole = (SAMPLES / sample).read_bytes()
            # Some formats keep other parts after the layers.
            end = max(parser.read(SAMPLES / sample).end_byte_offset_by_layer)
            for missing in (1, 4096, end // 3):
                with self.assertRaises(MalformedFile):
                    parser.read(self._copy(sample, whole[: end - missing]))

    def test_a_printer_name_of_absurd_length_is_refused(self) -> None:
        path = self._with(
            "stairs.fdg",
            _offset_of(FDGHeader, "machine_size"),
            struct.pack("<I", 0x7FFFFFFF),
        )
        with self.assertRaises(MalformedFile):
            FDGFile.read(path)

    def test_a_file_of_the_first_format_version_is_read(self) -> None:
        # It has no table of slicer settings: where its place would be
        # given, the header says 0. Nothing is known then of the printer
        # and the slicer, and the file prints all the same.
        for sample, parser, header, _ in PLAIN:
            if "slicer_offset" not in [f.name for f in dataclasses.fields(header)]:
                continue
            whole = bytearray((SAMPLES / sample).read_bytes())
            struct.pack_into("<I", whole, _offset_of(header, "version"), 1)
            struct.pack_into("<I", whole, _offset_of(header, "slicer_offset"), 0)
            struct.pack_into("<I", whole, _offset_of(header, "slicer_size"), 0)
            expected = parser.read(SAMPLES / sample)
            read = parser.read(self._copy(sample, bytes(whole)))
            expect(read.printer_name).to_equal("")
            expect(read.slicer_version).to_equal("")
            expect(read.layer_count).to_equal(expected.layer_count)
            expect(read.end_byte_offset_by_layer).to_equal(
                expected.end_byte_offset_by_layer
            )

    def test_a_slicer_table_of_no_size_is_not_read(self) -> None:
        whole = bytearray((SAMPLES / "stairs.ctb").read_bytes())
        struct.pack_into("<I", whole, _offset_of(CTBHeader, "slicer_size"), 0)
        read = CTBFile.read(self._copy("stairs.ctb", bytes(whole)))
        expect(read.slicer_version).to_equal("")

    def test_an_encrypted_file_cut_in_a_layer_stored_encrypted_is_refused(
        self,
    ) -> None:
        # Such a layer gives a second pair of numbers, which are not places
        # in the file. Where the layer ends is said by the first pair.
        whole = bytearray((SAMPLES / "bolts.ctb").read_bytes())
        with open(SAMPLES / "bolts.ctb", "rb") as file:
            header, slicer = ctb_encrypted._read_settings(file)
        last = (
            slicer.layer_table_offset
            + (slicer.layer_count - 1) * ctb_encrypted.CTBLayerPointer.get_size()
        )
        layer_offset = struct.unpack_from("<I", whole, last)[0]
        layer = ctb_encrypted.CTBEncryptedLayerDef
        struct.pack_into(
            "<I", whole, layer_offset + _offset_of(layer, "encrypted_data_length"), 1024
        )
        CTBEncryptedFile.read(self._copy("bolts.ctb", bytes(whole)))
        where = layer_offset + _offset_of(layer, "data_length")
        length = struct.unpack_from("<I", whole, where)[0]
        struct.pack_into("<I", whole, where, length + 100_000)
        with self.assertRaises(MalformedFile):
            CTBEncryptedFile.read(self._copy("bolts.ctb", bytes(whole)))

    def test_a_printer_name_of_no_length_is_read_wherever_it_is_said_to_be(
        self,
    ) -> None:
        whole = bytearray((SAMPLES / "stairs.ctb").read_bytes())
        slicer = struct.unpack_from(
            "<I", whole, _offset_of(CTBHeader, "slicer_offset")
        )[0]
        struct.pack_into(
            "<II",
            whole,
            slicer + _offset_of(CTBSlicer, "machine_offset"),
            0x7FFFFFFF,
            0,
        )
        expect(
            CTBFile.read(self._copy("stairs.ctb", bytes(whole))).printer_name
        ).to_equal("")

    def test_a_measure_that_is_not_a_number_is_refused(self) -> None:
        # Not a number, or without end: nothing can be worked out from it,
        # and it cannot be written in an answer.
        for sample, parser, header, _ in PLAIN:
            for field in ("layer_height_mm", "height_mm", "bed_size_x_mm"):
                if field not in [f.name for f in dataclasses.fields(header)]:
                    continue
                for value in (float("nan"), float("inf"), float("-inf")):
                    path = self._with(
                        sample, _offset_of(header, field), struct.pack("<f", value)
                    )
                    with self.assertRaises(MalformedFile):
                        parser.read(path)
        for field in ("layer_height_mm", "total_height_mm", "display_width"):
            with self.assertRaises(MalformedFile):
                CTBEncryptedFile.read(self._encrypted_with(**{field: float("nan")}))

    def test_a_file_without_a_layer_is_refused(self) -> None:
        for sample, parser, header, _ in PLAIN:
            path = self._with(
                sample, _offset_of(header, "layer_count"), struct.pack("<I", 0)
            )
            with self.assertRaises(MalformedFile) as raised:
                parser.read(path)
            expect(str(raised.exception)).to_equal("the file holds no layer")
        with self.assertRaises(MalformedFile) as raised:
            CTBEncryptedFile.read(self._encrypted_with(layer_count=0))
        expect(str(raised.exception)).to_equal("the file holds no layer")

    def test_anti_aliasing_in_the_newer_format_does_not_multiply_the_layers(
        self,
    ) -> None:
        # There the passes are folded into one image per layer.
        path = self._with(
            "stairs.ctb",
            _offset_of(CTBHeader, "anti_alias_level"),
            struct.pack("<I", 4),
        )
        expect(CTBFile.read(path).layer_count).to_equal(400)

    def test_a_ctb_file_too_short_to_say_which_kind_it_is_is_refused(self) -> None:
        for contents in (b"", b"ab", b"abc"):
            path = self._copy("short.ctb", contents)
            with self.assertRaises(MalformedFile):
                get_file_format(str(path)).read(path)

    def test_an_anti_aliased_file_cut_in_its_last_pass_is_refused(self) -> None:
        # This format stores each layer once per anti-aliasing pass. The
        # passes after the first come last in the file.
        whole = (SAMPLES / "pyramid.cbddlp").read_bytes()
        CTBFile.read(self._copy("pyramid.cbddlp", whole))
        for missing in (64, 4096):
            with self.assertRaises(MalformedFile):
                CTBFile.read(self._copy("pyramid.cbddlp", whole[:-missing]))

    def test_the_same_goes_for_a_photon_file(self) -> None:
        # The two extensions are one format.
        whole = (SAMPLES / "pyramid.cbddlp").read_bytes()
        expect(PhotonFile.read(self._copy("p.photon", whole)).layer_count).to_equal(50)
        with self.assertRaises(MalformedFile):
            PhotonFile.read(self._copy("p.photon", whole[:-4096]))

    def test_a_slicer_table_is_read_only_if_it_has_a_place_and_a_size(self) -> None:
        for sample, parser, header in (
            ("stairs.ctb", CTBFile, CTBHeader),
            ("stairs.photon", PhotonFile, PhotonHeader),
        ):
            for field in ("slicer_offset", "slicer_size"):
                path = self._with(
                    sample, _offset_of(header, field), struct.pack("<I", 0)
                )
                expect(parser.read(path).slicer_version).to_equal("")

    def test_an_anti_aliased_file_reads_as_before(self) -> None:
        read = CTBFile.read(SAMPLES / "pyramid.cbddlp")
        expect(read.layer_count).to_equal(50)
        expect(len(read.end_byte_offset_by_layer)).to_equal(50)
        expect(max(read.end_byte_offset_by_layer)).to_equal(5862924)

    def test_an_encrypted_layer_described_past_the_end_is_refused(self) -> None:
        whole = bytearray((SAMPLES / "bolts.ctb").read_bytes())
        with open(SAMPLES / "bolts.ctb", "rb") as file:
            _, slicer = ctb_encrypted._read_settings(file)
        for place in (len(whole) - 4, len(whole), 0x7FFFFFFF):
            struct.pack_into("<I", whole, slicer.layer_table_offset, place)
            with self.assertRaises(MalformedFile):
                CTBEncryptedFile.read(self._copy("bolts.ctb", bytes(whole)))

    def test_an_encrypted_layer_reaching_past_the_end_is_refused(self) -> None:
        # The signature only covers the settings, so it still matches.
        whole = bytearray((SAMPLES / "bolts.ctb").read_bytes())
        with open(SAMPLES / "bolts.ctb", "rb") as file:
            _, slicer = ctb_encrypted._read_settings(file)
        layer_offset = struct.unpack_from(
            "<I",
            whole,
            slicer.layer_table_offset
            + _offset_of(ctb_encrypted.CTBLayerPointer, "layer_offset"),
        )[0]
        where = layer_offset + _offset_of(
            ctb_encrypted.CTBEncryptedLayerDef, "encrypted_data_length"
        )
        struct.pack_into("<I", whole, where, 0x7FFFFFF0)
        with self.assertRaises(MalformedFile) as raised:
            CTBEncryptedFile.read(self._copy("bolts.ctb", bytes(whole)))
        expect("layer 1 of" in str(raised.exception)).to_equal(True)

    def test_a_preview_of_absurd_size_is_refused(self) -> None:
        for sample, parser, header, preview in PLAIN:
            whole = (SAMPLES / sample).read_bytes()
            where = struct.unpack_from(
                "<I", whole, _offset_of(header, "high_res_preview_offset")
            )[0]
            for field, value in (
                ("resolution_x", 0x10000),
                ("resolution_y", 0),
                ("image_length", 0x7FFFFFFF),
                ("image_offset", 0x7FFFFFFF),
            ):
                path = self._with(
                    sample, where + _offset_of(preview, field), struct.pack("<I", value)
                )
                with self.assertRaises(MalformedFile):
                    parser.read_preview(path)

    def test_a_preview_header_outside_the_file_is_refused(self) -> None:
        for sample, parser, header, _ in PLAIN:
            path = self._with(
                sample,
                _offset_of(header, "high_res_preview_offset"),
                struct.pack("<I", 0x7FFFFFF0),
            )
            with self.assertRaises(MalformedFile):
                parser.read_preview(path)

    # ---- encrypted CTB ----

    def _encrypted_with(self, **changes: float) -> pathlib.Path:
        """bolts.ctb with fields of its encrypted settings block changed."""
        whole = bytearray((SAMPLES / "bolts.ctb").read_bytes())
        header = CTBEncryptedHeader.unpack_from(bytes(whole))
        start = header.slicer_offset
        end = start + header.slicer_size
        block = bytearray(ctb_encrypted._aes_crypt(bytes(whole[start:end]), False))
        for name, value in changes.items():
            kind = "<f" if isinstance(value, float) else "<I"
            struct.pack_into(kind, block, _offset_of(CTBEncryptedSlicer, name), value)
        whole[start:end] = ctb_encrypted._aes_crypt(bytes(block), True)
        return self._copy("bolts.ctb", bytes(whole))

    def test_the_untouched_encrypted_sample_is_read(self) -> None:
        expect(CTBEncryptedFile.read(self._encrypted_with()).layer_count).to_equal(110)

    def test_an_encrypted_layer_count_the_file_cannot_hold_is_refused(self) -> None:
        for count in (0xFFFFFFFF, 100_001, 60_000):
            with self.assertRaises(MalformedFile):
                CTBEncryptedFile.read(self._encrypted_with(layer_count=count))

    def test_an_encrypted_layer_table_outside_the_file_is_refused(self) -> None:
        with self.assertRaises(MalformedFile):
            CTBEncryptedFile.read(self._encrypted_with(layer_table_offset=0x7FFFFFF0))

    def test_an_encrypted_printer_name_of_absurd_length_is_refused(self) -> None:
        with self.assertRaises(MalformedFile):
            CTBEncryptedFile.read(self._encrypted_with(machine_name_size=0x7FFFFFFF))

    def test_an_encrypted_preview_outside_the_file_is_refused(self) -> None:
        with self.assertRaises(MalformedFile):
            CTBEncryptedFile.read_preview(
                self._encrypted_with(large_preview_offset=0x7FFFFFF0)
            )

    def test_settings_of_an_unexpected_size_are_refused(self) -> None:
        for size in (0, 16, 0x7FFFFFFF):
            path = self._with(
                "bolts.ctb",
                _offset_of(CTBEncryptedHeader, "slicer_size"),
                struct.pack("<I", size),
            )
            with self.assertRaises(MalformedFile):
                CTBEncryptedFile.read(path)
            with self.assertRaises(MalformedFile):
                CTBEncryptedFile.read_preview(path)

    def test_a_signature_with_its_bytes_in_another_order_is_refused(self) -> None:
        # Made of the same bytes, so the same set of values, but not equal.
        whole = bytearray((SAMPLES / "bolts.ctb").read_bytes())
        header = CTBEncryptedHeader.unpack_from(bytes(whole))
        start = header.signature_offset
        expect(whole[start] == whole[start + 1]).to_equal(False)
        whole[start], whole[start + 1] = whole[start + 1], whole[start]
        with self.assertRaises(MalformedFile):
            CTBEncryptedFile.read(self._copy("bolts.ctb", bytes(whole)))

    def test_a_signature_of_an_unexpected_size_is_refused(self) -> None:
        for size in (16, 0x7FFFFFFF):
            path = self._with(
                "bolts.ctb",
                _offset_of(CTBEncryptedHeader, "signature_size"),
                struct.pack("<I", size),
            )
            with self.assertRaises(MalformedFile):
                CTBEncryptedFile.read(path)

    def test_a_file_that_is_not_an_encrypted_ctb_is_refused(self) -> None:
        with self.assertRaises(MalformedFile):
            CTBEncryptedFile.read(SAMPLES / "stairs.ctb")


class FileFormatChoiceTest(TestCase):
    def test_an_unsupported_extension_is_refused_by_name(self) -> None:
        for name in ("notes.txt", "model.stl", "noextension", "archive.ctb.zip"):
            with self.assertRaises(UnsupportedFileFormat):
                get_file_format(name)

    def test_the_extension_is_read_whatever_its_case(self) -> None:
        expect(get_file_format("MODEL.FDG")).to_equal(FDGFile)
        expect(get_file_format("model.Photon")).to_equal(PhotonFile)
