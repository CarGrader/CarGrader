from flask import Flask, g, render_template, request, jsonify, url_for, abort
import sqlite3
import os
import shutil

app = Flask(__name__)

# === CONFIG ===
# Prefer a mounted disk in production: set DB_DIR=/var/data in Render Env.
# Optional overrides:
#   DB_FILENAME (default "GraderRater.db")
#   DB_PATH     (full explicit path; overrides DB_DIR/DB_FILENAME)
BASE_DIR = os.path.dirname(__file__)
DB_DIR = os.environ.get("DB_DIR") or os.path.join(BASE_DIR, "instance")
os.makedirs(DB_DIR, exist_ok=True)

DB_FILENAME = os.environ.get("DB_FILENAME", "GraderRater.db")
DB_PATH = os.environ.get("DB_PATH") or os.path.join(DB_DIR, DB_FILENAME)

# Optional secure upload token for one-time DB upload (see /admin/upload-db)
UPLOAD_TOKEN = os.environ.get("UPLOAD_TOKEN")  # e.g., a long random string
MAX_CONTENT_LENGTH = 1024 * 1024 * 1024  # 1 GB cap; adjust if needed
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH


# === DB HELPERS ===
def get_db():
    if "db" not in g:
        # Standard file path (not URI) so writes work on Render/Linux
        g.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# === PAGES ===
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/favicon.ico")
def favicon():
    # avoid noisy 404s; add a real favicon later if you want
    return ("", 204)


# === DIAGNOSTICS ===
@app.route("/api/health")
def health():
    try:
        db = get_db()
        tables = [r["name"] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        exists = "AllCars" in tables
        count_all = db.execute("SELECT COUNT(*) AS c FROM AllCars").fetchone()["c"] if exists else 0
        count_ready = db.execute(
            "SELECT COUNT(*) AS c FROM AllCars WHERE Score IS NOT NULL AND Certainty IS NOT NULL"
        ).fetchone()["c"] if exists else 0
        return jsonify({
            "db_path": DB_PATH,
            "tables": tables,
            "allcars_exists": exists,
            "allcars_count": count_all,
            "with_score_certainty": count_ready
        })
    except Exception as e:
        return jsonify({"error": str(e), "db_path": DB_PATH}), 500


# === DATA APIS ===
@app.route("/api/years")
def years():
    """Years that have at least one row with both Score & Certainty."""
    try:
        db = get_db()
        rows = db.execute("""
            SELECT DISTINCT CAST(TRIM(ModelYear) AS INTEGER) AS Y
            FROM AllCars
            WHERE Score IS NOT NULL AND Certainty IS NOT NULL
                  AND ModelYear IS NOT NULL AND TRIM(ModelYear) <> ''
            ORDER BY Y DESC
        """).fetchall()
        return jsonify([r["Y"] for r in rows if r["Y"] is not None])
    except Exception as e:
        print("Error /api/years:", e)
        return jsonify([]), 500

@app.route("/api/makes")
def makes():
    year = request.args.get("year", type=int)
    if year is None:
        return jsonify([])
    try:
        db = get_db()
        rows = db.execute("""
            SELECT DISTINCT Make
            FROM AllCars
            WHERE CAST(TRIM(ModelYear) AS INTEGER) = ?
              AND Score IS NOT NULL AND Certainty IS NOT NULL
            ORDER BY Make
        """, (year,)).fetchall()
        return jsonify([r["Make"] for r in rows])
    except Exception as e:
        print("Error /api/makes:", e)
        return jsonify([]), 500

@app.route("/api/models")
def models():
    year  = request.args.get("year",  type=int)
    make  = request.args.get("make",  type=str)
    if year is None or not make:
        return jsonify([])
    try:
        db = get_db()
        rows = db.execute("""
            SELECT DISTINCT Model
            FROM AllCars
            WHERE CAST(TRIM(ModelYear) AS INTEGER) = ?
              AND Make = ?
              AND Score IS NOT NULL AND Certainty IS NOT NULL
            ORDER BY Model
        """, (year, make)).fetchall()
        return jsonify([r["Model"] for r in rows])
    except Exception as e:
        print("Error /api/models:", e)
        return jsonify([]), 500

@app.route("/api/grade")
def grade():
    """Return Score & Certainty rounded to 1 decimal for a Y/M/M tuple."""
    year  = request.args.get("year", type=int)
    make  = request.args.get("make", type=str)
    model = request.args.get("model", type=str)

    if year is None or not make or not model:
        return jsonify({"error": "Missing params"}), 400

    try:
        db = get_db()
        row = db.execute("""
            SELECT
                ROUND(Score, 1)     AS ScoreRounded,
                ROUND(Certainty, 1) AS CertaintyRounded
            FROM AllCars
            WHERE CAST(TRIM(ModelYear) AS INTEGER) = ?
              AND Make  = ?
              AND Model = ?
              AND Score IS NOT NULL AND Certainty IS NOT NULL
            LIMIT 1
        """, (year, make, model)).fetchone()

        if not row:
            return jsonify({"error": "Not found"}), 404

        return jsonify({
            "year": year,
            "make": make,
            "model": model,
            "score": float(row["ScoreRounded"]) if row["ScoreRounded"] is not None else None,
            "certainty": float(row["CertaintyRounded"]) if row["CertaintyRounded"] is not None else None
        })
    except Exception as e:
        print("Error /api/grade:", e)
        return jsonify({"error": "Server error"}), 500


# === ONE-TIME ADMIN: upload a large DB to the mounted disk ===
# POST /admin/upload-db  with header: Authorization: Bearer <UPLOAD_TOKEN>  and form-data: file=@path/to/your.db
@app.route("/admin/upload-db", methods=["POST"])
def upload_db():
    if not UPLOAD_TOKEN:
        abort(404)  # route effectively disabled unless token is set
    token = request.headers.get("Authorization", "")
    if token != f"Bearer {UPLOAD_TOKEN}":
        abort(401, "unauthorized")
    file = request.files.get("file")
    if not file or not file.filename.lower().endswith(".db"):
        abort(400, "upload a .db file")
    tmp_path = DB_PATH + ".tmp"
    file.save(tmp_path)
    os.replace(tmp_path, DB_PATH)  # atomic replace
    return jsonify({"ok": True, "db_path": DB_PATH})


# === MAIN (local only; Render uses gunicorn) ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

