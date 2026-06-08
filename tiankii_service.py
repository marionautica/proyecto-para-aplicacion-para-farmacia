import os
import requests
from decimal import Decimal
from typing import Dict, Any, Tuple

class TiankiiService:
    # Endpoint oficial de producción
    BASE_URL = "https://api.md.tiankii.com"
        
    @classmethod
    def _get_headers(cls) -> Dict[str, str]:
        """Genera los encabezados de seguridad de forma dinámica."""
        token = os.environ.get("TIANKII_API_KEY") or os.environ.get("TIANKII_TOKEN_POS")
        if not token:
            print("❌ FATAL: TIANKII_TOKEN_POS no encontrado en las variables de entorno.")
            raise ValueError("Configuración de pasarela de pago ausente.")
        
        return {
            "x-api-key": str(token).strip(),  
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    @classmethod
    def _get_base_url_app(cls) -> str:
        """
        Autodescubrimiento del dominio del backend para el enrutamiento dinámico
        de los webhooks de notificación.
        """
        railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
        if railway_domain:
            return f"https://{railway_domain}"
        return os.environ.get("APP_LOCAL_URL") or "http://localhost:5000"

    @classmethod
    def create_checkout(cls, order_reference: str, amount: Decimal, moneda: str = "USD") -> Dict[str, Any]:
        """
        Crea una intención de cobro (Invoice) en Tiankii.
        
        Campos Obligatorios del Schema v1 cubiertos: amount, currency, storeId, appId.
        """
        url = f"{cls.BASE_URL}/v1/invoice"
        base_url_app = cls._get_base_url_app()

        # Validación de configuración obligatoria antes de intentar nada
        store_id = os.environ.get("TIANKII_STORE_ID")
        app_id = os.environ.get("TIANKII_APP_ID")
        token = os.environ.get("TIANKII_TOKEN_POS")
        
        if not all([store_id, app_id, token]):
            missing = [k for k, v in {"TIANKII_STORE_ID": store_id, "TIANKII_APP_ID": app_id, "TIANKII_TOKEN_POS": token}.items() if not v]
            print(f"❌ FATAL: Faltan variables de entorno: {', '.join(missing)}")
            return {"success": False, "error": f"Falta configuración obligatoria: {', '.join(missing)}"}

        # Validación y formateo estricto del monto a tipo de dato 'number'
        try:
            monto_seguro = round(float(amount), 2)
            if monto_seguro <= 0:
                return {"success": False, "error": "El monto debe ser un número positivo mayor a cero."}
        except (ValueError, TypeError):
            return {"success": False, "error": "Monto de transacción inválido."}

        # Payload bajo especificaciones oficiales v1
        payload = {
            "amount": monto_seguro,
            "currency": moneda,
            "storeId": store_id,
            "appId": app_id,
            "metadata": {
                "orderId": order_reference,
                "description": f"Pago de Orden #{order_reference} - Bitfarma"
            },
            "webhook": f"{base_url_app}/webhook/tiankii"
        }

        # Query Parameter opcional para forzar métodos de pago específicos (?paymentMethod=ID)
        payment_method_id = os.environ.get("TIANKII_PAYMENT_METHOD")
        query_params = {}
        if payment_method_id:
            query_params["paymentMethod"] = payment_method_id

        try:
            print(f"⚡ Tiankii POST -> Iniciando factura para Orden: {order_reference} | Monto: ${monto_seguro} {moneda}")
            
            response = requests.post(
                url, 
                json=payload, 
                headers=cls._get_headers(), 
                params=query_params,
                timeout=12
            )
            
            # Si el código no es 201 Created, levantará un HTTPError para ser capturado abajo
            response.raise_for_status()
            data = response.json()
            
            # Mapeo y desanidación limpia del Response Body para la UI y persistencia
            return {
                "success": True,
                "invoice_id": data.get("invoiceId"),
                "status": data.get("status"),
                "payment_url": data.get("invoiceUrl"),
                "qr_data": data.get("paymentDestination"),  # Dirección On-Chain o LN Invoice string
                "crypto_amount": data.get("cryptoAmount"),   # Monto equivalente calculado en BTC
                "expires_at": data.get("expirationDate")     # Timestamp ISO 8601 para el temporizador de la UI
            }

        except requests.exceptions.Timeout:
            print(f"❌ Error Tiankii (Timeout): La solicitud expiró al procesar orden {order_reference}.")
            return {"success": False, "error": "La pasarela de pago tardó demasiado en responder. Intente nuevamente."}
            
        except requests.exceptions.HTTPError as e:
            status_code = response.status_code if response else 500
            error_text = response.text if response else str(e)
            print(f"❌ Error Tiankii (HTTP {status_code}): {error_text}")
            return {"success": False, "error": f"La pasarela rechazó la solicitud (Código {status_code})."}
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Error de Red en Tiankii Service: {str(e)}")
            return {"success": False, "error": "Error de conexión crítico con el servidor de pagos."}
            
        except Exception as e:
            print(f"❌ Error imprevisto en TiankiiService.create_checkout: {str(e)}")
            return {"success": False, "error": "Error interno al procesar el checkout."}

    @classmethod
    def get_all_invoices(cls) -> Dict[str, Any]:
        """
        Recupera el historial completo de facturas asociadas a la cuenta autenticada (GET /v1/invoice).
        Útil para procesos internos de auditoría, dashboards y conciliación de transacciones.
        """
        url = f"{cls.BASE_URL}/v1/invoice"

        try:
            print("🔍 Tiankii GET -> Recuperando historial de facturas...")
            response = requests.get(url, headers=cls._get_headers(), timeout=15)
            response.raise_for_status()
            
            return {
                "success": True,
                "invoices": response.json()  # Retorna el listado [] completo de objetos
            }

        except requests.exceptions.HTTPError as e:
            status_code = response.status_code if response else 500
            if status_code == 401:
                print("❌ Error Tiankii GET (401): API Key no autorizada o expirada.")
                return {"success": False, "error": "Autenticación inválida con la pasarela de pagos."}
            
            print(f"❌ Error Tiankii GET (HTTP {status_code}): {response.text if response else str(e)}")
            return {"success": False, "error": f"Error del servidor de consultas (Código {status_code})."}
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Error de Conexión en Tiankii Service (Historial): {str(e)}")
            return {"success": False, "error": "No se pudo establecer comunicación para auditar el historial."}
            
        except Exception as e:
            print(f"❌ Error imprevisto en TiankiiService.get_all_invoices: {str(e)}")
            return {"success": False, "error": "Error de sistema al leer el historial."}