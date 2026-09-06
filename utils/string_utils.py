import re

class StringUtils:

    def get_ib_hash_from_filename(filename:str) -> str:
        # Regex: match the content after '-ib=' up to the next '-'
        match = re.search(r'-ib=([^-]+)', filename)
        if match:
            return match.group(1)  # Return the first capture group, i.e. the content after ib=
        return None  # Return None when there is no match