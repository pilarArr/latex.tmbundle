#!/usr/bin/env python -u
# encoding: utf-8

# This is a rewrite of latexErrWarn.py
#
# Goals:
#
#   1. Modularize the processing of a latex run to better capture and parse
#      errors
#   2. Replace latexmk
#   3. Provide a nice pushbutton interface for manually running
#      latex, bibtex, makeindex, and viewing
#
# Overview:
#
#    Each tex command has its own class that parses the output from that
#    program.  Each of these classes extends the TexParser class which provides
#    default methods:
#
#       parseStream
#       error
#       warning
#       info
#
#   The parseStream method reads each line from the input stream matches
#   against a set of regular expressions defined in the patterns dictionary. If
#   one of these patterns matches then the corresponding method is called. This
#   method is also stored in the dictionary. Pattern matching callback methods
#   must each take the match object as well as the current line as a parameter.
#
#   To enable debug mode without modifying this file:
#
#       defaults write com.macromates.textmate latexDebug 1
#
#   Progress:
#
#       7/17/07  -- Brad Miller
#
#       Implemented  TexParse, BibTexParser, and LaTexParser classes see the
#       TODO's sprinkled in the code below
#
#       7/24/07  -- Brad Miller
#
#       Spiffy new configuration window added
#       pushbutton interface at the end of the latex output is added the
#       confusing mass of code that was Typeset & View has been replaced by
#       this one
#
#   Future:
#
#       Think about replacing latexmk with a simpler python version.  If only
#       rubber worked reliably..

# -- Imports ------------------------------------------------------------------

import sys
import re
import os
import tmprefs

from glob import glob
from os import chdir, getenv  # NOQA
from os.path import abspath, dirname, isfile, normpath  # NOQA
from re import match
from subprocess import call, check_output, Popen, PIPE, STDOUT
from sys import stdout
from urllib import quote

from texparser import (BibTexParser, BiberParser, ChkTeXParser, LaTexParser,
                       MakeGlossariesParser, ParseLatexMk, TexParser)


# -- Module Import ------------------------------------------------------------

reload(sys)
sys.setdefaultencoding("utf-8")


# -- Global Variables ---------------------------------------------------------

DEBUG = False


# -- Functions ----------------------------------------------------------------

def expand_name(filename, program='pdflatex'):
    """Get the expanded file name for a certain tex file.

    Arguments:

        filename

                The name of the file we want to expand.

        program

                The name of the tex program for which we want to expand the
                name of the file.

    Returns: ``str``

    Examples:

        >>> expand_name('Tests/text.tex')
        './Tests/text.tex'
        >>> expand_name('non_existent_file.tex')
        ''

    """
    stdout.flush()
    run_object = Popen("kpsewhich -progname='{}' '{}'".format(
        program, filename), shell=True, stdout=PIPE)
    return run_object.stdout.read().strip()


def run_bibtex(texfile, verbose=False):
    """Run bibtex for a certain tex file.

    Run bibtex for ``texfile`` and return the following values:

    - The return value of the bibtex runs done by this function: This value
      will be ``0`` after a successful run. Any other value indicates that
      there were some kind of problems.

    - Fatal error: Specifies if there was a fatal error while processing the
      bibliography.

    - Errors: The number of non-fatal errors encountered while processing the
      bibliography

    - Warnings: The number of warnings found while running this function

    Arguments:

        texfile

            Specifies the name of the tex file. This information will be used
            to find the bibliography.

        verbose

            Specifies if the output by this function should be verbose.


    Returns: ``(int, bool, int, int)``

    Examples:

        >>> chdir('Tests')
        >>> run_bibtex('external_bibliography.tex') # doctest:+ELLIPSIS
        <h4>Processing: ...
        ...
        (0, False, 0, 0)
        >>> chdir('..')

    """
    basename = texfile[:texfile.rfind('.')]
    directory = dirname(texfile) if dirname(texfile) else '.'
    regex_auxfiles = (r'.*/({}|bu\d+)\.aux$'.format(basename))
    auxfiles = [f for f in glob("{}/*.aux".format(directory))
                if match(regex_auxfiles, f)]

    stat, fatal, errors, warnings = 0, False, 0, 0
    for bib in auxfiles:
        print('<h4>Processing: {} </h4>'.format(bib))
        run_object = Popen("bibtex '{}'".format(bib), shell=True, stdout=PIPE,
                           stdin=PIPE, stderr=STDOUT, close_fds=True)
        bp = BibTexParser(run_object.stdout, verbose)
        f, e, w = bp.parseStream()
        fatal |= f
        errors += e
        warnings += w
        stat |= run_object.wait()
    return stat, fatal, errors, warnings


def run_biber(texfile, verbose=False):
    """Run biber for a certain tex file.

    The interface for this function is exactly the same as the one for
    ``run_bibtex``. For the list of arguments and return values please take a
    look at the doc-string of ``run_bibtex``.

    Examples:

        >>> chdir('Tests')
        >>> run_biber('external_bibliography_biber.tex') # doctest:+ELLIPSIS
        <...
        ...
        (0, False, 0, 0)
        >>> chdir('..')

    """
    file_no_suffix = getFileNameWithoutExtension(texfile)
    run_object = Popen("biber '{}'".format(file_no_suffix), shell=True,
                       stdout=PIPE, stdin=PIPE, stderr=STDOUT, close_fds=True)
    bp = BiberParser(run_object.stdout, verbose)
    fatal, errors, warnings = bp.parseStream()
    stat = run_object.wait()
    return stat, fatal, errors, warnings


def run_latex(ltxcmd, texfile, verbose=False):
    """Run the flavor of latex specified by ltxcmd on texfile.

    This function returns:

        - the return value of ``ltxcmd``,

        - a value specifying if there were any fatal flaws (``True``) or not
          (``False``), and

        - the number of errors and

        - the number of warnings encountered while processing ``texfile``.

    Arguments:

        ltxcmd

            The latex command which should be used translate ``texfile``.

        texfile

            The path of the tex file which should be translated by ``ltxcmd``.

    Returns: ``(int, bool, int, int)``

    Examples:

        >>> chdir('Tests')
        >>> run_latex(ltxcmd='pdflatex',
        ...           texfile='external_bibliography.tex') # doctest:+ELLIPSIS
        <h4>...
        ...
        (0, False, 0, 0)
        >>> chdir('..')

    """
    if DEBUG:
        print("<pre>run_latex: {} '{}'</pre>".format(ltxcmd, texfile))
    run_object = Popen("{} '{}'".format(ltxcmd, texfile), shell=True,
                       stdout=PIPE, stdin=PIPE, stderr=STDOUT, close_fds=True)
    lp = LaTexParser(run_object.stdout, verbose, texfile)
    fatal, errors, warnings = lp.parseStream()
    stat = run_object.wait()
    return stat, fatal, errors, warnings


def run_makeindex(filename):
    """Run the makeindex command.

    Generate the index for the given file returning

        - the return value of ``makeindex``,

        - a value specifying if there were any fatal flaws (``True``) or not
          (``False``), and

        - the number of errors and

        - the number of warnings encountered while processing ``filename``.

    Arguments:

        filename

            The name of the tex file for which we want to generate an index.

    Returns: ``(int, bool, int, int)``

    Examples:

        >>> chdir('Tests')
        >>> run_makeindex('makeindex.tex') # doctest:+ELLIPSIS
        This is makeindex...
        ...
        (0, False, 0, 0)
        >>> chdir('..')

    """
    run_object = Popen("makeindex '{}.idx'".format(
                       getFileNameWithoutExtension(filename)), shell=True,
                       stdout=PIPE, stdin=PIPE, stderr=STDOUT, close_fds=True)
    ip = TexParser(run_object.stdout, True)
    fatal, errors, warnings = ip.parseStream()
    stat = run_object.wait()
    return stat, fatal, errors, warnings


def run_makeglossaries(filename):
    """Run makeglossaries for the given file.

    The interface of this function is exactly the same as the one for
    ``run_makeindex``. For the list of arguments and return values, please
    take a look at ``run_makeindex``.

    Examples:

        >>> chdir('Tests')
        >>> run_makeglossaries('makeglossaries.tex') # doctest:+ELLIPSIS
        <h2>Make Glossaries...
        ...
        (0, False, 0, 0)
        >>> chdir('..')

    """
    run_object = Popen("makeglossaries '{}'".format(
                       getFileNameWithoutExtension(filename)), shell=True,
                       stdout=PIPE, stdin=PIPE, stderr=STDOUT, close_fds=True)
    bp = MakeGlossariesParser(run_object.stdout, True)
    fatal, errors, warnings = bp.parseStream()
    stat = run_object.wait()
    return stat, fatal, errors, warnings


def get_app_path(application, tm_support_path=getenv("TM_SUPPORT_PATH")):
    """Get the absolute path of the specified application.

    This function returns either the path to ``application`` or ``None`` if
    the specified application was not found.

    Arguments:

        application

            The application for which this function should return the path

        tm_support_path

            The path to the “Bundle Support” bundle

    Returns: ``str``

        # We assume that Skim is installed in the ``/Applications`` folder
        >>> get_app_path('Skim')
        '/Applications/Skim.app'
        >>> get_app_path('NonExistentApp') # Returns ``None``

    """
    try:
        return check_output("'{}/bin/find_app' '{}.app'".format(
                            tm_support_path, application),
                            shell=True, universal_newlines=True).strip()
    except:
        return None


def get_app_path_and_sync_command(viewer, path_pdf, path_tex_file,
                                  line_number):
    """Get the path and pdfsync command for the specified viewer.

    This function returns a tuple containing

        - the full path to the application, and

        - a command which can be used to show the PDF output corresponding to
          ``line_number`` inside tex file.

    If one of these two variables could not be determined, then the
    corresponding value will be set to ``None``.

    Arguments:

        viewer:

            The name of the PDF viewer application.

        path_pdf:

            The path to the PDF file generated from the tex file located at
            ``path_tex_file``.

        path_tex_file

            The path to the tex file for which we want to generate the pdfsync
            command.

        line_number

            The line in the tex file for which we want to get the
            synchronization command.

    Examples:

        # We assume that Skim is installed
        >>> get_app_path_and_sync_command('Skim', 'test.pdf', 'test.tex', 1)
        ...     # doctest:+ELLIPSIS +NORMALIZE_WHITESPACE
        ('.../Skim.app',
         "'.../Skim.app/.../displayline' 1 'test.pdf' 'test.tex'")

        # Preview has no pdfsync support
        >>> get_app_path_and_sync_command('Preview', 'test.pdf', 'test.tex', 1)
        ('/Applications/Preview.app', None)

    """
    sync_command = None
    path_to_viewer = get_app_path(viewer)
    if path_to_viewer and viewer == 'Skim':
        sync_command = ("'{}/Contents/SharedSupport/displayline' ".format(
                        path_to_viewer) + "{} '{}' '{}'".format(line_number,
                        path_pdf, path_tex_file))
    if DEBUG:
        print("Path to PDF viewer:      {}".format(path_to_viewer))
        print("Synchronization command: {}".format(sync_command))
    return path_to_viewer, sync_command


def refresh_viewer(viewer, pdf_path):
    """Tell the specified PDF viewer to refresh the PDF output.

    If the viewer does not support refreshing PDFs (e.g. “Preview”) then this
    command will do nothing. This command will return a non-zero value if the
    the viewer could not be found or the PDF viewer does not support a “manual”
    refresh.

    Arguments:

        viewer

            The viewer for which we want to refresh the output of the PDF file
            specified in ``pdf_path``.

        pdf_path

            The path to the PDF file for which we want to refresh the output.

    Returns: ``int``

    Examples:

        >>> refresh_viewer('Skim', 'test.pdf')
        <p class="info">Tell Skim to refresh 'test.pdf'</p>
        0

    """
    print('<p class="info">Tell {} to refresh \'{}\'</p>').format(viewer,
                                                                  pdf_path)
    if viewer == 'Skim':
        return call("osascript -e 'tell application \"{}\" ".format(viewer) +
                    "to revert (documents whose path is " +
                    "\"{}\")'".format(pdf_path), shell=True)
    elif viewer == 'TeXShop':
        return call("osascript -e 'tell application \"{}\" ".format(viewer) +
                    "to tell documents whose path is " +
                    "\"{}\" to refreshpdf'".format(pdf_path), shell=True)
    return 1


def run_viewer(viewer, file_name, file_path, suppress_pdf_output_textmate,
               use_pdfsync, line_number,
               tm_bundle_support=getenv('TM_BUNDLE_SUPPORT')):
    """Open the PDF viewer containing the PDF generated from ``file_name``.

    If ``use_pdfsync`` is set to ``True`` and the ``viewer`` supports pdfsnyc
    then the part of the PDF corresponding to ``line_number`` will be opened.
    The function returns the exit value of the shell command used to display
    the PDF file.

    Arguments:

        viewer

            Specifies which PDF viewer should be used to display the PDF

        file_name

            The file name of the tex file

        file_path

            The path to the folder which contains the tex file

        suppress_pdf_output_textmate

            This variable is only used when ``viewer`` is set to ``TextMate``.
            If it is set to ``True`` then TextMate will not try to display the
            generated PDF.

        tm_bundle_support

            The location of the “LaTeX Bundle” support folder

    Returns: ``int``

    Examples:

        >>> chdir('Tests')
        >>> call("pdflatex makeindex.tex > /dev/null", shell=True)
        0
        >>> run_viewer('Skim', 'makeindex.tex', '.',
        ...            suppress_pdf_output_textmate=None, use_pdfsync=True,
        ...            line_number=10, tm_bundle_support=abspath('..'))
        0
        >>> chdir('..')

    """
    status = 0
    path_file = "{}/{}".format(file_path, file_name)
    path_pdf = "{}/{}.pdf".format(file_path,
                                  getFileNameWithoutExtension(file_name))

    if viewer == 'TextMate':
        if not suppress_pdf_output_textmate:
            if isfile(path_pdf):
                print('''<script type="text/javascript">
                         window.location="file://{}"
                         </script>'''.format(quote(path_pdf)))
            else:
                print("File does not exist: '{}'".format(path_pdf))
    else:
        path_to_viewer, sync_command = get_app_path_and_sync_command(
            viewer, path_pdf, path_file, line_number)
        # PDF viewer is installed and it supports pdfsync
        if sync_command and use_pdfsync:
            call(sync_command, shell=True)
        # PDF viewer is installed
        elif path_to_viewer:
            if use_pdfsync:
                print("{} does not supported pdfsync".format(viewer))
            # If this is not done, the next line will thrown an encoding
            # exception when the PDF file contains non-ASCII characters.
            viewer = viewer.encode('utf-8')
            pdf_already_open = not(bool(
                call("'{}/bin/check_open' '{}' '{}'".format(tm_bundle_support,
                     viewer, path_pdf), shell=True)))
            if pdf_already_open:
                refresh_viewer(viewer, path_pdf)
            else:
                status = call("open -a '{}.app' '{}'".format(viewer, path_pdf),
                              shell=True)
        # PDF viewer could not be found
        else:
            print('<strong class="error"> {} does not appear '.format(viewer) +
                  'to be installed on your system.</strong>')
    return status


def determine_ts_directory(tsDirectives):
    """Determine the proper directory to use for typesetting the current
    document"""
    master = os.getenv('TM_LATEX_MASTER')
    texfile = os.getenv('TM_FILEPATH')
    startDir = os.path.dirname(texfile)

    if 'root' in tsDirectives:
        masterPath = os.path.dirname(os.path.normpath(tsDirectives['root']))
        return masterPath
    if master:
        masterPath = os.path.dirname(master)
        if masterPath == '' or masterPath[0] != '/':
            masterPath = os.path.normpath(os.path.join(startDir, masterPath))
    else:
        masterPath = startDir
    if DEBUG:
        print '<pre>Typesetting Directory = ', masterPath, '</pre>'
    return masterPath


def findTexPackages(fileName):
    """Find all packages included by the master file.
       or any file included from the master.  We should not have to go
       more than one level deep for preamble stuff.
    """
    try:
        realfn = expand_name(fileName)
        texString = open(realfn)
    except:
        print('<p class="error">Error: Could not open ' +
              '%s to check for packages</p>' % fileName)
        print('<p class="error">This is most likely a problem with ' +
              'TM_LATEX_MASTER</p>')
        sys.exit(1)
    inputre = re.compile(r'((^|\n)[^%]*?)(\\input|\\include)\{([\w /\.\-]+)\}')
    usepkgre = re.compile(
        r'((^|\n)[^%]*?)\\usepackage(\[[\w, \-]+\])?\{([\w,\-]+)\}')
    beginre = re.compile(r'((^|\n)[^%]*?)\\begin\{document\}')
    incFiles = []
    myList = []
    for line in texString:
        begin = re.search(beginre, line)
        inc = re.search(inputre, line)
        usepkg = re.search(usepkgre, line)
        if begin:
            break
        elif inc:
            incFiles.append(inc.group(4))
        elif usepkg:
            myList.append(usepkg.group(4))
    beginFound = False
    for ifile in incFiles:
        if ifile.find('.tex') < 0:
            ifile += '.tex'
        try:
            realif = expand_name(ifile)
            incmatches = []
            for line in file(realif):
                incmatches.append(re.search(usepkgre, line))
                if re.search(beginre, line):
                    beginFound = True
            myList += [x.group(4) for x in incmatches if x]
        except:
            print('<p class="warning">Warning: Could not open ' +
                  '%s to check for packages</p>' % ifile)
        if beginFound:
            break
    newList = []
    for pkg in myList:
        if pkg.find(',') >= 0:
            for sp in pkg.split(','):
                newList.append(sp.strip())
        else:
            newList.append(pkg.strip())
    if DEBUG:
        print '<pre>TEX package list = ', newList, '</pre>'
    return newList


def find_TEX_directives():
    """Build a dictionary of %!TEX directives

    The main ones we are concerned with are

       root : which specifies a root file to run tex on for this subsidiary
       TS-program : which tells us which latex program to run
       TS-options : options to pass to TS-program
       encoding  :  file encoding

    """
    texfile = os.getenv('TM_FILEPATH')
    startDir = os.path.dirname(texfile)
    done = False
    tsDirectives = {}
    rootChain = [texfile]
    while not done:
        f = open(texfile)
        foundNewRoot = False
        for i in range(20):
            line = f.readline()
            m = re.match(r'^%!TEX\s+([\w-]+)\s?=\s?(.*)', line)
            if m:
                if m.group(1) == 'root':
                    foundNewRoot = True
                    if m.group(2)[0] == '/':
                        newtf = m.group(2).rstrip()
                    else:  # new root is relative or in same directory
                        newtf = os.path.realpath(
                            os.path.join(startDir, m.group(2).rstrip()))
                    if newtf in rootChain:
                        print("<p class='error'> There is a loop in your " +
                              "'%!TEX root =' directives.</p>")
                        print "<p class='error'> chain = ", rootChain, "</p>"
                        print "<p class='error'> exiting.</p>"
                        sys.exit(-1)
                    else:
                        texfile = newtf
                        rootChain.append(newtf)
                    startDir = os.path.dirname(texfile)
                    tsDirectives['root'] = texfile
                else:
                    tsDirectives[m.group(1)] = m.group(2).rstrip()
        f.close()
        if not foundNewRoot:
            done = True
    if DEBUG:
        print '<pre>%!TEX Directives: ', tsDirectives, '</pre>'
    return tsDirectives


def findFileToTypeset(tsDirectives):
    """Determine which file to typeset. Using the following rules:

       + %!TEX root directive
       + using the TM_LATEX_MASTER environment variable
       + Using TM_FILEPATH

       Once the file is decided return the name of the file and the normalized
       absolute path to the file as a tuple.

    """
    if 'root' in tsDirectives:
        f = tsDirectives['root']
    elif os.getenv('TM_LATEX_MASTER'):
        f = os.getenv('TM_LATEX_MASTER')
    else:
        f = os.getenv('TM_FILEPATH')
    master = os.path.basename(f)
    if DEBUG:
        print '<pre>master file = ', master, '</pre>'
    return master, determine_ts_directory(tsDirectives)


def constructEngineOptions(tsDirectives, tmPrefs):
    """Construct a string of command line options to pass to the typesetting
    engine

    Options can come from:

        +  %!TEX TS-options directive in the file
        + Preferences

    In any case nonstopmode is set as is file-line-error-style.

    """
    opts = "-interaction=nonstopmode -file-line-error-style"
    if synctex:
        opts += " -synctex=1 "
    if 'TS-options' in tsDirectives:
        opts += " " + tsDirectives['TS-options']
    else:
        opts += " " + tmPrefs['latexEngineOptions']
    if DEBUG:
        print '<pre>Engine options = ', opts, '</pre>'
    return opts


def usesOnePackage(testPack, allPackages):
    for p in testPack:
        if p in allPackages:
            return True
    return False


def constructEngineCommand(tsDirectives, tmPrefs, packages):
    """This function decides which engine to run using

       + %!TEX directives from the tex file
       + Preferences
       + or by detecting certain packages

    The default is pdflatex.  But it may be modified to be one of

          latex
          xelatex
          texexec  -- although I'm not sure how compatible context is with any
                      of this

    """
    engine = "pdflatex"
    latexIndicators = ['pstricks', 'xyling', 'pst-asr', 'OTtablx', 'epsfig']
    xelatexIndicators = ['xunicode', 'fontspec']

    if 'TS-program' in tsDirectives:
        engine = tsDirectives['TS-program']
    elif usesOnePackage(latexIndicators, packages):
        engine = 'latex'
    elif usesOnePackage(xelatexIndicators, packages):
        engine = 'xelatex'
    else:
        engine = tmPrefs['latexEngine']
    stat = os.system("type {} > /dev/null".format(engine))
    if stat != 0:
        print('<p class="error">Error: %s is not found, ' % engine +
              'you need to install LaTeX or be sure that your PATH is ' +
              'setup properly.</p>')
        sys.exit(1)
    return engine


def getFileNameWithoutExtension(fileName):
    """Return filename upto the . or full filename if no ."""
    suffStart = fileName.rfind(".")
    if suffStart > 0:
        fileNoSuffix = fileName[:suffStart]
    else:
        fileNoSuffix = fileName
    return fileNoSuffix


def writeLatexmkRc(engine, eOpts):
    """Create a latexmkrc file that uses the proper engine and arguments"""
    rcFile = open("/tmp/latexmkrc", 'w')
    rcFile.write("$latex = 'latex -interaction=nonstopmode " +
                 "-file-line-error-style %s  ';\n" % eOpts)
    rcFile.write("$pdflatex = '%s -interaction=nonstopmode " % engine +
                 "-file-line-error-style %s ';\n""" % eOpts)
    rcFile.close()

###############################################################
#                                                             #
#                 Start of main program...                    #
#                                                             #
###############################################################

if __name__ == '__main__':
    verbose = False
    numRuns = 0
    stat = 0
    texStatus = None
    numErrs = 0
    numWarns = 0
    firstRun = False
    synctex = False
    line_number = os.getenv('TM_SELECTION').split(':')[0]

#
# Parse command line parameters...
#
    if len(sys.argv) > 2:
        firstRun = True         # A little hack to make the buttons work nicer.
    if len(sys.argv) > 1:
        texCommand = sys.argv[1]
    else:
        sys.stderr.write("Usage: "+sys.argv[0]+" tex-command firstRun\n")
        sys.exit(255)

#
# Get preferences from TextMate or local directives
#
    tmPrefs = tmprefs.Preferences()

    if int(tmPrefs['latexDebug']) == 1:
        DEBUG = True
        print '<pre>turning on debug</pre>'

    tsDirs = find_TEX_directives()
    os.chdir(determine_ts_directory(tsDirs))

#
# Set up some configuration variables
#
    if tmPrefs['latexVerbose'] == 1:
        verbose = True

    useLatexMk = tmPrefs['latexUselatexmk']
    if texCommand == 'latex' and useLatexMk:
        texCommand = 'latexmk'

    if texCommand == 'latex' and tmPrefs['latexEngine'] == 'builtin':
        texCommand = 'builtin'

    fileName, filePath = findFileToTypeset(tsDirs)
    fileNoSuffix = getFileNameWithoutExtension(fileName)

    ltxPackages = findTexPackages(fileName)

    viewer = tmPrefs['latexViewer']
    engine = constructEngineCommand(tsDirs, tmPrefs, ltxPackages)

    syncTexCheck = os.system("{} --help |grep -q synctex".format(engine))
    if syncTexCheck == 0:
        synctex = True

    if os.getenv('TEXINPUTS'):
        texinputs = os.getenv('TEXINPUTS') + ':'
    else:
        texinputs = ".::"
    texinputs += "%s/tex//" % os.getenv('TM_BUNDLE_SUPPORT')
    os.putenv('TEXINPUTS', texinputs)

    if DEBUG:
        print '<pre>'
        print 'engine = ', engine
        print 'texCommand = ', texCommand
        print 'viewer = ', viewer
        print 'texinputs = ', texinputs
        print 'fileName = ', fileName
        print 'useLatexMk = ', useLatexMk
        print 'synctex = ', synctex
        print '</pre>'

    if texCommand == "version":
        runObj = Popen("{} --version".format(engine), stdout=PIPE, shell=True)
        print runObj.stdout.read().split("\n")[0]
        sys.exit(0)

#
# print out header information to begin the run
#
    if not firstRun:
        print '<hr>'
    #print '<h2>Running %s on %s</h2>' % (texCommand,fileName)
    print '<div id="commandOutput"><div id="preText">'

    if fileName == fileNoSuffix:
        print("<h2 class='warning'>Warning:  Latex file has no extension. " +
              "See log for errors/warnings</h2>")

    if synctex and 'pdfsync' in ltxPackages:
        print("<p class='warning'>Warning:  %s supports synctex " % engine +
              "but you have included pdfsync. You can safely remove " +
              "\usepackage{pdfsync}</p>")

#
# Run the command passed on the command line or modified by preferences
#
    if texCommand == 'latexmk':
        writeLatexmkRc(engine, constructEngineOptions(tsDirs, tmPrefs))
        if engine == 'latex':
            texCommand = 'latexmk -pdfps -f -r /tmp/latexmkrc '
        else:
            texCommand = 'latexmk -pdf -f -r /tmp/latexmkrc '
        texCommand = "{} '{}'".format(texCommand, fileName)
        if DEBUG:
            print("latexmk command = {}".format(texCommand))
        runObj = Popen(texCommand, shell=True, stdout=PIPE, stdin=PIPE,
                       stderr=STDOUT, close_fds=True)
        commandParser = ParseLatexMk(runObj.stdout, verbose, fileName)
        isFatal, numErrs, numWarns = commandParser.parseStream()
        texStatus = runObj.wait()
        os.remove("/tmp/latexmkrc")
        if tmPrefs['latexAutoView'] and numErrs < 1:
            stat = run_viewer(
                viewer, fileName, filePath,
                numErrs > 1 or numWarns > 0 and tmPrefs['latexKeepLogWin'],
                'pdfsync' in ltxPackages or synctex, line_number)
        numRuns = commandParser.numRuns

    elif texCommand == 'bibtex':
        if os.path.exists(fileNoSuffix+'.bcf'):
            texStatus, isFatal, numErrs, numWarns = run_biber(texfile=fileName)
        else:
            texStatus, isFatal, numErrs, numWarns = run_bibtex(
                texfile=fileName)

    elif texCommand == 'index':
        if os.path.exists(fileNoSuffix+'.glsdefs'):
            texStatus, isFatal, numErrs, numWarns = (
                run_makeglossaries(fileName))
        else:
            texStatus, isFatal, numErrs, numWarns = run_makeindex(fileName)

    elif texCommand == 'clean':
        auxiliary_file_extension = ['aux', 'bbl', 'bcf', 'blg', 'fdb_latexmk',
                                    'fls', 'fmt', 'ini', 'log', 'out', 'maf',
                                    'mtc', 'mtc1', 'pdfsync', 'run.xml',
                                    'synctex.gz', 'toc']
        texCommand = 'rm ' + ' '.join(
            ['*.' + extension for extension in auxiliary_file_extension])
        runObj = Popen(texCommand, shell=True, stdout=PIPE, stdin=PIPE,
                       stderr=STDOUT, close_fds=True)
        commandParser = ParseLatexMk(runObj.stdout, True, fileName)

    elif texCommand == 'builtin':
        # the latex, bibtex, index, latex, latex sequence should cover 80% of
        # the cases that latexmk does
        texCommand = engine + " " + constructEngineOptions(tsDirs, tmPrefs)
        texStatus, isFatal, numErrs, numWarns = run_latex(
            texCommand, fileName, verbose)
        numRuns += 1
        if os.path.exists(fileNoSuffix + '.bcf'):
            texStatus, isFatal, numErrs, numWarns = run_biber(texfile=fileName)
        else:
            texStatus, isFatal, numErrs, numWarns = run_bibtex(
                texfile=fileName)
        if os.path.exists(fileNoSuffix + '.idx'):
            texStatus, isFatal, numErrs, numWarns = run_makeindex(fileName)
        texStatus, isFatal, numErrs, numWarns = run_latex(texCommand,
                                                          fileName, verbose)
        numRuns += 1
        texStatus, isFatal, numErrs, numWarns = run_latex(texCommand,
                                                          fileName, verbose)
        numRuns += 1

    elif texCommand == 'latex':
        texCommand = engine + " " + constructEngineOptions(tsDirs, tmPrefs)
        texStatus, isFatal, numErrs, numWarns = run_latex(
            texCommand, fileName, verbose)
        numRuns += 1
        if engine == 'latex':
            psFile = fileNoSuffix+'.ps'
            os.system("dvips {}.dvi -o '{}'".format(fileNoSuffix, psFile))
            os.system("ps2pdf {}".format(psFile))
        if tmPrefs['latexAutoView'] and numErrs < 1:
            stat = run_viewer(
                viewer, fileName, filePath,
                numErrs > 1 or numWarns > 0 and tmPrefs['latexKeepLogWin'],
                'pdfsync' in ltxPackages or synctex, line_number)

    elif texCommand == 'view':
        stat = run_viewer(
            viewer, fileName, filePath,
            numErrs > 1 or numWarns > 0 and tmPrefs['latexKeepLogWin'],
            'pdfsync' in ltxPackages or synctex, line_number)

    elif texCommand == 'sync':
        if 'pdfsync' in ltxPackages or synctex:
            _, sync_command = get_app_path_and_sync_command(
                viewer, '{}.pdf'.format(fileNoSuffix), fileName, line_number)
            if sync_command:
                stat = call(sync_command, shell=True)
            else:
                print("{} does not supported for pdfsync".format(viewer))
                stat = 1

        else:
            print "pdfsync.sty must be included to use this command"
            print "or use a typesetter that supports synctex (such as TexLive)"
            sys.exit(206)

    elif texCommand == 'chktex':
        texCommand = "{} '{}'".format(texCommand, fileName)
        runObj = Popen(texCommand, shell=True, stdout=PIPE, stdin=PIPE,
                       stderr=STDOUT, close_fds=True)
        commandParser = ChkTeXParser(runObj.stdout, verbose, fileName)
        isFatal, numErrs, numWarns = commandParser.parseStream()
        texStatus = runObj.wait()

#
# Check status of running the viewer
#
    if stat != 0:
        print('<p class="error"><strong>error number %d ' % stat +
              ' opening viewer</strong></p>')

#
# Check the status of any runs...
#
    eCode = 0
    if texStatus != 0 or numWarns > 0 or numErrs > 0:
        print("<p class='info'>Found " + str(numErrs) + " errors, and " +
              str(numWarns) + " warnings in " + str(numRuns) + " runs</p>")
        if texStatus:
            if texStatus > 0:
                print("<p class='info'>%s exited with status " % texCommand +
                      "%d</p>" % texStatus)
            else:
                print("<p class='error'>%s exited with error " % texCommand +
                      "code %d</p> " % texStatus)
#
# Decide what to do with the Latex & View log window
#
    if not tmPrefs['latexKeepLogWin']:
        if numErrs == 0 and viewer != 'TextMate':
            eCode = 200
        else:
            eCode = 0
    else:
        eCode = 0

    print '</div></div>'  # closes <pre> and <div id="commandOutput">

#
# Output buttons at the bottom of the window
#
    if firstRun:
        # only need to include the javascript library once
        js = os.getenv('TM_BUNDLE_SUPPORT') + '/bin/texlib.js'
        js = quote(js)
        print('\n<script src="file://%s" type="text/javascript"' % js +
              'charset="utf-8"></script>')
        print('<div id="texActions">')
        print('<input type="button" value="Re-Run %s" ' % engine +
              'onclick="runLatex(); return false" />')
        print('<input type="button" value="Run Bib" onclick="runBibtex(); ' +
              'return false" />')
        if os.path.exists(fileNoSuffix+'.glsdefs'):
            print('<input type="button" value="Make Glossaries" ' +
                  'onclick="runMakeIndex(); return false" />')
        else:
            print('<input type="button" value="Run Makeindex" ' +
                  'onclick="runMakeIndex(); return false" />')
        print('<input type="button" value="Clean up" onclick="runClean(); ' +
              'return false" />')
        if viewer == 'TextMate':
            pdfFile = fileNoSuffix+'.pdf'
            print('<input type="button" value="view in TextMate" ' +
                  'onclick="window.location=\'file://' +
                  quote(filePath + '/' + pdfFile) + '\'"/>')
        else:
            print('<input type="button" value="View in %s" ' % viewer +
                  'onclick="runView(); return false" />')
        print('<input type="button" value="Preferences…" ' +
              'onclick="runConfig(); return false" />')
        print('<p>')
        print('<input type="checkbox" id="hv_warn" name="fmtWarnings" ' +
              'onclick="makeFmtWarnVisible(); return false" />')
        print('<label for="hv_warn">Show hbox,vbox Warnings </label>')
        if useLatexMk:
            print('<input type="checkbox" id="ltxmk_warn" ' +
                  'name="ltxmkWarnings" onclick="makeLatexmkVisible(); ' +
                  'return false" />')
            print('<label for="ltxmk_warn">Show Latexmk Messages </label>')
        print('</p>')
        print('</div>')

    sys.exit(eCode)
