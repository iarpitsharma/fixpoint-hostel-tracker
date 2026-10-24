import os
import csv
import io
import json
import sqlite3
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, session, flash, Response, jsonify

app = Flask(__name__)
app.secret_key = 'fixpoint_secret_key_change_in_production'

UPLOAD_FOLDER = os.path.join('static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DB_NAME = 'hostel.db'

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            room_no TEXT
        )
    ''')
    
    # Complaints table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            priority TEXT NOT NULL,
            status TEXT DEFAULT 'Pending',
            upvotes INTEGER DEFAULT 0,
            image_filename TEXT,
            resolution_notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # 1-vote-per-student table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS complaint_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            voted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(complaint_id, user_id),
            FOREIGN KEY (complaint_id) REFERENCES complaints (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Auto-seed and enforce the specified official Warden credentials
    cursor.execute("SELECT id FROM users WHERE username = 'warden'")
    existing_warden = cursor.fetchone()
    warden_hashed_pw = generate_password_hash('warden@123')
    
    if not existing_warden:
        cursor.execute(
            "INSERT INTO users (username, password, role, room_no) VALUES (?, ?, ?, ?)",
            ('warden', warden_hashed_pw, 'warden', 'Admin Office')
        )
    else:
        cursor.execute(
            "UPDATE users SET password = ?, role = 'warden' WHERE username = 'warden'",
            (warden_hashed_pw,)
        )
    
    conn.commit()
    conn.close()

init_db()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def update_sla_status():
    conn = get_db()
    cursor = conn.cursor()
    threshold = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('''
        UPDATE complaints 
        SET status = 'Escalated' 
        WHERE status = 'Pending' AND created_at <= ?
    ''', (threshold,))
    conn.commit()
    conn.close()

@app.route('/')
def index():
    if 'user_id' in session:
        if session.get('role') == 'warden':
            return redirect(url_for('warden_dashboard'))
        return redirect(url_for('student_dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        room_no = request.form.get('room_no', '').strip()
        
        # Enforce student role for all self-registrations
        role = 'student'
        
        if not username or not password:
            flash("Username and password are required.", "error")
            return redirect(url_for('register'))
            
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        if cursor.fetchone():
            conn.close()
            flash("Username already exists. Please choose another.", "error")
            return redirect(url_for('register'))
        
        hashed = generate_password_hash(password)
        cursor.execute(
            "INSERT INTO users (username, password, role, room_no) VALUES (?, ?, ?, ?)",
            (username, hashed, role, room_no)
        )
        conn.commit()
        conn.close()
        flash("Registration successful! Please log in.", "success")
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
        conn.close()
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['room_no'] = user['room_no']
            if user['role'] == 'warden':
                return redirect(url_for('warden_dashboard'))
            return redirect(url_for('student_dashboard'))
        flash("Invalid username or password.", "error")
        return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/student/dashboard')
def student_dashboard():
    if 'user_id' not in session or session.get('role') != 'student':
        return redirect(url_for('login'))
    
    update_sla_status()
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT c.*, u.username, u.room_no 
        FROM complaints c
        JOIN users u ON c.user_id = u.id
        ORDER BY c.created_at DESC
    ''')
    complaints = cursor.fetchall()
    
    cursor.execute(
        "SELECT complaint_id FROM complaint_votes WHERE user_id = ?",
        (session['user_id'],)
    )
    user_voted_ids = [row['complaint_id'] for row in cursor.fetchall()]
    
    conn.close()
    return render_template('student_dashboard.html', complaints=complaints, user_voted_ids=user_voted_ids)

@app.route('/complaint/new', methods=['GET', 'POST'])
def new_complaint():
    if 'user_id' not in session or session.get('role') != 'student':
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        category = request.form.get('category')
        priority = request.form.get('priority')
        description = request.form.get('description', '').strip()
        
        filename = None
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                safe_name = secure_filename(file.filename)
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S_")
                filename = timestamp + safe_name
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO complaints (user_id, title, description, category, priority, image_filename)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (session['user_id'], title, description, category, priority, filename))
        conn.commit()
        conn.close()
        
        flash("Complaint registered successfully!", "success")
        return redirect(url_for('student_dashboard'))
    return render_template('new_complaint.html')

@app.route('/upvote/<int:complaint_id>', methods=['POST'])
def upvote(complaint_id):
    if 'user_id' not in session or session.get('role') != 'student':
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT id FROM complaint_votes WHERE complaint_id = ? AND user_id = ?",
        (complaint_id, user_id)
    )
    if cursor.fetchone():
        conn.close()
        flash("You have already upvoted this complaint.", "warning")
        return redirect(url_for('student_dashboard'))
    
    cursor.execute(
        "INSERT INTO complaint_votes (complaint_id, user_id) VALUES (?, ?)",
        (complaint_id, user_id)
    )
    cursor.execute(
        "UPDATE complaints SET upvotes = upvotes + 1 WHERE id = ?",
        (complaint_id,)
    )
    conn.commit()
    conn.close()
    
    flash("Upvote recorded!", "success")
    return redirect(url_for('student_dashboard'))

@app.route('/warden/dashboard')
def warden_dashboard():
    if 'user_id' not in session or session.get('role') != 'warden':
        return redirect(url_for('login'))
    
    update_sla_status()
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT c.*, u.username, u.room_no 
        FROM complaints c
        JOIN users u ON c.user_id = u.id
        ORDER BY c.created_at DESC
    ''')
    complaints = cursor.fetchall()
    
    total = len(complaints)
    pending = sum(1 for c in complaints if c['status'] == 'Pending')
    in_progress = sum(1 for c in complaints if c['status'] == 'In Progress')
    escalated = sum(1 for c in complaints if c['status'] == 'Escalated')
    resolved = sum(1 for c in complaints if c['status'] == 'Resolved')

    category_counts = {}
    for c in complaints:
        cat = c['category']
        category_counts[cat] = category_counts.get(cat, 0) + 1

    chart_categories = list(category_counts.keys())
    chart_category_values = list(category_counts.values())

    conn.close()
    return render_template(
        'warden_dashboard.html',
        complaints=complaints,
        total=total,
        pending=pending,
        in_progress=in_progress,
        escalated=escalated,
        resolved=resolved,
        chart_categories=json.dumps(chart_categories),
        chart_category_values=json.dumps(chart_category_values)
    )

@app.route('/complaint/update/<int:complaint_id>', methods=['POST'])
def update_status(complaint_id):
    if 'user_id' not in session or session.get('role') != 'warden':
        return redirect(url_for('login'))
    
    status = request.form['status']
    notes = request.form.get('resolution_notes', '').strip()
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE complaints 
        SET status = ?, resolution_notes = ? 
        WHERE id = ?
    ''', (status, notes, complaint_id))
    conn.commit()
    conn.close()
    
    flash("Complaint updated successfully.", "success")
    return redirect(url_for('warden_dashboard'))

# Feature 1: Warden Deletion of Ticket
@app.route('/complaint/delete/<int:complaint_id>', methods=['POST'])
def delete_complaint(complaint_id):
    if 'user_id' not in session or session.get('role') != 'warden':
        return redirect(url_for('login'))
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Remove image from storage if uploaded
    cursor.execute("SELECT image_filename FROM complaints WHERE id = ?", (complaint_id,))
    complaint = cursor.fetchone()
    if complaint and complaint['image_filename']:
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], complaint['image_filename'])
        if os.path.exists(image_path):
            try:
                os.remove(image_path)
            except OSError:
                pass

    # Remove linked votes and complaint record
    cursor.execute("DELETE FROM complaint_votes WHERE complaint_id = ?", (complaint_id,))
    cursor.execute("DELETE FROM complaints WHERE id = ?", (complaint_id,))
    
    conn.commit()
    conn.close()
    
    flash(f"Ticket #{complaint_id} has been permanently deleted.", "success")
    return redirect(url_for('warden_dashboard'))

@app.route('/warden/export-csv')
def export_csv():
    if 'user_id' not in session or session.get('role') != 'warden':
        return redirect(url_for('login'))
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT c.id, u.username, u.room_no, c.title, c.category, c.priority, c.status, c.upvotes, c.resolution_notes, c.created_at
        FROM complaints c
        JOIN users u ON c.user_id = u.id
        ORDER BY c.id DESC
    ''')
    rows = cursor.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Ticket ID', 'Student', 'Room No', 'Title', 'Category', 'Priority', 'Status', 'Upvotes', 'Resolution Notes', 'Created At'])
    
    for r in rows:
        writer.writerow([r['id'], r['username'], r['room_no'], r['title'], r['category'], r['priority'], r['status'], r['upvotes'], r['resolution_notes'] or '', r['created_at']])
        
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=fixpoint_hostel_report.csv"}
    )

@app.route('/api/v1/complaints', methods=['GET'])
def api_complaints():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT c.id, u.username, u.room_no, c.title, c.description, c.category, c.priority, c.status, c.upvotes, c.created_at
        FROM complaints c
        JOIN users u ON c.user_id = u.id
        ORDER BY c.created_at DESC
    ''')
    complaints = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify({"status": "success", "count": len(complaints), "data": complaints})

if __name__ == '__main__':
    app.run(debug=True)