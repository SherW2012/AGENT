---
name: create-excel
description: Generate an Excel (.xlsx) workbook in the workspace from one or more sheets of rows and cells. Use when the user asks to create, export, or write an Excel spreadsheet, table, or .xlsx file.
version: 0.1.0
display_name: "Excel 表格"
short_description: "生成 .xlsx Excel 表格。"
default_prompt: "使用 create-excel skill 生成一个 Excel 表格：先确认文件名、各工作表名称和表头与数据行，再写入工作目录。"
---

# Create Excel Workbook

Use this skill when the user wants an Excel/.xlsx file produced in the workspace.

## How it works

- Call the `create_excel` tool with a `path` and a list of `sheets`.
- Each sheet is an object: `{ "name": "Sheet1", "rows": [["列A","列B"], ["1","文本"]] }`.
- Cells are strings; values that look like numbers (e.g. `"42"`, `"3.14"`) are
  written as real numbers so Excel can calculate on them.
- Output is standards-based Office Open XML (ECMA-376 / ISO 29500) built with the
  Python standard library only — no third-party dependency and no licensing
  concern.

## Workflow

1. Confirm the file name, the sheet name(s), the header row, and the data rows.
2. Put the header in the first row, then one data row per record.
3. Call `create_excel`; writing a file requires human approval.
4. Tell the user the saved path. Never write patient identifiers or secrets.
