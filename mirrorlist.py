import os
from mod_python import apache
from urlparse import *
import httplib
import ConfigParser
from StringIO import *

CONFIG_PATH='/var/www/html/conf'
RELEASES_FILE='http://www.russianfedora.ru/releases.txt'

class MirrorList:
	def __init__(self, repo, arch):
		self.repo = repo
		self.arch = arch
		self.mlist = ''
		self.mirrors_list_file = 'mirrors.list'

		self.mlist += self._g_init_string()

		archs = self._get_config_file_as_list('archs.list')
		if self.arch not in archs:
			return

		workarounds = self._get_config_file_as_dict('workaround.list')
		if self.repo in workarounds.keys():
			if self.repo.find('build') == 0:
				self.mirrors_list_file = 'build-mirrors.list'
			# make workaround links
			mirrors = self._get_config_file_as_list(self.mirrors_list_file)	
			for m in mirrors:
				port = workarounds[self.repo].replace('$arch$', self.arch)
				wl = m + port + '\n'
				self.mlist += self._clear_slashes(wl)
			return

		self.repo_type = ''
		self.repo_params = {}
		self._init_repo()

		self.mlist += self._g_mirrors_strings()

	def _clear_slashes(self, raw):
		check_raw = raw
		found_scheme_separator = raw.find('://')
		if found_scheme_separator > -1:
			check_raw = raw[found_scheme_separator+3:]
		while check_raw.find('//') > -1:
			check_raw = check_raw.replace('//','/')

		raw = raw[:found_scheme_separator+3] + check_raw
		return raw


	def _get_param_by_key(self, d, key):
		if d.has_key(key):
			return d[key]
		return ''
	def _g_mirrors_strings(self):
		if ( len(self.repo_params.keys()) < 3 ):
			return ''

		ret_s = ''
		mirrors = self._get_config_file_as_list(self.mirrors_list_file)
		repos = self._get_config_file_as_dict('repos.list')
		variants = self._get_config_file_as_dict('variants.list')
		portions = self._get_config_file_as_dict('portions.list')
		
		for m in mirrors:
			variant = self.repo_params['variant']
			raw = variant.replace('$mirror$', m.strip())

			for k in self.repo_params.keys():
				if k == 'variant':
					continue
				str_key = '$%s$' % k
				val = self.repo_params[k]
				raw = raw.replace(str_key, val)

			ret_mirror = self._clear_slashes(raw)
			ret_s += ret_mirror + '\n' 

		return ret_s

	def _release_ver_is_present(self, version):
		if version.upper() == 'RAWHIDE':
			return True

		stable_releases = self._get_config_file_as_dict('releases.list')
		if version in stable_releases.keys():
			return True

		return False
	
	def _get_version_from_repo(self, repo_p):
		result_repo_p = []
		result_version= ''
		cut_version_pos = -1
		t_ver = repo_p[-1:][0]
		if t_ver.isdigit():
			result_version = t_ver
		else:
			if t_ver.find('.') > -1:
				result_version = self._remove_dot_version(t_ver)
			elif t_ver.upper() == 'RAWHIDE':
				result_version = t_ver
			else:
				cut_version_pos = -2
				result_version = self._remove_dot_version(repo_p[-2:-1][0])
		result_repo_p = repo_p[:cut_version_pos]
		return (result_version, result_repo_p)

	def _remove_dot_version(self, version):
		dot_found = version.find('.')
		if dot_found < 0:
			return version

		return version[:dot_found]

	def _init_repo_build(self):
		# 2010-10-14
		# changes for build
		repo_p = self.repo.split('-')
		arch   = self.arch
		variants = self._get_config_file_as_dict('variants.list')

		if repo_p[0] == 'build':
			self.mirrors_list_file = 'build-mirrors.list'
			(version, repo_p) = self._get_version_from_repo(repo_p)

			if not self._release_ver_is_present(version):
				return
			
			if self._is_stable_release(version):
				variant = 'build'
			else:
				variant = 'build-development'
			brepo_p = repo_p[1:]
			portion = str.join('-', brepo_p)

			self.repo_params['variant'] = self._get_param_by_key(variants, variant)
			self.repo_params['repos'] = ''
			self.repo_params['portion'] = portion
			self.repo_params['arch'] = arch
			self.repo_params['version'] = version
			return True
		return False

	def _init_repo(self):
		repo_p = self.repo.split('-')
		num = 0

		# checks
		if ( len(repo_p) < 3 ):
			return ''
	
		if repo_p[1] != 'fedora' and repo_p[0] != 'build':
			return

		variant = ''
		portion = ''
		version = ''
		repos   = repo_p[0]
		arch    = self.arch

		if self._init_repo_build() == True:
			return

		variants = self._get_config_file_as_dict('variants.list')
		(version, repo_p) = self._get_version_from_repo(repo_p)

		if len(repo_p) == 2:	# is main release
			variant = 'main'
			portion = 'main' 
		elif len(repo_p) == 3: # is main release, but with debug or source
			variant = 'main'
			portion = repo_p[2]
		elif len(repo_p) == 4: # is a updates or updates-testing
			if repo_p[3] == 'testing':
				variant = '%s-%s' % (repo_p[2], repo_p[3])
			elif repo_p[3] == 'released':
				variant = repo_p[2]

			portion = 'main'
		elif len(repo_p) == 5: # is a update or u-t, with d or s
			if repo_p[3] == 'testing':
				variant = '%s-%s' % (repo_p[2], repo_p[3])
			elif repo_p[3] == 'released':
				variant = repo_p[2]

			portion = repo_p[4]

		# second checks
		if portion == 'main':
			if variant not in [ 'main', 'development' ]:
				portion = ''
		elif portion == 'source':
			if variant in [ 'main', 'development' ]:
				arch = 'source/SRPMS'
				portion = ''
			else:
				arch = 'SRPMS'
				portion = ''
		
		#version = self._remove_dot_version(version)
		if not self._release_ver_is_present(version):
			return

		# check stable and rawhide
		if self._is_stable_release(version) == False:
			variant = 'development'

		# cookie dicts
		repos_l  = self._get_config_file_as_dict('repos.list')
		portions = self._get_config_file_as_dict('portions.list')

		if (variant not in variants.keys()) or (repos not in repos_l.keys()):
			return

		if len(portion) != 0 and portion not in portions.keys():
			return
		
		self.repo_params['variant'] = self._get_param_by_key(variants, variant)
		self.repo_params['repos'] = self._get_param_by_key(repos_l, repos)
		self.repo_params['portion'] = self._get_param_by_key(portions, portion)
		self.repo_params['arch'] = arch
		self.repo_params['version'] = version

	def _is_stable_release(self, version):
		if version.upper() == 'RAWHIDE':
			return False

		stable_releases = self._get_config_file_as_dict('releases.list')
		if version in stable_releases.keys():
			if ( stable_releases[version].upper() == 'STABLE' ):
				return True
		return False

	def _is_stable_release_by_releases_file(self, version):
		if version == 'rawhide':
			return False

		ret_res = False
		url = urlparse(RELEASES_FILE)
		netloc = ''
		path = ''
		
		if type(url) is tuple:
		    scheme = ''
		    p = q = f = ''
		    (scheme, netloc, path, p, q, f) = url
		else:
		    netloc = url.netloc
		    path   = url.path
		
		conn = httplib.HTTPConnection(netloc)
		conn.request("GET", path)
		res = conn.getresponse()
		if res.status == 200:
			raw_data = res.read()
			config = ConfigParser.RawConfigParser() #allow_no_value=True)
			
			config.readfp(StringIO(raw_data))
			for sect in config.sections():
				if config.get(sect, 'version') == version:
					r = config.get(sect, 'stable')
					if r.upper() == 'FALSE':
						ret_res = False
					else:
						ret_res = True #config.get(sect, 'stable')
					break

		return ret_res

	def _get_config_file_as_list(self, conf_file_name):
		full_file_path = os.path.join(CONFIG_PATH, conf_file_name)
		ret_l = []
		f = open(full_file_path, 'r')
		try:
			for l in f:
				# add 2010-10-21 (cut comments)
				cc_catch = l.find('#')
				if cc_catch > -1:
					l = l[:cc_catch]
				if ( len(l.strip()) == 0 ):
					continue
				ret_l.append(l.strip())
		finally:
			f.close()

		return ret_l
	
	def _get_config_file_as_dict(self, conf_file_name):
		ret_d = {}
		lst = self._get_config_file_as_list(conf_file_name)
		for l in lst:
			found = l.find('=')
			if found == 0:
				continue
			key = l[:found]
			value = l[found+1:]
			ret_d[key.strip()] = value.strip()
		return ret_d

	def _g_init_add_languages(self, init_str):
		langs = self._get_config_file_as_list('languages.list')
		for lang in langs:
			if len(lang.strip()) != 0:
				init_str += ' country = %s' % lang.strip()
		return init_str

	def _g_init_string(self):
		init_str = '# repo = %s arch = %s' % (self.repo, self.arch)
		init_str = self._g_init_add_languages(init_str)
		init_str += '\n'
		return init_str

	#def _g_init_string_path(self):
	#	init_str = '# path = %s' % (self.path)
	#	init_str = self._g_init_add_languages(init_str)
	#	init_str += '\n'
	#	return init_str

	def generate_list(self):
		return self.mlist

class MirrorListPath(MirrorList):
	def __init__(self, path):
		self.mlist = ''
		self.path = path
		self.mlist += self._g_init_string_path()
		mirrors = self._get_config_file_as_list('mirrors.list')
		for m in mirrors:
			url = m + '/' + path
			if url[-1:] != '/':
				url += '/'
			self.mlist += self._clear_slashes(url) + '\n'
	def _g_init_string_path(self):
		init_str = '# path = %s' % (self.path)
		init_str = self._g_init_add_languages(init_str)
		init_str += '\n'
		return init_str

def index(req, **options):
	req.content_type = "text/plain"
	req.send_http_header()
	ret = ''
	if options.has_key('repo') and options.has_key('arch'):
		ml = MirrorList(options['repo'], options['arch'])
		ret = ml.generate_list()
	elif options.has_key('path'):
		ml = MirrorListPath(options['path'])
		ret = ml.generate_list()
	req.write(ret)

	return
