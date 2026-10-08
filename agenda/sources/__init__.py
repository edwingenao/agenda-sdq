from agenda.sources.casa_de_teatro import CasaDeTeatro
from agenda.sources.cce import CentroCulturalEspana
from agenda.sources.centro_leon import CentroLeon
from agenda.sources.jazz_en_dominicana import JazzEnDominicana
from agenda.sources.recurring import SeriesRecurrentes
from agenda.sources.sic import MinisterioCulturaSIC
from agenda.sources.teatro_las_mascaras import TeatroLasMascaras
from agenda.sources.teatro_nacional import TeatroNacional
from agenda.sources.tix import Tix
from agenda.sources.zona_colonial import ZonaColonial

SOURCES = {cls.id: cls for cls in (TeatroNacional, ZonaColonial, CentroCulturalEspana, CasaDeTeatro, JazzEnDominicana, MinisterioCulturaSIC, CentroLeon, SeriesRecurrentes, TeatroLasMascaras, Tix)}
