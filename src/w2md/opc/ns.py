"""OOXML namespace constants."""

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PIC_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"
V_NS = "urn:schemas-microsoft-com:vml"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"

# In-memory marker written by the image extractor before the document is
# parsed.  It lets the parser attach the exact placeholder to each occurrence
# instead of relying on a second traversal staying in the same order.
QT_IMAGE_NS = "urn:quicktransform:image"
IMAGE_PLACEHOLDER_ATTR = "{%s}placeholder" % QT_IMAGE_NS
