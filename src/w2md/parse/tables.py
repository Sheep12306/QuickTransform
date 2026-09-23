"""Table parsing: Word tables to a normalized cell grid."""

from ..ir.nodes import LineBreak, Table
from ..opc.ns import W_NS
from . import inline


W = "{%s}" % W_NS


def parse_table(tbl_el):
    column_count = _column_count(tbl_el)
    rows = []
    merge_bank = {}

    for tr in tbl_el.findall(W + "tr"):
        row = []
        col = 0
        for tc in tr.findall(W + "tc"):
            tcpr = tc.find(W + "tcPr")
            span = _grid_span(tcpr)
            vmerge = _v_merge(tcpr)

            if vmerge == "continue":
                content = merge_bank.get(col, [])
            else:
                content = _parse_cell(tc)
                if vmerge == "restart":
                    for offset in range(span):
                        merge_bank[col + offset] = content

            for _ in range(span):
                row.append(content)
                col += 1

        rows.append(row)

    effective_count = column_count or max((len(row) for row in rows), default=0)
    for row in rows:
        while len(row) < effective_count:
            row.append([])

    return Table(rows=rows, column_count=effective_count)


def _column_count(tbl_el):
    grid = tbl_el.find(W + "tblGrid")
    if grid is not None:
        cols = grid.findall(W + "gridCol")
        if cols:
            return len(cols)
    return 0


def _grid_span(tcpr):
    if tcpr is None:
        return 1
    span = tcpr.find(W + "gridSpan")
    if span is None:
        return 1
    try:
        return max(1, int(span.get(W + "val")))
    except (TypeError, ValueError):
        return 1


def _v_merge(tcpr):
    if tcpr is None:
        return None
    vmerge = tcpr.find(W + "vMerge")
    if vmerge is None:
        return None
    if vmerge.get(W + "val") == "continue":
        return "continue"
    return "restart"


def _parse_cell(tc):
    children = []
    paragraphs = tc.findall(W + "p")
    for index, p_el in enumerate(paragraphs):
        if index:
            children.append(LineBreak())
        children.extend(inline.parse_paragraph_runs(p_el))
    return children
