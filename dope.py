from git import Repo
from pathlib import Path
from colorama import init as colorama_init
from dope_common import *
from deepmerge import always_merger
import argparse
import os
import shutil
import sys
import wget
import yaml

DEPS_YML         = "deps.yml"
SETTINGS_YML     = "settings.yml"
SETTINGS_WIN_YML = "settings-win.yml"
SETTINGS_LIN_YML = "settings-lin.yml"
SETTINGS_MAC_YML = "settings-mac.yml"

def parse_args(cwd):
	default_assets_path = cwd
	parser = argparse.ArgumentParser(description='Build/Install dependencies')
	parser.add_argument('-r', '--root', required=True, help='Where to build/install dependencies')
	parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
	parser.add_argument('-1', '--dep', help='Build/Install a specific dependency')
	parser.add_argument('-c', '--clean', action='store_true', help='Clean instead of build/install')
	parser.add_argument('-a', '--assets', default=default_assets_path, help='Path to assets directory')
	parser.add_argument('-f', '--fresh', action='store_true', help='Fresh build (clear CMake cache)')
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

def unpack_into(dep, filepath, target_dir):
	print(f"{green(dep['name'])} Unpacking {cyan(filepath)} into {cyan(target_dir)}")
	os.makedirs(target_dir, exist_ok=True)
	shutil.unpack_archive(filepath, target_dir)

def download_package(dep, root, url):
	print(f"{green(dep['name'])} Downloading from {cyan(url)}")
	dep_pkg_dir = os.path.join(make_pkg_dir(root), dep["name"])
	os.makedirs(dep_pkg_dir, exist_ok=True)
	filename = os.path.basename(url)
	filepath = os.path.join(dep_pkg_dir, filename)
	wget.download(url, filepath)
	unpack_into(dep, filepath, make_dep_src_unpack_dir(dep, root))

def download_source_from_url(dep, root):
	url = dep["url"]
	unpack_dir = make_dep_src_unpack_dir(dep, root)
	if not os.path.exists(unpack_dir):
		download_package(dep, root, url)
	else:
		print(f"{green(dep['name'])} Skipping download from {cyan(url)} because it already exists in {cyan(unpack_dir)}")

def clone_source_from_git(dep, root):
	url = dep["git"]
	clone_dir = make_dep_src_dir(dep, root)
	if not os.path.exists(clone_dir):
		print(f"{green(dep['name'])} Cloning from {cyan(url)}")
		repo = Repo.clone_from(url, clone_dir)
		if "tag" in dep:
			repo.git.checkout(dep["tag"])
	else:
		print(f"{green(dep['name'])} Skipping clone from {cyan(url)} because it already exists in {cyan(clone_dir)}")

def copy_source_from_path(dep, root):
	path = dep["path"]
	copy_dir = make_dep_src_dir(dep, root)
	if not os.path.exists(copy_dir):
		print(f"{green(dep['name'])} Copying from {cyan(path)}")
		shutil.copytree(path, copy_dir)
	else:
		print(f"{green(dep['name'])} Skipping copy from {cyan(path)} because it already exists in {cyan(copy_dir)}")

def add_src_files(dep, root, assets_dir):
	src_add_dir = make_dep_src_add_dir(dep, assets_dir)
	src_dst_dir = make_dep_src_dir(dep, root)
	for file in os.listdir(src_add_dir):
		dst_file = os.path.join(src_dst_dir, file)
		print(f"{green(dep['name'])} Adding {cyan(dst_file)}")
		shutil.copy(os.path.join(src_add_dir, file), dst_file)

def get_source(dep, root, assets_dir):
	if "url" in dep:
		download_source_from_url(dep, root)
	elif "git" in dep:
		clone_source_from_git(dep, root)
	elif "path" in dep:
		copy_source_from_path(dep, root)
	if "add-src-files" in dep and dep["add-src-files"]:
		add_src_files(dep, root, assets_dir)

def cmake_configure(dep, root, config, settings, fresh, verbose):
	print(f"{green(dep['name'])} {cyan(config)} Configure")
	cmake_cmd = 'cmake'
	cmake_cmd += f' -B "{make_dep_build_dir(dep, config, root)}"'
	cmake_cmd += f' -S "{make_dep_src_dir(dep, root)}"'
	cmake_cmd += f' {" ".join(settings["cmake-options"])}'
	cmake_cmd += f' -DCMAKE_PREFIX_PATH="{make_install_dir(root)}"'
	cmake_cmd += f' -DCMAKE_INSTALL_PREFIX="{make_install_dir(root)}"'
	if fresh:
		cmake_cmd += ' --fresh'
	if "cmake-options" in dep:
		cmake_cmd += f" {dep['cmake-options']}"
	if sys.platform == "darwin" and "cmake-options-mac" in dep:
		cmake_cmd += f" {dep['cmake-options-mac']}"
	elif sys.platform == "linux" and "cmake-options-lin" in dep:
		cmake_cmd += f" {dep['cmake-options-lin']}"
	elif sys.platform == "win32" and "cmake-options-win" in dep:
		cmake_cmd += f" {dep['cmake-options-win']}"
	run(cmake_cmd, verbose)

def cmake_clean(dep, root, config, verbose):
	print(f"{green(dep['name'])} {cyan(config)} Clean")
	run(f'cmake --build {make_dep_build_dir(dep, config, root)} --config {config} --target clean', verbose)

def cmake_build(dep, root, config, verbose):
	print(f"{green(dep['name'])} {cyan(config)} Build")
	run(f'cmake --build {make_dep_build_dir(dep, config, root)} --config {config}', verbose)

def cmake_install(dep, root, config, verbose):
	print(f"{green(dep['name'])} {cyan(config)} Install")
	run(f'cmake --install {make_dep_build_dir(dep, config, root)} --config {config}', verbose)

def run_cmake_for_config(dep, root, config, settings, clean, fresh, verbose):
	cmake_configure(dep, root, config, settings, fresh, verbose)
	if clean:
		cmake_clean(dep, root, config, verbose)
	else:
		cmake_build(dep, root, config, verbose)
		cmake_install(dep, root, config, verbose)

def run_cmake(dep, root, settings, clean, fresh, verbose):
	run_cmake_for_config(dep, root, "Debug", settings, clean, fresh, verbose)
	run_cmake_for_config(dep, root, "Release", settings, clean, fresh, verbose)

def run_script(dep, root, assets_dir, clean, verbose):
	script_path = make_dep_script_path(dep, assets_dir)
	if not os.path.exists(script_path):
		raise FileNotFoundError(f"{script_path} not found. Did you remember to set the --assets argument?")
	print(f"{green(dep['name'])} Running script {cyan(script_path)}")
	cmd = f'python {script_path} --root "{root}" --assets "{assets_dir}"'
	if clean:
		cmd += ' --clean'
	if verbose:
		cmd += ' --verbose'
	env = os.environ.copy()
	package_root = Path(__file__).resolve().parent
	env["PYTHONPATH"] = str(package_root) + os.pathsep + env.get("PYTHONPATH", "")
	run_with_env(cmd, env, verbose)

def install_dep(dep, root, assets_dir, settings, clean, fresh, verbose):
	if dep["build-type"] == "cmake":
		run_cmake(dep, root, settings, clean, fresh, verbose)
	elif dep["build-type"] == "py":
		run_script(dep, root, assets_dir, clean, verbose)

def install_one_dep(name, deps, root, assets_dir, settings, clean, fresh, verbose):
	dep = next((d for d in deps if d["name"] == name), None)
	if not dep:
		print(f"{red(name)} not found")
		return
	get_source(dep, root, assets_dir)
	install_dep(dep, root, assets_dir, settings, clean, fresh, verbose)

def install_all_deps(deps, root, assets_dir, settings, clean, fresh, verbose):
	for dep in deps:
		get_source(dep, root, assets_dir)
		install_dep(dep, root, assets_dir, settings, clean, fresh, verbose)

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

def main():
	colorama_init()
	cwd       = os.getcwd()
	args      = parse_args(cwd)
	settings  = get_settings(args.assets)
	deps_file = os.path.join(args.assets, DEPS_YML)
	deps      = read_deps_file(deps_file)
	if args.dep:
		install_one_dep(args.dep, deps, args.root, args.assets, settings, args.clean, args.fresh, args.verbose)
	else:
		install_all_deps(deps, args.root, args.assets, settings, args.clean, args.fresh, args.verbose)

if __name__ == "__main__":
	main()