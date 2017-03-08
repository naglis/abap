import pathlib
import re

from setuptools import setup


def get_version(filename):
    with open(filename) as f:
        metadata = dict(re.findall(r'__([a-z]+)__ = \'([^\']+)\'', f.read()))
        return metadata['version']


def get_requirements(filename='requirements.txt'):
    requirements = []
    with open(filename, 'rt') as f:
        for line in f:
            requirements.append(line.strip())
    return requirements


setup(
    name='abap',
    version=get_version(pathlib.Path('abap') / '__init__.py'),
    description='',
    author='Naglis Jonaitis',
    author_email='naglis@mailbox.org',
    license='MIT',
    packages=['abap'],
    install_requires=get_requirements(),
    entry_points={
        'console_scripts': [
            'abap = abap.main:main',
        ],
        'abap.command': [
            'init = abap.commands:InitCommand',
            'serve = abap.commands:ServeCommand',
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
