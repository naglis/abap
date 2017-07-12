POS_SYMBOLS = frozenset(':0123456789')
RFC822 = '%a, %d %b %Y %H:%M:%S +0000'
ITUNES_NS = 'http://www.itunes.com/dtds/podcast-1.0.dtd'
ATOM_NS = 'http://www.w3.org/2005/Atom'
PSC_NS = 'http://podlove.org/simple-chapters'
NAMESPACES = {
    'atom': ATOM_NS,
    'itunes': ITUNES_NS,
    'psc': PSC_NS,
}
RSS_VERSION = '2.0'
PSC_VERSION = '1.2'
DEFAULT_LANG_CODE = 'en-us'
DEFAULT_XML_ENCODING = 'utf-8'

IMAGE_EXTENSIONS = ('jpg', 'jpeg', 'png')
AUDIO_EXTENSIONS = ('mp3', 'ogg', 'm4a', 'm4b', 'opus')
COVER_FILENAMES = (r'cover', r'folder', r'cover[\s_-]?art')
FANART_FILENAMES = (r'fan[\s_-]?art',)
IGNORE_FILENAME = b'.abap_ignore'

DURATION_RE = r'^([0-9]{2,}):([0-5][0-9]):([0-5][0-9])(\.([0-9]{3}))?$'

# Our default time-to-live of RSS feeds (in minutes).
TTL = 60 * 24 * 365

MANIFEST_FILENAME = 'manifest.abook'
