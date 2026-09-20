# Prompts para Claude Code — FashionStore

Un prompt = un módulo = medio día de trabajo. Nunca una etapa completa de golpe.
Cada bloque incluye qué revisar antes de dar el módulo por cerrado.

---

## PASO PREVIO — `CLAUDE.md` en la raíz del repositorio

Claude Code lee este archivo automáticamente en cada sesión. Sin él, cada
prompt tiene que repetir las decisiones y aun así improvisa. Creá el archivo
con este contenido:

```markdown
# FashionStore — Contexto del proyecto

Plataforma de e-commerce de ropa con vestidor virtual por realidad aumentada.
Proyecto académico, Sistemas II, UAGRM. Metodología PUDS, modelado UML 2.5.

## Stack
- Backend: Python 3.13 + FastAPI + SQLAlchemy 2.0 + Pydantic v2 + Alembic
- BD: PostgreSQL en Railway
- Web: Angular + PrimeNG (back office: admin, encargado, cajero)
- Móvil: Flutter + Dart, Material 3 (cliente)
- Imágenes: Cloudinary
- IA: Groq (voz, recomendador)
- Probador: google_mlkit_pose_detection (espejo) + Vertex AI (generativo)
- Pagos: Libélula y PayPal, ambos en sandbox
- Despliegue: Railway (sin Docker) + Vercel para el Angular

## Arquitectura
Monolito modular en capas. 13 paquetes de negocio bajo `backend/app/`:
core, seguridad, organizacion, catalogo, abastecimiento, inventario,
reservas, ventas, pagos, entregas, probador, inteligencia, reportes.

Cada paquete tiene exactamente estos archivos:
  models.py       modelos SQLAlchemy
  schemas.py      schemas Pydantic (Crear, Actualizar, Respuesta)
  repository.py   acceso a datos
  service.py      reglas de negocio
  router.py       endpoints FastAPI

## Reglas obligatorias
1. Sin dependencias circulares entre paquetes.
2. Un paquete NUNCA consulta las tablas de otro paquete. Llama al service
   del otro paquete. Ejemplo: ventas llama a
   inventario.service.registrar_movimiento(), no hace UPDATE sobre stock.
3. Todo CRUD hereda de core/crud_base.py. No repetir código CRUD.
4. Todo cambio de esquema va en una migración de Alembic. Nunca a mano.
5. El router no toca la base de datos. El service no sabe de HTTP.
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
El esquema completo y definitivo está en `docs/fashionstore_esquema.sql`.
No inventar tablas ni columnas nuevas sin pedirlo explícitamente.

## Plan de desarrollo
`docs/plan_desarrollo_fashionstore.md`

## Tokens de diseño
Fondo #FFFFFF / #F7F7F5 · Texto #1A1A1A / #6B6B6B · Acento #1F2937
Éxito #16A34A · Error #DC2626 · Borde #E5E5E5 · Radio 8px · Espaciado múltiplos de 4px

## Alcance del probador virtual
Solo prendas superiores masculinas (poleras, camisas, chamarras).
```

Subí también al repositorio, en `docs/`, el esquema SQL y el plan de desarrollo.

---

# ETAPA 1 — Cimientos

## P1.1 — Estructura y núcleo

```
Creá la estructura base del backend FastAPI según CLAUDE.md.

Incluí:
- backend/app/core/ con: config.py (Pydantic Settings leyendo variables de
  entorno), database.py (engine SQLAlchemy 2.0 + sesión por request),
  exceptions.py (excepciones de dominio y handlers), deps.py.
- backend/app/core/crud_base.py: clase genérica CRUDBase con métodos listar
  (con paginación y filtros), obtener, crear, actualizar y desactivar
  (borrado lógico). Tipada con genéricos para que cada paquete la reutilice.
- main.py con la app, CORS configurado por variable de entorno, y el
  registro de routers.
- requirements.txt con versiones fijadas.
- .python-version con el contenido 3.13
- Alembic inicializado y apuntando a la metadata de SQLAlchemy.
- .env.example con todas las variables necesarias.
- .gitignore

No crees todavía ningún paquete de negocio.
```

**Revisar**: que `crud_base` esté tipado con genéricos y no devuelva registros con `activo = False` en el listado. Que `.env` no esté commiteado.

---

## P1.2 — Paquete seguridad

```
Implementá el paquete `seguridad` según CLAUDE.md y el esquema de
docs/fashionstore_esquema.sql (tablas: rol, permiso, rol_permiso, usuario,
usuario_rol, cliente).

Incluí:
- Modelos SQLAlchemy de esas tablas.
- Hash de contraseñas en core/security.py usando la librería `bcrypt`
  directamente. NO uses `passlib` ni CryptContext: passlib está sin
  mantenimiento y es incompatible con las versiones actuales de bcrypt.
- JWT con access token y refresh token. El payload lleva usuario_id, roles
  y permisos.
- Dependencia get_current_user y un decorador/dependencia
  require_permission(codigo) para proteger endpoints.
- Endpoints:
  POST /api/v1/auth/registro     (crea usuario + cliente, rol cliente)
  POST /api/v1/auth/login
  POST /api/v1/auth/refresh
  GET  /api/v1/auth/yo
  POST /api/v1/auth/recuperar
  CRUD /api/v1/roles
  CRUD /api/v1/usuarios
  GET/PUT /api/v1/clientes/perfil
- Migración de Alembic.
- Seed de los 5 roles y sus permisos según el SQL.
- Tests: registro, login correcto, login con contraseña incorrecta,
  acceso a endpoint protegido sin token y con token de rol insuficiente.

No toques otros paquetes.
```

**Revisar**: que el hash sea bcrypt y no algo casero. Que el token no incluya la contraseña. Que `require_permission` verifique realmente contra la tabla y no contra una lista fija.

---

## P1.3 — Paquete organización

```
Implementá el paquete `organizacion` según CLAUDE.md y el esquema
(tablas: ciudad, sucursal, horario_sucursal, empleado).

Endpoints:
  CRUD /api/v1/ciudades
  CRUD /api/v1/sucursales
  CRUD /api/v1/sucursales/{id}/horarios
  CRUD /api/v1/empleados

Reglas:
- No permitir horarios superpuestos para el mismo día y sucursal.
- Un empleado pertenece a una sola sucursal.
- Todos los endpoints requieren permiso de administrador, excepto
  GET /api/v1/sucursales que es público (lo consume el catálogo).

Incluí migración y tests. Heredá de CRUDBase. No toques otros paquetes.
```

**Revisar**: que el GET público de sucursales no exponga datos de empleados.

---

## P1.4 — Base del Angular

```
Creá el proyecto Angular en web/ con PrimeNG.

Incluí:
- Configuración de tokens de diseño de CLAUDE.md en styles.scss como
  variables CSS.
- core/: servicio de autenticación, interceptor de JWT, interceptor de
  errores con notificación, guarda de ruta por rol.
- Cliente HTTP generado desde el OpenAPI del backend
  (usá openapi-generator o escribí los servicios a mano si es más simple).
- shared/tabla-generica: componente reutilizable que reciba columnas,
  endpoint y acciones, y resuelva filtrado, ordenamiento y paginación
  contra el backend. Todas las pantallas de administración lo van a usar.
- Layout con menú lateral que se arma según los permisos del usuario.
- Pantallas: login, dashboard vacío, y CRUD de usuarios, roles, ciudades
  y sucursales usando tabla-generica.

El diseño del back office es denso: tablas compactas, poco espaciado.
```

**Revisar**: que `tabla-generica` sea realmente genérica (que agregar el CRUD de colores después no requiera escribir una tabla nueva). Que el token se guarde y se limpie bien al cerrar sesión.

---

## P1.5 — Base del Flutter

```
Creá el proyecto Flutter en mobile/.

Paquetes: go_router, dio, flutter_riverpod, flutter_secure_storage,
cached_network_image.

Incluí:
- ThemeData con los tokens de diseño de CLAUDE.md (Material 3).
- Cliente Dio con interceptor que agrega el JWT y maneja el refresh
  automático al recibir 401.
- Almacenamiento del token con flutter_secure_storage.
- Rutas con go_router y redirección según sesión.
- Pantallas: splash, registro, login, home vacío.
- La URL de la API debe venir de --dart-define, no hardcodeada.

El diseño del cliente es al revés que el back office: fondo claro,
mucho espacio, la fotografía como protagonista.
```

**Revisar**: que el refresh automático no entre en bucle infinito si el refresh token también expiró.

---

## P1.6 — Despliegue

```
Preparo el despliegue en Railway sin Docker.

Necesito:
- Procfile o railway.json con el comando de arranque de uvicorn usando
  el puerto de la variable PORT.
- Verificar que Railway respete el .python-version con 3.13. Si el
  autodetector elige otra versión, fijarla por variable de entorno.
- Script de arranque que ejecute las migraciones de Alembic antes de
  levantar la app.
- Endpoint GET /health que verifique la conexión a la base de datos.
- Documentar en README.md las variables de entorno necesarias y el
  procedimiento de despliegue.
- Configuración de CORS para el dominio de Vercel.
```

**Revisar**: que las migraciones corran antes del arranque y no en cada worker. Probar `/health` desde el navegador antes de seguir.

---

# ETAPA 2 — Catálogo

## P2.1 — Catálogos simples

```
Implementá en el paquete `catalogo` los CRUD de las entidades simples
según el esquema: categoria (con jerarquía padre-hijo), talla, color,
material, temporada, coleccion.

Endpoints CRUD estándar bajo /api/v1/ para cada una, heredando de CRUDBase.
Los GET son públicos, el resto requiere permiso de administrador.

Validaciones:
- No permitir borrar una categoría con hijos o con productos asociados.
- El código de talla es único y tiene un campo orden para el listado.
- La temporada valida que fecha_fin sea posterior a fecha_inicio.

Migración, seed de tallas y materiales según el SQL, y tests.
```

**Revisar**: la jerarquía de categorías: que no permita que una categoría sea su propio padre ni cree ciclos.

---

## P2.2 — Producto y variantes

```
Implementá en `catalogo` las entidades producto, producto_variante,
producto_imagen y tabla_medida según el esquema.

Endpoints:
  CRUD /api/v1/productos
  GET/POST /api/v1/productos/{id}/variantes
  PUT/DELETE /api/v1/variantes/{id}
  CRUD /api/v1/productos/{id}/medidas

Regla central: al crear un producto se recibe una lista de tallas y una
lista de colores, y el sistema genera automáticamente la combinatoria de
variantes con SKU autogenerado con el formato
{codigo_producto}-{codigo_talla}-{codigo_color}.

Otras reglas:
- No permitir desactivar una variante con stock físico mayor a cero.
- El precio de la variante es opcional; si es nulo se usa precio_base
  del producto.
- El campo admite_probador se marca solo si la categoría es de torso superior.

Migración y tests de la generación de variantes.
```

**Revisar**: que el SKU sea realmente único y que la combinatoria no duplique variantes si se edita el producto agregando un color.

---

## P2.3 — Cloudinary

```
Implementá el servicio de almacenamiento en core/storage.py usando Cloudinary.

Requisitos:
- Subida firmada desde el backend. El api_secret nunca sale del servidor
  ni se expone en ningún endpoint.
- Estructura de carpetas: fashionstore/productos/{producto_id}/ y
  fashionstore/probador/{variante_id}/
- Guardar el public_id en la base de datos, no la URL completa.
- Función para generar URLs transformadas por tamaño y formato.
- Para imágenes de catálogo usar f_auto y q_auto.
- Para los PNG del probador NO usar f_auto: el formato debe forzarse a png
  para preservar el canal alfa.
- Borrado en Cloudinary al eliminar la imagen en la base de datos.

Endpoints:
  POST   /api/v1/productos/{id}/imagenes
  DELETE /api/v1/imagenes/{id}
  PUT    /api/v1/imagenes/{id}/principal
```

**Revisar**: esto es lo más importante de la etapa. Confirmá que el `api_secret` no aparece en ninguna respuesta de la API ni en el bundle del frontend. Y verificá con una imagen real que el PNG del probador conserva la transparencia.

---

## P2.4 — Catálogo público

```
Implementá los endpoints públicos de consulta del catálogo en `catalogo`.

  GET /api/v1/catalogo          listado paginado
  GET /api/v1/catalogo/buscar   con filtros
  GET /api/v1/catalogo/{id}     detalle con variantes e imágenes
  CRUD /api/v1/favoritos        requiere sesión de cliente

Filtros soportados en /buscar: texto libre, categoria_id, talla_id,
color_id, material_id, temporada_id, genero, precio_min, precio_max,
sucursal_id, solo_disponibles.

Requisitos:
- Paginación obligatoria, máximo 50 por página.
- Índices de base de datos que sostengan estos filtros (ya están en el SQL,
  verificá que se hayan aplicado).
- La respuesta del detalle incluye las variantes con su disponibilidad,
  pero la disponibilidad se pide al service de inventario, no consultando
  la tabla stock directamente. Si el paquete inventario todavía no existe,
  dejá la llamada preparada con un TODO.
```

**Revisar**: el tiempo de respuesta con los 30 productos cargados. Si supera el segundo, revisar el N+1 en las consultas de variantes.

---

## P2.5 — Editor de anclajes

```
Implementá el módulo de assets del probador.

Backend, paquete `probador`, tabla activo_probador del esquema:
  POST /api/v1/probador/assets              subida del PNG o flat-lay
  PUT  /api/v1/probador/assets/{id}/anclajes
  PUT  /api/v1/probador/assets/{id}/validar
  GET  /api/v1/probador/assets?variante_id=

Validaciones en la subida:
- El PNG debe tener canal alfa real (verificar con Pillow, no por extensión).
- Mínimo 512px de lado, máximo 3MB.
- El JSON de anclajes debe traer hombro_izq, hombro_der y cadera,
  con coordenadas normalizadas entre 0 y 1.

Frontend Angular, pantalla de editor de anclajes:
- Muestra el PNG a tamaño completo.
- El usuario hace clic en tres puntos en orden: hombro izquierdo,
  hombro derecho, cadera. Cada clic pone un marcador visible y arrastrable.
- Las coordenadas se guardan normalizadas respecto al tamaño de la imagen.
- Campo para factor_ancho (por defecto 1.18) con vista previa.
- Selector de plantilla por tipo de prenda que precarga anclajes típicos.
- Botón de validar que cambia el estado del asset.
```

**Revisar**: que las coordenadas se guarden normalizadas y no en píxeles. Probá redimensionando la imagen: los anclajes deben seguir siendo válidos.

---

## P2.6 — Catálogo en Flutter

```
Implementá en Flutter las pantallas del catálogo contra los endpoints
públicos ya creados.

Pantallas:
- Grilla de catálogo con scroll infinito y cached_network_image.
- Panel de filtros (categoría, talla, color, material, temporada, precio).
- Detalle de prenda: carrusel de imágenes, selector de talla y color que
  cambia la variante activa, precio, descripción, disponibilidad por sucursal.
- Favoritos.

Además, un servicio de tracking que registre eventos en
POST /api/v1/ia/eventos con tipo vista, busqueda o favorito.
Este registro alimenta al recomendador, así que tiene que funcionar desde ahora.
Si el endpoint todavía no existe, creá el modelo y dejá el envío encolado.

Diseño: fondo claro, la foto ocupa el protagonismo, interfaz mínima.
```

**Revisar**: que el tracking no bloquee la interfaz si falla la red (debe ser fire-and-forget).

---

# ETAPA 3 — Inventario

## P3.1 — Servicio de movimientos

```
Implementá el paquete `inventario` según el esquema (stock,
tipo_movimiento, movimiento_inventario, transferencia,
transferencia_detalle).

El corazón es service.registrar_movimiento(), que en UNA transacción:
1. Inserta la fila en movimiento_inventario con su saldo_post.
2. Actualiza stock.cantidad_fisica según el signo del tipo de movimiento.
3. Si el tipo tiene afecta_costo = true, recalcula el promedio ponderado:
   nuevo_promedio = (stock_anterior * costo_anterior +
                     cantidad_ingresada * costo_ingreso)
                    / (stock_anterior + cantidad_ingresada)
4. Guarda ese resultado en movimiento.costo_promedio_post y en
   stock.costo_promedio.
5. Bloquea la fila de stock con SELECT FOR UPDATE para evitar condiciones
   de carrera.

Además:
- reservar_stock(variante, sucursal, cantidad): incrementa
  cantidad_reservada. Nunca toca cantidad_fisica.
- liberar_stock(...): decrementa cantidad_reservada.
- Ninguna de las dos genera movimiento de inventario.
- cantidad_disponible es una columna generada: nunca escribirla.

Tests obligatorios:
- Tres recepciones con costos 10, 20 y 30 y verificación del promedio.
- Que reservar no altere cantidad_fisica.
- Que no se pueda reservar más de lo disponible.
- Que el saldo_post coincida con la suma acumulada de movimientos.
```

**Revisar línea por línea.** Esta es la regla de negocio que te van a pedir explicar en la defensa. Verificá manualmente los tres casos del test con calculadora.

---

## P3.2 — Endpoints de inventario y abastecimiento

```
Implementá los endpoints de `inventario` y el paquete `abastecimiento`.

Inventario:
  GET  /api/v1/inventario/consolidado      usa la vista vw_inventario_consolidado
  GET  /api/v1/inventario/sucursal/{id}
  GET  /api/v1/inventario/disponibilidad   público
  POST /api/v1/inventario/movimientos
  GET  /api/v1/inventario/movimientos      kardex por variante y sucursal
  PUT  /api/v1/inventario/stock/{id}/limites
  GET  /api/v1/inventario/alertas          disponible <= stock_minimo
  GET  /api/v1/inventario/valuacion
  CRUD /api/v1/transferencias
  POST /api/v1/inventario/ajustes

Abastecimiento (paquete nuevo): proveedor, producto_proveedor,
orden_compra, orden_compra_detalle, recepcion, recepcion_detalle.
  CRUD /api/v1/proveedores
  CRUD /api/v1/ordenes-compra
  POST /api/v1/recepciones

La recepción genera movimientos de tipo `recepcion` con costo unitario
llamando a inventario.service.registrar_movimiento(). Es la única entrada
de stock con costo.

La transferencia genera salida en origen e ingreso en destino, usando el
costo promedio del origen.
```

**Revisar**: que `abastecimiento` no escriba en la tabla `stock` directamente, sino que llame al service de inventario.

---

## P3.3 — Pantallas de inventario

```
Implementá en Angular las pantallas del módulo de inventario.

- Inventario consolidado: tabla con filtros por sucursal, producto,
  categoría y estado de stock. Columnas: producto, talla, color, sucursal,
  físico, reservado, disponible, mínimo, costo promedio, valor.
- Kardex: seleccionada una variante y sucursal, muestra el historial de
  movimientos con fecha, tipo, cantidad, saldo y costo promedio resultante.
  Esta pantalla es la evidencia visual del promedio ponderado.
- Formulario de recepción de mercadería: proveedor, sucursal, y líneas con
  variante, cantidad y costo unitario.
- Configuración de stock mínimo y máximo, en lote por sucursal.
- Panel de alertas de reposición.
- Reporte de valuación con el valor total del inventario por sucursal.
- Transferencias y ajustes.
```

**Revisar**: que el kardex muestre el costo promedio después de cada movimiento. Es lo que vas a mostrar en la defensa.

---

# ETAPA 4 — Reservas y probador

## P4.1 — Backend de reservas

```
Implementá el paquete `reservas` según el esquema (estado_reserva, reserva,
reserva_detalle, reserva_historial).

Reglas:
- Crear reserva: valida disponibilidad de cada variante en la sucursal
  elegida, valida que la franja horaria caiga dentro del horario de esa
  sucursal para ese día, llama a inventario.service.reservar_stock() por
  cada línea, fija fecha_expiracion (por defecto 24 horas después de la
  franja) y genera notificaciones para los empleados de la sucursal.
  Todo en una transacción.
- Transiciones válidas: pendiente → preparada → en_prueba → completada.
  Desde pendiente o preparada también → cancelada. Cualquier otra
  transición debe rechazarse con error de dominio.
- Cada cambio de estado se registra en reserva_historial.
- Registrar selección: el encargado marca cuáles prendas eligió el cliente.
  Las marcadas con seleccionada = false liberan su stock reservado.
  Las marcadas true quedan reservadas hasta que se registre la venta.
- Expirar reservas: libera el stock de todas las reservas vencidas que
  sigan en estado pendiente o preparada.

Endpoints:
  POST   /api/v1/reservas
  GET    /api/v1/reservas/mis-reservas
  GET    /api/v1/reservas/{id}
  DELETE /api/v1/reservas/{id}
  GET    /api/v1/reservas/sucursal/{id}
  PUT    /api/v1/reservas/{id}/preparar
  PUT    /api/v1/reservas/{id}/confirmar-llegada
  PUT    /api/v1/reservas/{id}/seleccion
  POST   /api/v1/tareas/expirar-reservas    protegido por token de servicio
  GET    /api/v1/notificaciones

Tests: crear reserva descuenta disponible, cancelar lo devuelve, selección
parcial libera solo lo no seleccionado, transición inválida falla.
```

**Revisar**: el caso de selección parcial. Es el hueco que el enunciado no cubría y el que más fácil sale mal.

---

## P4.2 — Reservas en Flutter y Angular

```
Implementá las interfaces de reservas.

Flutter (cliente):
- Desde el detalle de prenda, botón "agregar a reserva" que arma una
  lista temporal de variantes.
- Pantalla de confirmación: selección de sucursal (solo las que tienen
  stock de todas las prendas), fecha y franja horaria dentro del horario
  de esa sucursal.
- Mis reservas: listado con estado, detalle y botón de cancelar.
- Notificación visual cuando la reserva pasa a preparada.

Angular (encargado):
- Bandeja de reservas de la sucursal con filtro por fecha y estado.
- Detalle con checklist para marcar cada prenda como preparada.
- Botón de confirmar llegada del cliente.
- Pantalla de registro de selección tras la prueba: por cada prenda,
  seleccionar comprada o no comprada, y confirmar.
```

**Revisar**: que la selección de sucursal en el móvil solo ofrezca sucursales con stock real de todas las prendas.

---

## P4.3 — Backend del probador

```
Completá el paquete `probador` con los endpoints de uso.

  GET  /api/v1/probador/variante/{id}/assets
       devuelve el overlay validado con sus anclajes y el flat-lay si existe
  POST /api/v1/probador/generar
       recibe la foto del cliente y la variante. Calcula sha256 de la foto,
       busca en probador_generacion por (hash_foto, variante_id). Si existe
       y está completado, devuelve la URL cacheada sin llamar a la API.
       Si no, crea el registro en estado en_proceso, lanza la llamada a
       Vertex AI en segundo plano y devuelve el id.
  GET  /api/v1/probador/generar/{id}
       consulta de estado para polling
  POST /api/v1/probador/sesion
       registra uso del probador (métrica y alimento del recomendador)
  POST /api/v1/probador/talla
       recibe estatura, peso y preferencia de ajuste, estima medidas y las
       cruza con tabla_medida para recomendar talla

Límites: máximo 3 generaciones por cliente por día, una sola imagen por
petición, timeout de 60 segundos.

La integración con Vertex va detrás de una interfaz ProbadorGenerativoBase,
para poder cambiar de proveedor sin tocar el resto.

La foto original del cliente no se persiste: se procesa y se descarta.
Solo se guarda el hash y la URL del resultado.
```

**Revisar**: que el caché funcione (probá dos veces con la misma foto y prenda, la segunda debe ser instantánea). Que la foto original no quede guardada en ningún lado.

---

## P4.4 — Probador en Flutter, detección de pose

```
Implementá SOLO la detección de pose en Flutter. No el overlay todavía.

- Pantalla con CameraController usando la cámara frontal en resolución media.
- PoseDetector de google_mlkit_pose_detection en modo stream.
- Conversión correcta del CameraImage a InputImage, respetando la rotación
  del sensor según la plataforma y la orientación del dispositivo.
- Pintar círculos de depuración sobre los landmarks de hombros y caderas.
- Mostrar en pantalla el valor de likelihood de cada hombro.
- Manejo de permisos de cámara.

Objetivo de este paso: confirmar que los landmarks caen donde corresponde
y son estables. Nada más.
```

**Revisar**: parate frente a la cámara y verificá que los círculos caen en tus hombros reales. Si están espejados o rotados, se arregla acá y no después.

---

## P4.5 — Probador en Flutter, overlay

```
Sobre la pantalla de detección de pose ya funcionando, implementá el
overlay de la prenda.

- Descarga del PNG y su JSON de anclajes desde
  GET /api/v1/probador/variante/{id}/assets, con caché local.
- CustomPainter que en cada frame:
  1. Si el likelihood de cualquiera de los hombros es menor a 0.6, no
     dibuja nada y muestra "acércate a la cámara".
  2. Calcula ancho = distancia euclidiana entre hombros detectados.
  3. Calcula ángulo = atan2(dy, dx) entre los hombros.
  4. Calcula centro = punto medio entre hombros.
  5. escala = (ancho / anchoAssetEnPixeles) * factor_ancho
  6. Aplica al canvas: translate(centro) → rotate(angulo) → scale(escala)
     → translate negativo del punto medio de los anclajes del asset.
  7. Dibuja la imagen.
- Suavizado exponencial de las coordenadas entre frames (factor 0.3) para
  evitar temblor.
- Corrección del espejado de la cámara frontal en el eje X.
- Selector horizontal para cambiar de prenda sin salir de la pantalla.
- Botón de captura que guarda la imagen compuesta en la galería.

Al abrir el probador, registrar la sesión con POST /api/v1/probador/sesion.
```

**Revisar**: el paso 6. La traslación negativa del punto medio de los anclajes es la que casi siempre se omite y hace que la prenda aparezca corrida. Probá con tres prendas distintas.

---

## P4.6 — Modo generativo en Flutter

```
Implementá el modo foto realista del probador en Flutter.

- Pestaña o botón que alterna entre modo espejo y modo realista.
- En modo realista: checkbox de consentimiento explícito antes de habilitar
  la captura, con texto que explique que la foto se envía a un servicio
  externo para generar la imagen y no se almacena.
- Captura desde cámara o selección desde galería.
- Envío a POST /api/v1/probador/generar, indicador de progreso, polling
  cada 2 segundos a GET /api/v1/probador/generar/{id}.
- Resultado a pantalla completa con opciones de guardar y compartir.
- Si el servicio falla o se agota el límite diario, mensaje claro y
  sugerencia de usar el modo espejo. La app nunca debe quedar bloqueada
  por la falla del servicio externo.
```

**Revisar**: desconectá internet a propósito y confirmá que la app degrada con elegancia en vez de colgarse.

---

# ETAPA 5 — Ventas, pagos, entregas

## P5.1 — Backend de ventas

```
Implementá el paquete `ventas` según el esquema (estado_venta, promocion,
promocion_alcance, venta, venta_detalle, carrito, carrito_detalle,
devolucion, devolucion_detalle).

Regla central: registrar_venta() en UNA transacción:
1. Valida disponibilidad de cada línea.
2. Crea venta y venta_detalle, congelando costo_unitario desde
   stock.costo_promedio actual de esa variante y sucursal.
3. Llama a inventario.service.registrar_movimiento() tipo `venta` por cada línea.
4. Si la venta proviene de una reserva, libera el stock reservado y marca
   la reserva como completada.
5. Aplica promociones vigentes según promocion_alcance.
6. Calcula subtotal, descuento, costo de envío y total.

Endpoints:
  CRUD /api/v1/carrito
  POST /api/v1/ventas/digital
  POST /api/v1/ventas/presencial
  GET  /api/v1/ventas/{id}/comprobante
  GET  /api/v1/ventas/mis-compras
  GET  /api/v1/ventas/sucursal/{id}
  POST /api/v1/devoluciones
  CRUD /api/v1/promociones
  POST /api/v1/carrito/aplicar-promocion

La devolución reingresa stock con movimiento tipo `devolucion` y marca el
estado. Una venta digital y una presencial usan la misma tabla, cambia
el campo canal.

Tests: venta descuenta stock, venta desde reserva libera lo reservado,
costo congelado no cambia si después cambia el promedio, no se puede
vender más de lo disponible.
```

**Revisar**: el congelamiento del costo. Hacé una venta, después una recepción a otro costo, y verificá que el margen histórico de la primera venta no cambió.

---

## P5.2 — Pagos y pasarelas

```
Implementá el paquete `pagos` según el esquema (metodo_pago, estado_pago,
pago, transaccion_pasarela).

Arquitectura: clase abstracta PasarelaBase con los métodos iniciar_pago(),
consultar_estado() y procesar_webhook(). Implementaciones concretas
LibelulaGateway y PayPalGateway, ambas en modo sandbox. El resto del
sistema no sabe cuál se está usando.

Endpoints:
  POST /api/v1/pagos/iniciar          devuelve la URL de redirección
  POST /api/v1/pagos/caja             efectivo, QR, tarjeta, transferencia
  POST /api/v1/pagos/webhook/{pasarela}
  GET  /api/v1/pagos/{id}/estado
  POST /api/v1/pagos/{id}/anular

Requisitos:
- Registrar en transaccion_pasarela el payload enviado y el recibido.
  Es la evidencia para las pruebas de integración del documento.
- El webhook verifica la firma de la pasarela antes de procesar.
- El webhook es idempotente: recibirlo dos veces no debe generar dos ventas
  ni descontar stock dos veces.
- El pago en caja con efectivo calcula el cambio.
- Solo cuando el pago pasa a aprobado se confirma la venta y se descuenta
  el stock.

Tests: webhook duplicado no duplica la venta, pago rechazado no descuenta
stock, cálculo de cambio.
```

**Revisar**: la idempotencia del webhook. Mandá el mismo webhook dos veces con curl y verificá que el stock se descontó una sola vez.

---

## P5.3 — Entregas

```
Implementá el paquete `entregas` según el esquema (zona_envio,
regla_tarifa_envio, direccion_cliente, envio).

Regla de cálculo:
  costo = zona.tarifa_base + recargo de la regla cuyo rango de peso
          contenga el peso total del pedido
El peso del pedido se estima con un peso promedio por prenda configurable.

Endpoints:
  CRUD /api/v1/zonas-envio
  CRUD /api/v1/clientes/direcciones
  POST /api/v1/envios/cotizar        no persiste, solo calcula
  POST /api/v1/envios
  PUT  /api/v1/envios/{id}/estado

Seed: zonas por anillo para Santa Cruz (1er al 4to anillo con tarifa fija,
recargo por anillo adicional), según lo indicado por la docente.

Test: cálculo de tarifa por anillo con y sin recargo por peso.
```

**Revisar**: que la cotización no persista nada. Es un cálculo, no una entidad.

---

## P5.4 — Punto de caja en Angular

```
Implementá el punto de venta en Angular.

- Búsqueda rápida de producto por código de barras (con foco automático
  en el campo, pensado para lector físico) o por nombre.
- Carrito de caja con edición de cantidades y descuentos por línea.
- Atajo para cargar una reserva atendida y convertirla en venta.
- Selección de método de pago: efectivo (con cálculo de cambio), QR,
  tarjeta o transferencia.
- Confirmación de la venta y generación del comprobante imprimible.
- Historial de ventas de la sucursal del día.
- Registro de devoluciones.
- Pantallas de administración de promociones y de zonas de envío.

La pantalla de caja debe funcionar con teclado, sin mouse: es lo que
espera un cajero real y se nota en la defensa.
```

**Revisar**: el flujo completo con teclado. Es un detalle que impresiona y cuesta poco.

---

## P5.5 — Checkout en Flutter

```
Implementá la compra desde la app.

- Carrito persistente sincronizado con el backend.
- Checkout en pasos: revisión del carrito, elección entre retiro en
  sucursal o envío a domicilio, selección o alta de dirección, cotización
  de envío en vivo, selección de método de pago, confirmación.
- Redirección a la pasarela mediante navegador externo o WebView, con
  retorno a la app por deep link.
- Pantalla de estado del pago con polling.
- Historial de compras con detalle y comprobante.

Si el pago queda pendiente, la app debe mostrar el estado y permitir
reintentar, nunca dejar al usuario sin saber qué pasó.
```

**Revisar**: el retorno desde la pasarela. Es el punto que más falla en móvil.

---

# ETAPA 6 — IA y reportes

## P6.1 — Búsqueda por voz

```
Implementá la búsqueda por voz en el paquete `inteligencia`.

Backend, POST /api/v1/ia/voz:
- Recibe el texto ya transcrito por el dispositivo.
- Arma un prompt para Groq (modelo llama-3.3-70b o similar) que devuelva
  ÚNICAMENTE un JSON con esta forma, sin texto adicional ni markdown:
  {"categoria": null, "temporada": null, "material": null, "color": null,
   "talla": null, "genero": null, "precio_max": null, "sucursal": null}
- El prompt debe incluir las listas de valores válidos existentes en la
  base de datos para categoría, material, color, talla y temporada, para
  que el modelo mapee sinónimos a valores reales ("hilo" → material Hilo).
- Valida la respuesta con un schema Pydantic. Si no valida o Groq falla,
  cae a búsqueda por texto plano sobre el catálogo.
- Ejecuta la búsqueda reutilizando el servicio de /api/v1/catalogo/buscar.
- Registra la consulta en consulta_voz con el texto, los filtros y la
  cantidad de resultados.

Flutter:
- Botón de micrófono en el catálogo usando speech_to_text con locale es-BO
  o es-ES.
- Retroalimentación visual de escucha y transcripción parcial en pantalla.
- Al terminar, envía el texto al endpoint y aplica los filtros devueltos,
  mostrándolos como chips que el usuario puede quitar.
- Manejo de permiso de micrófono y del caso en que el dispositivo no tenga
  reconocimiento de voz disponible.

Test: la frase "quiero una camisa de algodón azul de primavera" debe
producir los filtros correctos.
```

**Revisar**: probá con cinco frases distintas, incluyendo una imposible ("quiero un auto rojo"). El sistema debe responder sin resultados, no romperse.

---

## P6.2 — Recomendador

```
Implementá el recomendador en `inteligencia`.

Tres capas, documentadas como híbrido:
1. Reglas: variantes con stock disponible, de la temporada vigente,
   excluyendo lo ya comprado por el cliente.
2. Historial: pondera candidatos según historial_navegacion del cliente
   (vistas, favoritos, usos del probador, compras previas), pesando más
   los eventos recientes.
3. Groq: recibe los 20 mejores candidatos con sus atributos y el perfil
   del cliente, y devuelve los 6 finales ordenados con un motivo en
   lenguaje natural por cada uno.

Persistir el resultado en la tabla recomendacion con puntaje y motivo.

Endpoints:
  POST /api/v1/ia/recomendaciones
  POST /api/v1/ia/eventos            registro del historial de navegación

Si el cliente es nuevo y no tiene historial, recomendar por popularidad
de la temporada vigente. Nunca devolver lista vacía.

Flutter: carrusel de recomendaciones en el home y en el detalle de prenda,
mostrando el motivo debajo de cada tarjeta.
```

**Revisar**: el caso del cliente nuevo. Un carrusel vacío en la defensa es peor que uno genérico.

---

## P6.3 — Reportes y dashboard

```
Implementá el paquete `reportes`.

Endpoints, apoyados en las vistas vw_inventario_consolidado y
vw_ventas_detalle del esquema:
  GET  /api/v1/reportes/ventas       por período, sucursal, categoría, canal
  GET  /api/v1/reportes/inventario
  GET  /api/v1/reportes/dashboard
  GET  /api/v1/reportes/reservas
  POST /api/v1/ia/reporte-voz        consulta en lenguaje natural

Indicadores del dashboard: ventas del período, cantidad de transacciones,
ticket promedio, margen bruto, productos más vendidos, ventas por canal,
ventas por sucursal, valor total del inventario, variantes bajo mínimo,
reservas por estado, tasa de conversión de reservas a ventas, y uso del
probador virtual.

El reporte por voz traduce la consulta a filtros con Groq y llama al
endpoint de reportes correspondiente. Solo lectura, nunca genera SQL
directamente a partir del texto del usuario.

Angular: dashboard con tarjetas de indicadores y gráficos de PrimeNG,
y pantallas de reportes con exportación.

`reportes` solo lee. Ningún otro paquete depende de él.
```

**Revisar**: que el reporte por voz no construya SQL desde el texto. Es una vulnerabilidad de inyección y además te la van a preguntar.

---

## P6.4 — Botpress

```
Integrá el chatbot de Botpress solo en la web Angular.

- Widget embebido en el layout, visible para clientes y administradores.
- Configurar en Botpress las llamadas HTTP a los endpoints públicos:
  GET /api/v1/catalogo/buscar y GET /api/v1/inventario/disponibilidad,
  para que pueda responder sobre productos y stock reales.
- Crear un token de servicio de solo lectura para esas llamadas. Nunca
  usar credenciales de administrador.
- Flujos mínimos: consultar disponibilidad de una prenda, explicar cómo
  funciona la reserva, explicar cómo funciona el probador virtual,
  derivar a un humano.

No integrar Botpress en Flutter.   <- REVISADO el 20/09/2026: ver la nota de abajo.
```

> **Actualización (20/09/2026): el asistente también está en la app móvil.**
>
> Lo que se decidió y por qué: se probó que el bot de la web carga y responde dentro de un WebView de
> Android (sin restricción de dominio en Botpress) y contesta con datos reales del catálogo, así que
> llevarlo a la app costaba poco y no requiere backend, migración ni llaves nuevas.
>
> Cómo quedó: es el **mismo bot** (mismo `botId`/`clientId`), cargado en un WebView desde
> `mobile/lib/features/asistente/`. El acceso es un ícono de burbuja en la barra del catálogo, visible
> también para el invitado. Los flujos siguen viviendo en el panel de Botpress, no en este repositorio.
>
> Límites conocidos: el micrófono del chat no funciona en la app; los enlaces dentro de las respuestas
> se bloquean; la conversación empieza de cero cada vez que se abre; el bot no sabe quién es el cliente
> (no responde por sus pedidos); la interfaz del chat sigue el idioma del teléfono.
>
> Mantenimiento: las dos URLs de Botpress están duplicadas en `web/src/index.html` y en
> `mobile/lib/features/asistente/models/pagina_asistente.dart`. Si el bot se vuelve a publicar y cambia
> el archivo de configuración, hay que actualizarlas en los dos lugares.

**Revisar**: preguntale por una prenda que no existe. Si inventa una respuesta, ajustá el flujo para que consulte siempre la API antes de responder. (Verificado en la app el 20/09/2026 con una prenda inexistente: respondió que no la encontró, sin inventar.)

---

# ETAPA 7 — Cierre

## P7.1 — Datos de demostración

```
Creá un script de seed de datos de demostración en backend/scripts/.

Debe generar:
- 2 ciudades, 3 sucursales con horarios.
- 1 administrador, 3 encargados, 3 cajeros, 10 clientes con nombres reales.
- 3 proveedores.
- Los 30 productos del dataset con sus variantes, imágenes y materiales.
- Assets de probador para 10 variantes.
- Recepciones de mercadería con costos variados en las últimas 8 semanas,
  para que el promedio ponderado tenga historia real.
- 40 ventas distribuidas en las últimas 6 semanas, mezclando canal digital
  y presencial, con sus pagos.
- 8 reservas en distintos estados: pendiente, preparada, completada,
  cancelada y expirada.
- Historial de navegación para 5 clientes, para que el recomendador tenga
  datos.
- Zonas de envío por anillo para Santa Cruz.

El script debe ser idempotente: correrlo dos veces no duplica datos.
```

**Revisar**: que el dashboard se vea poblado después de correrlo. Es la diferencia entre una demo convincente y una vacía.

---

## P7.2 — Revisión final

```
Hacé una revisión de seguridad y consistencia de todo el backend.

Verificá y corregí:
- Que ningún endpoint quede sin protección salvo los explícitamente
  públicos (catálogo, disponibilidad, login, registro, webhooks).
- Que no haya secretos, claves ni contraseñas en el repositorio.
- Que ningún paquete consulte tablas de otro paquete directamente.
- Que todas las operaciones sobre stock estén dentro de transacciones.
- Que los errores devuelvan códigos HTTP correctos y no expongan trazas.
- Que exista índice para cada filtro usado en los listados.
- Que todas las migraciones de Alembic apliquen limpio desde cero sobre
  una base vacía.

Generá un informe con lo encontrado y lo corregido.
```

**Revisar**: correr las migraciones desde cero en una base limpia. Si fallan, lo descubrís ahora y no el 20 de septiembre.

---

# Cómo revisar lo que produce

**Aceptá con lectura rápida**: CRUD estándar, schemas, routers, pantallas de listado, formularios.

**Leé línea por línea**, sin excepción:
1. `inventario.service.registrar_movimiento()` — el promedio ponderado.
2. `ventas.service.registrar_venta()` — la transacción atómica.
3. `reservas.service.registrar_seleccion()` — la liberación parcial.
4. El `CustomPainter` del probador — la transformación de anclajes.
5. El webhook de pagos — la idempotencia.
6. El endpoint de reporte por voz — que no construya SQL.

Son las seis piezas que te van a preguntar en la defensa y las que tenés
que poder explicar como propias.

**Después de cada módulo**, antes de pasar al siguiente:
- Endpoints probados manualmente en `/docs`.
- Migración aplicada en Railway.
- Tests pasando.
- Commit con mensaje descriptivo.

Si tres de esas cuatro cosas no están, no abras el módulo siguiente.
