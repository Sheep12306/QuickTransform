"""Document-order image and embedded-object reference iteration.

Word may wrap modern DrawingML in ``mc:Choice`` with an old VML copy in
``mc:Fallback``.  Both describe the *same* visual image, so only the preferred
representation is yielded when a choice exists.

Embedded Word documents, videos, OLE packages and HTML chunks (``w:object``,
``w:altChunk``, ``a:videoFile``) are reported as ``embedded`` instead of as
images.  Their preview icons / poster frames are skipped so the extraction
stage never treats them as replaceable pictures.
"""

from .ns import A_NS, MC_NS, O_NS, R_NS, V_NS, W_NS


A = "{%s}" % A_NS
MC = "{%s}" % MC_NS
O = "{%s}" % O_NS
R = "{%s}" % R_NS
V = "{%s}" % V_NS
W = "{%s}" % W_NS

EMBEDDED_TAGS = {
    W + "altChunk",
    W + "object",
    W + "control",
    W + "objectEmbed",
    O + "OLEObject",
    A + "videoFile",
}


def iter_media_references(container):
    """Yield ``(element, relationship_id, kind)`` in document order.

    ``kind`` is ``drawingml`` / ``vml`` for images and ``embedded`` for Word
    documents, videos, OLE objects and HTML chunks.
    """

    for child in container:
        if not isinstance(child.tag, str):
            continue

        if child.tag == MC + "AlternateContent":
            has_choice = any(grand.tag == MC + "Choice" for grand in child)
            for grand in child:
                if grand.tag == MC + "Fallback" and has_choice:
                    continue
                yield from iter_media_references(grand)
            continue

        if child.tag == W + "altChunk":
            yield child, child.get(R + "id"), "embedded"
            continue

        if child.tag == W + "object":
            marker, relationship_id = _first_embedded_ref(child)
            yield marker, relationship_id, "embedded"
            continue

        if child.tag == W + "pict" and _contains_embedded(child):
            marker, relationship_id = _first_embedded_ref(child)
            yield marker, relationship_id, "embedded"
            continue

        if child.tag == W + "drawing" and _contains_video(child):
            marker, relationship_id = _first_embedded_ref(child)
            yield marker, relationship_id, "embedded"
            continue

        if child.tag in (W + "control", W + "objectEmbed"):
            yield child, child.get(R + "id"), "embedded"
            continue

        if child.tag == O + "OLEObject":
            yield child, child.get(R + "id"), "embedded"
            continue

        if child.tag == A + "videoFile":
            yield child, child.get(R + "link"), "embedded"
            continue

        if child.tag == A + "blip":
            embed = child.get(R + "embed")
            link = child.get(R + "link")
            yield child, embed or link, "drawingml"
        elif child.tag == V + "imagedata":
            yield child, child.get(R + "id"), "vml"

        yield from iter_media_references(child)


def iter_image_references(container):
    """Yield only real image references (used by the Markdown parser)."""

    for element, relationship_id, kind in iter_media_references(container):
        if kind != "embedded":
            yield element, relationship_id, kind


def _contains_embedded(container):
    for element in container.iter():
        if isinstance(element.tag, str) and element.tag in (
            O + "OLEObject",
            W + "control",
            W + "objectEmbed",
        ):
            return True
    return False


def _contains_video(container):
    for element in container.iter():
        if isinstance(element.tag, str) and element.tag == A + "videoFile":
            return True
    return False


def _first_embedded_ref(container):
    for element in container.iter():
        if not isinstance(element.tag, str):
            continue
        if element.tag == O + "OLEObject":
            return container, element.get(R + "id")
        if element.tag in (W + "control", W + "objectEmbed"):
            return container, element.get(R + "id")
        if element.tag == A + "videoFile":
            return container, element.get(R + "link")
    return container, container.get(R + "id")
