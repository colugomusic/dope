from typing import Optional
from colorama import Fore, Style
from colorama import init as colorama_init
from dataclasses import dataclass
from git import Repo
from pathlib import Path
from urllib.parse import urlparse
from hashlib import md5
import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
import traceback
import wget
import yaml

DEPS_YML     = "deps.yml"
SETTINGS_YML = "settings.yml"

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
	path: str = None
	build_type: str = None
	cmake_options: str = None
	cmake_options_mac: str = None
	cmake_options_lin: str = None
	cmake_options_win: str = None
	md5: str = None
	find_package_name: str = None
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
	reacquire: list[str]
	reinstall: list[str]
	root: str
	verbose: bool

@dataclass
class RootSettings:
	cmake_options: list[str]

def make_print_prefix(options:DopeOptions):
	return f'{options.project_name}'

def make_dep_print_prefix(dep:Dependency, options:DopeOptions):
	if options.project_name != "":
		return f'{options.project_name} -> {dep.name}'
	else:
		return f'{dep.name}'

def make_build_dir(config, root):
	return os.path.join(root, "build", config)

def make_install_dir(root):
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

def get_subdirs_to_try(dep:Dependency, unpack_dir:str):
	version                    = get_version_from_url(dep.url)
	filename_without_extension = get_filename_without_extension_from_url(dep.url)
	subdirs = []
	if version:
		subdirs.append(os.path.join(unpack_dir, dep.name + "-" + version))
	if filename_without_extension:
		subdirs.append(os.path.join(unpack_dir, dep.name + "-" + filename_without_extension))
	return subdirs

def make_dep_src_dir(dep:Dependency, root):
	unpack_dir = make_dep_src_unpack_dir(dep, root)
	if dep.url:
		if dep.src_subdir:
			return os.path.join(unpack_dir, dep.src_subdir)
		subdirs = get_subdirs_to_try(dep, unpack_dir)
		for subdir in subdirs:
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
	parser.add_argument('--reacquire', action='append', help='Reacquire a specific dependency, or "*" for all')
	parser.add_argument('--reinstall', action='append', help='Reinstall a specific dependency, or "*" for all')
	return parser.parse_args()

def read_from_yaml(filepath:str):
	with open(filepath, "r") as f:
		return yaml.safe_load(f)

def write_to_yaml(dict:dict, filepath:str):
	with open(filepath, "w") as f:
		yaml.dump(dict, f)

def read_settings_file(path:str):
	if not os.path.exists(path):
		raise FileNotFoundError(f"{path} not found. Did you remember to set the --assets argument?")
	return read_from_yaml(path)

def read_deps_file(path):
	if not os.path.exists(path):
		raise FileNotFoundError(f"{path} not found. Did you remember to set the --assets argument?")
	return read_from_yaml(path)

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
		print(f"{green(make_dep_print_prefix(dep, options))} Skipping download from {cyan(dep.url)} because it already exists in {cyan(unpack_dir)}")

def clone_source_from_git(dep:Dependency, options:DopeOptions, reacquire:bool):
	url = dep.git
	clone_dir = make_dep_src_dir(dep, options.root)
	if os.path.exists(clone_dir) and reacquire:
		shutil.rmtree(clone_dir, onerror=handle_remove_readonly)
	if not os.path.exists(clone_dir):
		print(f"{green(make_dep_print_prefix(dep, options))} Cloning from {cyan(url)}")
		repo = Repo.clone_from(url, clone_dir)
		if dep.tag:
			repo.git.checkout(dep.tag)
	else:
		print(f"{green(make_dep_print_prefix(dep, options))} Skipping clone from {cyan(url)} because it already exists in {cyan(clone_dir)}")

def copy_source_from_path(dep:Dependency, options:DopeOptions, reacquire:bool):
	copy_dir = make_dep_src_dir(dep, options.root)
	if os.path.exists(copy_dir) and reacquire:
		shutil.rmtree(copy_dir, onerror=handle_remove_readonly)
	if not os.path.exists(copy_dir):
		print(f"{green(make_dep_print_prefix(dep, options))} Copying from {cyan(dep.path)}")
		shutil.copytree(dep.path, copy_dir)
	else:
		print(f"{green(make_dep_print_prefix(dep, options))} Skipping copy from {cyan(dep.path)} because it already exists in {cyan(copy_dir)}")

def add_src_files(dep:Dependency, options:DopeOptions):
	src_add_dir = make_dep_src_add_dir(dep, options.assets)
	src_dst_dir = make_dep_src_dir(dep, options.root)
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

def read_cmake_cache(dep:Dependency, config:str, options:DopeOptions):
	build_dir = make_dep_build_dir(dep, config, options.root)
	cmake_cache_path = os.path.join(build_dir, "CMakeCache.txt")
	if not os.path.exists(cmake_cache_path):
		raise FileNotFoundError(f"{cmake_cache_path} not found.")
	with open(cmake_cache_path, "r") as f:
		return f.read()

def is_multi_config_generator(generator:str):
	if generator == "Ninja":
		return True
	if generator.startswith("Visual Studio"):
		return True
	return False

def is_multi_config(dep:Dependency, config:str, options:DopeOptions):
	cmake_cache:str = read_cmake_cache(dep, config, options)
	lines = cmake_cache.split("\n")
	for line in lines:
		if line.startswith("CMAKE_GENERATOR:INTERNAL="):
			return is_multi_config_generator(line.split("=")[1].strip())
	return False

def cmake_configure(dep:Dependency, build_dir:str, config:Optional[str], options:DopeOptions, root_settings:RootSettings):
	src_dir = make_dep_src_dir(dep, options.root)
	expected_cmake_lists = os.path.join(src_dir, "CMakeLists.txt")
	if not os.path.exists(expected_cmake_lists):
		if dep.url:
			raise FileNotFoundError(f"{expected_cmake_lists} not found. You may need to provide the 'src-subdir' option for this dependency, depending on the structure of the package archive.")
		else:
			raise FileNotFoundError(f"{expected_cmake_lists} not found.")
	cmake_cmd = []
	cmake_cmd.append('cmake')
	cmake_cmd.append('-B')
	cmake_cmd.append(build_dir)
	cmake_cmd.append('-S')
	cmake_cmd.append(make_dep_src_dir(dep, options.root))
	cmake_cmd.append('--install-prefix')
	cmake_cmd.append(make_install_dir(options.root))
	cmake_cmd.append(f'-DCMAKE_PREFIX_PATH={make_install_dir(options.root)}')
	if config:
		cmake_cmd.append(f'-DCMAKE_BUILD_TYPE={config}')
	cmake_cmd.extend(translate_special_vars(root_settings.cmake_options, options))
	if options.fresh:
		cmake_cmd.append('--fresh')
	# Dependency-specific CMake options
	if dep.cmake_options:
		cmake_cmd.append(dep.cmake_options)
	if sys.platform == "darwin" and dep.cmake_options_mac:
		cmake_cmd.append(dep.cmake_options_mac)
	elif sys.platform == "linux" and dep.cmake_options_lin:
		cmake_cmd.append(dep.cmake_options_lin)
	elif sys.platform == "win32" and dep.cmake_options_win:
		cmake_cmd.append(dep.cmake_options_win)
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
	did_first_configure:bool = False
	multi_config:bool = False
	multi_config_build_dir:str = None
	for config in options.config:
		should_configure = not (multi_config and did_first_configure)
		build_dir = make_dep_build_dir(dep, config, options.root)
		if should_configure:
			dep_print_prefix = make_dep_print_prefix(dep, options)
			print(f"{green(dep_print_prefix)} Configure...", end="", flush=True)
			cmake_configure(dep, build_dir, config, options, root_settings)
			if not did_first_configure:
				multi_config           = is_multi_config(dep, config, options)
				multi_config_build_dir = build_dir
				if multi_config:
					print(f'\r{green(dep_print_prefix)} {cyan("Multi-Config")} Configure')
				else:
					print(f'\r{green(dep_print_prefix)} {cyan(config)} Configure')
			else:
				print(f'\r{green(dep_print_prefix)} {cyan(config)} Configure')
		cmake_clean_or_build_and_install(dep, multi_config_build_dir if multi_config else build_dir, config, options)
		did_first_configure = True

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

def have_package(dep:Dependency, options:DopeOptions):
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
	cmake_cmd.append(f'-DCMAKE_PREFIX_PATH={make_install_dir(options.root)}')
	result = run(cmake_cmd, shell=False, verbose=options.verbose, check=False)
	return result.returncode == 0

def make_name_list_for_subdope(dep:Dependency, names:list[str]):
	out = []
	for name in names:
		if is_deep_name(name):
			if name.startswith(f'{dep.name}/'):
				out.append(name[len(dep.name) + 1:])
	return out

def run_dope_if_present(dep:Dependency, options:DopeOptions, root_settings:RootSettings):
	src_dir = make_dep_src_dir(dep, options.root)
	assets_dir = os.path.join(src_dir, "dope")
	reacquire = make_name_list_for_subdope(dep, options.reacquire)
	reinstall = make_name_list_for_subdope(dep, options.reinstall)
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
		for dep in reacquire:
			cmd.append('--reacquire')
			cmd.append(dep)
		for dep in reinstall:
			cmd.append('--reinstall')
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

def remove_dep_from_lists(dep:Dependency, options:DopeOptions):
	if dep.name in options.reacquire:
		options.reacquire.remove(dep.name)
	if dep.name in options.reinstall:
		options.reinstall.remove(dep.name)

def should_reacquire(dep:Dependency, options:DopeOptions):
	return "*" in options.reacquire or dep.name in options.reacquire

def should_reinstall(dep:Dependency, options:DopeOptions):
	return "*" in options.reinstall or dep.name in options.reinstall or should_reacquire(dep, options)

def a_sub_dependency_needs_to_reacquire_or_reinstall(dep:Dependency, options:DopeOptions):
	for name in options.reacquire:
		if is_deep_name(name):
			if name.startswith(f'{dep.name}/'):
				return True
	for name in options.reinstall:
		if is_deep_name(name):
			if name.startswith(f'{dep.name}/'):
				return True
	return False

def install_one_dep(dep:Dependency, options:DopeOptions, root_settings:RootSettings):
	reacquire = should_reacquire(dep, options)
	reinstall = should_reinstall(dep, options)
	this_dep_needs_reinstall = reinstall or not have_package(dep, options)
	a_sub_dep_needs_to_process = a_sub_dependency_needs_to_reacquire_or_reinstall(dep, options)
	if not this_dep_needs_reinstall and not a_sub_dep_needs_to_process:
		print(f"{green(make_dep_print_prefix(dep, options))} already installed")
		return
	remove_dep_from_lists(dep, options)
	if this_dep_needs_reinstall:
		get_source(dep, options, reacquire)
	if this_dep_needs_reinstall or a_sub_dep_needs_to_process:
		run_dope_if_present(dep, options, root_settings)
	if this_dep_needs_reinstall:
		install_dep(dep, options, root_settings)
		check_if_installation_worked(dep, options)

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
		find_and_install_one_dep(name, deps, options, root_settings)

def install_all_deps(deps:list[Dependency], options:DopeOptions, root_settings:RootSettings):
	for dep in deps:
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

def get_root_settings(options:DopeOptions):
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
	return Dependency(
		name=x["name"],
		url=x["url"] if "url" in x else None,
		git=x["git"] if "git" in x else None,
		tag=x["tag"] if "tag" in x else None,
		path=x["path"] if "path" in x else None,
		build_type=x["build-type"] if "build-type" in x else "cmake",
		cmake_options=x["cmake-options"] if "cmake-options" in x else None,
		cmake_options_mac=x["cmake-options-mac"] if "cmake-options-mac" in x else None,
		cmake_options_lin=x["cmake-options-lin"] if "cmake-options-lin" in x else None,
		cmake_options_win=x["cmake-options-win"] if "cmake-options-win" in x else None,
		md5=x["md5"] if "md5" in x else None,
		find_package_name=x["find-package-name"] if "find-package-name" in x else None,
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
		reacquire=args.reacquire or [],
		reinstall=args.reinstall or [],
		root=args.root,
		verbose=args.verbose
	)
	root_settings = get_root_settings(options)
	if deps is None:
		print(f'{green(make_print_prefix(options))} {yellow(f"No dependencies found in {cyan(deps_file)}")}')
		return
	if "*" in options.reacquire:
		options.reacquire = [d.name for d in deps]
	if "*" in options.reinstall:
		options.reinstall = [d.name for d in deps]
	try:
		if len(names) + len(options.reacquire) + len(options.reinstall) > 0:
			names = merge_dep_lists(names, options.reinstall, options.reacquire)
			names = add_parents(names)
			find_and_install_these_deps(names, deps, options, root_settings)
		else:
			install_all_deps(deps, options, root_settings)
	except Exception as e:
		print(traceback.format_exc())
		print(f'{red(make_print_prefix(options))} {red(f"Error: {e}")}')
		sys.exit(1)

if __name__ == "__main__":
	main()