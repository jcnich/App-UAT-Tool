"""Flask routes for UAT Test Management Tool."""
import csv
from io import BytesIO, StringIO, TextIOWrapper

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

    def _get_review_section_ids(db, review_id):
        """Return set of section_id for this review, or None meaning 'all sections' (backward compat)."""
        rows = db.execute(
            "SELECT section_id FROM review_section WHERE review_id = ?", (review_id,)
        ).fetchall()
        if not rows:
            return None
        return {row["section_id"] for row in rows}

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
                   (SELECT COUNT(*) FROM review_result rr WHERE rr.review_id = r.id) AS total
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
            active_page="index",
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
                    raw = f.read()
                    text = raw.decode("utf-8-sig", errors="replace")
                    reader = csv.DictReader(StringIO(text))
                    fieldnames = list(reader.fieldnames or [])
                    norm = lambda c: (c or "").strip().lstrip("\ufeff")
                    normalized = [norm(k) for k in fieldnames]
                    if "section_name" not in normalized or "criteria" not in normalized:
                        flash("CSV must have columns: section_name, criteria")
                        return redirect(url_for("checklist_edit"))
                    section_key = next(k for k in fieldnames if norm(k) == "section_name")
                    criteria_key = next(k for k in fieldnames if norm(k) == "criteria")
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
                    sec_name = (row.get(section_key) or "").strip()
                    criteria_text = (row.get(criteria_key) or "").strip()
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
            if action == "move_section":
                section_id = request.form.get("section_id", type=int)
                direction = request.form.get("direction")  # "up" or "down"
                if section_id and direction in ("up", "down"):
                    row = db.execute(
                        "SELECT id, sort_order FROM checklist_section WHERE id = ?",
                        (section_id,),
                    ).fetchone()
                    if row:
                        current_order = row["sort_order"]
                        if direction == "up":
                            neighbour = db.execute(
                                """SELECT id, sort_order FROM checklist_section
                                   WHERE sort_order < ? ORDER BY sort_order DESC, id DESC LIMIT 1""",
                                (current_order,),
                            ).fetchone()
                        else:
                            neighbour = db.execute(
                                """SELECT id, sort_order FROM checklist_section
                                   WHERE sort_order > ? ORDER BY sort_order ASC, id ASC LIMIT 1""",
                                (current_order,),
                            ).fetchone()
                        if neighbour:
                            db.execute(
                                "UPDATE checklist_section SET sort_order = ? WHERE id = ?",
                                (neighbour["sort_order"], section_id),
                            )
                            db.execute(
                                "UPDATE checklist_section SET sort_order = ? WHERE id = ?",
                                (current_order, neighbour["id"]),
                            )
                            db.commit()
                            flash("Section order updated.")
                return redirect(url_for("checklist_edit"))
            if action == "move_item":
                item_id = request.form.get("item_id", type=int)
                direction = request.form.get("direction")  # "up" or "down"
                if item_id and direction in ("up", "down"):
                    row = db.execute(
                        "SELECT id, section_id, sort_order FROM checklist WHERE id = ?",
                        (item_id,),
                    ).fetchone()
                    if row:
                        sec_id, current_order = row["section_id"], row["sort_order"]
                        if direction == "up":
                            neighbour = db.execute(
                                """SELECT id, sort_order FROM checklist
                                   WHERE section_id = ? AND (sort_order < ? OR (sort_order = ? AND id < ?))
                                   ORDER BY sort_order DESC, id DESC LIMIT 1""",
                                (sec_id, current_order, current_order, item_id),
                            ).fetchone()
                        else:
                            neighbour = db.execute(
                                """SELECT id, sort_order FROM checklist
                                   WHERE section_id = ? AND (sort_order > ? OR (sort_order = ? AND id > ?))
                                   ORDER BY sort_order ASC, id ASC LIMIT 1""",
                                (sec_id, current_order, current_order, item_id),
                            ).fetchone()
                        if neighbour:
                            db.execute(
                                "UPDATE checklist SET sort_order = ? WHERE id = ?",
                                (neighbour["sort_order"], item_id),
                            )
                            db.execute(
                                "UPDATE checklist SET sort_order = ? WHERE id = ?",
                                (current_order, neighbour["id"]),
                            )
                            db.commit()
                            flash("Item order updated.")
                return redirect(url_for("checklist_edit"))
            if action == "remove_items":
                delete_ids = request.form.getlist("delete_ids", type=int)
                if delete_ids:
                    placeholders = ",".join("?" * len(delete_ids))
                    db.execute(
                        f"DELETE FROM checklist WHERE id IN ({placeholders})",
                        delete_ids,
                    )
                    db.commit()
                    n = len(delete_ids)
                    flash(f"Removed {n} item(s)." if n != 1 else "Item removed.")
                else:
                    flash("No criteria selected.")
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
            if action == "set_section_default":
                section_id = request.form.get("section_id", type=int)
                is_default = request.form.get("is_default", "0") == "1"
                if section_id is not None:
                    db.execute(
                        "UPDATE checklist_section SET is_default = ? WHERE id = ?",
                        (1 if is_default else 0, section_id),
                    )
                    db.commit()
                    flash("Default section setting updated.")
                return redirect(url_for("checklist_edit"))

        sections = db.execute(
            "SELECT id, sort_order, name, COALESCE(is_default, 1) AS is_default FROM checklist_section ORDER BY sort_order, id"
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
                {
                    "id": sec["id"],
                    "sort_order": sec["sort_order"],
                    "name": sec["name"],
                    "is_default": bool(sec["is_default"]),
                    "items": sec_items,
                }
            )
        return render_template(
            "checklist_edit.html",
            sections=sections_with_items,
            active_page="checklist_edit",
        )

    @app.route("/review/new", methods=["GET", "POST"])
    def review_new():
        """New review: step 1 = app metadata, step 2 = select sections. GET ?from_id=N pre-fills from review N (re-review)."""
        db = get_db()
        from_id = request.args.get("from_id", type=int)
        prefill = None
        if from_id:
            r = db.execute(
                "SELECT app_name, app_id, date, app_owner_email, overall_notes FROM review WHERE id = ?",
                (from_id,),
            ).fetchone()
            if r:
                prefill = dict(r)

        if request.method == "POST":
            action = request.form.get("action")
            app_name = request.form.get("app_name", "").strip()
            app_id = request.form.get("app_id", "").strip()
            date = request.form.get("date", "").strip()
            app_owner_email = request.form.get("app_owner_email", "").strip()
            overall_notes = request.form.get("overall_notes", "").strip()
            prefill_data = {
                "app_name": app_name,
                "app_id": app_id,
                "date": date,
                "app_owner_email": app_owner_email,
                "overall_notes": overall_notes,
            }

            if action == "next":
                if not app_name or not app_id or not date:
                    flash("App name, App ID, and Date are required.")
                    return render_template(
                        "review_new.html",
                        prefill=prefill_data,
                        step=1,
                        from_id=from_id,
                        active_page="review_new",
                    )
                sections = db.execute(
                    "SELECT id, sort_order, name, is_default FROM checklist_section ORDER BY sort_order, id"
                ).fetchall()
                selected_ids = None
                if from_id:
                    selected_ids = _get_review_section_ids(db, from_id)
                if selected_ids is None:
                    selected_ids = {row["id"] for row in sections if row["is_default"]}
                    if not selected_ids:
                        selected_ids = {row["id"] for row in sections}
                sections_for_step2 = [
                    {
                        "id": row["id"],
                        "name": row["name"],
                        "selected": row["id"] in selected_ids,
                    }
                    for row in sections
                ]
                return render_template(
                    "review_new.html",
                    prefill=prefill_data,
                    step=2,
                    from_id=from_id,
                    sections=sections_for_step2,
                    active_page="review_new",
                )

            if action == "create":
                section_ids = request.form.getlist("section_ids", type=int)
                if not app_name or not app_id or not date:
                    flash("App name, App ID, and Date are required.")
                    return render_template(
                        "review_new.html",
                        prefill=prefill_data,
                        step=1,
                        from_id=from_id,
                        active_page="review_new",
                    )
                if not section_ids:
                    flash("Select at least one section for this review.")
                    sections = db.execute(
                        "SELECT id, sort_order, name, is_default FROM checklist_section ORDER BY sort_order, id"
                    ).fetchall()
                    selected_ids = None
                    if from_id:
                        selected_ids = _get_review_section_ids(db, from_id)
                    if selected_ids is None:
                        selected_ids = {row["id"] for row in sections if row["is_default"]}
                        if not selected_ids:
                            selected_ids = {row["id"] for row in sections}
                    sections_for_step2 = [
                        {"id": row["id"], "name": row["name"], "selected": row["id"] in selected_ids}
                        for row in sections
                    ]
                    return render_template(
                        "review_new.html",
                        prefill=prefill_data,
                        step=2,
                        from_id=from_id,
                        sections=sections_for_step2,
                        active_page="review_new",
                    )
                cur = db.execute(
                    """INSERT INTO review (app_name, app_id, date, app_owner_email, overall_notes, status)
                       VALUES (?, ?, ?, ?, ?, 'in_progress')""",
                    (app_name, app_id, date, app_owner_email, overall_notes),
                )
                db.commit()
                review_id = cur.lastrowid
                for sid in section_ids:
                    db.execute(
                        "INSERT INTO review_section (review_id, section_id) VALUES (?, ?)",
                        (review_id, sid),
                    )
                db.commit()
                placeholders = ",".join("?" * len(section_ids))
                items = db.execute(
                    "SELECT id FROM checklist WHERE section_id IN ({}) ORDER BY sort_order, id".format(
                        placeholders
                    ),
                    section_ids,
                ).fetchall()
                for item in items:
                    db.execute(
                        "INSERT OR IGNORE INTO review_result (review_id, checklist_id) VALUES (?, ?)",
                        (review_id, item["id"]),
                    )
                # Re-review: copy result and attachment from original review for matching checklist items only.
                # New sections/items (not in original) have no source row, so they stay blank.
                if from_id:
                    for row in db.execute(
                        "SELECT checklist_id, result, attachment FROM review_result WHERE review_id = ?",
                        (from_id,),
                    ).fetchall():
                        db.execute(
                            """UPDATE review_result SET result = ?, attachment = ?
                               WHERE review_id = ? AND checklist_id = ?""",
                            (row["result"], row["attachment"] or None, review_id, row["checklist_id"]),
                        )
                db.commit()
                return redirect(url_for("review_run", review_id=review_id))

        return render_template(
            "review_new.html",
            prefill=prefill,
            step=1,
            from_id=from_id,
            active_page="review_new",
        )

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
                        attachment_val = request.form.get(f"attachment_{cid}", "").strip() or None
                        db.execute(
                            """INSERT INTO review_result (review_id, checklist_id, result, attachment)
                               VALUES (?, ?, ?, ?) ON CONFLICT(review_id, checklist_id) DO UPDATE SET result = excluded.result, attachment = excluded.attachment""",
                            (review_id, int(cid), val, attachment_val),
                        )
            for key, val in request.form.items():
                if key.startswith("attachment_"):
                    cid = key[11:]
                    if cid.isdigit():
                        checklist_id = int(cid)
                        attachment_val = val.strip() or None
                        db.execute(
                            """INSERT INTO review_result (review_id, checklist_id, attachment)
                               VALUES (?, ?, ?) ON CONFLICT(review_id, checklist_id) DO UPDATE SET attachment = excluded.attachment""",
                            (review_id, checklist_id, attachment_val),
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
        section_ids = _get_review_section_ids(db, review_id)
        if section_ids is not None:
            items = [row for row in items if row["section_id"] in section_ids]
        result_map = {}
        attachment_map = {}
        for row in db.execute(
            "SELECT checklist_id, result, attachment FROM review_result WHERE review_id = ?",
            (review_id,),
        ).fetchall():
            result_map[row["checklist_id"]] = row["result"]
            attachment_map[row["checklist_id"]] = (row["attachment"] or "").strip()

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
                    "attachment": attachment_map.get(row["id"], ""),
                }
            )
        return render_template(
            "review_run.html",
            review=dict(review),
            sections_criteria=sections_criteria,
            results_options=RESULTS,
            active_page="index",
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
            """SELECT c.id, c.sort_order, c.text, c.section_id, s.name AS section_name, s.sort_order AS section_order
               FROM checklist c
               LEFT JOIN checklist_section s ON c.section_id = s.id
               ORDER BY s.sort_order, s.id, c.sort_order, c.id"""
        ).fetchall()
        section_ids = _get_review_section_ids(db, review_id)
        if section_ids is not None:
            items = [row for row in items if row["section_id"] in section_ids]
        result_map = {}
        attachment_map = {}
        for row in db.execute(
            "SELECT checklist_id, result, attachment FROM review_result WHERE review_id = ?",
            (review_id,),
        ).fetchall():
            result_map[row["checklist_id"]] = row["result"]
            attachment_map[row["checklist_id"]] = (row["attachment"] or "").strip()
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
                    "attachment": attachment_map.get(row["id"], ""),
                }
            )
        return render_template(
            "review_detail.html",
            review=review,
            sections_criteria=sections_criteria,
            active_page="index",
        )

    @app.route("/review/<int:review_id>/re-review", methods=["POST"])
    def re_review(review_id):
        """Redirect to New review with from_id so user can confirm metadata and sections, then create new run."""
        db = get_db()
        r = db.execute("SELECT id FROM review WHERE id = ?", (review_id,)).fetchone()
        if not r:
            abort(404)
        return redirect(url_for("review_new", from_id=review_id))

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
            """SELECT c.id, c.sort_order, c.text, c.section_id, s.name AS section_name, s.sort_order AS section_order
               FROM checklist c
               LEFT JOIN checklist_section s ON c.section_id = s.id
               ORDER BY s.sort_order, s.id, c.sort_order, c.id"""
        ).fetchall()
        section_ids = _get_review_section_ids(db, review_id)
        if section_ids is not None:
            items = [row for row in items if row["section_id"] in section_ids]
        result_map = {}
        attachment_map = {}
        for row in db.execute(
            "SELECT checklist_id, result, attachment FROM review_result WHERE review_id = ?",
            (review_id,),
        ).fetchall():
            result_map[row["checklist_id"]] = row["result"]
            attachment_map[row["checklist_id"]] = (row["attachment"] or "").strip()
        sections_criteria = []
        current_sec = None
        for row in items:
            sec_name = row["section_name"] or "General"
            if current_sec is None or current_sec["name"] != sec_name:
                current_sec = {"name": sec_name, "items": []}
                sections_criteria.append(current_sec)
            current_sec["items"].append(
                {
                    "text": row["text"],
                    "result": result_map.get(row["id"]),
                    "attachment": attachment_map.get(row["id"], ""),
                }
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
