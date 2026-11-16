"""Conversion configuration."""

from dataclasses import dataclass


@dataclass
class Config:
    heading_offset: int = 1
    inline_style: str = "drop"
    assets_mode: str = "folder"
    image_previews: bool = True
    max_upload_bytes: int = 5 * 1024 * 1024
    max_image_dimension: int = 4000
    preview_max_dimension: int = 2000
