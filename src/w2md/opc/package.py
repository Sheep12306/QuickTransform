"""Read-only access to the OPC package that makes up a .docx file."""

from pathlib import Path
import zipfile

from lxml import etree


DOCUMENT_PART = "word/document.xml"
DOCUMENT_RELS_PART = "word/_rels/document.xml.rels"
STYLES_PART = "word/styles.xml"
NUMBERING_PART = "word/numbering.xml"


class OpcPackage:
    def __init__(self, path):
        self.path = Path(path)
        self._zip = zipfile.ZipFile(self.path, "r")

    def part_names(self):
        return set(self._zip.namelist())

    def has_part(self, name):
        return name in self._zip.namelist()

    def read_part(self, name):
        return self._zip.read(name)

    def read_xml(self, name):
        return etree.fromstring(self._zip.read(name))

    def read_document_relationships(self):
        root = etree.fromstring(self._zip.read(DOCUMENT_RELS_PART))
        relationships = {}
        for rel in root:
            relationships[rel.get("Id")] = rel.get("Target")
        return relationships

    def close(self):
        self._zip.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
