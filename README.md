# UAT Test Management Tool

A simple web app to run UAT checklists on app submissions, save reviews, re-review apps, approve/archive reviews, and export PDF reports.

## Setup

```bash
cd /path/to/App-UAT-Tool
python -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
source venv/bin/activate   # if using venv
python app.py
```

Then open http://127.0.0.1:5000 in your browser.

Or with Flask CLI:

```bash
export FLASK_APP=app.py
flask run
```

## First use

1. Go to **Checklist** and set up sections (e.g. "Section 1", "Section 2"). Paste criteria into a section (one per line), add items per section, or **import from CSV** (see below). Section names are editable; you can add or remove sections.
2. Click **New review**, enter app metadata, then run through the checklist (Pass/Fail/Partial/NA per item). Criteria are grouped by section.
3. Save progress or Finish review, then Export PDF. Use **Re-review this app** to start a new run for the same app. For completed reviews, choose **Approve** or **Reject**; then use **Archive** to move the review to the Archived tab. The **Runs** page has **Active** and **Archived** tabs.

The UI uses a BigCommerce-inspired style (colors and typography from [BigDesign](https://developer.bigcommerce.com/big-design/)).

### Importing criteria from CSV

In **Checklist**, use **Import from CSV** to add criteria in bulk. The CSV must have two columns:

| Column         | Description                          |
|----------------|--------------------------------------|
| `section_name` | Name of the section (created if missing) |
| `criteria`     | Criterion text (one per row)         |

Example:

```csv
section_name,criteria
"First section","Here is the criteria I want"
"First section","Another criterion in the same section"
"New Section","Only in the new section"
```

If a section name does not exist, a new section is created. If the same criteria text already exists in that section (exact match), that row is skipped.
