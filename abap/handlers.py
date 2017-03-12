import abc
import datetime
import time
import typing
import urllib.parse
import xml.dom.minidom
import xml.etree.cElementTree as ET

import stevedore
import tornado.web

from abap import __version__, abook, const, utils

atom = utils.make_ns_getter(const.ATOM_NS)
itunes = utils.make_ns_getter(const.ITUNES_NS)
psc = utils.make_ns_getter(const.PSC_NS)


def render_chapter(chapter: abook.Chapter):
    return ET.Element(
        psc('chapter'),
        attrib={
            'title': chapter.name,
            'start': f'{chapter.start!s}',
        },
    )


class XMLNamespace(typing.NamedTuple):
    prefix: str
    uri: str


class RenderingPlugin(metaclass=abc.ABCMeta):

    def __init__(self, uri_func: typing.Callable = None):
        self.uri_func = uri_func

    def reverse_uri(self, handler, *args, **kwargs):
        if callable(self.uri_func):
            return self.uri_func(handler, *args, **kwargs)
        else:
            return handler

    @property
    def namespaces(self):
        return []

    @abc.abstractmethod
    def render_abook(self, abook):
        pass

    def render_audiofile(self, abook, audiofile, sequence=0):
        pass


class RSSRenderingPlugin(RenderingPlugin):

    def render_abook(self, abook: abook.Abook):
        generator = ET.Element('generator')
        generator.text = f'abap/{__version__}'
        yield generator

        title = ET.Element('title')
        title.text = abook.title
        yield title

        link = ET.Element('link')
        link.text = self.reverse_uri(None)
        yield link

        if abook.description:
            desc = ET.Element('description')
            desc.text = abook.description
            yield desc

        lang = ET.Element('language')
        lang.text = abook.lang
        yield lang

        if abook.publication_date:
            pub_date = ET.Element('pubDate')
            pub_date.text = time.strftime(
                const.RFC822,
                abook.publication_date.timetuple(),
            )
            yield pub_date

        cover_url = self.reverse_uri('cover', abook.slug)
        image = ET.Element('image')
        ET.SubElement(image, 'url').text = cover_url
        ET.SubElement(image, 'title').text = abook.title
        ET.SubElement(image, 'link').text = self.reverse_uri(None)
        yield image

        if abook._filename:
            dt = datetime.datetime.fromtimestamp(
                abook._filename.stat().st_mtime)
        else:
            dt = datetime.datetime.now()
        build_date = ET.Element('lastBuildDate')
        build_date.text = time.strftime(const.RFC822, dt.timetuple())
        yield build_date

        ttl = ET.Element('ttl')
        ttl.text = str(const.TTL)
        yield ttl

    def render_audiofile(self, abook, audiofile, sequence=0):
        title = ET.Element('title')
        title.text = audiofile.title
        yield title

        guid = ET.Element('guid', attrib={'isPermaLink': 'false'})
        guid.text = str(sequence)
        yield guid

        '''
        pub_date = ET.Element('pubDate')
        pub_date.text = time.strftime(
            const.RFC822,
            (datetime.datetime.now() -
                datetime.timedelta(seconds=sequence)).timetuple()
        )
        yield pub_date

        if i.subtitle:
            ET.SubElement(
                channel, itunes('subtitle')).text = i.subtitle

        if i.summary:
            ET.SubElement(
                channel, itunes('summary')).text = i.summary
        '''

        yield ET.Element('enclosure', attrib={
            'type': audiofile.mimetype,
            'length': str((abook.path / audiofile.path).stat().st_size),
            'url': self.reverse_uri(
                'stream', abook.slug, str(sequence), audiofile.ext),
        })


class AtomRenderingPlugin(RenderingPlugin):

    @property
    def namespaces(self):
        return [
            XMLNamespace('atom', const.ATOM_NS),
        ]

    def render_abook(self, abook):
        icon = ET.Element(atom('icon'))
        icon.text = self.reverse_uri('cover', abook.slug)
        yield icon

        fanart = ET.Element(atom('logo'))
        fanart.text = self.reverse_uri('fanart', abook.slug)
        yield fanart

    def render_audiofile(self, abook, audiofile, sequence: int = 0):
        return
        yield


class ITunesRenderingPlugin(RenderingPlugin):

    @property
    def namespaces(self):
        return [
            XMLNamespace('itunes', const.ITUNES_NS),
        ]

    def render_abook(self, abook):
        author = ET.Element(itunes('author'))
        author.text = ', '.join(abook.authors)
        yield author

        cover_url = self.reverse_uri('cover', abook.slug)
        image = ET.Element(itunes('image'), attrib={'href': cover_url})
        yield image

    def render_audiofile(self, abook, audiofile, sequence: int = 0):
        duration = ET.Element(itunes('duration'))
        duration.text = str(audiofile.duration)
        yield duration

        explicit = ET.Element(itunes('explicit'))
        explicit.text = ('Yes' if audiofile.explicit else 'No')
        yield explicit


class PodloveChapterRenderingPlugin(RenderingPlugin):

    @property
    def namespaces(self):
        return [
            XMLNamespace('psc', const.PSC_NS),
        ]

    def render_abook(self, abook):
        return
        yield

    def render_audiofile(self, abook, audiofile, sequence: int = 0):
        if audiofile.chapters:
            chapters = ET.Element(
                psc('chapters'),
                attrib={
                    'version': const.PSC_VERSION,
                }
            )
            for c in audiofile.chapters:
                chapters.append(render_chapter(c))
            yield chapters


class AbookRenderer(metaclass=abc.ABCMeta):

    def __init__(self, abook: abook.Abook) -> None:
        self.abook = abook

    @abc.abstractmethod
    def dumps(self) -> str:
        pass


class AbookRSSRenderer(AbookRenderer):

    def __init__(self, abook: abook.Abook,
                 url_reverse_func=lambda n, *a: n) -> None:
        super().__init__(abook)
        self.reverse_url = url_reverse_func

    def render(self):
        manager = stevedore.extension.ExtensionManager('abap.rss_renderer')
        extensions = []
        for ext in manager:
            extensions.append(ext.plugin(self.reverse_url))

        for ext in extensions:
            for ns in ext.namespaces:
                ET.register_namespace(ns.prefix, ns.uri)

        rss = ET.Element('rss', attrib={'version': const.RSS_VERSION})
        channel = ET.SubElement(rss, 'channel')

        for ext in extensions:
            for el in ext.render_abook(self.abook):
                channel.append(el)

        for idx, audiofile in enumerate(self.abook, start=1):
            item = ET.SubElement(channel, 'item')
            for ext in extensions:
                for elem in ext.render_audiofile(
                        self.abook, audiofile, sequence=idx):
                    item.append(elem)

        return rss

    def dumps(self) -> str:
        rss = self.render()
        return xml.dom.minidom.parseString(
            ET.tostring(rss, encoding=const.DEFAULT_XML_ENCODING)
        ).toprettyxml(encoding=const.DEFAULT_XML_ENCODING)


class AbookHandler:

    @property
    def bundle(self) -> abook.Abook:
        return self.application.bundle

    def slug_exists(self, slug: str) -> bool:
        return self.bundle.slug == slug

    def assert_slug(self, slug: str):
        if not self.slug_exists(slug):
            raise tornado.web.HTTPError(status_code=400)


class StreamHandler(tornado.web.StaticFileHandler, AbookHandler):

    def head(self, slug: str, sequence: str, ext: str):
        return self.get(slug, sequence, ext, include_body=False)

    def get(self, slug: str, sequence: str, ext: str,
            include_body: bool = True):
        self.assert_slug(slug)

        try:
            artifact = self.bundle[int(sequence) - 1]
        except ValueError:
            raise tornado.web.HTTPError(status_code=400)
        except IndexError:
            raise tornado.web.HTTPError(status_code=404)

        self.set_header('Content-Type', artifact.mimetype)
        return super().get(artifact.path, include_body=include_body)


class CoverHandler(tornado.web.StaticFileHandler, AbookHandler):

    def slug_exists(self, slug):
        return super().slug_exists(slug) and self.bundle.has_cover

    def get(self, slug: str):
        self.assert_slug(slug)
        cover = utils.first_of(self.bundle.covers)
        self.set_header('Content-Type', cover.mimetype)
        return super().get(cover.path)


class FanartHandler(tornado.web.StaticFileHandler, AbookHandler):

    def slug_exists(self, slug):
        return super().slug_exists(slug) and self.bundle.has_fanart

    def get(self, slug: str):
        self.assert_slug(slug)
        fanart = utils.first_of(self.bundle.fanarts)
        self.set_header('Content-Type', fanart.mimetype)
        return super().get(fanart.path)


class RSSHandler(tornado.web.RequestHandler, AbookHandler):

    def get(self, slug: str):
        self.assert_slug(slug)

        self.set_header(
            'Content-Type',
            f'application/rss+xml; charset="{const.DEFAULT_XML_ENCODING}"'
        )

        def make_url_reverse(reverse_func, base_url):

            def url_reverse(endpoint, *args, **kwargs):
                if endpoint:
                    return urllib.parse.urljoin(
                        base_url, reverse_func(endpoint, *args, **kwargs)
                    )
                else:
                    return base_url

            return url_reverse

        base_url = f'{self.request.protocol}://{self.request.host}'
        reverse_func = make_url_reverse(self.reverse_url, base_url)
        renderer = AbookRSSRenderer(
            self.bundle,
            url_reverse_func=reverse_func,
        )
        self.write(renderer.dumps())
