from __future__ import annotations

import pathlib
import struct
from dataclasses import dataclass
from typing import BinaryIO, Tuple, Type, Union

import png
from typedstruct import LittleEndianStruct, StructType

from mariner.file_formats import SlicedModelFile
from mariner.file_formats.cipher import xorCipher, computeSHA256Hash
from mariner.file_formats.reading import (
    MalformedFile,
    check_layer_count,
    check_layers_fit,
    read_bytes,
    read_preview,
    read_struct,
    read_text,
    size_of,
)

import base64
from Crypto.Cipher import AES

from mariner.file_formats.ctb import CTBFile

MAGIC_CTB_ENCRYPTED = 0x12FD0107
HASH_LENGTH = 32
BHASH = b"32"

about_software = "UVtools"
secret1 = "hQ36XB6yTk+zO02ysyiowt8yC1buK+nbLWyfY40EXoU="
secret2 = "Wld+ampndVJecmVjYH5cWQ=="
bigfoot: bytes = bytes(
    xorCipher(base64.b64decode(secret1, validate=True), about_software.encode())
)
cookiemonster: bytes = bytes(
    xorCipher(base64.b64decode(secret2, validate=True), about_software.encode())
)


@dataclass(frozen=True)
class CTBEncryptedHeader(LittleEndianStruct):
    magic: int = StructType.uint32()
    slicer_size: int = StructType.uint32()
    slicer_offset: int = StructType.uint32()
    unknown_01: int = StructType.uint32()
    unknown_02: int = StructType.uint32()
    signature_size: int = StructType.uint32()
    signature_offset: int = StructType.uint32()
    unknown_03: int = StructType.uint32()
    unknown_04: int = StructType.uint16()
    unknown_05: int = StructType.uint16()
    unknown_06: int = StructType.uint32()
    unknown_07: int = StructType.uint32()
    unknown_08: int = StructType.uint32()


@dataclass(frozen=True)
class CTBEncryptedSlicer(LittleEndianStruct):
    checksum_value: int = StructType.uint64()
    layer_table_offset: int = StructType.uint32()
    display_width: float = StructType.float32()
    display_height: float = StructType.float32()
    machine_z: float = StructType.float32()
    unknown_01: int = StructType.uint32()
    unknown_02: int = StructType.uint32()
    total_height_mm: float = StructType.float32()
    layer_height_mm: float = StructType.float32()
    exposure_time: float = StructType.float32()
    bottom_exposure_time: float = StructType.float32()
    light_off_delay: float = StructType.float32()
    bottom_layer_count: int = StructType.uint32()
    resolution_x: int = StructType.uint32()
    resolution_y: int = StructType.uint32()
    layer_count: int = StructType.uint32()
    large_preview_offset: int = StructType.uint32()
    small_preview_offset: int = StructType.uint32()
    print_time: int = StructType.uint32()
    projector_type: int = StructType.uint32()
    bottom_lift_height: float = StructType.float32()
    bottom_lift_speed: float = StructType.float32()
    lift_height: float = StructType.float32()
    lift_speed: float = StructType.float32()
    retract_speed: float = StructType.float32()
    material_mm: float = StructType.float32()
    material_grams: float = StructType.float32()
    material_cost: float = StructType.float32()
    bottom_light_off_delay: float = StructType.float32()
    unknown_03: int = StructType.uint32()
    light_pwm: int = StructType.uint16()
    bottom_light_pwm: int = StructType.uint16()
    layer_xor_key: int = StructType.uint32()
    bottom_lift_height2: float = StructType.float32()
    bottom_lift_speed2: float = StructType.float32()
    lift_height2: float = StructType.float32()
    lift_speed2: float = StructType.float32()
    retract_height2: float = StructType.float32()
    retract_speed2: float = StructType.float32()
    rest_time_after_lift: float = StructType.float32()
    machine_name_offset: int = StructType.uint32()
    machine_name_size: int = StructType.uint32()
    per_layer_settings: int = StructType.uint32()
    unknown_04: int = StructType.uint32()
    unknown_05: int = StructType.uint32()
    rest_time_after_retract: float = StructType.float32()
    rest_time_after_lift2: float = StructType.float32()
    transition_layer_count: int = StructType.uint32()
    bottom_retract_speed: float = StructType.float32()
    bottom_retract_speed2: float = StructType.float32()
    padding1: int = StructType.uint32()
    four1: float = StructType.float32()
    padding2: int = StructType.uint32()
    four2: float = StructType.float32()
    rest_time_after_retract2: float = StructType.float32()
    rest_time_after_lift3: float = StructType.float32()
    rest_time_before_lift: float = StructType.float32()
    bottom_retract_height2: float = StructType.float32()
    unknown_06: int = StructType.uint32()
    unknown_07: int = StructType.uint32()
    unknown_08: int = StructType.uint32()
    last_layer_index: int = StructType.uint32()
    padding3: int = StructType.uint32()
    padding4: int = StructType.uint32()
    padding5: int = StructType.uint32()
    padding6: int = StructType.uint32()
    disclaimer_offset: int = StructType.uint32()
    disclaimer_size: int = StructType.uint32()
    padding7: int = StructType.uint32()
    padding8: int = StructType.uint32()
    padding9: int = StructType.uint32()
    padding10: int = StructType.uint32()
    # machine_name: bytes = StructType.chars()


@dataclass(frozen=True)
class CTBLayerPointer(LittleEndianStruct):
    layer_offset: int = StructType.uint32()
    padding_01: int = StructType.uint32()
    layer_table_size: int = StructType.uint32()
    padding_02: int = StructType.uint32()


@dataclass(frozen=True)
class CTBEncryptedLayerDef(LittleEndianStruct):
    table_size: int = StructType.uint32()
    position_z: float = StructType.float32()
    exposure_time: float = StructType.float32()
    light_off_delay: float = StructType.float32()
    layer_def_offset: int = StructType.uint32()
    unknown_02: int = StructType.uint32()
    data_length: int = StructType.uint32()
    unknown_03: int = StructType.uint32()
    encrypted_data_offset: int = StructType.uint32()
    encrypted_data_length: int = StructType.uint32()
    lift_height: float = StructType.float32()
    lift_speed: float = StructType.float32()
    lift_height2: float = StructType.float32()
    lift_speed2: float = StructType.float32()
    retract_speed: float = StructType.float32()
    retract_height2: float = StructType.float32()
    retract_speed2: float = StructType.float32()
    rest_time_before_lift: float = StructType.float32()
    rest_time_after_lift: float = StructType.float32()
    rest_time_after_retract: float = StructType.float32()
    light_pwm: float = StructType.float32()
    unknown_06: int = StructType.uint32()


@dataclass(frozen=True)
class CTBPreview(LittleEndianStruct):
    resolution_x: int = StructType.uint32()
    resolution_y: int = StructType.uint32()
    image_offset: int = StructType.uint32()
    image_length: int = StructType.uint32()


def check_encrypted(filename: str) -> Type[Union[CTBEncryptedFile, CTBFile]]:
    """Which of the two CTB parsers the file at *filename* is for.

    Told by the first four bytes. A file too short to have them is left to
    the plain parser, which refuses it.
    """
    with open(filename, "rb") as file:
        magic = file.read(4)
    if len(magic) == 4 and struct.unpack("<I", magic)[0] == MAGIC_CTB_ENCRYPTED:
        return CTBEncryptedFile
    return CTBFile


def _aes_crypt(enc: bytes, encrypt: bool) -> bytes:
    Cipher = AES.new(bytes(bigfoot), AES.MODE_CBC, bytes(cookiemonster))

    temp = bytearray()
    temp += enc
    if len(enc) % 16 != 0:
        temp += (16 - len(enc) % 16) * b"X"

    if encrypt:
        return Cipher.encrypt(bytes(temp))
    else:
        return Cipher.decrypt(bytes(temp))


def _read_settings(file: BinaryIO) -> Tuple[CTBEncryptedHeader, CTBEncryptedSlicer]:
    """The header of an encrypted CTB file and its decrypted settings block."""
    ctb_header = read_struct(file, CTBEncryptedHeader, 0, "header")
    if ctb_header.magic != MAGIC_CTB_ENCRYPTED:
        raise MalformedFile("not an encrypted CTB file")
    # The settings block has one size. A file that claims another is not
    # read on its word: the block is decrypted whole, in memory.
    if ctb_header.slicer_size != CTBEncryptedSlicer.get_size():
        raise MalformedFile(
            f"the settings block claims to be {ctb_header.slicer_size} bytes"
        )
    encrypted_block = read_bytes(
        file, ctb_header.slicer_offset, ctb_header.slicer_size, "settings block"
    )
    try:
        ctb_slicer = CTBEncryptedSlicer.unpack(_aes_crypt(encrypted_block, False))
    except struct.error as error:
        raise MalformedFile("the settings block cannot be read") from error
    return (ctb_header, ctb_slicer)


def _check_signature(
    file: BinaryIO, ctb_header: CTBEncryptedHeader, ctb_slicer: CTBEncryptedSlicer
) -> None:
    """Refuse a file whose signature is not the one its settings call for.

    The signature is the encrypted SHA-256 of the checksum stored in the
    settings block. It is compared byte for byte: comparing the two as
    sets of byte values, as was done before, accepts nearly anything.
    """
    checksum_bytes = ctb_slicer.checksum_value.to_bytes(8, "little")
    expected = _aes_crypt(computeSHA256Hash(checksum_bytes), True)

    # The header says where the signature is, so use it. Seeking back from
    # the end instead assumes the signature is the last thing in the file,
    # which breaks on writers that append anything after it.
    if ctb_header.signature_offset and ctb_header.signature_size:
        if ctb_header.signature_size != HASH_LENGTH:
            raise MalformedFile(
                f"the signature claims to be {ctb_header.signature_size} bytes"
            )
        offset = ctb_header.signature_offset
    else:
        offset = size_of(file) - HASH_LENGTH
    if read_bytes(file, offset, HASH_LENGTH, "signature") != expected:
        raise MalformedFile("the signature does not match the settings")


@dataclass(frozen=True)
class CTBEncryptedFile(SlicedModelFile):
    @classmethod
    def read(cls, path: pathlib.Path) -> "CTBEncryptedFile":
        with open(str(path), "rb") as file:
            ctb_header, ctb_slicer = _read_settings(file)
            _check_signature(file, ctb_header, ctb_slicer)
            printer_name = read_text(
                file,
                ctb_slicer.machine_name_offset,
                ctb_slicer.machine_name_size,
                "printer name",
            )

            pointer_size = CTBLayerPointer.get_size()
            check_layer_count(
                file,
                ctb_slicer.layer_count,
                ctb_slicer.layer_table_offset,
                pointer_size,
            )
            end_byte_offset_by_layer = []
            stored_ends = []
            for layer in range(0, ctb_slicer.layer_count):
                pointer = read_struct(
                    file,
                    CTBLayerPointer,
                    ctb_slicer.layer_table_offset + layer * pointer_size,
                    "layer table",
                )
                layer_def = read_struct(
                    file, CTBEncryptedLayerDef, pointer.layer_offset, "layer"
                )
                # Where the layer ends in the file, whether or not part of
                # it is stored encrypted.
                stored_ends.append(layer_def.layer_def_offset + layer_def.data_length)
                enc_end = (
                    layer_def.encrypted_data_offset + layer_def.encrypted_data_length
                )
                if enc_end > 0:
                    end_byte_offset_by_layer.append(enc_end)
                else:
                    end_byte_offset_by_layer.append(
                        layer_def.layer_def_offset + layer_def.data_length
                    )

            check_layers_fit(file, end_byte_offset_by_layer)
            check_layers_fit(file, stored_ends)

            return CTBEncryptedFile(
                filename=path.name,
                bed_size_mm=(
                    round(ctb_slicer.display_width, 4),
                    round(ctb_slicer.display_height, 4),
                    round(ctb_slicer.machine_z, 4),
                ),
                height_mm=ctb_slicer.total_height_mm,
                layer_height_mm=ctb_slicer.layer_height_mm,
                layer_count=ctb_slicer.layer_count,
                resolution=(ctb_slicer.resolution_x, ctb_slicer.resolution_y),
                print_time_secs=ctb_slicer.print_time,
                end_byte_offset_by_layer=end_byte_offset_by_layer,
                # This format does not carry the version of the slicer.
                slicer_version="1.1.9.1",
                printer_name=printer_name,
            )

    @classmethod
    def read_preview(cls, path: pathlib.Path) -> png.Image:
        with open(str(path), "rb") as file:
            _, ctb_slicer = _read_settings(file)
            preview = read_struct(
                file, CTBPreview, ctb_slicer.large_preview_offset, "preview header"
            )
            return read_preview(
                file,
                preview.resolution_x,
                preview.resolution_y,
                preview.image_offset,
                preview.image_length,
            )
