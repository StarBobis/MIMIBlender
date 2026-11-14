"""Node-owned outline options; old nodes explicitly retain legacy behavior."""

from ..common.global_config import GlobalConfig, LogicName
from ..i18n.i18n import tr

PRESETS = (LogicName.GIMI, LogicName.SRMI, LogicName.HIMI, LogicName.ZZMI)


def snapshot(node):
    # Snapshot the selected output, so two Mods can choose independent policies.
    if GlobalConfig.logic_name not in PRESETS:
        return {}
    return dict(mode=getattr(node, 'outline_mode', 'LEGACY'), precision=getattr(node, 'outline_precision', 8),
                custom_normals=getattr(node, 'outline_custom_normals', False),
                gate=getattr(node, 'outline_gate', 10.0), himi_target=getattr(node, 'outline_himi_target', 'TANGENT'))


def draw(node, layout):
    if GlobalConfig.logic_name not in PRESETS:
        return
    box = layout.box()
    box.prop(node, 'outline_settings_open', text=tr('Outline Rebuild'), icon='TRIA_DOWN' if node.outline_settings_open else 'TRIA_RIGHT', emboss=False)
    if not node.outline_settings_open:
        return
    box.prop(node, 'outline_mode')
    if node.outline_mode != 'MODERN':
        return
    if GlobalConfig.logic_name == LogicName.HIMI:
        box.prop(node, 'outline_himi_target')
    box.prop(node, 'outline_precision')
    box.prop(node, 'outline_custom_normals')
    if GlobalConfig.logic_name == LogicName.ZZMI:
        box.prop(node, 'outline_gate')
