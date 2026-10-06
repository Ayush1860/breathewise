import sys


def test_python_is_312():
    assert sys.version_info[:2] == (3, 12)
