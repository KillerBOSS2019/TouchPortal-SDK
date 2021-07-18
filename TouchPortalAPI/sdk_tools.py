#!/usr/bin/env python3
'''
Touch Portal Python SDK Tools

Functions:
	* Generates an entry.tp definition file for a Touch Portal plugin based
	on variables specified in the plugin source code (`generateDefinitionFromScript()`),
	from a loaded module (`generateDefinitionFromModule()`) or specified by value (`generateDefinitionFromDeclaration()`).
	* Validate an entire plugin definition (entry.tp) file (`validateDefinitionFile()`),
	string (`validateDefinitionString()`), or object (`validateDefinitionObject()`).
	* Validate an entry.tp attribute value against the minimum
	SDK version, value type, value content, etc. (`validateAttribValue()`).
	* ... ?

Command-line Usage:
	sdk_tools.py [-h] [action] [target] [output]

	* `action` : "--generate" (default) to generate definition file or "--validate" to validate an existing definition file.
	* `target` : path to file, type depending on action.
	             Either a plugin script for `generate` or an entry.tp file for `validate`. Or use 'stdin' (or '-') to read from input stream.
               Paths are relative to current working directory. Defaults to "./main.py" and "./entry.tp" respectively.
	* `output` : output file path for generated definition JSON, or 'stdout' (or '-') to print to console.
	             Default will be a file named 'entry.tp' in the same folder as the input script.

TODO/Ideas:

* Validate that IDs for states/actions/etc are unique.
# Dynamic default values, eg. for action prefix or category id/name (see notes in sdk_spec tables).
* Allow plugin author to set their own defaults?
'''

import sys
import os.path
import importlib.util
import json
from types import ModuleType
from typing import (Union, TextIO)
from re import compile as re_compile

sys.path.append(os.path.dirname(os.path.realpath(__file__)))
from sdk_spec import *

## globals
g_messages = []

## Utils

def getMessages():
	return g_messages

def _printMessages(messages:list):
	for msg in messages:
		_printToErr(msg)

def _addMessage(msg):
	global g_messages
	g_messages.append(msg)

def _clearMessages():
	global g_messages
	g_messages.clear()

def _printToErr(msg):
	sys.stderr.write(msg + "\n")

def _normPath(path):
	if not isinstance(path, str):
		return path
	return os.path.normpath(os.path.join(os.getcwd(), path))

def _keyPath(path, key):
	return ":".join(filter(None, [path, key]))

## Generator functions

def _dictFromItem(item:dict, table:dict, sdk_v:int, path:str=""):
	ret = {}
	for k, data in table.items():
		# try get explicit value from item
		if (v := item.get(k)) is None:
			# try get default value
			v = data.get('d')
		# check if there is nested data, eg. in an Action
		if isinstance(v, dict) and data.get('t') is list:
			v = _arrayFromDict(v, data.get('l', {}), sdk_v, path=_keyPath(path, k))
		# check that the value is valid and add it to the dict if it is
		if validateAttribValue(k, v, data, sdk_v, path):
			ret[k] = v
	return ret


def _arrayFromDict(d:dict, table:dict, sdk_v:int, category:str=None, path:str=""):
	ret = []
	for key, item in d.items():
		if not category or not (cat := item.get('category')) or cat == category:
			ret.append(_dictFromItem(item, table, sdk_v, f"{path}[{key}]"))
	if path in ["actions","connectors"]:
		_replaceFormatTokens(ret)
	return ret


def _replaceFormatTokens(items:list):
	for d in items:
		if not isinstance(d, dict) or not 'format' in d.keys() or not 'data' in d.keys():
			continue
		data_ids = {}
		for data in d.get('data'):
			if (did := data.get('id')):
				data_ids[did.rsplit(".", 1)[-1]] = did
		if not data_ids:
			continue
		fmt = d.get('format')
		rx = re_compile(r'\$\[(\w+)\]')
		begin = 0
		while (m := rx.search(fmt, begin)):
			idx = m.group(1)
			if idx in data_ids.keys():
				val = data_ids.get(idx)
			elif idx.isdigit() and (i := int(idx) - 1) >= 0 and i < len(data_ids):
				val = list(data_ids.values())[i]
			else:
				begin = m.end()
				continue
			# print(m.span(), val)
			fmt = fmt[:m.start()] + "{$" + val + "$}" + fmt[m.end():]
			begin = m.start() + len(val) + 4
		d['format'] = fmt


def generateDefinitionFromScript(script:Union[str, TextIO]):
	"""
	Returns an "entry.tp" Python `dict` which is suitable for direct conversion to JSON format.
	`script` should be a valid python script, either a file path (ending in .py), string, or open file handle (like stdin).
	The script should contain "SDK declaration variables" like	`TP_PLUGIN_INFO`, `TP_PLUGIN_SETTINGS`, etc.

	Note that the script is interpreted (executed), so any actual "business" logic (like connecting to TP) should be in "__main__".

	May raise an `ImportError` if the plugin script could not be loaded or is missing required variables.
	Use `getMessages()` to check for any warnings/etc which may be generated (eg. from attribute validation).
	"""
	input_name = "input string"
	script_str = ""
	if hasattr(script, "read"):
		script_str = script.read()
		input_name = "input stream"
	elif script.endswith(".py"):
		with open(script, 'r') as script_file:
			script_str = script_file.read()
		input_name = script
	else:
		script_str = script

	try:
		# spec = importlib.util.spec_from_file_location("plugin", script)
		spec = importlib.util.spec_from_loader("plugin", loader=None)
		plugin = importlib.util.module_from_spec(spec)
		# spec.loader.exec_module(plugin)
		exec(script_str, plugin.__dict__)
		# print(plugin.TP_PLUGIN_INFO)
	except Exception as e:
		raise ImportError(f"ERROR while trying to import plugin code from '{input_name}': {repr(e)}")
	return generateDefinitionFromModule(plugin)


def generateDefinitionFromModule(plugin:ModuleType):
	"""
	Returns an "entry.tp" Python `dict`, which is suitable for direct conversion to JSON format.
	`plugin` should be a loaded Python "module" which contains "SDK declaration variables" like
	`TP_PLUGIN_INFO`, `TP_PLUGIN_SETTINGS`, etc. From within a plugin script this could be called like:
	`generateDefinitionFromModule(sys.modules[__name__])`.
	May raise an `ImportError` if the plugin script is missing required variables TP_PLUGIN_INFO and TP_PLUGIN_CATEGORIES.
	Use `getMessages()` to check for any warnings/etc which may be generated (eg. from attribute validation).
	"""
	# Load the "standard SDK declaration variables" from plugin script into local scope
	# INFO and CATEGORY are required, rest are optional.
	if not (info := getattr(plugin, "TP_PLUGIN_INFO", {})):
		raise ImportError(f"ERROR: Could not import required TP_PLUGIN_INFO variable from plugin source.")
	if not (cats := getattr(plugin, "TP_PLUGIN_CATEGORIES", {})):
		raise ImportError(f"ERROR: Could not import required TP_PLUGIN_CATEGORIES variable from plugin source.")
	return generateDefinitionFromDeclaration(
		info, cats,
		settings = getattr(plugin, "TP_PLUGIN_SETTINGS", {}),
		actions = getattr(plugin, "TP_PLUGIN_ACTIONS", {}),
		states = getattr(plugin, "TP_PLUGIN_STATES", {}),
		events = getattr(plugin, "TP_PLUGIN_EVENTS", {}),
		connectors = getattr(plugin, "TP_PLUGIN_CONNECTORS", {})
	)


def generateDefinitionFromDeclaration(info:dict, categories:dict, **kwargs):
	"""
	Returns an "entry.tp" Python `dict` which is suitable for direct conversion to JSON format.
	Arguments should contain SDK declaration dict values, for example as specified for `TP_PLUGIN_INFO`,
	etc.  The `info` and `category` values are required, the rest are optional.
	Use `getMessages()` to check for any warnings/etc which may be generated (eg. from attribute validation).
	`kwargs` can be one or more of:
		settings:dict={},
		actions:dict={},
		states:dict={},
		events:dict={},
		connectors:dict={}
	"""
	_clearMessages()
	settings = kwargs.get('settings', {})
	actions = kwargs.get('actions', {})
	states = kwargs.get('states', {})
	events = kwargs.get('events', {})
	connectors = kwargs.get('connectors', {})
	# print(info, categories, settings, actions, states, events, connectors)

	# Start the root entry.tp object using basic plugin metadata
	# This will also create an empty `categories` array in the root of the entry.
	entry = _dictFromItem(info, TPSDK_ATTRIBS_ROOT, TPSDK_DEFAULT_VERSION, "info")

	# Get the target SDK version (was either specified in plugin or is TPSDK_DEFAULT_VERSION)
	tgt_sdk_v = entry['sdk']

	# Loop over each plugin category and set up actions, states, events, and connectors.
	for cat, data in categories.items():
		path = f"category[{cat}]"
		category = _dictFromItem(data, TPSDK_ATTRIBS_CATEGORY, tgt_sdk_v, path)
		category['actions'] = _arrayFromDict(actions, TPSDK_ATTRIBS_ACTION, tgt_sdk_v, cat, "actions")
		category['states'] = _arrayFromDict(states, TPSDK_ATTRIBS_STATE, tgt_sdk_v, cat, "states")
		category['events'] = _arrayFromDict(events, TPSDK_ATTRIBS_EVENT, tgt_sdk_v, cat, "events")
		if tgt_sdk_v >= 4:
			category['connectors'] = _arrayFromDict(connectors, TPSDK_ATTRIBS_CONNECTOR, tgt_sdk_v, cat, "connectors")
		# add the category to entry's categories array
		entry['categories'].append(category)

	# Add Settings to root
	if tgt_sdk_v >= 3:
		entry['settings'].extend(_arrayFromDict(settings, TPSDK_ATTRIBS_SETTINGS, tgt_sdk_v, path = "settings"))

	return entry


## Validation functions

def validateAttribValue(key:str, value, attrib_data:dict, sdk_v:int, path:str=""):
	"""
	`key` is the attribute name;
	`value` is what to validate;
	`action_data` is the lookup table data for the given key (eg. `TPSDK_ATTRIBS_INFO[key]` );
	`sdk_v` is the TP SDK version being used (for validation).
	`path` is just extra information to print before the key name in warning messages (to show where attribute is in the tree).
	"""
	keypath = _keyPath(path, key)
	if value is None:
		if attrib_data.get('r'):
			_addMessage(f"WARNING: Missing required attribute '{keypath}'.")
		return False
	if not isinstance(value, (exp_typ := attrib_data.get('t', str))):
		_addMessage(f"WARNING: Wrong data type for attribute '{keypath}'. Expected {exp_typ} but got {type(value)}")
		return False
	if sdk_v < (min_sdk := attrib_data.get('v', sdk_v)):
		_addMessage(f"WARNING: Wrong SDK version for attribute '{keypath}'. Minimum is v{min_sdk} but using v{sdk_v}")
		return False
	if (choices := attrib_data.get('c')) and value not in choices:
		_addMessage(f"WARNING: Value error for attribute '{keypath}'. Got '{value}' but expected one of {choices}")
		return False
	return True

def _validateDefinitionDict(d:dict, table:dict, sdk_v:int, path:str=""):
	# iterate over existing attributes to validate them
	for k, v in d.items():
		adata = table.get(k)
		keypath = _keyPath(path, k)
		if not adata:
			_addMessage(f"WARNING: Attribute '{keypath}' is unknown.")
			continue
		if not validateAttribValue(k, v, adata, sdk_v, path):
			continue
		# print(k, v, type(v))
		if isinstance(v, list) and (ltable := adata.get('l')):
			_validateDefinitionArray(v, ltable, sdk_v, keypath)
	# iterate over table entries to check if all required attribs are present
	for k, data in table.items():
		if data.get('r') and k not in d.keys():
			_addMessage(f"WARNING: Missing required attribute '{_keyPath(path, k)}'.")

def _validateDefinitionArray(a:list, table:dict, sdk_v:int, path:str=""):
	i = 0
	for item in a:
		if isinstance(item, dict):
			_validateDefinitionDict(item, table, sdk_v, f"{path}[{i:d}]")
		else:
			_addMessage(f"WARNING: Unable to handle array member '{item}' in '{path}'.")
		i += 1


def validateDefinitionObject(data:dict):
	"""
	Validates a TP plugin definition structure from a Python `dict` object.
	`data` is a de-serialzed entry.tp JSON object (eg. json.load('entry.tp'))
	Returns `True` if no problems were found, `False` otherwise.
	Use `getMessages()` to check for any validation warnings which may be generated.
	"""
	_clearMessages()
	sdk_v = data.get('sdk', TPSDK_DEFAULT_VERSION)
	_validateDefinitionDict(data, TPSDK_ATTRIBS_ROOT, sdk_v)
	return len(g_messages) == 0

def validateDefinitionString(data:str):
	"""
	Validates a TP plugin definition structure from JSON string.
	`data` is an entry.tp JSON string
	Returns `True` if no problems were found, `False` otherwise.
	Use `getMessages()` to check for any validation warnings which may be generated.
	"""
	return validateDefinitionObject(json.loads(data))

def validateDefinitionFile(file:Union[str, TextIO]):
	"""
	Validates a TP plugin definition structure from JSON file.
	`file` is a valid system path to an entry.tp JSON file _or_ an already-opened file handle (eg. sys.stdin).
	Returns `True` if no problems were found, `False` otherwise.
	Use `getMessages()` to check for any validation warnings which may be generated.
	"""
	fh = file
	if isinstance(fh, str):
		fh = open(file, 'r')
	ret = validateDefinitionObject(json.load(fh))
	if fh != file:
		fh.close()
	return ret


## CLI handlers

def _generateDefinition(script, output_path, indent):
	input_name = "input stream"
	if isinstance(script, str):
		if len(script.split(".")) < 2:
			script = script + ".py"
		input_name = script
	indent = None if indent is None or int(indent) < 0 else indent

	_printToErr(f"Generating plugin definition JSON from '{input_name}'...\n")
	entry = generateDefinitionFromScript(script)
	entry_str = json.dumps(entry, indent=indent) + "\n"
	if (messages := getMessages()):
		_printMessages(messages)
		_printToErr("")
	# output
	if output_path:
		# write it to a file
		with open(output_path, "w") as entry_file:
			entry_file.write(entry_str)
		_printToErr(f"Saved generated JSON to '{output_path}'\n")
	else:
		# send to stdout
		print(entry_str)
	_printToErr(f"Finished generating plugin definition JSON from '{input_name}'.\n")
	return entry_str


def _validateDefinition(entry, as_str=False):
	name = entry if isinstance(entry, str) and not as_str else "input stream"
	_printToErr(f"Validating '{name}', any errors or warnings will be printed below...\n")
	if as_str:
		res = validateDefinitionString(entry)
	else:
		res = validateDefinitionFile(entry)
	if res:
		_printToErr("No problems found!")
	else:
		_printMessages(getMessages())
	_printToErr(f"\nFinished validating '{name}'.\n")


def main():
	from argparse import (ArgumentParser, FileType)
	parser = ArgumentParser()
	parser.add_argument("-g", "--generate", action='store_true',
	                    help="Generate a definition file from plugin script data. This is the default action.")
	parser.add_argument("-v", "--validate", action='store_true',
	                    help="Validate a definition JSON file (entry.tp). If given with `generate` then will validate the generated JSON output.")
	parser.add_argument("-o", metavar="<file_path>",
	                    help="Output file for `generate` action. Default will be a file named 'entry.tp' in the same folder as the input script. "
                           "Paths are relative to current working directory. Use 'stdout' (or '-') to print the output to the console/stream instead.")
	parser.add_argument("-i", "--indent", metavar="<n>", type=int, default=2,
	                    help="Indent level (spaces) for generated JSON. Use 0 for only newlines, or -1 for the most compact representation. Default is 2 spaces.")
	parser.add_argument("target", metavar="target", nargs="?", default="",
	                    help="Either a plugin script for `generate` or an entry.tp file for `validate`. Paths are relative to current working directory. "
	                         "Defaults to './main.py' and './entry.tp' respectively. Use 'stdin' (or '-') to read from input stream instead. ")
	opts = parser.parse_args()
	del parser

	# default action
	opts.generate = opts.generate or not opts.validate

	_printToErr("")

	if opts.target in ("-","stdin"):
		opts.target = sys.stdin

	entry_str = ""
	if opts.generate:
		opts.target = _normPath(opts.target or "main.py")
		output_path = None
		if opts.o:
			if opts.o not in ("-","stdout"):
				output_path = opts.o
		else:
			output_path = os.path.join(os.path.dirname(opts.target), "entry.tp")
		entry_str = _generateDefinition(opts.target, output_path, opts.indent)
		if opts.validate and output_path:
			opts.target = output_path

	if opts.validate:
		if entry_str:
			_validateDefinition(entry_str, True)
		else:
			opts.target = _normPath(opts.target or "entry.tp")
			_validateDefinition(opts.target)

	return 0


if __name__ == "__main__":
	sys.exit(main())