import pathlib
import re

from setuptools import setup


def get_version(filename):
    with open(filename) as f:
        metadata = dict(re.findall(r'__([a-z]+)__ = \'([^\']+)\'', f.read()))
        return metadata['version']


setup(
    name='abap',
    version=get_version(pathlib.Path('abap.py')),
    description='Audiobooks as podcasts',
    author='Naglis Jonaitis',
    author_email='naglis@mailbox.org',
    license='MIT',
    py_modules=[
        'abap',
    ],
    install_requires=[
        'PyYAML==3.13',
        'pytaglib==1.4.3',
        'schema==0.6.8',
        'aiohttp==3.4.2',
        'python-slugify==1.2.5',
    ],
    tests_require=[
        'tox',
    ],
    entry_points={
        'console_scripts': [
            'abap = abap:main',
        ],
        'abap.command': [
            'init = abap:InitCommand',
            'serve = abap:ServeCommand',
        ],
        'abap.xml_renderer': [
            'rss2 = abap:RSSRenderer',
            'itunes = abap:ITunesRenderer',
            'podlove_chapters = abap:PodloveChapterRenderer',
        ],
    },
    include_package_data=True,
    classifiers=[
        'Development Status :: 1 - Planning',
        'Environment :: Console',
        'Environment :: Web Environment',
        'Intended Audience :: Other Audience',
        'Natural Language :: English',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 3 :: Only',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: Implementation :: CPython',
        'Programming Language :: Python',
        'Topic :: Internet :: WWW/HTTP :: WSGI :: Application',
        'Topic :: Multimedia :: Sound/Audio :: Speech',
        'Topic :: Other/Nonlisted Topic',
    ],
)
