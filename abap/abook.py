import collections
import copy
import logging
import mimetypes
import pathlib
import typing

import schema
import slugify
import yaml

from . import const, scan, utils

LOG = logging.getLogger(__name__)

EXPORTABLE_ABOOK_KEYS = (
    'authors',
    'title',
    'slug',
    'description',
    'categories',
    'explicit',
    'cover',
    'items',
)
EXPORTABLE_ITEM_KEYS = (
    'authors',
    'categories',
    'chapters',
    'description',
    'explicit',
    'path',
    'title',
)

by_abook_key = collections.OrderedDict(
    zip(EXPORTABLE_ABOOK_KEYS, range(len(EXPORTABLE_ABOOK_KEYS)))).get

def non_empty_string(s: typing.Any) -> bool:
    return isinstance(s, str) and bool(s.strip())


# Schemas for validation of abook data loaded from YAML.
CHAPTER_SCHEMA = schema.Schema({
    'name': str,
    'start': schema.Use(utils.parse_duration),
    schema.Optional('url'): str,  # TODO(naglis): validate URL.
})
ITEM_SCHEMA = schema.Schema({
    'path': non_empty_string,
    schema.Optional('authors'): [
        str,
    ],
    schema.Optional('sequence'): int,
    schema.Optional('explicit'): bool,
    schema.Optional('title'): str,
    schema.Optional('description'): str,
    schema.Optional('categories'): [
        str,
    ],
    schema.Optional('chapters'): [
        CHAPTER_SCHEMA,
    ],
})
ABOOK_SCHEMA = schema.Schema({
    schema.Optional('authors'): [
        str,
    ],
    schema.Optional('title'): str,
    schema.Optional('description'): str,
    schema.Optional('slug'): str,
    schema.Optional('categories'): [
        str,
    ],
    schema.Optional('explicit'): bool,
    schema.Optional('items'): [
        ITEM_SCHEMA,
    ],
    schema.Optional('cover'): str,
})


def from_dir(directory: pathlib.Path, ignore_files) -> dict:
    authors, albums, descriptions, categories = map(
        lambda i: collections.OrderedDict(), range(4))
    all_non_explicit = True
    items = []

    results = scan.labeled_scan(
        directory, {
            'audio': scan.audio_matcher,
            'cover': scan.cover_matcher,
        },
    )
    for audio_file in sorted(results.get('audio', [])):
        if ignore_files and audio_file.resolve(strict=True) in ignore_files:
            continue
        item = {
            'authors': [
                'Unknown author',
            ],
            'title': audio_file.stem,
            'path': audio_file,
            'size': audio_file.stat().st_size,
            'mimetype': utils.first(mimetypes.guess_type(str(audio_file))),
        }

        tags = scan.get_tags(audio_file)
        item.update(tags)

        if tags.get('authors'):
            for a in tags.get('authors'):
                authors[a] = True
        if tags.get('album'):
            albums[tags['album']] = True
        if tags.get('description'):
            descriptions[tags['description']] = True
        if tags.get('categories'):
            categories[tuple(c for c in sorted(tags.get('categories')))] = True

        if tags.get('explicit') and all_non_explicit:
            all_non_explicit = False

        items.append(item)

    for item in items:
        item.pop('album', None)
        if not item.get('chapters'):
            item.pop('chapters', None)

        if len(descriptions) == 1 or not item.get('description'):
            item.pop('description', None)

        if len(categories) == 1 or not item.get('categories'):
            item.pop('categories', None)

        if all_non_explicit:
            item.pop('explicit', None)

    global_data = {
        'title': 'Unknown title',
        'authors': [
            'Unknown author',
        ],
        'categories': [
        ],
        'items': items,
    }

    if not all_non_explicit:
        global_data.update({
            'explicit': True,
        })

    if authors:
        global_data.update({
            'authors': list(authors),
        })

    if albums:
        if len(albums) > 1:
            LOG.warn('Multiple values for album title found. '
                     'Will use the first one')
        global_data.update({
            'title': utils.first(list(albums.keys())),
        })

    if descriptions:
        if len(descriptions) > 1:
            LOG.warn('Multiple values for description found. '
                     'Will use the first one')
        global_data.update({
            'description': utils.first(list(descriptions.keys())),
        })

    if categories:
        global_data.setdefault('categories', []).extend(sorted(list({
            c for cats in categories for c in cats})))

    covers = results.get('cover', [])
    if covers:
        global_data.update({
            'cover': utils.first(covers),
        })

    global_data.update({
        'slug': slugify.slugify(global_data['title']),
    })

    return global_data


def merge(directory: pathlib.Path, data: typing.MutableMapping,
          yaml_data: typing.MutableMapping) -> typing.MutableMapping:

    result = copy.deepcopy(data)
    yaml_data = copy.deepcopy(yaml_data)
    yaml_items = collections.OrderedDict()

    def override(key):
        if key in yaml_data:
            result[key] = yaml_data[key]

    items_by_path = {}
    for item in result.get('items', []):
        items_by_path[item['path']] = item

    if ('title' in yaml_data and not
            yaml_data['title'] == data['title'] and
            'slug' not in yaml_data):
        result['slug'] = slugify.slugify(yaml_data['title'])

    for key in ('title', 'authors', 'categories', 'description', 'slug'):
        override(key)

    for idx, item in enumerate(yaml_data.get('items', [])):
        item_path = directory / item['path']

        current_item = items_by_path.get(item_path)
        if current_item is None:
            LOG.warn(f'Unknown item: {item_path!s} in YAML data')
            continue

        overrides = {}
        for k in ('title', 'categories', 'description', 'chapters', 'sequence',
                  'explicit'):
            if k in item:
                overrides[k] = item[k]
        if overrides:
            current_item.update(overrides)

        # Retain index for sorting purposes.
        yaml_items[item_path] = idx

    # Decide sorting order.
    if len(items_by_path) == len(yaml_items):
        LOG.debug(
            'Manifest contains all the items, items without sequence will be '
            'sorted by their order in the manifest')
        sequences = {p: i for i, p in enumerate(yaml_items, start=1)}
    else:
        LOG.debug('Items without sequence will be sorted by path')
        sequences = {
            p: i for i, p in enumerate(sorted(items_by_path), start=1)}

    def sort_key(item):
        return item.get('sequence', sequences[item['path']])

    result.update({
        'items': sorted(result.get('items', []), key=sort_key),
    })

    return result


def prepare_for_export(directory: pathlib.Path, d: dict) -> dict:

    authors = set()

    def relative_path(path: pathlib.Path) -> str:
        return str(path.relative_to(directory))

    result = copy.deepcopy(d)
    for k in result:
        if k not in EXPORTABLE_ABOOK_KEYS:
            result.pop(k)

    if 'cover' in result:
        result['cover'] = relative_path(result['cover'])

    for item in result.get('items', []):
        for k in list(item.keys()):
            if k not in EXPORTABLE_ITEM_KEYS:
                item.pop(k)
                continue
        authors.update(item.get('authors', []))
        item['path'] = relative_path(item['path'])

    if utils.items_are_equal(authors, result.get('authors', [])):
        for item in result.get('items', []):
            item.pop('authors', None)

    return {
        k: result[k] for k in sorted(result, key=by_abook_key)
    }


class Abook(collections.abc.Mapping):

    def __init__(self, directory: pathlib.Path, d: dict) -> None:
        self.directory = directory
        self._d = d

    def __getitem__(self, idx):
        return self._d[idx]

    def __iter__(self):
        return iter(self._d)

    def __len__(self) -> int:
        return len(self._d)

    @property
    def manifest(self) -> pathlib.Path:
        return self.directory / const.MANIFEST_FILENAME

    @property
    def has_manifest(self) -> bool:
        return self.manifest.is_file()

    def merge_manifest(self, yaml_data=None) -> None:
        yaml_data = yaml_data or {}

        if not yaml_data:
            try:
                with open(self.manifest) as f:
                    yaml_data = yaml.safe_load(f)
            except FileNotFoundError:
                pass

        if yaml_data:
            yaml_data = ABOOK_SCHEMA.validate(yaml_data)

        self._d = merge(self.directory, self._d, yaml_data)

    @classmethod
    def from_directory(
            cls, directory: pathlib.Path,
            ignore_files: typing.Optional[typing.Set[pathlib.Path]] = None):
        d = from_dir(directory, ignore_files or set())
        return cls(directory, d)
