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


# ── Upgrade 2: Area impact multiplier ─────────────────────────────────────────
def get_area_impact_multiplier(area_impact_tag):
    multipliers = {
        'Residential': 1.0,
        'Commercial Hub': 2.0,
        'School Zone': 3.0,
        'Hospital Zone': 4.0,
        'Main Road': 2.5,
    }
    return multipliers.get(area_impact_tag, 1.0)


def compute_priority(severity, report_count, area_impact_tag):
    m = get_area_impact_multiplier(area_impact_tag)
    return round((severity * 0.4) + (report_count * 0.3) + (m * 0.3), 2)


# ── Upgrade 4: Team routing ────────────────────────────────────────────────────
def get_team_for_zone(zone_id):
    teams = {
        'Zone-1': 'Zone-1 Rapid Action Team',
        'Zone-2': 'Zone-2 Maintenance Crew',
        'Zone-3': 'Zone-3 Rapid Action',
        'Zone-4': 'Zone-4 Civil Works',
        'Zone-5': 'Zone-5 Emergency Response',
    }
    return teams.get(zone_id, 'General Maintenance Team')


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    # Create cases table if not exists
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

    # Upgrade 1: Add new columns to cases with try/except (SQLite has no ADD COLUMN IF NOT EXISTS)
    new_columns = [
        ('area_impact', 'TEXT DEFAULT NULL'),
        ('asset_id', 'INTEGER DEFAULT NULL'),
        ('zone_id', 'TEXT DEFAULT NULL'),
        ('assigned_team', 'TEXT DEFAULT NULL'),
    ]
    for col_name, col_def in new_columns:
        try:
            cur.execute(f'ALTER TABLE cases ADD COLUMN {col_name} {col_def}')
            conn.commit()
        except Exception:
            pass  # Column already exists

    # Upgrade 1: Drop and recreate drain_assets table, then seed 15 assets
    cur.execute('DROP TABLE IF EXISTS drain_assets')
    cur.execute('''
        CREATE TABLE drain_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            lat REAL,
            lng REAL,
            zone_id TEXT,
            asset_type TEXT
        )
    ''')
    conn.commit()

    asset_types = ['Manhole', 'Drain Grate', 'Culvert']
    drain_assets = [
        # Zone-1
        ('Zone-1 Asset A', 12.9716, 77.5946, 'Zone-1', asset_types[0]),
        ('Zone-1 Asset B', 12.9740, 77.5970, 'Zone-1', asset_types[1]),
        ('Zone-1 Asset C', 12.9760, 77.5990, 'Zone-1', asset_types[2]),
        # Zone-2
        ('Zone-2 Asset A', 12.9680, 77.5900, 'Zone-2', asset_types[0]),
        ('Zone-2 Asset B', 12.9650, 77.5870, 'Zone-2', asset_types[1]),
        ('Zone-2 Asset C', 12.9700, 77.5920, 'Zone-2', asset_types[2]),
        # Zone-3
        ('Zone-3 Asset A', 12.9780, 77.6010, 'Zone-3', asset_types[0]),
        ('Zone-3 Asset B', 12.9800, 77.6030, 'Zone-3', asset_types[1]),
        ('Zone-3 Asset C', 12.9820, 77.6050, 'Zone-3', asset_types[2]),
        # Zone-4
        ('Zone-4 Asset A', 12.9640, 77.5960, 'Zone-4', asset_types[0]),
        ('Zone-4 Asset B', 12.9660, 77.5980, 'Zone-4', asset_types[1]),
        ('Zone-4 Asset C', 12.9620, 77.5940, 'Zone-4', asset_types[2]),
        # Zone-5
        ('Zone-5 Asset A', 12.9730, 77.5860, 'Zone-5', asset_types[0]),
        ('Zone-5 Asset B', 12.9750, 77.5880, 'Zone-5', asset_types[1]),
        ('Zone-5 Asset C', 12.9710, 77.5840, 'Zone-5', asset_types[2]),
    ]
    cur.executemany(
        'INSERT INTO drain_assets (name, lat, lng, zone_id, asset_type) VALUES (?, ?, ?, ?, ?)',
        drain_assets
    )
    conn.commit()

    cur.execute('SELECT COUNT(*) FROM cases')
    count = cur.fetchone()[0]
    if count == 0:
        # Seed cases with new fields; snap some to known assets and zones
        seed_data = [
            # lat, lng, severity, notes, status, report_count, photo_filename, area_impact, asset_id, zone_id, assigned_team
            (12.9716, 77.5946, 4, 'Main road drain completely blocked, water logging', 'Open', 2, None,
             'Commercial Hub', 1, 'Zone-1', get_team_for_zone('Zone-1')),
            (12.9751, 77.5993, 3, 'Partial blockage near market area', 'Assigned', 1, None,
             'Residential', None, None, 'General Maintenance Team'),
            (12.9680, 77.5880, 5, 'Severe flooding, drain overflow at junction', 'Open', 1, None,
             'Main Road', 4, 'Zone-2', get_team_for_zone('Zone-2')),
            (12.9800, 77.6010, 2, 'Minor debris accumulation', 'Resolved', 3, None,
             'Residential', 7, 'Zone-3', get_team_for_zone('Zone-3')),
            (12.9730, 77.5850, 1, 'Small blockage, low priority', 'Resolved', 1, None,
             'Residential', 13, 'Zone-5', get_team_for_zone('Zone-5')),
            (12.9660, 77.5960, 4, 'Storm drain blocked after heavy rain', 'Open', 2, None,
             'School Zone', 10, 'Zone-4', get_team_for_zone('Zone-4')),
            (12.9810, 77.5900, 3, 'Drain grate missing, safety hazard', 'Assigned', 1, None,
             'Hospital Zone', None, None, 'General Maintenance Team'),
            (12.9690, 77.6030, 5, 'Critical blockage causing road flooding', 'Open', 3, None,
             'Main Road', None, None, 'General Maintenance Team'),
            (12.9770, 77.5970, 2, 'Leaves and debris blocking outlet', 'Open', 1, None,
             'Residential', None, None, 'General Maintenance Team'),
            (12.9640, 77.5910, 4, 'Industrial waste blocking residential drain', 'Assigned', 2, None,
             'Commercial Hub', 10, 'Zone-4', get_team_for_zone('Zone-4')),
        ]
        for row in seed_data:
            (lat, lng, severity, notes, status, report_count, photo_filename,
             area_impact, asset_id, zone_id, assigned_team) = row
            priority_score = compute_priority(severity, report_count, area_impact or 'Residential')
            cur.execute('''
                INSERT INTO cases (lat, lng, severity, notes, status, report_count, photo_filename,
                                   priority_score, area_impact, asset_id, zone_id, assigned_team)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (lat, lng, severity, notes, status, report_count, photo_filename,
                  priority_score, area_impact, asset_id, zone_id, assigned_team))
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


# ── Upgrade 1: Drain assets endpoint ──────────────────────────────────────────
@app.route('/api/assets', methods=['GET'])
def get_assets():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT id, name, lat, lng, zone_id, asset_type FROM drain_assets')
    rows = cur.fetchall()
    conn.close()
    return jsonify([
        {
            'id': r['id'],
            'name': r['name'],
            'lat': r['lat'],
            'lng': r['lng'],
            'zone_id': r['zone_id'],
            'asset_type': r['asset_type'],
        }
        for r in rows
    ])


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
            'area_impact': row['area_impact'],
            'asset_id': row['asset_id'],
            'zone_id': row['zone_id'],
            'assigned_team': row['assigned_team'],
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
    area_impact = request.form.get('area_impact', 'Residential').strip() or 'Residential'

    photo_filename = None
    if 'photo' in request.files:
        photo = request.files['photo']
        if photo and photo.filename and allowed_file(photo.filename):
            filename = secure_filename(photo.filename)
            ts = datetime.utcnow().strftime('%Y%m%d%H%M%S%f')
            filename = f"{ts}_{filename}"
            photo.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            photo_filename = filename

    conn = get_db()
    cur = conn.cursor()

    # Upgrade 1: Asset snapping — find nearest drain asset within 20 m
    cur.execute('SELECT * FROM drain_assets')
    all_assets = cur.fetchall()
    snapped_asset = None
    snapped_dist = float('inf')
    for asset in all_assets:
        d = haversine(lat, lng, asset['lat'], asset['lng'])
        if d <= 20 and d < snapped_dist:
            snapped_asset = asset
            snapped_dist = d

    asset_id = snapped_asset['id'] if snapped_asset else None
    zone_id = snapped_asset['zone_id'] if snapped_asset else None
    assigned_team = get_team_for_zone(zone_id)

    snapped_to = None
    if snapped_asset:
        snapped_to = {'name': snapped_asset['name'], 'zone_id': snapped_asset['zone_id']}

    # Deduplication: find active cases within 25 metres
    cur.execute("SELECT * FROM cases WHERE status != 'Resolved'")
    active_cases = cur.fetchall()

    # Find the *nearest* active case within 25 m (not just the first one found)
    merged_case = None
    min_merge_dist = float('inf')
    for case in active_cases:
        dist = haversine(lat, lng, case['lat'], case['lng'])
        if dist <= 25 and dist < min_merge_dist:
            merged_case = case
            min_merge_dist = dist

    if merged_case:
        new_report_count = merged_case['report_count'] + 1
        # Use the merged case's area_impact (or incoming if missing)
        merged_area_impact = merged_case['area_impact'] or area_impact

        # NOTE: impact_rank is an *ordinal override comparison* map — it determines which
        # area_impact tag "wins" when merging two reports. It must NOT be aligned to the
        # multiplier values in get_area_impact_multiplier(); the ordering here is intentional
        # (e.g. School Zone ranks above Main Road for override purposes even though Main Road
        # has a higher numeric multiplier). Changing these values to match the multipliers
        # would silently break merge escalation priority.
        impact_rank = {
            'Residential': 1, 'Commercial Hub': 2, 'Main Road': 3,
            'School Zone': 4, 'Hospital Zone': 5
        }
        incoming_rank = impact_rank.get(area_impact, 1)
        existing_rank = impact_rank.get(merged_area_impact, 1)
        final_area_impact = area_impact if incoming_rank > existing_rank else merged_area_impact

        new_priority = compute_priority(merged_case['severity'], new_report_count, final_area_impact)
        merged_notes = merged_case['notes'] or ''
        if notes:
            merged_notes = merged_notes + (' | ' if merged_notes else '') + notes

        # Update asset/zone/team if previously unset and now snapped.
        # is_generic_team covers both NULL and the 'General Maintenance Team' fallback written
        # when the original case had no zone snap — so a later snapped merge can promote it.
        update_asset_id = asset_id if (asset_id and not merged_case['asset_id']) else merged_case['asset_id']
        update_zone_id = zone_id if (zone_id and not merged_case['zone_id']) else merged_case['zone_id']
        is_generic_team = (not merged_case['assigned_team'] or merged_case['assigned_team'] == 'General Maintenance Team')
        update_team = assigned_team if (zone_id and is_generic_team) else (merged_case['assigned_team'] or assigned_team)

        # photo_filename: keep existing unless new report brings a photo (COALESCE keeps old if new is NULL)
        cur.execute('''
            UPDATE cases
            SET report_count = ?,
                priority_score = ?,
                notes = ?,
                area_impact = ?,
                asset_id = ?,
                zone_id = ?,
                assigned_team = ?,
                photo_filename = COALESCE(?, photo_filename),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (new_report_count, new_priority, merged_notes, final_area_impact,
              update_asset_id, update_zone_id, update_team, photo_filename, merged_case['id']))
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
            'area_impact': updated['area_impact'],
            'asset_id': updated['asset_id'],
            'zone_id': updated['zone_id'],
            'assigned_team': updated['assigned_team'],
            'snapped_to': snapped_to,
        })
    else:
        priority_score = compute_priority(severity, 1, area_impact)
        cur.execute('''
            INSERT INTO cases (lat, lng, severity, notes, status, priority_score, photo_filename,
                               report_count, area_impact, asset_id, zone_id, assigned_team)
            VALUES (?, ?, ?, ?, 'Open', ?, ?, 1, ?, ?, ?, ?)
        ''', (lat, lng, severity, notes, priority_score, photo_filename,
              area_impact, asset_id, zone_id, assigned_team))
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
            'area_impact': new_case['area_impact'],
            'asset_id': new_case['asset_id'],
            'zone_id': new_case['zone_id'],
            'assigned_team': new_case['assigned_team'],
            'snapped_to': snapped_to,
            'asset_name': snapped_asset['name'] if snapped_asset else None,
        }), 201


@app.route('/api/cases/<int:case_id>/status', methods=['PUT', 'OPTIONS'])
def update_case_status(case_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    data = request.get_json()
    if not data or 'status' not in data:
        return jsonify({'error': 'Missing status field'}), 400

    new_status = data['status']
    if new_status not in ('Open', 'Assigned', 'In Progress', 'Resolved'):
        return jsonify({'error': 'Invalid status value'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM cases WHERE id = ?', (case_id,))
    case = cur.fetchone()
    if not case:
        conn.close()
        return jsonify({'error': 'Case not found'}), 404

    # Upgrade 4: Auto-assign team when transitioning to Assigned or In Progress.
    # Also re-evaluate if currently set to the generic fallback 'General Maintenance Team',
    # since that value is written when zone_id was unknown at creation — a later snap may
    # have filled zone_id, so we re-derive the team here.
    assigned_team = case['assigned_team']
    if new_status in ('Assigned', 'In Progress') and (not assigned_team or assigned_team == 'General Maintenance Team'):
        zone_id = case['zone_id']
        assigned_team = get_team_for_zone(zone_id)
        cur.execute('''
            UPDATE cases SET status = ?, assigned_team = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?
        ''', (new_status, assigned_team, case_id))
    else:
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
        'assigned_team': updated['assigned_team'],
    })


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5006, debug=True)
