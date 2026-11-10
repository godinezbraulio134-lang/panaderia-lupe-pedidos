# Pedidos para Panadería Doña Lupe: formulario sin servidores en AWS

## El cliente y su necesidad

El cliente es una panadería local que ya tiene un sitio estático (Proyecto 1) y quería agregarle un formulario de pedidos con los campos nombre, teléfono, qué pan, cuántas piezas y qué día pasan por él. Quería recibir un aviso por correo cada vez que un cliente haga un pedido nuevo, poder ver los pedidos de la semana ordenados, sin tener que buscarlos, y que quien haga el pedido vea el mensaje "Recibimos tu pedido".

Esperaba entre 20 y 50 pedidos al mes, no quería servidores que administrar y quería que el costo fuera idealmente $0. Le preocupaban los pedidos falsos, que los datos de sus clientes quedaran expuestos y que un cliente que da dos clics al botón de enviar generara un pedido duplicado. No necesitaba pagos en línea, cuentas de usuario ni una app para el celular.
