"""Collect WWMI metadata before any export files are written.

Collection runs during normal blueprint parsing, before model construction.
One plain dictionary snapshots the current node for the selected export.
The runtime resource names remain unchanged; only their contents vary.
Missing nodes preserve the legacy exporter behavior.
Unusable Logo paths fail before geometry can overwrite an existing Mod.
Text stays in quoted INI data, matching the established resource format.
Unsupported quoting is rejected explicitly rather than guessed or replaced.
"""

import os
from ...common.global_config import GlobalConfig, LogicName
from ...i18n.i18n import tr


def collect_mod_info(tree):
    # A saved WWMI node must not affect any other preset's exporter.
    if GlobalConfig.logic_name != LogicName.WWMI:
        return {}
    nodes = [node for node in tree.nodes if node.bl_idname == 'MIMINode_WWMI_Mod_Info']
    if len(nodes) > 1:
        raise ValueError(tr("Only one WWMI Mod Info node is allowed per blueprint"))
    if not nodes:
        return {}
    node = nodes[0]
    values = {name: getattr(node, name).strip() for name in ('mod_name', 'mod_author', 'mod_desc', 'mod_link', 'mod_logo')}
    # Quoted INI data is single-line. Reject ambiguous syntax instead of
    # silently changing user metadata or injecting extra sections.
    for field in ('mod_name', 'mod_author', 'mod_desc', 'mod_link'):
        if any(char in values[field] for char in ('"', '\n', '\r', '\0')):
            raise ValueError(tr("Mod info text cannot contain double quotes or line breaks"))
    if values['mod_logo']:
        import bpy
        path = bpy.path.abspath(values['mod_logo'])
        # Validate the source before geometry writes, including relative paths.
        # The runtime expects a DDS image; do not rename arbitrary image bytes.
        if not os.path.isfile(path):
            raise ValueError(tr("Mod Logo DDS file was not found: {path}").format(path=path))
        with open(path, 'rb') as source:
            if len(source.read(128)) < 128:
                raise ValueError(tr("Mod Logo must be a DDS file"))
            source.seek(0)
            if source.read(4) != b'DDS ':
                raise ValueError(tr("Mod Logo must be a DDS file"))
        values['mod_logo'] = path
    return values
