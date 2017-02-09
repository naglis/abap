import os
import collections


def labeled_scan(path: str, label_funcs, path_join=os.path.join):
    results = collections.defaultdict(list)
    for subdir, dirs, files in os.walk(path):
        rel_dir = os.path.relpath(subdir, path)
        rel_dir = '' if rel_dir == '.' else rel_dir
        for fn in files:
            for label, func in label_funcs.items():
                if func(fn):
                    results[label].append(path_join(rel_dir, fn))

    return results
