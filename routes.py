"""Flask routes for UAT Test Management Tool."""
import csv
from io import BytesIO, TextIOWrapper

from flask import (
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from database import RESULTS, get_db


def register_routes(app):
    """Register all routes on the Flask app."""

    def _build_reviews_list(rows):
        """Build list of review dicts with progress and status_display."""
        status_display_map = {
            "in_progress": "In Review",
            "completed": "Completed",
            "approved": "Approved",
            "rejected": "Rejected",
        }
        reviews = []
        for row in rows:
            total = row["total"] or 0
            filled = row["filled"] or 0
            if total == 0:
                progress = "—"
            else:
                pct = 100 * filled // total
                progress = f"{filled}/{total} ({pct}%)"
            status = row["status"] or "in_progress"
            reviews.append(
                {
                    "id": row["id"],
                    "app_name": row["app_name"],
                    "app_id": row["app_id"],
                    "date": row["date"],
                    "status": status,
                    "status_display": status_display_map.get(status, status),
                    "created_at": row["created_at"],
                    "progress": progress,
                }
            )
        return reviews

    @app.route("/")
    def index():
        """Runs overview: Active and Archived tabs."""
        db = get_db()
        tab = request.args.get("tab", "active")
        base_sql = """
            SELECT r.id, r.app_name, r.app_id, r.date, r.status, r.created_at,
                   (SELECT COUNT(*) FROM review_result rr WHERE rr.review_id = r.id AND rr.result IS NOT NULL) AS filled,
                   (SELECT COUNT(*) FROM checklist) AS total
            FROM review r
            WHERE r.archived = ?
            ORDER BY r.created_at DESC
        """
        rows_active = db.execute(base_sql, (0,)).fetchall()
        rows_archived = db.execute(base_sql, (1,)).fetchall()
        reviews_active = _build_reviews_list(rows_active)
        reviews_archived = _build_reviews_list(rows_archived)
        return render_template(
            "index.html",
            reviews_active=reviews_active,
            reviews_archived=reviews_archived,
            tab=tab,
        )

    @app.route("/bulk-archive", methods=["POST"])
    def bulk_archive():
        """Move selected reviews to Archived (set archived=1)."""
        review_ids = request.form.getlist("review_ids", type=int)
        if review_ids:
            db = get_db()
            placeholders = ",".join("?" * len(review_ids))
            db.execute(
                f"UPDATE review SET archived = 1 WHERE id IN ({placeholders})",
                review_ids,
            )
            db.commit()
            flash(f"Archived {len(review_ids)} review(s).")
        return redirect(url_for("index", tab="active"))

    @app.route("/bulk-unarchive", methods=["POST"])
    def bulk_unarchive():
        """Move selected reviews back to Active (set archived=0)."""
        review_ids = request.form.getlist("review_ids", type=int)
        if review_ids:
            db = get_db()
            placeholders = ",".join("?" * len(review_ids))
            db.execute(
                f"UPDATE review SET archived = 0 WHERE id IN ({placeholders})",
                review_ids,
            )
            db.commit()
            flash(f"Unarchived {len(review_ids)} review(s).")
        return redirect(url_for("index", tab="archived"))

    @app.route("/bulk-delete", methods=["POST"])
    def bulk_delete():
        """Permanently delete selected archived reviews. Only deletes rows where archived=1."""
        review_ids = request.form.getlist("review_ids", type=int)
        if review_ids:
            db = get_db()
            placeholders = ",".join("?" * len(review_ids))
            cur = db.execute(
                f"DELETE FROM review WHERE id IN ({placeholders}) AND archived = 1",
                review_ids,
            )
            db.commit()
            deleted = cur.rowcount
            if deleted:
                flash(f"Permanently deleted {deleted} review(s).")
        return redirect(url_for("index", tab="archived"))

    @app.route("/checklist", methods=["GET", "POST"])
    def checklist_edit():
        """View/edit checklist: sections and items. Paste into section, add/rename/remove sections, add/remove/reorder items."""
        db = get_db()
        if request.method == "POST":
            action = request.form.get("action")
            if action == "paste":
                section_id = request.form.get("section_id", type=int)
                text = request.form.get("checklist_text", "").strip()
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                if section_id and lines:
                    max_order = db.execute(
                        "SELECT COALESCE(MAX(sort_order), -1) FROM checklist WHERE section_id = ?",
                        (section_id,),
                    ).fetchone()[0] or -1
                    for i, line in enumerate(lines):
                        db.execute(
                            "INSERT INTO checklist (section_id, sort_order, text) VALUES (?, ?, ?)",
                            (section_id, max_order + 1 + i, line),
                        )
                    db.commit()
                    flash("Items added to section from pasted text.")
                return redirect(url_for("checklist_edit"))
            if action == "import_csv":
                f = request.files.get("csv_file")
                if not f or not f.filename or not f.filename.lower().endswith((".csv", ".txt")):
                    flash("Please upload a CSV file.")
                    return redirect(url_for("checklist_edit"))
                try:
                    stream = TextIOWrapper(f.stream, encoding="utf-8", errors="replace")
                    reader = csv.DictReader(stream)
                    if "section_name" not in reader.fieldnames or "criteria" not in reader.fieldnames:
                        flash("CSV must have columns: section_name, criteria")
                        return redirect(url_for("checklist_edit"))
                except Exception:
                    flash("Could not read CSV. Use UTF-8 and columns: section_name, criteria")
                    return redirect(url_for("checklist_edit"))
                db = get_db()
                sections_by_name = {
                    row["name"]: row["id"]
                    for row in db.execute(
                        "SELECT id, name FROM checklist_section"
                    ).fetchall()
                }
                max_section_order = db.execute(
                    "SELECT COALESCE(MAX(sort_order), -1) FROM checklist_section"
                ).fetchone()[0] or -1
                added = 0
                skipped = 0
                new_sections = 0
                for row in reader:
                    sec_name = (row.get("section_name") or "").strip()
                    criteria_text = (row.get("criteria") or "").strip()
                    if not sec_name or not criteria_text:
                        continue
                    if sec_name not in sections_by_name:
                        max_section_order += 1
                        cur = db.execute(
                            "INSERT INTO checklist_section (sort_order, name) VALUES (?, ?)",
                            (max_section_order, sec_name),
                        )
                        db.commit()
                        sec_id = cur.lastrowid
                        sections_by_name[sec_name] = sec_id
                        new_sections += 1
                    else:
                        sec_id = sections_by_name[sec_name]
                    exists = db.execute(
                        "SELECT 1 FROM checklist WHERE section_id = ? AND text = ?",
                        (sec_id, criteria_text),
                    ).fetchone()
                    if exists:
                        skipped += 1
                        continue
                    max_order = db.execute(
                        "SELECT COALESCE(MAX(sort_order), -1) FROM checklist WHERE section_id = ?",
                        (sec_id,),
                    ).fetchone()[0] or -1
                    db.execute(
                        "INSERT INTO checklist (section_id, sort_order, text) VALUES (?, ?, ?)",
                        (sec_id, max_order + 1, criteria_text),
                    )
                    added += 1
                db.commit()
                msg = f"Imported {added} criteria."
                if new_sections:
                    msg += f" Created {new_sections} new section(s)."
                if skipped:
                    msg += f" Skipped {skipped} duplicate(s) (exact match in same section)."
                flash(msg)
                return redirect(url_for("checklist_edit"))
            if action == "add_section":
                name = request.form.get("section_name", "").strip() or "Section"
                max_order = db.execute(
                    "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM checklist_section"
                ).fetchone()[0]
                db.execute(
                    "INSERT INTO checklist_section (sort_order, name) VALUES (?, ?)",
                    (max_order, name),
                )
                db.commit()
                flash("Section added.")
                return redirect(url_for("checklist_edit"))
            if action == "rename_section":
                section_id = request.form.get("section_id", type=int)
                name = request.form.get("section_name", "").strip()
                if section_id and name:
                    db.execute(
                        "UPDATE checklist_section SET name = ? WHERE id = ?",
                        (name, section_id),
                    )
                    db.commit()
                    flash("Section renamed.")
                return redirect(url_for("checklist_edit"))
            if action == "delete_section":
                section_id = request.form.get("section_id", type=int)
                if section_id:
                    first = db.execute(
                        "SELECT id FROM checklist_section WHERE id != ? ORDER BY sort_order, id LIMIT 1",
                        (section_id,),
                    ).fetchone()
                    if first:
                        db.execute(
                            "UPDATE checklist SET section_id = ? WHERE section_id = ?",
                            (first["id"], section_id),
                        )
                    db.execute("DELETE FROM checklist_section WHERE id = ?", (section_id,))
                    db.commit()
                    flash("Section removed. Items moved to another section.")
                return redirect(url_for("checklist_edit"))
            delete_id = request.form.get("delete_id", type=int)
            if delete_id:
                db.execute("DELETE FROM checklist WHERE id = ?", (delete_id,))
                db.commit()
                flash("Item removed.")
                return redirect(url_for("checklist_edit"))
            if action == "reorder":
                order_keys = sorted(
                    [k for k in request.form if k.startswith("order_")],
                    key=lambda x: int(x.split("_")[1]),
                )
                for i, key in enumerate(order_keys):
                    cid = request.form.get(key, type=int)
                    if cid:
                        db.execute(
                            "UPDATE checklist SET sort_order = ? WHERE id = ?", (i, cid)
                        )
                db.commit()
                flash("Order updated.")
                return redirect(url_for("checklist_edit"))
            if action == "add":
                text = request.form.get("new_text", "").strip()
                section_id = request.form.get("section_id", type=int)
                if text and section_id:
                    max_order = db.execute(
                        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM checklist WHERE section_id = ?",
                        (section_id,),
                    ).fetchone()[0]
                    db.execute(
                        "INSERT INTO checklist (section_id, sort_order, text) VALUES (?, ?, ?)",
                        (section_id, max_order, text),
                    )
                    db.commit()
                    flash("Item added.")
                return redirect(url_for("checklist_edit"))

        sections = db.execute(
            "SELECT id, sort_order, name FROM checklist_section ORDER BY sort_order, id"
        ).fetchall()
        items = db.execute(
            "SELECT id, section_id, sort_order, text FROM checklist ORDER BY sort_order, id"
        ).fetchall()
        # Group items by section for template
        sections_with_items = []
        order_index = 0
        for sec in sections:
            sec_items = [dict(i) for i in items if i["section_id"] == sec["id"]]
            for it in sec_items:
                it["order_index"] = order_index
                order_index += 1
            sections_with_items.append(
                {"id": sec["id"], "sort_order": sec["sort_order"], "name": sec["name"], "items": sec_items}
            )
        return render_template(
            "checklist_edit.html",
            sections=sections_with_items,
        )

    @app.route("/review/new", methods=["GET", "POST"])
    def review_new():
        """New review step 1: app metadata. GET ?from_id=N pre-fills from review N (re-review)."""
        from_id = request.args.get("from_id", type=int)
        prefill = None
        if from_id:
            db = get_db()
            r = db.execute(
                "SELECT app_name, app_id, date, app_owner_email, overall_notes FROM review WHERE id = ?",
                (from_id,),
            ).fetchone()
            if r:
                prefill = dict(r)

        if request.method == "POST":
            app_name = request.form.get("app_name", "").strip()
            app_id = request.form.get("app_id", "").strip()
            date = request.form.get("date", "").strip()
            app_owner_email = request.form.get("app_owner_email", "").strip()
            overall_notes = request.form.get("overall_notes", "").strip()
            if not app_name or not app_id or not date:
                flash("App name, App ID, and Date are required.")
                return render_template(
                    "review_new.html",
                    prefill={
                        "app_name": app_name,
                        "app_id": app_id,
                        "date": date,
                        "app_owner_email": app_owner_email,
                        "overall_notes": overall_notes,
                    },
                )
            db = get_db()
            cur = db.execute(
                """INSERT INTO review (app_name, app_id, date, app_owner_email, overall_notes, status)
                   VALUES (?, ?, ?, ?, ?, 'in_progress')""",
                (app_name, app_id, date, app_owner_email, overall_notes),
            )
            db.commit()
            review_id = cur.lastrowid
            # Create empty result rows for each checklist item
            items = db.execute("SELECT id FROM checklist ORDER BY sort_order, id").fetchall()
            for item in items:
                db.execute(
                    "INSERT OR IGNORE INTO review_result (review_id, checklist_id) VALUES (?, ?)",
                    (review_id, item["id"]),
                )
            db.commit()
            return redirect(url_for("review_run", review_id=review_id))

        return render_template("review_new.html", prefill=prefill)

    @app.route("/review/<int:review_id>/run", methods=["GET", "POST"])
    def review_run(review_id):
        """Run checklist for a review: Pass/Fail/Partial/NA per item. Save / Finish review."""
        db = get_db()
        review = db.execute(
            "SELECT id, app_name, app_id, date, app_owner_email, overall_notes, status FROM review WHERE id = ?",
            (review_id,),
        ).fetchone()
        if not review:
            abort(404)

        if request.method == "POST":
            action = request.form.get("action")
            for key, val in request.form.items():
                if key.startswith("result_") and val in RESULTS:
                    cid = key[7:]
                    if cid.isdigit():
                        db.execute(
                            """INSERT INTO review_result (review_id, checklist_id, result)
                               VALUES (?, ?, ?) ON CONFLICT(review_id, checklist_id) DO UPDATE SET result = ?""",
                            (review_id, int(cid), val, val),
                        )
            db.commit()

            if action == "finish":
                db.execute(
                    "UPDATE review SET status = 'completed' WHERE id = ?", (review_id,)
                )
                db.commit()
                flash("Review completed. You can export a PDF or re-review this app.")
                return redirect(url_for("review_detail", review_id=review_id))
            # save and continue later
            flash("Progress saved.")
            return redirect(url_for("review_run", review_id=review_id))

        items = db.execute(
            """SELECT c.id, c.sort_order, c.text, c.section_id, s.name AS section_name, s.sort_order AS section_order
               FROM checklist c
               LEFT JOIN checklist_section s ON c.section_id = s.id
               ORDER BY s.sort_order, s.id, c.sort_order, c.id"""
        ).fetchall()
        result_map = {}
        for row in db.execute(
            "SELECT checklist_id, result FROM review_result WHERE review_id = ?",
            (review_id,),
        ).fetchall():
            result_map[row["checklist_id"]] = row["result"]

        # Group by section
        sections_criteria = []
        current_sec = None
        for row in items:
            sec_name = row["section_name"] or "General"
            if current_sec is None or current_sec["name"] != sec_name:
                current_sec = {"name": sec_name, "items": []}
                sections_criteria.append(current_sec)
            current_sec["items"].append(
                {
                    "id": row["id"],
                    "text": row["text"],
                    "result": result_map.get(row["id"]),
                }
            )
        return render_template(
            "review_run.html",
            review=dict(review),
            sections_criteria=sections_criteria,
            results_options=RESULTS,
        )

    @app.route("/review/<int:review_id>")
    def review_detail(review_id):
        """Review detail: metadata, results, Export PDF, Re-review, Approve/Reject, Archive."""
        db = get_db()
        review = db.execute(
            "SELECT id, app_name, app_id, date, app_owner_email, overall_notes, status, archived, created_at FROM review WHERE id = ?",
            (review_id,),
        ).fetchone()
        if not review:
            abort(404)
        review = dict(review)
        status_display_map = {
            "in_progress": "In Review",
            "completed": "Completed",
            "approved": "Approved",
            "rejected": "Rejected",
        }
        review["status_display"] = status_display_map.get(review["status"], review["status"])

        items = db.execute(
            """SELECT c.id, c.sort_order, c.text, s.name AS section_name, s.sort_order AS section_order
               FROM checklist c
               LEFT JOIN checklist_section s ON c.section_id = s.id
               ORDER BY s.sort_order, s.id, c.sort_order, c.id"""
        ).fetchall()
        result_map = {}
        for row in db.execute(
            "SELECT checklist_id, result FROM review_result WHERE review_id = ?",
            (review_id,),
        ).fetchall():
            result_map[row["checklist_id"]] = row["result"]
        sections_criteria = []
        current_sec = None
        for row in items:
            sec_name = row["section_name"] or "General"
            if current_sec is None or current_sec["name"] != sec_name:
                current_sec = {"name": sec_name, "items": []}
                sections_criteria.append(current_sec)
            current_sec["items"].append(
                {"id": row["id"], "text": row["text"], "result": result_map.get(row["id"])}
            )
        return render_template(
            "review_detail.html", review=review, sections_criteria=sections_criteria
        )

    @app.route("/review/<int:review_id>/re-review", methods=["POST"])
    def re_review(review_id):
        """Create a new review with metadata copied from this one; redirect to new review run."""
        db = get_db()
        r = db.execute(
            "SELECT app_name, app_id, date, app_owner_email, overall_notes FROM review WHERE id = ?",
            (review_id,),
        ).fetchone()
        if not r:
            abort(404)
        cur = db.execute(
            """INSERT INTO review (app_name, app_id, date, app_owner_email, overall_notes, status)
               VALUES (?, ?, ?, ?, ?, 'in_progress')""",
            (r["app_name"], r["app_id"], r["date"], r["app_owner_email"], r["overall_notes"] or ""),
        )
        db.commit()
        new_id = cur.lastrowid
        items = db.execute("SELECT id FROM checklist ORDER BY sort_order, id").fetchall()
        for item in items:
            db.execute(
                "INSERT OR IGNORE INTO review_result (review_id, checklist_id) VALUES (?, ?)",
                (new_id, item["id"]),
            )
        db.commit()
        flash("New review created. Complete the checklist.")
        return redirect(url_for("review_run", review_id=new_id))

    @app.route("/review/<int:review_id>/approve", methods=["POST"])
    def approve(review_id):
        """Mark review as approved (decision only; does not archive)."""
        db = get_db()
        db.execute("UPDATE review SET status = 'approved' WHERE id = ?", (review_id,))
        db.commit()
        flash("Review approved.")
        return redirect(url_for("review_detail", review_id=review_id))

    @app.route("/review/<int:review_id>/reject", methods=["POST"])
    def reject(review_id):
        """Mark review as rejected."""
        db = get_db()
        db.execute("UPDATE review SET status = 'rejected' WHERE id = ?", (review_id,))
        db.commit()
        flash("Review rejected.")
        return redirect(url_for("review_detail", review_id=review_id))

    @app.route("/review/<int:review_id>/archive", methods=["POST"])
    def archive(review_id):
        """Move review to Archived (archived=1)."""
        db = get_db()
        db.execute("UPDATE review SET archived = 1 WHERE id = ?", (review_id,))
        db.commit()
        flash("Review archived.")
        return redirect(url_for("index", tab="archived"))

    @app.route("/review/<int:review_id>/unarchive", methods=["POST"])
    def unarchive(review_id):
        """Move review back to Active (archived=0)."""
        db = get_db()
        db.execute("UPDATE review SET archived = 0 WHERE id = ?", (review_id,))
        db.commit()
        flash("Review unarchived.")
        return redirect(url_for("review_detail", review_id=review_id))

    @app.route("/review/<int:review_id>/pdf")
    def pdf_export(review_id):
        """Generate and download PDF report for the review."""
        from pdf_report import build_pdf

        db = get_db()
        review = db.execute(
            "SELECT id, app_name, app_id, date, app_owner_email, overall_notes, created_at FROM review WHERE id = ?",
            (review_id,),
        ).fetchone()
        if not review:
            abort(404)
        review = dict(review)
        items = db.execute(
            """SELECT c.id, c.sort_order, c.text, s.name AS section_name, s.sort_order AS section_order
               FROM checklist c
               LEFT JOIN checklist_section s ON c.section_id = s.id
               ORDER BY s.sort_order, s.id, c.sort_order, c.id"""
        ).fetchall()
        result_map = {}
        for row in db.execute(
            "SELECT checklist_id, result FROM review_result WHERE review_id = ?",
            (review_id,),
        ).fetchall():
            result_map[row["checklist_id"]] = row["result"]
        sections_criteria = []
        current_sec = None
        for row in items:
            sec_name = row["section_name"] or "General"
            if current_sec is None or current_sec["name"] != sec_name:
                current_sec = {"name": sec_name, "items": []}
                sections_criteria.append(current_sec)
            current_sec["items"].append(
                {"text": row["text"], "result": result_map.get(row["id"])}
            )
        buf = build_pdf(review, sections_criteria)
        buf.seek(0)
        filename = f"UAT_Report_{review['app_name'].replace(' ', '_')}_{review['app_id']}.pdf"
        return send_file(
            buf,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )
