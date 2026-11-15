from dataclasses import dataclass, field


# Storage and transfer space are independent parts of the serialized contract.
# GPU semantic names and Blender layer names remain COLOR, COLOR1, and so on.
COLOR_POLICIES = {
    'BYTECOLOR_LINEAR': ('BYTE_COLOR', 'color'),
    'BYTECOLOR_SRGB': ('BYTE_COLOR', 'color_srgb'),
    'FLOATCOLOR_LINEAR': ('FLOAT_COLOR', 'color'),
    'FLOATCOLOR_SRGB': ('FLOAT_COLOR', 'color_srgb'),
}


def resolve_color_policy(hint='', logic_name='', storage_type=None):
    """Resolve explicit policies first; legacy aliases retain old project behavior."""
    normalized = hint.strip().upper()
    if normalized in COLOR_POLICIES:
        return COLOR_POLICIES[normalized]
    # Only old files may omit the transfer space. Never guess unknown values.
    legacy = normalized.replace('_', '')
    if legacy not in ('', 'BYTECOLOR', 'FLOATCOLOR'):
        raise ValueError('Unknown BlenderColorType: ' + hint)
    if legacy == 'FLOATCOLOR' or (not legacy and storage_type == 'FLOAT_COLOR'):
        return COLOR_POLICIES['FLOATCOLOR_LINEAR']
    if not legacy and logic_name in ('WWMI', 'EFMI'):
        return COLOR_POLICIES['FLOATCOLOR_LINEAR']
    # The prior ZZMI correction used the stored-byte sRGB API for byte layers.
    if logic_name == 'ZZMI':
        return COLOR_POLICIES['BYTECOLOR_SRGB']
    return COLOR_POLICIES['BYTECOLOR_LINEAR']


@dataclass
class D3D11Element:
    SemanticName:str
    SemanticIndex:int
    Format:str
    ByteWidth:int
    # Which type of slot and slot number it use? eg:vb0
    ExtractSlot:str
    # Is it from pointlist or trianglelist or compute shader?
    ExtractTechnique:str
    # Human named category, also will be the buf file name suffix.
    Category:str

    # Fixed items
    InputSlot:str = field(default="0", init=False, repr=False)
    InputSlotClass:str = field(default="per-vertex", init=False, repr=False)
    InstanceDataStepRate:str = field(default="0", init=False, repr=False)

    # Generated Items
    ElementNumber:int = field(init=False,default=0)
    AlignedByteOffset:int
    ElementName:str = field(init=False,default="")

    # Explicit BYTECOLOR/FLOATCOLOR + _LINEAR/_SRGB policy from SubmeshJson.
    # Missing and storage-only values are accepted only for legacy workspaces.
    BlenderColorType:str = field(default="")

    def __post_init__(self):
        self.ElementName = self.get_indexed_semantic_name()
        # Validate before import can create a temporary object or color layer.
        if self.SemanticName.startswith('COLOR'):
            resolve_color_policy(self.BlenderColorType)

    def get_indexed_semantic_name(self)->str:
        if self.SemanticIndex == 0:
            return self.SemanticName
        else:
            return self.SemanticName + str(self.SemanticIndex)

    def get_blender_color_type(self, logic_name:str="")->str:
        # Kept as the storage-only accessor for existing callers.
        return resolve_color_policy(self.BlenderColorType, logic_name)[0]

    def get_blender_color_property(self, logic_name:str="")->str:
        # Import and export must use the same API view for a given policy.
        return resolve_color_policy(self.BlenderColorType, logic_name)[1]
