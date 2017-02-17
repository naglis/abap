import itertools
import pathlib

from abap import utils


def labeled_scan(path: pathlib.Path, label_funcs):
    return {
        k: list(map(utils.second_of, g))
        for k, g in itertools.groupby(
            sorted(labeled_scan_iter(path, label_funcs), key=utils.first_of),
            key=utils.first_of,
        )
    }


def labeled_scan_iter(path: pathlib.Path, label_funcs):
    for child in path.iterdir():
        if child.is_dir():
            yield from labeled_scan_iter(child, label_funcs)
        elif child.is_file():
            for label, func in label_funcs.items():
                if func(str(child)):
                    yield label, child
        else:
            pass
