#!/usr/bin/env python3
"""
# Touch Portal Python SDK Tools

## Features

This SDK tool provides features for generating and validating Touch Portal Plugin Description files,
which are in JSON format and typically named "entry.tp" (as described in the [TP API docs](https://www.touch-portal.com/api/)).

**Generation** is done based on dictionary structures defined in plugin scripts. These structures closely follow
the format of the description file JSON, but are further expanded to make them also useful within the plugin
scripts themselves. This avoids almost all the need for duplication of things like unique IDs, default values,
settings names, and so on, since those details need to be available in both the definition JSON and in the
script which will be using those definitions to communicate with Touch Portal.

**Validation** is performed on the generated descriptions, and can also be run against pre-existing definition files
as a sort of "lint" utility. Currently the following things are checked:
- All required attributes are present.
- All attribute values are of the supported data type(s).
- No unknown attributes are present.
- Attributes are valid for the TP SDK version being used.
- Attribute values fall within allowed list of values (if relevant, eg. `Action.type`).
- All ID strings are unique within the plugin (eg. for States, Actions, etc).

This tool can be used as a command-line utility, or imported as a module to use the available functions programmatically.
The script command is `tppsdk` when the TouchPortalAPI is installed (via pip or setup), or `sdk_tool.py` when run directly
from this source. To use within a script, simply import in the usual way as needed. For example:

```py
from TouchPortalAPI.sdk_tools import generateDefinitionFromScript
```

All generation/validation routines are based on TP API specification data tables defined in `TouchPortalAPI.sdk_spec`.

A comprehensive example plugin which utilizes the SDK features is included with the TouchPortalAPI project.
The JSON definition "entry.tp" file for that example could be generated with a simple command from within a local
folder containing the example script:

```
tppsdk plugin_example.py
```


## Functions
* Generates an `entry.tp` definition file for a Touch Portal plugin based
on variables specified in the plugin source code (`generateDefinitionFromScript()`),
from a loaded module (`generateDefinitionFromModule()`) or specified by value (`generateDefinitionFromDeclaration()`).
* Validate an entire plugin definition (`entry.tp`) file (`validateDefinitionFile()`),
string (`validateDefinitionString()`), or object (`validateDefinitionObject()`).
* Validate an `entry.tp` attribute value against the minimum
SDK version, value type, value content, etc. (`validateAttribValue()`).


## Command-line Usage
The script command is `tppsdk` when the TouchPortalAPI is installed (via pip or setup), or `sdk_tool.py` when run directly from this source.
```
<script_command> [-h] [-g] [-v] [-o <file>] [-s] [-i <n>] [target]

positional arguments:
  target                Either a plugin script for `generate` or an entry.tp file for `validate`. Paths are relative to current working
                        directory. Defaults to './TPPEntry.py' and './entry.tp' respectively. Use 'stdin' (or '-') to read from input
                        stream instead. Another usage is if you pass in a normal entry.tp without `validate` argument, It can generate
                        Python version of entry.tp struct. It will be saved in `TPPEntry.py` if `output` is not given.

optional arguments:
  -h, --help            show this help message and exit
  -g, --generate        Generate a definition file from plugin script data. This is the default action.
  -v, --validate        Validate a definition JSON file (entry.tp). If given with `generate` then will validate the generated JSON output.

generator arguments:
  -o <file>             Output file for `generate` action. Default will be a file named 'entry.tp' in the same folder as the input script.
                        Paths are relative to current working directory. Use 'stdout' (or '-') to print the output to the console/stream instead.
  -s, --skip-invalid    Skip attributes with invalid values (they will not be included in generated output). Default behavior is to only warn about them.
  -i <n>, --indent <n>  Indent level (spaces) for generated JSON. Use 0 for only newlines, or -1 for the most compact representation. Default is 2 spaces.
  --noconfirm           When generating python struct from entry.tp, you can pass this arg to bypass confirm if you want to contiune if any error is given for vaildating entry.tp before generate python struct.
This script exits with status code -1 (error) if generation or validation produces warning messages about malformed data.
All progress and warning messages are printed to stderr stream.
```

## TODO/Ideas

* Document the default attribute values from sdk_specs table.
* Dynamic default values, eg. for action prefix or category id/name (see notes in sdk_spec tables).
* Dynamic ID generation and write-back to plugin at runtime.
* Allow plugin author to set their own defaults.
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

import sys
import os.path
import importlib.util
import json
from types import ModuleType
from typing import (Union, TextIO)
from re import compile as re_compile

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from sdk_spec import *
from TpToPy import TpToPy

## globals
g_messages = []  # validation reporting
g_seen_ids = {}  # for validating unique IDs


## Utils

def getMessages():
    """ Gets a list of messages which may have been produced during generation/validation.
    """
    return g_messages

def clearMessages():
    """ Clears the list of validation warning messages.
    Do this before invoking `validateAttribValue()` directly (outside of the other functions provided here).
    """
    global g_messages
    g_messages.clear()

def _printMessages(messages:list):
    for msg in messages:
        _printToErr(msg)

def _addMessage(msg):
    global g_messages
    g_messages.append(msg)


def _seenIds():
    global g_seen_ids
    return g_seen_ids.keys()

def _addSeenId(id, path):
    global g_seen_ids
    g_seen_ids[id] = path

def _clearSeenIds():
    global g_seen_ids
    g_seen_ids.clear()


def _printToErr(msg):
    sys.stderr.write(msg + "\n")

def _normPath(path):
    if not isinstance(path, str):
        return path
    return os.path.normpath(os.path.join(os.getcwd(), path))

def _keyPath(path, key):
    return ":".join(filter(None, [path, key]))

## Generator functions

def _dictFromItem(item:dict, table:dict, sdk_v:int, path:str="", skip_invalid:bool=False):
    ret = {}
    if not isinstance(item, dict):
        return ret
    for k, data in table.items():
        # try get explicit value from item
        #if not data.get("doc"): continue
        if (v := item.get(k)) is None:
            if (not data.get('r') or data.get("DV", 0) >= sdk_v or data.get("v", 0) >= sdk_v) or "api" in k or "sdk" in k:
                continue
            # try get default value
            v = data.get('d')
        # check if there is nested data, eg. in an Action
        # print(k, data.get('t'), v)
        if isinstance(v, dict) and data.get('t') is list:
            # print(k, v)
            v = _arrayFromDict(v, data.get('l', {}), sdk_v, path=_keyPath(path, k), skip_invalid=skip_invalid)
        # check that the value is valid and add it to the dict if it is
        # print(k, v)
        if validateAttribValue(k, v, data, sdk_v, path) or (not skip_invalid and v != None):
            # if k in ['sdk','api']:
                # print(k, v, data, path)
            ret[k] = v
    return ret


def _arrayFromDict(d:dict, table:dict, sdk_v:int, category:str=None, path:str="", skip_invalid:bool=False):
    ret = []
    if not isinstance(d, dict):
        return ret

    if path in ["connectors", "actions"]:
        _processFormat(d)

    for key, item in d.items():
        if not category or not (cat := item.get('category')) or cat == category:
            # print(item, table)
            ret.append(_dictFromItem(item, table, sdk_v, f"{path}[{key}]", skip_invalid))
    return ret

def _processFormat(d:dict):
    if not isinstance(d, dict):
        return
    
    for _, item in d.items():
        if (data := item.get("data")) and isinstance(data, dict):
            data_ids = {}
            for k, v in data.items():
                if (did := v.get("id")):
                    data_ids[k] = did
            _replaceFormatTokens(item=item, data_ids=data_ids)

def _replaceFormat(data_ids:dict, fmt:str, d:dict):
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
            _addMessage(f"WARNING: Could not find replacement for token '{idx}' in 'format' attribute for element `{d.get('id')}`. The data arry does not contain this name/index.")
            continue
        # print(m.span(), val)
        fmt = fmt[:m.start()] + "{$" + val + "$}" + fmt[m.end():]
        begin = m.start() + len(val) + 4
    return fmt

def _replaceFormatTokens(item:list, data_ids:dict):
    if 'lines' in item.keys():
        for k, v in item.get('lines').items():
            for line in v:
                if (line_data := line.get('data')):
                    for data in line_data:
                        if not isinstance(data, dict) or not 'lineFormat' in data.keys():
                            continue
                        data['lineFormat'] = _replaceFormat(data_ids, data.get('lineFormat'), item)
    elif 'format' in item.keys():
        item['format'] = _replaceFormat(data_ids, item.get('format'), item)


def generateDefinitionFromScript(script:Union[str, TextIO], skip_invalid:bool=False):
    """
    Returns an "entry.tp" Python `dict` which is suitable for direct conversion to JSON format.

    `script` should be a valid python script, either a file path (ending in .py), string, or open file handle (like stdin).
    The script should contain "SDK declaration variables" like	`TP_PLUGIN_INFO`, `TP_PLUGIN_SETTINGS`, etc.

    Setting `skip_invalid` to `True` will skip attributes with invalid values (they will not be included in generated output).
    Default behavior is to only warn about them.

    Note that the script is interpreted (executed), so any actual "business" logic (like connecting to TP) should be in "__main__".
    Also note that when using input from a file handle or string, the script's "__file__" attribute is set to the current working
    directory and the file name "tp_plugin.py".

    May raise an `ImportError` if the plugin script could not be loaded or is missing required variables.
    Use `getMessages()` to check for any warnings/etc which may be generated (eg. from attribute validation).
    """
    script_str = ""
    if hasattr(script, "read"):
        script_str = script.read()
    elif not script.endswith(".py"):
        script_str = script

    try:
        if script_str:
            # load from a string
            spec = importlib.util.spec_from_loader("plugin", loader=None)
            plugin = importlib.util.module_from_spec(spec)
            setattr(plugin, "__file__", os.path.join(os.getcwd(), "tp_plugin.py"))
            exec(script_str, plugin.__dict__)
        else:
            # load directly from a file path
            spec = importlib.util.spec_from_file_location("plugin", script)
            plugin = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(plugin)
        # print(plugin.TP_PLUGIN_INFO)
    except Exception as e:
        input_name = "input stream" if script_str else script
        raise ImportError(f"ERROR while trying to import plugin code from '{input_name}': {repr(e)}")
    return generateDefinitionFromModule(plugin, skip_invalid)


def generateDefinitionFromModule(plugin:ModuleType, skip_invalid:bool=False):
    """
    Returns an "entry.tp" Python `dict`, which is suitable for direct conversion to JSON format.
    `plugin` should be a loaded Python "module" which contains "SDK declaration variables" like
    `TP_PLUGIN_INFO`, `TP_PLUGIN_SETTINGS`, etc. From within a plugin script this could be called like:
    `generateDefinitionFromModule(sys.modules[__name__])`.

    Setting `skip_invalid` to `True` will skip attributes with invalid values (they will not be included in generated output).
    Default behavior is to only warn about them.

    May raise an `ImportError` if the plugin script is missing required variables `TP_PLUGIN_INFO` and `TP_PLUGIN_CATEGORIES`.
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
        connectors = getattr(plugin, "TP_PLUGIN_CONNECTORS", {}),
        skip_invalid = skip_invalid
    )


def generateDefinitionFromDeclaration(info:dict, categories:dict, skip_invalid:bool=False, **kwargs):
    """
    Returns an "entry.tp" Python `dict` which is suitable for direct conversion to JSON format.
    Arguments should contain SDK declaration dict values, for example as specified for `TP_PLUGIN_INFO`, etc.

    The `info` and `category` values are required, the rest are optional.

    Setting `skip_invalid` to `True` will skip attributes with invalid values (they will not be included in generated output).
    Default behavior is to warn about them but still include them in the output.

    `**kwargs` can be one or more of:
    - settings:dict = {},
    - actions:dict = {},
    - states:dict = {},
    - events:dict = {},
    - connectors:dict = {}

    Use `getMessages()` to check for any warnings/etc which may be generated (eg. from attribute validation).
    """
    _clearSeenIds()
    clearMessages()
    settings = kwargs.get('settings', {})
    actions = kwargs.get('actions', {})
    states = kwargs.get('states', {})
    events = kwargs.get('events', {})
    connectors = kwargs.get('connectors', {})
    # print(info, categories, settings, actions, states, events, connectors)

    # Get the target SDK version (was either specified in plugin or is TPSDK_DEFAULT_VERSION)
    tgt_sdk_v = info.get('api', info.get('sdk', TPSDK_DEFAULT_VERSION))

    # Start the root entry.tp object using basic plugin metadata
    # This will also create an empty `categories` array in the root of the entry.

    entry = _dictFromItem(info, TPSDK_ATTRIBS_ROOT, tgt_sdk_v, "info")

    # Loop over each plugin category and set up actions, states, events, and connectors.
    for cat, data in categories.items():
        path = f"category[{cat}]"
        category = _dictFromItem(data, TPSDK_ATTRIBS_CATEGORY, tgt_sdk_v, path, skip_invalid)
        category['actions'] = _arrayFromDict(actions, TPSDK_ATTRIBS_ACTION, tgt_sdk_v, cat, "actions", skip_invalid)
        category['states'] = _arrayFromDict(states, TPSDK_ATTRIBS_STATE, tgt_sdk_v, cat, "states", skip_invalid)
        category['events'] = _arrayFromDict(events, TPSDK_ATTRIBS_EVENT, tgt_sdk_v, cat, "events", skip_invalid)
        if tgt_sdk_v >= 4:
            category['connectors'] = _arrayFromDict(connectors, TPSDK_ATTRIBS_CONNECTOR, tgt_sdk_v, cat, "connectors", skip_invalid)
        # add the category to entry's categories array
        entry['categories'].append(category)

    # print(entry)
    # Add Settings to root
    if tgt_sdk_v >= 3:
        entry['settings'] = _arrayFromDict(settings, TPSDK_ATTRIBS_SETTINGS, tgt_sdk_v, path = "settings", skip_invalid = skip_invalid)

    return entry


## Validation functions

def validateAttribValue(key:str, value, attrib_data:dict, sdk_v:int, path:str=""):
    """
    Validates one attribute's value based on provided lookup table and target SDK version.
    Returns `False` if any validation fails or `value` is `None`, `True` otherwise.
    Error description message(s) can be retrieved with `getMessages()` and cleared with `clearMessages()`.

    Args:
        `key` is the attribute name;
        `value` is what to validate;
        `attrib_data` is the lookup table data for the given key (eg. `TPSDK_ATTRIBS_INFO[key]` );
        `sdk_v` is the TP SDK version being used (for validation).
        `path` is just extra information to print before the key name in warning messages (to show where attribute is in the tree).
    """
    global g_seen_ids
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
    if key == "id":
        if not value in _seenIds():
            _addSeenId(value, keypath)
        else:
            _addMessage(f"WARNING: The ID '{value}' in '{keypath}' is not unique. It was previously seen in '{g_seen_ids.get(value)}'")
            return False
    if (deprecated_version := attrib_data.get('DV')):
        if sdk_v >= deprecated_version:
            _addMessage(f"WARNING: Attribute '{keypath}' is deprecated in v{deprecated_version}")
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
    `data` is a de-serialized entry.tp JSON object (eg. `json.load('entry.tp')`)
    Returns `True` if no problems were found, `False` otherwise.
    Use `getMessages()` to check for any validation warnings which may be generated.
    """
    _clearSeenIds()
    clearMessages()

    sdk_v = data.get('sdk', TPSDK_DEFAULT_VERSION)
    _validateDefinitionDict(data, TPSDK_ATTRIBS_ROOT, sdk_v)
    return len(g_messages) == 0

def validateDefinitionString(data: dict):
    """
    Validates a TP plugin definition structure from JSON string.
    `data` is an entry.tp JSON string
    Returns `True` if no problems were found, `False` otherwise.
    Use `getMessages()` to check for any validation warnings which may be generated.
    """
    return validateDefinitionObject(data)

def validateDefinitionFile(file:Union[str, TextIO]):
    """
    Validates a TP plugin definition structure from JSON file.
    `file` is a valid system path to an entry.tp JSON file *or* an already-opened file handle (eg. sys.stdin).
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

def _generateDefinition(script, output_path, indent, skip_invalid:bool=False):
    input_name = "input stream"
    if isinstance(script, str):
        if len(script.split(".")) < 2:
            script = script + ".py"
        input_name = script
    indent = None if indent is None or int(indent) < 0 else indent

    _printToErr(f"Generating plugin definition JSON from '{input_name}'...\n")
    entry = generateDefinitionFromScript(script, skip_invalid)
    entry_str = json.dumps(entry, indent=indent) + "\n"
    valid = True
    if (messages := getMessages()):
        valid = False
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
    return entry_str, valid


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
    return res

def generatePythonStruct(entry, name):
    _printToErr("Generating Python struct from entry json...\n")
    try:
        tp_to_py = TpToPy(entry)
        tp_to_py.writetoFile(name)
        _printToErr(f"Saved generated Python struct to '{name}'\n")
        return True
    except Exception as e:
        _printToErr(f"Error: {e}")
        return False

def main(sdk_args=None):
    from argparse import ArgumentParser

    parser = ArgumentParser(epilog="This script exits with status code -1 (error) if generation or validation produces warning messages about malformed data. "
                                   "All progress and warning messages are printed to stderr stream.")
    parser.add_argument("-g", "--generate", action='store_true',
                        help="Generate a definition file from plugin script data. This is the default action.")
    parser.add_argument("-v", "--validate", action='store_true',
                        help="Validate a definition JSON file (entry.tp). If given with `generate` then will validate the generated JSON output.")
    parser.add_argument("target", metavar="target", nargs="?", default="",
                        help="Either a plugin script for `generate` or an entry.tp file for `validate`. Paths are relative to current working directory. "
                             "Defaults to './TPPEntry.py' and './entry.tp' respectively. Use 'stdin' (or '-') to read from input stream instead. "
                             "Another usage is if you pass in a normal entry.tp without `validate` argument, It can generate "
                             "Python version of entry.tp struct. It will be saved in `TPPEntry.py` if `output` is not given.")
    gen_grp = parser.add_argument_group("Generator arguments")
    gen_grp.add_argument("-o", metavar="<file>",
                         help="Output file for `generate` action. Default will be a file named 'entry.tp' in the same folder as the input script. "
                           "Paths are relative to current working directory. Use 'stdout' (or '-') to print the output to the console/stream instead.")
    gen_grp.add_argument("-s", "--skip-invalid", action='store_true', dest="skip_invalid", default=False,
                         help="Skip attributes with invalid values (they will not be included in generated output). Default behavior is to only warn about them.")
    gen_grp.add_argument("-i", "--indent", metavar="<n>", type=int, default=2,
                         help="Indent level (spaces) for generated JSON. Use 0 for only newlines, or -1 for the most compact representation. Default is %(default)s spaces.")
    gen_grp.add_argument("--noconfirm", action='store_true', default=False,
                         help="When generating python struct from entry.tp, you can pass this arg to bypass confirm if you want to contiune if any error is given for vaildating entry.tp before generate python struct")
    opts = parser.parse_args(sdk_args)
    del parser

    t = _normPath(opts.target or "TPPEntry.py")
    if opts.target.endswith(".tp") and not opts.validate:
        valid = _validateDefinition(t)
        # Incase if file is invaild they will have choice to either contiune. but --noconfirm can override this.
        # so that way if they use on github action it can still contiune if they wish.
        if not valid and not opts.noconfirm: input("Found errors. Press Enter to build or Ctrl+C to exit...")
        successful = generatePythonStruct(t, opts.o or "TPPEntry.py")
        if not successful: _printToErr("Failed to generate exiting...")

        return successful

    # default action
    opts.generate = opts.generate or not opts.validate

    _printToErr("")

    if opts.target in ("-","stdin"):
        opts.target = sys.stdin

    valid = True
    entry_str = ""
    if opts.generate:
        opts.target = _normPath(opts.target or "TPPEntry.py")
        output_path = None
        if opts.o:
            if opts.o not in ("-","stdout"):
                output_path = opts.o
        else:
            out_dir = os.getcwd() if hasattr(opts.target, "read") else os.path.dirname(opts.target)
            output_path = os.path.join(out_dir, "entry.tp")
        sys.path.append(os.path.dirname(os.path.realpath(opts.target)))
        entry_str, valid = _generateDefinition(opts.target, output_path, opts.indent, opts.skip_invalid)
        if opts.validate and output_path:
            opts.target = output_path

    if opts.validate:
        if entry_str:
            valid = _validateDefinition(entry_str, True)
        elif opts.target.endswith(".py"): # checks if is python file if It is then It will vaildate the python file by converting it to json first
            valid = _validateDefinition(generateDefinitionFromScript(opts.target), as_str=True) # little hacky lol
        else:
            opts.target = _normPath(opts.target or "entry.tp")
            valid = _validateDefinition(opts.target)

    return 0 if valid else -1


if __name__ == "__main__":
    sys.exit(main())
