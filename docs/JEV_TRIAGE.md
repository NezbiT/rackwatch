# Triage con Jev (sin modelo generativo)

`POST /api/v1/triage` sustituye el nodo de Ollama en el flujo de alertas. Jev elige una causa y una acción. RackWatch redacta el texto. No reinicia contenedores.

La clave `TYPESAFE_API_KEY` va en el entorno de RackWatch, no en el widget de Omarchy.

## Alerta

El cuerpo puede ser el JSON del nodo **Preparar Alerta**, más `logs` si existen.

```http
POST /api/v1/triage
X-API-Key: <RACKWATCH_API_TOKEN>
```

Respuesta útil para Telegram:

- `text`: mensaje en español
- `cause`, `action`, `needs_review`
- `target`: contenedor al que aplica la acción

Si la confianza de la causa baja de 0.6, o la acción es reiniciar, `needs_review` es verdadero y el texto pide una persona. Ese umbral es un punto de partida: ajústalo con tus alertas.

En n8n, cambia el nodo **Ollama Diagnostico** por un HTTP Request a esa ruta. En **Formatear Telegram Alerta**, usa `$json.text` en lugar de `$json.message.content`.

## Pregunta del bot

`POST /api/v1/triage/intent` con `{ "text": "¿por qué falló adguard?" }` devuelve `intent` (`status`, `cpu`, `memory`, `alerts`, `logs`, `help`, `unknown`) y `endpoint`. El código de n8n consulta esa ruta de RackWatch y formatea los números. No hay párrafo generado.

Una confianza de intención bajo 0.6 queda en `unknown` y no elige contenedor.
