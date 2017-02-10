import tornado.web

from abap import abook, handlers


def make_app(bundle: abook.Abook):
    abap_app = tornado.web.Application([
        tornado.web.URLSpec(
            r'/(?P<slug>\w+)',
            handlers.RSSHandler,
            name='rss',
        ),
        tornado.web.URLSpec(
            r'/(?P<slug>\w+)/stream/(?P<sequence>\d+).(?P<ext>[\w]{1,})',
            handlers.StreamHandler,
            {'path': bundle.path},
            name='stream',
        ),
        tornado.web.URLSpec(
            r'/(?P<slug>\w+)/cover',
            handlers.CoverHandler,
            {'path': bundle.path},
            name='cover',
        ),
        tornado.web.URLSpec(
            r'/(?P<slug>\w+)/fanart',
            handlers.FanartHandler,
            {'path': bundle.path},
            name='fanart',
        ),
    ])
    abap_app.bundle = bundle
    return abap_app
