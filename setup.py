import pathlib
import re

from setuptools import find_packages, setup


def get_version(filename):
    with open(filename) as f:
        metadata = dict(re.findall(r'([A-Za-z_]+) = \'([^\']+)\'', f.read()))
        return metadata['__version__']


setup(
    name='abap',
    version=get_version(pathlib.Path('abap/__init__.py')),
    description='Audiobooks as podcasts',
    author='Naglis Jonaitis',
    author_email='naglis@mailbox.org',
    license='MIT',
    packages=find_packages(),
    install_requires=[
        'PyYAML==3.13',
        'pytaglib==1.4.4',
        'schema==0.6.8',
        'aiohttp==3.5.2',
        'python-slugify==2.0.1',
    ],
    tests_require=[
        'tox',
    ],
    entry_points={
        'console_scripts': [
            'abap = abap.main:main',
        ],
        'abap.command': [
            'init = abap.commands:InitCommand',
            'serve = abap.commands:ServeCommand',
        ],
        'abap.xml_renderer': [
            'rss2 = abap.render:RSSRenderer',
            'itunes = abap.render:ITunesRenderer',
            'podlove_chapters = abap.render:PodloveChapterRenderer',
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
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: Implementation :: CPython',
        'Programming Language :: Python',
        'Topic :: Internet :: WWW/HTTP :: WSGI :: Application',
        'Topic :: Multimedia :: Sound/Audio :: Speech',
        'Topic :: Other/Nonlisted Topic',
    ],
)
