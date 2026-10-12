import os
import math
import sqlite3
import json
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_from_directory
from werkzeug.utils import secure_filename

BASE_DIR = '/Users/ajayice/DRAINAGE BLOCK TRACKER'
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
DATABASE = os.path.join(BASE_DIR, 'drainage.db')

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'))
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SECRET_KEY'] = 'drainwatch-dev-key'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def haversine(lat1, lng1, lat2, lng2):
    """Return distance in meters between two lat/lng points."""
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            severity INTEGER,
            notes TEXT,
            status TEXT DEFAULT 'Open',
            priority_score REAL DEFAULT 0,
            photo_filename TEXT,
            report_count INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()

    cur.execute('SELECT COUNT(*) FROM cases')
    count = cur.fetchone()[0]
    if count == 0:
        seed_data = [
            (12.9716, 77.5946, 4, 'Main road drain completely blocked, water logging', 'Open', 2, None, 8),
            (12.9751, 77.5993, 3, 'Partial blockage near market area', 'Assigned', 1, None, 3),
            (12.9680, 77.5880, 5, 'Severe flooding, drain overflow at junction', 'Open', 1, None, 5),
            (12.9800, 77.6010, 2, 'Minor debris accumulation', 'Resolved', 3, None, 6),
            (12.9730, 77.5850, 1, 'Small blockage, low priority', 'Resolved', 1, None, 1),
            (12.9660, 77.5960, 4, 'Storm drain blocked after heavy rain', 'Open', 2, None, 8),
            (12.9810, 77.5900, 3, 'Drain grate missing, safety hazard', 'Assigned', 1, None, 3),
            (12.9690, 77.6030, 5, 'Critical blockage causing road flooding', 'Open', 3, None, 15),
            (12.9770, 77.5970, 2, 'Leaves and debris blocking outlet', 'Open', 1, None, 2),
            (12.9640, 77.5910, 4, 'Industrial waste blocking residential drain', 'Assigned', 2, None, 8),
        ]
        cur.executemany('''
            INSERT INTO cases (lat, lng, severity, notes, status, report_count, photo_filename, priority_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', seed_data)
        conn.commit()
    conn.close()


@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/api/cases', methods=['GET'])
def get_cases():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM cases ORDER BY priority_score DESC')
    rows = cur.fetchall()
    conn.close()
    cases = []
    for row in rows:
        cases.append({
            'id': row['id'],
            'lat': row['lat'],
            'lng': row['lng'],
            'severity': row['severity'],
            'notes': row['notes'],
            'status': row['status'],
            'priority_score': row['priority_score'],
            'photo_filename': row['photo_filename'],
            'report_count': row['report_count'],
            'created_at': row['created_at'],
            'updated_at': row['updated_at'],
        })
    return jsonify(cases)


@app.route('/api/report', methods=['POST', 'OPTIONS'])
def submit_report():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        lat = float(request.form.get('lat'))
        lng = float(request.form.get('lng'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid or missing lat/lng'}), 400

    severity = int(request.form.get('severity', 3))
    notes = request.form.get('notes', '').strip()

    photo_filename = None
    if 'photo' in request.files:
        photo = request.files['photo']
        if photo and photo.filename and allowed_file(photo.filename):
            filename = secure_filename(photo.filename)
            # Avoid collisions with a timestamp prefix
            ts = datetime.utcnow().strftime('%Y%m%d%H%M%S%f')
            filename = f"{ts}_{filename}"
            photo.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            photo_filename = filename

    conn = get_db()
    cur = conn.cursor()

    # Deduplication: find active cases within 25 metres
    cur.execute("SELECT * FROM cases WHERE status != 'Resolved'")
    active_cases = cur.fetchall()

    merged_case = None
    for case in active_cases:
        dist = haversine(lat, lng, case['lat'], case['lng'])
        if dist <= 25:
            merged_case = case
            break

    if merged_case:
        new_report_count = merged_case['report_count'] + 1
        new_priority = severity * new_report_count
        merged_notes = merged_case['notes'] or ''
        if notes:
            merged_notes = merged_notes + (' | ' if merged_notes else '') + notes
        cur.execute('''
            UPDATE cases
            SET report_count = ?,
                priority_score = ?,
                notes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (new_report_count, new_priority, merged_notes, merged_case['id']))
        conn.commit()

        cur.execute('SELECT * FROM cases WHERE id = ?', (merged_case['id'],))
        updated = cur.fetchone()
        conn.close()
        return jsonify({
            'merged': True,
            'id': updated['id'],
            'lat': updated['lat'],
            'lng': updated['lng'],
            'severity': updated['severity'],
            'notes': updated['notes'],
            'status': updated['status'],
            'priority_score': updated['priority_score'],
            'photo_filename': updated['photo_filename'],
            'report_count': updated['report_count'],
            'created_at': updated['created_at'],
            'updated_at': updated['updated_at'],
        })
    else:
        priority_score = severity * 1
        cur.execute('''
            INSERT INTO cases (lat, lng, severity, notes, status, priority_score, photo_filename, report_count)
            VALUES (?, ?, ?, ?, 'Open', ?, ?, 1)
        ''', (lat, lng, severity, notes, priority_score, photo_filename))
        conn.commit()
        new_id = cur.lastrowid
        cur.execute('SELECT * FROM cases WHERE id = ?', (new_id,))
        new_case = cur.fetchone()
        conn.close()
        return jsonify({
            'merged': False,
            'id': new_case['id'],
            'lat': new_case['lat'],
            'lng': new_case['lng'],
            'severity': new_case['severity'],
            'notes': new_case['notes'],
            'status': new_case['status'],
            'priority_score': new_case['priority_score'],
            'photo_filename': new_case['photo_filename'],
            'report_count': new_case['report_count'],
            'created_at': new_case['created_at'],
            'updated_at': new_case['updated_at'],
        }), 201


@app.route('/api/cases/<int:case_id>/status', methods=['PUT', 'OPTIONS'])
def update_case_status(case_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    data = request.get_json()
    if not data or 'status' not in data:
        return jsonify({'error': 'Missing status field'}), 400

    new_status = data['status']
    if new_status not in ('Open', 'Assigned', 'Resolved'):
        return jsonify({'error': 'Invalid status value'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT id FROM cases WHERE id = ?', (case_id,))
    if not cur.fetchone():
        conn.close()
        return jsonify({'error': 'Case not found'}), 404

    cur.execute('''
        UPDATE cases SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?
    ''', (new_status, case_id))
    conn.commit()
    cur.execute('SELECT * FROM cases WHERE id = ?', (case_id,))
    updated = cur.fetchone()
    conn.close()

    return jsonify({
        'id': updated['id'],
        'status': updated['status'],
        'updated_at': updated['updated_at'],
    })


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
