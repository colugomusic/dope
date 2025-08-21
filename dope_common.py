from colorama import Fore, Style
import os
import subprocess

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

def run(cmd, verbose):
	if verbose:
		subprocess.run(cmd, check=True, shell=True)
	else:
		subprocess.run(cmd, check=True, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def run_with_env(cmd, env, verbose):
	if verbose:
		subprocess.run(cmd, check=True, shell=True, env=env)
	else:
		subprocess.run(cmd, check=True, shell=True, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def green(text):
	return f"{Fore.GREEN}{text}{Style.RESET_ALL}"

def cyan(text):
	return f"{Fore.CYAN}{text}{Style.RESET_ALL}"

def red(text):
	return f"{Fore.RED}{text}{Style.RESET_ALL}"

def yellow(text):
	return f"{Fore.YELLOW}{text}{Style.RESET_ALL}"
