import json

class JsonUtils:


    @staticmethod
    def SaveToFile(filepath:str,json_dict:dict):
        # Convert the dictionary into a JSON-formatted string
        json_string = json.dumps(json_dict, ensure_ascii=False, indent=4)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(json_string)
            
    @staticmethod
    def LoadFromFile(filepath: str) -> dict:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                # Read the file content and parse it into a dictionary
                json_dict = json.load(f)
            return json_dict
        except FileNotFoundError:
            print(f"Error: The file at {filepath} was not found.")
            return {}
        except json.JSONDecodeError:
            print(f"Error: The file at {filepath} is not a valid JSON file.")
            return {}