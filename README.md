# Agenda cultural de Santo Domingo: scraper

Lee fuentes de eventos, los normaliza a un esquema único, los guarda en SQLite y exporta
`docs/events.json` para el sitio (misma forma que el prototipo: `date`, `end`, `title`, `venue`, `zone`,
`cat`, `price`, `time`, `kids`, `srcName`, `srcUrl`...).

## Sitio

`docs/index.html` es la app (Hoy, Calendario, Guardados y detalle). Lee `docs/events.json`, que el workflow
diario actualiza, y se publica con GitHub Pages (rama `main`, carpeta `/docs`). Para verla en local:

```bash
python -m http.server 8765 --directory docs   # y abre http://localhost:8765
```

Los eventos con rango de fechas sin sesiones (p. ej. una obra del 9 al 18) salen una sola vez con "Hasta",
porque la fuente no dice qué días hay función dentro del rango.

## Uso

```bash
pip install -r requirements.txt
export AGENDA_CONTACT="tu@correo.com"   # va en el User-Agent: los sitios saben a quién escribir

python -m agenda sources                 # lista las fuentes
python -m agenda run                     # lee todas, guarda y exporta docs/events.json
python -m agenda run --source cce --max-details 3
python -m agenda inspect <url>           # guarda el HTML y su texto en inspect/ (para ajustar selectores)
pytest                                   # pruebas offline (incluye páginas reales de samples/)
```

## Fuentes

| id | Fuente | Método | Estado |
|---|---|---|---|
| `teatro_nacional` | teatronacional.gob.do | API REST de WordPress (`/wp-json/wp/v2/event`) para el listado + página de detalle (`Fecha:`, `Sala:`, precios `RD$`). Respaldo: sitemap de eventos | **Verificado con HTML real** (detalle). Categoría desde "Categoría:"; sin hora en la página |
| `zona_colonial` | zonacolonial.do/actividades | Una página; cada tarjeta se detecta por el ancestro de un enlace con exactamente una fecha `MES DD` | **Verificado con HTML real** (11 tarjetas). Hora desde `data-time` del botón "Agendar"; el año se infiere |
| `cce` | ccesd.aecid.es | Enlaces `/w/...` de la página 1 del buscador + detalle (fechas `17/Oct/2026`, horario, lugar, precio) | **Listado verificado con HTML real** (tarjetas `.cardReco`; descarta eventos pasados). Detalle `/w/...` aún sin ver; 30 s entre peticiones |
| `casa_de_teatro` | casadeteatro.org/agenda | API JSON `/api/events?upcoming=true` (la página es React, HTML vacío) | **Estructura verificada con el navegador.** Hoy la API trae 0 eventos próximos (el último es del 30 jul) mientras zonacolonial.do lista 9 de Casa de Teatro para oct–nov: no confiar en ella como única fuente |
| `sic` | sic.cultura.gob.do/agenda-cultural (Ministerio de Cultura) | API JSON pública `apisic.cultura.gob.do/api/public/v1/events?date_from=…&page=N`, sin autenticación | **Verificado con la API real** (6 oct). Solo Santo Domingo y acceso abierto; une repetidos de la propia API. Sin descripción; puede pasar semanas sin eventos futuros |
| `centro_leon` | centroleon.org.do | API de The Events Calendar (`/wp-json/tribe/events/v1/events?start_date=…`) | **Verificado con la API real** (6 oct). Solo publica lo que es en Santo Domingo (la extensión de Calle Las Damas); ese día los 19 eventos eran en Santiago, así que aporta 0 |
| `teatro_las_mascaras` | teatrolasmascaras.com | Cartelera en la portada (WordPress.com): bloque por montaje con título, `Del X al Y de mes`, `Funciones:`, `Boletas: RD$…` y botón a tix.do. Se lee el texto visible; robots.txt lo permite (la API pública de WordPress.com no) | **Sin HTML real verificado**: pruebas con HTML sintético. Hora no única (vie y sáb 8:30 p. m., dom 6:30 p. m.): `start_time` vacío y el horario en la descripción. El parqueo (RD$50/100) no cuenta como precio |
| `recurring` | `agenda/series_recurrentes.json` (curado a mano) | Series semanales, n-ésimo día del mes, fechas sueltas o rangos (exposiciones y festivales), cada una con sus fuentes y fecha de última confirmación | **Sin peticiones a ningún sitio.** Activas: Domingos de Bonyé, 809 Mercado, EUROCINE 2026, Gerard Ellis en Lyle O. Reitzel (inauguración y muestra) y 10 eventos de la guía de letstalkart.rd (7 al 15 oct). Las de temporada quedan `"active": false` hasta que anuncien la próxima edición; una serie sin reconfirmar en 60 días queda para revisión |
| `ticketmax` | ticketmax.org (ticketmax.com.do redirige) | Tarjetas de la portada (`data-city`, `data-venue`, `data-cats`) y JSON-LD `Event` de cada /evento/<id>/ | **Verificado con páginas reales** (7 oct): 68 eventos vigentes, 56 en Santo Domingo. Hora de `startDate` (con zona), precio de `offers` en DOP. Fuera congresos, tours, deportes y TV. Hasta 80 páginas por corrida, primero las nuevas |
| `jazz_en_dominicana` | jazzendominicana.com | Feed Atom de Blogger; parsea la entrada semanal "Jazz en Vivo en RD" (bloques "Jueves 8: … (Ciudad):"), solo Santo Domingo; anuncios sueltos vía IA (opcional) | **Feed verificado con el navegador**; los datos del bloque semanal vienen de texto libre: revisar lugares nuevos (`needs_review`) |

"Verificado" significa que leí las páginas con una herramienta de lectura web que devuelve el contenido
como texto, no el HTML en bruto. Los selectores del código se apoyan en esos textos, no en el marcado.

### Primera corrida real (haz esto primero)

1. `python -m agenda inspect https://zonacolonial.do/actividades/` y lo mismo con
   `https://ccesd.aecid.es/eventos/buscador-de-eventos` y una página `https://teatronacional.gob.do/events/wagner-molina/`.
2. `python -m agenda run`. Si una fuente dice "0 tarjetas" o "no pude extraer fecha", el HTML real difiere
   de lo esperado: los archivos de `inspect/` son lo que hay que mirar para ajustar esa función.
3. Revisa la lista de "necesitan revisión" al final de la corrida.

## Repetidos entre fuentes

La base guarda cada fuente por separado. Al exportar, `agenda/dedupe.py` une los eventos que son la misma
función vista en varias fuentes (mismo día, sede compatible, título parecido y hora a menos de 90 min si ambas
la traen). Los datos salen de la fuente más confiable (`SOURCE_PRIORITY`); la hora y el precio, de la mejor
fuente que los informe. Cada evento de `events.json` lleva `sources` con todas sus fuentes, y la corrida lista
los eventos unidos y los conflictos de hora o precio para revisarlos. Las variantes de nombres de sedes se
agregan en `VENUE_ALIASES`.

## Reglas de cortesía (ya implementadas en `agenda/http.py`)

- Lee y respeta `robots.txt`, incluidos los comodines (`*p_p_id=`). Si no puede leerlo (5xx), omite el sitio.
- Espera entre peticiones al mismo sitio (por fuente; 30 s en el CCE) y reintenta con pausa.
- Solo reprocesa páginas cuyo **texto visible** cambió (huella SHA-1), no el HTML crudo.
- Guarda datos del evento y **siempre el enlace a la fuente**; no copia textos largos ni imágenes.

Notas por sitio: el `robots.txt` del CCE prohíbe `/search`, `/c/`, `/web/guest/` y cualquier URL con
`p_p_id=` o `p_auth=` (la paginación de Liferay suele usarlos), y pide `Crawl-delay: 30` a rastreadores de IA.
Por eso solo se lee la primera página del buscador. El del Teatro Nacional solo cierra `/wp-admin/` y `/feed/`.
El de zonacolonial.do solo cierra `/feed/`. Los términos de uso de cada sitio **no se revisaron**.

## Extracción de respaldo con IA (opcional)

Si un adaptador no logra leer una página, puede pedirle los campos a Claude:

```bash
pip install anthropic
export AGENDA_LLM=1 ANTHROPIC_API_KEY=...   # modelo: AGENDA_LLM_MODEL (por defecto claude-haiku-4-5-20251001)
```

Esos eventos quedan marcados `needs_review`. Sin esas variables, nada se envía a ningún servicio.

## Agregar una fuente

1. Crea `agenda/sources/mi_fuente.py` con una clase que herede de `Source` y defina `id`, `name`, `delay` y `run()`
   (devuelve una lista de `Event`). Usa `self.fetch_page(url)` para obtener `(html, huella, cambió)`.
2. Regístrala en `agenda/sources/__init__.py`.
3. Escribe una prueba con HTML de muestra en `tests/test_sources.py`.

## Automatización

`.github/workflows/scrape.yml` corre a diario, conserva `data/agenda.db` en caché y publica `docs/events.json`.
Define la variable de repositorio `AGENDA_CONTACT`.

## Limitaciones conocidas

- Categorías por palabras clave en zonacolonial (la tarjeta no la trae): "El desencanto (1976)" cae en *Cultura*, no *Cine*.
- `zonacolonial.do` no da hora; el CCE y el Teatro Nacional dan hora solo a veces.
- Los eventos con varias sesiones (CCE) se guardan como un evento con `date`, `end` y `sessions`.
- Instagram, Tix, Boletu, medios y el PDF "Mi Cultura" no están cubiertos todavía.
