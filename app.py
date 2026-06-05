import os
import uuid
from datetime import datetime, date
from functools import wraps
from decimal import Decimal  # Precisión para Bitcoin


from flask import (Flask, render_template, redirect, url_for, flash,
                   request, abort, send_file, jsonify)
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)
from werkzeug.utils import secure_filename

from models import db, User, Prescription, Medication, Order, OrderItem, Label
from label_generator import generate_label

from tiankii_service import TiankiiService
# ---------------------------------------------------------------------------
# App factory / config
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.config['SECRET_KEY'] = 'isss-farmacia-secret-key-2024'

# Configuración de Base de Datos
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'farmacia.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Creación segura de carpetas vitales
db_folder = os.path.join(BASE_DIR, 'instance')
if not os.path.exists(db_folder):
    os.makedirs(db_folder)

app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'uploads')
app.config['LABELS_FOLDER'] = os.path.join(BASE_DIR, 'labels')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['LABELS_FOLDER'], exist_ok=True)

app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png'}

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
    if current_user.is_authenticated:
        return redirect(url_for('index'))
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
    # 1. Validar la existencia de la orden y la propiedad del paciente
    order = Order.query.get_or_404(order_id)
    if order.prescription.patient_id != current_user.id:
        abort(403)
        
    # Verificar si la orden ya fue pagada para evitar doble cobro
    if order.status == 'pagado':
        flash('Esta orden ya ha sido liquidada exitosamente.', 'info')
        return redirect(url_for('patient_dashboard'))

    # 2. Invocar al Sistema Eléctrico para generar el cobro real en Bitcoin
    checkout_response = TiankiiService.create_checkout(
        order_reference=order.reference_id,  # Referencia única (BIT-XXXX)
        amount=order.total_amount            # Monto exacto en Decimal
    )

    # 3. Procesar la respuesta de la pasarela
    if checkout_response.get("success"):
        print(f"⚡ Redirigiendo al paciente al checkout de Tiankii: {checkout_response['checkout_id']}")
        # Redirección directa y fluida a la factura Lightning / On-chain
        return redirect(checkout_response["payment_url"])
    else:
        # Manejo elegante de errores de conectividad o tokens sin romper la experiencia del usuario
        flash(f"No se pudo iniciar el portal de pagos: {checkout_response.get('error')}", "danger")
        return redirect(url_for('patient_dashboard'))

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
    return render_template('pharmacist/prescription_detail.html', 
                           prescription=pres, 
                           medications=Medication.query.all(), 
                           orders=Order.query.filter_by(prescription_id=prescription_id).all())

from checkout_service import CheckoutService # Asegúrate de importar el servicio al inicio

@app.route('/farmaceutico/receta/<int:prescription_id>/orden', methods=['POST'])
@login_required
@role_required('farmaceutico')
def pharmacist_create_order(prescription_id):
    # 1. Recolectamos los datos del formulario
    med_ids = request.form.getlist('medication_id[]')
    cants = request.form.getlist('cantidad[]')
    dosis = request.form.getlist('dosis_indicada[]')
    frecs = request.form.getlist('frecuencia[]')
    durs = request.form.getlist('duracion[]')

    items_data = []
    for i in range(len(med_ids)):
        items_data.append({
            'med_id': int(med_ids[i]),
            'qty': int(cants[i]),
            'dosis': dosis[i],
            'frec': frecs[i],
            'dur': durs[i]
        })

    delivery_info = {
        'type': request.form.get('delivery_type'),
        'address': request.form.get('delivery_address')
    }

    try:
        # 2. Delegamos la creación al Sótano Atómico
        # Nota: Aquí ya NO se resta stock, solo se crea la orden 'pendiente'
        order = CheckoutService.create_order_from_prescription(
            prescription_id=prescription_id,
            pharmacist_id=current_user.id,
            items_data=items_data,
            delivery_info=delivery_info
        )
        
        flash(f'Orden {order.reference_id} creada exitosamente. Esperando pago.', 'success')
        return redirect(url_for('pharmacist_order_detail', order_id=order.id))

    except Exception as e:
        flash(f'Error al crear la orden: {str(e)}', 'danger')
        return redirect(url_for('pharmacist_prescription', prescription_id=prescription_id))
    
@app.route('/farmaceutico/orden/<int:order_id>')
@login_required
@role_required('farmaceutico')
def pharmacist_order_detail(order_id):
    return render_template('pharmacist/order_detail.html', order=Order.query.get_or_404(order_id))

@app.route('/farmaceutico/orden/<int:order_id>/generar-vineta/<int:item_id>')
@login_required
@role_required('farmaceutico')
def generate_vineta(order_id, item_id):
    order = Order.query.get_or_404(order_id)
    item = OrderItem.query.get_or_404(item_id)
    if item.order_id != order_id: abort(400)
    
    existing = Label.query.filter_by(order_item_id=item_id).first()
    if existing:
        return send_file(existing.pdf_path, as_attachment=True, download_name=os.path.basename(existing.pdf_path))
    
    pdf_path = generate_label(item, app.config['LABELS_FOLDER'])
    label = Label(order_item_id=item_id, pdf_path=pdf_path)
    db.session.add(label)
    db.session.commit()
    return send_file(pdf_path, as_attachment=True, download_name=os.path.basename(pdf_path))

@app.route('/farmaceutico/orden/<int:order_id>/estado', methods=['POST'])
@login_required
@role_required('farmaceutico')
def update_order_status(order_id):
    order = Order.query.get_or_404(order_id)
    status = request.form.get('status')
    if status in ('listo', 'entregado', 'en_proceso'):
        order.status = status
        if status in ('listo', 'entregado'): 
            order.prescription.status = status
        elif status == 'en_proceso':
            order.prescription.status = 'en_proceso'
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
    return render_template('admin/dashboard.html', 
        total_users=User.query.count(), 
        total_prescriptions=Prescription.query.count(),
        pending=Prescription.query.filter_by(status='pendiente').count(),
        total_orders=Order.query.count(), 
        low_stock_meds=Medication.query.filter(Medication.stock <= Medication.stock_minimo).all(),
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
        precio = Decimal(request.form.get('precio', '0').replace(',', '.'))
        med = Medication(
            nombre=request.form['nombre'].strip(), 
            concentracion=request.form['concentracion'].strip(),
            unidad=request.form['unidad'].strip(), 
            precio=precio,
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
    flash('Medicamento eliminado.', 'success')
    return redirect(url_for('admin_inventory'))

@app.route('/admin/usuarios')
@login_required
@role_required('admin')
def admin_users():
    return render_template('admin/users.html', users=User.query.order_by(User.created_at.desc()).all())

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

@app.route('/admin/recetas')
@login_required
@role_required('admin')
def admin_prescriptions():
    status_filter = request.args.get('status', '')
    query = Prescription.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    prescriptions = query.order_by(Prescription.upload_date.desc()).all()
    return render_template('admin/prescriptions.html',
                           prescriptions=prescriptions,
                           status_filter=status_filter)


# ---------------------------------------------------------------------------
# Webhooks y APIs
# ---------------------------------------------------------------------------
from flask import request, jsonify

@app.route('/webhook/tiankii', methods=['POST'])
def tiankii_webhook():
    """
    Sensor Asíncrono de Pagos - API v1 Certificada.
    Recibe la confirmación de Tiankii, extrae los metadatos anidados 
    y ejecuta la transacción atómica de inventario.
    """
    try:
        # 1. Captura del payload JSON enviado por Tiankii
        payload = request.get_json()
        if not payload:
            print("⚠️ Webhook rechazado: Cuerpo de petición ausente.")
            return jsonify({"error": "Cuerpo de petición ausente"}), 400

        # 2. Extracción de variables con tipado seguro y desanidación (Defensa en profundidad)
        invoice_id = payload.get('invoiceId')  # ID único de la factura de Tiankii (ej: 'inv-xyz789')
        status = payload.get('status', '').upper() 
        
        # Ojo aquí: Extraemos de 'metadata' tal como exige la estructura v1
        metadata = payload.get('metadata', {})
        order_reference = None
        
        if isinstance(metadata, dict):
            order_reference = metadata.get('orderId')
            
        # Fallback de respaldo: por si Tiankii aplanara el JSON en actualizaciones de red
        if not order_reference:
            order_reference = payload.get('orderId')

        print(f"🔔 Webhook Tiankii: Pulso recibido -> Invoice: {invoice_id} | Orden Interna: {order_reference} | Estado: {status}")

        # Validación de seguridad: Asegurar que podemos identificar el pedido antes de proceder
        if not order_reference:
            print(f"⚠️ Alerta: Webhook procesado sin orderId válido. Estructura del payload: {payload}")
            return jsonify({"error": "No se pudo mapear la referencia interna de la orden"}), 400

        # 3. Lógica de Negocio: Tiankii v1 opera con el estado 'paid'
        if status in ['PAID', 'COMPLETED', 'SUCCESS']:
            
            # CheckoutService ejecuta la lógica atómica de base de datos
            success = CheckoutService.finalize_payment(order_reference)
            
            if success:
                print(f"✅ ÉXITO: Stock de la orden {order_reference} descontado y pago asentado.")
            else:
                print(f"⚠️ Info: CheckoutService omitió el proceso. La orden {order_reference} ya estaba completada o no requiere stock.")

        # 4. Idempotencia: Devolver HTTP 200 rápido a Tiankii para cerrar el loop de reintentos
        return jsonify({
            "received": True, 
            "invoiceId": invoice_id, 
            "processed_status": status
        }), 200

    except Exception as e:
        print(f"❌ FATAL: Error crítico de servidor procesando webhook de Tiankii: {str(e)}")
        # Devolver 500 le indica a Tiankii que nuestro backend tuvo un tropiezo temporal
        # y que debe aplicar su política de reintentos (Retry Policy) más tarde.
        return jsonify({"error": "Error interno del servidor en procesamiento de pagos"}), 500


# ---------------------------------------------------------------------------
# Otros (Gestión de Archivos y Errores)
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

with app.app_context():
    # 1. Crea físicamente el archivo .db y las tablas si no existen
    db.create_all()
    
    # 2. Asegura que el usuario admin exista tras el Hard Reset
    if not User.query.filter_by(username='admin').first():
        admin = User(
            username='admin',
            role='admin',
            nombre_completo='Administrador del Sistema'
        )
        admin.set_password('admin123') # Contraseña temporal
        db.session.add(admin)
        db.session.commit()
        print("✅ EOS: Base de Datos y Admin inicializados en Railway.")

if __name__ == '__main__':
    # Railway inyecta el puerto en esta variable de entorno
    port = int(os.environ.get("PORT", 5000))
    # host='0.0.0.0' abre la escucha a redes externas (Internet)
    app.run(host='0.0.0.0', port=port)
