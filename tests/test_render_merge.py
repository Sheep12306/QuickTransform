"""Renderer tests for merging adjacent inline formatting nodes."""

import unittest

from w2md.ir.nodes import Bold, Document, Heading, Text
from w2md.render.markdown import render


class RenderMergeTest(unittest.TestCase):
    def test_adjacent_bold_runs_merge_into_single_marker_pair(self):
        document = Document(
            blocks=[
                Heading(
                    level=1,
                    children=[
                        Bold([Text("（")]),
                        Bold([Text("杨")]),
                        Bold([Text("）")]),
                        Bold([Text("异形件溢价计算操作费")]),
                    ],
                )
            ]
        )

        markdown = render(document)

        self.assertEqual(markdown.strip(), "# **（杨）异形件溢价计算操作费**")


if __name__ == "__main__":
    unittest.main()
