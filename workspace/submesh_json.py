from dataclasses import dataclass, field
import os

from ..utils.json_utils import JsonUtils
from ..common.d3d11_element import D3D11Element


@dataclass
class SubmeshIndexBuffer:
	DXGI_FORMAT:str
	FileName:str
	FilePath:str = field(init=False)

	def bind_dir_path(self, dir_path:str):
		self.FilePath = os.path.join(dir_path, self.FileName)


@dataclass
class SubmeshShapeKeyPositionBuffer:
	ShapeKeyName:str
	FileName:str
	FilePath:str = field(init=False)

	def bind_dir_path(self, dir_path:str):
		self.FilePath = os.path.join(dir_path, self.FileName)


@dataclass
class SubmeshDrawCallSegment:
	IBIndex:int
	IndexOffset:int
	IndexCount:int
	DrawStartIndex:int = 0


@dataclass
class SubmeshCategoryBuffer:
	FileName:str
	Type:str
	D3D11ElementList:list[D3D11Element] = field(default_factory=list)
	FilePath:str = field(init=False)
	Stride:int = field(init=False, default=0)

	def bind_dir_path(self, dir_path:str):
		self.FilePath = os.path.join(dir_path, self.FileName)

	def calc_stride(self):
		self.Stride = sum(d3d11_element.ByteWidth for d3d11_element in self.D3D11ElementList)


@dataclass
class SubmeshJson:
	JsonFilePath:str

	FileName:str = field(init=False)
	DirPath:str = field(init=False)
	JsonDict:dict = field(init=False, repr=False)

	GamePreset:str = field(init=False, default="")
	VertexLimitVB:str = field(init=False, default="")
	CSOutputVertexLimitVB:str = field(init=False, default="")
	CategoryHash:dict = field(init=False, default_factory=dict)
	CategoryDrawCategoryMap:dict = field(init=False, default_factory=dict)
	WorkGameType:str = field(init=False, default="")
	GPU_PreSkinning:bool = field(init=False, default=False)
	LocalBoundingBoxMin:list = field(init=False, default_factory=list)
	LocalBoundingBoxMax:list = field(init=False, default_factory=list)
	VertexCompressionParams:list = field(init=False, default_factory=list)
	VertexOffset:int = field(init=False, default=0)
	VertexCount:int = field(init=False, default=-1)
	MatchCS:str = field(init=False, default="")
	MatchUAVBytes:int = field(init=False, default=0)
	CB4Hash:str = field(init=False, default="")
	BoneMatrixFileName:str = field(init=False, default="")
	VGOffset:int = field(init=False, default=0)
	VGCount:int = field(init=False, default=0)
	VGMap:dict = field(init=False, default_factory=dict)
	ShapeKeysInfo:dict = field(init=False, default_factory=dict)
	DrawCallIndexList:list[str] = field(init=False, default_factory=list)
	DrawCallSegmentList:list[SubmeshDrawCallSegment] = field(init=False, default_factory=list)
	IndexBufferList:list[SubmeshIndexBuffer] = field(init=False, default_factory=list)
	CategoryBufferList:list[SubmeshCategoryBuffer] = field(init=False, default_factory=list)
	ShapeKeyPositionBufferList:list[SubmeshShapeKeyPositionBuffer] = field(init=False, default_factory=list)
	TextureMarkUpInfoList:list = field(init=False, default_factory=list)
	SubMeshRole:str = field(init=False, default="")

	def __post_init__(self):
		self.FileName = os.path.basename(self.JsonFilePath)
		self.DirPath = os.path.dirname(self.JsonFilePath)
		self.JsonDict = JsonUtils.LoadFromFile(self.JsonFilePath)
		self.parse_json_dict()

	def parse_json_dict(self):
		self.GamePreset = self.JsonDict.get("GamePreset", "")
		self.VertexLimitVB = self.JsonDict.get("VertexLimitVB", "")
		self.CSOutputVertexLimitVB = self.JsonDict.get("CSOutputVertexLimitVB", "")
		self.CategoryHash = self.JsonDict.get("CategoryHash", {})
		self.CategoryDrawCategoryMap = self.JsonDict.get("CategoryDrawCategoryMap", {})
		self.WorkGameType = self.JsonDict.get("WorkGameType", "")
		self.GPU_PreSkinning = self.JsonDict.get("GPU-PreSkinning", False)
		self.LocalBoundingBoxMin = list(self.JsonDict.get("LocalBoundingBoxMin", []))
		self.LocalBoundingBoxMax = list(self.JsonDict.get("LocalBoundingBoxMax", []))
		self.VertexCompressionParams = list(self.JsonDict.get("VertexCompressionParams", []))
		self.TextureMarkUpInfoList = list(self.JsonDict.get("TextureMarkUpInfoList", []))
		role = self.JsonDict.get("SubMeshRole", "")
		self.SubMeshRole = role if role in {"Face", "Neck", "Eye"} else ""
		self.VertexOffset = int(self.JsonDict.get("VertexOffset", 0))
		self.VertexCount = int(self.JsonDict.get("VertexCount", -1))
		self.MatchCS = str(self.JsonDict.get("match_cs", "") or "").strip()
		self.MatchUAVBytes = int(self.JsonDict.get("match_uav_bytes", 0) or 0)
		self.CB4Hash = self.JsonDict.get("CB4Hash", "")
		self.BoneMatrixFileName = self.JsonDict.get("BoneMatrixFileName", "")
		self.VGOffset = int(self.JsonDict.get("VGOffset", 0))
		self.VGCount = int(self.JsonDict.get("VGCount", 0))
		self.VGMap = dict(self.JsonDict.get("VGMap", {}))
		self.ShapeKeysInfo = dict(self.JsonDict.get("ShapeKeysInfo", {}))
		self.DrawCallIndexList = [str(draw_call_index) for draw_call_index in self.JsonDict.get("DrawCallIndexList", [])]

		self.DrawCallSegmentList = []
		for draw_call_segment_json in self.JsonDict.get("DrawCallSegmentList", []):
			draw_call_segment = SubmeshDrawCallSegment(
				IBIndex=int(draw_call_segment_json.get("IBIndex", 0)),
				IndexOffset=int(draw_call_segment_json.get("IndexOffset", 0)),
				IndexCount=int(draw_call_segment_json.get("IndexCount", 0)),
				DrawStartIndex=int(draw_call_segment_json.get("DrawStartIndex", 0)),
			)
			self.DrawCallSegmentList.append(draw_call_segment)

		self.IndexBufferList = []
		for index_buffer_json in self.JsonDict.get("IndexBufferList", []):
			index_buffer = SubmeshIndexBuffer(
				DXGI_FORMAT=index_buffer_json.get("DXGI_FORMAT", ""),
				FileName=index_buffer_json.get("FileName", "")
			)
			index_buffer.bind_dir_path(self.DirPath)
			self.IndexBufferList.append(index_buffer)

		self.CategoryBufferList = []
		for category_buffer_json in self.JsonDict.get("CategoryBufferList", []):
			aligned_byte_offset = 0
			d3d11_element_list = []
			for d3d11_element_json in category_buffer_json.get("D3D11ElementList", []):
				d3d11_element = D3D11Element(
					SemanticName=d3d11_element_json.get("SemanticName", ""),
					SemanticIndex=int(d3d11_element_json.get("SemanticIndex", 0)),
					Format=d3d11_element_json.get("Format", ""),
					ByteWidth=int(d3d11_element_json.get("ByteWidth", 0)),
					ExtractSlot=d3d11_element_json.get("ExtractSlot", ""),
					ExtractTechnique=d3d11_element_json.get("ExtractTechnique", ""),
					Category=d3d11_element_json.get("Category", ""),
					AlignedByteOffset=aligned_byte_offset,
				)
				aligned_byte_offset += d3d11_element.ByteWidth
				d3d11_element_list.append(d3d11_element)

			category_buffer = SubmeshCategoryBuffer(
				FileName=category_buffer_json.get("FileName", ""),
				Type=category_buffer_json.get("Type", ""),
				D3D11ElementList=d3d11_element_list,
			)
			category_buffer.bind_dir_path(self.DirPath)
			category_buffer.calc_stride()
			self.CategoryBufferList.append(category_buffer)

		self.ShapeKeyPositionBufferList = []
		for shapekey_buffer_json in self.JsonDict.get("ShapeKeyPositionBufferList", []):
			shapekey_buffer = SubmeshShapeKeyPositionBuffer(
				ShapeKeyName=shapekey_buffer_json.get("ShapeKeyName", ""),
				FileName=shapekey_buffer_json.get("FileName", ""),
			)
			shapekey_buffer.bind_dir_path(self.DirPath)
			self.ShapeKeyPositionBufferList.append(shapekey_buffer)

	def get_d3d11_element_json_list(self) -> list[dict]:
		d3d11_element_json_list = []
		for category_buffer_json in self.JsonDict.get("CategoryBufferList", []):
			for d3d11_element_json in category_buffer_json.get("D3D11ElementList", []):
				d3d11_element_json_list.append(dict(d3d11_element_json))
		return d3d11_element_json_list
