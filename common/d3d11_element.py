from dataclasses import dataclass, field


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

    # Blender color attribute type hint carried by the SubmeshJson
    # ("BYTECOLOR" / "FLOATCOLOR"); empty on old extractions, in which case
    # get_blender_color_type() falls back to the historical per-game rule.
    BlenderColorType:str = field(default="")

    def __post_init__(self):
        self.ElementName = self.get_indexed_semantic_name()

    def get_indexed_semantic_name(self)->str:
        if self.SemanticIndex == 0:
            return self.SemanticName
        else:
            return self.SemanticName + str(self.SemanticIndex)

    def get_blender_color_type(self, logic_name:str="")->str:
        '''
        Resolve which Blender color attribute data type to create for a COLOR
        element: 'BYTE_COLOR' or 'FLOAT_COLOR'.

        New MMT/SSMT5 extractions annotate COLOR elements explicitly via the
        BlenderColorType field. Old extractions without the annotation keep
        the historical behavior so existing workspaces import exactly as
        before: WWMI/EFMI use FLOAT_COLOR (their shaders read high-precision
        COLOR payloads such as smooth normals), other games use BYTE_COLOR.
        '''
        if self.BlenderColorType:
            # Normalize so both "FLOATCOLOR" and "FLOAT_COLOR" spellings work.
            normalized = self.BlenderColorType.strip().upper().replace("_", "")
            if normalized == "FLOATCOLOR":
                return 'FLOAT_COLOR'
            return 'BYTE_COLOR'

        # Lazy import keeps this pure data module free of bpy-side imports.
        from .global_config import LogicName
        if logic_name in (LogicName.WWMI, LogicName.EFMI):
            return 'FLOAT_COLOR'
        return 'BYTE_COLOR'