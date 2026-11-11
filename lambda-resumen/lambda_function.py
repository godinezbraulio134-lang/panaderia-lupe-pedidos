import os
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Attr

# --- Reglas de negocio ---
DIAS_VENTANA = 7  # el resumen cubre los 7 días que empiezan mañana

# México no usa horario de verano desde 2022, así que UTC-6 es fijo.
ZONA_MX = timezone(timedelta(hours=-6))

NOMBRES_DIA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
NOMBRES_MES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

# La tabla y el tema vienen de variables de entorno, no del código.
TABLE = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
SNS = boto3.client("sns")
TOPIC_ARN = os.environ["TOPIC_ARN"]


def etiqueta(dia_iso):
    d = date.fromisoformat(dia_iso)
    return f"{NOMBRES_DIA[d.weekday()]} {d.day} de {NOMBRES_MES[d.month - 1]}"


def leer_pedidos(desde, hasta):
    """Lee la tabla completa (Scan) y se queda con los pedidos de la ventana.
    El filtro también descarta los elementos #contador#, que no tienen dia_entrega."""
    kwargs = {"FilterExpression": Attr("dia_entrega").between(desde.isoformat(), hasta.isoformat())}
    pedidos = []
    while True:
        respuesta = TABLE.scan(**kwargs)
        pedidos.extend(respuesta.get("Items", []))
        if "LastEvaluatedKey" not in respuesta:
            return pedidos
        kwargs["ExclusiveStartKey"] = respuesta["LastEvaluatedKey"]


def armar_resumen(pedidos, desde, hasta):
    """Devuelve (asunto, mensaje). Función pura: no toca AWS, así se puede probar sola."""
    periodo = f"{etiqueta(desde.isoformat())} al {etiqueta(hasta.isoformat())}"

    if not pedidos:
        return (
            "Sin pedidos esta semana",
            f"No hay pedidos para {periodo}.\n\n"
            "El sistema está funcionando: este aviso llega cada semana aunque no haya pedidos.",
        )

    pedidos = sorted(pedidos, key=lambda p: (p["dia_entrega"], p.get("creado", "")))
    lineas = [f"Pedidos de la semana: {periodo}", f"Total: {len(pedidos)} pedido(s)", ""]

    dia_actual = None
    for p in pedidos:
        if p["dia_entrega"] != dia_actual:
            dia_actual = p["dia_entrega"]
            lineas += ["", etiqueta(dia_actual)]
        lineas.append(f"- {p['nombre']} ({p['telefono']}): {int(p['piezas'])} {p['pan']}")

    totales = Counter()
    for p in pedidos:
        totales[p["pan"]] += int(p["piezas"])
    lineas += ["", "Total por pan"]
    lineas += [f"- {pan}: {cantidad}" for pan, cantidad in sorted(totales.items())]

    return f"Pedidos de la semana ({len(pedidos)})", "\n".join(lineas)


def lambda_handler(event, context):
    hoy = datetime.now(ZONA_MX).date()
    desde = hoy + timedelta(days=1)
    hasta = hoy + timedelta(days=DIAS_VENTANA)

    pedidos = leer_pedidos(desde, hasta)
    asunto, mensaje = armar_resumen(pedidos, desde, hasta)
    SNS.publish(TopicArn=TOPIC_ARN, Subject=asunto, Message=mensaje)
    return {"pedidos": len(pedidos)}
