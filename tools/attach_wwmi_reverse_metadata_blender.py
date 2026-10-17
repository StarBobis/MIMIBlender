"""Attach recorded WWMI reverse batches to selected meshes in an old project.

Run this file from Blender's Text Editor after enabling the updated addon.
Set source_json below to the reverse export's JSON, then select its meshes.
This repairs metadata only: it never imports/replaces geometry or edits keys.
It does not save the blend, modify extraction files, or export any buffers.
The exporter still validates the target workspace and every runtime overlap.
An incorrect source is not made compatible merely by running this script.
"""

import json
from pathlib import Path
import sys

import bpy


# Set the explicit reverse JSON path; never search a user's disk for a guess.
# Select the edited meshes that came from that reverse source before running.
# Use Merged for genuine cross-component weights; this does not change palettes.
source_json = r""


def attach(source, objects):
    """Use the enabled addon's helper without depending on its install name.

    Extension installs and development installs use different package prefixes.
    Refuse ambiguous simultaneously loaded addon copies instead of choosing one.
    Snapshot all target properties so an attachment failure can be rolled back.
    The caller decides when or whether to save their project after checking it.
    """
    if not source:
        raise ValueError('Set source_json to the explicit reverse JSON path first.')
    modules = {module for name, module in list(sys.modules.items())
               if name.endswith('.workspace.wwmi_reverse_metadata')}
    if len(modules) != 1:
        raise ValueError('Enable exactly one updated MIMIBlender addon before attaching metadata.')
    helper = modules.pop()
    meshes = [obj for obj in objects if obj.type == 'MESH']
    if not meshes:
        raise ValueError('Select the meshes imported from this reverse source first.')
    data = json.loads(Path(source).read_text(encoding='utf-8-sig'))
    if (data.get('GamePreset') != 'WWMI' or not data.get('MatchComponentList')
            or not data.get('ShapeKeysInfo', {}).get('batches')):
        raise ValueError('This JSON has no WWMI reverse component matches and runtime batches.')
    buffers = {'metadata': data['ShapeKeysInfo'],
               'source_match_components': data['MatchComponentList']}
    key = helper.PROPERTY_NAME
    previous = [(obj, obj.get(key)) for obj in meshes]
    try:
        for obj in meshes:
            helper.capture_reverse_shape_metadata(obj, buffers)
    except Exception:
        # Roll back only this property; geometry and other custom data are untouched.
        # A missing old property is different from an old stored JSON value.
        # Re-raise so the user sees the original attachment failure.
        for obj, value in previous:
            if value is None:
                if key in obj:
                    del obj[key]
            else:
                obj[key] = value
        raise
    print('Attached WWMI reverse metadata to ' + str(len(meshes)) + ' selected meshes. '
          'No files saved. Export will validate the source against the target workspace.')


if __name__ == '__main__':
    attach(source_json, bpy.context.selected_objects)
