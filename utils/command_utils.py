# The helper class helps us to execute outside programs.
import os
import subprocess

from ..common.global_config import GlobalConfig
from ..common.mimi_global_properties import MIMIGlobalProperties

class CommandUtils:

    @staticmethod
    def OpenGeneratedModFolder():
        '''
        This will be call after generate mod, it will open explorer and shows the result mod files generated.

        Do not open the folder with subprocess.run('explorer',path) - on some users' computers the path is not recognized and it opens the Documents folder instead.
        # Also, opening the folder with subprocess.run('explorer',path) opens a new folder every single time; hundreds of them piled up will freeze the computer.
        So using os.startfile() is the best way
        '''
        if MIMIGlobalProperties.open_mod_folder_after_generate_mod():
            generated_mod_folder_path = GlobalConfig.path_generate_mod_folder()
            os.startfile(generated_mod_folder_path)



