import pathlib
import re

from setuptools import setup


def get_version(filename):
    with open(filename) as f:
        metadata = dict(re.findall(r'__([a-z]+)__ = \'([^\']+)\'', f.read()))
        return metadata['version']


setup(
    name='abap',
    version=get_version(pathlib.Path('abap') / '__init__.py'),
    description='',
    author='Naglis Jonaitis',
    author_email='naglis@mailbox.org',
    license='MIT',
    packages=['abap'],
    install_requires=[
        'PyYAML>=3.12,<3.20',
        'attrs>=16.3.0,<17.0.0',
        'jsonschema>=2.6.0,<3.0.0',
        'mutagen>=1.36.0,<1.37.0',
        'stevedore>=1.20.0,<1.30.0',
        'tornado>=4.4.0,<4.5.0',
    ],
    entry_points={
        'console_scripts': [
            'abap = abap.main:main',
        ],
        'abap.command': [
            'init = abap.commands:InitCommand',
            'serve = abap.commands:ServeCommand',
            'transcode = abap.commands:TranscodeCommand',
            'zip = abap.commands:ZipCommand',
        ],
    },
    include_package_data=True,
    classifiers=[
        'Development Status :: 1 - Planning',
        'Environment :: Console',
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'Intended Audience :: Other Audience',
        'Natural Language :: English',
        'Operating System :: POSIX :: Linux',
        'Operating System :: POSIX',
        'Programming Language :: Python :: 3 :: Only',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: Implementation :: CPython',
        'Programming Language :: Python',
        'Topic :: Internet :: WWW/HTTP :: WSGI :: Application',
        'Topic :: Internet :: WWW/HTTP :: WSGI',
        'Topic :: Internet :: WWW/HTTP',
        'Topic :: Internet',
        'Topic :: Multimedia :: Sound/Audio :: Speech',
        'Topic :: Other/Nonlisted Topic',
    ],
    zip_safe=False
)
