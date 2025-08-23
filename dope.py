from colorama import Fore, Style
from colorama import init as colorama_init
from deepmerge import always_merger
from git import Repo
from pathlib import Path
from dataclasses import dataclass
import argparse
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import yaml
import wget

DEPS_YML         = "deps.yml"
SETTINGS_YML     = "settings.yml"
SETTINGS_WIN_YML = "settings-win.yml"
SETTINGS_LIN_YML = "settings-lin.yml"
SETTINGS_MAC_YML = "settings-mac.yml"

@dataclass
class DopeOptions:
	assets: str
	clean: bool
	cmake_options: str
	fresh: bool
	project_name: str
	reacquire: bool
	reinstall: bool
	reacquire1: list[str]
	reinstall1: list[str]
	root: str
	settings: dict
	verbose: bool

def make_print_prefix(options:DopeOptions):
	return f'{options.project_name}'

def make_dep_print_prefix(dep, options:DopeOptions):
	if options.project_name != "":
		return f'{options.project_name} -> {dep["name"]}'
	else:
		return f'{dep["name"]}'

def make_build_dir(config, root):
	return os.path.join(root, "build", config)

def make_install_dir(root):
	return os.path.join(root, "install")

def make_src_dir(root):
	return os.path.join(root, "src")

def make_pkg_dir(root):
	return os.path.join(root, "pkg")

def make_dep_build_dir(dep, config, root):
	return os.path.join(make_build_dir(config, root), dep["name"])

def make_dep_src_unpack_dir(dep, root):
	return os.path.join(make_src_dir(root), dep["name"])

def make_dep_src_dir(dep, root):
	if "src_subdir" in dep:
		return os.path.join(make_dep_src_unpack_dir(dep, root), dep["src_subdir"])
	else:
		return make_dep_src_unpack_dir(dep, root)

def make_dep_script_path(dep, assets_dir):
	return os.path.join(assets_dir, dep["name"], "install.py")

def make_dep_src_add_dir(dep, assets_dir):
	return os.path.join(assets_dir, dep["name"], "src")

def make_pkg_check_dir(root):
	return os.path.join(root, "pkg-check")

def run(cmd, verbose, check=True):
	if verbose:
		return subprocess.run(cmd, check=check, shell=True)
	else:
		return subprocess.run(cmd, check=check, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def run_with_env(cmd, env, verbose, check=True):
	if verbose:
		return subprocess.run(cmd, check=check, shell=True, env=env)
	else:
		return subprocess.run(cmd, check=check, shell=True, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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
	parser.add_argument('--project-name', type=str, default="", help='Project name')
	parser.add_argument('--cmake-options', type=str, default="", help='Additional CMake options')
	parser.add_argument('--reinstall', action='store_true', help='Reinstall packages')
	parser.add_argument('--reacquire', action='store_true', help='Reacquire packages')
	parser.add_argument('--reacquire1', action='append', help='Reacquire a specific dependency')
	parser.add_argument('--reinstall1', action='append', help='Reinstall a specific dependency')
	return parser.parse_args()

def read_settings_file(path):
	if not os.path.exists(path):
		raise FileNotFoundError(f"{path} not found. Did you remember to set the --assets argument?")
	with open(path, "r") as f:
		return yaml.safe_load(f)

def read_deps_file(path):
	if not os.path.exists(path):
		raise FileNotFoundError(f"{path} not found. Did you remember to set the --assets argument?")
	with open(path, "r") as f:
		return yaml.safe_load(f)

def unpack_into(dep, filepath, target_dir, options:DopeOptions):
	print(f"{green(make_dep_print_prefix(dep, options))} Unpacking {cyan(filepath)} into {cyan(target_dir)}")
	os.makedirs(target_dir, exist_ok=True)
	shutil.unpack_archive(filepath, target_dir)

def download_package(dep, url:str, options:DopeOptions):
	print(f"{green(make_dep_print_prefix(dep, options))} Downloading from {cyan(dep['url'])}")
	dep_pkg_dir = os.path.join(make_pkg_dir(options.root), dep["name"])
	os.makedirs(dep_pkg_dir, exist_ok=True)
	filename = os.path.basename(url)
	filepath = os.path.join(dep_pkg_dir, filename)
	wget.download(url, filepath, bar=None)
	unpack_into(dep, filepath, make_dep_src_unpack_dir(dep, options.root), options)

def handle_remove_readonly(func, path, exc_info):
	# remove read-only attribute and retry
	os.chmod(path, stat.S_IWRITE)
	func(path)

def should_reacquire(dep, options:DopeOptions):
	if options.reacquire:
		return True
	if options.reacquire1:
		return dep["name"] in options.reacquire1
	return False

def should_reinstall(dep, options:DopeOptions):
	if options.reinstall:
		return True
	if options.reinstall1:
		return dep["name"] in options.reinstall1
	return should_reacquire(dep, options)

def download_source_from_url(dep, options:DopeOptions):
	url = dep["url"]
	unpack_dir = make_dep_src_unpack_dir(dep, options.root)
	if os.path.exists(unpack_dir) and should_reacquire(dep, options):
		shutil.rmtree(unpack_dir, onerror=handle_remove_readonly)
	if not os.path.exists(unpack_dir):
		download_package(dep, url, options)
	else:
		print(f"{green(make_dep_print_prefix(dep, options))} Skipping download from {cyan(url)} because it already exists in {cyan(unpack_dir)}")

def clone_source_from_git(dep, options:DopeOptions):
	url = dep["git"]
	clone_dir = make_dep_src_dir(dep, options.root)
	if os.path.exists(clone_dir) and should_reacquire(dep, options):
		shutil.rmtree(clone_dir, onerror=handle_remove_readonly)
	if not os.path.exists(clone_dir):
		print(f"{green(make_dep_print_prefix(dep, options))} Cloning from {cyan(url)}")
		repo = Repo.clone_from(url, clone_dir)
		if "tag" in dep:
			repo.git.checkout(dep["tag"])
	else:
		print(f"{green(make_dep_print_prefix(dep, options))} Skipping clone from {cyan(url)} because it already exists in {cyan(clone_dir)}")

def copy_source_from_path(dep, options:DopeOptions):
	path = dep["path"]
	copy_dir = make_dep_src_dir(dep, options.root)
	if os.path.exists(copy_dir) and should_reacquire(dep, options):
		shutil.rmtree(copy_dir, onerror=handle_remove_readonly)
	if not os.path.exists(copy_dir):
		print(f"{green(make_dep_print_prefix(dep, options))} Copying from {cyan(path)}")
		shutil.copytree(path, copy_dir)
	else:
		print(f"{green(make_dep_print_prefix(dep, options))} Skipping copy from {cyan(path)} because it already exists in {cyan(copy_dir)}")

def add_src_files(dep, options:DopeOptions):
	src_add_dir = make_dep_src_add_dir(dep, options.assets)
	src_dst_dir = make_dep_src_dir(dep, options.root)
	for file in os.listdir(src_add_dir):
		dst_file = os.path.join(src_dst_dir, file)
		print(f"{green(make_dep_print_prefix(dep, options))} Adding {cyan(dst_file)}")
		shutil.copy(os.path.join(src_add_dir, file), dst_file)

def get_source(dep, options:DopeOptions):
	if "url" in dep:
		download_source_from_url(dep, options)
	elif "git" in dep:
		clone_source_from_git(dep, options)
	elif "path" in dep:
		copy_source_from_path(dep, options)
	if "add-src-files" in dep and dep["add-src-files"]:
		add_src_files(dep, options)

def translate_special_vars(string:str, options:DopeOptions):
	string = string.replace("__dope_root__",       options.root)
	string = string.replace("__dope_on_linux__",   "ON" if sys.platform == "linux" else "OFF")
	string = string.replace("__dope_on_macos__",   "ON" if sys.platform == "darwin" else "OFF")
	string = string.replace("__dope_on_windows__", "ON" if sys.platform == "win32" else "OFF")
	return string

def get_untranslated_cmake_options(options:DopeOptions):
	# CMake options passed in as a command line argument take
	# precedence over the options in the settings file.
	if options.cmake_options != "":
		return options.cmake_options
	else:
		if "cmake-options" in options.settings:
			return " ".join(options.settings["cmake-options"])
		else:
			return ""

def make_global_cmake_options(options:DopeOptions):
	return translate_special_vars(get_untranslated_cmake_options(options), options)

def cmake_configure(dep, config, options:DopeOptions):
	print(f"{green(make_dep_print_prefix(dep, options))} {cyan(config)} Configure")
	cmake_cmd = 'cmake'
	cmake_cmd += f' -B "{make_dep_build_dir(dep, config, options.root)}"'
	cmake_cmd += f' -S "{make_dep_src_dir(dep, options.root)}"'
	cmake_cmd += f' --install-prefix "{make_install_dir(options.root)}"'
	cmake_cmd += f' -DCMAKE_PREFIX_PATH="{make_install_dir(options.root)}"'
	cmake_cmd += f' -DCMAKE_BUILD_TYPE={config}'
	cmake_cmd += f' {make_global_cmake_options(options)}'
	if options.fresh:
		cmake_cmd += ' --fresh'
	# Dependency-specific CMake options
	if "cmake-options" in dep:
		cmake_cmd += f" {dep['cmake-options']}"
	if sys.platform == "darwin" and "cmake-options-mac" in dep:
		cmake_cmd += f" {dep['cmake-options-mac']}"
	elif sys.platform == "linux" and "cmake-options-lin" in dep:
		cmake_cmd += f" {dep['cmake-options-lin']}"
	elif sys.platform == "win32" and "cmake-options-win" in dep:
		cmake_cmd += f" {dep['cmake-options-win']}"
	run(cmake_cmd, options.verbose)

def cmake_clean(dep, config, options:DopeOptions):
	print(f"{green(make_dep_print_prefix(dep, options))} {cyan(config)} Clean")
	run(f'cmake --build {make_dep_build_dir(dep, config, options.root)} --config {config} --target clean', options.verbose)

def cmake_build(dep, config, options:DopeOptions):
	print(f"{green(make_dep_print_prefix(dep, options))} {cyan(config)} Build")
	run(f'cmake --build {make_dep_build_dir(dep, config, options.root)} --config {config}', options.verbose)

def cmake_install(dep, config, options:DopeOptions):
	print(f"{green(make_dep_print_prefix(dep, options))} {cyan(config)} Install")
	run(f'cmake --install {make_dep_build_dir(dep, config, options.root)} --config {config}', options.verbose)

def run_cmake_for_config(dep, config, options:DopeOptions):
	cmake_configure(dep, config, options)
	if options.clean:
		cmake_clean(dep, config, options)
	else:
		cmake_build(dep, config, options)
		cmake_install(dep, config, options)

def run_cmake(dep, options:DopeOptions):
	run_cmake_for_config(dep, "Debug", options)
	run_cmake_for_config(dep, "Release", options)

def run_script(dep, options:DopeOptions):
	script_path = make_dep_script_path(dep, options.assets)
	if not os.path.exists(script_path):
		raise FileNotFoundError(f"{script_path} not found. Did you remember to set the --assets argument?")
	print(f"{green(make_dep_print_prefix(dep, options))} Running script {cyan(script_path)}")
	cmd = f'python {script_path} --root "{options.root}" --assets "{options.assets}"'
	if options.clean:
		cmd += ' --clean'
	if options.verbose:
		cmd += ' --verbose'
	env = os.environ.copy()
	package_root = Path(__file__).resolve().parent
	env["PYTHONPATH"] = str(package_root) + os.pathsep + env.get("PYTHONPATH", "")
	run_with_env(cmd, env, options.verbose)

def install_dep(dep, options:DopeOptions):
	if "build-type" not in dep:
		return
	if dep["build-type"] == "cmake":
		run_cmake(dep, options)
	elif dep["build-type"] == "py":
		run_script(dep, options)

def have_package(dep, options:DopeOptions):
	# NOTE: i'm aware that CMake has a --find-package option but apparently
	# its usage is not recommended.
	pkg_check_dir = make_pkg_check_dir(options.root)
	os.makedirs(pkg_check_dir, exist_ok=True)
	find_package_name = dep.get("find-package-name", dep["name"])
	cmake_lists = os.path.join(pkg_check_dir, "CMakeLists.txt")
	with open(cmake_lists, "w") as f:
		f.write(f'cmake_minimum_required(VERSION 3.30)\n')
		f.write(f'project(dope-package-find-test CXX)\n')
		f.write(f'find_package({find_package_name} REQUIRED CONFIG)\n')
	cmake_cmd = f'cmake -B "{pkg_check_dir}" -S "{pkg_check_dir}" -DCMAKE_PREFIX_PATH="{make_install_dir(options.root)}"'
	result = run(cmake_cmd, options.verbose, check=False)
	return result.returncode == 0

def run_dope_if_present(dep, options:DopeOptions):
	src_dir = make_dep_src_dir(dep, options.root)
	assets_dir = os.path.join(src_dir, "dope")
	if os.path.exists(os.path.join(assets_dir, DEPS_YML)):
		cmd  = f'{sys.executable} {os.path.abspath(__file__)}'
		cmd += f' --assets "{assets_dir}"'
		cmd += f' --root "{options.root}"'
		cmd += f' --cmake-options "{make_global_cmake_options(options)}"'
		cmd += f' --project-name "{dep["name"]}"'
		if options.clean:
			cmd += ' --clean'
		if options.fresh:
			cmd += ' --fresh'
		if options.reinstall:
			cmd += ' --reinstall'
		if options.reacquire:
			cmd += ' --reacquire'
		if options.verbose:
			cmd += ' --verbose'
		if options.reacquire1:
			for dep in options.reacquire1:
				cmd += f' --reacquire1 {dep}'
		if options.reinstall1:
			for dep in options.reinstall1:
				cmd += f' --reinstall1 {dep}'
		run(cmd, verbose=True)

def merge_dep_lists(names:list[str], reinstall:list[str], reacquire:list[str]):
	merged = []
	if names:
		merged.extend(names)
	if reinstall:
		merged.extend(reinstall)
	if reacquire:
		merged.extend(reacquire)
	merged = list(set(merged))
	return merged

def install_one_dep(name:str, deps, options:DopeOptions):
	dep = next((d for d in deps if d["name"] == name), None)
	if not dep:
		return
	if not should_reinstall(dep, options) and have_package(dep, options):
		print(f"{green(make_dep_print_prefix(dep, options))} already installed")
		return
	get_source(dep, options)
	run_dope_if_present(dep, options)
	install_dep(dep, options)

def install_these_deps(names:list[str], deps, options:DopeOptions):
	for name in names:
		install_one_dep(name, deps, options)

def install_all_deps(deps, options:DopeOptions):
	for dep in deps:
		if not should_reinstall(dep, options) and have_package(dep, options):
			print(f"{green(make_dep_print_prefix(dep, options))} already installed")
			continue
		get_source(dep, options)
		run_dope_if_present(dep, options)
		install_dep(dep, options)

def get_platform_settings_file_path(assets_dir):
	match sys.platform:
		case "win32":
			return os.path.join(assets_dir, SETTINGS_WIN_YML)
		case "linux":
			return os.path.join(assets_dir, SETTINGS_LIN_YML)
		case "darwin":
			return os.path.join(assets_dir, SETTINGS_MAC_YML)
		case _:
			raise ValueError(f"Unsupported platform: {sys.platform}")

def get_settings_file_path(assets_dir):
	return os.path.join(assets_dir, SETTINGS_YML)

def get_settings(assets_dir):
	settings_file          = get_settings_file_path(assets_dir)
	platform_settings_file = get_platform_settings_file_path(assets_dir)
	settings               = read_settings_file(settings_file) if os.path.exists(settings_file) else None
	platform_settings      = read_settings_file(platform_settings_file) if os.path.exists(platform_settings_file) else None
	combined_settings      = {}
	if settings:
		combined_settings = always_merger.merge(combined_settings, settings)
	if platform_settings:
		combined_settings = always_merger.merge(combined_settings, platform_settings)
	return combined_settings

def find_assets_dir(assets_arg:str):
	if os.path.exists(os.path.join(assets_arg, DEPS_YML)):
		return assets_arg
	if os.path.exists(os.path.join(assets_arg, "dope", DEPS_YML)):
		return os.path.join(assets_arg, "dope")
	raise FileNotFoundError(f"Assets directory not found in {assets_arg}")

def main():
	colorama_init()
	cwd        = os.getcwd()
	args       = parse_args(cwd)
	assets_dir = find_assets_dir(args.assets)
	settings   = get_settings(assets_dir)
	deps_file  = os.path.join(assets_dir, DEPS_YML)
	deps       = read_deps_file(deps_file)
	dope_options = DopeOptions(
		assets=assets_dir,
		clean=args.clean,
		cmake_options=args.cmake_options,
		fresh=args.fresh,
		project_name=args.project_name,
		reacquire=args.reacquire,
		reinstall=args.reinstall,
		reacquire1=args.reacquire1,
		reinstall1=args.reinstall1,
		root=args.root,
		settings=settings,
		verbose=args.verbose
	)
	if deps is None:
		print(f'{green(make_print_prefix(dope_options))} {yellow(f"No dependencies found in {cyan(deps_file)}")}')
		return
	if args.dep or dope_options.reacquire1 or dope_options.reinstall1:
		names = merge_dep_lists(args.dep, dope_options.reinstall1, dope_options.reacquire1)
		install_these_deps(names, deps, dope_options)
	else:
		install_all_deps(deps, dope_options)

if __name__ == "__main__":
	main()