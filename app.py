import os
import uuid
from datetime import datetime, date
from functools import wraps
from decimal import Decimal  # Pieza fundamental para la precisión de Bitcoin

from flask import (Flask, render_template, redirect, url_for, flash,
                   request, abort, send_file, jsonify)
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)
from werkzeug.utils import secure_filename

# Importación de componentes internos
from models import db, User, Prescription, Medication, Order, OrderItem, Label
from label_generator import generate_label

# ---------------------------------------------------------------------------
# Configuración y Fábrica de la App
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.config['SECRET_KEY'] = 'isss-farmacia-secret-key-2024'

# 1. Configuración de Base de Datos (SQLite)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'farmacia.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 2. Blindaje de Directorios (Asegura que Railway no falle al arrancar)
db_folder = os.path.join(BASE_DIR, 'instance')
if not os.path.exists(db_folder):
    os.makedirs(db_folder)

app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'uploads')
app.config['LABELS_FOLDER'] = os.path.join(BASE_DIR, 'labels')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['LABELS_FOLDER'], exist_ok=True)

app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # Límite de 10 MB
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png'}

# 3. Inicialización de Extensiones
db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Por favor inicia sesión para continuar.'
login_manager.login_message_category = 'warning'


# ---------------------------------------------------------------------------
# Helpers de Seguridad y Lógica Global
# ---------------------------------------------------------------------------

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('login'))
            if current_user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.context_processor
def inject_globals():
    """Mantiene el contador de stock bajo actualizado en la barra de navegación."""
    low_stock_count = 0
    if current_user.is_authenticated and current_user.role in ('admin', 'farmaceutico'):
        try:
            low_stock_count = Medication.query.filter(
                Medication.stock <= Medication.stock_minimo
            ).count()
        except:
            low_stock_count = 0
    return dict(low_stock_count=low_stock_count)


# ---------------------------------------------------------------------------
# Rutas de Autenticación
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    if current_user.is_authenticated:
        destinos = {
            'paciente': 'patient_dashboard', 
            'farmaceutico': 'pharmacist_dashboard', 
            'admin': 'admin_dashboard'
        }
        return redirect(url_for(destinos.get(current_user.role, 'login')))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            flash(f'¡Bienvenido, {user.nombre_completo}!', 'success')
            return redirect(request.args.get('next') or url_for('index'))
        flash('Usuario o contraseña incorrectos.', 'danger')
    return render_template('auth/login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        if User.query.filter_by(username=username).first():
            flash('El nombre de usuario ya existe.', 'danger')
            return render_template('auth/register.html')
        
        user = User(
            username=username,
            role='paciente',
            nombre_completo=request.form.get('nombre_completo', '').strip(),
            num_seguro_social=request.form.get('num_seguro_social', '').strip()
        )
        user.set_password(request.form.get('password', ''))
        db.session.add(user)
        db.session.commit()
        flash('Registro exitoso. Ya puedes iniciar sesión.', 'success')
        return redirect(url_for('login'))
    return render_template('auth/register.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))


# ---------------------------------------------------------------------------
# Rutas de Paciente (Dashboard y Pagos Bitcoin)
# ---------------------------------------------------------------------------

@app.route('/paciente')
@login_required
@role_required('paciente')
def patient_dashboard():
    prescriptions = Prescription.query.filter_by(patient_id=current_user.id).order_by(Prescription.upload_date.desc()).all()
    return render_template('patient/dashboard.html', prescriptions=prescriptions)

@app.route('/paciente/receta/subir', methods=['GET', 'POST'])
@login_required
@role_required('paciente')
def patient_upload():
    if request.method == 'POST':
        file = request.files.get('file')
        if file and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = f"{uuid.uuid4().hex}.{ext}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            pres = Prescription(patient_id=current_user.id, filename=filename, notes=request.form.get('notes', ''))
            db.session.add(pres)
            db.session.commit()
            flash('Receta enviada a revisión.', 'success')
            return redirect(url_for('patient_dashboard'))
    return render_template('patient/upload.html')

@app.route('/paciente/pago/<int:order_id>')
@login_required
@role_required('paciente')
def patient_payment(order_id):
    """Pasarela de pago real conectada a tu billetera."""
    order = Order.query.get_or_404(order_id)
    if order.prescription.patient_id != current_user.id:
        abort(403)
    
    # TU BILLETERA REAL
    wallet_btc = "bc1pxhx0sd05wfp7fclykuqgmn48s7xh3ts27yxranzy6u30dspys2xqauks2u"
    return render_template('patient/payment.html', order=order, wallet=wallet_btc)

@app.route('/paciente/receta/<int:prescription_id>')
@login_required
@role_required('paciente')
def patient_order_status(prescription_id):
    prescription = Prescription.query.get_or_404(prescription_id)
    if prescription.patient_id != current_user.id:
        abort(403)
    orders = Order.query.filter_by(prescription_id=prescription_id).all()
    return render_template('patient/order_status.html', prescription=prescription, orders=orders)


# ---------------------------------------------------------------------------
# Rutas de Farmacéutico (Cálculo Financiero de Precisión)
# ---------------------------------------------------------------------------

@app.route('/farmaceutico/receta/<int:prescription_id>')
@login_required
@role_required('farmaceutico')
def pharmacist_prescription(prescription_id):
    pres = Prescription.query.get_or_404(prescription_id)
    return render_template('pharmacist/prescription_detail.html', 
                           prescription=pres, 
                           medications=Medication.query.all(), 
                           orders=Order.query.filter_by(prescription_id=prescription_id).all())
