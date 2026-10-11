from ..utils.format_utils import FormatUtils
from ..utils.format_utils import Fatal
from ..utils.log_utils import LOG

from ..common.d3d11_gametype import D3D11Element

import os
import numpy


class FMTFile:
    def __init__(self, fmt_file_path:str):
        self.stride = 0
        self.topology = ""
        self.format = ""
        self.gametypename = ""
        self.prefix = ""
        self.logic_name = ""
        self.elements:list[D3D11Element] = []

        with open(fmt_file_path, 'r') as file:
            lines = file.readlines()

        element_info = {}
        for line in lines:
            parts = line.strip().split(":")
            if len(parts) < 2:
                continue  # Skip lines with an invalid format

            key, value = parts[0].strip(), ":".join(parts[1:]).strip()
            if key == "stride" or key.endswith(" stride"):
                self.stride = int(value)
            elif key == "topology":
                self.topology = value
            elif key == "format":
                self.format = value
            elif key == "gametypename":
                self.gametypename = value
            elif key == "prefix":
                self.prefix = value
            elif key == "logic_name":
                self.logic_name = value


            elif key.startswith("element"):
                # Handle an element block
                if "SemanticName" in element_info:
                    aligned_byte_offset = int(element_info["AlignedByteOffset"]) if "AlignedByteOffset" in element_info else -1
                    append_d3delement = D3D11Element(
                        SemanticName=element_info["SemanticName"], SemanticIndex=int(element_info["SemanticIndex"]),
                        Format= element_info["Format"],AlignedByteOffset= aligned_byte_offset,
                        ByteWidth=0,
                        ExtractSlot="0",ExtractTechnique="",Category="")
                    
                    if "ByteWidth" in element_info:
                        # print("ByteWidth present: " + element_info["ByteWidth"])
                        append_d3delement.ByteWidth = int(element_info["ByteWidth"])
                    else:
                        append_d3delement.ByteWidth = FormatUtils.format_size(append_d3delement.Format)
                    
                    # If element info is already present, append it to the list first
                    self.elements.append(append_d3delement)
                    element_info.clear()  # Clear the current element info

                # Add the new element attribute to the element_info dict
                element_info[key.split()[0]] = value
            elif key in ["SemanticName", "SemanticIndex", "Format","ByteWidth", "InputSlot", "AlignedByteOffset", "InputSlotClass", "InstanceDataStepRate"]:
                element_info[key] = value

        # Append the last element
        if "SemanticName" in element_info:
            aligned_byte_offset = int(element_info["AlignedByteOffset"]) if "AlignedByteOffset" in element_info else -1
            append_d3delement = D3D11Element(
                SemanticName=element_info["SemanticName"], SemanticIndex=int(element_info["SemanticIndex"]),
                Format= element_info["Format"],AlignedByteOffset= aligned_byte_offset,
                ByteWidth=0,
                ExtractSlot="0",ExtractTechnique="",Category=""
            )

            if "ByteWidth" in element_info:
                # print("ByteWidth present: " + element_info["ByteWidth"])
                append_d3delement.ByteWidth = int(element_info["ByteWidth"])
            else:
                append_d3delement.ByteWidth = FormatUtils.format_size(append_d3delement.Format)

            self.elements.append(append_d3delement)

    def __repr__(self):
        return (f"FMTFile(stride={self.stride}, topology='{self.topology}', format='{self.format}', "
                f"gametypename='{self.gametypename}', prefix='{self.prefix}', elements={self.elements})")
    
    def get_dtype(self):
        fields = []
        names = []
        formats = []
        offsets = []
        use_aligned_offsets = True
        for elemnt in self.elements:
            # The numpy type is determined by Format, so even WWMI's special R8_UINT yields the correct numpy.uint8
            numpy_type = FormatUtils.get_nptype_from_format(elemnt.Format)
            
            # Here we use ByteWidth / numpy_type.itemsize to get the total number of dimensions, i.e. the number of columns
            # XXX Note: computing a correct Size requires numpy_type to truly match the real byte count and ByteWidth to be correct - the data type must be exactly right.
            size = int( elemnt.ByteWidth / numpy.dtype(numpy_type).itemsize)

            # print("element: "+ elemnt.ElementName)
            # print(numpy_type)
            # print(size)
            if size == 1:
                field_format = numpy_type
            else:
                field_format = (numpy_type, size)

            fields.append((elemnt.ElementName, field_format))
            names.append(elemnt.ElementName)
            formats.append(field_format)

            if int(elemnt.AlignedByteOffset) < 0:
                use_aligned_offsets = False
            else:
                offsets.append(int(elemnt.AlignedByteOffset))

        if not use_aligned_offsets:
            return numpy.dtype(fields)

        itemsize = self.stride
        if itemsize <= 0:
            itemsize = max(
                int(elemnt.AlignedByteOffset) + int(elemnt.ByteWidth)
                for elemnt in self.elements
            )

        dtype = numpy.dtype({
            'names': names,
            'formats': formats,
            'offsets': offsets,
            'itemsize': itemsize,
        })
        return dtype
    