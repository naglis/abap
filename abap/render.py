import abc
import collections
import datetime
import logging
import pathlib
import time
import typing
import xml.etree.cElementTree as ET

import pkg_resources

from . import abook, const, utils

LOG = logging.getLogger(__name__)

ETGenerator = typing.Generator[ET.Element, None, None]

itunes = utils.make_ns_getter(const.ITUNES_NAMESPACE)
psc = utils.make_ns_getter(const.PSC_NAMESPACE)


class XMLNamespace(typing.NamedTuple):
    prefix: str  # noqa: E701. See also: https://git.io/vS5GZ
    uri: str  # noqa


class XMLRenderer(metaclass=abc.ABCMeta):

    def __init__(self, uri_func: typing.Callable = None) -> None:
        self.uri_func = uri_func

    def reverse_uri(self, handler: typing.Optional[str], **kwargs):
        if callable(self.uri_func):
            return self.uri_func(handler, **kwargs)
        else:
            return handler

    def el(self, tag: str,
           text: typing.Optional[str] = None,
           **attrib: typing.Dict[str, str]) -> ET.Element:
        element = ET.Element(tag, attrib=attrib)
        element.text = text
        return element

    @property
    def namespaces(self) -> typing.List[XMLNamespace]:
        return []

    @abc.abstractmethod
    def render_channel(self, abook: abook.Abook) -> ETGenerator:
        '''Yields XML nodes which are appended inside <channel>.'''

    @abc.abstractmethod
    def render_item(self, abook: abook.Abook, item: dict,
                    sequence: int = 0) -> ETGenerator:
        '''Yields XML nodes which are appended inside an <item>.'''


class RSSRenderer(XMLRenderer):

    def render_channel(self, abook: abook.Abook) -> ETGenerator:
        yield self.el('generator', f'abap/{const.ABAP_VERSION}')

        yield self.el('title', abook['title'])

        yield self.el('link', self.reverse_uri(None))

        if abook.get('description'):
            yield self.el('description', abook['description'])

        for category in abook.get('categories', []):
            yield self.el('category', category)
        '''
        yield self.el('language', abook.lang)

        if abook.has_manifest:
            yield self.el('pubDate', time.strftime(
                const.RFC822, abook.publication_date.timetuple()))
        '''


        cover_url = self.reverse_uri('cover', slug=abook['slug'])
        image = self.el('image')
        image.append(self.el('url', cover_url))
        image.append(self.el('title', abook['title']))
        image.append(self.el('link', self.reverse_uri(None)))
        yield image

        if abook.has_manifest:
            dt = datetime.datetime.fromtimestamp(
                abook.manifest.stat().st_mtime)
        else:
            dt = datetime.datetime.now()
        yield self.el('lastBuildDate', time.strftime(const.RFC822, dt.timetuple()))

        yield self.el('ttl', str(const.DEFAULT_TTL))

    def render_item(self, abook: abook.Abook, item: dict,
                    sequence: int = 0) -> ETGenerator:
        yield self.el('title', item['title'])

        yield self.el('guid', str(sequence), isPermaLink='false')

        # FIXME: this is a bit of a workaround in order to help sorting the
        # episodes in the podcast client.
        pub_date = time.strftime(
            const.RFC822,
            (datetime.datetime.now() -
                datetime.timedelta(minutes=sequence)).timetuple())
        yield self.el('pubDate', pub_date)

        '''
        if i.subtitle:
            ET.SubElement(
                channel, itunes('subtitle')).text = i.subtitle

        if i.summary:
            ET.SubElement(
                channel, itunes('summary')).text = i.summary
        '''

        yield self.el(
            'enclosure',
            type=item['mimetype'],
            length=str(item['size']),
            url=self.reverse_uri(
                'episode',
                slug=abook['slug'],
                sequence=str(sequence),
                ext=item['path'].suffix.lstrip('.'),
            ),
        )


class ITunesRenderer(XMLRenderer):

    @property
    def namespaces(self) -> typing.List[XMLNamespace]:
        return [
            XMLNamespace('itunes', const.ITUNES_NAMESPACE),
        ]

    def render_channel(self, abook: abook.Abook) -> ETGenerator:
        yield self.el(itunes('author'), ', '.join(abook['authors']))

        for category in abook.get('categories', []):
            yield self.el(itunes('category'), category)

        yield self.el(
            itunes('image'),
            href=self.reverse_uri('cover', slug=abook['slug']))

    def render_item(self, abook: abook.Abook, item: dict,
                    sequence: int = 0) -> ETGenerator:
        yield self.el(itunes('duration'), utils.format_duration(item['duration']))

        if 'explicit' in item:
            yield self.el(
                itunes('explicit'), 'Yes' if item['explicit'] else 'No')


class PodloveChapterRenderer(XMLRenderer):

    @property
    def namespaces(self) -> typing.List[XMLNamespace]:
        return [
            XMLNamespace('psc', const.PSC_NAMESPACE),
        ]

    def render_channel(self, abook: abook.Abook) -> ETGenerator:
        return
        yield

    def render_item(self, abook: abook.Abook, item: dict,
                    sequence: int = 0) -> ETGenerator:
        if item.get('chapters'):
            chapters = self.el(
                psc('chapters'),
                version=const.PSC_VERSION,
            )
            for c in item.get('chapters', []):
                chapters.append(self.el(
                    psc('chapter'),
                    title=c['name'],
                    start=utils.format_duration(c['start']),
                ))
            yield chapters


def load_renderers(entry_point_name='abap.xml_renderer') -> typing.Mapping[str, XMLRenderer]:
    LOG.debug(f'Loading XML renderers from entry point: {entry_point_name}')

    renderers = collections.OrderedDict()
    for entry_point in pkg_resources.iter_entry_points(entry_point_name):
        LOG.debug(f'Loading XML renderer: {entry_point.name}')
        # FIXME: handle exceptions
        renderers[entry_point.name] = entry_point.load()

    return renderers


def build_rss(directory: pathlib.Path,
              abook: abook.Abook, reverse_url=lambda n, **kw: n,
              renderers: typing.Optional[typing.Mapping[
                  str, typing.Type[XMLRenderer]]]=None) -> ET.Element:
    renderers = renderers or load_renderers()

    extensions = collections.OrderedDict([
        (n, cls(reverse_url)) for n, cls in renderers.items()
    ])

    for ext_name, ext in extensions.items():
        LOG.debug(f'Registering XML namespaces for renderer: {ext_name}')
        for ns in ext.namespaces:
            ET.register_namespace(ns.prefix, ns.uri)

    rss = ET.Element('rss', attrib={'version': const.RSS_VERSION})
    channel = ET.SubElement(rss, 'channel')

    for ext_name, ext in extensions.items():
        LOG.debug(f'Rendering channel elements with renderer: {ext_name}')
        for el in ext.render_channel(abook):
            channel.append(el)

    for idx, item in enumerate(abook.get('items', []), start=1):
        item_elem = ET.SubElement(channel, 'item')
        for ext_name, ext in extensions.items():
            LOG.debug(
                f'Rendering item #{idx} elements with renderer: {ext_name}')
            for elem in ext.render_item(abook, item, sequence=idx):
                item_elem.append(elem)

    return rss
