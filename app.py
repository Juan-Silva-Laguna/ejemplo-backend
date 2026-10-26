import os
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv
from flask import Flask, g, jsonify, request
from mysql.connector.constants import ClientFlag
from werkzeug.exceptions import HTTPException


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024
LOCAL_FRONTEND_ORIGINS = {
    "http://localhost:5500",
    "http://127.0.0.1:5500",
}


@app.after_request
def allow_local_frontend(response):
    origin = request.headers.get("Origin")
    if origin in LOCAL_FRONTEND_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Vary"] = "Origin"
    return response


def get_db():
    if "db" not in g:
        if os.environ.get("MYSQL_SSL_MODE", "REQUIRED") not in {
            "REQUIRED", "VERIFY_CA", "VERIFY_IDENTITY"
        }:
            raise RuntimeError("La conexion MySQL requiere SSL.")
        g.db = mysql.connector.connect(
            host=os.environ["MYSQL_HOST"],
            port=int(os.environ.get("MYSQL_PORT", "3306")),
            database=os.environ["MYSQL_DATABASE"],
            user=os.environ["MYSQL_USER"],
            password=os.environ["MYSQL_PASSWORD"],
            ssl_disabled=False,
            ssl_ca=str(BASE_DIR / os.environ["MYSQL_SSL_CA"]),
            ssl_verify_cert=True,
            ssl_verify_identity=True,
            charset="utf8mb4",
            connection_timeout=10,
            autocommit=True,
            client_flags=[ClientFlag.FOUND_ROWS],
        )
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    database = g.pop("db", None)
    if database is not None:
        database.close()


def get_body():
    body = request.get_json()
    if not isinstance(body, dict):
        raise ValueError("Se esperaba un objeto JSON.")
    return body


def required_text(body, field, limit):
    value = body.get(field)
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
        raise ValueError(f"{field}: escribe entre 1 y {limit} caracteres.")
    return value.strip()


@app.errorhandler(ValueError)
def invalid_value(error):
    return jsonify(error=str(error)), 400


@app.errorhandler(HTTPException)
def http_error(error):
    return jsonify(error=error.description), error.code


@app.errorhandler(mysql.connector.Error)
def database_error(error):
    app.logger.error("Error MySQL (codigo %s).", error.errno)
    return jsonify(error="No se pudo completar la operacion en la base de datos."), 503


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/categorias")
def list_categories():
    with get_db().cursor(dictionary=True) as cursor:
        cursor.execute("SELECT * FROM categorias ORDER BY nombre")
        return jsonify(cursor.fetchall())


@app.post("/api/categorias")
def create_category():
    nombre = required_text(get_body(), "nombre", 80)
    database = get_db()
    try:
        with database.cursor() as cursor:
            cursor.execute("INSERT INTO categorias (nombre) VALUES (%s)", (nombre,))
            category_id = cursor.lastrowid
    except mysql.connector.IntegrityError as error:
        if error.errno == 1062:
            return jsonify(error="Ya existe una categoria con ese nombre."), 409
        raise
    return jsonify(id=category_id, nombre=nombre), 201


@app.delete("/api/categorias/<int:category_id>")
def delete_category(category_id):
    with get_db().cursor() as cursor:
        cursor.execute("DELETE FROM categorias WHERE id = %s", (category_id,))
        if not cursor.rowcount:
            return jsonify(error="Categoria no encontrada."), 404
    return "", 204


@app.get("/api/notas")
def list_notes():
    with get_db().cursor(dictionary=True) as cursor:
        cursor.execute(
            """SELECT notas.*, categorias.nombre AS categoria
               FROM notas LEFT JOIN categorias ON categorias.id = notas.categoria_id
               ORDER BY notas.actualizada_en DESC, notas.id DESC"""
        )
        return jsonify(cursor.fetchall())


@app.route("/api/notas", methods=["POST"])
@app.route("/api/notas/<int:note_id>", methods=["PUT"])
def save_note(note_id=None):
    body = get_body()
    titulo = required_text(body, "titulo", 150)
    contenido = body.get("contenido", "")
    categoria_id = body.get("categoria_id")
    if not isinstance(contenido, str):
        raise ValueError("El contenido debe ser texto.")
    if categoria_id is not None and type(categoria_id) is not int:
        raise ValueError("La categoria debe ser un identificador numerico o null.")
    with get_db().cursor(dictionary=True) as cursor:
        if categoria_id is not None:
            cursor.execute("SELECT id FROM categorias WHERE id = %s", (categoria_id,))
            if not cursor.fetchone():
                raise ValueError("La categoria seleccionada no existe.")
        if note_id is None:
            cursor.execute(
                "INSERT INTO notas (titulo, contenido, categoria_id) VALUES (%s, %s, %s)",
                (titulo, contenido, categoria_id),
            )
            note_id = cursor.lastrowid
            status = 201
        else:
            cursor.execute(
                """UPDATE notas SET titulo = %s, contenido = %s, categoria_id = %s,
                   actualizada_en = CURRENT_TIMESTAMP WHERE id = %s""",
                (titulo, contenido, categoria_id, note_id),
            )
            if not cursor.rowcount:
                return jsonify(error="Nota no encontrada."), 404
            status = 200
        cursor.execute("SELECT * FROM notas WHERE id = %s", (note_id,))
        return jsonify(cursor.fetchone()), status


@app.delete("/api/notas/<int:note_id>")
def delete_note(note_id):
    with get_db().cursor() as cursor:
        cursor.execute("DELETE FROM notas WHERE id = %s", (note_id,))
        if not cursor.rowcount:
            return jsonify(error="Nota no encontrada."), 404
    return "", 204


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "9000")))