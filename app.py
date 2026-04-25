import os
import uuid
from datetime import datetime, date
from functools import wraps
from decimal import Decimal  # IMPORTANTE: Para precisión financiera

from flask import (Flask, render_template, redirect, url_for, flash,
                   request, abort, send_file, jsonify)
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)
from werkzeug.utils import secure_filename

from models import db, User, Prescription, Medication, Order, OrderItem, Label
from label_generator import generate_label

# ---------------------------------------------------------------------------
# App factory / config
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.config['SECRET_KEY'] = 'isss-farmacia-secret-key-2024'

# 1. Configuración de Base de Datos
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'farmacia.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 2. Creación segura de carpetas
db_folder = os.path.join(BASE_DIR, 'instance')
if not os.path.exists(db_folder):
    os.makedirs(db_folder)

app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'uploads')
app.config['LABELS_FOLDER'] = os.path.join(BASE_DIR, 'labels')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['LABELS_FOLDER'], exist_ok=True)

app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png'}

# 3. Inicialización
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
        if current_user.role == 'paciente':
            return redirect(url_for('patient_dashboard'))
        elif current_user.role == 'farmaceutico':
            return redirect(url_for('pharmacist_dashboard'))
        elif current_user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
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
            next_page = request.args.get('next')
            flash(f'¡Bienvenido, {user.nombre_completo}!', 'success')
            return redirect(next_page or url_for('index'))
        flash('Usuario o contraseña incorrectos.', 'danger')
    return render_template('auth/login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        nombre_completo = request.form.get('nombre_completo', '').strip()
        num_seguro_social = request.form.get('num_seguro_social', '').strip()

        if User.query.filter_by(username=username).first():
            flash('Ese nombre de usuario ya está en uso.', 'danger')
            return render_template('auth/register.html')

        user = User(
            username=username,
            role='paciente',
            nombre_completo=nombre_completo,
            num_seguro_social=num_seguro_social
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('Cuenta creada exitosamente. Ya puedes iniciar sesión.', 'success')
        return redirect(url_for('login'))
    return render_template('auth/register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Sesión cerrada.', 'info')
    return redirect(url_for('login'))


# ---------------------------------------------------------------------------
# Rutas de Paciente
# ---------------------------------------------------------------------------

@app.route('/paciente')
@login_required
@role_required('paciente')
def patient_dashboard():
    prescriptions = Prescription.query.filter_by(
        patient_id=current_user.id
    ).order_by(Prescription.upload_date.desc()).all()
    return render_template('patient/dashboard.html', prescriptions=prescriptions)

@app.route('/paciente/receta/subir', methods=['GET', 'POST'])
@login_required
@role_required('paciente')
def patient_upload():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No se seleccionó ningún archivo.', 'danger')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('No se seleccionó ningún archivo.', 'danger')
            return redirect(request.url)
        if not allowed_file(file.filename):
            flash('Solo se permiten archivos PDF o imágenes JPG/PNG.', 'danger')
            return redirect(request.url)

        ext = file.filename.rsplit('.', 1)[1].lower()
        unique_name = f"{uuid.uuid4().hex}.{ext}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_name))

        prescription = Prescription(
            patient_id=current_user.id,
            filename=unique_name,
            notes=request.form.get('notes', '')
        )
        db.session.add(prescription)
        db.session.commit()
        flash('Receta subida exitosamente. Pronto será atendida.', 'success')
        return redirect(url_for('patient_dashboard'))
    return render_template('patient/upload.html')

@app.route('/paciente/pago/<int:order_id>')
@login_required
@role_required('paciente')
def patient_payment(order_id):
    order = Order.query.get_or_404(order_id)
    if order.prescription.patient_id != current_user.id:
        abort(403)
    
    # Tu billetera Bitcoin configurada
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
    return render_template('patient/order_status.html',
                           prescription=prescription, orders=orders)


# ---------------------------------------------------------------------------
# Rutas de Farmacéutico
# ---------------------------------------------------------------------------

@app.route('/farmaceutico')
@login_required
@role_required('farmaceutico')
def pharmacist_dashboard():
    status_filter = request.args.get('status', 'pendiente')
    query = Prescription.query
    if status_filter and status_filter != 'todos':
        query = query.filter_by(status=status_filter)
    prescriptions = query.order_by(Prescription.upload_date.asc()).all()
    return render_template('pharmacist/dashboard.html',
                           prescriptions=prescriptions,
                           status_filter=status_filter)

@app.route('/farmaceutico/receta/<int:prescription_id>')
@login_required
@role_required('farmaceutico')
def pharmacist_prescription(prescription_id):
    prescription = Prescription.query.get_or_404(prescription_id)
    medications = Medication.query.order_by(Medication.nombre).all()
    orders = Order.query.filter_by(prescription_id=prescription_id).all()
    return render_template('pharmacist/prescription_detail.html',
                           prescription=prescription,
                           medications=medications,
                           orders=orders)

@app.route('/farmaceutico/receta/<int:prescription_id>/orden', methods=['POST'])
@login_required
@role_required('farmaceutico')
def pharmacist_create_order(prescription_id):
    prescription = Prescription.query.get_or_404(prescription_id)

    delivery_type = request.form.get('delivery_type')
    delivery_address = request.form.get('delivery_address', '').strip()

    medication_ids = request.form.getlist('medication_id[]')
    cantidades = request.form.getlist('cantidad[]')
    dosis_list = request.form.getlist('dosis_indicada[]')
    frecuencias = request.form.getlist('frecuencia[]')
    duraciones = request.form.getlist('duracion[]')

    if not medication_ids:
        flash('Debe agregar al menos un medicamento.', 'danger')
        return redirect(url_for('pharmacist_prescription', prescription_id=prescription_id))

    # Inicializamos con Decimal para evitar TypeError con modelos Numeric
    total_calculado = Decimal('0.0')

    order = Order(
        prescription_id=prescription_id,
        pharmacist_id=current_user.id,
        delivery_type=delivery_type,
        delivery_address=delivery_address if delivery_type == 'envio' else None,
        status='pendiente_pago',
        total_amount=Decimal('0.0')
    )
    db.session.add(order)
    db.session.flush()

    for i, med_id in enumerate(medication_ids):
        med = Medication.query.get(int(med_id))
        cantidad = int(cantidades[i])
        
        # Lógica de stock
        if med.stock < cantidad:
            flash(f'Stock insuficiente para {med.nombre}.', 'danger')
            return redirect(url_for('pharmacist_prescription', prescription_id=prescription_id))
            
        med.stock -= cantidad
        
        # Cálculo de subtotal con precisión Decimal
        subtotal = med.precio * Decimal(str(cantidad))
        total_calculado += subtotal

        item = OrderItem(
            order_id=order.id,
            medication_id=med.id,
            cantidad=cantidad,
            precio_unitario=med.precio,
            dosis_indicada=dosis_list[i],
            frecuencia=frecuencias[i],
            duracion=duraciones[i]
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
    order = Order.query.get_or_404(order_id)
    return render_template('pharmacist/order_detail.html', order=order)

@app.route('/farmaceutico/orden/<int:order_id>/estado', methods=['POST'])
@login_required
@role_required('farmaceutico')
def update_order_status(order_id):
    order = Order.query.get_or_404(order_id)
    new_status = request.form.get('status')
    if new_status in ('listo', 'entregado', 'en_proceso'):
        order.status = new_status
        if new_status == 'entregado':
            order.prescription.status = 'entregado'
        elif new_status == 'listo':
            order.prescription.status = 'listo'
        db.session.commit()
        flash('Estado actualizado.', 'success')
    return redirect(url_for('pharmacist_order_detail', order_id=order_id))


# ---------------------------------------------------------------------------
# Rutas de Administrador
# ---------------------------------------------------------------------------

@app.route('/admin')
@login_required
@role_required('admin')
def admin_dashboard():
    total_users = User.query.count()
    total_prescriptions = Prescription.query.count()
    pending = Prescription.query.filter_by(status='pendiente').count()
    total_orders = Order.query.count()
    low_stock_meds = Medication.query.filter(Medication.stock <= Medication.stock_minimo).all()
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(10).all()
    return render_template('admin/dashboard.html', total_users=total_users,
                           total_prescriptions=total_prescriptions, pending=pending,
                           total_orders=total_orders, low_stock_meds=low_stock_meds,
                           recent_orders=recent_orders)

@app.route('/admin/inventario')
@login_required
@role_required('admin')
def admin_inventory():
    meds = Medication.query.order_by(Medication.nombre).all()
    return render_template('admin/inventory.html', medications=meds)

@app.route('/admin/inventario/nuevo', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def admin_med_new():
    if request.method == 'POST':
        # Conversión a Decimal para no perder micro-valores
        precio_val = Decimal(request.form.get('precio', '0').replace(',', '.'))
        
        med = Medication(
            nombre=request.form['nombre'].strip(),
            concentracion=request.form['concentracion'].strip(),
            unidad=request.form['unidad'].strip(),
            precio=precio_val,
            stock=int(request.form['stock']),
            stock_minimo=int(request.form['stock_minimo'])
        )
        db.session.add(med)
        db.session.commit()
        flash('Medicamento agregado.', 'success')
        return redirect(url_for('admin_inventory'))
    return render_template('admin/med_form.html', med=None, action='Agregar')

@app.route('/admin/inventario/<int:med_id>/editar', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def admin_med_edit(med_id):
    med = Medication.query.get_or_404(med_id)
    if request.method == 'POST':
        med.nombre = request.form['nombre'].strip()
        med.concentracion = request.form['concentracion'].strip()
        med.unidad = request.form['unidad'].strip()
        # Actualización con precisión Decimal
        med.precio = Decimal(request.form.get('precio', '0').replace(',', '.'))
        med.stock = int(request.form['stock'])
        med.stock_minimo = int(request.form['stock_minimo'])
        db.session.commit()
        flash('Medicamento actualizado.', 'success')
        return redirect(url_for('admin_inventory'))
    return render_template('admin/med_form.html', med=med, action='Editar')

@app.route('/admin/inventario/<int:med_id>/eliminar', methods=['POST'])
@login_required
@role_required('admin')
def admin_med_delete(med_id):
    med = Medication.query.get_or_404(med_id)
    db.session.delete(med)
    db.session.commit()
    return redirect(url_for('admin_inventory'))

@app.route('/admin/usuarios')
@login_required
@role_required('admin')
def admin_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)

@app.route('/admin/usuarios/<int:user_id>/rol', methods=['POST'])
@login_required
@role_required('admin')
def admin_change_role(user_id):
    user = User.query.get_or_404(user_id)
    new_role = request.form.get('role')
    if new_role in ('paciente', 'farmaceutico', 'admin'):
        user.role = new_role
        db.session.commit()
        flash(f'Rol actualizado para {user.username}.', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/reportes')
@login_required
@role_required('admin')
def admin_reports():
    from sqlalchemy import func
    orders_by_day = db.session.query(
        func.date(Order.created_at).label('day'), func.count(Order.id).label('count')
    ).group_by(func.date(Order.created_at)).order_by('day').limit(30).all()

    top_meds = db.session.query(
        Medication.nombre, func.sum(OrderItem.cantidad).label('total')
    ).join(OrderItem).group_by(Medication.id).order_by(func.sum(OrderItem.cantidad).desc()).limit(10).all()

    status_counts = db.session.query(
        Prescription.status, func.count(Prescription.id)
    ).group_by(Prescription.status).all()

    return render_template('admin/reports.html', orders_by_day=orders_by_day,
                           top_meds=top_meds, status_counts=status_counts)


# ---------------------------------------------------------------------------
# Otros (Cargas y Errores)
# ---------------------------------------------------------------------------

@app.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if not os.path.exists(filepath): abort(404)
    return send_file(filepath)

@app.errorhandler(403)
def forbidden(e): return render_template('errors/403.html'), 403

@app.errorhandler(404)
def not_found(e): return render_template('errors/404.html'), 404
