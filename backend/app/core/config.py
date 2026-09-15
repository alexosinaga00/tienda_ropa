from decimal import Decimal
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "local"

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
    # configurado, VertexAIProbadorGenerativo falla al primer uso: el modo
    # espejo (Flutter, sin backend) sigue funcionando igual, es el
    # generativo el que queda inhabilitado hasta configurar el proyecto de
    # GCP. Las credenciales van por GOOGLE_APPLICATION_CREDENTIALS (ruta a
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
    # app/pagos/pasarela.py). Ambas pasarelas corren en modo sandbox sin
    # credenciales reales todavía, así que estos valores por defecto son
    # solo para desarrollo/pruebas -- en producción se sobreescriben por
    # variable de entorno como cualquier otro secreto (regla 9).
    libelula_webhook_secret: str = "sandbox-secret-libelula"
    paypal_webhook_secret: str = "sandbox-secret-paypal"

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

    # Búsqueda por voz (paquete `inteligencia`, P6.1): Groq expone una API
    # HTTP compatible con OpenAI, sin SDK propio en requirements.txt (se
    # llama con httpx, igual que probador/service.py llama a otras APIs
    # externas). Sin groq_api_key configurada, el parser de voz falla y
    # inteligencia.service cae directo al fallback de texto plano.
    # `llama-3.3-70b-versatile` (el que sugiere el enunciado) ya no está
    # disponible en cuentas nuevas de Groq -- comprobado contra
    # GET /openai/v1/models con la key real de este proyecto. gpt-oss-20b
    # sí está disponible, responde JSON limpio y es liviano (menor latencia
    # para una búsqueda por voz).
    groq_api_key: str = ""
    groq_modelo: str = "openai/gpt-oss-20b"

    # Peso promedio de una prenda (kg), para estimar el peso total de un
    # pedido en entregas.service._peso_pedido() sin modelar el peso real de
    # cada variante (fuera del alcance de P5.3).
    peso_promedio_prenda_kg: Decimal = Decimal("0.3")


@lru_cache
def get_settings() -> Settings:
    return Settings()
