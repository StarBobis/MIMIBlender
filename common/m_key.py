
from dataclasses import dataclass, field


@dataclass
class M_Key:
    '''
    key_name 声明的key名称，一般按照声明顺序为$swapkey + 数字
    key_value 具体的按键VK值
    comment 备注信息，会以注释形式生成到配置表中
    '''

    key_name: str = ""
    key_value: str = ""
    value_list: list[int] = field(default_factory=list)
    
    initialize_value: int = 0
    initialize_vk_str: str = ""  # 虚拟按键组合，遵循3Dmigoto的解析格式

    # 用于chain_key_list中传递使用
    tmp_value: int = 0
    
    # 备注信息
    comment: str = ""

    def __str__(self):
        return (f"M_Key(key_name='{self.key_name}', key_value='{self.key_value}', "
                f"value_list={self.value_list}, initialize_value={self.initialize_value}, "
                f"tmp_value={self.tmp_value}, comment='{self.comment}')")