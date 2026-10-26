# API de notas: Flask en Google Cloud Run

Este repositorio contiene solo la API Python. La base MySQL se ejecuta en Aiven y el frontend se publica por separado en Vercel. Los comandos de este manual se ejecutan desde la raiz de **este repositorio**, donde estan `app.py`, `requirements.txt` y `Procfile`.

Los ejemplos de terminal usan **PowerShell**. Sustituye los valores de ejemplo. Este manual no publica recursos automaticamente: los comandos que ejecutes pueden generar costos.

## 1. Arquitectura y orden

```text
Navegador -> Vercel -> reescritura /api/* -> Cloud Run -> MySQL de Aiven
             HTTPS                         HTTPS        TLS + CA
```

1. Crea MySQL en Aiven y ejecuta el script del repositorio de base de datos desde Workbench o DBeaver.
2. Configura y despliega este backend.
3. Usa la URL de Cloud Run en la reescritura de Vercel del repositorio frontend.

No necesitas SSH para conectar Cloud Run con Aiven. Cloud Run administra el servidor; la conexion a MySQL usa TLS.

## 2. Ajuste obligatorio por la separacion de repositorios

**Estado actual:** `app.py` todavia define `init_db()` y la ejecuta al importar el modulo. Esa funcion lee `schema.sql` desde la carpeta del backend, pero el archivo ahora pertenece al repositorio de base de datos. Si no corriges esto, Gunicorn no podra iniciar.

Antes de desplegar:

1. Elimina la funcion `init_db()` de `app.py`.
2. Elimina tambien la llamada suelta `init_db()` que aparece antes de `if __name__ == "__main__":`.
3. No copies el SQL al backend: crea las tablas manualmente desde el repositorio de base de datos.
4. La ruta `/` aun intenta servir `static/index.html`, que ya no esta aqui. Reemplaza solo su cuerpo para devolver una respuesta de estado:

```python
@app.get("/")
def index():
    return jsonify(servicio="api-notas", estado="ok")
```

Puedes crear Flask como `Flask(__name__, static_folder=None)` en lugar de configurar `static`. Los endpoints `/api/...` no necesitan otros cambios para trabajar con la reescritura de Vercel.

El estado de `/` solo indica que el proceso responde; no verifica MySQL. Comprueba la conexion real con `/api/categorias`.

Estos ajustes se describen aqui como pasos previos; este README no modifica automaticamente el codigo.

## 3. Preparar y probar localmente

Requisitos: Python 3.11 o 3.12 recomendado, Git y acceso a Aiven. En Windows utiliza `py` si `python` abre Microsoft Store.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Gunicorn es para Linux, como el entorno de Cloud Run. En Windows usa el servidor local de Flask, no ejecutes Gunicorn.

Descarga el CA del proyecto correcto de Aiven y guardalo en `certs/ca.pem`. Crea un archivo `.env` local con tus valores:

```dotenv
MYSQL_HOST=tu-servicio.aivencloud.com
MYSQL_PORT=16702
MYSQL_DATABASE=defaultdb
MYSQL_USER=tu_usuario_api
MYSQL_PASSWORD="tu_contrasena_real"
MYSQL_SSL_MODE=VERIFY_IDENTITY
MYSQL_SSL_CA=certs/ca.pem
PORT=8000
```

El puerto es ilustrativo: usa el de tu servicio. Si creaste `notas_app`, reemplaza `defaultdb`. En `.env`, las comillas delimitan el valor; no forman parte de la contrasena. Para valores especiales sigue la sintaxis de python-dotenv.

La aplicacion lee estas variables individuales. Una variable `DATABASE_URL` por si sola no configura esta conexion. En Cloud Run se usaran variables y Secret Manager, no este `.env`.

`get_db()` activa `ssl_verify_cert=True` y `ssl_verify_identity=True` siempre, incluso si se configura el modo `REQUIRED`. No permite conexiones sin SSL. `MYSQL_SSL_CA` acepta una ruta relativa al backend o una absoluta.

Valida el CA y arranca despues de aplicar el apartado 2:

```powershell
.\.venv\Scripts\python.exe -c "import ssl; ssl.create_default_context(cafile='certs/ca.pem'); print('CA legible')"
.\.venv\Scripts\python.exe app.py
```

En otra terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/
Invoke-RestMethod http://127.0.0.1:8000/api/categorias
Invoke-RestMethod http://127.0.0.1:8000/api/notas
```

Las consultas deben devolver listas JSON; si no hay datos, `[]` es correcto. Un `503` indica que debes revisar la conexion o el esquema.

## 4. Proteger los archivos antes de subir el repositorio

Mantiene fuera de Git `.env`, `.venv/`, `__pycache__/`, `*.db` y credenciales. El antiguo `notas.db` no se utiliza: la aplicacion usa MySQL, no SQLite.

Ademas, crea un archivo **`.gcloudignore`** con este contenido. Git y la subida de codigo a Google Cloud son mecanismos distintos; no dependas solo de `.gitignore`:

```gitignore
.gcloudignore
.git/
.gitignore
.env
.env.*
.venv/
__pycache__/
*.pyc
*.db
certs/
```

Antes del despliegue, `gcloud meta list-files-for-upload` permite revisar que se sube. No deben aparecer contrasenas, `.env` ni el certificado local: este ultimo se montara desde Secret Manager.

## 5. Preparar Google Cloud

1. Crea o selecciona un proyecto en https://console.cloud.google.com/.
2. Vincula una cuenta de facturacion. Cloud Run, Cloud Build, Artifact Registry y Secret Manager pueden generar cargos.
3. Instala Google Cloud CLI: https://cloud.google.com/sdk/docs/install.
4. Abre una terminal PowerShell nueva y autentica tu cuenta:

```powershell
gcloud auth login
```

Define los valores para el resto del manual. Usa el **ID** del proyecto, no su nombre visible:

```powershell
$ProjectId = "tu-project-id"
$Region = "us-central1"
$Service = "notas-api"
$RuntimeName = "notas-api-runtime"
$BuildName = "notas-api-build"
$RuntimeEmail = "$RuntimeName@$ProjectId.iam.gserviceaccount.com"
$BuildEmail = "$BuildName@$ProjectId.iam.gserviceaccount.com"

gcloud config set project $ProjectId
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com iam.googleapis.com
```

Elige una region disponible cercana a Aiven. Usa la misma region en todos los comandos del servicio.

Para la primera configuracion necesitas permisos para habilitar servicios, crear cuentas de servicio y secretos, y asignar roles. Para desplegar desde codigo se necesitan, entre otros, Cloud Run Source Developer (`roles/run.sourceDeveloper`), Service Usage Consumer (`roles/serviceusage.serviceUsageConsumer`) y permiso Service Account User sobre las cuentas utilizadas. Configurar secretos y modificar el acceso publico tambien requiere permisos de administracion del servicio, como Cloud Run Admin (`roles/run.admin`). Si no tienes permisos, solicita al administrador que haga la preparacion; no es necesario convertir la API en administradora del proyecto.

## 6. Crear identidades separadas

La cuenta de ejecucion lee secretos. La de compilacion construye la imagen. Ninguna necesita ser Owner.

```powershell
gcloud iam service-accounts create $RuntimeName --display-name="Runtime API notas"
gcloud iam service-accounts create $BuildName --display-name="Build API notas"

gcloud projects add-iam-policy-binding $ProjectId --member="serviceAccount:$BuildEmail" --role="roles/run.builder"
```

Si ya existen, no las vuelvas a crear. El usuario que despliega necesita `roles/iam.serviceAccountUser` sobre ambas cuentas. Un administrador puede concederlo asi, reemplazando el correo:

```powershell
$DeployerEmail = "tu-correo@example.com"
gcloud iam service-accounts add-iam-policy-binding $RuntimeEmail --member="user:$DeployerEmail" --role="roles/iam.serviceAccountUser"
gcloud iam service-accounts add-iam-policy-binding $BuildEmail --member="user:$DeployerEmail" --role="roles/iam.serviceAccountUser"
```

La propagacion de permisos puede tardar unos minutos. No repitas todo el proceso si el primer intento aun no reconoce un rol.

## 7. Guardar contrasena y CA en Secret Manager

Para no dejar la contrasena en el historial de la terminal, utiliza la consola web:

1. Abre `Security > Secret Manager` en tu proyecto.
2. Crea el secreto **`aiven-mysql-password`**.
3. Introduce solo la contrasena real: sin comillas de `.env`, sin `MYSQL_PASSWORD=` y sin saltos de linea extra.
4. Crea otro secreto llamado **`aiven-mysql-ca`** y carga el contenido completo del archivo `ca.pem` mediante la opcion de archivo.
5. Anota la version numerica creada para cada secreto. Los comandos siguientes suponen que ambas son `1`.

El CA no es una clave privada; usar Secret Manager aqui permite montarlo sin incluirlo en la imagen. No subas una clave privada en su lugar.

Concede acceso solo a la identidad de ejecucion y solo a esos dos secretos:

```powershell
gcloud secrets add-iam-policy-binding aiven-mysql-password --member="serviceAccount:$RuntimeEmail" --role="roles/secretmanager.secretAccessor"
gcloud secrets add-iam-policy-binding aiven-mysql-ca --member="serviceAccount:$RuntimeEmail" --role="roles/secretmanager.secretAccessor"
```

## 8. Confirmar el arranque de produccion

El `Procfile` incluido debe contener:

```procfile
web: gunicorn app:app --bind 0.0.0.0:$PORT
```

`requirements.txt` ya incluye Gunicorn. Los buildpacks de Google usan el `Procfile` para el proceso web; no necesitas Dockerfile para esta ruta de despliegue.

Cloud Run inyecta `PORT`; no lo fijes con `--set-env-vars`. Gunicorn debe escuchar en `0.0.0.0`, no en `127.0.0.1`. El bloque local `app.run(...)` no se ejecuta al importar `app:app` con Gunicorn.

## 9. Desplegar desde codigo fuente

Desde la raiz del repositorio backend, define los datos no secretos:

```powershell
$MysqlHost = "tu-servicio.aivencloud.com"
$MysqlPort = "16702"
$MysqlDatabase = "defaultdb"
$MysqlUser = "tu_usuario_api"

$EnvVars = "MYSQL_HOST=$MysqlHost,MYSQL_PORT=$MysqlPort,MYSQL_DATABASE=$MysqlDatabase,MYSQL_USER=$MysqlUser,MYSQL_SSL_MODE=VERIFY_IDENTITY,MYSQL_SSL_CA=/secrets/mysql/ca.pem"
$SecretBindings = "MYSQL_PASSWORD=aiven-mysql-password:1,/secrets/mysql/ca.pem=aiven-mysql-ca:1"

gcloud meta list-files-for-upload
```

Verifica la lista de archivos antes de continuar. Luego ejecuta:

```powershell
gcloud run deploy $Service --source . --region $Region --service-account $RuntimeEmail --build-service-account "projects/$ProjectId/serviceAccounts/$BuildEmail" --allow-unauthenticated --set-build-env-vars GOOGLE_PYTHON_VERSION=3.12.x --set-env-vars $EnvVars --set-secrets $SecretBindings --max-instances 2 --concurrency 8 --memory 512Mi --cpu 1 --timeout 60
```

`GOOGLE_PYTHON_VERSION` configura la compilacion, no una variable de la API. Aqui se fija la familia 3.12 para no depender de la version predeterminada del buildpack. Revisa su soporte antes de actualizarla.

Si pregunta si deseas crear el repositorio de Artifact Registry para las compilaciones desde codigo, confirma solo despues de revisar proyecto y region. Se construira una imagen y se creara una revision de Cloud Run.

Este comando publica la API en Internet. **La API actual no tiene autenticacion ni separacion de usuarios: cualquier persona que conozca la URL puede leer, crear, editar y borrar todas las notas y categorias.** Es apropiado para una demostracion sin datos sensibles, no para notas privadas. La reescritura de Vercel y CORS no sustituyen autenticacion. Antes de uso real, incorpora autenticacion y autorizacion; no confies en ocultar la URL.

Algunas organizaciones prohiben `--allow-unauthenticated`. En ese caso, este frontend no podra usar la API sin un mecanismo adicional de autenticacion entre Vercel y Cloud Run. Solicita una configuracion aprobada; no desactives politicas de la organizacion.

`--max-instances` y `--concurrency` son limites iniciales conservadores, no una garantia de costo maximo ni de disponibilidad. Configura alertas de presupuesto y revisa los limites de conexiones de tu plan de Aiven.

## 10. Red entre Cloud Run y Aiven

Con un host publico de Aiven, la conexion sale por Internet usando TLS. No debes configurar Cloud SQL: Aiven no es Cloud SQL.

Si Aiven tiene una lista de IP permitidas, la salida predeterminada de Cloud Run puede cambiar. Opciones:

- Para una prueba, utiliza solo la politica de acceso publico que hayas decidido aceptar conscientemente en Aiven. Permitir todas las IP amplifica la exposicion aunque la conexion use TLS.
- Para una lista cerrada de IP, configura una IP publica estatica de salida mediante VPC, Cloud NAT y enrutamiento de **todo** el trafico de salida por esa VPC; permite esa IP en Aiven. Un conector por si solo o la opcion de enviar solo rangos privados no fija la IP hacia Aiven publico.

La red con IP estatica es infraestructura adicional con permisos y costos propios; este comando de despliegue no la crea. Sigue la guia oficial: https://cloud.google.com/run/docs/configuring/static-outbound-ip.

## 11. Comprobar el despliegue

```powershell
$ApiUrl = (gcloud run services describe $Service --region $Region --format="value(status.url)").Trim()
$ApiUrl
Invoke-RestMethod "$ApiUrl/"
Invoke-RestMethod "$ApiUrl/api/categorias"
Invoke-RestMethod "$ApiUrl/api/notas"
```

Las dos ultimas consultas comprueban acceso a MySQL y tablas existentes. Una respuesta `[]` es correcta si no hay datos. Entrega al repositorio frontend el valor HTTPS de `$ApiUrl`, sin agregar `/api` al final.

Para revisar registros:

```powershell
gcloud run services logs read $Service --region $Region --limit 50
```

No imprimas contrasenas ni URI de conexion en los logs. Una prueba TLS local puede confirmar la negociacion usando la configuracion real de `get_db()`:

```powershell
.\.venv\Scripts\python.exe -c "from app import app, get_db; context = app.app_context(); context.push(); cursor = get_db().cursor(); cursor.execute('SHOW SESSION STATUS LIKE %s', ('Ssl_cipher',)); print(cursor.fetchone()); cursor.close(); context.pop()"
```

El cifrado debe ser no vacio. La lectura del CA por si sola no comprueba la conexion a Aiven.

## 12. Actualizar codigo o secretos

Para publicar cambios de codigo, vuelve a ejecutar el comando de despliegue desde la raiz del backend con las variables de tu sesion definidas. Conserva los mismos nombres de servicio y region. No necesitas ejecutar otra vez el SQL si las tablas no cambiaron.

Para cambiar la contrasena, cambiala en Aiven, crea una version nueva del secreto y despliega una revision con ese numero en `$SecretBindings`. Haz lo mismo si cambia el CA. Las versiones estan fijadas explicitamente: crear una nueva no actualiza automaticamente esta revision. Coordina la rotacion para minimizar interrupciones y conserva una revision anterior utilizable cuando sea posible.

`--set-env-vars` reemplaza la configuracion de variables definida de esa forma: incluye todas las necesarias al reutilizarlo. Comprueba tambien las referencias a secretos en cada revision. No almacenes archivos persistentes ni SQLite en Cloud Run; el sistema de archivos del contenedor es efimero.

## 13. API disponible

| Metodo | Ruta | Uso |
| --- | --- | --- |
| GET | `/api/categorias` | Listar categorias |
| POST | `/api/categorias` | Crear con `{"nombre":"Trabajo"}` |
| DELETE | `/api/categorias/<id>` | Borrar categoria, conservando sus notas |
| GET | `/api/notas` | Listar notas |
| POST | `/api/notas` | Crear con `{"titulo":"Ejemplo","contenido":"Texto","categoria_id":null}` |
| PUT | `/api/notas/<id>` | Editar enviando los mismos campos |
| DELETE | `/api/notas/<id>` | Borrar nota |

Los cuerpos son JSON con `Content-Type: application/json`. Se usan respuestas `201` al crear y `204` al borrar; `400`, `404`, `409` y `503` indican errores segun el caso.

## 14. Problemas frecuentes

| Problema | Accion |
| --- | --- |
| FileNotFoundError de schema.sql al arrancar | Aplicar el apartado 2; la creacion del esquema es externa |
| No escucha en PORT | Revisar Procfile, Gunicorn y logs; no usar el servidor local de Flask |
| Error al construir / permission denied | Revisar APIs, rol `roles/run.builder` y permiso para usar las cuentas de servicio |
| Permission denied al leer secretos | Verificar la cuenta de ejecucion, `secretAccessor`, nombre y version |
| SSL / certificate verify failed | Comprobar CA montado, ruta `/secrets/mysql/ca.pem`, host y CA del proyecto correcto |
| Timeout MySQL | Comprobar puerto, servicio Aiven y reglas de salida/IP permitidas |
| 503 de la API | Revisar logs: credenciales, base elegida y existencia de tablas |
| 403 antes de llegar a Flask | Revisar acceso publico de Cloud Run y politicas de organizacion |
| 404 en / | Aplicar la sustitucion de la ruta del apartado 2 |
| Frontend no conecta | Revisar la URL HTTPS y la reescritura de Vercel |

## Referencias

- Despliegue desde codigo: https://cloud.google.com/run/docs/deploying-source-code
- Buildpack Python: https://cloud.google.com/docs/buildpacks/python
- Secretos en Cloud Run: https://cloud.google.com/run/docs/configuring/services/secrets
- IP estatica de salida: https://cloud.google.com/run/docs/configuring/static-outbound-ip