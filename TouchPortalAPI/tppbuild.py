""" 
# TouchPortal Python TPP build tool

## Features

 This SDK tools makes compile, packaging and distribution of your plugin easier.

 These are the steps the tppbuild will do for you:
 - Generate entry.tp if you passed in .py file otherwise it will validate the .tp file and raise an error if it's not valid.
 - Compile your main script for your system (Windows, MacOS) depending on the platform you're running on.
 - Create a .tpp file with all the files include compiled script, (generated or existing) entry.tp file.
 - Also the .tpp file will be renamed into this format pluginname_version_os.tpp

 Note that running this script requires `pyinstaller` to be installed. You can install it by running `pip install pyinstaller` in your terminal.

 Using it in [example](https://github.com/KillerBOSS2019/TouchPortal-API/tree/main/examples)

 ```
 tppbuild --target example_build.py
 ```
 In this example we targed the example_build.py file because that file contains infomations on how to build the plugin.

 ## Command-line Usage
 The script command is `tppbuild` when the TouchPortalAPI is installed (via pip or setup), or `tppbuild.py` when run directly from this source.

 ```
<script-command> [-h] --target [<target> ...]

buildScript automatically compile into exe, entry and package them into importable tpp file

optional arguments:
  -h, --help            show this help message and exit
  --target [<target> ...]
                        target is target to a build file that contains some infomations about the plugin.Using given infomation about the plugin, It will
                        automatically build entry.tp (if given file is .py) and it will build the distrobased on what system your using.
 ```

"""

__copyright__ = """
This file is part of the TouchPortal-API project.
Copyright TouchPortal-API Developers
Copyright (c) 2021 Maxim Paperno
All rights reserved.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import importlib
import os
import sys
from zipfile import (ZipFile, ZIP_DEFLATED)
from argparse import ArgumentParser
from glob import glob
from shutil import rmtree
try:
	import PyInstaller.__main__
except ImportError:
	print("PyInstaller is not installed. Please install it before running this script.")
	sys.exit(1)

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sdk_tools

def getInfoFromBuildScript(script:str):
	try:
		spec = importlib.util.spec_from_file_location("buildScript", script)
		buildScript = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(buildScript)
	except Exception as e:
		raise ImportError(f"ERROR while trying to import plugin code from '{script}': {repr(e)}")
	return buildScript

def build_tpp(zip_name, tpp_pack_list):
	print("Creating archive: " + zip_name)
	with ZipFile(zip_name, "w", ZIP_DEFLATED) as zf:
		for src, dest in tpp_pack_list.items():
			zf.write(src, dest + os.path.basename(src))
	print("")

def zip_dir(zf, path, base_path="./", recurse=True):
	relroot = os.path.abspath(os.path.join(path, os.pardir))
	for root, _, files in os.walk(path):
		zf.write(os.path.join(root, "."))
		for file in files:
			src = os.path.join(root, file)
			if os.path.isfile(src):
				dst = os.path.join(base_path, os.path.relpath(root, relroot), file)
				zf.write(src, dst)
			elif recurse and os.path.isdir(src):
				zip_dir(zf, src, base_path)

def build_distro(opsys, version, pluginname, packingList, output):
	os_name = "Windows" if opsys == OS_WIN else "MacOS"
	zip_name = pluginname + "_v" + str(version) + "_" + os_name + ".tpp"
	print("Creating archive: "+ zip_name)
	if not os.path.exists(output):
		os.makedirs(output)
	with ZipFile(os.path.join(output, zip_name), "w", ZIP_DEFLATED) as zf:
		for src, dest in packingList.items():
			if os.path.isdir(src):
				zip_dir(zf, src, dest)
			elif os.path.isfile(src):
				zf.write(src, dest + os.path.basename(src))

	print("")

def build_clean(morefile=None, dirPath=None):
	print("Cleaning up...")
	files = glob("build")
	files.extend(glob("*.spec"))
	for f in ["dist/*.exe", "__pycache__"]:
		files.extend(glob(os.path.join(dirPath,f)))
	if morefile != None:
		files.extend(morefile)
	for file in files:
		if os.path.exists(file):
			print("removing: " + file)
			if os.path.isfile(file):
				os.remove(file)
			elif os.path.isdir(file):
				rmtree(file)
	print("")

EXE_SFX = ".exe" if sys.platform == "win32" else ""

OS_WIN = 1
OS_MAC = 2

def main():
	if sys.platform == "win32":
		opsys = OS_WIN
	elif sys.platform == "darwin":
		opsys = OS_MAC
	elif sys.platform == "linux":
		print("Linux is not supported yet.")
		sys.exit(1)
	else:
		return "Unsupported OS: " + sys.platform

	parser = ArgumentParser(description=
		"Script to automatically compile a Python plugin into a standalone exe, generate entry.tp, and package them into importable tpp file."
	)

	parser.add_argument(
		"target", metavar='<target>', type=str,
		help='A build script that contains some infomations about the plugin. ' +
		'Using given infomation about the plugin, this script will automatically build entry.tp (if given file is .py) and it will build the distro ' +
		'based on which operating system you\'re using.'
	)

	opts = parser.parse_args()
	del parser
	
	print("tppbuild started with target: " + opts.target)
	buildfile = getInfoFromBuildScript(opts.target)

	attri_list = ["PLUGIN_ENTRY", "PLUGIN_MAIN", "PLUGIN_ROOT", "ADDITIONAL_PYINSTALLER_ARGS",
				  "PLUGIN_EXE_NAME", "PLUGIN_ICON", "PLUGIN_ICON", "ADDITIONAL_FILES",
				  "OUTPUT_PATH", "PLUGIN_VERSION", "PLUGIN_ENTRY_INDENT"]

	checklist = [attri in dir(buildfile) for attri in attri_list]
	if all(checklist) == False:
		print(f"{opts.target} is missing these variables: ", " ".join([attri for attri in attri_list if attri not in dir(buildfile)]))
		return -1

	TPP_PACK_LIST = {}

	print(f"Building {buildfile.PLUGIN_EXE_NAME} v{buildfile.PLUGIN_VERSION} target(s) on {sys.platform}\n")

	buildfile_path = os.path.join(os.getcwd(), os.path.dirname(opts.target))
	if os.path.exists(dirPath := os.path.join(buildfile_path, buildfile.OUTPUT_PATH, "dist")):
		rmtree(dirPath)
	os.makedirs(dirPath)

	if os.path.isfile(os.path.join(buildfile_path, buildfile.PLUGIN_ENTRY)):
		sys.path.append(os.path.dirname(os.path.realpath(os.path.join(buildfile_path, buildfile.PLUGIN_ENTRY))))
		entry_output_path = os.path.join(buildfile_path, buildfile.OUTPUT_PATH, "dist", "entry.tp")
		sdk_arg = [os.path.join(buildfile_path, buildfile.PLUGIN_ENTRY), f"-i={buildfile.PLUGIN_ENTRY_INDENT}", f"-o={entry_output_path}"]
		result = sdk_tools.main(sdk_arg)
		if result == 0:
			print("Adding entry.tp to packing list.")
			TPP_PACK_LIST[os.path.join(buildfile_path, buildfile.OUTPUT_PATH, "dist", "entry.tp") if buildfile.PLUGIN_ENTRY.endswith(".py") else entry_output_path] = buildfile.PLUGIN_ROOT + "/"
		else:
			print("Cannot contiune because entry.tp is invalid. Please check the error message above. and try again.")
			return 0
	else:
		print(f"Warning could not find {buildfile.PLUGIN_ENTRY}. Canceling build process.")
		return 0
	
	if not os.path.exists(os.path.join(buildfile_path, buildfile.PLUGIN_ICON)):
		print(f"Warning {buildfile.PLUGIN_ICON} does not exist. TouchPortal will use default plugin icon.")
	else:
		print(f"Found {buildfile.PLUGIN_ICON} adding it to packing list.")
		iconpath = os.path.join(buildfile_path, buildfile.PLUGIN_ICON)
		TPP_PACK_LIST[os.path.join(buildfile_path, buildfile.PLUGIN_ICON.split("/")[-1])] = buildfile.PLUGIN_ROOT + "/" \
			 if len(buildfile.PLUGIN_ICON.split("/")) == 1 else "".join(buildfile.PLUGIN_ICON.split("/")[0:-1])

	print(f"Compiling {buildfile.PLUGIN_MAIN} for {sys.platform}")

	PI_RUN = [os.path.join(buildfile_path, buildfile.PLUGIN_MAIN)]
	PI_RUN.append(f'--distpath={os.path.join(buildfile_path, buildfile.OUTPUT_PATH, "dist")}')
	PI_RUN.append(f'--onefile')
	PI_RUN.append("--clean")
	if (buildfile.PLUGIN_EXE_NAME == ""):
		PI_RUN.append(f'--name={os.path.splitext(os.path.basename(buildfile.PLUGIN_MAIN))[0]}')
	else:
		PI_RUN.append(f'--name={buildfile.PLUGIN_EXE_NAME}')
	if buildfile.PLUGIN_EXE_ICON and os.path.isfile(os.path.join(buildfile_path, buildfile.PLUGIN_EXE_ICON)):
		PI_RUN.append(f"--icon={os.path.join(buildfile_path, buildfile.PLUGIN_EXE_ICON)}")
	PI_RUN.extend(buildfile.ADDITIONAL_PYINSTALLER_ARGS)

	print("Running pyinstaller with arguments:", " ".join(PI_RUN))
	PyInstaller.__main__.run(PI_RUN)
	print(f"Done compiling. adding to packing list:", buildfile.PLUGIN_EXE_NAME + EXE_SFX)
	TPP_PACK_LIST[os.path.join(buildfile_path, buildfile.OUTPUT_PATH, "dist", buildfile.PLUGIN_EXE_NAME + EXE_SFX)] = buildfile.PLUGIN_ROOT + "/"
	print("Checking for any additional required files")
	for file in buildfile.ADDITIONAL_FILES:
		print(f"Adding {file} to plugin")
		TPP_PACK_LIST[file.split("/")[-1]] = file.split("/")[0:-1]

	print("Packing everything into tpp file")
	build_distro(opsys, buildfile.PLUGIN_VERSION, buildfile.PLUGIN_EXE_NAME, TPP_PACK_LIST, os.path.join(buildfile_path, buildfile.OUTPUT_PATH))

	build_clean([entry_output_path] if buildfile.PLUGIN_ENTRY.endswith(".py") else None, buildfile_path)

	# remove empty dist folder
	rmtree(os.path.join(buildfile_path, buildfile.OUTPUT_PATH, "dist"))
	print("Done!")

	return 0

if __name__ == "__main__":
	sys.exit(main())
