import os

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PIDS_FILE = os.path.join(_BASE_DIR, "pids.txt")


def _load():
    """Return dict {name: pid} from pids.txt."""
    result = {}
    try:
        with open(_PIDS_FILE, encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(None, 1)
                if len(parts) == 2:
                    try:
                        result[parts[1]] = int(parts[0])
                    except ValueError:
                        pass
    except FileNotFoundError:
        pass
    return result


def _save(data):
    with open(_PIDS_FILE, "w", encoding="utf-8") as f:
        for name, pid in sorted(data.items()):
            f.write(f"{pid}  {name}\n")


def read_pid(name):
    return _load().get(name)


def write_pid(name, pid):
    data = _load()
    data[name] = pid
    _save(data)


def remove_pid(name):
    data = _load()
    if name in data:
        data.pop(name)
        _save(data)


def read_all():
    return _load()


def clear():
    try:
        os.remove(_PIDS_FILE)
    except FileNotFoundError:
        pass
