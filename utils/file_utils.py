import os

class FileUtils:

    def list_files(directory)->list[str]:
        """ List all the files in the directory, excluding subdirectories """
        file_list = []

        for entry in os.listdir(directory):
            full_path = os.path.join(directory, entry)
            if os.path.isfile(full_path):
                file_list.append(entry)
        return file_list

