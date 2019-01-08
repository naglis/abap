
ABAP_VERSION = '0.1.1a'
RSS_VERSION = '2.0'
PSC_VERSION = '1.2'
RFC822 = '%a, %d %b %Y %H:%M:%S +0000'
ITUNES_NAMESPACE = 'http://www.itunes.com/dtds/podcast-1.0.dtd'
PSC_NAMESPACE = 'http://podlove.org/simple-chapters'

# Our default time-to-live of RSS feeds (in minutes).
DEFAULT_TTL = 60 * 24 * 365

DEFAULT_XML_ENCODING = 'utf-8'
DEFAULT_PORT = 8000
MANIFEST_FILENAME = 'abap.yaml'

AUDIO_EXTENSIONS = (
    'm4a',
    'm4b',
    'mp3',
    'ogg',
    'opus',
    'flac',
)
IMAGE_EXTENSIONS = (
    'jpeg',
    'jpg',
    'png',
)
COVER_FILENAMES = (
    'cover',
    'cover_art',
    'folder',
)
