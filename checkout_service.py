import uuid
from decimal import Decimal
from models import db, Order, OrderItem, Medication, Prescription

class CheckoutService:
    @staticmethod
    def create_order_from_prescription(prescription_id, pharmacist_id, items_data, delivery_info):
        """
        PASO 1: Crea la orden en estado 'pendiente_pago'.
        Registra la intención de compra pero NO descuenta stock todavía.
        """
        try:
            total_calculado = Decimal('0.0')
            order_ref = f"BIT-{uuid.uuid4().hex[:8].upper()}"
            
            # Instanciamos la orden
            new_order = Order(
                reference_id=order_ref,
                prescription_id=prescription_id,
                pharmacist_id=pharmacist_id,
                delivery_type=delivery_info.get('type'),
                delivery_address=delivery_info.get('address'),
                status='pendiente_pago',
                total_amount=Decimal('0.0')
            )
            db.session.add(new_order)
            db.session.flush() # Genera el ID de la orden sin confirmar la transacción total

            for item in items_data:
                med = Medication.query.get(item['med_id'])
                if not med:
                    raise Exception(f"Medicamento ID {item['med_id']} no encontrado.")
                
                # Verificación preventiva de stock (sin descontar)
                if med.stock < item['qty']:
                    raise Exception(f"Stock insuficiente para {med.nombre}. Disponible: {med.stock}")

                subtotal = med.precio * Decimal(str(item['qty']))
                total_calculado += subtotal

                # Crear el detalle de la orden
                order_item = OrderItem(
                order_id=new_order.id,
                medication_id=med.id,
                quantity=item['qty'],             
                price=med.precio,                 
                dose_indicated=item.get('dosis', ''), 
                frequency=item.get('frec', ''),   
                duration=item.get('dur', '')      
            )
                db.session.add(order_item)

            new_order.total_amount = total_calculado
            
            # Actualizamos el estado de la receta
            prescription = Prescription.query.get(prescription_id)
            prescription.status = 'pendiente_pago'
            
            db.session.commit()
            return new_order

        except Exception as e:
            db.session.rollback() # Si algo falla, se borra todo lo anterior
            print(f"❌ Error en create_order: {str(e)}")
            raise e

    @staticmethod
    def finalize_payment(reference_id):
        """
        PASO 2: Confirmación de pago.
        Aquí es donde el stock finalmente sale del inventario.
        """
        try:
            order = Order.query.filter_by(reference_id=reference_id).first()
            
            if not order:
                print(f"⚠️ Orden {reference_id} no encontrada.")
                return False
            
            if order.status == 'pagado':
                print(f"⚠️ La orden {reference_id} ya fue procesada anteriormente.")
                return True

            # Verificación final de stock justo antes de descontar
            for item in order.items:
                med = Medication.query.get(item.medication_id)
                if med.stock < item.cantidad:
                    raise Exception(f"Stock insuficiente de último momento para {med.nombre}")
                
                # DESCUENTO REAL DE STOCK
                med.stock -= item.cantidad

            # Marcamos como pagado y actualizamos receta
            order.status = 'pagado'
            if order.prescription:
                order.prescription.status = 'en_proceso'
            
            db.session.commit()
            print(f"✅ Orden {reference_id} finalizada y stock actualizado.")
            return True

        except Exception as e:
            db.session.rollback() # Seguridad: si el descuento falla, no se marca como pagado
            print(f"❌ Error en finalize_payment: {str(e)}")
            return False