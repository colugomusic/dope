from colorama import Fore, Style
from colorama import init as colorama_init
from dataclasses import dataclass
from git import Repo, GitCommandError
from hashlib import md5
from pathlib import Path
from ruamel.yaml import YAML
from typing import Optional
from urllib.parse import urlparse
import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
import traceback
import wget

DEPS_YML     = "deps.yml"
SETTINGS_YML = "settings.yml"
META_YML     = "meta.yml"

ERR_MSG_INSTALL_SUCCEEDED_BUT_PACKAGE_NOT_FOUND = (
	"Installation apparently succeeded but the package still cannot be found using CMake's find_package(). "
	"This is most likely because the install rules in the dependency's CMakeLists.txt are missing or incorrect."
)

@dataclass
class Dependency:
	name: str
	url: str = None
	git: str = None
	tag: str = None
	track: bool = False
	path: str = None
	remote_path: str = None
	build_type: str = None
	cmake_options: str = None
	cmake_options_mac: str = None
	cmake_options_lin: str = None
	cmake_options_win: str = None
	md5: str = None
	find_package_name: str = None
	installed_files: list[str] = None
	src_subdir: str = None
	add_src_files: bool = False
	spec_src: str = None

@dataclass
class DopeOptions:
	assets: str
	clean: bool
	config: list[str]
	fresh: bool
	project_name: str
	reacquires: list[str]
	reinstalls: list[str]
	reacquire_all: bool
	reinstall_all: bool
	excludes: list[str]
	root: str
	track: list[str]
	install_self: bool
	verbose: bool

@dataclass
class RootSettings:
	cmake_options: list[str]

@dataclass
class InstalledDepMeta:
	"""Metadata about an installed dependency stored in meta.yml"""
	name: str
	consumer: str  # Path to the project that installed this dependency
	url: str = None
	git: str = None
	tag: str = None
	path: str = None
	remote_path: str = None

def make_print_prefix(options:DopeOptions):
	return f'{options.project_name}'

def make_dep_print_prefix(dep:Dependency, options:DopeOptions):
	if options.project_name != "":
		return f'{options.project_name} -> {dep.name}'
	else:
		return f'{dep.name}'

def make_build_dir(config, root):
	return os.path.join(root, "build", config)

def make_install_dir(root:str, config:str=None):
	if config:
		return os.path.join(root, "install", config)
	return os.path.join(root, "install")

def make_src_dir(root):
	return os.path.join(root, "src")

def make_pkg_dir(root):
	return os.path.join(root, "pkg")

def make_dep_build_dir(dep:Dependency, config:Optional[str], root):
	return os.path.join(make_build_dir(config if config else "Multi-Config", root), dep.name)

def make_dep_src_unpack_dir(dep:Dependency, root):
	return os.path.join(make_src_dir(root), dep.name)

def get_version_from_url(url:str):
	path = urlparse(url).path
	filename = path.split("/")[-1]
	name, _, _ = filename.rpartition(".")
	match = re.search(r'(\d+(?:\.\d+)*(?:[A-Za-z0-9\-_]*)?)$', name)
	return match.group(1) if match else None

def get_filename_without_extension_from_url(url:str):
	path = urlparse(url).path
	filename = path.split("/")[-1]
	return filename.rpartition(".")[0]

def has_only_one_subdir(dir:str):
	return len(os.listdir(dir)) == 1

def get_subdirs_to_try(dep:Dependency, unpack_dir:str):
	subdirs = []
	subdirs.append(unpack_dir)
	if has_only_one_subdir(unpack_dir):
		subdirs.append(os.path.join(unpack_dir, os.listdir(unpack_dir)[0]))
	else:
		version                    = get_version_from_url(dep.url)
		filename_without_extension = get_filename_without_extension_from_url(dep.url)
		if version:
			subdirs.append(os.path.join(unpack_dir, dep.name + "-" + version))
		if filename_without_extension:
			subdirs.append(os.path.join(unpack_dir, dep.name + "-" + filename_without_extension))
	return subdirs

def make_dep_src_dir(dep:Dependency, root:str, cmake:bool):
	if dep.remote_path:
		return dep.remote_path
	unpack_dir = make_dep_src_unpack_dir(dep, root)
	if dep.url:
		if dep.src_subdir:
			return os.path.join(unpack_dir, dep.src_subdir)
		subdirs = get_subdirs_to_try(dep, unpack_dir)
		for subdir in subdirs:
			if cmake:
				if os.path.exists(os.path.join(subdir, "CMakeLists.txt")):
					return subdir
			else:
				if os.path.exists(subdir):
					return subdir
	return unpack_dir

def make_dep_script_path(dep:Dependency, assets_dir):
	return os.path.join(assets_dir, dep.name, "install.py")

def make_dep_src_add_dir(dep:Dependency, assets_dir):
	return os.path.join(assets_dir, dep.name, "src")

def make_pkg_check_dir(options:DopeOptions):
	return os.path.join(options.root, "pkg-check")

def run(cmd, verbose:bool, shell:bool=True, check:bool=True):
	if verbose:
		return subprocess.run(cmd, check=check, shell=shell)
	else:
		return subprocess.run(cmd, check=check, shell=shell, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def run_with_env(cmd, env, verbose, shell=True, check=True):
	if verbose:
		return subprocess.run(cmd, check=check, shell=shell, env=env)
	else:
		return subprocess.run(cmd, check=check, shell=shell, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def green(text):
	return f"{Fore.GREEN}{text}{Style.RESET_ALL}"

def cyan(text):
	return f"{Fore.CYAN}{text}{Style.RESET_ALL}"

def red(text):
	return f"{Fore.RED}{text}{Style.RESET_ALL}"

def yellow(text):
	return f"{Fore.YELLOW}{text}{Style.RESET_ALL}"

def parse_args(cwd):
	default_assets_path = cwd
	parser = argparse.ArgumentParser(description='Build/Install dependencies')
	parser.add_argument('-r', '--root', required=True, help='Where to build/install dependencies')
	parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
	parser.add_argument('-1', '--dep', action='append', help='Build/Install a specific dependency')
	parser.add_argument('-c', '--clean', action='store_true', help='Clean instead of build/install')
	parser.add_argument('-a', '--assets', default=default_assets_path, help='Path to assets directory')
	parser.add_argument('-f', '--fresh', action='store_true', help='Fresh build (clear CMake cache)')
	parser.add_argument('--config', action='append', help='Configuration to install (default: Debug + Release)')
	parser.add_argument('--project-name', type=str, default="", help='Project name')
	parser.add_argument('--reacquire', action='append', default=[], help='Reacquire a specific dependency, or "*" for all')
	parser.add_argument('--reinstall', action='append', default=[], help='Reinstall a specific dependency, or "*" for all')
	parser.add_argument('--track', action='append', default=[], help='Update tag to latest commit hash for a git dependency, or "*" for all with track=true')
	parser.add_argument('--exclude', action='append', default=[], help='Exclude a specific dependency from being processed')
	parser.add_argument('--install-self', action='store_true', help='Install all dependencies, then install the consumer project itself')
	return parser.parse_args()

def read_from_yaml(filepath:str):
	ryaml = YAML()
	with open(filepath, "r") as f:
		return ryaml.load(f)

def write_to_yaml(data:dict, filepath:str):
	ryaml = YAML()
	ryaml.preserve_quotes = True
	ryaml.width = 4096
	with open(filepath, "w") as f:
		ryaml.dump(data, f)

def read_settings_file(path:str):
	if not os.path.exists(path):
		raise FileNotFoundError(f"{path} not found. Did you remember to set the --assets argument?")
	return read_from_yaml(path)

def read_deps_file(path):
	if not os.path.exists(path):
		raise FileNotFoundError(f"{path} not found. Did you remember to set the --assets argument?")
	return read_from_yaml(path)

def get_meta_file_path(root:str):
	return os.path.join(root, META_YML)

def read_meta_file(root:str) -> dict:
	"""Read meta.yml from root, returning empty dict if not exists."""
	meta_path = get_meta_file_path(root)
	if not os.path.exists(meta_path):
		return {}
	return read_from_yaml(meta_path) or {}

def write_meta_file(root:str, meta:dict):
	"""Write meta.yml to root."""
	meta_path = get_meta_file_path(root)
	write_to_yaml(meta, meta_path)

def get_installed_dep_meta(root:str, dep_name:str) -> InstalledDepMeta:
	"""Get metadata for an installed dependency, or None if not found."""
	meta = read_meta_file(root)
	if dep_name not in meta:
		return None
	entry = meta[dep_name]
	return InstalledDepMeta(
		name=dep_name,
		consumer=entry.get('consumer'),
		url=entry.get('url'),
		git=entry.get('git'),
		tag=entry.get('tag'),
		path=entry.get('path'),
		remote_path=entry.get('remote-path')
	)

def save_installed_dep_meta(root:str, dep:Dependency, consumer_path:str):
	"""Save metadata for an installed dependency."""
	meta = read_meta_file(root)
	entry = {'consumer': consumer_path}
	if dep.url:
		entry['url'] = dep.url
	if dep.git:
		entry['git'] = dep.git
	if dep.tag:
		entry['tag'] = dep.tag
	if dep.path:
		entry['path'] = dep.path
	if dep.remote_path:
		entry['remote-path'] = dep.remote_path
	meta[dep.name] = entry
	write_meta_file(root, meta)

def check_dep_source_mismatch(dep:Dependency, options:DopeOptions) -> str:
	"""
	Check if the dependency source matches what's in meta.yml.
	Returns an error message if there's a mismatch, or None if OK.
	"""
	installed = get_installed_dep_meta(options.root, dep.name)
	if installed is None:
		return None  # Not installed yet, no mismatch possible
	
	# Check source type and values
	if dep.git:
		if installed.git != dep.git:
			return f"git repository mismatch: installed from '{installed.git}', but '{dep.git}' specified"
		if installed.tag != dep.tag:
			return f"git tag mismatch: installed with tag '{installed.tag}', but tag '{dep.tag}' specified"
	elif dep.url:
		if installed.url != dep.url:
			return f"url mismatch: installed from '{installed.url}', but '{dep.url}' specified"
	elif dep.path:
		if installed.path != dep.path:
			return f"path mismatch: installed from '{installed.path}', but '{dep.path}' specified"
	elif dep.remote_path:
		if installed.remote_path != dep.remote_path:
			return f"remote-path mismatch: installed from '{installed.remote_path}', but '{dep.remote_path}' specified"
	
	return None

def unpack_into(dep:Dependency, filepath, target_dir, options:DopeOptions):
	print(f"{green(make_dep_print_prefix(dep, options))} Unpacking {cyan(filepath)} into {cyan(target_dir)}")
	os.makedirs(target_dir, exist_ok=True)
	shutil.unpack_archive(filepath, target_dir)

def check_file_md5(filepath:str, md5_str:str):
	md5_hash = md5(open(filepath, "rb").read()).hexdigest()
	if md5_hash != md5_str:
		raise ValueError(f"MD5 checksum mismatch for {filepath}. Expected {md5_str}, got {md5_hash}")

def download_package(dep:Dependency, url:str, options:DopeOptions):
	print(f"{green(make_dep_print_prefix(dep, options))} Downloading from {cyan(dep.url)}")
	dep_pkg_dir = os.path.join(make_pkg_dir(options.root), dep.name)
	os.makedirs(dep_pkg_dir, exist_ok=True)
	filename = os.path.basename(url)
	filepath = os.path.join(dep_pkg_dir, filename)
	wget.download(url, filepath, bar=None)
	if dep.md5:
		check_file_md5(filepath, dep.md5)
	unpack_into(dep, filepath, make_dep_src_unpack_dir(dep, options.root), options)

def handle_remove_readonly(func, path, exc_info):
	# remove read-only attribute and retry
	os.chmod(path, stat.S_IWRITE)
	func(path)

def download_source_from_url(dep, options:DopeOptions, reacquire:bool):
	unpack_dir = make_dep_src_unpack_dir(dep, options.root)
	if os.path.exists(unpack_dir) and reacquire:
		shutil.rmtree(unpack_dir, onerror=handle_remove_readonly)
	if not os.path.exists(unpack_dir):
		download_package(dep, dep.url, options)
	else:
		if options.verbose:
			print(f"{green(make_dep_print_prefix(dep, options))} Skipping download from {cyan(dep.url)} because it already exists in {cyan(unpack_dir)}")

def reset_and_pull(dep:Dependency):
		repo = Repo(dep.git)
		if repo.bare:
			raise Exception("Bare repo, cannot reset")
		repo.git.reset("--hard")
		repo.git.clean("-fd")
		repo.remotes.origin.fetch()
		if dep.tag:
			repo.git.reset("--hard", f"origin/{dep.tag}")
		elif repo.head.is_detached:
			repo.git.reset("--hard", "origin/HEAD")
		else:
			repo.git.reset("--hard", f"origin/{repo.active_branch.name}")
		repo.git.submodule("sync", "--recursive")
		repo.git.submodule("update", "--init", "--recursive", "--force")
		for submodule in repo.submodules:
			sm_repo = submodule.module()
			sm_repo.git.reset("--hard")
			sm_repo.git.clean("-fd")
			sm_repo.remotes.origin.fetch()
			if sm_repo.head.is_detached:
				sm_repo.git.reset("--hard", "origin/HEAD")
			else:
				sm_repo.git.reset("--hard", f"origin/{sm_repo.active_branch.name}")
		return repo

def nuke_and_reclone(dep:Dependency, clone_dir:str):
	if os.path.exists(clone_dir):
		shutil.rmtree(clone_dir, onerror=handle_remove_readonly)
	repo = Repo.clone_from(dep.git, clone_dir)
	if dep.tag:
		repo.git.checkout(dep.tag)
	for submodule in repo.submodules:
		submodule.update(init=True, recursive=True)

def clone_source_from_git(dep:Dependency, options:DopeOptions, reacquire:bool):
	clone_dir = make_dep_src_dir(dep, options.root, dep.build_type == "cmake")
	if os.path.exists(clone_dir) and reacquire:
		if os.path.exists(os.path.join(clone_dir, ".git")):
			print(f'{green(make_dep_print_prefix(dep, options))} Pulling latest changes from {cyan(dep.git)}')
			try:
				reset_and_pull(clone_dir)
			except (GitCommandError, Exception) as e:
				nuke_and_reclone(dep, clone_dir)
			return
	if not os.path.exists(os.path.join(clone_dir, ".git")):
		print(f"{green(make_dep_print_prefix(dep, options))} Cloning from {cyan(dep.git)}")
		nuke_and_reclone(dep, clone_dir)
	else:
		if options.verbose:
			print(f"{green(make_dep_print_prefix(dep, options))} Skipping clone from {cyan(dep.git)} because it already exists in {cyan(clone_dir)}")

def copy_source_from_path(dep:Dependency, options:DopeOptions, reacquire:bool):
	copy_dir = make_dep_src_dir(dep, options.root, dep.build_type == "cmake")
	if os.path.exists(copy_dir) and reacquire:
		shutil.rmtree(copy_dir, onerror=handle_remove_readonly)
	if not os.path.exists(copy_dir):
		print(f"{green(make_dep_print_prefix(dep, options))} Copying from {cyan(dep.path)}")
		shutil.copytree(dep.path, copy_dir)
	else:
		if options.verbose:
			print(f"{green(make_dep_print_prefix(dep, options))} Skipping copy from {cyan(dep.path)} because it already exists in {cyan(copy_dir)}")

def add_src_files(dep:Dependency, options:DopeOptions):
	src_add_dir = make_dep_src_add_dir(dep, options.assets)
	src_dst_dir = make_dep_src_dir(dep, options.root, dep.build_type == "cmake")
	for file in os.listdir(src_add_dir):
		dst_file = os.path.join(src_dst_dir, file)
		print(f"{green(make_dep_print_prefix(dep, options))} Adding {cyan(dst_file)}")
		shutil.copy(os.path.join(src_add_dir, file), dst_file)

def get_source(dep:Dependency, options:DopeOptions, reacquire:bool):
	if dep.url:
		download_source_from_url(dep, options, reacquire)
	elif dep.git:
		clone_source_from_git(dep, options, reacquire)
	elif dep.path:
		copy_source_from_path(dep, options, reacquire)
	if dep.add_src_files:
		add_src_files(dep, options)

def translate_special_vars(strings:list[str], options:DopeOptions):
	for s in strings:
		s = s.replace("__dope_root__",       options.root)
		s = s.replace("__dope_on_linux__",   "ON" if sys.platform == "linux" else "OFF")
		s = s.replace("__dope_on_macos__",   "ON" if sys.platform == "darwin" else "OFF")
		s = s.replace("__dope_on_windows__", "ON" if sys.platform == "win32" else "OFF")
	return strings

def make_config_string(config:Optional[str]):
	return config if config else "Multi-Config"

def cmake_configure(dep:Dependency, build_dir:str, config:str, options:DopeOptions, root_settings:RootSettings):
	src_dir = make_dep_src_dir(dep, options.root, True)
	expected_cmake_lists = os.path.join(src_dir, "CMakeLists.txt")
	if not os.path.exists(expected_cmake_lists):
		if dep.url:
			raise FileNotFoundError(f"{expected_cmake_lists} not found. You may need to provide the 'src-subdir' option for this dependency, depending on the structure of the package archive.")
		else:
			raise FileNotFoundError(f"{expected_cmake_lists} not found.")
	install_dir = make_install_dir(options.root, config)
	cmake_cmd = []
	cmake_cmd.append('cmake')
	cmake_cmd.append('-B')
	cmake_cmd.append(build_dir)
	cmake_cmd.append('-S')
	cmake_cmd.append(src_dir)
	cmake_cmd.append('--install-prefix')
	cmake_cmd.append(install_dir)
	# Add all config-specific install directories to the prefix path so that
	# dependencies can find each other during the build.
	prefix_paths = [make_install_dir(options.root, c) for c in options.config]
	cmake_cmd.append(f'-DCMAKE_PREFIX_PATH={";".join(prefix_paths)}')
	cmake_cmd.append(f'-DCMAKE_BUILD_TYPE={config}')
	cmake_cmd.extend(translate_special_vars(root_settings.cmake_options, options))
	if options.fresh:
		cmake_cmd.append('--fresh')
	# Dependency-specific CMake options
	if dep.cmake_options:
		cmake_cmd.extend(dep.cmake_options.split(" "))
	if sys.platform == "darwin" and dep.cmake_options_mac:
		cmake_cmd.extend(dep.cmake_options_mac.split(" "))
	elif sys.platform == "linux" and dep.cmake_options_lin:
		cmake_cmd.extend(dep.cmake_options_lin.split(" "))
	elif sys.platform == "win32" and dep.cmake_options_win:
		cmake_cmd.extend(dep.cmake_options_win.split(" "))
	run(cmake_cmd, shell=False, verbose=options.verbose)

def cmake_clean(dep:Dependency, build_dir:str, config:str, options:DopeOptions):
	print(f"{green(make_dep_print_prefix(dep, options))} {cyan(make_config_string(config))} Clean")
	cmake_cmd = []
	cmake_cmd.append('cmake')
	cmake_cmd.append('--build')
	cmake_cmd.append(build_dir)
	cmake_cmd.append('--config')
	cmake_cmd.append(config)
	cmake_cmd.append('--target clean')
	run(cmake_cmd, shell=False, verbose=options.verbose)

def cmake_build(dep:Dependency, build_dir:str, config:str, options:DopeOptions):
	print(f"{green(make_dep_print_prefix(dep, options))} {cyan(make_config_string(config))} Build")
	cmake_cmd = []
	cmake_cmd.append('cmake')
	cmake_cmd.append('--build')
	cmake_cmd.append(build_dir)
	cmake_cmd.append('--config')
	cmake_cmd.append(config)
	run(cmake_cmd, shell=False, verbose=options.verbose)

def cmake_install(dep:Dependency, build_dir:str, config:str, options:DopeOptions):
	print(f"{green(make_dep_print_prefix(dep, options))} {cyan(make_config_string(config))} Install")
	cmake_cmd = []
	cmake_cmd.append('cmake')
	cmake_cmd.append('--install')
	cmake_cmd.append(build_dir)
	cmake_cmd.append('--config')
	cmake_cmd.append(config)
	run(cmake_cmd, shell=False, verbose=options.verbose)

def cmake_clean_or_build_and_install(dep:Dependency, build_dir:str, config:str, options:DopeOptions):
	if options.clean:
		cmake_clean(dep, build_dir, config, options)
	else:
		cmake_build(dep, build_dir, config, options)
		cmake_install(dep, build_dir, config, options)

def run_cmake(dep:Dependency, options:DopeOptions, root_settings:RootSettings):
	# We always configure/build/install each config separately, even if the
	# generator supports multi-config. This is because we use config-specific
	# CMAKE_INSTALL_INCLUDEDIR and CMAKE_INSTALL_LIBDIR to avoid overwriting
	# config-dependent headers (e.g. config.h) when installing multiple configs.
	for config in options.config:
		build_dir = make_dep_build_dir(dep, config, options.root)
		dep_print_prefix = make_dep_print_prefix(dep, options)
		print(f"{green(dep_print_prefix)} {cyan(config)} Configure")
		cmake_configure(dep, build_dir, config, options, root_settings)
		cmake_clean_or_build_and_install(dep, build_dir, config, options)

def run_script(dep:Dependency, options:DopeOptions):
	script_path = make_dep_script_path(dep, options.assets)
	if not os.path.exists(script_path):
		raise FileNotFoundError(f"{script_path} not found. Did you remember to set the --assets argument?")
	print(f"{green(make_dep_print_prefix(dep, options))} Running script {cyan(script_path)}")
	cmd = []
	cmd.append('python')
	cmd.append(script_path)
	cmd.append('--root')
	cmd.append(options.root)
	cmd.append('--assets')
	cmd.append(options.assets)
	if options.clean:
		cmd.append('--clean')
	for config in options.config:
		cmd.append('--config')
		cmd.append(config)
	if options.verbose:
		cmd.append('--verbose')
	env = os.environ.copy()
	package_root = Path(__file__).resolve().parent
	env["PYTHONPATH"] = str(package_root) + os.pathsep + env.get("PYTHONPATH", "")
	run_with_env(cmd, env, shell=False, verbose=options.verbose)

def install_dep(dep:Dependency, options:DopeOptions, root_settings:RootSettings):
	if dep.build_type == "cmake":
		run_cmake(dep, options, root_settings)
	elif dep.build_type == "py":
		run_script(dep, options)

def all_files_exist(files: list[str], install_dir:str):
	for file in files:
		if not os.path.exists(os.path.join(install_dir, file)):
			return False
	return True

def have_package_in_config(dep:Dependency, config:str, options:DopeOptions):
	install_dir = make_install_dir(options.root, config)
	if dep.installed_files:
		if all_files_exist(dep.installed_files, install_dir):
			return True
	# NOTE: i'm aware that CMake has a --find-package option but apparently
	# its usage is not recommended.
	pkg_check_dir = make_pkg_check_dir(options)
	os.makedirs(pkg_check_dir, exist_ok=True)
	find_package_name = dep.find_package_name or dep.name
	cmake_lists = os.path.join(pkg_check_dir, "CMakeLists.txt")
	with open(cmake_lists, "w") as f:
		f.write(f'cmake_minimum_required(VERSION 3.30)\n')
		f.write(f'project(dope-package-find-test CXX)\n')
		f.write(f'find_package({find_package_name} REQUIRED CONFIG)\n')
	cmake_cmd = []
	cmake_cmd.append('cmake')
	cmake_cmd.append('-B')
	cmake_cmd.append(pkg_check_dir)
	cmake_cmd.append('-S')
	cmake_cmd.append(pkg_check_dir)
	cmake_cmd.append(f'-DCMAKE_PREFIX_PATH={install_dir}')
	result = run(cmake_cmd, shell=False, verbose=options.verbose, check=False)
	return result.returncode == 0

def have_package(dep:Dependency, options:DopeOptions):
	"""Check if package is installed in all requested configs."""
	for config in options.config:
		if not have_package_in_config(dep, config, options):
			return False
	return True

def make_name_list_for_subdope(dep:Dependency, names:list[str], all:bool):
	if all:
		return ["*"]
	out = []
	for name in names:
		if is_deep_name(name):
			if name.startswith(f'{dep.name}/'):
				out.append(name[len(dep.name) + 1:])
	return out

def run_dope_if_present(dep:Dependency, options:DopeOptions, root_settings:RootSettings):
	src_dir = make_dep_src_dir(dep, options.root, dep.build_type == "cmake")
	assets_dir = os.path.join(src_dir, "dope")
	if os.path.exists(os.path.join(assets_dir, DEPS_YML)):
		cmd = []
		cmd.append(sys.executable)
		cmd.append(os.path.abspath(__file__))
		cmd.append('--assets')
		cmd.append(assets_dir)
		cmd.append('--root')
		cmd.append(options.root)
		cmd.append('--project-name')
		cmd.append(dep.name)
		if options.clean:
			cmd.append('--clean')
		if options.fresh:
			cmd.append('--fresh')
		if options.verbose:
			cmd.append('--verbose')
		for config in options.config:
			cmd.append('--config')
			cmd.append(config)
		reacquires = make_name_list_for_subdope(dep, options.reacquires, options.reacquire_all)
		for dep in reacquires:
			cmd.append('--reacquire')
			cmd.append(dep)
		reinstalls = make_name_list_for_subdope(dep, options.reinstalls, options.reinstall_all)
		for dep in reinstalls:
			cmd.append('--reinstall')
			cmd.append(dep)
		for dep in options.excludes:
			cmd.append('--exclude')
			cmd.append(dep)
		run(cmd, shell=False, verbose=True)

def merge_dep_lists(names:list[str], reinstall:list[str], reacquire:list[str]):
	merged = []
	merged.extend(names)
	merged.extend(reinstall)
	merged.extend(reacquire)
	merged = list(set(merged))
	return merged

def find_dependency_specification_in_deps_list(name:str, deps:list[Dependency], options:DopeOptions):
	return next((d for d in deps if d.name == name), None)

def check_if_installation_worked(dep:Dependency, options:DopeOptions):
	if not have_package(dep, options):
		print(f"{green(make_dep_print_prefix(dep, options))} {yellow(ERR_MSG_INSTALL_SUCCEEDED_BUT_PACKAGE_NOT_FOUND)}")

def is_dep_or_subdep(deep_name:str, name:str):
	if deep_name == name:
		return True
	if deep_name.endswith(f'/{name}'):
		return True
	return False

def should_reacquire(dep:Dependency, options:DopeOptions):
	return "*" in options.reacquires or dep.name in options.reacquires

def should_reinstall(dep:Dependency, options:DopeOptions):
	return "*" in options.reinstalls or dep.name in options.reinstalls or should_reacquire(dep, options)

def a_sub_dependency_needs_to_reacquire_or_reinstall(dep:Dependency, options:DopeOptions):
	for name in options.reacquires:
		if is_deep_name(name):
			if name.startswith(f'{dep.name}/'):
				return True
	for name in options.reinstalls:
		if is_deep_name(name):
			if name.startswith(f'{dep.name}/'):
				return True
	return False

def install_one_dep(dep:Dependency, options:DopeOptions, root_settings:RootSettings):
	# Check for source mismatch before anything else
	mismatch = check_dep_source_mismatch(dep, options)
	if mismatch:
		raise ValueError(f"Dependency '{dep.name}' source mismatch: {mismatch}")
	
	# If not in meta.yml yet, add it (even if already installed)
	installed_meta = get_installed_dep_meta(options.root, dep.name)
	if installed_meta is None:
		save_installed_dep_meta(options.root, dep, options.assets)
	
	reacquire = should_reacquire(dep, options)
	reinstall = should_reinstall(dep, options)
	this_dep_needs_reinstall = reinstall or not have_package(dep, options)
	a_sub_dep_needs_to_process = a_sub_dependency_needs_to_reacquire_or_reinstall(dep, options)
	if not this_dep_needs_reinstall and not a_sub_dep_needs_to_process:
		print(f"{green(make_dep_print_prefix(dep, options))} already installed")
		return
	options.excludes.append(dep.name)
	if this_dep_needs_reinstall:
		get_source(dep, options, reacquire)
	if this_dep_needs_reinstall or a_sub_dep_needs_to_process:
		run_dope_if_present(dep, options, root_settings)
	if this_dep_needs_reinstall:
		install_dep(dep, options, root_settings)
		check_if_installation_worked(dep, options)
		# Save/update metadata about this installed dependency
		save_installed_dep_meta(options.root, dep, options.assets)

def is_deep_name(name:str):
	return name.count("/") > 0

def find_and_install_one_dep(name:str, deps:list[Dependency], options:DopeOptions, root_settings:RootSettings):
	if is_deep_name(name):
		# skip as it will be processed when the parent is processed
		return
	dep = find_dependency_specification_in_deps_list(name, deps, options)
	if not dep:
		raise ValueError(f"Dependency {name} not found")
	install_one_dep(dep, options, root_settings)

def find_and_install_these_deps(names:list[str], deps:list[Dependency], options:DopeOptions, root_settings:RootSettings):
	for name in names:
		if not name in options.excludes:
			find_and_install_one_dep(name, deps, options, root_settings)

def install_all_deps(deps:list[Dependency], options:DopeOptions, root_settings:RootSettings):
	for dep in deps:
		if not dep.name in options.excludes:
			install_one_dep(dep, options, root_settings)

def get_platform_long_string():
	match sys.platform:
		case "win32":
			return "windows"
		case "linux":
			return "linux"
		case "darwin":
			return "macos"
		case _:
			raise ValueError(f"Unsupported platform: {sys.platform}")

def get_settings_file_path(options:DopeOptions):
	return os.path.join(options.root, SETTINGS_YML)

def get_cmake_options_from_dict(settings:dict):
	cmake_options = []
	platform_str = get_platform_long_string()
	if "cmake-options" in settings:
		cmake_options.extend(settings["cmake-options"])
	if platform_str in settings:
		platform_settings = settings[platform_str]
		if "cmake-options" in platform_settings:
			cmake_options.extend(platform_settings["cmake-options"])
	return cmake_options

def settings_from_dict(settings:dict):
	settings = RootSettings(cmake_options = get_cmake_options_from_dict(settings))
	return settings

def copy_settings_from_cwd_dope_if_needed(options:DopeOptions, cwd:str):
	"""
	If settings.yml doesn't exist in the root directory, check if it exists at
	(cwd)/dope/settings.yml. If found, copy it to root and print a warning.
	"""
	settings_file = get_settings_file_path(options)
	if os.path.exists(settings_file):
		return  # Already exists, nothing to do
	
	cwd_dope_settings = os.path.join(cwd, "dope", SETTINGS_YML)
	if os.path.exists(cwd_dope_settings):
		os.makedirs(options.root, exist_ok=True)
		shutil.copy(cwd_dope_settings, settings_file)
		print(yellow(f"WARNING: {SETTINGS_YML} was not found in {options.root}"))
		print(yellow(f"So I have copied {SETTINGS_YML} from {cwd_dope_settings} to {settings_file}."))
		print(yellow(f"This won't happen again. This is the file your root is going to use from now on."))
		print(yellow(f"Contents of {settings_file}:"))
		with open(settings_file, "r") as f:
			contents = f.read()
		print(yellow(contents))

def get_root_settings(options:DopeOptions, cwd:str):
	copy_settings_from_cwd_dope_if_needed(options, cwd)
	settings_file = get_settings_file_path(options)
	settings_dict = read_settings_file(settings_file) if os.path.exists(settings_file) else None
	return settings_from_dict(settings_dict) if settings_dict else RootSettings(cmake_options = [])

def find_assets_dir(assets_arg:str):
	if os.path.exists(os.path.join(assets_arg, DEPS_YML)):
		return assets_arg
	if os.path.exists(os.path.join(assets_arg, "dope", DEPS_YML)):
		return os.path.join(assets_arg, "dope")
	raise FileNotFoundError(f"Assets directory not found in {assets_arg}")

def to_dep(x:dict, deps_yml:str) -> Dependency:
	git = x["git"] if "git" in x else None
	tag = x["tag"] if "tag" in x else None
	track = x["track"] if "track" in x else False
	# tag is required for git deps, unless track=True (in which case tag will be auto-filled)
	if git is not None and tag is None and not track:
		raise ValueError(f"Dependency '{x['name']}' has 'git' specified but is missing required 'tag' field (or set track: true)")
	return Dependency(
		name=x["name"],
		url=x["url"] if "url" in x else None,
		git=git,
		tag=tag,
		track=track,
		path=x["path"] if "path" in x else None,
		remote_path=x["remote-path"] if "remote-path" in x else None,
		build_type=x["build-type"] if "build-type" in x else "cmake",
		cmake_options=x["cmake-options"] if "cmake-options" in x else None,
		cmake_options_mac=x["cmake-options-mac"] if "cmake-options-mac" in x else None,
		cmake_options_lin=x["cmake-options-lin"] if "cmake-options-lin" in x else None,
		cmake_options_win=x["cmake-options-win"] if "cmake-options-win" in x else None,
		md5=x["md5"] if "md5" in x else None,
		find_package_name=x["find-package-name"] if "find-package-name" in x else None,
		installed_files=x["installed-files"] if "installed-files" in x else [],
		src_subdir=x["src-subdir"] if "src-subdir" in x else None,
		add_src_files=x["add-src-files"] if "add-src-files" in x else False,
		spec_src=deps_yml
	)

def to_deps(deps:list[dict], deps_yml:str) -> list[Dependency]:
	if deps is None:
		return []
	return [to_dep(dep, deps_yml) for dep in deps]

def add_parents(names:list[str]):
	parents = set()
	for name in names:
		if is_deep_name(name):
			parents.add(name.split("/")[0])
	names.extend(parents)
	return names

def get_latest_commit_hash(git_url:str) -> str:
	"""Get the latest commit hash from the default branch of a remote git repository."""
	result = subprocess.run(
		['git', 'ls-remote', git_url, 'HEAD'],
		capture_output=True,
		text=True,
		check=True
	)
	# Output format is: "<hash>\tHEAD"
	output = result.stdout.strip()
	if output:
		return output.split()[0]
	raise ValueError(f"Could not get latest commit hash from {git_url}")

def update_tag_in_deps_file(deps_file:str, dep_name:str, new_tag:str):
	"""Update the tag field for a specific dependency in the deps.yml file."""
	ryaml = YAML()
	ryaml.preserve_quotes = True
	ryaml.width = 4096
	
	with open(deps_file, 'r') as f:
		deps_list = ryaml.load(f)
	
	old_tag = None
	for dep in deps_list:
		if dep.get('name') == dep_name:
			old_tag = dep.get('tag')
			if 'tag' in dep:
				dep['tag'] = new_tag
			else:
				# Insert 'tag' directly after 'git'
				keys = list(dep.keys())
				if 'git' in keys:
					git_idx = keys.index('git')
					dep.insert(git_idx + 1, 'tag', new_tag)
				else:
					dep['tag'] = new_tag
			break
	
	with open(deps_file, 'w') as f:
		ryaml.dump(deps_list, f)
	
	return old_tag

def track_one_dependency(dep:Dependency, options:DopeOptions) -> bool:
	"""Update the tag for a single git dependency with track=True to the latest commit hash.
	Returns True if the tag was updated, False otherwise."""
	print(f"{green(make_dep_print_prefix(dep, options))} Fetching latest commit hash from {cyan(dep.git)}")
	try:
		new_tag = get_latest_commit_hash(dep.git)
		if new_tag == dep.tag:
			print(f"{green(make_dep_print_prefix(dep, options))} Already at latest: {cyan(new_tag)}")
			return False
		else:
			old_tag = update_tag_in_deps_file(dep.spec_src, dep.name, new_tag)
			print(f"{green(make_dep_print_prefix(dep, options))} Updated tag: {cyan(old_tag)} -> {cyan(new_tag)}")
			dep.tag = new_tag  # Update in-memory too
			return True
	except Exception as e:
		print(f"{red(make_dep_print_prefix(dep, options))} Failed to track: {e}")
		return False

def should_track_dep(dep:Dependency, options:DopeOptions) -> bool:
	"""Determine if a dependency should be tracked based on options.track list."""
	if not dep.git:
		return False
	# If specific dep name is in track list, track it regardless of track field
	if dep.name in options.track:
		return True
	# If '*' is in track list, track all git deps with track=True
	if "*" in options.track and dep.track:
		return True
	return False

def track_dependencies(deps:list[Dependency], options:DopeOptions):
	"""Update tags for git dependencies based on the track list.
	Adds any updated dependencies to the reacquires list."""
	for dep in deps:
		if should_track_dep(dep, options):
			if track_one_dependency(dep, options):
				# Tag was updated, add to reacquires
				if dep.name not in options.reacquires:
					options.reacquires.append(dep.name)

def track_subdependencies(dep:Dependency, options:DopeOptions):
	"""Run tracking on sub-dependencies of a git dependency."""
	src_dir = make_dep_src_dir(dep, options.root, dep.build_type == "cmake")
	assets_dir = os.path.join(src_dir, "dope")
	if os.path.exists(os.path.join(assets_dir, DEPS_YML)):
		cmd = []
		cmd.append(sys.executable)
		cmd.append(os.path.abspath(__file__))
		cmd.append('--assets')
		cmd.append(assets_dir)
		cmd.append('--root')
		cmd.append(options.root)
		cmd.append('--project-name')
		cmd.append(dep.name)
		cmd.append('--track')
		cmd.append('*')
		run(cmd, shell=False, verbose=True)

def auto_track_deps_missing_tag(deps:list[Dependency], options:DopeOptions):
	"""Auto-track git dependencies with track=True that are missing a tag."""
	for dep in deps:
		if dep.git and dep.track and dep.tag is None:
			print(f"{green(make_dep_print_prefix(dep, options))} Auto-tracking (missing tag)")
			track_one_dependency(dep, options)
			# Reload the tag from the updated deps file
			updated_deps_list = read_deps_file(dep.spec_src)
			for updated_dep in updated_deps_list:
				if updated_dep.get('name') == dep.name:
					dep.tag = updated_dep.get('tag')
					break

def make_self_dependency(assets_dir:str) -> Dependency:
	"""Create a Dependency object representing the consumer project itself.
	The consumer project is the parent directory of the assets (dope) folder."""
	consumer_dir = os.path.dirname(assets_dir)
	project_name = os.path.basename(consumer_dir)
	return Dependency(
		name=project_name,
		remote_path=consumer_dir,
		build_type="cmake"
	)

def install_self(options:DopeOptions, root_settings:RootSettings):
	"""Install the consumer project itself as a dependency."""
	self_dep = make_self_dependency(options.assets)
	print(f"{green(make_dep_print_prefix(self_dep, options))} Installing self...")
	install_dep(self_dep, options, root_settings)
	check_if_installation_worked(self_dep, options)

def main():
	colorama_init()
	cwd           = os.getcwd()
	args          = parse_args(cwd)
	assets_dir    = find_assets_dir(args.assets)
	deps_file     = os.path.join(assets_dir, DEPS_YML)
	deps          = to_deps(read_deps_file(deps_file), deps_file)
	names         = args.dep or []
	options = DopeOptions(
		assets=assets_dir,
		clean=args.clean,
		config=args.config or ["Debug", "Release"],
		fresh=args.fresh,
		project_name=args.project_name,
		reacquires=args.reacquire,
		reinstalls=args.reinstall,
		reacquire_all=False,
		reinstall_all=False,
		excludes=args.exclude,
		root=args.root,
		track=args.track,
		install_self=args.install_self,
		verbose=args.verbose
	)
	root_settings = get_root_settings(options, cwd)
	if deps is None:
		print(f'{green(make_print_prefix(options))} {yellow(f"No dependencies found in {cyan(deps_file)}")}')
		return
	if "*" in options.reacquires:
		options.reacquires = [d.name for d in deps]
		options.reacquire_all = True
	if "*" in options.reinstalls:
		options.reinstalls = [d.name for d in deps]
		options.reinstall_all = True
	try:
		# Auto-track any git deps with track=True that are missing a tag
		auto_track_deps_missing_tag(deps, options)
		if options.track:
			track_dependencies(deps, options)
			# Also forward --track * to sub-dependencies of tracked git deps
			for dep in deps:
				if should_track_dep(dep, options):
					track_subdependencies(dep, options)
			# Continue to install any deps that were updated (now in reacquires)
		if len(names) + len(options.reacquires) + len(options.reinstalls) > 0:
			names = merge_dep_lists(names, options.reinstalls, options.reacquires)
			names = add_parents(names)
			find_and_install_these_deps(names, deps, options, root_settings)
		else:
			install_all_deps(deps, options, root_settings)
		# Install the consumer project itself if requested
		if options.install_self:
			install_self(options, root_settings)
	except Exception as e:
		print(traceback.format_exc())
		print(f'{red(make_print_prefix(options))} {red(f"Error: {e}")}')
		sys.exit(1)

if __name__ == "__main__":
	main()
