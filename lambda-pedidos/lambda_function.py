import base64
import json
import os
import re
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

# --- Reglas de negocio: se acuerdan con Lupe y viven solo aquí ---
MENU = ["Concha", "Cuerno", "Oreja", "Empanada de piña", "Polvorón", "Bolillo", "Pan de elote"]
NOMBRE_MIN, NOMBRE_MAX = 2, 50
PIEZAS_MIN, PIEZAS_MAX = 1, 100
DIAS_MIN, DIAS_MAX = 1, 14  # desde mañana hasta dentro de 2 semanas
TOPE_DIARIO = 15  # máximo de pedidos nuevos por día
CAMPO_TRAMPA = "sitio_web"  # campo oculto del formulario: una persona lo deja vacío

# México no usa horario de verano desde 2022, así que UTC-6 es fijo.
ZONA_MX = timezone(timedelta(hours=-6))

# Los nombres de la tabla y del tema vienen de variables de entorno, no del código.
TABLE_NAME = os.environ["TABLE_NAME"]
TABLE = boto3.resource("dynamodb").Table(TABLE_NAME)
DB = boto3.client("dynamodb")  # cliente de bajo nivel: lo pide la transacción
SNS = boto3.client("sns")
TOPIC_ARN = os.environ["TOPIC_ARN"]


def responder(codigo, mensaje):
    return {
        "statusCode": codigo,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"mensaje": mensaje}, ensure_ascii=False),
    }


def validar(datos):
    """Devuelve (pedido_limpio, None) si todo es válido, o (None, mensaje_de_error)."""
    pedido_id = str(datos.get("pedido_id", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9-]{8,64}", pedido_id):
        return None, "Solicitud inválida."

    nombre = str(datos.get("nombre", "")).strip()
    if not (NOMBRE_MIN <= len(nombre) <= NOMBRE_MAX) or not re.fullmatch(
        r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]+", nombre
    ):
        return None, f"Revisa el nombre: de {NOMBRE_MIN} a {NOMBRE_MAX} letras."

    pan = str(datos.get("pan", "")).strip()
    if pan not in MENU:
        return None, "Elige un pan del menú."

    piezas = str(datos.get("piezas", "")).strip()
    if not piezas.isdigit() or not (PIEZAS_MIN <= int(piezas) <= PIEZAS_MAX):
        return None, f"Revisa las piezas: de {PIEZAS_MIN} a {PIEZAS_MAX}."

    try:
        dia = datetime.strptime(str(datos.get("dia_entrega", "")).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None, "Revisa el día de entrega."
    hoy = datetime.now(ZONA_MX).date()
    if not (hoy + timedelta(days=DIAS_MIN) <= dia <= hoy + timedelta(days=DIAS_MAX)):
        return None, "Revisa el día de entrega: desde mañana hasta dentro de 2 semanas."

    telefono = re.sub(r"[\s\-\(\)\.]", "", str(datos.get("telefono", "")))
    if telefono.startswith("+52"):
        telefono = telefono[3:]
    if not re.fullmatch(r"\d{10}", telefono):
        return None, "Revisa el teléfono: deben ser 10 dígitos."

    return {
        "pedido_id": pedido_id,
        "nombre": nombre,
        "pan": pan,
        "piezas": int(piezas),
        "dia_entrega": dia.isoformat(),
        "telefono": telefono,
    }, None


def avisar(pedido):
    SNS.publish(
        TopicArn=TOPIC_ARN,
        Subject=f"Nuevo pedido de {pedido['nombre']}",
        Message=(
            f"Nuevo pedido recibido\n\n"
            f"Nombre: {pedido['nombre']}\n"
            f"Teléfono: {pedido['telefono']}\n"
            f"Pan: {pedido['pan']}\n"
            f"Piezas: {int(pedido['piezas'])}\n"
            f"Día de entrega: {pedido['dia_entrega']}\n"
        ),
    )


def lambda_handler(event, context):
    # 1. Leer los datos que llegan del formulario
    try:
        raw = event.get("body") or ""
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode("utf-8")
        if len(raw) > 4000:
            return responder(400, "Solicitud inválida.")
        datos = json.loads(raw)
        if not isinstance(datos, dict):
            raise ValueError
    except ValueError:
        return responder(400, "Solicitud inválida.")

    # 2. Campo trampa: si trae algo, se rechaza sin explicar el motivo
    if datos.get(CAMPO_TRAMPA):
        return responder(400, "Solicitud inválida.")

    # 3. Validar (el 400 es una respuesta normal, no una excepción)
    pedido, error = validar(datos)
    if error:
        return responder(400, error)

    # 4. Guardar el pedido y sumar al contador del día, como UNA sola operación:
    #    o se aplican las dos escrituras, o ninguna.
    ahora = datetime.now(ZONA_MX)
    clave_contador = f"#contador#{ahora.date().isoformat()}"  # '#' no pasa la validación del ID
    nuevo = dict(pedido, aviso_enviado=False, creado=ahora.isoformat())
    try:
        DB.transact_write_items(
            TransactItems=[
                {
                    "Put": {
                        "TableName": TABLE_NAME,
                        "Item": {
                            "pedido_id": {"S": nuevo["pedido_id"]},
                            "nombre": {"S": nuevo["nombre"]},
                            "pan": {"S": nuevo["pan"]},
                            "piezas": {"N": str(nuevo["piezas"])},
                            "dia_entrega": {"S": nuevo["dia_entrega"]},
                            "telefono": {"S": nuevo["telefono"]},
                            "aviso_enviado": {"BOOL": False},
                            "creado": {"S": nuevo["creado"]},
                        },
                        "ConditionExpression": "attribute_not_exists(pedido_id)",
                    }
                },
                {
                    "Update": {
                        "TableName": TABLE_NAME,
                        "Key": {"pedido_id": {"S": clave_contador}},
                        "UpdateExpression": "ADD pedidos_hoy :uno",
                        "ConditionExpression": "attribute_not_exists(pedidos_hoy) OR pedidos_hoy < :tope",
                        "ExpressionAttributeValues": {
                            ":uno": {"N": "1"},
                            ":tope": {"N": str(TOPE_DIARIO)},
                        },
                    }
                },
            ]
        )
        a_avisar = nuevo
    except ClientError as e:
        if e.response["Error"]["Code"] != "TransactionCanceledException":
            raise  # fallo real: sube como error y activa la alarma
        # Los motivos vienen en el mismo orden que las operaciones: [guardar, contador]
        motivos = [m.get("Code") for m in e.response.get("CancellationReasons", [])]
        if len(motivos) >= 1 and motivos[0] == "ConditionalCheckFailed":
            # El ID ya existía. Esto se revisa PRIMERO: un clic repetido es el mismo
            # pedido, aunque el contador del día esté lleno.
            existente = TABLE.get_item(Key={"pedido_id": pedido["pedido_id"]}).get("Item")
            if existente is None:
                raise
            if existente.get("aviso_enviado"):
                return responder(200, "Pedido recibido")
            a_avisar = existente  # existe, pero el aviso quedó pendiente
        elif len(motivos) >= 2 and motivos[1] == "ConditionalCheckFailed":
            return responder(
                429, "Hoy ya recibimos el máximo de pedidos. Intenta mañana o escríbenos por WhatsApp."
            )
        else:
            raise

    # 5. Avisar a Lupe y marcar el aviso como enviado
    avisar(a_avisar)
    TABLE.update_item(
        Key={"pedido_id": pedido["pedido_id"]},
        UpdateExpression="SET aviso_enviado = :v",
        ExpressionAttributeValues={":v": True},
    )

    # 6. Responder al navegador
    return responder(200, "Pedido recibido")
