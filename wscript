#!/bin/env python

#############################################
#
# Author: Lionel Orry ( lionel DOT orry AT gmail DOT com )
# Date: 2011-02-04
#
# U++ sample build script for waf >= 1.6.2
# 
# This has been tested with gcc-4.4.4 and LLVM clang 2.8
# on a Fedora 12 and with gcc-4.4.5 on a Gentoo box.
#
# Example of usage:
#
# 1. Do the configure at start, then only when you want to change the mode (debug/release,
#    compiler flags, compiler executable, etc.)
# 
#    $ ./waf configure
#
#    To get help about options:
#    $ ./waf --help
#
# 2. A package is identified by its assembly/package_name pair. Ex: 'uppsrc/ide' or
#    'bazaar/TestScatter2'. You must select a package with the '--pkg=<package>' option.
#
#    $ ./waf --pkg=bazaar/PolyXMLTest build
#
#    To see a list of the dependencies determined for this package:
#
#    $ ./waf --pkg=bazaar/PolyXMLTest list
#
# There are lots, lots of things remaining, including:
#  - More precise FLAGS handling, use variants etc. See FIXMEs below (HARD)
#  - (DONE but lots of bugs left) Add a pure-python .upp file parser
#    (the generic Makefile by dolik.rce includes a shell script parser that
#    can be used a as basis) to dynamically determine a set of flags and
#    call the task generators (MEDIUM)
#  - Add support for other platforms than Linux
#
# PS: I am a nearly absolute beginner in python, the stuff below is really crap
#     and should be rewritten by a real python programmer who knows Waf as well.
#
#############################################

# Customization to add .icpp to the list of
# extensions handled by the C++ tool
from waflib import TaskGen
from waflib.Tools.cxx import cxx_hook
import re

TaskGen.extension('.icpp')(cxx_hook) 

# FIXME: Handle Upp Flags and other compiler flags correctly
# TODO: Use 'mainconfig' section to get the default use flags (GUI, etc.)
# FIXME: FLAGS should create a variant, and should be constant over a whole build, excepted MAIN flag
# TODO:  Can we create several variants and build them all according to the final targets to create?
# FIXME:  Where to integrate SPEED ?

UPPFLAGS = 'GCC LINUX POSIX SHARED'

def upp_use_flags(ctx, flags):
	arr = []
	for f in flags.split():
		if not f.startswith('.'):
			# append the uselib to the array
			arr = arr + ['useflag_'+f]
			# add a uselib for this flag
			ctx.env['DEFINES_useflag_'+f] = ['flag'+f]
	return ' '.join(arr)

def upp_accept_defines(flags, acceptflags):
	defs = []
	af = acceptflags.split()
	uf = flags.split()
	for f in uf:
		if f.startswith('.'):
			f = f.lstrip('.')
			if ('MAIN' in uf) or (f in af):
				defs.append('flag'+f)
	return defs

# returns: [file_names,c_options,c_uses,c_link,upp_uses,includes,acceptflags,mainconfig]
def parse_pkg(ctx,path,is_main):

	def incond_options(pkg_str,optname):
		# find unconditional options
		opt_lines = re.findall('(?m)^' + optname + r'[ \n]([^;]+)',pkg_str)
		#print 'opt_lines: %r' % opt_lines
		# FIXME: do not remove commas when in a double-quoted string,
		#        see SOLARIS in uppsrc/Core/Core.upp
		_options = [ l.strip().replace('"','').replace(',','').split(' ') for l in opt_lines ]
		# flatten
		_options = " ".join([ item for sublist in _options for item in sublist])
		#print '%s must use for %s %r' % (path,optname,_options)
		return _options

	def cond_options(pkg_str,optname):
		cond_opt_lines = re.findall('(?m)^' + optname + r'\((.+)\)[ \n]([^;]+)',pkg_str)
		opt_line = ""
		for match in cond_opt_lines:
			useit = False
			m_str = match[0]
			#print m_str
			# transform into a python evaluable syntax
			m_str = re.sub(r'([!]?\w+)',r'"\1" in flag_list',m_str)
			m_str = re.sub(r'"!(\w+)"',r'"\1" not',m_str)
			m_str = re.sub(r'!',r' and not ',m_str)
			m_str = m_str.replace(' | ',' or ')
			m_str = m_str.replace(' & ',' and ')
			m_str = m_str.replace('flag_list "','flag_list and "')
			flag_list = ctx.env.UPPFLAGS.strip().split()
			if eval(m_str):
				# Append options
				#print '%s must use for %s %r' % (path,optname,match[1])
				opt_line = opt_line + ' ' + match[1]
		return opt_line.replace('"','').strip()

	def get_mainconfig(pkg_str):
		opt_lines = re.findall(r'(?m)^mainconfig[ \n]([^;]+)',pkg_str)
		if not len(opt_lines):
			return None
		configs = opt_lines[0]
		conf_lines = configs.split(',')
		arr = conf_lines[0].split('=')
		if not len(arr):
			return False
		return arr[1].translate(None,'"').strip()

	def all_opts(pkg_str,f):
		return incond_options(pkg_str,f) + ' ' + cond_options(pkg_str,f)

	def good_extension(f):
		f = f.replace('"','')
		return f.endswith('.cpp') or f.endswith('.c') or f.endswith('.icpp')

	try:
		pkg_f = open( path + "/" + path.rsplit('/',1)[1] + ".upp")
	except:
		return False
	try:
		pkg_desc = pkg_f.read()
	finally:
		pkg_f.close()
	pkg_str = pkg_desc.replace('\n\t',' ').replace('\r','')# .replace('\n','')# .split(';')

	# Mainconfig
	if is_main:
		mc = get_mainconfig(pkg_str)
		if(mc):
			ctx.env.UPPFLAGS = ctx.env.UPPFLAGS + ' ' + mc
		print 'ctx.env.UPPFLAGS is now %r' % ctx.env.UPPFLAGS

	# File names
	r = re.search(r'(?m)^file[ \n]([^;]+)',pkg_str)
	files = r.group(1).strip().split(', ')
	files = [ f for f in files if not f.endswith('separator') ]
	files = [ f.split(' ',1) for f in files ]
	files = [ a for a in files if good_extension(a[0])]
	file_names = ' '.join([ path+'/'+f[0].replace('"','') for f in files ])
	file_names = file_names.replace('\\','/')

	# Compiler options

	# Conditional options: USE flags analysis
	c_options = all_opts(pkg_str,'options')
	#print '%s C/CXX opts: %s' % (path, c_options)

	## CPP defines
	# For now, everything is in CFLAGS/CXXFLAGS: easier.
	## others
	includes = ' ' + ' '.join([ path + '/' + i for i in all_opts(pkg_str, 'include').strip().split()])
	#print '%s includes: %s' % (path, includes)
	

	# Uses
	upp_uses = all_opts(pkg_str,'uses').replace('\\\\','/').replace('\\','/').strip()
	upp_c_uses = ' '.join([ 'upp_' + i.replace('/','_') for i in upp_uses.split()])
	c_uses = upp_c_uses + ' ' + all_opts(pkg_str,'library').upper().strip()
	#print '%s c_uses: %s' % (path, c_uses)
	#print '%s upp_uses: %s' % (path, upp_uses)

	# Linker options
	c_link = all_opts(pkg_str,'link')

	# Accept flags
	acceptflags = all_opts(pkg_str,'acceptflags').strip()
	#print '%s acceptflags: %r' % (path, acceptflags)
	
	#import pprint
	#pp = pprint.PrettyPrinter()
	#pp.pprint((file_names,c_options,c_uses,c_link))
	return file_names,c_options,c_uses,c_link,upp_uses,includes,acceptflags

registered_libs=[]

def add_upp_deps(ctx,ass,dep_pkg):
	# For now we assume the uses come from the
	# current assembly or from the uppsrc nest.
	# FIXME: is the [current_assembly, 'uppsrc'] list enough?
	for pkg in dep_pkg:
		found_lib = False
		for cur_ass in [ass, 'uppsrc']:
			found_lib = upp_lib(ctx, cur_ass + '/' + pkg)
			if found_lib:
				break
		if not found_lib:
			print 'Could not find the dependency %s' % pkg

def upp_lib(ctx, full_pkg):
	if full_pkg in registered_libs:
		return True
	ass,pkg = full_pkg.split('/',1)
	try:
		file_names,c_options,c_uses,c_link,upp_uses,includes,af = parse_pkg(ctx,full_pkg, False)
	except:
		return False
	upp_flags = ctx.env.UPPFLAGS
	# Add u++ deps automatically
	add_upp_deps(ctx, ass, upp_uses.split())

	ctx.stlib(
		target = 'upp_' + pkg.replace('/','_'),
		source = file_names,
		includes = ass + includes,
		export_includes = ass + includes,
		use = c_uses + ' ' + upp_use_flags(ctx, upp_flags),
		defines = upp_accept_defines(upp_flags, af),
		cflags = c_options,
		cxxflags = c_options,
		linkflags = c_link,
	)
	registered_libs.append(full_pkg)
	return True

def upp_app(ctx, full_pkg):
	ass,pkg = full_pkg.split('/',1)
	try:
		file_names,c_options,c_uses,c_link,upp_uses,includes,af = parse_pkg(ctx,full_pkg, True)
	except:
		return False
	upp_flags = ctx.env.UPPFLAGS + ' MAIN'
	# Add u++ deps automatically
	add_upp_deps(ctx, ass, upp_uses.split())

	ctx.program(
		target = pkg.replace('/','_'),
		source = file_names,
		includes = ass + includes,
		export_includes = ass + includes,
		use = c_uses + ' ' + upp_use_flags(ctx, upp_flags),
		defines = upp_accept_defines(upp_flags, af),
		cflags = c_options,
		cxxflags = c_options,
		linkflags = c_link,
	)

def options(ctx):
	ctx.load('compiler_c')
	ctx.load('compiler_cxx')
	ctx.add_option('--nogtk', action='store_true', default=False,
		help='Compiles everything without GTK and with the NOGTK U++ flag')
	ctx.add_option('--debug', action='store_true', default=False,
		help='Compiles everything with the U++ flags DEBUG and DEBUG_FULL')
	ctx.add_option('--pkg', default='', dest='pkg', type='string',
		help="U++ package specification with assembly, ex. 'uppsrc/ide'")

def configure(ctx):
	ctx.load('compiler_c')
	ctx.load('compiler_cxx')
	ctx.env.UPPFLAGS = UPPFLAGS
	ctx.env.STLIB_MARKER = ['-Wl,--whole-archive', '-Wl,-Bstatic']
	ctx.env.SHLIB_MARKER = ['-Wl,--no-whole-archive', '-Wl,-Bdynamic']
	ctx.check_cxx(lib='m', uselib_store='M')
	ctx.check_cxx(lib='z', uselib_store='Z')
	ctx.check_cxx(lib='rt', uselib_store='RT')
	ctx.check_cxx(lib='dl', uselib_store='DL')
	ctx.check_cxx(lib='asound', uselib_store='ASOUND', mandatory=False)
	ctx.check_cxx(lib='pthread', uselib_store='PTHREAD')
	ctx.check_cxx(lib='Xft', uselib_store='XFT', mandatory=False)
	if not ctx.options.nogtk and ctx.check_cfg(package='gtk+-2.0', uselib_store='GTK-X11-2.0', args=['--cflags', '--libs'], mandatory=False):
		ctx.check_cfg(package='libnotify', uselib_store='GTK-X11-2.0', args=['--cflags', '--libs'])
	else:
		ctx.env.UPPFLAGS += ' .NOGTK'
	if ctx.check_cfg(package='freetype2', uselib_store='FREETYPE', args=['--cflags', '--libs']):
		if ctx.check_cfg(package='fontconfig', uselib_store='FONTCONFIG', args=['--cflags', '--libs']):
			if not ctx.env.INCLUDES_FONTCONFIG: ctx.env.INCLUDES_FONTCONFIG = []
			ctx.env.INCLUDES_FONTCONFIG.extend(ctx.env.INCLUDES_FREETYPE)
	ctx.check_cfg(package='libpng', uselib_store='PNG', args=['--cflags', '--libs'], mandatory=False)
	ctx.check_cfg(package='sdl', uselib_store='SDL', args=['--cflags', '--libs'], mandatory=False)
	for l in "AVUTIL AVCODEC AVFORMAT AVDEVICE SWSCALE AVCORE".split():
		ctx.check_cxx(lib=l.lower(), uselib_store=l, mandatory=False)
	ctx.env.prepend_value('CXXFLAGS', ['-x', 'c++'])
	if ctx.options.debug:
		ctx.env.UPPFLAGS = ctx.env.UPPFLAGS + ' DEBUG DEBUG_FULL'
		ctx.env.append_value('CXXFLAGS', ['-O0','-ggdb'])
	else:
		ctx.env.append_value('CXXFLAGS', ['-fexceptions','-Os','-ffunction-sections','-fdata-sections'])
		#ctx.env.append_value('CXXFLAGS', ['-finline-limit=20'])
		ctx.env.append_value('LINKFLAGS', ['-Wl,--gc-sections'])

def build(ctx):
	# FIXME: Handle the GUI flag correctly so that the
	#        corresponding libs are compiled without
	#        Gui support (see mainconfig section in .upp)
	pkgname = ctx.options.pkg
	if pkgname == '' and ctx.cmd != 'clean':
		ctx.fatal('Please select a package with the --pkg option')
	if pkgname.endswith('/'):
		pkgname = pkgname.rstrip('/')
	
	print "Selected package: %s" % pkgname
	upp_app(ctx, pkgname)

