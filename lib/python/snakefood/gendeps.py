"""
Detect import statements using the AST parser.

This script outputs a comma-separated list of tuples:

  ((from_root, from_filename), (to_root, to_filename))

The roots are the root directories where the modules lie.  You can use
sfood-graph or some other tool to filter, cluster and generate a meaningful
graph from this list of dependencies.

As a special case, if the 'to' tuple is (None, None), this means to at least
include the 'from' tuple as a node.  This may happen if the file has no
dependencies on anything.

See http://furius.ca/snakefood for details.
"""

import sys, os, logging, traceback, re
import imp, compiler
from compiler.visitor import ASTVisitor
from compiler.ast import Discard, Const
from os.path import *
from collections import defaultdict
from operator import itemgetter
from dircache import listdir



class ImportVisitor(object):
    "AST visitor for grabbing the import statements."

    def __init__(self):
        self.modules = []
        self.recent = []
        
    def visitImport(self, node):
        self.accept_imports()
        self.recent.extend((x[0], None, node.lineno) for x in node.names)

    def visitFrom(self, node):
        self.accept_imports()
        modname = node.modname
        for name, as_ in node.names:
            if name != '*':
                mod = (modname, name, node.lineno)
            else:
                mod = (modname, None, node.lineno)
            self.recent.append(mod)

    def default(self, node):
        pragma = None
        if self.recent:
            if isinstance(node, Discard):
                children = node.getChildren()
                if len(children) == 1 and isinstance(children[0], Const):
                    const_node = children[0]
                    pragma = const_node.value
                        
        self.accept_imports(pragma)

    def accept_imports(self, pragma=None):
        self.modules.extend((m, n, l, pragma) for (m, n, l) in self.recent)
        self.recent = []
        

class ImportWalker(ASTVisitor):
    "AST walker that we use to dispatch to a default method on the visitor."

    def __init__(self, visitor):
        ASTVisitor.__init__(self)
        self._visitor = visitor

    def default(self, node, *args):
        self._visitor.default(node)
        ASTVisitor.default(self, node, *args)


ERROR_IMPORT = "    Line %d: Could not import module '%s'"
ERROR_SYMBOL = "    Line %d: Symbol is not a module: '%s'"
ERROR_SOURCE = "       %s"
WARNING_OPTIONAL = "    Line %d: Pragma suppressing import '%s'"

def process_file(fn, verbose, process_pragmas):
    "Returns a list of the files it depends on."
    file_errors = []

    try:
        mod = compiler.parseFile(fn)
    except Exception, e:
        logging.error("Error processing file '%s':\n\n%s" %
                      (fn, traceback.format_exc(sys.stderr)))
        return [], file_errors

    vis = ImportVisitor()
    compiler.walk(mod, vis, ImportWalker(vis))
    vis.accept_imports()

    output_code = (verbose >= 2)
    source_lines = None
    if output_code:
        source_lines = open(fn).read().splitlines()

    files = []
    assert not isdir(fn)
    dn = dirname(fn)
    seenset = set()
    for x in vis.modules:
        mod, sub, lineno, pragma = x
        if process_pragmas and pragma == 'OPTIONAL':
            logging.warning(WARNING_OPTIONAL %
                            (lineno, mod if sub is None else '%s.%s' % (mod, sub)))
            continue
            
        sig = (mod, sub)
        if sig in seenset:
            continue
        seenset.add(sig)

        modfile, errors = find_dotted_module(mod, sub, dn)
        if errors:
            file_errors.extend(errors)
            for err, name in errors:
                efun = logging.warning if err is ERROR_IMPORT else logging.debug
                efun(err % (lineno, name))
                if output_code:
                    efun(ERROR_SOURCE % source_lines[lineno-1].rstrip())

        if modfile is None:
            continue
        files.append(realpath(modfile))

    return files, file_errors




# **WARNING** This is where all the evil lies.  Risk and peril.  Watch out.

libpath = join(sys.prefix, 'lib', 'python%d.%d' % sys.version_info[:2])

exceptions = ('os.path',)
builtin_module_names = sys.builtin_module_names + exceptions

module_cache = {}

def find_dotted_module(modname, sub, parentdir):
    """
    A version of find_module that supports dotted module names (packages).  This
    function returns the filename of the module if found, otherwise returns
    None.

    If 'sub' is not None, it first attempts to import 'modname.sub', and if it
    fails, it must therefore not be a module, so we look up 'modname' and return
    that instead.

    'parentdir' is the directory of the file that attempts to do the import.  We
    attempt to do a local import there first.
    """
    # Check for builtins.
    if modname in builtin_module_names:
        return join(libpath, modname), None

    errors = []
    names = modname.split('.')

    # Try relative import, then global imports.
    fn = find_dotted(names, parentdir)
    if not fn:
        try:
            fn = module_cache[modname]
        except KeyError:
            fn = find_dotted(names)
            module_cache[modname] = fn

        if not fn:
            errors.append((ERROR_IMPORT, modname))
            return None, errors

    # If this is a from-form, try the target symbol as a module.
    if sub:
        fn2 = find_dotted([sub], dirname(fn))
        if fn2:
            fn = fn2
        else:
            errors.append((ERROR_SYMBOL, '.'.join((modname, sub))))
            # Pass-thru and return the filename of the parent, which was found.

    return fn, errors

try:
    from imp import ImpImporter
except ImportError:
    from pkgutil import ImpImporter

def find_dotted(names, parentdir=None):
    """
    Dotted import.  'names' is a list of path components, 'parentdir' is the
    parent directory.
    """
    filename = None
    for name in names:
        mod = ImpImporter(parentdir).find_module(name)
        if not mod:
            break
        filename = mod.get_filename()
        if not filename:
            break
        parentdir = dirname(filename)
    else:
        return filename

def is_python(fn):
    "Return true if the file is a Python file."
    if fn.endswith('.py'):
        return True
    else:
        try:
            file_head = open(fn).read(64)
            if re.match("#!.*\\bpython", file_head):
                return True
        except IOError:
            return False

_iter_ignores = ['.svn', 'CVS', 'build']
# Note: 'build' is for those packages which have been installed with setup.py.
# It is pretty common to forget these around.

def iter_pyfiles(dirsorfns, ignores=None, abspaths=False):
    """Yield all the files ending with .py recursively.  'dirsorfns' is a list
    of filenames or directories.  If 'abspaths' is true, we assumethe paths are
    absolute paths."""
    assert isinstance(dirsorfns, (list, tuple))
    assert isinstance(ignores, list)

    ignores = ignores or _iter_ignores
    for dn in dirsorfns:
        if not abspaths:
            dn = realpath(dn)

        if not exists(dn):
            logging.warning("File '%s' does not exist." % dn)
            continue

        if not isdir(dn):
            if is_python(dn):
                yield dn

        else:
            for root, dirs, files in os.walk(dn):
                for r in ignores:
                    try:
                        dirs.remove(r)
                    except ValueError:
                        pass

                afiles = [join(root, x) for x in files]
                for fn in filter(is_python, afiles):
                    yield fn

def find_roots(list_dirofn, _):
    """
    Given a list of directories or filenames, find Python files and calculate
    the entire list of roots.
    """
    inroots = set()
    for fn in map(realpath, list_dirofn):

        # Search up the directory tree for a root.
        root = find_package_root(fn)
        if root:
            inroots.add(root)
        else:
            # If the given file is not sitting within a root, search down the
            # directory tree for available roots.
            downroots = search_for_roots(fn)
            if downroots:
                inroots.update(downroots)
            else:
                assert isdir(fn)
                logging.warning("Directory '%s' does live or include any roots." % fn)
    return sorted(inroots)

def find_package_root(dn):
    "Search up the directory tree for a package root."
    if not isdir(dn):
        dn = dirname(dn)
    while is_package_dir(dn):
        dn = dirname(dn)
    if is_package_root(dn):
        return dn

def search_for_roots(dn):
    """Search down the directory tree for package roots.  The recursive search
    does not move inside the package root when one is found."""
    if not isdir(dn):
        dn = dirname(dn)
    roots = []
    for root, dirs, files in os.walk(dn):
        if is_package_root(root):
            roots.append(root)
            dirs[:] = []
    return roots

def is_package_dir(dn):
    """Return true if this is a directory within a package."""
    return exists(join(dn, '__init__.py'))


filesets_ignore = (['setup.py'],)
maxlen_filesets = max(map(len, filesets_ignore))

def is_package_root(dn):
    """Return true if this is a package root.  A package root is a directory
    that could be used as a PYTHONPATH entry."""

    if exists(join(dn, '__init__.py')):
        return False
    else:
        # Check if the directory contains Python files.
        files = listdir(dn)
        pyfiles = []
        for x in [join(dn, x) for x in files]:
            ## FIXME: should we use opts.ignore here too?
            if x.endswith('.so') or is_python(x):
                pyfiles.append(x)
                if len(pyfiles) > maxlen_filesets:
                    break

        # Note: we skip directories which only contain a single distutils
        # setup.py file.
        if pyfiles and pyfiles not in filesets_ignore:
            return True

        # Note: We make use of the fact that dotted directory names cannot be
        # imported as packaged.
        for sub in files:
            if '.' in sub:
                continue
            sub = join(dn, sub)
            if not isdir(sub):
                continue
            if exists(join(sub, '__init__.py')):
                return True

    return False

def relfile(fn):
    "Return pairs of (package root, relative filename)."
    root = find_package_root(realpath(fn))
    assert root is not None, fn
    return root, fn[len(root)+1:]

# (Refactor candidate.)
def output_depends(depdict):
    """Given a dictionary of (from -> list of targets), generate an appropriate
    output file."""

    # Output the dependencies.
    write = sys.stdout.write
    for (from_root, from_), targets in sorted(depdict.iteritems(),
                                             key=itemgetter(0)):
        for to_root, to_ in sorted(targets):
            write(repr( ((from_root, from_), (to_root, to_)) ))
            write('\n')

LOG_FORMAT = "%(levelname)-12s: %(message)s"

def gendeps():
    import optparse
    parser = optparse.OptionParser(__doc__.strip())

    parser.add_option('-i', '--internal', '--internal-only', action='store_true',
                      help="Filter out dependencies that are outside of the "
                      "roots of the input files")

    parser.add_option('-I', '--ignore', dest='ignores', action='append', default=[],
                      help="Add the given directory name to the list to be ignored.")

    parser.add_option('-v', '--verbose', action='count', default=0,
                      help="Output more debugging information")

    parser.add_option('-f', '--follow', action='store_true',
                      help="Follow the modules depended upon and trace their dependencies. "
                      "WARNING: This can be slow.  Use --internal to limit the scope.")

    parser.add_option('--print-roots', action='store_true',
                      help="Only print the package roots corresponding to the input files."
                      "This is mostly used for testing and troubleshooting.")

    parser.add_option('-d', '--disable-pragmas', action='store_false',
                      dest='do_pragmas', default=True,
                      help="Disable processing of pragma directives as strings after imports.")

    opts, args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if opts.verbose >= 1 else logging.INFO,
                        format=LOG_FORMAT)
    if not args:
        logging.warning("Searching for files from root directory.")
        args = ['.']

    info = logging.info

    if opts.print_roots:
        inroots = find_roots(args, opts.ignores)
        for dn in sorted(inroots):
            print dn
        return

    info("")
    info("Input paths:")
    for arg in args:
        fn = realpath(arg)
        info('  %s' % fn)
        if not exists(fn):
            parser.error("Filename '%s' does not exist." % fn)

    # Get the list of package roots for our input files and prepend them to the
    # module search path to insure localized imports.
    inroots = find_roots(args, opts.ignores)
    if opts.internal and not inroots:
        parser.error("No package roots found from the given files or directories. "
                     "Using --internal with these roots will generate no dependencies.")
    info("")
    info("Roots of the input files:")
    for root in inroots:
        info('  %s' % root)

    info("")
    info("Using the following import path to search for modules:")
    sys.path = inroots + sys.path
    for dn in sys.path:
        info("  %s" % dn)
    inroots = frozenset(inroots)

    # Find all the dependencies.
    info("")
    info("Processing files:")
    info("")
    allfiles = defaultdict(set)
    allerrors = []
    processed_files = set()

    fiter = iter_pyfiles(args, opts.ignores, False)
    while 1:
        newfiles = set()
        for fn in fiter:
            if fn in processed_files:
                continue # Make sure we process each file only once.

            info("  %s" % fn)
            processed_files.add(fn)
            files, errors = process_file(fn, opts.verbose, opts.do_pragmas)
            allerrors.extend(errors)

            # When packages are the source of dependencies, remove the __init__
            # file.  This is important because the targets also do not include the
            # __init__ (i.e. when "from <package> import <subpackage>" is seen).
            if basename(fn) == '__init__.py':
                fn = dirname(fn)

            # Make sure all the files at least appear in the output, even if it has
            # no dependency.
            from_ = relfile(fn)
            if opts.internal and from_[0] not in inroots:
                continue
            allfiles[from_].add((None, None))

            # Add the dependencies.
            for dfn in files:
                xfn = dfn
                if basename(xfn) == '__init__.py':
                    xfn = dirname(xfn)
                
                to_ = relfile(xfn)
                if opts.internal and to_[0] not in inroots:
                    continue
                allfiles[from_].add(to_)
                newfiles.add(dfn)


        if not (opts.follow and newfiles):
            break
        else:
            fiter = iter(sorted(newfiles))


    info("")
    info("SUMMARY")
    info("=======")

    # Output a list of the symbols that could not be imported as modules.
    reports = [("Modules that could not be imported:", ERROR_IMPORT, logging.warning)]
    if opts.verbose >= 2:
        reports.append(
            ("Symbols that could not be imported as modules:", ERROR_SYMBOL, logging.debug))

    for msg, errtype, efun in reports:
        names = frozenset(name for err, name in allerrors if err is errtype)
        if names:
            efun("")
            efun(msg)
            for name in sorted(names):
                efun("  %s" % name)

    # Output the list of roots found.
    info("")
    info("Found roots:")

    found_roots = set()
    for key, files in allfiles.iteritems():
        found_roots.add(key[0])
        found_roots.update(map(itemgetter(0),files))
    if None in found_roots:
        found_roots.remove(None)
    for root in sorted(found_roots):
        info("  %s" % root)

    # Output the dependencies.
    info("")
    output_depends(allfiles)


def main():
    try:
        gendeps()
    except KeyboardInterrupt:
        raise SystemExit("Interrupted.")
    


