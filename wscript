#!/bin/env python

###############################################################################
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
###############################################################################

# Customization to add .icpp to the list of
# extensions handled by the C++ tool
from waflib import TaskGen, Task, Errors, Utils
from waflib.TaskGen import feature
from waflib.Configure import conf
from waflib.Tools.cxx import cxx_hook,cxx
import re, os

TaskGen.extension('.icpp')(cxx_hook) 

# FIXME: Handle Upp Flags and other compiler flags correctly
# TODO: Use 'mainconfig' section to get the default use flags (GUI, etc.)
# FIXME: FLAGS should create a variant, and should be constant over a whole build, excepted MAIN flag
# TODO:  Can we create several variants and build them all according to the final targets to create?
# FIXME:  Where to integrate SPEED ?

UPPFLAGS = 'GCC LINUX POSIX SHARED'

class fake_obj(cxx):
	"""
	Task used for reading an object file and adding the dependency on it
	"""
	def runnable_status(self):
		for t in self.run_after:
			if not t.hasrun:
				return Task.ASK_LATER

		for x in self.outputs:
			x.sig = Utils.h_file(x.abspath())
		return Task.SKIP_ME

@conf
def read_object(self, name):
	"""
	Read a system object files, enabling a use as a local object. Will trigger a rebuild if the file changes.
	"""
	return self(name=name, features='fake_obj')

@feature('fake_obj')
def process_obj(self):
	"""
	Find the location of a foreign object file.
	"""
	node = None

	node = self.path.find_node(self.name)
	if(node):
		node.sig = Utils.h_file(node.abspath())
	else:
		raise Errors.WafError('could not find object file %r' % self.name)
	self.objects = [node]
	task = self.create_task('fake_obj', [], [node])
	self.target = self.name
	try:
		self.compiled_tasks.append(task)
	except AttributeError:
		self.compiled_tasks = [task]

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
			flag_list = ctx.env.UPPFLAGS.replace('.','').strip().split()
			#print "flag_list: %r" % flag_list
			#print m_str
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

	def src_extension(f):
		f = f.replace('"','').lower()
		return f.endswith('.cpp') or f.endswith('.c') or f.endswith('.cc') or f.endswith('.icpp')

	def obj_extension(f):
		f = f.replace('"','').lower()
		return f.endswith('.o')

	def lib_extension(f):
		f = f.replace('"','').lower()
		return f.endswith('.a')

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
	if is_main and ctx.env.use_mainconfig:
		mc = get_mainconfig(pkg_str)
		if(mc):
			ctx.env.UPPFLAGS = ctx.env.UPPFLAGS + ' ' + mc
		print 'ctx.env.UPPFLAGS is now %r' % ctx.env.UPPFLAGS

	# File names
	r = re.search(r'(?m)^file[ \n]([^;]+)',pkg_str)
	files = r.group(1).strip().split(', ')
	files = [ f for f in files if not f.endswith('separator') ]
	files = [ f.split(' ',1) for f in files ]
	sources = [ a for a in files if src_extension(a[0])]
	objects = [ a for a in files if obj_extension(a[0])]
	libs    = [ a for a in files if lib_extension(a[0])]
	src_names = ' '.join([ path+'/'+f[0].replace('"','') for f in sources ])
	src_names = src_names.replace('\\','/')
	obj_files = ' '.join([ path+'/'+f[0].replace('"','') for f in objects ])
	obj_files = obj_files.replace('\\','/').strip().split()
	lib_files = ' '.join([ path+'/'+f[0].replace('"','') for f in libs ])
	lib_files = lib_files.replace('\\','/').strip().split()

	for i in obj_files:
		ctx.read_object(i)

	lib_names = []
	for i in lib_files:
		n = ctx.path.find_resource(i)
		nn = re.sub(r'lib(.+)\.a', r'\1', n.name)
		np = n.parent.srcpath()
		lib_names.append(nn)
		ctx.read_stlib(nn, [np])

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
	upp_c_uses = [ 'upp_' + i.replace('/','_') for i in upp_uses.split()]
	libraries = all_opts(pkg_str,'library').strip().split()
	c_uses = ' '.join(upp_c_uses + obj_files + lib_names)
	for l in libraries:
		usename = l.upper()
		#print 'adding %r in LIB_%s' % (l, usename)
		ctx.env.append_unique('LIB_'+usename, l)
		#print 'LIB_%s: %r' % (usename, ctx.env['LIB_'+usename])
		c_uses = c_uses + ' ' + usename
	#print '%s c_uses: %s' % (path, c_uses)
	#print '%s upp_uses: %s' % (path, upp_uses)

	# Linker options
	c_link = all_opts(pkg_str,'link')

	# Accept flags
	acceptflags = all_opts(pkg_str,'acceptflags').strip()
	#print '%s acceptflags: %r' % (path, acceptflags)
	
	#import pprint
	#pp = pprint.PrettyPrinter()
	#pp.pprint((src_names,c_options,c_uses,c_link,upp_uses,includes,acceptflags))
	return src_names,c_options,c_uses,c_link,upp_uses,includes,acceptflags

registered_libs=[]

def add_upp_deps(ctx,ass,dep_pkg):
	# For now we assume the uses come from the
	# current assembly or from the uppsrc nest.
	# FIXME: is the [current_assembly, 'uppsrc'] list enough?
	for pkg in dep_pkg:
		found_lib = False
		for cur_ass in [ass, 'uppsrc', 'bazaar']:
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

	targetname = 'upp_' + pkg.replace('/','_')

	for lf in c_link.strip().split():
		ctx.env.append_unique('LINKFLAGS_UPPGLOBAL', lf)

	# Add u++ deps automatically
	add_upp_deps(ctx, ass, upp_uses.split())

	ctx.stlib(
		target = targetname,
		source = file_names,
		includes = ass + includes,
		export_includes = ass + includes,
		use = c_uses + ' UPPGLOBAL ' + upp_use_flags(ctx, upp_flags),
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
		use = c_uses + ' UPPGLOBAL ' + upp_use_flags(ctx, upp_flags),
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
	ctx.add_option('--flags', default='__use_mainconfig__', dest='flags', type='string',
		help="U++ use flags, space-separated. ex. '--flags='GUI .NOGTK'")

def configure(ctx):
	def check_ext_lib(pkg, use, mandat=False):
		return ctx.check_cfg(package=pkg, uselib_store=use, args=['--cflags', '--libs'], mandatory=mandat)
	ctx.load('compiler_c')
	ctx.load('compiler_cxx')
	ctx.env.STLIB_MARKER = ['-Wl,--whole-archive', '-Wl,-Bstatic']
	ctx.env.SHLIB_MARKER = ['-Wl,--no-whole-archive', '-Wl,-Bdynamic']
	ctx.check_cxx(lib='m', uselib_store='M')
	ctx.check_cxx(lib='z', uselib_store='Z')
	ctx.check_cxx(lib='rt', uselib_store='RT')
	ctx.check_cxx(lib='dl', uselib_store='DL')
	ctx.check_cxx(lib='asound', uselib_store='ASOUND', mandatory=False)
	ctx.check_cxx(lib='pthread', uselib_store='PTHREAD')
	ctx.check_cxx(lib='uuid', uselib_store='UUID')
	ctx.check_cxx(lib='Xft', uselib_store='XFT', mandatory=False)
	if ctx.options.flags == '__use_mainconfig__':
		ctx.env.use_mainconfig = True
		ctx.env.UPPFLAGS = UPPFLAGS
	else:
		ctx.env.use_mainconfig = False
		ctx.env.UPPFLAGS = UPPFLAGS + ' ' + ctx.options.flags
	if not ctx.options.nogtk and check_ext_lib('gtk+-2.0', 'GTK-X11-2.0'):
		check_ext_lib('libnotify', 'GTK-X11-2.0', True)
	else:
		ctx.env.UPPFLAGS += ' .NOGTK'
	if check_ext_lib('freetype2', 'FREETYPE'):
		if check_ext_lib('fontconfig', 'FONTCONFIG'):
			if not ctx.env.INCLUDES_FONTCONFIG: ctx.env.INCLUDES_FONTCONFIG = []
			ctx.env.INCLUDES_FONTCONFIG.extend(ctx.env.INCLUDES_FREETYPE)
	check_ext_lib('libpng', 'PNG')
	check_ext_lib('sdl', 'SDL')
	check_ext_lib('python-2.7', 'PYTHON2.7')
	for l in "AVUTIL AVCODEC AVFORMAT AVDEVICE SWSCALE AVCORE".split():
		ctx.check_cxx(lib=l.lower(), uselib_store=l, mandatory=False)
	ctx.env.prepend_value('CXXFLAGS', ['-x', 'c++'])
	try: ctx.env.append_unique('RPATH', os.environ['RPATH'])
	except KeyError: pass
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
	if ctx.env.use_mainconfig:
		print "Selected package: %s using flags %r (mainconfig)" % (pkgname, ctx.env.UPPFLAGS)
	else:
		print "Selected package: %s using flags %r (no mainconfig)" % (pkgname, ctx.env.UPPFLAGS)

	upp_app(ctx, pkgname)

