import mimetypes
import operator

import aiohttp.web
import multidict

from . import abook, const, render, utils


def make_url_reverse(request):
    app = request.app
    base_url = request.url.origin()

    def url_reverse(resource, **kwargs) -> str:
        if resource:
            return str(base_url.join(app.router[resource].url_for(**kwargs)))
        else:
            return str(base_url)

    return url_reverse


async def rss_feed_handler(request):
    slug = request.match_info['slug']
    abook = request.app['abooks'].get(slug)
    if not abook:
        raise aiohttp.web.HTTPNotFound()

    return aiohttp.web.Response(
        body=utils.pretty_print_xml(render.build_rss(
            abook.directory,
            abook,
            reverse_url=make_url_reverse(request),
        )),
        headers=multidict.MultiDict({
            'Content-Type': (
                f'application/rss+xml; charset="{const.DEFAULT_XML_ENCODING}"'),
        }),
    )


async def episode_handler(request):
    slug, sequence, ext = operator.itemgetter('slug', 'sequence', 'ext')(
        request.match_info)
    abook = request.app['abooks'].get(slug)
    if not abook:
        raise aiohttp.web.HTTPNotFound()

    try:
        item = abook.get('items', [])[int(sequence) - 1]
    except ValueError:
        raise aiohttp.web.HTTPBadRequest()
    except IndexError:
        raise aiohttp.web.HTTPNotFound()

    return aiohttp.web.FileResponse(
        item['path'],
        headers=multidict.MultiDict({
            'Content-Type': item['mimetype'],
        }),
    )


async def cover_handler(request):
    slug = request.match_info['slug']
    abook = request.app['abooks'].get(slug)
    if not (abook and abook.get('cover')):
        raise aiohttp.web.HTTPNotFound()
    cover = abook.get('cover')
    return aiohttp.web.FileResponse(
        cover,
        headers=multidict.MultiDict({
            'Content-Type': utils.first(mimetypes.guess_type(str(cover))),
        }),
    )


def make_app(abook: abook.Abook):
    app = aiohttp.web.Application()
    # FIXME(naglis): Make slug and ext more strict.
    rss_feed = app.router.add_resource(
        r'/abook/{slug}/feed/rss', name='rss_feed')
    rss_feed.add_route('GET', rss_feed_handler)

    episode = app.router.add_resource(
        r'/abook/{slug}/episode/{sequence:\d+}.{ext}', name='episode',
    )
    episode.add_route('GET', episode_handler)

    cover = app.router.add_resource(r'/abook/{slug}/cover', name='cover')
    cover.add_route('GET', cover_handler)

    app['abooks'] = {
        abook['slug']: abook,
    }
    app.abook = abook
    return app
