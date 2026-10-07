from agenda.sources.casa_de_teatro import CasaDeTeatro
from agenda.sources.cce import CentroCulturalEspana
from agenda.sources.jazz_en_dominicana import JazzEnDominicana
from agenda.sources.sic import MinisterioCulturaSIC
from agenda.sources.teatro_nacional import TeatroNacional
from agenda.sources.zona_colonial import ZonaColonial

SOURCES = {cls.id: cls for cls in (TeatroNacional, ZonaColonial, CentroCulturalEspana, CasaDeTeatro, JazzEnDominicana, MinisterioCulturaSIC)}
