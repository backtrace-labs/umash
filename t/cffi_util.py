"""
Utility functions to work with cffi.
"""

import re


def read_stripped_header(path, replacements={}):
    """Returns the contents of a header file without preprocessor directives."""
    ret = ""
    in_directive = False
    with open(path) as f:
        for line in f:
            if in_directive or re.match(r"^\s*#", line):
                in_directive = line.endswith("\\\n")
            else:
                in_directive = False
                for pattern, repl in replacements.items():
                    line = re.sub(pattern, repl, line)
                ret += line
    return ret
