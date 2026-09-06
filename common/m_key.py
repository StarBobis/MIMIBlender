
from dataclasses import dataclass, field


@dataclass
class M_Key:
    '''
    key_name: name of the declared key, normally $swapkey + a number in declaration order
    key_value: concrete VK value of the key
    comment: remarks, written into the config table as a comment
    '''

    key_name: str = ""
    key_value: str = ""
    value_list: list[int] = field(default_factory=list)
    
    initialize_value: int = 0
    initialize_vk_str: str = ""  # Virtual-key combination following 3Dmigoto's parsing format

    # Used for passing data through chain_key_list
    tmp_value: int = 0
    
    # Remarks
    comment: str = ""

    def __str__(self):
        return (f"M_Key(key_name='{self.key_name}', key_value='{self.key_value}', "
                f"value_list={self.value_list}, initialize_value={self.initialize_value}, "
                f"tmp_value={self.tmp_value}, comment='{self.comment}')")