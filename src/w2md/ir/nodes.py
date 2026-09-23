"""IR node definitions, independent of both Word and Markdown."""

from dataclasses import dataclass, field


@dataclass
class Text:
    text: str


@dataclass
class Bold:
    children: list


@dataclass
class Italic:
    children: list


@dataclass
class Underline:
    children: list


@dataclass
class Color:
    color: str
    children: list


@dataclass
class Highlight:
    color: str
    children: list


@dataclass
class LineBreak:
    pass


@dataclass
class Image:
    source: str
    alt: str = ""
    src: str = ""


@dataclass
class Paragraph:
    children: list


@dataclass
class Table:
    rows: list
    column_count: int = 0


@dataclass
class Heading:
    level: int
    children: list


@dataclass
class Document:
    blocks: list = field(default_factory=list)
