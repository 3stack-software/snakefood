PACKAGE=snakefood

PYTHON=python2
GIT=git
RM=rm -f
CP=cp -f
MKDIR=mkdir

.PHONY:

all:

install:
	$(PYTHON) setup.py install --home=$(HOME)

clean:
	-$(PYTHON) setup.py clean
	-$(RM) -r build dist

distclean: clean

sdist: distclean
	$(PYTHON) setup.py sdist
bdist: distclean
	$(PYTHON) setup.py bdist_wheel --universal

test: .PHONY
	$(PYTHON) setup.py test
