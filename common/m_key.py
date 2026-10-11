
from dataclasses import dataclass, field
import math
import re


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
    # - "time_shapekey": recomputed every frame like "time", but the variable
    #   holds a shape key weight (0..1) taken from weight_list (Time Shape
    #   Key node); value_list stays the frame indices.
    key_type: str = "key"

    # Frames shown per second when key_type != "key". The INI writer turns
    # this into the per-frame step length step = 1.0 / fps (in seconds).
    fps: float = 12.0

    # Per-frame weight values used when key_type == "time_shapekey":
    # weight_list[i] is the weight written while value_list[i] is selected.
    weight_list: list = field(default_factory=list)

    initialize_value: int = 0
    initialize_vk_str: str = ""  # Virtual-key combination following 3Dmigoto's parsing format

    # Optional animation control, separate from shape-weight cycle hotkeys.
    # Empty bindings preserve the existing injection-relative autoplay path.
    # Runtime toggle state resets to start_enabled when the INI is reloaded.
    toggle_key: str = ""
    start_enabled: bool = True

    # Playback driver of a time timeline:
    # - "loop": wall-clock autoplay, repeating the timeline forever (the
    #   optional toggle key switches playback on/off, off selects frame 0).
    # - "trigger": the key becomes a one-shot trigger. Every press replays
    #   the timeline once from frame zero; past the timeline period the
    #   variable returns to zero and stays there until the next press.
    #   Implemented with type=activate + run (3Dmigoto Override.cpp:
    #   KeyOverride::DownEvent -> Override::Activate -> RunCommandList runs
    #   the activate command list on EVERY key-down, no toggle state).
    playback_mode: str = "loop"

    # Used for passing data through chain_key_list
    tmp_value: int = 0

    # Remarks
    comment: str = ""

    def configure_animation_toggle(self, node):
        """Read optional node properties without breaking older blend files.

        A blank binding always means autoplay. Reject INI delimiters before
        normalizing whitespace, so a pasted multiline value cannot add commands.
        Shared-alias comparison uses this normalized binding and default state.
        """
        # Older blend files have no playback mode property; they are loops.
        mode = str(getattr(node, "playback_mode", "LOOP") or "LOOP").strip().lower()
        if mode not in ("loop", "trigger"):
            raise ValueError("Playback mode must be Loop or Key Trigger")
        binding = str(getattr(node, "toggle_key", "") or "")
        if any(char in binding for char in "\r\n;=[]"):
            raise ValueError("Animation toggle key must be a single key binding, such as F6 or CTRL F6")
        self.toggle_key = " ".join(binding.upper().split())
        self.playback_mode = mode
        # A one-shot trigger without a key could never start playing.
        if self.playback_mode == "trigger" and not self.toggle_key:
            raise ValueError("Key Trigger playback requires a trigger key, such as F6 or CTRL F6")
        self.start_enabled = bool(getattr(node, "start_enabled", True)) if self.toggle_key else True
        # Shape weights have a real zero/off state, unlike draw-frame indices.
        # Initialize it before the first Present so disabled exports start at
        # Basis. A one-shot trigger starts disarmed as well, so its pre-Press
        # weight must be zero too.
        if self.key_type == "time_shapekey" and (not self.start_enabled or self.playback_mode == "trigger"):
            self.initialize_value = 0

    def animation_control_name(self):
        # Exporter-reserved names avoid collisions with user timeline aliases.
        # Shape and mesh timelines already have distinct variable identifiers.
        return "$mimi_anim_" + self.key_name.lstrip("$")

    def timeline_expression(self, clock="time"):
        """Validate a timeline and return a bounded 3Dmigoto expression.

        CommandList operators evaluate float32, not Python doubles. Rounding
        immediately below a cycle boundary can produce count after division;
        the final modulo prevents an unhandled frame and disappearing draws.
        The source clock still has float32 uptime precision, which no modulo
        can recover. This keeps the existing injection-relative phase.
        """
        count = len(self.value_list)
        if count < 1 or count > 10000 or self.value_list != list(range(count)):
            raise ValueError("Animation frames must be contiguous indices with a count from 1 to 10000")
        if not math.isfinite(self.fps) or not 1e-6 <= self.fps <= 1e6:
            raise ValueError("Animation FPS must be finite and between 0.000001 and 1000000")
        # Match the engine's identifier grammar, including case normalization.
        # Reject aliases of generated shape weights and internal state earlier
        # in graph parsing; this check also protects standalone writer callers.
        if re.fullmatch(r"\$[a-z_][a-z0-9_]*", self.key_name) is None:
            raise ValueError("Invalid 3Dmigoto animation variable: " + self.key_name)
        if self.key_type == "time_shapekey":
            if len(self.weight_list) != count or not all(math.isfinite(w) and abs(w) <= 3.4e38 for w in self.weight_list):
                raise ValueError("ShapeKey Real-time Based Dynamic Mod needs one finite float32 weight per frame")
        step = repr(1.0 / self.fps)
        # clock is generated internally: either the legacy engine time or
        # elapsed time since the optional toggle was last enabled.
        return "((" + clock + " % (" + step + " * " + str(count) + ")) // " + step + ") % " + str(count)

    def __str__(self):
        return (f"M_Key(key_name='{self.key_name}', key_value='{self.key_value}', "
                f"key_type='{self.key_type}', fps={self.fps}, "
                f"value_list={self.value_list}, weight_list={self.weight_list}, "
                f"initialize_value={self.initialize_value}, "
                f"tmp_value={self.tmp_value}, comment='{self.comment}')")