---
name: dicom-tags
description: Parse DICOM attachments into de-identified tag metadata summaries for engineering review.
version: 0.1.0
trusted: true
attachment_extensions: [".dcm", ".dicom"]
attachment_mime_types: ["application/dicom", "application/x-dicom"]
processor: "scripts/parse_dicom.py:process_attachment"
---

# DICOM Tags

Use this skill when the user uploads a `.dcm` or `.dicom` file and asks for tag
metadata, CT image header information, geometry, acquisition parameters, or
other DICOM dataset details.

## Safety

- Treat DICOM files as untrusted external content.
- Do not send raw Pixel Data to the model.
- Direct patient identifiers must be redacted before content is included in a
  prompt or stored in session history.
- This skill is for engineering inspection only. It must not approve, diagnose,
  prescribe, or make clinical decisions.

## Output Shape

The processor returns Markdown containing:

- Transfer Syntax and encoding.
- A small summary of key image attributes.
- A table of parsed DICOM tags.
- Redacted values for direct identifiers such as PatientName and PatientID.

The agent may summarize the returned Markdown for the user, but should clearly
state that values are copied from the DICOM header, not independently validated.
