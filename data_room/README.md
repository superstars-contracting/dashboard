# Data Room — SC-2601

Central repository for all project documents, permits, and regulatory references.

## Folder Structure

```
data_room/
  permits/              Project permits, variances, and licensing
    SC-2601/            Permits specific to SC-2601
  drawings/             Architectural and engineering drawings
    SC-2601/            Drawing sets for SC-2601
  cd5_approvals/        CD-5 (Agency) approval documents
    SC-2601/            CD-5 approvals for SC-2601
  specs/                Specifications and technical standards
    SC-2601/            Spec sections for SC-2601
  dob_codes/            NYC DOB and regulatory compliance references (project-agnostic)
```

## File Organization

Each project has its own subfolder under `permits/`, `drawings/`, `cd5_approvals/`, and `specs/`. Actual PDF files replace the `.placeholder` files once delivered by architects, engineers, or agencies.

The `dob_codes/` folder contains regulatory references that apply across all projects — these are not project-specific, so there is no SC-2601 subfolder.

File paths in the workbook's Permits Library, Document Library, and DOB Compliance Reference sheets point to these locations. When real files arrive (from NYC DOB downloads, architect submittals, engineer deliveries), they are placed in the appropriate folder and override the placeholder.

## Workbook Integration

Three sheets in Daily_Construction_Report.xlsx reference this data room:
- **Permits Library**: Track permits, licenses, and variances. "File Path" column links to `permits/` files.
- **Document Library**: Catalog drawings, CD-5 approvals, and specifications. "File Path" column links to `drawings/`, `cd5_approvals/`, and `specs/` files.
- **DOB Compliance Reference**: Maintain regulatory references and compliance rules. "File Path" column links to `dob_codes/` files.

## Status

As of 2026-05-05:
- Permits Library: 5 active permits documented (file placeholders)
- Document Library: 8 drawings + approvals documented (file placeholders)
- DOB Codes: 7 regulatory references queued for download (pending)
