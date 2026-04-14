"""
Punto de entrada de la aplicación Bitfarma.
Inicializa la base de datos y crea datos de prueba.
"""
import os
from app import app, db
from models import User, Medication


def init_db():
    with app.app_context():
        db.create_all()
        _seed_data()
        print("✅ Base de datos inicializada.")


def _seed_data():
    # Admin user
    if not User.query.filter_by(username='admin').first():
        admin = User(
            username='admin',
            role='admin',
            nombre_completo='Administrador ISSS',
            num_seguro_social='ADMIN-0001'
        )
        admin.set_password('admin123')
        db.session.add(admin)
        print("   → Usuario admin creado (admin/admin123)")

    # Pharmacist user
    if not User.query.filter_by(username='farmacia').first():
        farm = User(
            username='farmacia',
            role='farmaceutico',
            nombre_completo='Lic. María González',
            num_seguro_social='FARM-0001'
        )
        farm.set_password('farm123')
        db.session.add(farm)
        print("   → Farmacéutico creado (farmacia/farm123)")

    # Patient user (test)
    if not User.query.filter_by(username='paciente1').first():
        pat = User(
            username='paciente1',
            role='paciente',
            nombre_completo='Juan Carlos Martínez',
            num_seguro_social='07010112345678'
        )
        pat.set_password('paciente123')
        db.session.add(pat)
        print("   → Paciente de prueba creado (paciente1/paciente123)")

    # Medications inventory
    meds_data = [
        ('Amoxicilina', '500 mg', 'cápsulas', 200, 20),
        ('Metformina', '850 mg', 'tabletas', 300, 30),
        ('Losartán', '50 mg', 'tabletas', 150, 15),
        ('Omeprazol', '20 mg', 'cápsulas', 250, 25),
        ('Ibuprofeno', '400 mg', 'tabletas', 180, 20),
        ('Atenolol', '50 mg', 'tabletas', 100, 10),
        ('Amlodipino', '5 mg', 'tabletas', 120, 12),
        ('Metronidazol', '500 mg', 'tabletas', 90, 10),
        ('Paracetamol', '500 mg', 'tabletas', 500, 50),
        ('Ranitidina', '150 mg', 'tabletas', 8, 15),  # Low stock
        ('Salbutamol', '100 mcg', 'inhalador', 5, 10),  # Low stock
        ('Enalapril', '10 mg', 'tabletas', 130, 15),
        ('Hidroclorotiazida', '25 mg', 'tabletas', 110, 10),
        ('Glibenclamida', '5 mg', 'tabletas', 75, 10),
        ('Furosemida', '40 mg', 'tabletas', 95, 10),
    ]

    for nombre, conc, unidad, stock, stock_min in meds_data:
        if not Medication.query.filter_by(nombre=nombre, concentracion=conc).first():
            med = Medication(
                nombre=nombre,
                concentracion=conc,
                unidad=unidad,
                stock=stock,
                stock_minimo=stock_min
            )
            db.session.add(med)

    db.session.commit()
    print("   → Medicamentos de ejemplo cargados.")


if __name__ == '__main__':
    os.makedirs(os.path.join(os.path.dirname(__file__), 'instance'), exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(__file__), 'uploads'), exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(__file__), 'labels'), exist_ok=True)
    init_db()
    print("\n🏥 Bitfarma - Iniciando servidor...")
    print("   URL: http://127.0.0.1:5000")
    print("   Admin:      admin / admin123")
    print("   Farmacéutico: farmacia / farm123")
    print("   Paciente:   paciente1 / paciente123\n")
    port = int(os.environ.get('PORT', 5001))
    app.run(debug=True, host='0.0.0.0', port=port)
