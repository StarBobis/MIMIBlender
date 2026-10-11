"""Run the blueprint and related export regressions in isolated Blender processes.

Usage: python tools/run_blueprint_checks.py /path/to/blender
Each test uses factory startup so it cannot change an open user scene.
"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
# Keep explicit coverage rather than running tests that need private game data.
# Every listed script is a self-contained repository regression fixture.
TESTS = (
    'test_blueprint_blender.py',
    'test_dynamic_mod_titles.py',
    'test_dynamic_animation_blender.py',
    'test_time_switch_ini.py',
    'test_time_position_ini.py',
    'test_animation_toggle_ini.py',
    'test_texture_bind_ini.py',
    'test_hash_texture_bind_ini.py',
    'test_material_texture_apply.py',
    'test_wwmi_components_blender.py',
    'test_wwmi_multi_drawib_ini.py',
    'test_naraka_shapekeys.py',
    'test_yysls_shapekeys.py',
)


def main():
    # Capture logs to files instead of mixing Blender output across tests.
    # Failures remain visible and the runner exits nonzero if any test fails.
    blender = sys.argv[1]
    logs = ROOT / 'tmp' / 'blueprint_checks'
    logs.mkdir(parents=True, exist_ok=True)
    failed = []
    for filename in TESTS:
        # Blender's --python does not add the script directory to sys.path.
        # Several legacy fixtures import support modules next to themselves.
        setup = 'import sys; sys.path.insert(0, ' + repr(str(ROOT / 'tools')) + ')'
        # unittest.main must not interpret Blender's own command-line options.
        setup += '; sys.argv = [' + repr(filename) + ']'
        command = [blender, '-b', '--factory-startup', '--python-exit-code', '1', '--python-expr', setup, '--python', str(ROOT / 'tools' / filename)]
        with (logs / (filename + '.log')).open('w', encoding='utf-8') as output:
            result = subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, timeout=180)
        # Blender callbacks can print exceptions without setting an exit code.
        # Treat those traces as failures too, not a false green test result.
        text = (logs / (filename + '.log')).read_text(encoding='utf-8')
        success = result.returncode == 0 and 'Traceback (most recent call last)' not in text
        print(('PASS ' if success else 'FAIL ') + filename, flush=True)
        if not success:
            failed.append(filename)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} suites passed', flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
