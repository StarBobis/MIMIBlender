import bpy
import numpy
import os

from .d3d11_element import D3D11Element
from .mesh_create_helper import MeshCreateHelper
from ..workspace.submesh_json import SubmeshJson, SubmeshCategoryBuffer
from .global_properties import GlobalProperties
from ..utils.format_utils import Fatal, FormatUtils


class SSMTImportHelper:
	@staticmethod
	def create_mesh_from_json(json_file_path:str, import_collection:bpy.types.Collection | None = None):
		submesh_json = SubmeshJson(json_file_path)

		elements, vb_data, vb_vertex_count, shapekey_buffers = SSMTImportHelper.parse_category_buffers(submesh_json)
		ib_data_list, ib_entry_array_indices, ib_data, ib_count, ib_polygon_count = SSMTImportHelper.parse_index_buffers(submesh_json)
		shapekey_position_data = SSMTImportHelper.parse_shapekey_position_buffers(submesh_json)

		mesh_name = os.path.splitext(submesh_json.FileName)[0]
		logic_name = submesh_json.GamePreset
		gametypename = submesh_json.WorkGameType

		# Merged / UniComponent 模式：通过VGMap将local blend index重映射为global bone ID
		wwmi_vg_map = submesh_json.VGMap if (submesh_json.VGMap and GlobalProperties.is_merged_mode()) else None

		# 逆向产物可能携带 DrawCallSegmentList（每一条 drawindexed 一个分段）。
		# 存在有效分段时逐段创建独立网格对象（分段创建模型，与经典 fmt 输出的
		# 逐切片拆分语义一致）；不存在时按整条 IB 作为单一网格导入。
		draw_call_segments = SSMTImportHelper.resolve_draw_call_segments(
			submesh_json=submesh_json,
			ib_data_list=ib_data_list,
			ib_entry_array_indices=ib_entry_array_indices,
			ib_data_full=ib_data,
			vb_vertex_count=vb_vertex_count,
		)
		if len(draw_call_segments) > 0:
			if shapekey_buffers:
				# WWMI 风格形态键（ShapeKeyOffset/VertexId/VertexOffset 三件套）：
				# 缓冲是整份对象空间的，导入时按每个分段的顶点窗口
				# [vertex_min, vertex_max] 换算（local = global - vertex_min），
				# 与整体导入的 vertex_offset/vertex_count 语义一致。
				print("DrawCallSegment 导入：检测到 WWMI 风格形态键Buffer，按分段顶点窗口逐段导入")

			imported_obj_list = []
			for segment_index, (segment_ib_data, vertex_min, vertex_max, segment_info) in enumerate(draw_call_segments):
				if len(draw_call_segments) == 1:
					segment_mesh_name = mesh_name
				else:
					segment_mesh_name = mesh_name + "-" + str(segment_index + 1).zfill(2)

				# 每个分段独立压缩顶点区间 [vertex_min, vertex_max]，
				# VB 各元素数据与形态键数据按相同区间切片，IB 重基准到 0。
				segment_vb_data = {}
				for element_name, element_data in vb_data.items():
					segment_vb_data[element_name] = element_data[vertex_min:vertex_max + 1]

				segment_shapekey_position_data = {}
				for shapekey_name, shapekey_data in shapekey_position_data.items():
					segment_shapekey_position_data[shapekey_name] = shapekey_data[vertex_min:vertex_max + 1]

				segment_obj = MeshCreateHelper.create_mesh_object(
					mesh_name=segment_mesh_name,
					source_path=submesh_json.JsonFilePath,
					logic_name=logic_name,
					gametypename=gametypename,
					elements=elements,
					vb_data=segment_vb_data,
					ib_data=segment_ib_data - vertex_min,
					vb_vertex_count=vertex_max - vertex_min + 1,
					ib_count=len(segment_ib_data),
					ib_polygon_count=int(len(segment_ib_data) / 3),
					import_collection=import_collection,
					shapekey_position_data=segment_shapekey_position_data if segment_shapekey_position_data else None,
					# WWMI 形态键三件套：整份缓冲 + 分段顶点窗口
					# （global vertex id → 本段局部 id = global - vertex_min）。
					wwmi_shapekey_buffers=shapekey_buffers if shapekey_buffers else None,
					wwmi_vertex_offset=vertex_min,
					wwmi_vertex_count=vertex_max - vertex_min + 1,
					wwmi_vg_map=wwmi_vg_map,
					wwmi_vg_offset=submesh_json.VGOffset,
				)
				segment_obj["3DMigoto:DrawCallIBIndex"] = segment_info["ib_index"]
				segment_obj["3DMigoto:DrawCallIndexOffset"] = segment_info["index_offset"]
				segment_obj["3DMigoto:DrawCallIndexCount"] = segment_info["index_count"]
				imported_obj_list.append(segment_obj)

			if len(imported_obj_list) > 0:
				print("DrawCallSegment 导入完成，共创建 " + str(len(imported_obj_list)) + " 个分段网格")
				return imported_obj_list[0]

			print("DrawCallSegmentList 全部分段无效，回退为整体导入")

		return MeshCreateHelper.create_mesh_object(
			mesh_name=mesh_name,
			source_path=submesh_json.JsonFilePath,
			logic_name=logic_name,
			gametypename=gametypename,
			elements=elements,
			vb_data=vb_data,
			ib_data=ib_data,
			vb_vertex_count=vb_vertex_count,
			ib_count=ib_count,
			ib_polygon_count=ib_polygon_count,
			local_bounding_box_min=submesh_json.LocalBoundingBoxMin,
			local_bounding_box_max=submesh_json.LocalBoundingBoxMax,
			vertex_compression_params=submesh_json.VertexCompressionParams,
			import_collection=import_collection,
			wwmi_shapekey_buffers=shapekey_buffers if shapekey_buffers else None,
			shapekey_position_data=shapekey_position_data if shapekey_position_data else None,
			wwmi_vertex_offset=submesh_json.VertexOffset,
			wwmi_vertex_count=submesh_json.VertexCount,
			wwmi_vg_map=wwmi_vg_map,
			wwmi_vg_offset=submesh_json.VGOffset,
		)

	@staticmethod
	def resolve_draw_call_segments(submesh_json:SubmeshJson, ib_data_list:list, ib_entry_array_indices:list, ib_data_full, vb_vertex_count:int):
		'''
		解析 DrawCall 分段信息，返回 [(segment_ib_data, vertex_min, vertex_max, segment_info)]。

		优先使用 DrawCallSegmentList（逆向工具输出的完整有序分段，每一条
		drawindexed 一个分段，不做去重）。
		缺失时回退使用 DrawCallIndexList 顺序切分——但该字段旧版按 drawNumber
		去重，仅当其计数总和与 IB 实际索引数完全一致时才可信，否则放弃分段。
		'''
		raw_segments = []

		if len(submesh_json.DrawCallSegmentList) > 0:
			for draw_call_segment in submesh_json.DrawCallSegmentList:
				if draw_call_segment.IBIndex < 0 or draw_call_segment.IBIndex >= len(ib_entry_array_indices):
					print("DrawCallSegment 导入：分段指向不存在的 IBIndex " + str(draw_call_segment.IBIndex) + "，已跳过")
					continue

				source_ib_data = ib_data_list[ib_entry_array_indices[draw_call_segment.IBIndex]]
				if draw_call_segment.IndexCount <= 0:
					continue

				segment_end = draw_call_segment.IndexOffset + draw_call_segment.IndexCount
				if draw_call_segment.IndexOffset < 0 or segment_end > len(source_ib_data):
					print(
						"DrawCallSegment 导入：分段范围越界 (IBIndex=" + str(draw_call_segment.IBIndex)
						+ ", IndexOffset=" + str(draw_call_segment.IndexOffset)
						+ ", IndexCount=" + str(draw_call_segment.IndexCount)
						+ ", IB索引数=" + str(len(source_ib_data)) + ")，已跳过"
					)
					continue

				raw_segments.append((
					source_ib_data[draw_call_segment.IndexOffset:segment_end],
					{
						"ib_index": draw_call_segment.IBIndex,
						"index_offset": draw_call_segment.IndexOffset,
						"index_count": draw_call_segment.IndexCount,
					},
				))
		elif len(submesh_json.DrawCallIndexList) > 0:
			index_count_list = []
			for draw_call_index in submesh_json.DrawCallIndexList:
				try:
					index_count_list.append(int(draw_call_index))
				except (TypeError, ValueError):
					index_count_list = []
					break

			if len(index_count_list) > 0:
				if sum(index_count_list) == len(ib_data_full):
					index_offset = 0
					for index_count in index_count_list:
						raw_segments.append((
							ib_data_full[index_offset:index_offset + index_count],
							{"ib_index": -1, "index_offset": index_offset, "index_count": index_count},
						))
						index_offset += index_count
				else:
					print(
						"DrawCallIndexList 合计索引数 " + str(sum(index_count_list))
						+ " 与 IB 实际索引数 " + str(len(ib_data_full))
						+ " 不一致（旧版逆向工具对重复 drawNumber 做了去重），无法可靠分段，改为整体导入。"
						+ "使用更新后的逆向工具重新逆向即可获得 DrawCallSegmentList 精确分段。"
					)

		draw_call_segments = []
		for segment_ib_data, segment_info in raw_segments:
			if len(segment_ib_data) == 0:
				continue

			vertex_min = int(segment_ib_data.min())
			vertex_max = int(segment_ib_data.max())
			if vertex_min < 0 or vertex_max >= vb_vertex_count:
				print(
					"DrawCallSegment 导入：分段顶点范围 [" + str(vertex_min) + ", " + str(vertex_max)
					+ "] 超出 VB 顶点数 " + str(vb_vertex_count) + "，已跳过"
				)
				continue

			draw_call_segments.append((segment_ib_data, vertex_min, vertex_max, segment_info))

		return draw_call_segments

	@staticmethod
	def parse_index_buffers(submesh_json:SubmeshJson):
		'''
		解析 IndexBufferList 中的全部 IB 文件。

		返回 (ib_data_list, ib_entry_array_indices, ib_data_full, ib_count, ib_polygon_count)：
		- ib_data_list：按 FileName 去重后的 IB 数组列表（保持首次出现顺序），
		  供 DrawCallSegmentList 按 IBIndex 索引；
		- ib_entry_array_indices：IndexBufferList 每个条目映射到 ib_data_list 的下标
		  （旧版逆向产物中多个条目可能指向同一文件）；
		- ib_data_full：全部唯一 IB 顺序拼接后的完整索引数据（整体导入用）。
		'''
		if len(submesh_json.IndexBufferList) == 0:
			raise Fatal("SubmeshJson missing IndexBufferList.")

		ib_data_list = []
		filename_array_index_dict = {}
		ib_entry_array_indices = []

		for index_buffer in submesh_json.IndexBufferList:
			if index_buffer.FileName in filename_array_index_dict:
				ib_entry_array_indices.append(filename_array_index_dict[index_buffer.FileName])
				continue

			if not os.path.exists(index_buffer.FilePath):
				raise Fatal("Unable to find matching .ib file for: " + index_buffer.FileName)

			ib_file_size = os.path.getsize(index_buffer.FilePath)
			if ib_file_size == 0:
				raise Fatal("Current Import " + index_buffer.FileName + " file is empty, skip import.")

			index_np_type = FormatUtils.get_nptype_from_format(index_buffer.DXGI_FORMAT)
			index_stride = numpy.dtype(index_np_type).itemsize
			if ib_file_size % index_stride != 0:
				raise Fatal("Index buffer file size is not aligned with DXGI format stride: " + index_buffer.FileName)

			ib_count = int(ib_file_size / index_stride)
			ib_data = numpy.fromfile(index_buffer.FilePath, dtype=index_np_type, count=ib_count)

			filename_array_index_dict[index_buffer.FileName] = len(ib_data_list)
			ib_data_list.append(ib_data)
			ib_entry_array_indices.append(filename_array_index_dict[index_buffer.FileName])

		# IB indices are global (relative to full shared VB).
		# When VertexCount > 0, VB is sliced to [VertexOffset : VertexOffset+VertexCount],
		# so we subtract VertexOffset to make indices local to the sliced VB.
		# When VertexCount == 0, the full VB is loaded without slicing,
		# and the global IB indices are already valid for the full VB.
		vertex_offset = submesh_json.VertexOffset
		vertex_count = submesh_json.VertexCount
		if vertex_offset > 0 and vertex_count > 0:
			ib_data_list = [ib_data.astype(numpy.int64) - vertex_offset for ib_data in ib_data_list]

		if len(ib_data_list) > 1:
			ib_data_full = numpy.concatenate(ib_data_list)
		else:
			ib_data_full = ib_data_list[0]

		ib_count = len(ib_data_full)
		ib_polygon_count = int(ib_count / 3)

		return ib_data_list, ib_entry_array_indices, ib_data_full, ib_count, ib_polygon_count

	@staticmethod
	def parse_category_buffers(submesh_json:SubmeshJson):
		elements = []
		vb_data = {}
		vb_vertex_count = 0
		shapekey_buffers = {}

		vertex_slice_offset = submesh_json.VertexOffset
		vertex_slice_count = submesh_json.VertexCount

		# Buffer types that use standard D3D11ElementList structured layout.
		# - Normal: standard vertex buffer (Position, Texcoord, Color, etc.)
		# - BlendWeight: NTEMI packed BLENDINDICES + BLENDWEIGHTS buffer
		# - TangentFrame: NTEMI packed TANGENT + NORMAL buffer
		STRUCTURED_BUFFER_TYPES = {"Normal", "BlendWeight", "TangentFrame"}

		for category_buffer in submesh_json.CategoryBufferList:
			if category_buffer.Type not in STRUCTURED_BUFFER_TYPES:
				continue

			category_elements, category_vb_data, category_vertex_count = SSMTImportHelper.parse_normal_category_buffer(
				category_buffer, vertex_slice_offset, vertex_slice_count
			)

			if category_vertex_count > 0:
				if vb_vertex_count == 0:
					vb_vertex_count = category_vertex_count
				elif vb_vertex_count != category_vertex_count:
					raise Fatal(
						"Vertex count mismatch between category buffers: "
						+ category_buffer.FileName
						+ " expected " + str(vb_vertex_count)
						+ " actual " + str(category_vertex_count)
					)

			elements.extend(category_elements)
			vb_data.update(category_vb_data)

		SHAPEKEY_TYPES = ("ShapeKeyOffset", "ShapeKeyVertexId", "ShapeKeyVertexOffset", "ShapeKeyScale")

		for category_buffer in submesh_json.CategoryBufferList:
			if category_buffer.Type in STRUCTURED_BUFFER_TYPES:
				continue

			if category_buffer.Type in SHAPEKEY_TYPES:
				if os.path.exists(category_buffer.FilePath) and os.path.getsize(category_buffer.FilePath) > 0:
					shapekey_buffers[category_buffer.Type] = numpy.fromfile(category_buffer.FilePath, dtype=numpy.uint8)
				continue

			category_elements, category_vb_data, category_vertex_count = SSMTImportHelper.parse_special_category_buffer(
				category_buffer=category_buffer,
				vb_vertex_count=vb_vertex_count,
			)

			if category_vertex_count > 0 and category_vertex_count != vb_vertex_count:
				raise Fatal(
					"Vertex count mismatch between category buffers: "
					+ category_buffer.FileName
					+ " expected " + str(vb_vertex_count)
					+ " actual " + str(category_vertex_count)
				)

			elements.extend(category_elements)
			vb_data.update(category_vb_data)

		if vb_vertex_count == 0:
			raise Fatal("No valid normal category buffer was parsed from SubmeshJson.")

		return elements, vb_data, vb_vertex_count, shapekey_buffers

	@staticmethod
	def parse_shapekey_position_buffers(submesh_json:SubmeshJson):
		'''
		解析 ShapeKeyPositionBufferList 中描述的形态键Buffer。

		形态键Buffer的二进制布局与 Position 分类的 CategoryBuffer 完全一致，
		因此直接复用 Position 分类Buffer的 D3D11ElementList 来解析，
		并从中提取 POSITION 元素的绝对坐标数据（与基础 POSITION 同一坐标空间）。
		'''
		shapekey_position_data = {}

		if len(submesh_json.ShapeKeyPositionBufferList) == 0:
			return shapekey_position_data

		# 找到第一个包含 POSITION 语义元素的 CategoryBuffer 作为布局模板。
		position_category_buffer = None
		position_element = None
		for category_buffer in submesh_json.CategoryBufferList:
			for d3d11_element in category_buffer.D3D11ElementList:
				if d3d11_element.SemanticName == "POSITION":
					position_category_buffer = category_buffer
					position_element = d3d11_element
					break
			if position_category_buffer is not None:
				break

		if position_category_buffer is None or position_element is None:
			print("ShapeKeyPosition 导入：未找到 Position 分类Buffer，跳过形态键导入。")
			return shapekey_position_data

		if position_category_buffer.Stride <= 0:
			return shapekey_position_data

		for shapekey_buffer in submesh_json.ShapeKeyPositionBufferList:
			if not shapekey_buffer.FileName:
				continue

			if not os.path.exists(shapekey_buffer.FilePath) or os.path.getsize(shapekey_buffer.FilePath) == 0:
				print("ShapeKeyPosition 导入：形态键Buffer缺失或为空，已跳过: " + shapekey_buffer.FileName)
				continue

			if os.path.getsize(shapekey_buffer.FilePath) % position_category_buffer.Stride != 0:
				print("ShapeKeyPosition 导入：形态键Buffer大小与 Position 步长不对齐，已跳过: " + shapekey_buffer.FileName)
				continue

			shapekey_category_buffer = SubmeshCategoryBuffer(
				FileName=shapekey_buffer.FileName,
				Type="Normal",
				D3D11ElementList=position_category_buffer.D3D11ElementList,
			)
			shapekey_category_buffer.bind_dir_path(submesh_json.DirPath)
			shapekey_category_buffer.calc_stride()

			_, shapekey_vb_data, _ = SSMTImportHelper.parse_normal_category_buffer(
				shapekey_category_buffer,
				vertex_slice_offset=submesh_json.VertexOffset,
				vertex_slice_count=submesh_json.VertexCount,
			)

			position_data = shapekey_vb_data.get(position_element.ElementName)
			if position_data is None:
				continue

			position_data = FormatUtils.apply_format_conversion(position_data, position_element.Format)
			shapekey_position_data[shapekey_buffer.ShapeKeyName] = position_data

		return shapekey_position_data

	@staticmethod
	def parse_normal_category_buffer(category_buffer:SubmeshCategoryBuffer, vertex_slice_offset:int=0, vertex_slice_count:int=-1):
		if not os.path.exists(category_buffer.FilePath):
			raise Fatal("Unable to find matching .buf file for: " + category_buffer.FileName)

		if category_buffer.Stride <= 0:
			if len(category_buffer.D3D11ElementList) == 0:
				return [], {}, 0
			raise Fatal("Category buffer stride is zero: " + category_buffer.FileName)

		file_size = os.path.getsize(category_buffer.FilePath)
		if file_size == 0:
			raise Fatal("Current Import " + category_buffer.FileName + " file is empty, skip import.")
		if file_size % category_buffer.Stride != 0:
			raise Fatal("Category buffer file size is not aligned with stride: " + category_buffer.FileName)

		vertex_count = int(file_size / category_buffer.Stride)
		category_dtype = SSMTImportHelper.create_dtype_from_elements(category_buffer.D3D11ElementList)
		category_buffer_data = numpy.fromfile(category_buffer.FilePath, dtype=category_dtype, count=vertex_count)

		if vertex_slice_count > 0:
			category_buffer_data = category_buffer_data[vertex_slice_offset:vertex_slice_offset + vertex_slice_count]
			vertex_count = vertex_slice_count

		category_vb_data = {}
		for d3d11_element in category_buffer.D3D11ElementList:
			category_vb_data[d3d11_element.ElementName] = category_buffer_data[d3d11_element.ElementName]

		return category_buffer.D3D11ElementList, category_vb_data, vertex_count

	@staticmethod
	def parse_special_category_buffer(category_buffer:SubmeshCategoryBuffer, vb_vertex_count:int):
		if category_buffer.Type == "DynamicBlend":
			return SSMTImportHelper.parse_dynamic_blend_category_buffer(
				category_buffer=category_buffer,
				vb_vertex_count=vb_vertex_count,
			)

		print("预留特殊 Buffer 解析路线, 当前 Type: " + category_buffer.Type + ", FileName: " + category_buffer.FileName)
		return [], {}, 0

	@staticmethod
	def parse_dynamic_blend_category_buffer(category_buffer:SubmeshCategoryBuffer, vb_vertex_count:int):
		if vb_vertex_count <= 0:
			raise Fatal("DynamicBlend parsing requires a valid vb_vertex_count.")

		if not os.path.exists(category_buffer.FilePath):
			raise Fatal("Unable to find matching .buf file for: " + category_buffer.FileName)

		file_size = os.path.getsize(category_buffer.FilePath)
		if file_size == 0:
			raise Fatal("Current Import " + category_buffer.FileName + " file is empty, skip import.")
		if file_size % 4 != 0:
			raise Fatal("DynamicBlend buffer size must be aligned to uint32: " + category_buffer.FileName)

		raw_u32 = numpy.fromfile(category_buffer.FilePath, dtype=numpy.uint32)
		offset_count = vb_vertex_count + 1
		if len(raw_u32) <= offset_count:
			raise Fatal("DynamicBlend buffer is too short to contain offset table and packed entries: " + category_buffer.FileName)

		offsets = raw_u32[:offset_count].astype(numpy.uint64)
		packed_start_index = offset_count
		packed_end_index = len(raw_u32)

		if numpy.any(offsets < packed_start_index):
			raise Fatal("DynamicBlend offset table points before packed entry stream: " + category_buffer.FileName)
		if numpy.any(offsets > packed_end_index):
			raise Fatal("DynamicBlend offset table points past buffer end: " + category_buffer.FileName)
		if numpy.any(offsets[1:] < offsets[:-1]):
			raise Fatal("DynamicBlend offset table is not monotonically increasing: " + category_buffer.FileName)

		max_influence_count = int(numpy.max(offsets[1:] - offsets[:-1])) if vb_vertex_count > 0 else 0
		semantic_group_count = max(1, (max_influence_count + 3) // 4)

		blend_indices_dict = {}
		blend_weights_dict = {}
		for semantic_index in range(semantic_group_count):
			blend_indices_dict[semantic_index] = numpy.zeros((vb_vertex_count, 4), dtype=numpy.uint32)
			blend_weights_dict[semantic_index] = numpy.zeros((vb_vertex_count, 4), dtype=numpy.float32)

		for vertex_index in range(vb_vertex_count):
			start = int(offsets[vertex_index])
			end = int(offsets[vertex_index + 1])
			if end < start:
				raise Fatal("DynamicBlend offset table contains inverted range at vertex: " + str(vertex_index))

			packed_values = raw_u32[start:end]
			for influence_index, packed_value in enumerate(packed_values):
				semantic_index = influence_index // 4
				channel_index = influence_index % 4
				blend_indices_dict[semantic_index][vertex_index, channel_index] = packed_value & 0xFFFF
				blend_weights_dict[semantic_index][vertex_index, channel_index] = ((packed_value >> 16) & 0xFFFF) / 65535.0

		category_elements = []
		category_vb_data = {}
		aligned_byte_offset = 0
		for semantic_index in range(semantic_group_count):
			blendindices_element = D3D11Element(
				SemanticName="BLENDINDICES",
				SemanticIndex=semantic_index,
				Format="R32G32B32A32_UINT",
				ByteWidth=16,
				ExtractSlot="cs-t1",
				ExtractTechnique="compute",
				Category="Blend",
				AlignedByteOffset=aligned_byte_offset,
			)
			aligned_byte_offset += blendindices_element.ByteWidth

			blendweight_element = D3D11Element(
				SemanticName="BLENDWEIGHT",
				SemanticIndex=semantic_index,
				Format="R32G32B32A32_FLOAT",
				ByteWidth=16,
				ExtractSlot="cs-t1",
				ExtractTechnique="compute",
				Category="Blend",
				AlignedByteOffset=aligned_byte_offset,
			)
			aligned_byte_offset += blendweight_element.ByteWidth

			category_elements.append(blendindices_element)
			category_elements.append(blendweight_element)
			category_vb_data[blendindices_element.ElementName] = blend_indices_dict[semantic_index]
			category_vb_data[blendweight_element.ElementName] = blend_weights_dict[semantic_index]

		return category_elements, category_vb_data, vb_vertex_count

	@staticmethod
	def create_dtype_from_elements(d3d11_element_list:list):
		fields = []
		for d3d11_element in d3d11_element_list:
			numpy_type = FormatUtils.get_nptype_from_format(d3d11_element.Format)
			size = int(d3d11_element.ByteWidth / numpy.dtype(numpy_type).itemsize)
			if size == 1:
				fields.append((d3d11_element.ElementName, numpy_type))
			else:
				fields.append((d3d11_element.ElementName, numpy_type, size))
		return numpy.dtype(fields)
