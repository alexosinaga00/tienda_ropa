# Construye en Enterprise Architect los artefactos del Ciclo 2 de FashionStore.
# Trabaja SIEMPRE sobre una copia fresca de parcialsi2.eapx (el original no se toca):
#   architect\parcialsi2.eapx  ->  architect\parcialsi2_ciclo2.eapx
# Lee los casos de uso de cu_ciclo2.json y exporta cada diagrama a diagramas\*.png.
param(
    [string]$Original = "G:\sistemas de informacion 2 angelica garzon\architect\parcialsi2.eapx",
    [string]$Destino  = "G:\sistemas de informacion 2 angelica garzon\architect\parcialsi2_ciclo2.eapx"
)
$ErrorActionPreference = "Stop"
$aqui = Split-Path -Parent $MyInvocation.MyCommand.Path
$salida = Join-Path $aqui "diagramas"
New-Item -ItemType Directory -Force $salida | Out-Null
Copy-Item $Original $Destino -Force

$cus = Get-Content (Join-Path $aqui "cu_ciclo2.json") -Raw -Encoding UTF8 | ConvertFrom-Json

$rep = New-Object -ComObject EA.Repository
if (-not $rep.OpenFile($Destino)) { throw "No se pudo abrir $Destino" }
$proj = $rep.GetProjectInterface()

$PKG_REQ = 3; $PKG_ANA = 4; $PKG_ANACU = 6; $PKG_ARQ = 7; $PKG_DISCU = 8; $PKG_NEG = 10

# ---------------------------------------------------------------- utilidades
function Paquete([int]$id) { $rep.GetPackageByID($id) }

function Elemento-PorNombre([string]$nombre, [string]$tipo) {
    $sql = "SELECT Object_ID FROM t_object WHERE Name='" + $nombre.Replace("'", "''") + "' AND Object_Type='$tipo'"
    $xml = [xml]$rep.SQLQuery($sql)
    $fila = $xml.EADATA.Dataset_0.Data.Row | Select-Object -First 1
    if ($null -eq $fila) { return $null }
    return $rep.GetElementByID([int]$fila.Object_ID)
}

function Diagrama-PorNombre([string]$nombre) {
    $xml = [xml]$rep.SQLQuery("SELECT Diagram_ID FROM t_diagram WHERE Name='" + $nombre.Replace("'", "''") + "'")
    $fila = $xml.EADATA.Dataset_0.Data.Row | Select-Object -First 1
    if ($null -eq $fila) { return $null }
    return $rep.GetDiagramByID([int]$fila.Diagram_ID)
}

function Nuevo-Elemento($pkg, [string]$nombre, [string]$tipo, [string]$estereotipo = "") {
    $e = $pkg.Elements.AddNew($nombre, $tipo)
    if ($estereotipo) { $e.Stereotype = $estereotipo }
    $null = $e.Update()
    $null = $pkg.Elements.Refresh()
    return $e
}

function Nuevo-Diagrama($pkg, [string]$nombre, [string]$tipo) {
    $d = $pkg.Diagrams.AddNew($nombre, $tipo)
    $null = $d.Update()
    $null = $pkg.Diagrams.Refresh()
    return $d
}

function Poner($diag, $elem, [int]$l, [int]$t, [int]$r, [int]$b) {
    $o = $diag.DiagramObjects.AddNew("l=$l;r=$r;t=$t;b=$b;", "")
    $o.ElementID = $elem.ElementID
    $null = $o.Update()
    return $o
}

function Conectar($origen, $destino, [string]$tipo, [string]$estereotipo = "", [string]$nombre = "") {
    $c = $origen.Connectors.AddNew($nombre, $tipo)
    $c.SupplierID = $destino.ElementID
    if ($estereotipo) { $c.Stereotype = $estereotipo }
    $null = $c.Update()
    $null = $origen.Connectors.Refresh()
    return $c
}

function Existe-Conexion($a, $b) {
    $sql = "SELECT Connector_ID FROM t_connector WHERE (Start_Object_ID=$($a.ElementID) AND End_Object_ID=$($b.ElementID)) OR (Start_Object_ID=$($b.ElementID) AND End_Object_ID=$($a.ElementID))"
    $xml = [xml]$rep.SQLQuery($sql)
    return $null -ne ($xml.EADATA.Dataset_0.Data.Row | Select-Object -First 1)
}

function Agregar-Atributo($elem, [string]$nombre, [string]$tipo) {
    $a = $elem.Attributes.AddNew($nombre, $tipo)
    $a.Visibility = "Private"
    $null = $a.Update()
}

function Agregar-Operacion($elem, [string]$firma, [string]$retorno) {
    $nombre = $firma; $params = @()
    if ($firma -match '^([^(]+)\((.*)\)$') {
        $nombre = $Matches[1]
        if ($Matches[2].Trim()) { $params = $Matches[2].Split(',') | ForEach-Object { $_.Trim() } }
    }
    $op = $elem.Methods.AddNew($nombre, $retorno)
    $op.Visibility = "Public"
    $null = $op.Update()
    foreach ($p in $params) {
        # Con OpParams=1 EA muestra el tipo del parámetro: se usa el texto como tipo.
        $par = $op.Parameters.AddNew($p, $p)
        $null = $par.Update()
    }
}

function Al-Fondo($diag) {
    # Marcos (Package/Boundary) detrás del resto: en t_diagramobjects mayor Sequence = más atrás,
    # y los objetos agregados por la API quedan en 999999, así que el marco va por encima de eso.
    $rep.Execute("UPDATE t_diagramobjects SET Sequence=2000000 WHERE Diagram_ID=$($diag.DiagramID) AND Object_ID IN (SELECT Object_ID FROM t_object WHERE Object_Type IN ('Package','Boundary'))")
}

function Exportar($diag, [string]$archivo) {
    $ruta = Join-Path $salida $archivo
    $ok = $proj.PutDiagramImageToFile($diag.DiagramGUID, $ruta, 1)
    Write-Output ("  export {0} -> {1}" -f $diag.Name, $ok)
}

function Mensaje-Secuencia($diag, $desde, $hasta, [string]$texto, [int]$orden, [bool]$retorno) {
    $c = $desde.Connectors.AddNew($texto, "Sequence")
    $c.SupplierID = $hasta.ElementID
    $c.SequenceNo = $orden
    $c.DiagramID = $diag.DiagramID
    $null = $c.Update()
    $r = if ($retorno) { "1" } else { "0" }
    $rep.Execute("UPDATE t_connector SET PDATA1='Synchronous', PDATA2='retval=;params=;paramsDlg=;', PDATA3='Call', PDATA4='$r', SeqNo=$orden, DiagramID=$($diag.DiagramID) WHERE Connector_ID=$($c.ConnectorID)")
}

$pkgReq = Paquete $PKG_REQ; $pkgAnaCU = Paquete $PKG_ANACU; $pkgDisCU = Paquete $PKG_DISCU; $pkgAna = Paquete $PKG_ANA

# ------------------------------------------- 1. correcciones a elementos del Ciclo 1
Write-Output "== Correcciones Ciclo 1"
$renombres = @(
    @("Excluir Variante Sin Disponibilidad", "UseCase", "Rechazar Reserva por Stock Insuficiente"),
    @("Rechazar Superposicion de Temporada", "UseCase", "Rechazar Temporada Duplicada (Nombre y Anio)"),
    @("Crear Stock Inicial en Cero por Sucursal", "UseCase", "Generar Variantes Talla x Color"),
    @("Rechazar Combinacion Talla-Color Duplicada", "UseCase", "Omitir Combinacion Talla-Color Existente"),
    @("Registrar Pago Rechazado", "UseCase", "Anular Venta por Pago Rechazado"),
    @("Venta queda -pago_rechazado-, carrito se conserva", "Action", "Venta queda -anulada- y se libera el stock reservado")
)
foreach ($r in $renombres) {
    $e = Elemento-PorNombre $r[0] $r[1]
    if ($null -ne $e) { $e.Name = $r[2]; $null = $e.Update(); Write-Output "  renombrado: $($r[0]) -> $($r[2])" }
    else { Write-Output "  (no encontrado) $($r[0])" }
}

$actores = @{}
foreach ($n in "Cliente", "Administrador", "Encargado de sucursal", "Cajero") { $actores[$n] = Elemento-PorNombre $n "Actor" }

# ------------------------------------------- 2. los 16 casos de uso del Ciclo 2
$ucs = @{}
foreach ($cu in $cus) {
    $num = $cu.id.Substring(3)
    $titulo = "$($cu.id) $($cu.nombreEA)"
    Write-Output "== $titulo"
    $actor = $actores[$cu.actorEA]

    # 2.a Diagrama de caso de uso particular
    $uc = Nuevo-Elemento $pkgReq $titulo "UseCase"
    $ucs[$cu.id] = $uc
    $frontera = Nuevo-Elemento $pkgReq "$($cu.id): $($cu.nombreEA)  (FashionStore :: Paquete $($cu.paquete))" "Boundary"
    $dP = Nuevo-Diagrama $pkgReq "$($cu.id) Diagrama de Caso de Uso Particular" "Use Case"
    $null = Poner $dP $frontera 250 20 1000 350
    $null = Poner $dP $actor 40 150 110 240
    $null = Poner $dP $uc 300 70 580 130
    $null = Conectar $actor $uc "Association"
    $y = 220
    foreach ($inc in $cu.include) {
        $e = Nuevo-Elemento $pkgReq $inc "UseCase"
        $null = Poner $dP $e 320 $y 600 ($y + 60)
        $null = Conectar $uc $e "Association" "Include"
        $y += 90
    }
    $y = 70
    foreach ($ext in $cu.extend) {
        $e = Nuevo-Elemento $pkgReq $ext "UseCase"
        $null = Poner $dP $e 650 $y 900 ($y + 70)
        $null = Conectar $e $uc "Association" "Extend"
        $y += 100
    }
    Al-Fondo $dP
    Exportar $dP "UCP-$num.png"

    # 2.b Robustez (boundary / control / entity) compartida por COM y SEC
    $rob = @{}
    $rob["A"] = $actor
    $rob["IU"] = Nuevo-Elemento $pkgAnaCU $cu.iu.nombre "Class" "boundary"
    $rob["C"] = Nuevo-Elemento $pkgAnaCU $cu.ctrl.nombre "Class" "control"
    if ($cu.ctrl2) { $rob["C2"] = Nuevo-Elemento $pkgAnaCU $cu.ctrl2.nombre "Class" "control" }
    for ($i = 0; $i -lt $cu.ents.Count; $i++) { $rob["E$i"] = Nuevo-Elemento $pkgAnaCU $cu.ents[$i].nombre "Class" "entity" }

    # 2.c Diagrama de comunicación
    $dC = Nuevo-Diagrama $pkgAnaCU "COM-$num $titulo" "Communication"
    $null = Poner $dC $rob["A"] 20 140 80 230
    $null = Poner $dC $rob["IU"] 220 150 390 220
    $null = Poner $dC $rob["C"] 520 150 660 210
    if ($rob.ContainsKey("C2")) { $null = Poner $dC $rob["C2"] 520 320 660 380 }
    for ($i = 0; $i -lt $cu.ents.Count; $i++) {
        $t = 60 + $i * 150
        $null = Poner $dC $rob["E$i"] 860 $t 970 ($t + 55)
    }
    foreach ($m in $cu.com) {
        if ($m[0] -eq $m[1]) { continue }  # auto-mensaje: se documenta en la secuencia
        $null = Conectar $rob[$m[0]] $rob[$m[1]] "Association" "" $m[2]
    }
    Exportar $dC "COM-$num.png"

    # 2.d Diagrama de clases de análisis («IU», «Controller», «Entidad»)
    $dA = Nuevo-Diagrama $pkgAnaCU "CLA-$num $titulo (clases de analisis)" "Logical"
    $iu = Nuevo-Elemento $pkgAnaCU $cu.iu.nombre "Class" "IU"
    foreach ($a in $cu.iu.attrs) { Agregar-Atributo $iu $a[0] $a[1] }
    foreach ($o in $cu.iu.ops) { Agregar-Operacion $iu $o[0] $o[1] }
    $alto = 90 + 16 * ($cu.iu.attrs.Count + $cu.iu.ops.Count)
    $null = Poner $dA $iu 40 40 280 (40 + $alto)

    $ct = Nuevo-Elemento $pkgAnaCU $cu.ctrl.nombre "Class" "Controller"
    foreach ($o in $cu.ctrl.ops) { Agregar-Operacion $ct $o[0] $o[1] }
    $alto = 70 + 16 * $cu.ctrl.ops.Count
    $null = Poner $dA $ct 380 40 700 (40 + $alto)
    $null = Conectar $iu $ct "Association"

    if ($cu.ctrl2) {
        $ct2 = Nuevo-Elemento $pkgAnaCU $cu.ctrl2.nombre "Class" "Controller"
        foreach ($o in $cu.ctrl2.ops) { Agregar-Operacion $ct2 $o[0] $o[1] }
        $alto2 = 70 + 16 * $cu.ctrl2.ops.Count
        $null = Poner $dA $ct2 380 260 700 (260 + $alto2)
        $null = Conectar $ct $ct2 "Association"
    }
    $t = 40
    foreach ($en in $cu.ents) {
        $ee = Nuevo-Elemento $pkgAnaCU $en.nombre "Class" "Entidad"
        foreach ($a in $en.attrs) { Agregar-Atributo $ee $a[0] $a[1] }
        foreach ($o in $en.ops) { Agregar-Operacion $ee $o[0] $o[1] }
        $alto = 70 + 15 * ($en.attrs.Count + $en.ops.Count)
        $null = Poner $dA $ee 800 $t 1040 ($t + $alto)
        $null = Conectar $ct $ee "Association"
        $t += $alto + 30
    }
    Exportar $dA "CLA-$num.png"

    # 2.e Diagrama de secuencia
    $dS = Nuevo-Diagrama $pkgDisCU "SEC-$num $titulo" "Sequence"
    $orden = @("A", "IU", "C") + $(if ($rob.ContainsKey("C2")) { @("C2") } else { @() }) + (0..($cu.ents.Count - 1) | ForEach-Object { "E$_" })
    $fondo = 150 + 42 * $cu.seq.Count
    $x = 20
    foreach ($k in $orden) {
        $ancho = if ($k -eq "A") { 60 } else { 160 }
        $null = Poner $dS $rob[$k] $x 20 ($x + $ancho) $fondo
        $x += if ($k -eq "A") { 200 } else { 240 }
    }
    $n = 1
    foreach ($m in $cu.seq) {
        Mensaje-Secuencia $dS $rob[$m[0]] $rob[$m[1]] $m[2] $n ([bool][int]$m[3])
        $n++
    }
    Exportar $dS "SEC-$num.png"
}

# ------------------------------------------- 3. diagrama general de casos de uso (Ciclos 1 y 2)
Write-Output "== UC-02 general"
$uc1 = @{}
foreach ($nombre in "CU-01 Registrar cliente","CU-02 Iniciar sesion","CU-05 Gestionar sucursales","CU-07 Gestionar catalogo maestro","CU-08 Gestionar productos (variantes e imagenes)","CU-09 Consultar catalogo","CU-13 Consultar disponibilidad por sucursal","CU-16 Reservar varias prendas","CU-20 Atender prueba de reserva en sucursal","CU-21 Cargar assets y marcar anclajes","CU-22 Probar prenda en modo espejo","CU-24 Realizar compra digital","CU-25 Registrar venta presencial","CU-29 Pagar mediante pasarela digital") {
    $uc1[$nombre.Substring(0, 5)] = Elemento-PorNombre $nombre "UseCase"
}
foreach ($k in $ucs.Keys) { $uc1[$k] = $ucs[$k] }

# asociaciones de actores secundarios
foreach ($par in @(@("Encargado de sucursal","CU-14"), @("Cajero","CU-28"))) {
    if (-not (Existe-Conexion $actores[$par[0]] $uc1[$par[1]])) { $null = Conectar $actores[$par[0]] $uc1[$par[1]] "Association" }
}

$dG = Nuevo-Diagrama $pkgReq "UC-02 Diagrama de Casos de Uso (Ciclos 1 y 2)" "Use Case"
$sistema = Elemento-PorNombre "FashionStore" "Boundary"
$null = Poner $dG $sistema 200 20 1200 1460
# columna Cliente (izquierda)
$colCliente = "CU-01","CU-09","CU-10","CU-13","CU-16","CU-17","CU-18","CU-22","CU-23","CU-24","CU-29","CU-26"
# columna central (compartidos)
$colCentro  = "CU-02","CU-30","CU-25","CU-28"
# columna Administrador / Encargado (derecha)
$colDerecha = "CU-03","CU-04","CU-05","CU-06","CU-07","CU-08","CU-21","CU-11","CU-27","CU-14","CU-12","CU-15","CU-19","CU-20"
# columna Cliente en zigzag para que las líneas pasen entre elipses
$y = 50; $i = 0
foreach ($k in $colCliente) { $x = if ($i % 2 -eq 0) { 240 } else { 400 }; $null = Poner $dG $uc1[$k] $x $y ($x + 200) ($y + 60); $y += 115; $i++ }
$null = Poner $dG $uc1["CU-02"] 640 90 870 150
$y = 900; foreach ($k in "CU-25","CU-30","CU-28") { $null = Poner $dG $uc1[$k] 760 $y 990 ($y + 60); $y += 180 }
$y = 50;  foreach ($k in $colDerecha) { $null = Poner $dG $uc1[$k] 1030 $y 1260 ($y + 60); $y += 100 }
$null = Poner $dG $actores["Cliente"] 60 660 110 750
$null = Poner $dG $actores["Cajero"] 560 1500 610 1590
$null = Poner $dG $actores["Administrador"] 1390 330 1440 420
$null = Poner $dG $actores["Encargado de sucursal"] 1390 1060 1440 1150
foreach ($o in $dG.DiagramObjects) {
    if ($o.ElementID -eq $sistema.ElementID) { $o.right = 1300; $null = $o.Update() }
}
Al-Fondo $dG
Exportar $dG "UC-02.png"

# ------------------------------------------- 4. vistas de paquete (VP) y paquetes
Write-Output "== Vistas de paquete"
function Ampliar-VP([string]$nombreDiag, [string[]]$nuevos, [string[]]$actoresExtra) {
    $d = Diagrama-PorNombre $nombreDiag
    $maxB = 0; $marco = $null; $maxActor = 0
    foreach ($o in $d.DiagramObjects) {
        $e = $rep.GetElementByID($o.ElementID)
        if ($e.Type -eq "Package") { $marco = $o }
        elseif ($e.Type -eq "Actor") { $maxActor = [Math]::Max($maxActor, -$o.bottom) }
        else { $maxB = [Math]::Max($maxB, -$o.bottom) }
    }
    $y = $maxB + 40
    foreach ($k in $nuevos) { $null = Poner $d $ucs[$k] 480 $y 760 ($y + 65); $y += 100 }
    $ya = $maxActor + 30
    foreach ($a in $actoresExtra) { $null = Poner $d $actores[$a] 60 $ya 120 ($ya + 90); $ya += 120 }
    $fondo = [Math]::Max($y, $ya) + 20
    if ($null -ne $marco) { $marco.bottom = -$fondo; $null = $marco.Update() }
    $null = $d.Update()
    Al-Fondo $d
    return $d
}
$vp = @(
    @("VP-01 Vista de paquete - Seguridad y Control de Acceso", @("CU-03"), @(), "VP-01"),
    @("VP-02 Vista de paquete - Organizacion y Sucursales", @("CU-04","CU-06"), @(), "VP-02"),
    @("VP-03 Vista de paquete - Catalogo de Productos", @("CU-10"), @(), "VP-03"),
    @("VP-04 Vista de paquete - Inventario y Disponibilidad", @("CU-14","CU-15"), @("Administrador","Encargado de sucursal"), "VP-04"),
    @("VP-05 Vista de paquete - Reservas de Prendas", @("CU-17","CU-18","CU-19"), @(), "VP-05"),
    @("VP-07 Vista de paquete - Ventas (Digital y Presencial)", @("CU-23","CU-26","CU-27","CU-28"), @("Administrador","Encargado de sucursal"), "VP-07"),
    @("VP-08 Vista de paquete - Pagos y Pasarelas", @("CU-30"), @("Cajero"), "VP-08")
)
foreach ($v in $vp) { $d = Ampliar-VP $v[0] $v[1] $v[2]; Exportar $d "$($v[3]).png" }

# paquete de negocio abastecimiento (análisis) y su vista VP-09
$pkgAbast = $pkgAna.Packages.AddNew("abastecimiento", "")
$null = $pkgAbast.Update(); $null = $pkgAna.Packages.Refresh()
$elAbast = $pkgAbast.Element
$marcoAbast = $pkgAna.Packages.AddNew("Abastecimiento y Proveedores", "")
$null = $marcoAbast.Update(); $null = $pkgAna.Packages.Refresh()
$d9 = Nuevo-Diagrama $pkgAna "VP-09 Vista de paquete - Abastecimiento y Proveedores" "Use Case"
$null = Poner $d9 $marcoAbast.Element 20 20 800 300
$null = Poner $d9 $actores["Administrador"] 60 110 120 200
$null = Poner $d9 $ucs["CU-11"] 480 60 760 125
$null = Poner $d9 $ucs["CU-12"] 480 180 760 245
Al-Fondo $d9
Exportar $d9 "VP-09.png"

# dependencias reales de abastecimiento (imports del código): catalogo, inventario, organizacion
$elPkg = @{}
foreach ($n in "core","seguridad","organizacion","catalogo","inventario","reservas","ventas","pagos","probador") { $elPkg[$n] = Elemento-PorNombre $n "Package" }
foreach ($dep in "catalogo","inventario","organizacion") { $null = Conectar $elAbast $elPkg[$dep] "Dependency" }

$d0 = Diagrama-PorNombre "PKG-00 Identificar paquetes"
$null = Poner $d0 $elAbast 40 1280 220 1340
$nota = Nuevo-Elemento $pkgAna "abastecimiento: proveedores, productos del proveedor, ordenes de compra y recepciones de mercaderia (entrada de stock con costo). Se incorpora en el Ciclo 2 (CU-11, CU-12)." "Note"
$nota.Notes = $nota.Name; $null = $nota.Update()
$null = Poner $d0 $nota 320 1280 840 1370
Exportar $d0 "PKG-00.png"

$d1 = Diagrama-PorNombre "PKG-01 Vista de paquetes"
$null = Poner $d1 $elAbast 40 220 200 280
Exportar $d1 "PKG-01.png"

$d3 = Nuevo-Diagrama $pkgAna "PKG-03 Relacionar paquetes y casos de uso (Ciclo 2)" "Package"
$grupos = [ordered]@{
    "seguridad" = @("CU-03"); "organizacion" = @("CU-04","CU-06"); "catalogo" = @("CU-10");
    "abastecimiento" = @("CU-11","CU-12"); "inventario" = @("CU-14","CU-15"); "reservas" = @("CU-17","CU-18","CU-19");
    "ventas" = @("CU-23","CU-26","CU-27","CU-28"); "pagos" = @("CU-30")
}
$y = 30
foreach ($g in $grupos.Keys) {
    $elP = if ($g -eq "abastecimiento") { $elAbast } else { $elPkg[$g] }
    $alto = [Math]::Max(70, 85 * $grupos[$g].Count)
    $yp = $y + [int](($alto - 60) / 2)
    $null = Poner $d3 $elP 40 $yp 240 ($yp + 60)
    $yc = $y
    foreach ($k in $grupos[$g]) {
        $null = Poner $d3 $ucs[$k] 460 $yc 760 ($yc + 60)
        $null = Conectar $elP $ucs[$k] "Dependency"
        $yc += 85
    }
    $y += $alto + 25
}
Exportar $d3 "PKG-03.png"

# ------------------------------------------- 5. despliegue: servicios de IA externos
Write-Output "== DESP-01"
$dd = Diagrama-PorNombre "DESP-01 Diagrama de despliegue (zonas)"
$pkgArq = Paquete $PKG_ARQ
$groq = Nuevo-Elemento $pkgArq "Groq (IA de lenguaje: voz y reportes)" "Node"
$vertex = Nuevo-Elemento $pkgArq "Google Vertex AI (probador generativo)" "Node"
$null = Poner $dd $groq 990 230 1230 300
$null = Poner $dd $vertex 990 320 1230 390
foreach ($o in $dd.DiagramObjects) {
    $e = $rep.GetElementByID($o.ElementID)
    if ($e.Name -eq "Servicios externos (terceros)") { $o.bottom = -420; $null = $o.Update() }
}
$api = Elemento-PorNombre "Railway - Servidor de aplicacion (FastAPI)" "Node"
$null = Conectar $api $groq "Association" "" "HTTPS"
$null = Conectar $api $vertex "Association" "" "HTTPS"
Al-Fondo $dd
Exportar $dd "DESP-01.png"

# ------------------------------------------- 6. re-exportar los diagramas del Ciclo 1 afectados por las correcciones
Write-Output "== Re-export Ciclo 1 corregidos"
foreach ($par in @(
    @("CU-07 Diagrama de Caso de Uso Particular","UCP-07.png"),
    @("CU-08 Diagrama de Caso de Uso Particular","UCP-08.png"),
    @("CU-16 Diagrama de Caso de Uso Particular","UCP-16.png"),
    @("CU-24 Diagrama de Caso de Uso Particular","UCP-24.png"),
    @("ACT-02 Flujo de venta y pago","ACT-02.png"))) {
    $d = Diagrama-PorNombre $par[0]
    if ($null -ne $d) { Exportar $d $par[1] }
}

# ------------------------------------------- 7. diagramas de estado (entidades con ciclo de vida real)
Write-Output "== Diagramas de estado"
function Diagrama-Estados([string]$nombre, [string]$archivo, $estados, $transiciones) {
    # $estados: lista de @(clave, nombre, x, y, tipo) ; tipo = State | Inicial | Final
    $d = Nuevo-Diagrama $pkgDisCU $nombre "Statechart"
    $els = @{}
    foreach ($e in $estados) {
        if ($e[4] -eq "State") {
            $el = Nuevo-Elemento $pkgDisCU $e[1] "State"
            $null = Poner $d $el $e[2] $e[3] ($e[2] + 170) ($e[3] + 60)
        } else {
            $el = $pkgDisCU.Elements.AddNew($e[1], "StateNode")
            $el.Subtype = $(if ($e[4] -eq "Inicial") { 3 } else { 4 })
            $null = $el.Update(); $null = $pkgDisCU.Elements.Refresh()
            $null = Poner $d $el $e[2] $e[3] ($e[2] + 30) ($e[3] + 30)
        }
        $els[$e[0]] = $el
    }
    foreach ($t in $transiciones) { $null = Conectar $els[$t[0]] $els[$t[1]] "StateFlow" "" $t[2] }
    $null = $d.Update()
    Exportar $d $archivo
}

Diagrama-Estados "EST-01 Estados de la Reserva" "EST-01.png" @(
    @("i", "Inicio", 40, 285, "Inicial"),
    @("pen", "pendiente", 330, 270, "State"),
    @("pre", "preparada", 760, 270, "State"),
    @("pru", "en_prueba", 1190, 270, "State"),
    @("com", "completada", 1620, 270, "State"),
    @("exp", "expirada", 545, 40, "State"),
    @("can", "cancelada", 545, 520, "State"),
    @("f", "Fin", 1690, 55, "Final"),
    @("f2", "Fin ", 1690, 540, "Final")
) @(
    @("i", "pen", "crearReserva() / reservarStock()"),
    @("pen", "pre", "prepararReserva()"),
    @("pre", "pru", "confirmarLlegada()"),
    @("pru", "com", "registrarSeleccion() [todo decidido]"),
    @("pen", "can", "cancelarReserva() / liberarStock()"),
    @("pre", "can", "cancelarReserva() / liberarStock()"),
    @("pen", "exp", "expirarReservas() [+24 h] / liberarStock()"),
    @("pre", "exp", "expirarReservas() [+24 h]"),
    @("com", "f", ""),
    @("can", "f2", ""),
    @("exp", "f", "")
)

Diagrama-Estados "EST-02 Estados de la Venta" "EST-02.png" @(
    @("i", "Inicio", 40, 175, "Inicial"),
    @("pp", "pendiente_pago", 200, 160, "State"),
    @("pag", "pagada", 620, 160, "State"),
    @("anu", "anulada", 620, 380, "State"),
    @("f", "Fin", 1000, 400, "Final")
) @(
    @("i", "pp", "registrarVentaDigital() | registrarVentaPresencial() / reservarStock()"),
    @("pp", "pag", "confirmarVenta() [pago aprobado] / descontar stock físico"),
    @("pp", "anu", "anularVenta() [pago rechazado] / liberarStock()"),
    @("pag", "anu", "anularPago() [reembolso] / reingresar stock (devolución)"),
    @("pag", "f", ""),
    @("anu", "f", "")
)

Diagrama-Estados "EST-03 Estados del Pago" "EST-03.png" @(
    @("i", "Inicio", 40, 315, "Inicial"),
    @("ini", "iniciado", 360, 120, "State"),
    @("rec", "rechazado", 900, 40, "State"),
    @("apr", "aprobado", 900, 300, "State"),
    @("ree", "reembolsado", 1420, 300, "State"),
    @("f", "Fin", 1490, 55, "Final")
) @(
    @("i", "ini", "iniciarPagoPasarela() [sin otro pago en curso]"),
    @("i", "apr", "pagarEnCaja() [monto suficiente]"),
    @("ini", "apr", "webhook | consultarEstado() [aprobado] / confirmarVenta()"),
    @("ini", "rec", "webhook | consultarEstado() [rechazado] / anularVenta()"),
    @("apr", "ree", "anularPago() / anularVenta()"),
    @("apr", "f", ""),
    @("rec", "f", ""),
    @("ree", "f", "")
)

# ------------------------------------------- 8. diagramas de navegación
Write-Output "== Diagramas de navegacion"
function Diagrama-Navegacion([string]$nombre, [string]$archivo, $pantallas, $enlaces) {
    # $pantallas: @(clave, texto, columna, fila) ; $enlaces: @(desde, hasta, etiqueta)
    $d = Nuevo-Diagrama $pkgDisCU $nombre "Logical"
    $els = @{}
    foreach ($p in $pantallas) {
        $el = Nuevo-Elemento $pkgDisCU $p[1] "Class" "pantalla"
        $x = 30 + [int]$p[2] * 250; $y = 30 + [int]$p[3] * 95
        $null = Poner $d $el $x $y ($x + 200) ($y + 55)
        $els[$p[0]] = $el
    }
    foreach ($e in $enlaces) {
        $c = Conectar $els[$e[0]] $els[$e[1]] "Association" "link" $e[2]
        $c.Direction = "Source -> Destination"; $null = $c.Update()
    }
    $null = $d.Update()
    Exportar $d $archivo
}

Diagrama-Navegacion "NAV-01 Navegacion - Tienda web (cliente)" "NAV-01.png" @(
    @("cat", "Catalogo (/catalogo)", 0, 2),
    @("log", "Iniciar sesion (/login)", 0, 5),
    @("reg", "Registro (/registro)", 1, 6),
    @("rec", "Recuperar contrasena (/recuperar)", 1, 4),
    @("det", "Detalle de prenda (/producto/:id)", 1, 2),
    @("car", "Carrito (/carrito)", 2, 1),
    @("ent", "Checkout entrega", 3, 1),
    @("pag", "Checkout pago", 4, 1),
    @("est", "Estado del pago", 5, 1),
    @("res", "Confirmar reserva", 2, 3),
    @("mre", "Mis reservas", 3, 3),
    @("dre", "Detalle de reserva", 4, 3),
    @("mco", "Mis compras", 3, 0),
    @("com", "Comprobante", 4, 0)
) @(
    @("cat", "det", "elegir prenda"), @("cat", "log", "iniciar sesion"), @("log", "reg", "crear cuenta"),
    @("log", "rec", "olvide mi contrasena"), @("det", "car", "agregar al carrito"), @("car", "ent", "continuar"),
    @("ent", "pag", "elegir entrega"), @("pag", "est", "pagar en pasarela"), @("det", "res", "reservar para probarte"),
    @("res", "mre", "confirmar"), @("mre", "dre", "ver / cancelar"), @("car", "mco", "menu"), @("mco", "com", "ver comprobante")
)

Diagrama-Navegacion "NAV-02 Navegacion - Back office web" "NAV-02.png" @(
    @("log", "Iniciar sesion (/login)", 0, 4),
    @("das", "Dashboard", 1, 4),
    @("org", "Organizacion", 2, 1),
    @("usu", "Usuarios", 3, 0), @("rol", "Roles", 4, 0), @("ciu", "Ciudades", 3, 1), @("suc", "Sucursales", 4, 1), @("emp", "Empleados", 5, 1),
    @("cat", "Catalogo", 2, 3),
    @("ctm", "Categorias / Tallas / Colores / Temporadas / Colecciones", 3, 2), @("pro", "Productos", 3, 3), @("prb", "Probador (editor de anclajes)", 4, 3),
    @("inv", "Inventario", 2, 5),
    @("itb", "Consolidado / Kardex / Recepcion / Limites / Alertas / Valuacion / Transferencias", 3, 5),
    @("prv", "Proveedores", 2, 6),
    @("ven", "Ventas", 2, 8),
    @("rsv", "Reservas de sucursal", 3, 7), @("caj", "Caja", 3, 8), @("prm", "Promociones", 3, 9),
    @("rep", "Reportes", 2, 10), @("zon", "Zonas de envio", 2, 11)
) @(
    @("log", "das", "ingresar (rol staff)"), @("das", "org", "menu"), @("org", "usu", ""), @("usu", "rol", ""), @("org", "ciu", ""), @("ciu", "suc", ""),
    @("suc", "emp", ""), @("das", "cat", "menu"), @("cat", "ctm", ""), @("cat", "pro", ""), @("pro", "prb", "assets de variante"),
    @("das", "inv", "menu"), @("inv", "itb", "pestanas"), @("das", "prv", "menu"), @("das", "ven", "menu"), @("ven", "caj", ""),
    @("ven", "prm", ""), @("ven", "rsv", ""), @("rsv", "caj", "facturar reserva completada"), @("das", "rep", "menu"), @("das", "zon", "menu")
)

Diagrama-Navegacion "NAV-03 Navegacion - App movil (cliente)" "NAV-03.png" @(
    @("spl", "Splash", 0, 3),
    @("log", "Login", 1, 5), @("reg", "Registro", 2, 6),
    @("hom", "Home / catalogo", 1, 2),
    @("fil", "Filtros y busqueda por voz", 2, 0),
    @("det", "Detalle de prenda", 2, 2),
    @("prb", "Probador (espejo / realista)", 3, 0),
    @("fav", "Favoritos", 2, 1),
    @("car", "Carrito", 3, 2), @("ent", "Entrega", 4, 2), @("dir", "Nueva direccion", 5, 3), @("pag", "Pago", 5, 2), @("est", "Estado del pago (WebView)", 6, 2),
    @("res", "Confirmar reserva", 3, 4), @("mre", "Mis reservas", 4, 4), @("dre", "Detalle de reserva", 5, 4),
    @("mco", "Mis compras", 3, 5), @("com", "Detalle de compra", 4, 5)
) @(
    @("spl", "hom", "sesion restaurada"), @("spl", "log", "sin sesion"), @("log", "reg", "crear cuenta"), @("log", "hom", "ingresar"),
    @("hom", "fil", "filtrar / voz"), @("hom", "det", "elegir prenda"), @("hom", "fav", "menu"), @("det", "prb", "probar"),
    @("det", "car", "agregar"), @("car", "ent", "continuar"), @("ent", "dir", "agregar direccion"), @("ent", "pag", "elegir entrega"),
    @("pag", "est", "pagar"), @("det", "res", "reservar"), @("res", "mre", "confirmar"), @("mre", "dre", "ver / cancelar"),
    @("hom", "mco", "menu"), @("mco", "com", "ver")
)

# ------------------------------------------- 8b. DCD general (reemplaza la vista vieja con errores)
Write-Output "== DCD-00"
$pkgDatos = Paquete 9
$dDcd = Nuevo-Diagrama $pkgDatos "DCD-00 Vista general del modelo de datos" "Logical"
$clavesDcd = @(
    @("Usuario", 40, 40), @("Cliente", 40, 330), @("Empleado", 40, 620),
    @("Sucursal", 380, 620), @("Categoria", 380, 40), @("Producto", 720, 40),
    @("ProductoVariante", 720, 330), @("Stock", 380, 330), @("Reserva", 1060, 620),
    @("ReservaDetalle", 1060, 330), @("Carrito", 1400, 40), @("CarritoDetalle", 1060, 40),
    @("Venta", 1400, 620), @("VentaDetalle", 1400, 330), @("Pago", 1740, 620)
)
foreach ($c in $clavesDcd) {
    $xml = [xml]$rep.SQLQuery("SELECT Object_ID FROM t_object WHERE Package_ID=9 AND Object_Type='Class' AND Name='$($c[0])'")
    $fila = $xml.EADATA.Dataset_0.Data.Row | Select-Object -First 1
    if ($null -eq $fila) { Write-Output "  (sin clase $($c[0]))"; continue }
    $el = $rep.GetElementByID([int]$fila.Object_ID)
    $alto = [Math]::Min(250, 60 + 14 * $el.Attributes.Count)
    $null = Poner $dDcd $el $c[1] $c[2] ($c[1] + 280) ($c[2] + $alto)
}
$null = $dDcd.Update()
Exportar $dDcd "DCD-00.png"

# ------------------------------------------- 9. exportar diagramas de datos existentes
Write-Output "== Diagramas de datos"
foreach ($n in "DAT-01 Seguridad y Organizacion", "DAT-02 Catalogo", "DAT-03 Inventario", "DAT-04 Reservas", "DAT-05 Probador", "DAT-06 Ventas y Pagos") {
    $d = Diagrama-PorNombre $n
    if ($null -ne $d) { Exportar $d ($n.Substring(0, 6) + ".png") }
}

$rep.CloseFile()
$rep.Exit()
Write-Output "LISTO"
