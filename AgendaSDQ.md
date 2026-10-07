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
4. **Sitio** (`docs/index.html`): una sola página sin dependencias que carga `events.json`. Pantallas Hoy,
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

El orden de confianza para unir repetidos está en `SOURCE_PRIORITY` (`agenda/dedupe.py`).

## Reglas del producto

- **Solo Santo Domingo.** Lo de otras ciudades se descarta. Si no se sabe dónde es, se publica marcado para revisión
  o no se publica, según la fuente.
- **Nunca inventar una hora.** Si la fuente no la da, `start_time` queda vacío y el sitio dice "Hora por confirmar".
- **Precio honesto.** Gratis solo si la fuente lo dice. Precio vacío o dudoso = "por confirmar", nunca gratis.
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
- Gastronomía todavía no tiene ninguna fuente.

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
- Fuentes de Gastronomía.
- La hora de los eventos del Teatro Nacional (su página no la publica).
