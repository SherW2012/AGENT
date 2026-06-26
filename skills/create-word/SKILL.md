---
name: create-word
description: Generate a Word (.docx) document in the workspace from a title and structured paragraphs. Use when the user asks to create, export, or write a Word document, report, or .docx file.
version: 0.1.0
display_name: "Word 文档"
short_description: "生成 .docx Word 文档。"
default_prompt: "使用 create-word skill 生成一份 Word 文档：先确认文件名、标题和章节要点，再写入工作目录。"
---

# Create Word Document

Use this skill when the user wants a Word/.docx file produced in the workspace.

## How it works

- Call the `create_word_document` tool with a `path`, a `title`, and a list of
  `paragraphs`.
- A paragraph beginning with `# ` becomes a level-1 heading and `## ` a level-2
  heading; everything else is a normal paragraph.
- Output is standards-based Office Open XML (ECMA-376 / ISO 29500) built with the
  Python standard library only — no third-party dependency and no licensing
  concern.

## Workflow

1. Confirm the file name, document title, and the main sections/points.
2. Draft the content as a list of paragraphs (use `# `/`## ` for headings).
3. Call `create_word_document`; writing a file requires human approval.
4. Tell the user the saved path and remind them values are author-provided, not
   independently verified. Never write patient identifiers or secrets.
