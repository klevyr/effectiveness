# Efectividad SMS YPP

### Procedimiento

* Acceder al sftp Diners y buscar el ultimo archivo dentro de `/LINK MOBILE LINKMBL BTS_ SMS` o `SMS`
  * Utiliza la libreta [Descarga_SFTP](../Efectividad/Descarga_SFTP.ipynb) para descargar directamente en la carpeta correspondiente.
* ~Descargar los archivos que sean necesarios al equipo local~
* ~Seleccionar el archivo descargado y comprimirlo en `ZIP`~
* ~El archivo comprimido subirlo a la carpeta `/Vendor`~
* Iniciar el flujo, seleccionando el rango de fechas
* 🚩 IMPORTANTE: Asegurar de cargar los archivos comprimidos en **ZIP**
  en el directorio `/Vendor` de las fecha a procesar. 
* 🚩 No necesitas descargar transferencias
* Ejecutar por separado la generacion de los reportes.

## Descripcion funcionalidad

El proceso de conciliacion consiste en identificar el estado de los mensajes si esta fue entregado o no,
para esto se realiza el cruce entre el log del gestor `TMSMT13U` (Log SMS `aka` Metroline) y el log del
proveedor (vendor), con el fin de poder identificar la campania y marca que corresponde.

Esto se lo realiza asi, debido a que la informacion del proveedor unicamente contiene datos de celular, mensaje y estado, 
mientras que la informacion importante se encuentra en gestor, como es la marca, codigo de campania, entidad y tipo de sms,
por lo que el unir ambas fuentes es necesario, sin embargo, no existen campos en compun que sean 100% confiables, 
por lo que se realiza un cruce por `message`, `mobilenumber` y `transactionId` que los datos en comun.

Dado que el cruzar por mensaje no es optimo, se lo pasa a `MD5` para poder realizar un cruce mas optimo y adicionalmente no
todos los casos tiene el campo transaccionid, por lo que se hace una relacion entre el tiempo generado y el tiempo enviado, 
mismo que no sobrepase mas de 5min.

El estado se dividen en dos y se encuentran detalladas en la seccion de **definiciones**:
* Estado Proveedor, `ApplicationStatus`, indica lo entregado hacia las operadoras y que queda pendiente de la gestion de estas.
* Estado Operadora, campo `PlatformStatus`, para casos en los que se tiene una respuesta de la operadora se almacena en este campo y adicionamente se nos entrega una descripcion del estado `DescripcionStatus`



## Definiciones

* Durante este proceso se esdta cruzando la informacion entre los envios
registrados en gestor y los envios del proveedor.
* Conforme a las definiciones del proveedor, esta es la descripcion de los estados:

| ApplicationStatus | PlatformStatus | Estado_Proveedor | Estado_Operadora |
|---|---|---|---|
|SUBMITD|DELIVRD|✅Entregado|✅Entregado|
|SUBMITD|UNDELIV|✅Entregado|❌No Entregado|
|UNDELIV|UNDELIV|❌No Entregado|❌No Entregado|
|***OTROS***|--|❌No Entregado|❌No Entregado|


--- 
Version Anterior

---
| STATUS | DESCRIPTION | INTERPRETACION |
|---|---|---|
|REGISTD|Recibido, evento encolado en Sendo, es un estado temporal hasta que intenta el primer despacho|✅Entregado|
|SUBMITD|Evento encolado en operadora móvil|✅Entregado|
|DELIVRD|Entregado al destino|✅Entregado|
|UNDELIV|Operadora indica que no fue posible entregar el SMS|🔺No Entregado|
|EXPIRED|El mensaje superó el tiempo previsto para ser entregado debido a que el teléfono no se encontraba en estado de recepción|🔺No Entregado|
|PORTED|El teléfono está en un estado transitorio de portabilidad|🔺No Entregado|
|DELETED|El mensaje ha sido eliminado. El mensaje ha sido cancelado o eliminado del MC. No se realizarán más intentos de entrega.|✅Entregado|
