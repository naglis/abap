
RFC822 = '%a, %d %b %Y %H:%M:%S +0000'
ITUNES_NS = 'http://www.itunes.com/dtds/podcast-1.0.dtd'
ATOM_NS = 'http://www.w3.org/2005/Atom'

IMAGE_EXTENSIONS = ('jpg', 'jpeg', 'png')
AUDIO_EXTENSIONS = ('mp3', 'ogg', 'm4a', 'm4b', 'opus')
COVER_FILENAMES = (r'cover', r'folder', r'cover[\s_-]?art')
FANART_FILENAMES = (r'fan[\s_-]?art',)
IGNORE_FILENAME = b'.ausis_ignore'

# Our default time-to-live of RSS feeds (in minutes).
TTL = 60 * 24 * 365
