import pathlib
import re

from setuptools import find_packages, setup


def get_version(filename):
    with open(filename) as f:
        metadata = dict(re.findall(r'([A-Za-z_]+) = \'([^\']+)\'', f.read()))
        return metadata['ABAP_VERSION']


setup(
    name='abap',
    version=get_version(pathlib.Path('abap/const.py')),
    description='Audiobooks as podcasts',
    author='Naglis Jonaitis',
    author_email='naglis@mailbox.org',
    license='MIT',
    packages=find_packages(),
    install_requires=[
        'PyYAML==3.12',
        'pytaglib==1.4.3',
        'schema==0.6.7',
        'aiohttp==3.3.0',
        'python-slugify==1.2.5',
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
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: Implementation :: CPython',
        'Programming Language :: Python',
        'Topic :: Internet :: WWW/HTTP :: WSGI :: Application',
        'Topic :: Multimedia :: Sound/Audio :: Speech',
        'Topic :: Other/Nonlisted Topic',
    ],
)
