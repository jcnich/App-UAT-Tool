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

1. Go to **Checklist** and set up sections (e.g. "Section 1", "Section 2"). Paste criteria into a section (one per line), or add items per section. Section names are editable; you can add or remove sections.
2. Click **New review**, enter app metadata, then run through the checklist (Pass/Fail/Partial/NA per item). Criteria are grouped by section.
3. Save progress or Finish review, then Export PDF. Use **Re-review this app** to start a new run for the same app. For completed reviews, choose **Approve** or **Reject**; then use **Archive** to move the review to the Archived tab. The **Runs** page has **Active** and **Archived** tabs.

The UI uses a BigCommerce-inspired style (colors and typography from [BigDesign](https://developer.bigcommerce.com/big-design/)).

## Renaming the project folder

If you rename this project folder (e.g. from `Cursor-Tutorial` to `App-UAT-Tool`):

1. **Rename the folder** in Finder or in Terminal:
   ```bash
   cd /path/to/parent
   mv Cursor-Tutorial App-UAT-Tool
   cd App-UAT-Tool
   ```

2. **Recreate the virtual environment**, because the existing `venv` stores absolute paths to the old folder:
   ```bash
   rm -rf venv
   python3 -m venv venv
   source venv/bin/activate   # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

   Alternatively, you can edit `venv/bin/activate` (and `venv/bin/activate.csh`, `venv/bin/activate.fish` if you use them) and replace the old project path with the new one. The same path may appear in `venv/bin/pip`, `venv/bin/flask`, etc.; update those shebang lines if you run them directly.
