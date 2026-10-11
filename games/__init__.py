"""
Game exporter registry.

Every supported game preset maps its LogicName to one exporter class here,
so the export UI dispatches with a single lookup instead of a long
if/elif chain, and every preset is free to pick its internal structure:

- Single module (games/snowbreak.py): presets whose unique logic fits in
  one file.  Most of them only override add_drawib_sections() on top of
  the shared StandardExporter pipeline.
- Package (games/wwmi/): presets with several logic files (own models,
  shape keys, blueprint nodes, ...), so everything game-specific stays in
  one folder.
"""

from ..common.global_config import LogicName

from .efmi import ExportEFMI
from .gimi.exporter import Exporter as GimiExporter
from .identityv import ExportIdentityV
from .naraka.exporter import Exporter as NarakaExporter
from .ntemi.exporter import Exporter as NtemiExporter
from .snowbreak import ExportSnowBreak
from .srmi import ExportSRMI
from .unity import UnityVsExporter, UnityCsExporter
from .wwmi.exporter import Exporter as WwmiExporter
from .yysls import ExportYYSLS
from .zzmi import ExportZZMI
from .zzmidx12 import ExportZZMIDX12

# LogicName -> exporter class.  Presets without an entry raise the
# "not yet supported" error in the export UI.
_LOGIC_EXPORTER_DICT = {
    LogicName.EFMI: ExportEFMI,
    LogicName.GIMI: GimiExporter,
    # HIMI's generated INI is byte-identical to the Unity VS variant, so it
    # shares the class; if HIMI ever needs its own logic again, create a
    # games/himi.py and point this entry at it.
    LogicName.HIMI: UnityVsExporter,
    LogicName.IdentityV: ExportIdentityV,
    LogicName.SRMI: ExportSRMI,
    LogicName.ZZMI: ExportZZMI,
    LogicName.ZZMIDX12: ExportZZMIDX12,
    LogicName.WWMI: WwmiExporter,
    LogicName.NTEMI: NtemiExporter,
    LogicName.SnowBreak: ExportSnowBreak,
    LogicName.YYSLS: ExportYYSLS,
    LogicName.Naraka: NarakaExporter,
    # The old ExportUnity picked the VS/CS path by checking logic_name at
    # runtime; the registry now maps every preset straight to its variant.
    LogicName.NarakaM: UnityCsExporter,
    LogicName.GF2: UnityVsExporter,
    LogicName.AILIMIT: UnityCsExporter,
}


def get_exporter_class(logic_name):
    """Return the exporter class of a LogicName, or None when unsupported."""
    return _LOGIC_EXPORTER_DICT.get(logic_name)


def get_tree_post_processor(logic_name):
    """Return the blueprint tree post-processor of a game preset, if any.

    A tree post-processor runs right after BluePrintModel finishes parsing
    the node tree and may annotate the parsed DrawCallModels with
    game-specific data (Naraka uses it for its cross-IB rendering pairs).
    Imported lazily so the shared model layer never depends on game code.
    """
    if logic_name == LogicName.Naraka:
        from .naraka.cross_ib import apply_cross_ib_render_nodes
        return apply_cross_ib_render_nodes
    return None
