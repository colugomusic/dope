# dope is not a package manager

This is a C++ dependency installer.

- Assumes that the top-level project is a CMake project.
- Dependencies do not need to be CMake projects (but that is the best-case scenario.)
- Dependencies with broken or incorrectly written CMake projects can be worked around.
- Dependencies are built locally at least once. Binaries can then be re-used.
- Dope will call itself recursively when processing dependencies which also use dope for their sub-dependencies.
- Dependencies can be downloaded from package archives, or cloned using git, or copied from some other local path on your computer.
- There is no centralized package repository or community of package maintainers. There are no "recipes". There are no packages. This is not a package manager.
- You have to use your brain to manually resolve version conflicts. We assume that if something during the build tries to use a version of a dependency which is incompatible with the one installed, then it will tell you about it.
- There is no additional meta-data stored about the state of your dependencies such as which ones are installed and which ones aren't.
- Dependencies are considered to be "installed" if `find_package(dependency_name REQUIRED CONFIG)` succeeds.
- `find_package(dependency_name REQUIRED CONFIG)` is checked automatically, once before processing a dependency, to skip it if it's already installed, and once again after installing the dependency, to check if it installed successfully.
- Only Windows, macOS and Linux are considered.

## Installation
```
pip install path/to/this/repository/
```

## Usage

Dope requires a "root". This is a folder on your computer which will have the following structure.

```
📦root
 ┣ 📂build
 ┣ 📂install
 ┣ 📂pkg
 ┣ 📂src
 ┗ 📜settings.yml
```

The folders are generated automatically. 📜settings.yml needs to be added by you.

You can have as many roots as you like. You can re-use the same root for different projects if you want.

### 📂build
Build folders for various dependencies

### 📂install
This will be your `CMAKE_INSTALL_PATH` while dependencies are installing, and `CMAKE_PREFIX_PATH` while installing dependencies and building your top-level project.

### 📂pkg
Unextracted package archives downloaded from the internet.

### 📂src
Source code of dependencies.

### 📜settings.yml
A file containing build settings which will be used for building every dependency in the root. Example from my own project:
```yml
cmake-options:
  - -DBUILD_SHARED_LIBS=OFF
  - -DCMAKE_DEBUG_POSTFIX=d
  - -DCMAKE_POSITION_INDEPENDENT_CODE=ON
macos:
  - cmake-options:
    - -DCMAKE_OSX_ARCHITECTURES=arm64;x86_64
    - -DCMAKE_OSX_DEPLOYMENT_TARGET=13.3
```

Everything in the settings file is optional but if you are building for both Debug and Release then you very likely want to remember `CMAKE_DEBUG_POSTFIX`.

The platform-specific sections are named `linux`, `macos`, and `windows`.

In the root of your project, create the file `dope/deps.yml`:

```
📦your project
 ┣ 📂dope
 ┃ ┗ 📜deps.yml
```

## Example 📜deps.yml

This is a stripped down example from my own project which shows some various ways of specifying dependencies:

```yml
- name:                ez
  git:                 https://github.com/colugomusic/ez.git

- name:                ads
  git:                 https://github.com/colugomusic/ads.git

- name:                minizip-ng
  url:                 https://github.com/zlib-ng/minizip-ng/archive/refs/tags/4.0.10.zip
  cmake-options:       -DMZ_BZIP2=OFF -DMZ_LZMA=OFF -DMZ_ZSTD=OFF
  find-package-name:   minizip

- name:                libpng
  git:                 https://github.com/pnggroup/libpng.git
  tag:                 v1.6.50
  cmake-options:       -DPNG_TESTS=OFF -DPNG_SHARED=OFF -DPNG_TOOLS=OFF -DPNG_ARM_NEON=off
  find-package-name:   PNG

- name:                Boost
  url:                 https://github.com/boostorg/boost/releases/download/boost-1.86.0/boost-1.86.0-cmake.zip
  src-subdir:          boost-1.86.0
  cmake-options-mac:   -DBOOST_CONTEXT_ABI=sysv -DBOOST_CONTEXT_ARCHITECTURE=combined

- name:                madronalib
  git:                 https://github.com/madronalabs/madronalib.git
  tag:                 6896aca
  add-src-files:       true

- name:                Immer
  git:                 https://github.com/arximboldi/immer.git
  tag:                 v0.8.1
  cmake-options:       -Dimmer_BUILD_DOCS=OFF -Dimmer_BUILD_TESTS=OFF -Dimmer_BUILD_EXAMPLES=OFF -Dimmer_BUILD_EXTRAS=OFF

- name:                magic_enum
  url:                 https://github.com/Neargye/magic_enum/archive/refs/tags/v0.9.7.zip
  md5:                 22f384763e107f34e552605b20ee18b2
  cmake-options:       -DMAGIC_ENUM_OPT_BUILD_EXAMPLES=OFF -DMAGIC_ENUM_OPT_BUILD_TESTS=OFF

- name:                memory
  url:                 https://github.com/foonathan/memory/archive/refs/tags/v0.7-4.zip
  cmake-options:       -DFOONATHAN_MEMORY_BUILD_EXAMPLES=OFF -DFOONATHAN_MEMORY_BUILD_TESTS=OFF -DFOONATHAN_MEMORY_BUILD_TOOLS=OFF
  find-package-name:   foonathan_memory

- name:                expected
  url:                 https://github.com/TartanLlama/expected/archive/refs/tags/v1.2.0.zip
  cmake-options:       -DEXPECTED_BUILD_TESTS=OFF
  find-package-name:   tl-expected

- name:                godot-cpp
  git:                 https://github.com/godotengine/godot-cpp.git
  tag:                 3.5
  build-type:          py
  add-src-files:       true
```

Options `url`, `git`, `path` and `remote-path` are mutually exclusive.

### name
You can give dependencies any name you want, but this is also the name that will be passed to `find_package()` to check if the installation was successful, unless `find-package-name` is also specified. Note that `find_package()` is case-sensitive.

### url
Source will be downloaded from the internet and extracted into `root/src/(dependency name)`. It's assumed that the downloaded file is an archive.

### git
Source will be cloned from the remote git repository.

### path
Source will be copied from the specified location on your computer to `root/src/(dependency name)`

### remote-path
Like `path`, but the source location is simply referenced instead of being copied into `root/src/(dependency name)`.

### tag
Only used with `git` to specify a tag.

### build-type
Possible values are "cmake" or "py". If not specified this defaults to "cmake".

### add-src-files
If specified, the contents of `(project root)/dope/(dependency name)/src` will be copied into the dependency's source directory before building it. You can use this to overwrite a broken or problematic `CMakeLists.txt` with your own, for example.

### md5
If specified, will be checked against the md5 hash of the package downloaded from the url specified with `url`

### find-package-name
If the name that should be passed to `find_package()` differs from the dependency name then you can specify it here. Note that `find_package()` is case-sensitive.

### src-subdir
Most packages you get from github or similar repositories will extract to a single subfolder named something like "(name)-(version)". If the archive contains multiple subfolders or a subfolder which isn't named in a predictable way then you can manually specify which folder, relative to the root of the extracted archive, contains the source code. (The Boost example here isn't actually necessary)

### cmake-options
CMake options which will be used when building the dependency, in addition to the options specified in `root/settings.yml`. You can specify platform-specific options with `cmake-options-lin`, `cmake-options-mac` and `cmake-options-win`.

## Installing dependencies using a custom script
If `build-type` is "py" then dope will look for a python script at `(project root)/dope/(dependency name)/install.py`. This script can do whatever you want to install the dependency. The script is working successfully if by the end of it, `find_package(dependency_name REQUIRED CONFIG)` succeeds.

The script should accept these arguments which will be forwarded from the top-level dope invocation (arguments are documented below)
```python
parser = argparse.ArgumentParser()
parser.add_argument("--root", type=str, required=True)
parser.add_argument("--assets", type=str, required=True)
parser.add_argument("--clean", action="store_true")
parser.add_argument("--verbose", action="store_true")
args = parser.parse_args()
```

For an example, see https://github.com/colugomusic/dope-godot-cpp (which builds the dependency using scons and then installs it using a custom CMakeLists.txt)

## How to run it
Go to the root of your project and run
`dope -r /path/to/your/dope/root`

If you want to run the command from somewhere else then you can explictly specify the project path with either of:
- `dope -r /path/to/your/dope/root -a /path/to/project/root`
- `dope -r /path/to/your/dope/root -a /path/to/project/root/dope`

## Arguments

### -r/--root (path)
Path to your root folder.

### -a/--assets (path)
Path to the "assets folder" which contains your `deps.yml`. If not specified, defaults to `(current working directory)/dope`

### --verbose
Basically prints everything that is happening. You will want this if a dependency installation is failing for some reason.

### --clean
Passes `--target clean` to CMake dependencies, and `--clean` to non-CMake dependencies. Skips the install step.

### --fresh
Forwards `--fresh` to CMake dependencies.

### --config
Can be given multiple times to specify configs to install. Defaults to `--config Debug --config Release`

### -1/--dep (name)
Can be given multiple times to build and install specific dependencies.

### --reacquire (name)
Can be given multiple times to reacquire specific dependencies (zip files will be redownloaded, git repositories will be re-pulled, etc.)

`--reacquire *` will reacquire all dependencies.

`--reacquire` implies also `--reinstall`.

For `remote-path` dependencies, equivalent to `--reinstall`

### --reinstall (name)
Can be given multiple times to reinstall specific dependencies. This is similar to `--dep` except it skips the initial `find_package()` check when processing the dependency and acts as if the check failed.

`--reinstall *` will reinstall all dependencies.

## Referring to sub-dependencies
Dope is only immediately aware of the dependencies specified in the `deps.yml` that it is currently processing. So if a dependency `foo` is also using dope, and specifies a sub-dependency `bar` then dope will not be aware of that until it gets around to processing `foo`.

Therefore `--reacquire bar` or `--reinstall bar` will not work.

However, you can refer to this dependency with the syntax `--reacquire foo/bar` or `--reinstall foo/bar`.

Alternatively you can process foo's sub-dependencies directly with `dope -z /path/to/your/dope/root -a /path/to/foo --reinstall bar`
