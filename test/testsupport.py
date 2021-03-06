"""
Support routines for all tests.
"""

from __future__ import print_function

import sys, os, re
from os.path import *
from subprocess import *


__all__ = ('data', 'find_dirs', 'run_sfood', 'compare_expect')

# Root of the repo.
_root = realpath(join(dirname(__file__), '..'))

# Executables directory and executables.
bindir = join(_root, 'bin')

# Root location where the data files are to be found.
data = join(dirname(__file__), 'data')


def find_dirs(startdir):
    "Returns a list of directories under startdir."
    rdirs = [startdir]
    for root, dirs, files in os.walk(abspath(startdir)):
        rdirs.extend(join(root, x) for x in dirs)
    return rdirs


def run_sfood(*args, **kw):
    """
    Run sfood with the given args, and capture and return output.
    If 'filterdir' is provided, remove those strings are replaced in the output.
    """
    filterdir = kw.get('filterdir', None)
    cmd = [join(bindir, args[0])] + list(args[1:])
    sys.stderr.write('Running cmd:\n')
    sys.stderr.write(' '.join(cmd))
    sys.stderr.write('\n\n')
    p = Popen(cmd, shell=False, stdout=PIPE, stderr=PIPE)
    out, log = p.communicate()
    if not isinstance(out, str):
        out = out.decode('utf8')
    if not isinstance(log, str):
        log = log.decode('utf8')
    if filterdir is not None:
        from_, to_ = filterdir
        out = re.sub(re.escape(from_), to_, out)
        log = re.sub(re.escape(from_), to_, log)

    if p.returncode != 0:
        sys.stderr.write("Program failed to run: %s\n" % p.returncode)
        sys.stderr.write(' '.join(cmd))
        sys.stderr.write('\n')

    return out, log



def compare_expect(exp_stdout, exp_stderr, *args, **kw):
    out, err = run_sfood(*args, **kw)

    filterdir = kw.get('filterdir', None)

    for name, efn, text in (('stdout', exp_stdout, out),
                            ('stderr', exp_stderr, err)):
        if efn is None:
            continue
        expected = open(efn).read()
        if filterdir is not None:
            from_, to_ = filterdir
            expected = re.sub(re.escape(from_), to_, expected)
        # Fixup path to python executable for repeatable test results
        text = re.sub(r"'[^']+/lib/python2\.7([^']*)'", "'/usr/lib/python2.7\g<1>'", text)
        # Fixup standard module names like `datetime.so`
        text = re.sub(r"/lib-dynload', '([^']+)\.so'", "', '\g<1>'", text)

        # Ensure equal ordering
        text = "\n".join(sorted(text.splitlines()))
        expected = "\n".join(sorted(expected.splitlines()))
        try:
            assert text == expected, ("Unexpected text: \n%s\n != \n%s\n" % (text, expected))
        except AssertionError:
            sys.stderr.write("%s:\n" % name)
            sys.stderr.write("--------\n")
            sys.stderr.write(text)
            sys.stderr.write("\n--------\n\n")
            sys.stderr.write("expected:\n")
            sys.stderr.write("--------\n")
            sys.stderr.write(expected)
            sys.stderr.write("\n--------\n")
            raise
