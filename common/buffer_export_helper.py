import os
import struct
import numpy

from .global_config import GlobalConfig


class BufferExportHelper:
    '''
    Utility class
    Responsible for writing ObjBufferModel data into files.

    Only used when generating a Mod.
    Flat Mod folder layout - everything is written next to the INI:

    Folder: Mod_<workspace name>
    - File:   *.buf                          binary buffer files (IB and VB/CategoryBuffer files)
    - File:   *.dds / *.png                  texture files
    - File:   <workspace name>.ini           all ini content must be written together in one file; splitting it across
      multiple ini files linked by namespace can cause a momentary texture
      binding delay when the Mod is toggled on or off
    '''

    @staticmethod
    def write_category_buffer_files(category_buffer_dict:dict, draw_ib:str):
        # Write directly by iterating OrderedCategoryNameList, preserving order and filtering logic
        for category_name,category_buf in category_buffer_dict.items():
            buf_path = GlobalConfig.path_generatemod_buffer_folder() + draw_ib + "-" + category_name + ".buf"
            with open(buf_path, 'wb') as ibf:
                category_buf.tofile(ibf)

    @staticmethod
    def write_numpy_buffer(buffer, filename: str):
        buf_path = os.path.join(GlobalConfig.path_generatemod_buffer_folder(), filename)
        with open(buf_path, 'wb') as buf_file:
            buffer.tofile(buf_file)

    @staticmethod
    def write_buf_ib_r32_uint(index_list:list[int],buf_file_name:str):
        ib_path = os.path.join(GlobalConfig.path_generatemod_buffer_folder(), buf_file_name)
        packed_data = struct.pack(f'<{len(index_list)}I', *index_list)
        with open(ib_path, 'wb') as ibf:
            ibf.write(packed_data) 

    @staticmethod
    def write_buf_shapekey_offsets(shapekey_offsets,filename:str):
        out_path = os.path.join(GlobalConfig.path_generatemod_buffer_folder(), filename)
        numpy.asarray(shapekey_offsets, dtype=numpy.uint32).tofile(out_path)

    @staticmethod
    def write_buf_shapekey_vertex_ids(shapekey_vertex_ids,filename:str):
        out_path = os.path.join(GlobalConfig.path_generatemod_buffer_folder(), filename)
        numpy.asarray(shapekey_vertex_ids, dtype=numpy.uint32).tofile(out_path)
                
    @staticmethod
    def write_buf_shapekey_vertex_offsets(shapekey_vertex_offsets,filename:str):
        # Convert the list to a numpy array
        float_array = numpy.array(shapekey_vertex_offsets, dtype=numpy.float32)
        # Change the data type to float16
        float_array = float_array.astype(numpy.float16)
        with open(GlobalConfig.path_generatemod_buffer_folder() + filename, 'wb') as file:
            float_array.tofile(file)

    @staticmethod
    def write_buf_blendindices_uint16(blendindices, filename: str):
        """
        Write BLENDINDICES array to disk as uint16 values.

        `blendindices` may be a numpy array of shape (loops,) or (loops, N)
        or a Python sequence. This function will convert/cast it to
        uint16 and write the raw bytes to the buffer folder.
        """
        arr = numpy.asarray(blendindices)

        # If structured dtype, try to view first field
        if arr.dtype.names:
            # pick first named field
            arr = arr[arr.dtype.names[0]]

        # Ensure numeric integer shape: flatten rows if 2D
        if arr.ndim > 1:
            arr_to_write = arr.reshape(-1)
        else:
            arr_to_write = arr

        # Cast to uint16 (safe truncation assumed per format expectations)
        arr_uint16 = arr_to_write.astype(numpy.uint16)

        out_path = os.path.join(GlobalConfig.path_generatemod_buffer_folder(), filename)
        # Ensure directory exists
        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        with open(out_path, 'wb') as f:
            arr_uint16.tofile(f)
