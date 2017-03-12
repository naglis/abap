====
abap
====

|Build Status|

Audiobooks as podcasts.

Features
--------

* Python 3.6+
* Audiobook scanner with metadata support.
* Additional audiobook in YAML file called abook.
* Valid RSS 2.0 and iTunes podcast feed.
* Built-in podcast server using Tornado.
* Asynchronous file streaming with seeking support (byte serving).
* Easy transcoding to different audio formats.
* Podlove Simple Chapters support.
* Supported audio formats: Ogg Vorbis, Opus, MP3, MP4 (M4A, M4B).

Dependencies
------------

* PyYAML
* attrs
* jsonschema
* mutagen
* tornado

.. |Build Status| image:: https://gitlab.com/naglis/abap/badges/master/build.svg
   :target: https://gitlab.com/naglis/abap/commits/master
