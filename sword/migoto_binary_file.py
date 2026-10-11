from ..utils.format_utils import FormatUtils
from ..utils.format_utils import Fatal
from ..utils.log_utils import LOG

from ..common.d3d11_gametype import D3D11Element

import os
import numpy

from .fmt_file import FMTFile


class MigotoBinaryFile:

    '''
    3Dmigoto model file

    No better design exists yet; for now, keep the old ib vb fmt design
    
    prefix is the file name prefix, e.g. with Body.ib, Body.vb and Body.fmt, Body is the prefix
    location_folder_path is the folder path storing these files, e.g. the extracted folder of the corresponding data type in the current workspace

    '''
    def __init__(self, fmt_path:str, mesh_name:str = ""):
        self.fmt_file = FMTFile(fmt_path)
        print("fmt_path: " + fmt_path)
        location_folder_path = os.path.dirname(fmt_path)
        print("location_folder_path: " + location_folder_path)

        if self.fmt_file.prefix == "":
            self.fmt_file.prefix = os.path.basename(fmt_path).split(".fmt")[0]

        if mesh_name == "":
            self.mesh_name = self.fmt_file.prefix
        else:
            self.mesh_name = mesh_name
        

        print("prefix: " + self.fmt_file.prefix)
        self.init_from_prefix(self.fmt_file.prefix, location_folder_path)

    def init_from_prefix(self,prefix:str, location_folder_path:str):

        self.fmt_name = prefix + ".fmt"
        self.vb_name = prefix + ".vb"
        self.ib_name = prefix + ".ib"

        self.location_folder_path = location_folder_path

        self.vb_name = self.resolve_vb_name(prefix, location_folder_path)
        self.vb_bin_path = os.path.join(location_folder_path, self.vb_name)
        self.ib_bin_path = os.path.join(location_folder_path, self.ib_name)
        self.fmt_path = os.path.join(location_folder_path, self.fmt_name)

        self.file_sanity_check()

        self.vb_file_size = os.path.getsize(self.vb_bin_path)
        self.ib_file_size = os.path.getsize(self.ib_bin_path)

        self.init_data()

    def init_data(self):
        ib_stride = FormatUtils.format_size(self.fmt_file.format)

        self.ib_count = int(self.ib_file_size / ib_stride)
        self.ib_polygon_count = int(self.ib_count / 3)
        self.ib_data = numpy.fromfile(self.ib_bin_path, dtype=FormatUtils.get_nptype_from_format(self.fmt_file.format), count=self.ib_count)
        
        # Read the fmt file and parse out the dtype to use later
        fmt_dtype = self.fmt_file.get_dtype()
        vb_stride = fmt_dtype.itemsize

        self.vb_vertex_count = int(self.vb_file_size / vb_stride)
        self.vb_data = numpy.fromfile(self.vb_bin_path, dtype=fmt_dtype, count=self.vb_vertex_count)

    def resolve_vb_name(self, prefix:str, location_folder_path:str) -> str:
        exact_vb_name = prefix + ".vb"
        exact_vb_path = os.path.join(location_folder_path, exact_vb_name)
        if os.path.exists(exact_vb_path):
            return exact_vb_name

        prefix_lower = (prefix + ".vb").lower()
        candidate_names = []
        for entry_name in os.listdir(location_folder_path):
            entry_path = os.path.join(location_folder_path, entry_name)
            if not os.path.isfile(entry_path):
                continue

            if entry_name.lower().startswith(prefix_lower):
                candidate_names.append(entry_name)

        if not candidate_names:
            return exact_vb_name

        candidate_names.sort(key=lambda name: (len(name), name.lower()))
        return candidate_names[0]

    
    def file_sanity_check(self):
        '''
        Check that the corresponding files exist, raising an exception if any is missing
        All three files must exist; none may be missing
        '''
        if not os.path.exists(self.vb_bin_path):
            raise Fatal("Unable to find matching .vb file for : " + self.mesh_name)
        if not os.path.exists(self.ib_bin_path):
            raise Fatal("Unable to find matching .ib file for : " + self.mesh_name)
        # if not os.path.exists(self.fmt_path):
        #     raise Fatal("Unable to find matching .fmt file for : " + self.mesh_name)

    def file_size_check(self) -> bool:
        '''
        Check whether the .ib and .vb files are empty; if so, show a warning message but do not raise an error.
        '''
        # If the vb and ib files are empty, skip the import
        # We cannot raise an exception directly because some .ib files are empty placeholder files
        if self.vb_file_size == 0:
            LOG.warning("Current Import " + self.vb_name +" file is empty, skip import.")
            return False
        
        if self.ib_file_size == 0:
            LOG.warning("Current Import " + self.ib_name + " file is empty, skip import.")
            return False
        
        return True