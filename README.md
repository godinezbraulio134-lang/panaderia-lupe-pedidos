# Pedidos para Panadería Doña Lupe: formulario sin servidores en AWS

## El cliente y su necesidad

El cliente es una panadería local que ya tiene un sitio estático (Proyecto 1) y quería agregarle un formulario de pedidos con los campos nombre, teléfono, qué pan, cuántas piezas y qué día pasan por él. Quería recibir un aviso por correo cada vez que un cliente haga un pedido nuevo, poder ver los pedidos de la semana ordenados, sin tener que buscarlos, y que quien haga el pedido vea el mensaje "Recibimos tu pedido".

Esperaba entre 20 y 50 pedidos al mes, no quería servidores que administrar y quería que el costo fuera idealmente $0. Le preocupaban los pedidos falsos, que los datos de sus clientes quedaran expuestos y que un cliente que da dos clics al botón de enviar generara un pedido duplicado. No necesitaba pagos en línea, cuentas de usuario ni una app para el celular.

## Arquitectura

### Cómo se procesa un pedido

El navegador genera un ID aleatorio para cada pedido al abrir la página y lo envía con el formulario, de modo que un doble clic llega con el mismo ID. La API pasa la petición a una Lambda que valida los datos y, si son válidos, guarda el pedido en DynamoDB y suma 1 al contador del día en una sola transacción: o se aplican las dos escrituras o ninguna. Luego publica el aviso para Lupe en SNS, marca el pedido con `aviso_enviado = true` y responde 200 con "Pedido recibido".

- **Pedido nuevo y válido:** 200. Se guarda, suma al contador y Lupe recibe un correo.
- **El mismo pedido otra vez (doble clic):** 200 con el mismo mensaje. No se guarda de nuevo, no suma al contador y no manda otro correo. Si el primer intento guardó el pedido pero falló antes de avisar, el pedido quedó con `aviso_enviado = false`: la Lambda lo detecta, manda el aviso que faltaba y responde 200.
- **Datos inválidos:** 400 con un mensaje que dice qué corregir. No se guarda ni se avisa. Es una respuesta normal de la Lambda, no un error, así que no activa la alarma.
- **Día lleno (15 pedidos):** 429, sin guardar ni avisar. Quien da doble clic en el pedido número 15 recibe 200, porque la Lambda revisa primero si el ID ya existía.

Si guardar o avisar fallan, la Lambda termina con error (500), cuenta para la alarma de CloudWatch y el comprador puede reintentar con el mismo ID.
