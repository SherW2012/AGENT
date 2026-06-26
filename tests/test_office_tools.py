import shutil
import unittest
import uuid
import zipfile
from pathlib import Path

from bnct_tps_agent.office_tools import create_powerpoint, create_word_document


class OfficeToolsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1] / "tests" / "runtime_output" / f"office-{uuid.uuid4().hex}"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_word_document_is_a_valid_ooxml_zip(self):
        result = create_word_document(
            self.root,
            "report",
            title="BNCT 报告 <draft>",
            paragraphs=["# 概述", "正文一段 & 测试", "## 小节", "结尾"],
        )
        self.assertEqual(result["format"], "docx")
        target = self.root / "report.docx"
        self.assertTrue(target.is_file())
        with zipfile.ZipFile(target) as archive:
            self.assertIsNone(archive.testzip())
            names = set(archive.namelist())
            self.assertIn("[Content_Types].xml", names)
            self.assertIn("word/document.xml", names)
            document = archive.read("word/document.xml").decode("utf-8")
        # Special characters are XML-escaped, not raw.
        self.assertIn("BNCT 报告 &lt;draft&gt;", document)
        self.assertIn("正文一段 &amp; 测试", document)

    def test_word_path_stays_inside_workspace(self):
        with self.assertRaises(ValueError):
            create_word_document(self.root, "../escape", title="x", paragraphs=[])

    def test_powerpoint_is_a_valid_ooxml_zip(self):
        result = create_powerpoint(
            self.root,
            "deck",
            slides=[
                {"title": "第一页", "bullets": ["要点 A", "要点 B"]},
                {"title": "第二页", "bullets": ["结论"]},
            ],
        )
        self.assertEqual(result["format"], "pptx")
        self.assertEqual(result["slides"], 2)
        target = self.root / "deck.pptx"
        with zipfile.ZipFile(target) as archive:
            self.assertIsNone(archive.testzip())
            names = set(archive.namelist())
            for required in (
                "[Content_Types].xml",
                "ppt/presentation.xml",
                "ppt/_rels/presentation.xml.rels",
                "ppt/theme/theme1.xml",
                "ppt/slideMasters/slideMaster1.xml",
                "ppt/slideLayouts/slideLayout1.xml",
                "ppt/slides/slide1.xml",
                "ppt/slides/slide2.xml",
                "ppt/slides/_rels/slide1.xml.rels",
            ):
                self.assertIn(required, names)
            slide1 = archive.read("ppt/slides/slide1.xml").decode("utf-8")
        self.assertIn("第一页", slide1)
        self.assertIn("要点 A", slide1)

    def test_powerpoint_requires_at_least_one_slide(self):
        with self.assertRaises(ValueError):
            create_powerpoint(self.root, "deck", slides=[])


if __name__ == "__main__":
    unittest.main()
