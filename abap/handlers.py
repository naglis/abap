import datetime
import time
import urllib.parse
import xml.dom.minidom
import xml.etree.cElementTree as ET

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


class AbookRSSRenderer(object):

    def __init__(self, abook: abook.Abook, base_url: str,
                 url_reverse_func=lambda n, *a: n) -> None:
        self.abook = abook
        self.base_url = base_url
        self.reverse_url = url_reverse_func

    def render_audiofile(self, audiofile: abook.Audiofile, sequence: int = 0,
                         when: datetime.datetime = datetime.datetime.now()):
        item = ET.Element('item')

        ET.SubElement(item, 'title').text = audiofile.title
        ET.SubElement(
            item, 'guid', attrib={'isPermaLink': 'false'}
        ).text = str(sequence)
        ET.SubElement(item, 'pubDate').text = time.strftime(
            const.RFC822,
            (when - datetime.timedelta(seconds=sequence)).timetuple()
        )
        ET.SubElement(item, itunes('duration')).text = str(audiofile.duration)

        ET.SubElement(item, itunes('explicit')).text = (
            'Yes' if audiofile.explicit else 'No')

        '''
        if i.subtitle:
            ET.SubElement(
                channel, itunes('subtitle')).text = i.subtitle

        if i.summary:
            ET.SubElement(
                channel, itunes('summary')).text = i.summary
        '''

        ET.SubElement(item, 'enclosure', attrib={
            'type': audiofile.mimetype,
            'length': str((self.abook.path / audiofile.path).stat().st_size),
            'url': urllib.parse.urljoin(
                self.base_url, self.reverse_url(
                    'stream', self.abook.slug, str(sequence), audiofile.ext),
            ),
        })

        if audiofile.chapters:
            chapters_elem = ET.SubElement(
                item,
                psc('chapters'),
                attrib={
                    'version': const.PSC_VERSION,
                }
            )
            for c in audiofile.chapters:
                chapters_elem.append(render_chapter(c))
        return item

    def render(self):
        cover_url = urllib.parse.urljoin(
            self.base_url, self.reverse_url('cover', self.abook.slug))
        fanart_url = urllib.parse.urljoin(
            self.base_url, self.reverse_url('fanart', self.abook.slug))

        for ns_name, ns_url in const.NAMESPACES.items():
            ET.register_namespace(ns_name, ns_url)

        rss = ET.Element('rss', attrib={'version': const.RSS_VERSION})
        channel = ET.SubElement(rss, 'channel')

        ET.SubElement(channel, 'generator').text = f'abap/{__version__}'
        ET.SubElement(channel, 'title').text = self.abook.title
        ET.SubElement(channel, 'link').text = self.base_url
        if self.abook.description:
            ET.SubElement(channel, 'description').text = self.abook.description
        ET.SubElement(channel, 'language').text = self.abook.lang
        ET.SubElement(channel, 'ttl').text = str(const.TTL)
        '''
        ET.SubElement(channel, 'lastBuildDate').text = time.strftime(
            RFC822, audiobook.pub_date.timetuple())
        '''
        ET.SubElement(channel, atom('icon')).text = cover_url
        ET.SubElement(channel, atom('logo')).text = fanart_url
        ET.SubElement(channel, itunes('author')).text = ', '.join(
            self.abook.authors)
        ET.SubElement(channel, itunes('image'), attrib={'href': cover_url})

        image = ET.SubElement(channel, 'image')
        ET.SubElement(image, 'url').text = cover_url
        ET.SubElement(image, 'title').text = self.abook.title
        ET.SubElement(image, 'link').text = self.base_url

        now = datetime.datetime.now()
        for idx, audiofile in enumerate(self.abook, start=1):
            channel.append(
                self.render_audiofile(audiofile, sequence=idx, when=now)
            )

        return rss

    def dumps(self) -> str:
        rss = self.render()
        return xml.dom.minidom.parseString(
            ET.tostring(rss, encoding='utf-8')).toprettyxml()


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

        self.set_header('Content-Type', 'application/rss+xml; charset="utf-8"')

        base_url = f'{self.request.protocol}://{self.request.host}'
        renderer = AbookRSSRenderer(
            self.bundle,
            base_url,
            url_reverse_func=self.reverse_url,
        )
        self.write(renderer.dumps())
