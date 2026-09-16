
from dataclasses import dataclass, field


@dataclass
class M_Key:
    '''
    key_name: name of the declared key, normally $swapkey + a number in declaration order
    key_value: concrete VK value of the key
    key_type: "key" for hotkey-driven variables, "time" for wall-clock-driven ones
    comment: remarks, written into the config table as a comment
    '''

    key_name: str = ""
    key_value: str = ""
    value_list: list[int] = field(default_factory=list)

    # Driver kind of this variable:
    # - "key": cycled by a [Key] section hotkey (classic Switch Key node).
    # - "time": recomputed every frame from 3Dmigoto's built-in "time" operand
    #   (Time Switch node). 3Dmigoto evaluates "time" as wall-clock seconds
    #   since injection: (GetTickCount() - ticks_at_launch) / 1000.0f, see
    #   CommandList.cpp ParamOverrideType::TIME, so playback speed never
    #   depends on the game's frame rate.
    key_type: str = "key"

    # Frames shown per second when key_type == "time". The INI writer turns
    # this into the per-frame step length step = 1.0 / fps (in seconds).
    fps: float = 12.0

    initialize_value: int = 0
    initialize_vk_str: str = ""  # Virtual-key combination following 3Dmigoto's parsing format

    # Used for passing data through chain_key_list
    tmp_value: int = 0

    # Remarks
    comment: str = ""

    def __str__(self):
        return (f"M_Key(key_name='{self.key_name}', key_value='{self.key_value}', "
                f"key_type='{self.key_type}', fps={self.fps}, "
                f"value_list={self.value_list}, initialize_value={self.initialize_value}, "
                f"tmp_value={self.tmp_value}, comment='{self.comment}')")