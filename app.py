import os
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "super_secret_hostel_key_change_in_prod"

UPLOAD_FOLDER = os.path.join("static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DB_NAME = "hostel.db"

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT CHECK(role IN ('student', 'warden')),
            room_no TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            category TEXT,
            title TEXT NOT NULL,
            description TEXT,
            photo_path TEXT,
            priority TEXT DEFAULT 'Normal',
            status TEXT DEFAULT 'Pending',
            upvotes INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            deadline_at TIMESTAMP,
            resolved_at TIMESTAMP,
            resolution_notes TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    # Create default demo warden if not present
    cursor.execute("SELECT * FROM users WHERE email = 'warden@hostel.com'")
    if not cursor.fetchone():
        cursor.execute("""
            INSERT INTO users (name, email, password_hash, role, room_no)
            VALUES (?, ?, ?, ?, ?)
        """, ("Head Warden", "warden@hostel.com", generate_password_hash("warden123"), "warden", "Office-101"))
    conn.commit()
    conn.close()

init_db()

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        password = request.form.get("password")
        room_no = request.form.get("room_no")
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
        if cursor.fetchone():
            flash("Email already registered. Please login.", "danger")
            conn.close()
            return redirect(url_for("login"))
            
        hashed_pw = generate_password_hash(password)
        cursor.execute("""
            INSERT INTO users (name, email, password_hash, role, room_no)
            VALUES (?, ?, ?, 'student', ?)
        """, (name, email, hashed_pw, room_no))
        conn.commit()
        conn.close()
        flash("Registration successful! Please login.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["role"] = user["role"]
            session["room_no"] = user["room_no"]
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid email or password.", "danger")
            return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))
        
    conn = get_db()
    cursor = conn.cursor()
    
    # Auto-escalation check: tickets older than 24h that are still Pending
    twenty_four_hours_ago = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        UPDATE complaints 
        SET status = 'Escalated' 
        WHERE status = 'Pending' AND created_at <= ?
    """, (twenty_four_hours_ago,))
    conn.commit()
    
    if session["role"] == "warden":
        complaints = cursor.execute("""
            SELECT c.*, u.name as student_name, u.room_no 
            FROM complaints c 
            JOIN users u ON c.user_id = u.id 
            ORDER BY c.upvotes DESC, c.created_at DESC
        """).fetchall()
        
        total = len(complaints)
        pending = sum(1 for c in complaints if c["status"] == "Pending")
        in_progress = sum(1 for c in complaints if c["status"] == "In Progress")
        escalated = sum(1 for c in complaints if c["status"] == "Escalated")
        resolved = sum(1 for c in complaints if c["status"] == "Resolved")
        conn.close()
        return render_template("warden_dashboard.html", complaints=complaints, total=total, pending=pending, in_progress=in_progress, escalated=escalated, resolved=resolved)
    else:
        all_complaints = cursor.execute("""
            SELECT c.*, u.name as student_name, u.room_no 
            FROM complaints c 
            JOIN users u ON c.user_id = u.id 
            ORDER BY c.created_at DESC
        """).fetchall()
        conn.close()
        return render_template("student_dashboard.html", complaints=all_complaints)

@app.route("/new_complaint", methods=["GET", "POST"])
def new_complaint():
    if "user_id" not in session or session["role"] != "student":
        return redirect(url_for("login"))
        
    if request.method == "POST":
        title = request.form.get("title")
        category = request.form.get("category")
        description = request.form.get("description")
        priority = request.form.get("priority", "Normal")
        
        filename = None
        if "photo" in request.files:
            file = request.files["photo"]
            if file and allowed_file(file.filename):
                filename = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
                file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
                
        conn = get_db()
        deadline = (datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("""
            INSERT INTO complaints (user_id, category, title, description, photo_path, priority, deadline_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (session["user_id"], category, title, description, filename, priority, deadline))
        conn.commit()
        conn.close()
        flash("Complaint registered with a 24-Hour SLA guarantee!", "success")
        return redirect(url_for("dashboard"))
        
    prefill_room = request.args.get("room", session.get("room_no", ""))
    return render_template("new_complaint.html", prefill_room=prefill_room)

@app.route("/upvote/<int:complaint_id>", methods=["POST"])
def upvote(complaint_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = get_db()
    conn.execute("UPDATE complaints SET upvotes = upvotes + 1 WHERE id = ?", (complaint_id,))
    conn.commit()
    conn.close()
    flash("You upvoted this complaint! (+1 Impact recorded)", "info")
    return redirect(url_for("dashboard"))

@app.route("/update_status/<int:complaint_id>", methods=["POST"])
def update_status(complaint_id):
    if "user_id" not in session or session["role"] != "warden":
        return redirect(url_for("login"))
        
    new_status = request.form.get("status")
    resolution_notes = request.form.get("resolution_notes", "")
    resolved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if new_status == "Resolved" else None
    
    conn = get_db()
    conn.execute("""
        UPDATE complaints 
        SET status = ?, resolution_notes = ?, resolved_at = ?
        WHERE id = ?
    """, (new_status, resolution_notes, resolved_at, complaint_id))
    conn.commit()
    conn.close()
    flash(f"Complaint #{complaint_id} updated to {new_status}.", "success")
    return redirect(url_for("dashboard"))

if __name__ == "__main__":
    app.run(debug=True, port=5000)