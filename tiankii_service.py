import os
import requests
from decimal import Decimal

class TiankiiService:
    # Endpoint oficial de producción/test
    BASE_URL = "https://dev1.api.md.tiankii.com"
        
    @classmethod
    def _get_headers(cls):
        """Genera los encabezados de seguridad de forma dinámica."""
        token = os.environ.get("TIANKII_TOKEN_POS")
        if not token:
            print("❌ FATAL: TIANKII_TOKEN_POS no encontrado en las variables de entorno.")
            raise ValueError("Configuración de pasarela de pago ausente.")
        
        return {
            "x-api-key": token,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    @classmethod
    def create_checkout(cls, order_reference: str, amount: Decimal):
        """
        Crea la intención de cobro.
        Utiliza autodescubrimiento para el dominio del Webhook.
        """
        
        #url = f"{cls.BASE_URL}/api/v1/invoices"
        url = f"{cls.BASE_URL}/api/v1/invoices"
        
        # entorno (Railway y Local)
        railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
        if railway_domain:
            base_url = f"https://{railway_domain}"
        else:
            base_url = "http://localhost:5000"

        monto_seguro = round(float(amount), 2)

        store_id = os.environ.get("TIANKII_STORE_ID")
        if not store_id:
            # no se si hiria aqui o en railway
            store_id = "89A276326C4254EBD8"

        # Payload profesional
        payload = {
            "store_id": store_id,
            "amount": monto_seguro, 
            "currency": "USD",
            "orderId": order_reference,
            "callbackUrl": f"{base_url}/webhook/tiankii",
            "successUrl": f"{base_url}/paciente",
            "cancelUrl": f"{base_url}/paciente"
        }

        try:
            print(f"⚡ Iniciando cobro en Tiankii -> Orden: {order_reference} | Monto: ${amount}")
            
            # timeout=10 previene que tu servidor colapse si la API externa está lenta
            response = requests.post(url, json=payload, headers=cls._get_headers(), timeout=10)
            response.raise_for_status()
            
            data = response.json()
            return {
                "success": True,
                "checkout_id": data.get("id"),
                "payment_url": data.get("paymentUrl") # URL de la factura interactiva
            }

        except requests.exceptions.Timeout:
            print(f"❌ Error Tiankii: Timeout al procesar la orden {order_reference}.")
            return {"success": False, "error": "La red de pagos tardó demasiado. Intente de nuevo."}
            
        except requests.exceptions.RequestException as e:
            # Captura errores HTTP (400, 401, 500)
            status = response.status_code if 'response' in locals() and response is not None else "N/A"
            error_body = response.text if 'response' in locals() and response is not None else str(e)
            print(f"❌ Error Tiankii (HTTP {status}): {error_body}")
            return {"success": False, "error": "Fallo en la comunicación con la pasarela de pagos."}
            
        except Exception as e:
            print(f"❌ Error interno crítico en TiankiiService: {str(e)}")
            return {"success": False, "error": "Error interno del sistema."}