---
name: create-ppt
description: Generate a PowerPoint (.pptx) deck in the workspace from a list of slides with titles and bullet points. Use when the user asks to create, export, or write a PPT, slides, or .pptx file.
version: 0.1.0
display_name: "PPT 演示文稿"
short_description: "生成 .pptx 演示文稿。"
default_prompt: "使用 create-ppt skill 生成一份 PPT：先确认文件名和每页的标题与要点，再写入工作目录。"
---

# Create PowerPoint Deck

Use this skill when the user wants a PowerPoint/.pptx file produced in the workspace.

## How it works

- Call the `create_powerpoint` tool with a `path` and a list of `slides`.
- Each slide is an object: `{ "title": "...", "bullets": ["point 1", "point 2"] }`.
- Output is standards-based Office Open XML (ECMA-376 / ISO 29500) built with the
  Python standard library only — no third-party dependency and no licensing
  concern.

## Workflow

1. Confirm the file name and the per-slide title + key points.
2. Keep bullets concise; one idea per bullet.
3. Call `create_powerpoint`; writing a file requires human approval.
4. Tell the user the saved path. Never write patient identifiers or secrets into
   a deck.
