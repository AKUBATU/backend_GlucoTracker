from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity
)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import RandomForestRegressor
from sklearn.pipeline import make_pipeline
from pytz import timezone
import pandas as pd
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'supersecretkey'
app.config['JWT_SECRET_KEY'] = 'glucotracker-secret-jwt'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///glucotracker.db'
app.config['JWT_TOKEN_LOCATION'] = ['headers']
app.config['JWT_HEADER_NAME'] = 'Authorization'
app.config['JWT_HEADER_TYPE'] = 'Bearer'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

jwt = JWTManager(app)
CORS(app, origins=["http://localhost:3000"])
db = SQLAlchemy(app)
tz = timezone('Asia/Jakarta')

# ---------- Models ----------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120))
    email = db.Column(db.String(120), unique=True)
    password_hash = db.Column(db.String(128))
    age = db.Column(db.Integer)
    height = db.Column(db.Integer)
    weight = db.Column(db.Integer)

class GlucoseLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    input_type = db.Column(db.String(10))
    input_value = db.Column(db.Text)
    sugar_result = db.Column(db.Float)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(tz))

class Badge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True)
    description = db.Column(db.String(255))
    icon = db.Column(db.String(120))

class UserBadge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    badge_id = db.Column(db.Integer, db.ForeignKey('badge.id'))
    achieved_at = db.Column(db.DateTime, default=lambda: datetime.now(tz))

# ---------- Badge Logic ----------
def award_badge(user_id, badge_name):
    badge = Badge.query.filter_by(name=badge_name).first()
    if not badge:
        return
    existing = UserBadge.query.filter_by(user_id=user_id, badge_id=badge.id).first()
    if not existing:
        user_badge = UserBadge(user_id=user_id, badge_id=badge.id)
        db.session.add(user_badge)
        db.session.commit()

def is_streak_7(dates):
    today = datetime.now(tz).date()
    for i in range(7):
        check_day = today - timedelta(days=i)
        if check_day.strftime('%Y-%m-%d') not in dates:
            return False
    return True

def check_and_award_badges(user_id):
    logs = GlucoseLog.query.filter_by(user_id=user_id).all()
    dates = sorted(set(log.timestamp.strftime('%Y-%m-%d') for log in logs))

    if len(dates) >= 1:
        award_badge(user_id, "Pemula Sehat")
    if len(dates) >= 7 and is_streak_7(dates):
        award_badge(user_id, "Konsisten Harian")
    if len(logs) >= 100:
        award_badge(user_id, "Ahli Gula")

# ---------- ML Model ----------
df = pd.read_csv('food_sugar_data.csv')
df['combined_text'] = df['nama_makanan'] + ' ' + df['jenis'] + ' ' + df['kategori']
X = df['combined_text']
y = df['gula_per_100g']
model = make_pipeline(TfidfVectorizer(), RandomForestRegressor(n_estimators=100, random_state=42))
model.fit(X, y)

@app.after_request
def add_headers(response):
    response.headers['Content-Type'] = 'application/json'
    response.headers['Cache-Control'] = 'no-store'
    return response

@app.route('/')
def index():
    return jsonify({'message': 'API GlucoTracker with JWT is running'})

# ---------- Auth ----------
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    required_fields = ['name', 'email', 'password', 'age', 'height']
    for field in required_fields:
        if field not in data or data[field] == '':
            return jsonify({'message': f'{field} wajib diisi'}), 400

    if User.query.filter_by(email=data['email']).first():
        return jsonify({'message': 'Email sudah digunakan'}), 400

    user = User(
        name=data['name'],
        email=data['email'],
        password_hash=generate_password_hash(data['password']),
        age=int(data['age']),
        height=int(data['height']),
        weight=int(data['weight']) if data.get('weight') else None
    )
    db.session.add(user)
    db.session.commit()
    return jsonify({'message': 'Registrasi berhasil'}), 201

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    user = User.query.filter_by(email=data['email']).first()
    if user and check_password_hash(user.password_hash, data['password']):
        token = create_access_token(identity=str(user.id))
        return jsonify({
            'access_token': token,
            'user': {
                'id': user.id,
                'name': user.name,
                'email': user.email,
                'age': user.age,
                'height': user.height,
                'weight': user.weight
            }
        })
    return jsonify({'message': 'Email atau password salah'}), 401

@app.route('/validate-token', methods=['GET'])
@jwt_required()
def validate_token():
    user_id = get_jwt_identity()
    return jsonify({'message': 'Token valid', 'user_id': user_id}), 200

@app.route('/update-profile', methods=['POST'])
@jwt_required()
def update_profile():
    user_id = get_jwt_identity()
    data = request.form
    user = User.query.get(user_id)

    user.age = int(data.get('age', user.age))
    user.height = int(data.get('height', user.height))
    user.weight = int(data.get('weight', user.weight)) if data.get('weight') else user.weight

    if 'profile_picture' in request.files:
        pic = request.files['profile_picture']
        filename = f"profile_{user.id}.jpg"
        os.makedirs('static', exist_ok=True)
        pic.save(os.path.join('static', filename))

    db.session.commit()
    return jsonify({'message': 'Profil berhasil diperbarui'})

# ---------- Prediksi + Badge ----------
@app.route('/predict', methods=['POST'])
@jwt_required()
def predict():
    user_id = get_jwt_identity()
    data = request.json
    makanan = data.get('makanan', [])
    prediksi = model.predict(makanan)
    total = float(sum(prediksi))

    log = GlucoseLog(
        user_id=user_id,
        input_type='manual',
        input_value=", ".join(makanan),
        sugar_result=total,
        timestamp=datetime.now(tz)
    )
    db.session.add(log)
    db.session.commit()

    check_and_award_badges(user_id)

    return jsonify({'total_gula': total, 'detail': list(zip(makanan, prediksi.tolist()))})

@app.route('/latest', methods=['GET'])
@jwt_required()
def latest():
    user_id = get_jwt_identity()
    log = GlucoseLog.query.filter_by(user_id=user_id).order_by(GlucoseLog.timestamp.desc()).first()
    if not log:
        return jsonify({'message': 'Belum ada data'})
    return jsonify({
        'input': log.input_value,
        'total_gula': log.sugar_result,
        'timestamp': log.timestamp.strftime('%Y-%m-%d %H:%M:%S')
    })

@app.route('/history')
@jwt_required()
def history():
    user_id = get_jwt_identity()
    query_date = request.args.get('date')
    target_date = datetime.strptime(query_date, '%Y-%m-%d').date() if query_date else datetime.now(tz).date()

    start = datetime.combine(target_date, datetime.min.time())
    end = datetime.combine(target_date, datetime.max.time())

    logs = GlucoseLog.query.filter_by(user_id=user_id).filter(
        GlucoseLog.timestamp >= start,
        GlucoseLog.timestamp <= end
    ).order_by(GlucoseLog.timestamp.desc()).all()

    return jsonify([{
        'id': log.id,
        'input': log.input_value,
        'sugar_result': log.sugar_result,
        'timestamp': log.timestamp.strftime('%Y-%m-%d %H:%M:%S')
    } for log in logs])

@app.route('/history/summary')
@jwt_required()
def history_summary():
    user_id = get_jwt_identity()
    now_local = datetime.now(tz)
    weekday = now_local.weekday()
    start_of_week_local = datetime.combine(now_local.date(), datetime.min.time()) - timedelta(days=weekday)
    end_of_week_local = start_of_week_local + timedelta(days=6, hours=23, minutes=59, seconds=59)

    logs = GlucoseLog.query.filter(
        GlucoseLog.user_id == user_id,
        GlucoseLog.timestamp >= start_of_week_local,
        GlucoseLog.timestamp <= end_of_week_local
    ).all()

    summary = {
        (start_of_week_local + timedelta(days=i)).strftime('%Y-%m-%d'): 0
        for i in range(7)
    }

    for log in logs:
        date_str = log.timestamp.strftime('%Y-%m-%d')
        if date_str in summary:
            summary[date_str] += log.sugar_result

    return jsonify([
        {"date": date, "total_sugar": summary[date]}
        for date in sorted(summary)
    ])

@app.route('/history/delete/<int:log_id>', methods=['DELETE'])
@jwt_required()
def delete_log(log_id):
    user_id = get_jwt_identity()
    log = GlucoseLog.query.filter_by(id=log_id, user_id=user_id).first()
    if not log:
        return jsonify({'message': 'Data tidak ditemukan'}), 404
    db.session.delete(log)
    db.session.commit()
    return jsonify({'message': 'Riwayat berhasil dihapus'})

@app.route('/badges', methods=['GET'])
@jwt_required()
def get_user_badges():
    user_id = get_jwt_identity()
    user_badges = UserBadge.query.filter_by(user_id=user_id).all()
    result = []
    for ub in user_badges:
        badge = Badge.query.get(ub.badge_id)
        result.append({
            'name': badge.name,
            'description': badge.description,
            'icon': badge.icon,
            'achieved_at': ub.achieved_at.strftime('%Y-%m-%d %H:%M:%S')
        })
    return jsonify(result)

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

# ---------- Badge Seeder ----------
def seed_badges():
    if Badge.query.count() == 0:
        db.session.add_all([
            Badge(name="Pemula Sehat", description="Input makanan pertamamu berhasil!", icon="starter.png"),
            Badge(name="Konsisten Harian", description="Input makanan 7 hari berturut-turut!", icon="streak7.png"),
            Badge(name="Ahli Gula", description="Telah mencapai 20 riwayat pencatatan konsumsi gula", icon="expert.png"),
            Badge(name="Target  Tercapai", description="Total konsumsi gula hari ini di bawah 25g", icon="target.png")
        ])
        db.session.commit()
        print("✅ Badge berhasil ditambahkan.")

if __name__ == '__main__':
    import os
    os.makedirs('static', exist_ok=True)

    with app.app_context():
        db.create_all()
        seed_badges()

    app.run(host='0.0.0.0', port=3000, debug=True)
