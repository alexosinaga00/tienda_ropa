import logging
import os
import secrets
from decimal import Decimal
from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Railway define estas variables en TODO servicio que despliega: sirven para saber que el proceso corre en un servidor y no
# en la máquina de alguien, aunque falte `ENVIRONMENT`.
_VARIABLES_DE_RAILWAY = ("RAILWAY_ENVIRONMENT_NAME", "RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID")
LARGO_MINIMO_CLAVE_JWT = 16  # por debajo de esto la clave no es una clave: el arranque se niega
LARGO_RECOMENDADO_CLAVE_JWT = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # "local" ENCIENDE atajos de desarrollo (p. ej. la recuperación de contraseña devuelve el token en la respuesta y la IP
    # del cliente se toma del socket): cualquier otro valor ("production") es un servidor. Por eso, si falta en un
    # servidor de Railway, el arranque se niega en vez de quedarse en "local" (ver `_validar_entorno`).
    environment: str = "local"
    # Nivel de los logs de la aplicación (`app.*`): DEBUG, INFO, WARNING, ERROR. INFO muestra la sincronización (RNF10).
    log_level: str = "INFO"

    database_url: str

    @field_validator("database_url")
    @classmethod
    def _forzar_driver_psycopg(cls, valor: str) -> str:
        # Railway inyecta DATABASE_URL como postgres:// o postgresql://
        # (formato psycopg2). El proyecto usa psycopg 3, así que hay que
        # forzar el dialecto +psycopg o SQLAlchemy intenta cargar psycopg2,
        # que ni siquiera está instalado.
        if valor.startswith("postgres://"):
            return valor.replace("postgres://", "postgresql+psycopg://", 1)
        if valor.startswith("postgresql://"):
            return valor.replace("postgresql://", "postgresql+psycopg://", 1)
        return valor

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # Bloqueo por cuenta del inicio de sesion (core/rate_limit.LimitadorIntentos):
    # tras `login_max_intentos` fallos dentro de `login_ventana_segundos` la
    # cuenta queda bloqueada hasta que el fallo mas viejo salga de la ventana.
    # No son secretos.
    # Costo de bcrypt al guardar una contraseña. 12 en producción (no lo cambies); las pruebas lo bajan
    # a 4 con BCRYPT_ROUNDS en tests/conftest.py para que la suite no pase la mayor parte del tiempo
    # calculando hashes. Un hash ya guardado se verifica con el costo con que se creó.
    bcrypt_rounds: int = Field(default=12, ge=4, le=16)

    login_max_intentos: int = 5
    login_ventana_segundos: int = 900

    # Vigencia de una suscripcion nueva cuando no se indica fecha de vencimiento.
    suscripcion_dias_por_defecto: int = 30
    # Dias completos de la prueba gratuita publica. El vencimiento es INCLUSIVO (una suscripcion
    # vence al dia siguiente de su fecha), asi que el vencimiento es hoy + (prueba_dias - 1).
    prueba_dias: int = 14

    # Sincronizacion offline (CU-25): una operacion con fecha mas alla de ahora + estos
    # minutos se rechaza como "fecha_futura" (reloj del dispositivo adelantado).
    sync_tolerancia_futuro_minutos: int = 5
    # Paquete de descarga (E08): horas tras las que el cliente avisa "información
    # desactualizada", y segundos que el servidor resta al `desde` del stock
    # incremental (cubre transacciones que confirman un poco después de su now()).
    sync_aviso_desactualizado_horas: int = 12
    sync_stock_solape_segundos: int = 120

    # Plazo (horas) para devolver o cambiar prendas cuando ni la empresa ni su plan
    # lo definen (p. ej. datos de prueba). D19.
    plazo_cambio_horas_respaldo: int = 24

    # Solicitud de cambio de talla o color del cliente (Etapa 2 del CU-17). El cliente solicita DENTRO del plazo; el
    # cajero la aprueba hasta `tolerancia` horas después de que el plazo terminó (el cliente puede llegar a la tienda
    # unas horas más tarde), y pasada esa tolerancia la solicitud pendiente vence sola. Por cuenta, como máximo
    # `max` solicitudes por ventana (anti abuso).
    solicitud_cambio_tolerancia_horas: int = 48
    solicitud_cambio_max_por_ventana: int = 5
    solicitud_cambio_ventana_segundos: int = 3600

    # Dias que se conserva la bitacora de auditoria; POST /tareas/purgar-bitacora
    # borra lo anterior.
    bitacora_retencion_dias: int = 365

    # Copias de seguridad por empresa (E22). El ZIP se arma en memoria (el disco de Railway es efímero y el
    # proceso es de un solo worker), por eso hay tres topes: tamaño comprimido, tiempo y copias a la vez.
    copias_max_bytes: int = 25 * 1024 * 1024
    copias_max_segundos: int = 60
    copias_max_simultaneas: int = 2

    # Orígenes del front Angular autorizados a llamar esta API desde el
    # navegador (CORS es una restricción que solo aplica a peticiones desde
    # un browser). La app Flutter (mobile/lib/core/network/dio_client.dart)
    # no pasa por acá: Dio no está sujeto a CORS, se conecta directo contra
    # ApiConfig.baseUrl sin que el backend tenga que autorizarla en esta lista.
    # En producción se sobreescribe por variable de entorno con la URL de
    # Vercel; en local coincide con environment.development.ts (web/).
    cors_origins: str = "http://localhost:4200"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""

    # Token fijo (no JWT) para tareas de sistema (cron/scheduler), p. ej.
    # POST /api/v1/tareas/expirar-reservas. Vacío por defecto: en ese caso
    # require_service_token() rechaza cualquier llamada, así que hay que
    # configurarlo explícitamente en el entorno para habilitar la tarea.
    tareas_token: str = ""

    # Modo generativo del probador (Vertex AI). Sin vertex_project_id
    # configurado, VertexAIProbadorGenerativo falla al primer uso: el probador
    # (único modo que queda) queda inhabilitado hasta configurar el proyecto
    # de GCP. Las credenciales van por GOOGLE_APPLICATION_CREDENTIALS (ruta a
    # archivo, entorno local) o por GOOGLE_CREDENTIALS_JSON (el contenido
    # del JSON de la cuenta de servicio, para Railway que no tiene archivos).
    vertex_project_id: str = ""
    vertex_location: str = "us-central1"
    vertex_modelo: str = "gemini-2.5-flash-image"
    google_credentials_json: str = ""
    # Generaciones por cliente por día (cada una tiene costo en Vertex AI).
    probador_limite_diario: int = 3

    # Una venta digital que sigue sin pagarse pasado este tiempo se anula
    # sola: libera el stock reservado y devuelve las prendas al carrito.
    venta_pendiente_minutos: int = 30
    # Tarea periódica dentro del propio backend (vence ventas pendientes y
    # reservas). Los tests la apagan.
    tareas_automaticas: bool = True
    tareas_intervalo_segundos: int = 300

    # Secretos para verificar la firma HMAC de los webhooks de pago (ver
    # app/comercial/pasarela.py). Sin valor por defecto (regla 9): un secreto
    # escrito acá es público para cualquiera con el repo y permitiría
    # firmar un webhook "aprobado". Sin configurar, el webhook de esa
    # pasarela se rechaza siempre (mismo criterio que tareas_token).
    libelula_webhook_secret: str = ""
    paypal_webhook_secret: str = ""
    # El QR online es simulado y su "webhook" lo firma y lo verifica este
    # mismo backend dentro del mismo request (confirmar_pago_qr): si no se
    # configura, alcanza con un secreto aleatorio por proceso.
    qr_online_webhook_secret: str = Field(default_factory=lambda: secrets.token_hex(32))

    # Base para construir URLs absolutas hacia esta misma API (p. ej. la
    # pantalla pública de pago con QR, ver app/comercial/pasarela.py) desde
    # código que no tiene acceso a un `Request` (arma la URL antes de que
    # exista ningún request entrante). En producción se sobreescribe por
    # variable de entorno con el dominio real de Railway, igual que
    # `cors_origins`.
    backend_public_url: str = "http://localhost:8000"

    # PayPal sí tiene credenciales reales de sandbox configuradas (Client
    # ID/Secret de una app de PayPal Developer en modo prueba): con esto,
    # PayPalGateway.iniciar_pago()/consultar_estado() llaman de verdad a
    # la API de PayPal en vez de simular. El webhook sigue siendo HMAC de
    # sandbox (ver pasarela.py): verificarlo de verdad necesita un
    # PAYPAL_WEBHOOK_ID configurado en el dashboard de PayPal contra una
    # URL pública, que este entorno local no tiene.
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_mode: str = "sandbox"

    # Compra de un plan con PayPal (CU-04, `GestionarContratacion`). Los planes se cobran en bolivianos pero PayPal
    # solo cobra en dólares: se convierte con este tipo de cambio de REFERENCIA (no se consulta a ninguna casa de
    # cambio) y se guarda en el pedido junto a los dos montos. El anual descuenta este porcentaje sobre 12 meses.
    tipo_cambio_bs_por_usd: Decimal = Decimal("6.96")
    descuento_anual_porcentaje: Decimal = Decimal("20")
    # URL base de la web (Angular): PayPal devuelve al comprador a `{frontend_public_url}/contratar/retorno?...`.
    # En producción se sobreescribe con el dominio de Vercel; en local coincide con `cors_origins`.
    frontend_public_url: str = "http://localhost:4200"
    # Minutos que un pedido sin pagar sigue abierto; pasado el plazo y sin aprobación en PayPal pasa a `vencido`.
    pedido_expira_minutos: int = 60

    # PayPal guardado (Vault v3) y pedido sin conexión (CU-13 y CU-18). El cliente autoriza UNA vez, con conexión; el
    # servidor guarda solo el token de PayPal y cobra después con él.
    # - `paypal_vault_usage_pattern`: cómo se declara el uso del token al crear el "setup token". El documentado en los
    #   ejemplos de PayPal es IMMEDIATE; UNSCHEDULED_POSTPAID (cobros del comercio sin calendario, después de recibir
    #   el producto) es el que describe este uso y es un valor válido del enumerado. No se probó contra el sandbox
    #   real: si PayPal lo rechaza, basta cambiar esta variable.
    # - `paypal_vault_stored_credential`: si el cobro con el token manda `stored_credential` (MERCHANT / UNSCHEDULED /
    #   SUBSEQUENT). El ejemplo oficial de cobro con `vault_id` no lo manda, por eso va apagado.
    # - límites por cuenta (en memoria, un solo worker): iniciar el guardado y enviar pedidos sin conexión.
    paypal_vault_usage_pattern: str = "UNSCHEDULED_POSTPAID"
    paypal_vault_stored_credential: bool = False
    paypal_guardado_max_por_ventana: int = 10
    paypal_guardado_ventana_segundos: int = 3600
    pedido_diferido_max_por_ventana: int = 30
    pedido_diferido_ventana_segundos: int = 3600
    # Topes de un pedido sin conexión (anti abuso): líneas, unidades por línea, unidades en total y costo de envío.
    pedido_diferido_max_lineas: int = 30
    pedido_diferido_max_unidades_por_linea: int = 20
    pedido_diferido_max_unidades: int = 100
    pedido_diferido_max_costo_envio: Decimal = Decimal("500")
    # Antigüedad máxima de un pedido sin conexión (según su `fecha_pedido`): más viejo es `pedido_vencido`. Una fecha en el
    # futuro más allá de la tolerancia (reloj del dispositivo mal puesto) es `pedido_invalido`.
    pedido_diferido_max_dias: int = 7
    pedido_diferido_tolerancia_futuro_horas: int = 24

    # Correo transaccional (core/correo.py, Brevo por HTTP). La clave va SOLO en el entorno (regla 9) y el remitente
    # debe estar verificado en Brevo; es uno solo para todas las empresas. Sin clave o sin remitente no se envía nada
    # (la recuperación de contraseña sigue respondiendo igual; en local entrega `token_dev`).
    brevo_api_key: str = ""
    correo_remitente_email: str = ""
    correo_remitente_nombre: str = "FashionStore"
    # Solicitudes de recuperación de contraseña por cuenta (empresa + correo) dentro de la ventana: pasado el máximo
    # no se emite token ni se envía correo (la respuesta al cliente no cambia). Evita llenar la bandeja de alguien.
    recuperar_max_solicitudes: int = 3
    recuperar_ventana_segundos: int = 3600

    # Notificaciones push (core/push.py, Firebase Cloud Messaging HTTP v1). La credencial es el JSON COMPLETO de la
    # cuenta de servicio de Firebase (de ahí sale también el project_id) y va SOLO en el entorno (regla 9). Sin ella
    # no se envía ningún push y todo lo demás funciona igual. Nunca se registra en logs ni en respuestas.
    firebase_credenciales_json: str = ""
    # Dispositivos activos por usuario (al pasar, se desactiva el más antiguo) y altas/bajas de dispositivos por cuenta
    # dentro de la ventana (en memoria, un solo worker).
    push_max_dispositivos_por_usuario: int = 5
    push_dispositivos_max_por_ventana: int = 30
    push_dispositivos_ventana_segundos: int = 3600

    # Búsqueda por voz (paquete `inteligencia`, P6.1): Groq expone una API
    # HTTP compatible con OpenAI, sin SDK propio en requirements.txt (se
    # llama con httpx, igual que catalogo/casos_uso/cu11_probar_prenda_con_ia.py
    # llama a otras APIs externas). Sin groq_api_key configurada, el parser
    # de voz falla y inteligencia.casos_uso.cu21_buscar_prendas_por_voz cae
    # directo al fallback de texto plano.
    # `llama-3.3-70b-versatile` (el que sugiere el enunciado) ya no está
    # disponible en cuentas nuevas de Groq -- comprobado contra
    # GET /openai/v1/models con la key real de este proyecto. gpt-oss-20b
    # sí está disponible, responde JSON limpio y es liviano (menor latencia
    # para una búsqueda por voz).
    groq_api_key: str = ""
    groq_modelo: str = "openai/gpt-oss-20b"

    # Reportes generativos (E09, CU-23): timeout y reintentos del intérprete de
    # Groq, tope de filas de un reporte y narrativa generada por IA (apagada: la
    # narrativa por plantilla es la que siempre se usa).
    groq_timeout_segundos: float = 10.0
    groq_reintentos: int = 1
    reportes_ia_max_filas: int = 500
    reportes_ia_narrativa_ia: bool = False

    # Peso promedio de una prenda (kg), para estimar el peso total de un
    # pedido en comercial.casos_uso.cu19_gestionar_envios_tarifas._peso_pedido()
    # sin modelar el peso real de cada variante (fuera del alcance de P5.3).
    peso_promedio_prenda_kg: Decimal = Decimal("0.3")

    # Topes de una reserva que hace el CLIENTE (CU-12): sin ellos, cualquiera con una cuenta podría apartar todo el stock con
    # una visita en el año 2099. No aplican a la reserva que el personal registra sin conexión (sincronización).
    reserva_max_dias_anticipacion: int = Field(default=60, ge=1)
    reserva_max_unidades_por_linea: int = Field(default=10, ge=1)
    reserva_max_unidades: int = Field(default=30, ge=1)
    reserva_max_activas_por_cliente: int = Field(default=5, ge=1)

    @model_validator(mode="after")
    def _validar_entorno(self) -> "Settings":
        """Falla cerrado ante una configuración peligrosa y avisa de las dudosas. Nunca imprime valores de secretos."""
        self.environment = (self.environment or "local").strip().lower()
        en_railway = any(os.environ.get(variable) for variable in _VARIABLES_DE_RAILWAY)
        if en_railway and self.environment == "local":
            raise ValueError(
                "ENVIRONMENT es 'local' en un servidor de Railway: en ese modo la recuperación de contraseña devuelve el "
                "token en la respuesta. Define ENVIRONMENT=production en las variables del servicio."
            )
        if len(self.jwt_secret_key) < LARGO_MINIMO_CLAVE_JWT:
            raise ValueError(
                f"JWT_SECRET_KEY es demasiado corta (mínimo {LARGO_MINIMO_CLAVE_JWT} caracteres): con ella se firman todos "
                "los tokens de sesión."
            )
        if self.environment != "local":
            if len(self.jwt_secret_key) < LARGO_RECOMENDADO_CLAVE_JWT:
                logger.warning(
                    "config_dudosa JWT_SECRET_KEY tiene menos de %s caracteres; se recomienda una clave aleatoria larga",
                    LARGO_RECOMENDADO_CLAVE_JWT,
                )
            for nombre, valor in (
                ("FRONTEND_PUBLIC_URL", self.frontend_public_url),
                ("BACKEND_PUBLIC_URL", self.backend_public_url),
                ("CORS_ORIGINS", self.cors_origins),
            ):
                if "localhost" in valor or "127.0.0.1" in valor:
                    logger.warning("config_dudosa %s apunta a localhost en un servidor", nombre)
            if not self.tareas_token:
                logger.warning("config_dudosa TAREAS_TOKEN está vacío: las rutas /tareas/* responderán siempre 401")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
