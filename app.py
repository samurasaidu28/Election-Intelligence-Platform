import os
import sqlite3
from functools import wraps
from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash, g
)
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-this")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "database", "election.db")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create the database tables if they do not exist."""
    os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
    db = sqlite3.connect(DATABASE)

    # Users table
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'observer',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Logistics assessments table
    db.execute("""
        CREATE TABLE IF NOT EXISTS logistics_assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            distance REAL,
            delay REAL,
            road TEXT,
            history REAL,
            communication TEXT,
            capacity REAL,
            score INTEGER,
            level TEXT,
            reasons TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)

    # Transparency analyses table
    db.execute("""
        CREATE TABLE IF NOT EXISTS transparency_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            filename TEXT,
            total_records INTEGER,
            missing_cells INTEGER,
            unusual_values INTEGER,
            findings TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)

    # Misinformation claims table
    db.execute("""
        CREATE TABLE IF NOT EXISTS misinformation_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            claim_text TEXT,
            category TEXT,
            score INTEGER,
            reasons TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)

    db.commit()
    db.close()
    print("Database tables ready.")


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(**kwargs)
    return wrapped_view


@app.route("/", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid username or password.", "danger")
        else:
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()

    # Count records from the database
    logistics_count = db.execute(
        "SELECT COUNT(*) FROM logistics_assessments"
    ).fetchone()[0]

    misinfo_count = db.execute(
        "SELECT COUNT(*) FROM misinformation_claims"
    ).fetchone()[0]

    transparency_count = db.execute(
        "SELECT COUNT(*) FROM transparency_analyses"
    ).fetchone()[0]

    total_reports = logistics_count + misinfo_count + transparency_count

    return render_template(
        "dashboard.html",
        logistics_count=logistics_count,
        misinfo_count=misinfo_count,
        transparency_count=transparency_count,
        total_reports=total_reports
    )


@app.route("/logistics", methods=["GET", "POST"])
@login_required
def logistics():
    result = None
    error = None
    form = {}

    if request.method == "POST":
        form = request.form.to_dict()
        try:
            distance = float(form["distance"])
            delay = float(form["delay"])
            history = float(form["history"])
            capacity = float(form["capacity"])
            road = form["road"]
            communication = form["communication"]

            if (distance < 0 or delay < 0 or capacity < 0
                    or not 0 <= history <= 100):
                raise ValueError()
            if road not in ("good", "moderate", "poor"):
                raise ValueError()
            if communication not in ("reliable", "intermittent", "unavailable"):
                raise ValueError()

            score = 0
            reasons = []

            if delay >= 12:
                score += 30
                reasons.append("Expected delay is 12 hours or more.")
            elif delay >= 4:
                score += 15
                reasons.append("Expected delay is between 4 and 12 hours.")

            if distance >= 100:
                score += 15
                reasons.append("Long shipment distance (100 km or more).")
            elif distance >= 50:
                score += 8
                reasons.append("Shipment distance is at least 50 km.")

            if road == "poor":
                score += 25
                reasons.append("Poor road conditions may delay delivery.")
            elif road == "moderate":
                score += 10
                reasons.append("Moderate road conditions may affect delivery.")

            if history >= 50:
                score += 20
                reasons.append("Historical delay rate is 50% or higher.")
            elif history >= 20:
                score += 10
                reasons.append("Historical delay rate is at least 20%.")

            if communication == "unavailable":
                score += 10
                reasons.append("Communication is currently unavailable.")
            elif communication == "intermittent":
                score += 5
                reasons.append("Communication may be interrupted.")

            score = min(score, 100)

            if score >= 60:
                level = "High"
            elif score >= 30:
                level = "Medium"
            else:
                level = "Low"

            if not reasons:
                reasons.append("No elevated risk factors were identified by these rules.")

            result = {
                "score": score,
                "level": level,
                "reasons": reasons
            }

            # Save to database
            db = get_db()
            db.execute(
                """INSERT INTO logistics_assessments
                   (user_id, distance, delay, road, history, communication, capacity, score, level, reasons)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session["user_id"], distance, delay, road, history,
                    communication, capacity, score, level, " | ".join(reasons)
                )
            )
            db.commit()

        except (ValueError, KeyError, TypeError):
            error = "Please enter valid values in all fields and check your selections."

    return render_template(
        "logistics.html",
        result=result,
        error=error,
        form=form
    )
    result = None
    error = None
    form = {}

    if request.method == "POST":
        form = request.form.to_dict()
        try:
            distance = float(form["distance"])
            delay = float(form["delay"])
            history = float(form["history"])
            capacity = float(form["capacity"])
            road = form["road"]
            communication = form["communication"]

            if (distance < 0 or delay < 0 or capacity < 0
                    or not 0 <= history <= 100):
                raise ValueError()
            if road not in ("good", "moderate", "poor"):
                raise ValueError()
            if communication not in ("reliable", "intermittent", "unavailable"):
                raise ValueError()

            score = 0
            reasons = []

            if delay >= 12:
                score += 30
                reasons.append("Expected delay is 12 hours or more.")
            elif delay >= 4:
                score += 15
                reasons.append("Expected delay is between 4 and 12 hours.")

            if distance >= 100:
                score += 15
                reasons.append("Long shipment distance (100 km or more).")
            elif distance >= 50:
                score += 8
                reasons.append("Shipment distance is at least 50 km.")

            if road == "poor":
                score += 25
                reasons.append("Poor road conditions may delay delivery.")
            elif road == "moderate":
                score += 10
                reasons.append("Moderate road conditions may affect delivery.")

            if history >= 50:
                score += 20
                reasons.append("Historical delay rate is 50% or higher.")
            elif history >= 20:
                score += 10
                reasons.append("Historical delay rate is at least 20%.")

            if communication == "unavailable":
                score += 10
                reasons.append("Communication is currently unavailable.")
            elif communication == "intermittent":
                score += 5
                reasons.append("Communication may be interrupted.")

            score = min(score, 100)

            if score >= 60:
                level = "High"
            elif score >= 30:
                level = "Medium"
            else:
                level = "Low"

            if not reasons:
                reasons.append("No elevated risk factors were identified by these rules.")

            result = {
                "score": score,
                "level": level,
                "reasons": reasons
            }

        except (ValueError, KeyError, TypeError):
            error = "Please enter valid values in all fields and check your selections."

    return render_template(
        "logistics.html",
        result=result,
        error=error,
        form=form
    )


@app.route("/transparency", methods=["GET", "POST"])
@login_required
def transparency():
    result = None
    error = None

    if request.method == "POST":
        uploaded = request.files.get("file")
        if not uploaded or not uploaded.filename:
            error = "Please select a CSV file."
        elif not uploaded.filename.lower().endswith(".csv"):
            error = "Only CSV files are supported."
        else:
            try:
                df = pd.read_csv(uploaded)
                if df.empty or len(df.columns) == 0:
                    raise ValueError("The CSV file is empty.")

                missing = int(df.isna().sum().sum())
                unusual = 0
                findings = []

                if missing:
                    findings.append(f"{missing} missing cells were found.")
                else:
                    findings.append("No missing cells were found.")

                numeric = df.select_dtypes(include="number")
                if not numeric.empty:
                    for column in numeric.columns:
                        values = numeric[column].dropna()
                        if len(values) >= 4:
                            q1 = values.quantile(0.25)
                            q3 = values.quantile(0.75)
                            iqr = q3 - q1
                            if iqr > 0:
                                flagged = (
                                    (values < q1 - 1.5 * iqr) |
                                    (values > q3 + 1.5 * iqr)
                                )
                                count = int(flagged.sum())
                                if count:
                                    unusual += count
                                    findings.append(
                                        f"{count} unusual value(s) found in {column}."
                                    )

                if unusual == 0:
                    findings.append("No numeric outliers were detected.")

                result = {
                    "total": len(df),
                    "missing": missing,
                    "unusual": unusual,
                    "findings": findings
                }

                # Save to database
                db = get_db()
                db.execute(
                    """INSERT INTO transparency_analyses
                       (user_id, filename, total_records, missing_cells, unusual_values, findings)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        session["user_id"],
                        uploaded.filename,
                        len(df),
                        missing,
                        unusual,
                        " | ".join(findings)
                    )
                )
                db.commit()

            except Exception as e:
                error = f"The file could not be analysed. Please check that it is a valid CSV. ({str(e)})"

    return render_template(
        "transparency.html",
        result=result,
        error=error
    )
    result = None
    error = None

    if request.method == "POST":
        uploaded = request.files.get("file")
        if not uploaded or not uploaded.filename:
            error = "Please select a CSV file."
        elif not uploaded.filename.lower().endswith(".csv"):
            error = "Only CSV files are supported."
        else:
            try:
                df = pd.read_csv(uploaded)
                if df.empty or len(df.columns) == 0:
                    raise ValueError("The CSV file is empty.")

                missing = int(df.isna().sum().sum())
                unusual = 0
                findings = []

                if missing:
                    findings.append(f"{missing} missing cells were found.")
                else:
                    findings.append("No missing cells were found.")

                numeric = df.select_dtypes(include="number")
                if not numeric.empty:
                    for column in numeric.columns:
                        values = numeric[column].dropna()
                        if len(values) >= 4:
                            q1 = values.quantile(0.25)
                            q3 = values.quantile(0.75)
                            iqr = q3 - q1
                            if iqr > 0:
                                flagged = (
                                    (values < q1 - 1.5 * iqr) |
                                    (values > q3 + 1.5 * iqr)
                                )
                                count = int(flagged.sum())
                                if count:
                                    unusual += count
                                    findings.append(
                                        f"{count} unusual value(s) found in {column}."
                                    )

                if unusual == 0:
                    findings.append("No numeric outliers were detected.")

                result = {
                    "total": len(df),
                    "missing": missing,
                    "unusual": unusual,
                    "findings": findings
                }

                # Save to database
                db = get_db()
                db.execute(
                    """INSERT INTO transparency_analyses
                       (user_id, filename, total_records, missing_cells, unusual_values, findings)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        session["user_id"],
                        uploaded.filename,
                        len(df),
                        missing,
                        unusual,
                        " | ".join(findings)
                    )
                )
                db.commit()

            except Exception:
                error = "The file could not be analysed. Please check that it is a valid CSV."

    return render_template(
        "transparency.html",
        result=result,
        error=error
    )
    result = None
    error = None

    if request.method == "POST":
        uploaded = request.files.get("file")
        if not uploaded or not uploaded.filename:
            error = "Please select a CSV file."
        elif not uploaded.filename.lower().endswith(".csv"):
            error = "Only CSV files are supported."
        else:
            try:
                df = pd.read_csv(uploaded)
                if df.empty or len(df.columns) == 0:
                    raise ValueError("The CSV file is empty.")

                missing = int(df.isna().sum().sum())
                unusual = 0
                findings = []

                if missing:
                    findings.append(f"{missing} missing cells were found.")
                else:
                    findings.append("No missing cells were found.")

                numeric = df.select_dtypes(include="number")
                if not numeric.empty:
                    for column in numeric.columns:
                        values = numeric[column].dropna()
                        if len(values) >= 4:
                            q1 = values.quantile(0.25)
                            q3 = values.quantile(0.75)
                            iqr = q3 - q1
                            if iqr > 0:
                                flagged = (
                                    (values < q1 - 1.5 * iqr) |
                                    (values > q3 + 1.5 * iqr)
                                )
                                count = int(flagged.sum())
                                if count:
                                    unusual += count
                                    findings.append(
                                        f"{count} unusual value(s) found in {column}."
                                    )

                if unusual == 0:
                    findings.append("No numeric outliers were detected.")

                result = {
                    "total": len(df),
                    "missing": missing,
                    "unusual": unusual,
                    "findings": findings
                }

            except Exception:
                error = "The file could not be analysed. Please check that it is a valid CSV."

    return render_template(
        "transparency.html",
        result=result,
        error=error
    )


@app.route("/misinformation", methods=["GET", "POST"])
@login_required
def misinformation():
    result = None
    error = None
    claim_text = ""

    if request.method == "POST":
        claim_text = request.form.get("claim", "").strip()

        if not claim_text:
            error = "Please enter a claim to analyse."
        else:
            text = claim_text.lower()
            score = 0
            reasons = []

            misleading_keywords = [
                "rigged", "stolen", "fake results", "ballot stuffing",
                "hacked", "fraud", "they cheated", "results changed"
            ]
            ungrounded_keywords = [
                "i heard", "someone said", "people are saying",
                "rumour", "rumor", "supposedly", "allegedly without proof"
            ]

            for word in misleading_keywords:
                if word in text:
                    score += 30
                    reasons.append(f"Contains potentially misleading language: '{word}'")

            for word in ungrounded_keywords:
                if word in text:
                    score += 20
                    reasons.append(f"Contains unverified source language: '{word}'")

            score = max(0, min(score, 100))

            if score >= 50:
                category = "Potentially Misleading"
            elif score >= 25:
                category = "Needs More Evidence"
            else:
                category = "Checkable / Low Concern"

            if not reasons:
                reasons.append("No strong risk keywords were detected. The claim appears relatively neutral.")

            result = {
                "category": category,
                "score": score,
                "reasons": reasons,
                "original": claim_text
            }

            # Save to database
            db = get_db()
            db.execute(
                """INSERT INTO misinformation_claims
                   (user_id, claim_text, category, score, reasons)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    session["user_id"], claim_text, category, score, " | ".join(reasons)
                )
            )
            db.commit()

    return render_template(
        "misinformation.html",
        result=result,
        error=error,
        claim_text=claim_text
    )
    result = None
    error = None
    claim_text = ""

    if request.method == "POST":
        claim_text = request.form.get("claim", "").strip()

        if not claim_text:
            error = "Please enter a claim to analyse."
        else:
            text = claim_text.lower()
            score = 0
            reasons = []
            category = "Checkable"

            # Simple keyword-based rules (beginner-friendly)
            misleading_keywords = [
                "rigged", "stolen", "fake results", "ballot stuffing",
                "hacked", "fraud", "they cheated", "results changed"
            ]
            ungrounded_keywords = [
                "i heard", "someone said", "people are saying",
                "rumour", "rumor", "supposedly", "allegedly without proof"
            ]
            checkable_keywords = [
                "official", "results", "turnout", "polling station",
                "voters registered", "materials arrived"
            ]

            for word in misleading_keywords:
                if word in text:
                    score += 30
                    reasons.append(f"Contains potentially misleading language: '{word}'")

            for word in ungrounded_keywords:
                if word in text:
                    score += 20
                    reasons.append(f"Contains unverified source language: '{word}'")

            for word in checkable_keywords:
                if word in text:
                    score -= 10

            score = max(0, min(score, 100))

            if score >= 50:
                category = "Potentially Misleading"
            elif score >= 25:
                category = "Needs More Evidence"
            else:
                category = "Checkable / Low Concern"

            if not reasons:
                reasons.append("No strong risk keywords were detected. The claim appears relatively neutral.")

            result = {
                "category": category,
                "score": score,
                "reasons": reasons,
                "original": claim_text
            }

    return render_template(
        "misinformation.html",
        result=result,
        error=error,
        claim_text=claim_text
    )
@app.route("/reports")
@login_required
def reports():
    db = get_db()

    logistics = db.execute(
        "SELECT id, score, level, created_at FROM logistics_assessments ORDER BY created_at DESC LIMIT 10"
    ).fetchall()

    misinfo = db.execute(
        "SELECT id, category, score, created_at FROM misinformation_claims ORDER BY created_at DESC LIMIT 10"
    ).fetchall()

    transparency = db.execute(
        "SELECT id, total_records, missing_cells, unusual_values, created_at FROM transparency_analyses ORDER BY created_at DESC LIMIT 10"
    ).fetchall()

    return render_template(
        "reports.html",
        logistics=logistics,
        misinfo=misinfo,
        transparency=transparency
    )
@app.route("/audit")
@login_required
def audit():
    db = get_db()

    logistics_records = db.execute(
        "SELECT id, user_id, score, level, created_at FROM logistics_assessments ORDER BY created_at DESC LIMIT 20"
    ).fetchall()

    misinfo_records = db.execute(
        "SELECT id, user_id, category, score, created_at FROM misinformation_claims ORDER BY created_at DESC LIMIT 20"
    ).fetchall()

    return render_template(
        "audit.html",
        logistics_records=logistics_records,
        misinfo_records=misinfo_records
    )
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5001)