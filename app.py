import os
import uuid
from datetime import datetime, date
from functools import wraps
from decimal import Decimal  # Pieza clave para la precisión financiera

from flask import (Flask, render_template, redirect, url_for, flash,
                   request, abort, send_file, jsonify)
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)
from werkzeug.utils import secure_filename

from models import db, User, Prescription, Medication, Order, OrderItem, Label
from label_generator import generate_label

# ---------------------------------------------------------------------------
# App factory / config (El motor del sistema)
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.config['SECRET_KEY'] = 'isss-farmacia-secret-key-2024'

# Configuración de Base de Datos
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'farmacia.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Creación automática de directorios necesarios
db_folder = os.path.join(BASE_DIR, 'instance')
if not os.path.exists(db_folder):
    os.makedirs(db_folder)

app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'uploads')
app.config['LABELS_FOLDER'] = os.path.join(BASE_DIR, 'labels')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['LABELS_FOLDER'], exist_ok=True)

app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png'}

# Inicialización
db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Por favor inicia sesión para continuar.'
login_manager.login_message_category = 'warning'

# ---------------------------------------------------------------------------
# Helpers y Seguridad
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
        destinos = {'paciente': 'patient_dashboard', 'farmaceutico': 'pharmacist_dashboard', 'admin': 'admin_dashboard'}
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
        flash('Registro exitoso. Inicia sesión.', 'success')
        return redirect(url_for('login'))
    return render_template('auth/register.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

# ---------------------------------------------------------------------------
# Rutas de Paciente
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
            flash('Receta subida con éxito.', 'success')
            return redirect(url_for('patient_dashboard'))
    return render_template('patient/upload.html')

@app.route('/paciente/pago/<int:order_id>')
@login_required
@role_required('paciente')
def patient_payment(order_id):
    order = Order.query.get_or_404(order_id)
    if order.prescription.patient_id != current_user.id: abort(403)
    wallet_btc = "bc1pxhx0sd05wfp7fclykuqgmn48s7xh3ts27yxranzy6u30dspys2xqauks2u"
    return render_template('patient/payment.html', order=order, wallet=wallet_btc)

@app.route('/paciente/receta/<int:prescription_id>')
@login_required
@role_required('paciente')
def patient_order_status(prescription_id):
    prescription = Prescription.query.get_or_404(prescription_id)
    if prescription.patient_id != current_user.id: abort(403)
    orders = Order.query.filter_by(prescription_id=prescription_id).all()
    return render_template('patient/order_status.html', prescription=prescription, orders=orders)

# ---------------------------------------------------------------------------
# Rutas de Farmacéutico
# ---------------------------------------------------------------------------

@app.route('/farmaceutico')
@login_required
@role_required('farmaceutico')
def pharmacist_dashboard():
    status = request.args.get('status', 'pendiente')
    query = Prescription.query.filter_by(status=status) if status != 'todos' else Prescription.query
    prescriptions = query.order_by(Prescription.upload_date.asc()).all()
    return render_template('pharmacist/dashboard.html', prescriptions=prescriptions, status_filter=status)

@app.route('/farmaceutico/receta/<int:prescription_id>')
@login_required
@role_required('farmaceutico')
def pharmacist_prescription(prescription_id):
    pres = Prescription.query.get_or_404(prescription_id)
    return render_template('pharmacist/prescription_detail.html', prescription=pres, medications=Medication.query.all(), orders=Order.query.filter_by(prescription_id=prescription_id).all())

@app.route('/farmaceutico/receta/<int:prescription_id>/orden', methods=['POST'])
@login_required
@role_required('farmaceutico')
def pharmacist_create_order(prescription_id):
    prescription = Prescription.query.get_or_404(prescription_id)
    
    # SINCRONIZACIÓN DECIMAL: El total comienza como Decimal para evitar TypeError
    total_calculado = Decimal('0.0')
    
    order = Order(
        prescription_id=prescription_id, 
        pharmacist_id=current_user.id,
        delivery_type=request.form.get('delivery_type'),
        delivery_address=request.form.get('delivery_address'),
        status='pendiente_pago',
        total_amount=Decimal('0.0')
    )
    db.session.add(order)
    db.session.flush()

    med_ids = request.form.getlist('medication_id[]')
    cants = request.form.getlist('cantidad[]')
    
    for i, m_id in enumerate(med_ids):
        med = Medication.query.get(int(m_id))
        cantidad = int(cants[i])
        
        # Operación protegida entre Decimals
        subtotal = med.precio * Decimal(str(cantidad))
        total_calculado += subtotal
        
        med.stock -= cantidad
        item = OrderItem(
            order_id=order.id, medication_id=med.id, cantidad=cantidad,
            precio_unitario=med.precio, dosis_indicada=request.form.getlist('dosis_indicada[]')[i],
            frecuencia=request.form.getlist('frecuencia[]')[i], duracion=request.form.getlist('duracion[]')[i]
        )
        db.session.add(item)

    order.total_amount = total_calculado
    prescription.status = 'pendiente_pago'
    db.session.commit()
    flash(f'Orden creada. Total: ${total_calculado:.8f}', 'success')
    return redirect(url_for('pharmacist_order_detail', order_id=order.id))

@app.route('/farmaceutico/orden/<int:order_id>')
@login_required
@role_required('farmaceutico')
def pharmacist_order_detail(order_id):
    return render_template('pharmacist/order_detail.html', order=Order.query.get_or_404(order_id))

@app.route('/farmaceutico/orden/<int:order_id>/estado', methods=['POST'])
@login_required
@role_required('farmaceutico')
def update_order_status(order_id):
    order = Order.query.get_or_404(order_id)
    status = request.form.get('status')
    if status in ('listo', 'entregado', 'en_proceso'):
        order.status = status
        if status in ('listo', 'entregado'): order.prescription.status = status
        db.session.commit()
    return redirect(url_for('pharmacist_order_detail', order_id=order_id))

# ---------------------------------------------------------------------------
# Rutas de Administrador (Engranaje Completo)
# ---------------------------------------------------------------------------

@app.route('/admin')
@login_required
@role_required('admin')
def admin_dashboard():
    return render_template('admin/dashboard.html', 
        total_users=User.query.count(), total_prescriptions=Prescription.query.count(),
        pending=Prescription.query.filter_by(status='pendiente').count(),
        total_orders=Order.query.count(), low_stock_meds=Medication.query.filter(Medication.stock <= Medication.stock_minimo).all(),
        recent_orders=Order.query.order_by(Order.created_at.desc()).limit(10).all())

@app.route('/admin/inventario')
@login_required
@role_required('admin')
def admin_inventory():
    return render_template('admin/inventory.html', medications=Medication.query.order_by(Medication.nombre).all())

@app.route('/admin/inventario/nuevo', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def admin_med_new():
    if request.method == 'POST':
        # Entrada de datos convertida a Decimal para soportar micro-decimales
        precio = Decimal(request.form.get('precio', '0').replace(',', '.'))
        med = Medication(
            nombre=request.form['nombre'].strip(), concentracion=request.form['concentracion'].strip(),
            unidad=request.form['unidad'].strip(), precio=precio,
            stock=int(request.form['stock']), stock_minimo=int(request.form['stock_minimo'])
        )
        db.session.add(med)
        db.session.commit()
        return redirect(url_for('admin_inventory'))
    return render_template('admin/med_form.html', med=None, action='Agregar')

@app.route('/admin/inventario/<int:med_id>/editar', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def admin_med_edit(med_id):
    med = Medication.query.get_or_404(med_id)
    if request.method == 'POST':
        med.nombre = request.form['nombre'].strip()
        med.precio = Decimal(request.form.get('precio', '0').replace(',', '.'))
        med.stock = int(request.form['stock'])
        db.session.commit()
        return redirect(url_for('admin_inventory'))
    return render_template('admin/med_form.html', med=med, action='Editar')

@app.route('/admin/usuarios')
@login_required
@role_required('admin')
def admin_users():
    return render_template('admin/users.html', users=User.query.all())

# ---------------------------------------------------------------------------
# Otros (Archivos y Errores)
# ---------------------------------------------------------------------------

@app.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], filename))

@app.errorhandler(403)
def forbidden(e): return render_template('errors/403.html'), 403

@app.errorhandler(404)
def not_found(e): return render_template('errors/404.html'), 404
