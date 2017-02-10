import datetime
import time
import urllib.parse
import xml.dom.minidom
import xml.etree.cElementTree as ET

import tornado.web

from abap import const, utils


def render_chapter(chapter):
    return ET.Element(
        utils.ns(const.PSC_NS, 'chapter'),
        attrib={
            'title': chapter.name,
            'start': f'{chapter.start!s}',
        },
    )


class AbookRSSRenderer(object):

    def __init__(self, abook, base_url, url_reverse_func=lambda n, *a: n):
        self.abook = abook
        self.base_url = base_url
        self.reverse_url = url_reverse_func

    def render_audiofile(self, audiofile, sequence=0,
                         when=datetime.datetime.now()):
        item = ET.Element('item')

        ET.SubElement(item, 'title').text = audiofile.title
        ET.SubElement(
            item, 'guid', attrib={'isPermaLink': 'false'}
        ).text = f'{sequence}'
        ET.SubElement(item, 'pubDate').text = time.strftime(
            const.RFC822,
            (when - datetime.timedelta(seconds=sequence)).timetuple()
        )
        ET.SubElement(
            item, utils.ns(const.ITUNES_NS, 'duration')
        ).text = f'{audiofile.duration}'

        ET.SubElement(item, utils.ns(const.ITUNES_NS, 'explicit')).text = (
            'Yes' if audiofile.explicit else 'No')

        '''
        if i.subtitle:
            ET.SubElement(
                channel, ns(ITUNES_NS, 'subtitle')).text = i.subtitle

        if i.summary:
            ET.SubElement(
                channel, ns(ITUNES_NS, 'summary')).text = i.summary
        '''

        ET.SubElement(item, 'enclosure', attrib={
            'type': audiofile.mimetype,
            'length': str((self.abook.path / audiofile.path).stat().st_size),
            'url': urllib.parse.urljoin(
                self.base_url, self.reverse_url(
                    'stream', self.abook.slug, f'{sequence}', audiofile.ext),
            ),
        })

        if audiofile.chapters:
            chapters_elem = ET.SubElement(
                item,
                utils.ns(const.PSC_NS, 'chapters'),
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

        ET.SubElement(channel, 'title').text = self.abook.title
        ET.SubElement(channel, 'link').text = self.base_url
        if self.abook.description:
            ET.SubElement(channel, 'description').text = self.abook.description
        ET.SubElement(channel, 'language').text = self.abook.lang
        ET.SubElement(channel, 'ttl').text = f'{const.TTL}'
        '''
        ET.SubElement(channel, 'lastBuildDate').text = time.strftime(
            RFC822, audiobook.pub_date.timetuple())
        '''
        ET.SubElement(
            channel, utils.ns(const.ATOM_NS, 'icon')).text = cover_url
        ET.SubElement(
            channel, utils.ns(const.ATOM_NS, 'logo')).text = fanart_url
        ET.SubElement(
            channel, utils.ns(const.ITUNES_NS, 'author')).text = ', '.join(
                self.abook.authors)
        ET.SubElement(
            channel, utils.ns(const.ITUNES_NS, 'image'), attrib={
                'href': cover_url})

        image = ET.SubElement(channel, 'image')
        ET.SubElement(image, 'url').text = cover_url
        ET.SubElement(image, 'title').text = self.abook.title
        ET.SubElement(image, 'link').text = self.base_url

        now = datetime.datetime.now()
        for idx, audiofile in enumerate(self.abook):
            channel.append(
                self.render_audiofile(audiofile, sequence=idx, when=now)
            )

        return rss

    def dumps(self):
        rss = self.render()
        return xml.dom.minidom.parseString(
            ET.tostring(rss, encoding='utf-8')).toprettyxml()


class StreamHandler(tornado.web.StaticFileHandler):

    def head(self, slug, sequence, ext):
        return self.get(slug, sequence, ext, include_body=False)

    def get(self, slug, sequence, ext, include_body=True):
        bundle = self.application.bundle
        if not bundle.slug == slug:
            raise tornado.web.HTTPError(status_code=404)

        try:
            artifact = bundle[int(sequence)]
        except IndexError:
            raise tornado.web.HTTPError(status_code=404)

        self.set_header('Content-Type', artifact.mimetype)
        return super().get(artifact.path, include_body=include_body)


class CoverHandler(tornado.web.StaticFileHandler):

    def get(self, slug):
        bundle = self.application.bundle
        if not (bundle.slug == slug and bundle.has_cover):
            raise tornado.web.HTTPError(status_code=404)
        else:
            cover = utils.first_of(bundle.covers)
        self.set_header('Content-Type', cover.mimetype)
        return super().get(cover.path)


class FanartHandler(tornado.web.StaticFileHandler):

    def get(self, slug):
        bundle = self.application.bundle
        if not (bundle.slug == slug and bundle.has_fanart):
            raise tornado.web.HTTPError(status_code=404)
        else:
            fanart = utils.first_of(bundle.fanarts)
        self.set_header('Content-Type', fanart.mimetype)
        return super().get(fanart.path)


class RSSHandler(tornado.web.RequestHandler):

    def get(self, slug):
        bundle = self.application.bundle
        if not bundle.slug == slug:
            raise tornado.web.HTTPError(status_code=404)

        self.set_header('Content-Type', 'application/rss+xml; charset="utf-8"')

        base_url = f'{self.request.protocol}://{self.request.host}'
        renderer = AbookRSSRenderer(
            bundle,
            base_url,
            url_reverse_func=self.reverse_url,
        )
        self.write(renderer.dumps())
