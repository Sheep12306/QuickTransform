"""Document-order image reference iteration shared by parser and extractor.

Word may wrap modern DrawingML in ``mc:Choice`` with an old VML copy in
``mc:Fallback``.  Both describe the *same* visual image, so only the preferred
representation is yielded when a choice exists.
"""

from .ns import A_NS, MC_NS, R_NS, V_NS


A = "{%s}" % A_NS
R = "{%s}" % R_NS
V = "{%s}" % V_NS
MC = "{%s}" % MC_NS


def iter_image_references(container):
    """Yield ``(element, relationship_id, kind)`` in document order."""

    for child in container:
        if not isinstance(child.tag, str):
            continue

        if child.tag == MC + "AlternateContent":
            has_choice = any(grand.tag == MC + "Choice" for grand in child)
            for grand in child:
                if grand.tag == MC + "Fallback" and has_choice:
                    continue
                yield from iter_image_references(grand)
            continue

        if child.tag == A + "blip":
            embed = child.get(R + "embed")
            link = child.get(R + "link")
            yield child, embed or link, "drawingml"
        elif child.tag == V + "imagedata":
            yield child, child.get(R + "id"), "vml"

        yield from iter_image_references(child)
