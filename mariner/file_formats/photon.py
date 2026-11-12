import pathlib
from dataclasses import dataclass

import png
from typedstruct import LittleEndianStruct, StructType

from mariner.file_formats import SlicedModelFile
from mariner.file_formats.reading import (
    check_layer_count,
    check_layers_fit,
    passes_stored,
    read_preview,
    read_struct,
    read_text,
)


@dataclass(frozen=True)
class PhotonHeader(LittleEndianStruct):
    magic: int = StructType.uint32()  # 00: Always 0x12FD0019
    version: int = StructType.uint32()  # 04: Always 0x01
    bed_size_x_mm: float = StructType.float32()  # 08:
    bed_size_y_mm: float = StructType.float32()
    bed_size_z_mm: float = StructType.float32()
    unknown_01: int = StructType.uint32()  # 14
    unknown_02: int = StructType.uint32()
    height_mm: float = StructType.float32()
    layer_height_mm: float = StructType.float32()  # 20:
    layer_exposure: float = StructType.float32()  # 24: Layer exposure(in seconds)
    bottom_exposure: float = StructType.float32()  # 28: Bottom layers exposure
    layer_off_time: float = StructType.float32()  # 2c: Layer off time(in seconds)
    bottom_count: int = StructType.uint32()  # 30: Number of bottom layers
    resolution_x: int = StructType.uint32()  # 34:
    resolution_y: int = StructType.uint32()  # 38:
    high_res_preview_offset: int = StructType.uint32()
    # 3c: Offset of the high-res preview
    layer_defs_offset: int = StructType.uint32()  # 40: Offset of the layer definitions
    layer_count: int = StructType.uint32()  # 44:
    low_res_preview_offset: int = StructType.uint32()  # 48: Offset of the low-rew prev
    print_time: int = StructType.uint32()  # 4c: In seconds
    projector: int = StructType.uint32()  # 50: 0 = CAST, 1 = LCD_X_MIRROR
    param_offset: int = StructType.uint32()  # 54:
    param_size: int = StructType.uint32()  # 58:
    anti_alias_level: int = StructType.uint32()  # 5c:
    light_pwm: int = StructType.uint16()  # 60:
    bottom_light_pwm: int = StructType.uint16()  # 62:
    encryption_seed: int = StructType.uint32()  # 64:
    slicer_offset: int = StructType.uint32()
    slicer_size: int = StructType.uint32()


@dataclass(frozen=True)
class PhotonParam(LittleEndianStruct):
    bottom_lift_height: float = StructType.float32()  # 00:
    bottom_lift_speed: float = StructType.float32()  # 04:
    lift_height: float = StructType.float32()  # 08:
    lift_speed: float = StructType.float32()  # 0c:
    retract_speed: float = StructType.float32()  # 10:
    volume_ml: float = StructType.float32()  # 14: Volume of resin in ml
    weight_gr: float = StructType.float32()  # 18: resin weight in grams
    cost_dollars: float = StructType.float32()  # 1c: slicers estimated resin cost USD
    bottom_lift_off_time: float = StructType.float32()  # 20
    light_off_time: float = StructType.float32()  # 24:
    bottom_layer_count: int = StructType.uint32()  # 28:
    unknown_01: int = StructType.uint32()  # 2c:
    unknown_02: int = StructType.uint32()  # 30:
    unknown_03: int = StructType.uint32()  # 34:
    unknown_04: int = StructType.uint32()  # 38:


@dataclass(frozen=True)
class PhotonSlicer(LittleEndianStruct):
    skip_0: int = StructType.uint32()
    skip_1: int = StructType.uint32()
    skip_2: int = StructType.uint32()
    skip_3: int = StructType.uint32()
    skip_4: int = StructType.uint32()
    skip_5: int = StructType.uint32()
    skip_6: int = StructType.uint32()
    machine_offset: int = StructType.uint32()
    machine_size: int = StructType.uint32()
    encryption_mode: int = StructType.uint32()
    time_seconds: int = StructType.uint32()
    unknown_01: int = StructType.uint32()
    version_patch: int = StructType.unsigned_char()
    version_minor: int = StructType.unsigned_char()
    version_major: int = StructType.unsigned_char()
    version_release: int = StructType.unsigned_char()
    unknown_02: int = StructType.uint32()
    unknown_03: int = StructType.uint32()
    unknown_04: float = StructType.float32()
    unknown_05: int = StructType.uint32()
    unknown_06: int = StructType.uint32()
    unknown_07: float = StructType.float32()


@dataclass(frozen=True)
class PhotonLayerDef(LittleEndianStruct):
    layer_height_mm: float = StructType.float32()  # 00:
    layer_exposure: float = StructType.float32()  # 04:
    layer_off_time: float = StructType.float32()  # 08:
    image_offset: int = StructType.uint32()  # 0c:
    image_length: int = StructType.uint32()  # 10:
    unknown_01: int = StructType.uint32()  # 14:
    unknown_02: int = StructType.uint32()  # 18:
    unknown_03: int = StructType.uint32()  # 1c:
    unknown_04: int = StructType.uint32()  # 20:


@dataclass(frozen=True)
class PhotonPreview(LittleEndianStruct):
    resolution_x: int = StructType.uint32()
    resolution_y: int = StructType.uint32()
    image_offset: int = StructType.uint32()
    image_length: int = StructType.uint32()
    unknown_01: int = StructType.uint32()
    unknown_02: int = StructType.uint32()
    unknown_03: int = StructType.uint32()
    unknown_04: int = StructType.uint32()


@dataclass(frozen=True)
class PhotonFile(SlicedModelFile):
    @classmethod
    def read(cls, path: pathlib.Path) -> "PhotonFile":
        with open(str(path), "rb") as file:
            photon_header = read_struct(file, PhotonHeader, 0, "header")
            # The first version of the format has no table of slicer
            # settings, and gives 0 as its place. Read from there, the
            # header itself would be taken for the table.
            printer_name = ""
            slicer_version = ""
            if photon_header.slicer_offset and photon_header.slicer_size:
                photon_slicer = read_struct(
                    file, PhotonSlicer, photon_header.slicer_offset, "slicer settings"
                )
                printer_name = read_text(
                    file,
                    photon_slicer.machine_offset,
                    photon_slicer.machine_size,
                    "printer name",
                )
                slicer_version = ".".join(
                    [
                        str(photon_slicer.version_release),
                        str(photon_slicer.version_major),
                        str(photon_slicer.version_minor),
                        str(photon_slicer.version_patch),
                    ]
                )

            layer_def_size = PhotonLayerDef.get_size()
            # The passes after the first are not needed to follow a print,
            # but a file that lacks part of them is as incomplete.
            passes = passes_stored(
                photon_header.magic,
                photon_header.version,
                photon_header.anti_alias_level,
            )
            check_layer_count(
                file,
                photon_header.layer_count,
                photon_header.layer_defs_offset,
                layer_def_size,
                passes,
            )
            entry_count = photon_header.layer_count * passes
            end_byte_offset_by_entry = []
            for layer in range(0, entry_count):
                layer_def = read_struct(
                    file,
                    PhotonLayerDef,
                    photon_header.layer_defs_offset + layer * layer_def_size,
                    "layer table",
                )
                end_byte_offset_by_entry.append(
                    layer_def.image_offset + layer_def.image_length
                )

            check_layers_fit(file, end_byte_offset_by_entry)
            end_byte_offset_by_layer = end_byte_offset_by_entry[
                : photon_header.layer_count
            ]

            return PhotonFile(
                filename=path.name,
                bed_size_mm=(
                    round(photon_header.bed_size_x_mm, 4),
                    round(photon_header.bed_size_y_mm, 4),
                    round(photon_header.bed_size_z_mm, 4),
                ),
                height_mm=photon_header.height_mm,
                layer_height_mm=photon_header.layer_height_mm,
                layer_count=photon_header.layer_count,
                resolution=(photon_header.resolution_x, photon_header.resolution_y),
                print_time_secs=photon_header.print_time,
                end_byte_offset_by_layer=end_byte_offset_by_layer,
                slicer_version=slicer_version,
                printer_name=printer_name,
            )

    @classmethod
    def read_preview(cls, path: pathlib.Path) -> png.Image:
        with open(str(path), "rb") as file:
            photon_header = read_struct(file, PhotonHeader, 0, "header")
            preview = read_struct(
                file,
                PhotonPreview,
                photon_header.high_res_preview_offset,
                "preview header",
            )
            return read_preview(
                file,
                preview.resolution_x,
                preview.resolution_y,
                preview.image_offset,
                preview.image_length,
            )
