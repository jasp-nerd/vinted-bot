---
title: "Bot de Vinted gratis: alertas de artículos nuevos sin pagar"
description: "Bot de Vinted gratis y de código abierto: recibe los artículos nuevos de tus búsquedas en Telegram, Discord o el móvil. Sin suscripción ni login."
slug: bot-vinted-gratis
key: free-bot
date: 2026-10-30
updated: 2026-10-30
keywords:
  - bot vinted gratis
  - bot vinted telegram
  - bot vinted discord
  - bot vinted gratis discord
  - bot vinted github
  - vinted bot free
faq:
  - q: "¿Existe un bot de Vinted gratis?"
    a: "Sí. vinted-sniper es gratuito y de código abierto (licencia MIT), sin planes de pago. Vigila tus búsquedas de Vinted y envía los artículos nuevos a Telegram, Discord, al móvil con ntfy o a un webhook. Funciona en tu propio ordenador, que tiene que estar encendido."
  - q: "¿Un bot de Vinted gratis necesita mi cuenta de Vinted?"
    a: "Un bot de alertas no. Los resultados de búsqueda se pueden leer sin iniciar sesión. Solo las herramientas que compran, envían mensajes o resuben artículos por ti necesitan tu cuenta, y son esas las que la ponen en riesgo."
  - q: "¿Hay un bot de Vinted en Telegram gratis?"
    a: "Con vinted-sniper creas tu propio bot privado de Telegram con BotFather en unos tres minutos, y te manda los artículos nuevos de tus búsquedas. Sin límite de búsquedas y sin pagar nada."
  - q: "¿Un bot de Vinted gratis puede comprar por mí?"
    a: "Este no. Comprar automáticamente necesita tu cuenta con la sesión iniciada, y de ahí vienen las restricciones de cuentas. vinted-sniper pone un botón de compra en cada alerta, así la compra la haces tú."
---

Sí, puedes tener un bot de Vinted gratis. vinted-sniper es una aplicación gratuita y de código abierto que vigila tus búsquedas de Vinted y te envía cada artículo nuevo a Telegram, Discord o el móvil, con el precio que pagarías de verdad. Funciona en tu propio ordenador en lugar del servidor de otra persona, por eso no cuesta nada, y nunca te pide tu cuenta de Vinted.

A continuación: qué se suele entender por "bot de Vinted", qué opciones gratuitas hay, cómo montarlo en unos diez minutos y qué límites conviene conocer antes de fiarte de él.

## Qué significa "bot de Vinted"

La palabra abarca herramientas muy distintas, y la diferencia importa tanto por el precio como por el riesgo.

Un bot de alertas (también llamado monitor o sniper) vigila una búsqueda y te avisa cuando aparece algo nuevo. Luego abres el anuncio y lo compras tú. Es lo que busca la mayoría cuando las alertas de las búsquedas guardadas de Vinted les fallan.

Un bot de compra automática (autobuy) entra con tu cuenta y paga en cuanto un anuncio encaja. Son los caros, y necesitan tu cuenta y tus datos de pago.

Los bots para resubir artículos, dar me gusta o seguir son para vendedores. También funcionan a través de tu cuenta.

Esta guía trata de los bots de alertas.

## Las opciones gratuitas, comparadas con honestidad

### Las búsquedas guardadas de Vinted

Gratis y dentro de la app. Guardas una búsqueda y Vinted debería avisarte de los artículos nuevos. En la práctica mucha gente recibe las notificaciones tarde o nunca, y el filtro de precio ignora la protección al comprador. Las causas están en la guía [la alerta de Vinted no funciona](/guides/vinted-alerta-no-funciona/).

### Pruebas gratis de bots de pago

Varios bots de Telegram y apps te dejan probar una búsqueda gratis y después cuestan más o menos entre 5 y 30 euros al mes (a octubre de 2026). Bien para probar, limitado para el uso real.

### Servidores de Discord gratuitos

Canales compartidos que publican anuncios de las categorías más populares. Ves lo mismo que todos los demás, en el mismo momento, sin poder elegir tus filtros.

### Herramientas de código abierto que ejecutas tú

Gratis y sin límite de búsquedas, pero necesitas un ordenador que se quede encendido. vinted-sniper es una de ellas. Está pensada para ser fácil de instalar y para avisarte cuando deja de funcionar, que es la queja más habitual sobre los bots gratuitos.

## Por qué vinted-sniper es gratis

No hay ningún servidor por nuestra parte. La app funciona en tu portátil, tu sobremesa, una Raspberry Pi o un NAS, revisa tus búsquedas desde tu propia conexión y envía las alertas desde ahí. Sin costes de alojamiento, no hay nada que cobrar. El código está en GitHub con licencia MIT, así que cualquiera puede leer exactamente lo que hace.

Lo que tienes gratis:

- Alertas en Telegram, Discord, ntfy (una app gratuita de notificaciones para el móvil, sin cuenta), RSS o tu propio webhook. El correo y servicios como Slack o Pushover funcionan con un complemento opcional.
- El precio total en cada alerta, protección al comprador incluida, y límites de precio que usan ese total. El filtro de precio de Vinted ignora la comisión.
- Palabras que el título debe llevar y palabras que excluir, para que "para piezas" o "solo caja" no te lleguen nunca.
- Filtros de vendedor: valoración mínima, número mínimo de opiniones, país y un botón para bloquearlo.
- Una etiqueta de chollo cuando un anuncio está muy por debajo de lo que suele encontrar esa búsqueda.
- Una búsqueda en varios sitios de Vinted de distintos países, horas de silencio y un panel con las novedades en directo.
- Un estado en palabras claras para cada búsqueda, para que sepas cuándo Vinted la está frenando o cuándo se ha atascado.

## Configúralo en cinco pasos

1. Instálalo. En Windows abre PowerShell y pega el comando de una línea de la página principal; en Mac o Linux abre Terminal y pega el otro. No hacen falta permisos de administrador ni Docker. Al terminar, el navegador abre el panel en `http://localhost:8000`.
2. Busca en Vinted como siempre (palabras, categoría, talla, marca, estado) y copia la dirección de la barra del navegador, o comparte la búsqueda desde la app y copia el enlace. También puedes crear la búsqueda en el panel, con las categorías y marcas de Vinted.
3. Pégala en el panel. Verás en directo cuántos anuncios actuales encajan y cuántos quita cada filtro. Pon como precio máximo el total que estás dispuesto a pagar.
4. Elige dónde llegan las alertas. Lo más rápido es una notificación en el móvil con la app gratuita ntfy: la instalas, añades el nombre que te muestra el panel y listo. Para Telegram creas tu bot con BotFather; para Discord copias un webhook desde los ajustes del canal. Pulsa "Send test" (enviar una prueba) antes de seguir.
5. Déjalo funcionando. La primera comprobación es silenciosa a propósito, para que no te llegue una avalancha de anuncios que ya estaban. A partir de ahí, cada artículo nuevo llega con fotos, precio total, talla, estado, valoración del vendedor y botones para comprar, escribir al vendedor o abrir el anuncio.

{{install}}

## Los límites, antes de fiarte

### El ordenador tiene que estar encendido

Las alertas salen de la máquina donde funciona. Un portátil en suspensión no envía nada. En Windows, pon la suspensión en "Nunca" mientras esté enchufado; el instalador de Mac ofrece mantener el Mac despierto mientras esté cargando. Para alertas a cualquier hora, una Raspberry Pi, un NAS o un portátil viejo enchufado funcionan bien y gastan poco.

### No es instantáneo, y nada lo es

Vinted añade los anuncios nuevos a su búsqueda unos minutos después de subirlos. Cualquier herramienta que lee la búsqueda, gratis o de pago, los ve en ese momento. vinted-sniper revisa cada minuto. Revisar más a menudo no encuentra nada antes y hace que Vinted frene tu conexión. Si compites con bots de compra automática por consolas baratas, ningún bot de alertas ganará esa carrera. Si buscas una talla, una marca o un coleccionable concreto, un minuto basta.

### Tu conexión importa

Vinted pone más trabas a algunas direcciones de centros de datos y VPN que a las conexiones de casa. Ejecutarlo en casa suele ser lo más fiable. Si Vinted te frena, la app espera por sí sola y el panel te lo dice.

### No compra por ti

A propósito. Comprar automáticamente necesita tu cuenta con la sesión iniciada, y así es como se restringen cuentas. Las condiciones de Vinted prohíben el acceso automatizado: un bot que no inicia sesión no tiene ninguna cuenta que perder; uno que compra por ti, sí.

## ¿Gratis o de pago?

Si tienes un ordenador encendido buena parte del día, o una Raspberry Pi o un NAS, la opción gratuita hace lo mismo que un servicio de alertas de 5 a 30 euros al mes. Si no tienes nada que se quede encendido y no quieres instalar nada, un servicio de pago es una opción razonable, porque funciona en sus servidores. En ese caso, elige uno que no te pida tu cuenta de Vinted.

Para configurar bien las alertas, también las de la propia Vinted, mira [cómo crear una alerta en Vinted](/guides/crear-alerta-vinted/).
