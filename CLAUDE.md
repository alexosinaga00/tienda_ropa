# FashionStore — Contexto del proyecto

Plataforma de e-commerce de ropa con vestidor virtual por realidad aumentada.
Proyecto académico, Sistemas II, UAGRM. Metodología PUDS, modelado UML 2.5.

## Stack
- Backend: Python 3.13 + FastAPI + SQLAlchemy 2.0 + Pydantic v2 + Alembic
- BD: PostgreSQL en Railway
- Web: Angular + PrimeNG (back office: admin, encargado, cajero; más una
  tienda pública para clientes: catálogo, registro/login, carrito y
  checkout — sin probador AR)
- Móvil: Flutter + Dart, Material 3 (cliente: catálogo, favoritos,
  carrito/checkout y el probador AR, exclusivo de esta app)
- Imágenes: Cloudinary
- IA: Groq (búsqueda por voz y recomendador)
- Chatbot: Botpress (widget en la web; el mismo bot en un WebView de la app móvil). Vive en la nube de
  Botpress: sus flujos no están en el repo y el backend no tiene endpoint de chat.
- Probador: google_mlkit_pose_detection (modo espejo) + Vertex AI (generativo)
- Pagos: Libélula y PayPal, ambos en sandbox
- Despliegue: Railway sin Docker, y Vercel para el Angular

## Arquitectura
Monolito modular en capas. 13 paquetes de negocio bajo `backend/app/`:
core, seguridad, organizacion, catalogo, abastecimiento, inventario,
reservas, ventas, pagos, entregas, probador, inteligencia, reportes.

Cada paquete tiene esta estructura:
  models.py       modelos SQLAlchemy (compartido por todo el paquete)
  schemas.py      schemas Pydantic (Crear, Actualizar, Respuesta)
  repository.py   acceso a datos (compartido)
  politicas.py    validaciones y reglas comunes del paquete (compartido)
  router.py       endpoints FastAPI
  casos_uso/      un archivo por caso de uso del catálogo (excepto en `core`,
                  que es infraestructura y no tiene casos_uso/)

## Convención de casos de uso
- Un archivo por caso de uso del catálogo, en `<paquete>/casos_uso/`.
- Nombre del archivo: cuXX_nombre_descriptivo.py, en minúsculas y con el
  número delante, para que el listado de la carpeta salga ordenado.
- El docstring del módulo empieza con "CU-XX — Nombre del caso de uso",
  seguido de actor, precondición y postcondición.
- Un caso de uso SIMPLE (una entidad, una operación, un actor) es una sola
  clase pública en PascalCase, con un único método público `ejecutar()`.
- Un caso de uso de tipo "Gestionar X" es un solo archivo que hereda de
  CRUDBase, no varios archivos separados por operación.
- Un caso de uso COMPUESTO (agrupa varias entidades o varias operaciones
  relacionadas del catálogo) puede romper la regla de "un único ejecutar()"
  de dos formas, y ninguna otra:
    a) Si agrupa varias entidades CRUD triviales del mismo dominio: el
       archivo contiene varias clases CRUDBase pequeñas, una por entidad.
       El archivo sigue siendo un solo CU.
    b) Si es una entidad principal con operaciones relacionadas: el archivo
       tiene una sola clase con varios métodos públicos en vez de un único
       ejecutar().
  Esta excepción no habilita a inventar más casos de uso ni a partir uno del
  catálogo en dos archivos: existe para fusionar en un solo archivo lo que
  el catálogo ya modela como un CU.
- Prohibido duplicar lógica entre casos de uso: si dos la necesitan, baja a
  repository.py (si es acceso a datos) o a politicas.py (si es validación o
  regla de negocio).
- Las relaciones <<include>> del modelo UML se implementan como llamadas de
  un caso de uso a otro, importando su clase. Nunca copiando el código.
- Un caso de uso puede llamar a casos de uso de otro paquete. Lo que sigue
  prohibido es consultar las tablas de otro paquete.
- Una operación que ningún CU-XX del catálogo nombra como caso de uso propio
  (ej. la actualización atómica de stock, la expiración automática de
  reservas, el cálculo de una tarifa de envío) NO se convierte en un CU
  nuevo: vive en politicas.py o repository.py del paquete correspondiente.
- El router instancia el caso de uso y llama a ejecutar() (o al método
  público que corresponda en un caso de uso compuesto). El router no
  contiene lógica de negocio.

## Trazabilidad con el modelo UML
El catálogo completo de los 43 casos de uso está en
`docs/consolidado_fashionstore.md`, sección 4 (y, mientras ese archivo no
exista, en `docs/presentacion2/generadores/cu_ciclo2.json` y
`docs/presentacion2/generadores/requisitos.json`).
Todo caso de uso implementado debe corresponder a uno de ese catálogo.
No inventar casos de uso nuevos ni cambiar la numeración.
Si al implementar surge la necesidad de una operación que no está en el
catálogo, no crear un CU nuevo: resolverla en politicas.py o en
repository.py, o preguntarlo explícitamente.

Algunas tablas del esquema (`docs/fashionstore_esquema.sql`) son soporte de
un caso de uso del catálogo pero no tienen su propio CU (ej. `orden_compra`,
que CU-12 referencia de forma opcional). Se implementan con su CRUD normal,
sin numerarlas ni contarlas para el total de 43.

## Reglas obligatorias
1. Sin dependencias circulares entre paquetes.
   Excepciones conocidas y deliberadas, ninguna otra: en ambas, el import
   diferido evita el ImportError circular y el acceso siempre pasa por
   `politicas`/`casos_uso` público del otro paquete, nunca por su tabla.
     - `core` ↔ `seguridad`: `core/security.py` necesita resolver permisos
       (tablas de `seguridad`) para JWT/autorización; importa
       `seguridad.politicas` de forma diferida (dentro de cada función)
       porque `seguridad.repository` importa `core.security` a nivel de
       módulo.
     - `catalogo` ↔ `inventario`: `catalogo.casos_uso.cu09` llama a
       `inventario.casos_uso.cu13` (ConsultarDisponibilidadSucursal) para
       resolver `cantidad_disponible`, y `catalogo.repository` llama a
       `inventario.politicas.listar_variantes_con_stock` (import diferido
       dentro del método, mismo motivo que en `core/security.py`) para el
       filtro `solo_disponibles` de CU-10; `inventario.politicas` ya
       llamaba a `catalogo.politicas` para validar que la variante exista.
2. Un paquete NUNCA consulta las tablas de otro paquete. Llama al caso de uso
   o a la política del otro paquete. Ejemplo: ventas llama a
   inventario.politicas.actualizar_stock_operacion(), no hace UPDATE sobre
   stock.
3. Todo caso de uso de tipo "Gestionar X" hereda de core/crud_base.py y
   ocupa un solo archivo (si agrupa varias entidades del mismo dominio, ver
   la excepción de la convención de casos de uso). No repetir código CRUD
   ni dividir un CRUD en varios casos de uso.
4. Todo cambio de esquema va en una migración de Alembic. Nunca a mano.
5. El router no toca la base de datos ni contiene lógica de negocio: solo
   instancia el caso de uso correspondiente y llama a ejecutar() (o al
   método público que corresponda en un caso de uso compuesto). Los casos
   de uso no saben de HTTP: no reciben Request ni devuelven Response,
   trabajan con schemas de Pydantic.
6. Toda operación que afecte stock va dentro de una transacción.
7. Nombres en español, tablas en singular, snake_case.
8. Borrado lógico con el campo `activo`. Nunca DELETE físico en tablas de negocio.
9. Los secretos van en variables de entorno. Nunca en el código.
10. El hash de contraseñas usa la librería `bcrypt` directamente.
    NO usar `passlib`: está sin mantenimiento y rompe con las versiones
    actuales de bcrypt.
11. La versión de Python es 3.13, fijada con `.python-version` en la raíz
    del backend para que el entorno local y Railway coincidan.

## Esquema de base de datos
El esquema completo y definitivo está en `docs/fashionstore_esquema.sql`
(61 tablas). No inventar tablas ni columnas nuevas sin pedirlo explícitamente.
Ese archivo es documentación de referencia: NO se ejecuta contra la base.
Las tablas las crea Alembic a partir de los modelos.

## Plan de desarrollo
`docs/plan_desarrollo_fashionstore.md`

## Tokens de diseño
Paleta terracota oscurecida (tienda de hombre: menos crema/pastel, base más
piedra/carbón, acento tipo cuero curtido en vez de coral). Fondo #EAE4DA
(contenido) / #FFFFFF (superficie/cards) · Texto #1C1713 / tenue #6E6156 ·
Acento #9A3E1F (hover #732E16, suave #E3D2C1) ·
Sidebar #241C18 (texto #C9BCB2, activo rgba(154,62,31,.28) / #F0DDCE) ·
Éxito #16A34A (suave #E8F6EE) · Advertencia #B45309 (suave #FDF0DD) ·
Error #DC2626 · Borde #DBD0C1 · Muted #C7BCAC.
Radio: 6px (inputs/filas/densos) · 10px (cards/stat tiles) · 18px (diálogos/hero).
Tipografía: Fraunces (serif, 500/600/700, itálica para marca y saludos) +
Public Sans (400-700, UI y datos). Números alineados en columna usan
tabular-nums. Espaciado en múltiplos de 4px.
El back office es denso (tablas compactas). El cliente móvil es amplio,
con la fotografía como protagonista.

## Alcance del probador virtual
Solo prendas superiores masculinas (poleras, camisas, chamarras).
Modo espejo obligatorio en Flutter. Modo generativo opcional.

## Entorno local
- PostgreSQL instalado localmente. Base de desarrollo: `fashionstore_dev`,
  creada manualmente antes de la primera migración.
- pgAdmin se usa solo para consulta. Las tablas NUNCA se crean ni se
  modifican desde pgAdmin.
- Conexión por variable de entorno DATABASE_URL en `.env`:
  postgresql+psycopg://postgres:PASSWORD@localhost:5432/fashionstore_dev
- Producción: PostgreSQL en Railway, DATABASE_URL provista por el servicio.

## Flujo de cambios de esquema
1. Modificar el modelo SQLAlchemy.
2. alembic revision --autogenerate -m "descripcion"
3. Revisar a mano el archivo generado. Atención con la columna generada
   `stock.cantidad_disponible`: autogenerate suele proponerla mal.
4. alembic upgrade head en local.
5. Commit y push. Railway aplica la migración al desplegar.