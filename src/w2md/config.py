"""Conversion configuration."""

from dataclasses import dataclass


@dataclass
class Config:
    heading_offset: int = 0
    inline_style: str = "drop"
    assets_mode: str = "folder"
