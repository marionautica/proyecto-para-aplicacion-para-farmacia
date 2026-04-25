from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # paciente, farmaceutico, admin
    nombre_completo = db.Column(db.String(150), nullable=False)
    num_seguro_social = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    prescriptions = db.relationship('Prescription', backref='patient', lazy=True,
                                    foreign_keys='Prescription.patient_id')
    orders_processed = db.relationship('Order', backref='pharmacist', lazy=True,
                                       foreign_keys='Order.pharmacist_id')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'


class Prescription(db.Model):
    __tablename__ = 'prescriptions'
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    filename = db.Column(db.String(256), nullable=False)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='pendiente')  # pendiente, pendiente_pago, en_proceso, listo, entregado
    notes = db.Column(db.Text, nullable=True)

    orders = db.relationship('Order', backref='prescription', lazy=True)

    def status_label(self):
        labels = {
            'pendiente': 'Pendiente',
            'pendiente_pago': 'Esperando Pago', # NUEVO: Etiqueta para el paciente
            'en_proceso': 'En Proceso',
            'listo': 'Listo',
            'entregado': 'Entregado'
        }
        return labels.get(self.status, self.status)

    def status_class(self):
        classes = {
            'pendiente': 'warning',
            'pendiente_pago': 'danger', # NUEVO: Rojo/Naranja para llamar la atención del pago
            'en_proceso': 'info',
            'listo': 'success',
            'entregado': 'secondary'
        }
        return classes.get(self.status, 'secondary')

    def __repr__(self):
        return f'<Prescription {self.id}>'


class Medication(db.Model):
    __tablename__ = 'medications'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    concentracion = db.Column(db.String(100), nullable=False)
    unidad = db.Column(db.String(50), nullable=False)
    
    # NUEVO: Columna para guardar el precio base del medicamento
    precio = db.Column(db.Numeric(precision=18, scale=8), default=0.0)    
    
    stock = db.Column(db.Integer, default=0)
    stock_minimo = db.Column(db.Integer, default=10)

    order_items = db.relationship('OrderItem', backref='medication', lazy=True)

    def is_low_stock(self):
        return self.stock <= self.stock_minimo

    def __repr__(self):
        return f'<Medication {self.nombre}>'


class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.Integer, primary_key=True)
    prescription_id = db.Column(db.Integer, db.ForeignKey('prescriptions.id'), nullable=False)
    pharmacist_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    delivery_type = db.Column(db.String(20), nullable=False)  # sucursal, envio
    delivery_address = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='pendiente_pago')  # pendiente_pago, en_proceso, listo, entregado
    
    # NUEVO: Columna para guardar el total a cobrar de toda la orden
    total_amount = db.Column(db.Float, default=0.0)

    items = db.relationship('OrderItem', backref='order', lazy=True)

    def status_label(self):
        labels = {
            'pendiente_pago': 'Pendiente de Pago', # NUEVO
            'en_proceso': 'En Proceso',
            'listo': 'Listo para retirar',
            'entregado': 'Entregado'
        }
        return labels.get(self.status, self.status)

    def status_class(self):
        classes = {
            'pendiente_pago': 'danger', # NUEVO
            'en_proceso': 'info',
            'listo': 'success',
            'entregado': 'secondary'
        }
        return classes.get(self.status, 'secondary')

    def __repr__(self):
        return f'<Order {self.id}>'


class OrderItem(db.Model):
    __tablename__ = 'order_items'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    medication_id = db.Column(db.Integer, db.ForeignKey('medications.id'), nullable=False)
    cantidad = db.Column(db.Integer, nullable=False)
    
    # NUEVO: Guarda el precio exacto al momento de la venta (histórico)
    precio_unitario = db.Column(db.Float, default=0.0) 
    
    dosis_indicada = db.Column(db.String(200), nullable=False)
    frecuencia = db.Column(db.String(200), nullable=False)
    duracion = db.Column(db.String(100), nullable=False)

    label = db.relationship('Label', backref='order_item', lazy=True, uselist=False)

    def __repr__(self):
        return f'<OrderItem {self.id}>'


class Label(db.Model):
    __tablename__ = 'labels'
    id = db.Column(db.Integer, primary_key=True)
    order_item_id = db.Column(db.Integer, db.ForeignKey('order_items.id'), nullable=False)
    pdf_path = db.Column(db.String(256), nullable=False)
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Label {self.id}>'
