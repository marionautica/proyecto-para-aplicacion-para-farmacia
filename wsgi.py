import os
from app import app, db
from models import User, Medication


def init_db():
    with app.app_context():
        db.create_all()
        # Admin por defecto si no existe
        if not User.query.filter_by(username='admin').first():
            admin = User(
                username='admin',
                role='admin',
                nombre_completo='Administrador Bitfarma',
                num_seguro_social='ADMIN-0001'
            )
            admin.set_password('admin123')
            db.session.add(admin)

        if not User.query.filter_by(username='farmacia').first():
            farm = User(
                username='farmacia',
                role='farmaceutico',
                nombre_completo='Lic. María González',
                num_seguro_social='FARM-0001'
            )
            farm.set_password('farm123')
            db.session.add(farm)

        db.session.commit()


# Inicializar DB al arrancar en Railway
init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port)
