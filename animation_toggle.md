# Animation Playback Toggles

All three animation nodes now support an optional keyboard switch:

- Time Switch (DrawIndexed)
- Time Position Switch (Position buffer replacement)
- Time Shape Key (shared, Naraka and WWMI exporters)

## Configuration

Each node has two new controls:

1. **Animation Toggle Key**: enter a 3Dmigoto key binding, for example `F6`, `VK_F6`, or `CTRL F6`.
2. **Start Enabled**: choose whether playback starts enabled when the mod is loaded or reloaded.

Leave the key empty to preserve the original automatic playback behavior. With an empty key, Start Enabled is disabled in the UI and does not affect export. Existing blend files therefore continue to work without changes.

Export the mod again after changing either setting, then reload it in the game. This feature changes INI generation and does not require a new mesh format or shader version.

## What switching does

| Animation mode | Enabled | Disabled |
| --- | --- | --- |
| DrawIndexed | Play the frame branches | Select frame 0; do not hide the entire mod |
| Position buffers | Apply the selected Position frame | Restore the separately connected base Position buffer |
| Shape key | Play the configured weight samples | Set only this timeline's shape weight to zero |

Each disabled-to-enabled transition restarts at frame 0. This is an on/off switch, not pause/resume: time spent disabled is not included in resumed playback.

For DrawIndexed, frame 0 should contain the desired resting mesh. If that socket is intentionally empty, the disabled animation draws nothing through this node. For Position switching, the base object must still be connected normally. Shape-key toggles leave other shape weights and Position timelines untouched.

A one-frame draw/Position node or a single manually entered shape weight can also have a switch. A single weight without a switch retains the previous incomplete-node behavior and is not exported as a time animation.

## Shared clocks and shared keys

Time Switch and Time Position Switch nodes with the same time alias share one exported clock and one toggle. They must use the same normalized key binding and Start Enabled setting, in addition to the existing matching-FPS requirement. Conflicts raise an export error instead of silently taking whichever node was visited first.

For example, two submeshes with alias `walk`, key `F6`, and Start Enabled checked are controlled by a single generated key section. Configure all nodes sharing that alias consistently; leaving the key empty on just one of them is a conflict.

Different timelines may deliberately use the same physical key, including a shape timeline. Each has its own switch, and that key toggles all of them. Use the same initial state if they should turn on/off together. Avoid assigning that key to unrelated mod controls unless simultaneous activation is intended.

The toggle is not gated by model visibility, so an animation can always be turned back on. Its state is not persisted: loading/reloading resets it to Start Enabled. Untoggled timelines retain their existing injection-clock-relative phase; toggled timelines use elapsed time since activation.

## INI implementation

The exporter generates a standard key cycle with `type = cycle`, `smart = true`, and values `0,1`. Smart cycling synchronizes with the current value, so the first press works for either initial state.

Each controlled timeline has reserved `$mimi_anim_*` globals for enabled state, previous enabled state, and start time. A `post run = CommandListMimiAnimation_*` command:

1. Runs after input events.
2. Captures the new start time on a rising enable edge.
3. Updates the frame or weight from elapsed time, or resets it to zero when off.

Position selection additionally checks the enabled variable, since frame zero and the separate base buffer are not necessarily identical. Its existing inactive-state cache restores the base once rather than copying it every rendered frame.

The ordering is input events, timeline update, Position selection/copy, then shared shape compute. Naraka and WWMI consume the updated weights at their existing draw/skinning hooks. The existing non-persistent frame variables, float32 bounds checks, resource validation and preset support limits remain unchanged.

## Verification

- `tools/test_animation_toggle_ini.py`: executes the generated test subset in pre-Present/input/post-Present order; checks both startup states, first press, disable, restart, Position cache behavior, shape weights and compute ordering.
- `tools/test_dynamic_animation_blender.py`: checks actual node-to-key parsing, shared alias deduplication/conflicts, all three RNA properties, blend-library save/load, and shared/Naraka/WWMI integration.
- Existing DrawIndexed and Position/shape INI tests verify blank-key backward compatibility.
- Translation coverage checks include the new English and Simplified Chinese UI labels and help text.

These checks are not a running-game injection test. Validate the chosen key bindings in the target game's 3Dmigoto environment and check for collisions with other enabled mods.
