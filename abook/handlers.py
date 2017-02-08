import datetime
import os
import time
import urllib.parse
import xml.dom.minidom
import xml.etree.cElementTree as ET

import tornado.web

from abook import const, utils


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
            raise tornado.web.HTTPError(404)
        else:
            cover = utils.first_of(bundle.covers)
        self.set_header('Content-Type', cover.mimetype)
        return super().get(cover.path)


class FanartHandler(tornado.web.StaticFileHandler):

    def get(self, slug):
        bundle = self.application.bundle
        if not (bundle.slug == slug and bundle.has_fanart):
            raise tornado.web.HTTPError(404)
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
        cover_url = urllib.parse.urljoin(
            base_url, self.reverse_url('cover', bundle.slug))
        fanart_url = urllib.parse.urljoin(
            base_url, self.reverse_url('fanart', bundle.slug))

        ET.register_namespace('itunes', const.ITUNES_NS)
        ET.register_namespace('atom', const.ATOM_NS)

        rss = ET.Element('rss', attrib={'version': '2.0'})
        channel = ET.SubElement(rss, 'channel')

        ET.SubElement(channel, 'title').text = bundle.title
        ET.SubElement(channel, 'link').text = base_url
        if bundle.description:
            ET.SubElement(channel, 'description').text = bundle.description
        ET.SubElement(channel, 'language').text = bundle.lang
        ET.SubElement(channel, 'ttl').text = str(const.TTL)
        '''
        ET.SubElement(channel, 'lastBuildDate').text = time.strftime(
            RFC822, audiobook.pub_date.timetuple())
        '''
        ET.SubElement(channel, utils.ns(const.ATOM_NS, 'icon')).text = cover_url
        ET.SubElement(channel, utils.ns(const.ATOM_NS, 'logo')).text = fanart_url
        ET.SubElement(channel, utils.ns(const.ITUNES_NS, 'author')).text = ', '.join(bundle.authors)
        ET.SubElement(
            channel, utils.ns(const.ITUNES_NS, 'image'), attrib={'href': cover_url})

        image = ET.SubElement(channel, 'image')
        ET.SubElement(image, 'url').text = cover_url
        ET.SubElement(image, 'title').text = bundle.title
        ET.SubElement(image, 'link').text = base_url

        now = datetime.datetime.now()
        for idx, a in enumerate(bundle):
            item = ET.SubElement(channel, 'item')

            ET.SubElement(item, 'title').text = a.title
            ET.SubElement(
                item, 'guid', attrib={'isPermaLink': 'false'}
            ).text = str(idx)
            ET.SubElement(item, 'pubDate').text = time.strftime(
                const.RFC822,
                (now - datetime.timedelta(seconds=idx)).timetuple()
            )
            ET.SubElement(
                item, utils.ns(const.ITUNES_NS, 'duration')
            ).text = str(a.duration)

            ET.SubElement(item, utils.ns(const.ITUNES_NS, 'explicit')).text = (
                'Yes' if a.explicit else 'No')

            '''
            if i.subtitle:
                ET.SubElement(
                    channel, ns(ITUNES_NS, 'subtitle')).text = i.subtitle

            if i.summary:
                ET.SubElement(
                    channel, ns(ITUNES_NS, 'summary')).text = i.summary
            '''

            ET.SubElement(item, 'enclosure', attrib={
                'type': a.mimetype,
                'length': str(
                    os.path.getsize(os.path.join(bundle.path, a.path))),
                'url': urllib.parse.urljoin(
                    base_url, self.reverse_url(
                        'stream', bundle.slug, str(idx), a.ext),
                ),
            })

        self.write(xml.dom.minidom.parseString(
            ET.tostring(rss, encoding='utf-8')).toprettyxml(),
        )
