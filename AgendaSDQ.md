# Agenda SDQ

Agenda cultural de Santo Domingo: música, cultura y planes gratis, en un solo lugar y actualizada cada día.
Proyecto personal de Edwin.

Este archivo es el punto de partida de cualquier sesión de Claude (claude.ai, claude.ai/code o Claude Code).
Léelo antes de tocar código o documentos del proyecto.

## Dónde vive cada cosa

| Qué | Dónde |
|---|---|
| Código (fuente de verdad) | https://github.com/edwingenao/agenda-sdq, rama `main` |
| Sitio publicado | https://edwingenao.github.io/agenda-sdq/ (GitHub Pages, carpeta `docs/`) |
| Datos que lee el sitio | `docs/events.json`, lo regenera el workflow diario |
| Decisiones e investigación | Documentos de Claude Docs (abajo) |

Documentos de Claude Docs:

- [Fuentes de la Agenda Cultural de Santo Domingo](https://claude.ai/artifact/Xu1Bo35kqWsjBUwhwUDY9M): todas las fuentes investigadas.
- [Primeras fuentes de eventos](https://claude.ai/artifact/1jqHEPHtNUVRvWGca6PMEh): pruebas de cada fuente.
- [Campos de cada evento](https://claude.ai/artifact/TJCe65gpmhnFhcrK3sLjBC): qué datos lleva un evento y sus reglas.
- [Esquema de base de datos](https://claude.ai/artifact/JWnFzEmJeU2tSd1WbZ9RQi): diseño de la base (el código actual usa una versión más simple, ver abajo).
- [Agenda SDQ (prototipo)](https://claude.ai/artifact/D54A6wtApPGoduUJjNtw8P) y dos lienzos de diseño: origen del diseño de `docs/index.html`.

Si un documento y el código no coinciden, manda el código; actualiza el documento o anota la diferencia aquí.

## Cómo funciona

1. **Scraper** (`agenda/`, Python): un adaptador por fuente en `agenda/sources/`. Cada uno devuelve `Event`
   (`agenda/models.py`). `python -m agenda run` lee todas las fuentes y guarda cada una por separado en SQLite
   (`data/agenda.db`, no se versiona).
2. **Exportación** (`agenda/export.py`): toma los eventos próximos, une los repetidos entre fuentes
   (`agenda/dedupe.py`) y escribe `docs/events.json`.
3. **Workflow** (`.github/workflows/scrape.yml`): corre a diario a las 6:17 a. m. de Santo Domingo y publica
   `events.json`. Necesita la variable de repositorio `AGENDA_CONTACT` (ya definida).
4. **Sitio** (`docs/index.html`): una sola página sin dependencias que carga `events.json`. Pantallas Bienvenida, Hoy,
   Calendario, Guardados y detalle.

## Fuentes

| id | Fuente | Estado |
|---|---|---|
| `teatro_nacional` | Teatro Nacional Eduardo Brito | Activa. Su página no publica la hora |
| `casa_de_teatro` | Casa de Teatro (API JSON) | Activa, pero su API suele venir vacía |
| `sic` | Ministerio de Cultura, SIC-RD (API pública) | Activa. Todo gratis; a veces pasa semanas sin eventos futuros |
| `centro_leon` | Centro León | Activa, pero casi todo es en Santiago: aporta solo lo de la extensión en Calle Las Damas |
| `zona_colonial` | zonacolonial.do | **En pausa**: responde 403 a los servidores de GitHub. Desde una PC funciona |
| `cce` | Centro Cultural de España | Activa. Solo la página 1 del buscador (robots.txt), 30 s entre peticiones |
| `jazz_en_dominicana` | Jazz en Dominicana (feed Atom) | Activa. Solo Santo Domingo |
| `teatro_las_mascaras` | Teatro Las Máscaras (portada del sitio) | Nueva, sin HTML real verificado: lee el texto de la portada (fechas, precio de la boleta, enlace a tix.do). Sin hora única: viernes y sábado 8:30 p. m., domingo 6:30 p. m. (va en la descripción) |
| — | Artsy, muestras de Santo Domingo (artsy.net/shows/santo-domingo-dominican-republic) | Sin adaptador: solo lista 2 galerías (Lyle O. Reitzel y ASR Galería), unas 3 muestras al mes. Se cargan a mano como series con `range` (ASR Galería: Interconexión y ARQUIONIRIAS). Volver a mirar cuando abra una muestra |
| `recurring` | Series curadas a mano (`agenda/series_recurrentes.json`) | Activa: Domingos de Bonyé, 809 Mercado, EUROCINE 2026, Gerard Ellis en Lyle O. Reitzel (inauguración y muestra) 10 eventos de la guía de letstalkart.rd (7 al 15 oct) y 2 muestras de ASR Galería. Para agregar o reconfirmar una serie se edita ese archivo (instrucciones dentro). Admite semanal, n-ésimo día del mes, fechas sueltas y rangos (`range`, con "Hasta") |

El orden de confianza para unir repetidos está en `SOURCE_PRIORITY` (`agenda/dedupe.py`).

## Reglas del producto

- **Solo Santo Domingo.** Lo de otras ciudades se descarta. Si no se sabe dónde es, se publica marcado para revisión
  o no se publica, según la fuente.
- **Nunca inventar una hora.** Si la fuente no la da, `start_time` queda vacío y el sitio dice "Hora por confirmar".
- **Precio honesto.** Gratis solo si la fuente lo dice. Precio vacío o dudoso = "por confirmar", nunca gratis.
  Excepciones confirmadas por Edwin el 7 de octubre de 2026 (la fuente no trae precio): los cursos de Formación del CCE,
  las exposiciones en galerías (series curadas) y Fiesta Sunset Jazz ("No cover!" en la barra lateral del blog) son gratis.
- **Fechas en hora de Santo Domingo** (UTC-4, sin cambio de horario). Las fuentes en UTC se convierten.
- **Rangos sin sesiones** (una obra del 9 al 18) salen una sola vez con "Hasta": no se inventan días de función.
- **Siempre el enlace a la fuente original.** No se copian textos largos (descripción hasta ~280 caracteres) ni imágenes.
- **Cortesía con los sitios.** Respetar robots.txt y las pausas. Si un sitio bloquea (como zonacolonial.do), no se
  esquiva con otro navegador falso ni con proxies: se pide permiso o se busca otra vía.
- **Muestras sin datos personales.** Los archivos de `samples/` van sin correos, teléfonos ni URLs firmadas.

### Categorías

- El scraper asigna **una** categoría por evento: Música, Teatro, Danza, Arte, Cine o Cultura (por defecto), con las
  reglas de `normalize_category` en `agenda/models.py`.
- El sitio muestra los chips **Música, Teatro y danza, Arte, Gastronomía y Cultura**. Teatro y Danza se juntan; Cine y
  Literatura van dentro de Cultura.
- Pendiente: el documento "Campos de cada evento" permite hasta **2** categorías, pero el modelo guarda solo una.
- Gastronomía solo tiene, por ahora, eventos de las series curadas (809 Mercado).

## Cómo trabajar

- **GitHub es la única fuente de verdad del código.** Empieza actualizando desde `main` y termina con commit y push,
  o con un pull request si el cambio necesita revisión.
- **Código nuevo, contra el código del repo.** Un adaptador usa `agenda.models.Event`, hereda de `Source` y pide las
  páginas con `self.fetcher` (respeta robots.txt, espera entre peticiones y se identifica con `AGENDA_CONTACT`).
  Nada de modelos provisionales ni `urllib` directo.
- **Pruebas:** `pytest` (todas offline). Todo cambio lleva sus pruebas; una fuente nueva lleva una muestra real en
  `samples/`.
- **Ver el sitio en local:** `python -m http.server 8765 --directory docs` y abrir http://localhost:8765.
- **Mensajes de commit** en español, explicando el porqué.

### Agregar una fuente

1. Verifica la fuente a mano: robots.txt, formato, si trae hora y precio, y si es en Santo Domingo.
2. Crea `agenda/sources/<id>.py` con una clase `Source` (`id`, `name`, `delay`, `run()`), con un docstring que diga
   qué se verificó y cuándo.
3. Regístrala en `agenda/sources/__init__.py` y agrégala a `SOURCE_PRIORITY` en `agenda/dedupe.py`.
4. Guarda una respuesta real, sin datos personales, en `samples/` y escribe `tests/test_<id>.py`.
5. Agrega la fila en la tabla de fuentes del `README.md` y en la de este archivo.

## Pendientes

- zonacolonial.do: escribirles para pedir acceso desde GitHub, o leerla desde una PC y subir el resultado.
- Hasta 2 categorías por evento (modelo, exportación y filtros del sitio).
- Fuentes sin integrar: Quinta Dominica (solo boletín por correo; hace falta un correo del proyecto), PDF "Mi Cultura"
  del Ministerio, Museos RD, Cinemateca (programas fijos, carga manual), Centro Cultural Banreservas (página vacía),
  galerías, ticketeras y medios.
- Fuentes de Gastronomía que publiquen con regularidad.
- Reconfirmar las series curadas antes de que venzan (60 días sin confirmar las marca para revisión) y activar las de temporada cuando anuncien fechas.
- La hora de los eventos del Teatro Nacional (su página no la publica).

## Fuentes revisadas que no se integran todavía

Revisadas desde la PC el 6 de octubre de 2026. Antes de volver a probarlas, lee la nota.

| Fuente | Qué se encontró | Qué hacer |
|---|---|---|
| Teatro Guloya (teatroguloya.com) | App de Base44 con API pública sin autenticación en su mismo dominio: `/api/apps/6aab0bddff1e87a2bfb25e50/entities/Show?q={"status":"cartelera"}` (obras) y `/entities/Function?q={"status":"activa"}` (funciones: `starts_at` en UTC, `ticket_types` con precio, `capacity`). No tiene robots.txt. Los datos son de prueba: una obra con descripción de relleno, precio RD$1 y una función ya pasada (20 sep); las noticias citan montajes que no están en la cartelera | Volver a mirar cuando carguen la temporada real. El adaptador sería corto: unir `Function` con su `Show` por `show_id` |
| Feed de DGCINE (dgcine.gob.do/feed/) | Feed RSS con unas 10 notas; casi todas son institucionales (convenios, convocatorias, festivales fuera). Ese día solo 2 eran eventos: EUROCINE 2026 (26 oct al 1 nov, Caribbean Cinemas Galería 360, 15 películas, sin precio) y una exposición de la Cinemateca | Muy poco volumen para un adaptador. Cargar EUROCINE a mano en las series curadas, o leerlo junto con las agendas de prensa cuando haya extracción con IA |
| Biblioteca Nacional (bnphu.gob.do, eventos.bnphu.gob.do) | `eventos.bnphu.gob.do` prohíbe todo en robots.txt (`Disallow: /`). `bnphu.gob.do` responde con la verificación anti-bots de Cloudflare ("Just a moment…"), también en su API de WordPress | No se lee de forma automática ni se esquiva el bloqueo. Pedirles la programación o cargarla a mano |

### Guía de letstalkart.rd (Instagram), revisada el 7 de octubre de 2026

Carrusel mensual "Agenda cultural" con eventos, talleres y convocatorias, desde una captura de pantalla (no se
lee de forma automática). Los 5 eventos que ya teníamos por otras fuentes (Wagner/Molina, Sandy Gabriel, 3 x Todas las
canciones, Rojo, Retro Jazz) coinciden en fecha y lugar. Marca "Santiago" los eventos de esa ciudad y se descartaron.
Se cargaron a mano como series curadas los que faltaban. Se dejaron fuera las clases y talleres de pago, los cursos
virtuales y las convocatorias (concursos con fecha límite): no son eventos para asistir.

| Fuente | Qué se encontró | Qué hacer |
|---|---|---|
| letstalkart.rd y las cuentas de Instagram de cada organizador | Instagram no se lee de forma automática. La guía se marca "AI content" y no tiene sitio ni feed | Seguir cargando a mano desde capturas, o leer las mismas fechas en una fuente web (las de abajo) |
| Acento Cultural (acento.com.do) | Agenda semanal en la web. robots.txt no prohíbe nada y publica sitemaps | La mejor candidata: cubre lo mismo que la guía y sí es texto. Necesita extracción con IA (`agenda/llm.py`) y `needs_review` |
| Ticketmax (ticketmax.org) | Revisado el 7 oct desde la PC: es la ticketera dominicana ("Boletos para eventos en República Dominicana"; sedes como Casa de Teatro y Hard Rock Cafe Santo Domingo). WordPress + WooCommerce; robots.txt solo bloquea `/wp-admin/` y pide 10 s a los bots de Meta. Cada evento (`/evento/<id>/`) trae JSON-LD `Event` con `startDate` con zona (-04:00), `offers` en DOP (`lowPrice`/`highPrice`) y `location` con `addressLocality`. 174 productos en `wp-sitemap-posts-product-1.xml` (incluye viejos) | **La mejor candidata siguiente**: adaptador corto leyendo el JSON-LD de cada evento desde el sitemap, filtrando por ciudad Santo Domingo y fecha futura |
| UEPA Tickets (uepatickets.com) | Sí existe (el Teatro Nacional enlaza a `uepatickets.com/tickets/...`), pero responde 403 con la verificación anti-bots de Cloudflare (`cf-mitigated: challenge`), también en las páginas de evento | No se lee ni se esquiva. Sus eventos de teatro suelen llegar por el Teatro Nacional |
| Fundación Sinfonía (sinfonia.org.do) | Revisado el 7 oct: tiene agenda (`/agenda/<slug>/`, `evento-sitemap.xml` con 40 eventos en total, uno o dos al mes). Sin JSON-LD de evento, pero el texto trae fecha y **hora** ("4 de noviembre de 2026, 8:30 p.m."), sala y precios por zona. Sus conciertos (Orquesta Sinfónica Nacional) suelen ser en el Teatro Nacional | Poco volumen, pero útil: aporta la hora y el precio que le faltan al Teatro Nacional; al unir repetidos gana la hora. Adaptador corto por sitemap |
| Teatro Guloya | Su cuenta anuncia "Sola" (4 oct) y "Liborio" (9 al 11 oct). Revisada otra vez el 7 oct: la API sigue con los mismos datos de prueba (Liborio con descripción de relleno, precio RD$1 y una función del 20 sep; sin cambios desde el 19 sep) | No hay adaptador todavía: se mantiene la serie curada `liborio-teatro-guloya-2026-10`. Volver a mirar cuando la boletería tenga funciones de octubre |
| Bellas Artes, DEFAE, ENAD, Cinemateca, Galería 360, The Green Room, Club Arroyo Hondo | Solo publican en Instagram (o su sitio bloquea lectura automática) | Carga manual; `jazz_en_dominicana` ya cubre parte de The Green Room, pero no todo (faltó Omar Quezada, 7 oct) |

Quedan por confirmar: la hora y el precio de casi todos los eventos cargados de esta guía (la columna "confirmar" del sitio
los marca), y que Velvet Room, Hard Rock Cafe y el Auditorio Patrick N. Hughson estén en Santo Domingo.

### Artsy, muestras de Santo Domingo (artsy.net/shows/santo-domingo-dominican-republic), revisada el 7 de octubre de 2026

Solo lista dos galerías: Lyle O. Reitzel y ASR Galería (esta es la "ARS" que se había supuesto). Trae título, galería y fechas,
sin año, dirección, horario ni precio; las cerradas salen sin fechas. robots.txt no prohíbe `/shows/` y publica `sitemap-shows.xml`;
no se revisaron sus términos de uso. Con unas 3 muestras al mes no justifica un adaptador: se cargan como series curadas con `range`
(Interconexión y ARQUIONIRIAS, de ASR Galería, quedaron cargadas). Volver a mirar la página cuando abra una muestra nueva.


### Noticias del Ministerio de Cultura (cultura.gob.do/noticias), revisadas el 7 de octubre de 2026

Sitio WordPress con feed RSS 2.0 (`/feed/`), `sitemap_index.xml` y un robots.txt sin ninguna prohibición. Las notas son comunicados de prensa
casi todos posteriores al hecho: las 16 más recientes (1 al 4 de oct) hablan de la Feria Internacional del Libro, que ya cerró el 4 de oct.
No traen calendario de eventos y los datos de fecha, hora, lugar y precio van dentro del texto. Solo una nota anuncia algo futuro
(la FILSD 2027, del 12 al 26 de septiembre de 2027, sin precio). Los eventos propios del Ministerio ya entran por `sic`.
No justifica un adaptador por ahora: rinde poco y repetiría `sic`. Útil como confirmación a mano y para series de temporada (FILSD, cuando
anuncien las fechas de 2027).

### Ayuntamiento del Distrito Nacional (adn.gob.do), revisado el 7 de octubre de 2026

WordPress con feed RSS 2.0 (`/feed/`), `wp-sitemap.xml` y un robots.txt que solo bloquea `/wp-admin/`. No tiene agenda ni calendario: el mapa del sitio
solo trae noticias, una página de Cultura que describe la Ciudad Colonial y secciones institucionales. Las 10 notas más recientes (19 sep al 7 oct) son
sobre obras, operativos de limpieza y actos de la alcaldesa; ninguna anuncia un evento con fecha futura. No se integra. Sirve como confirmación
a mano si una actividad municipal aparece en otra fuente.
