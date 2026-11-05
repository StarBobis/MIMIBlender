"""Validate automation inclusion in a local add-on archive without publishing."""
# Package acceptance:
# - This checker never builds, installs, enables or releases an add-on.
# - Required automation files are explicit runtime dependencies, not future tools.
# - Compile shipped Python source without importing bpy or running any module.
# - Reject duplicate entries, path traversal and files outside the wrapper.
# - A passing package is not a Blender execution or game-validation result.
# - Do not compare an old HEAD package against uncommitted working-tree files.
# - Real git archive checks run only after the code stage is committed.
# - Test archives and reports remain under repository tmp for review.
# - No archive entry is extracted into a user's scene or install directory.
# - Native release.ps1 also guards the critical automation entry points.
import argparse
import hashlib
import json
from pathlib import PurePosixPath
import zipfile


REQUIRED = tuple("automation/" + name + ".py" for name in (
    "__init__", "contract", "registry", "inspection", "properties", "blueprints", "presentation",
    "paths", "context", "revisions", "workspaces", "jobs", "binding", "exports", "audits",
    "preservation", "collaboration", "meshes", "reverse", "materials", "mcp_bridge", "state", "ui"))


def check_package(path, prefix):
    """Read ZIP bytes and require every implemented automation runtime module."""
    if not prefix or "/" in prefix or "\\" in prefix or prefix in {".", ".."}:
        raise ValueError("Package prefix must be one safe wrapper folder")
    with zipfile.ZipFile(path) as archive:  # Read-only inspection does not extract or overwrite user files.
        names = archive.namelist()  # Keep the actual central-directory entries, including potential duplicates.
        if len(names) != len(set(names)):
            raise ValueError("Archive contains duplicate entries")
        for name in names:
            parts = PurePosixPath(name).parts  # Normalize lexical ZIP components without filesystem access.
            if not name.startswith(prefix + "/") or ".." in parts or "\\" in name:
                raise ValueError("Archive entry escapes the required wrapper: " + name)
        missing = [name for name in ("__init__.py",) + REQUIRED if prefix + "/" + name not in names]
        if missing:
            raise ValueError("Archive misses required runtime files: " + ", ".join(missing))
        files = []  # Hash and compile only the shipped automation code, never repository substitutes.
        for name in REQUIRED:
            raw = archive.read(prefix + "/" + name)  # Exact member identity is the acceptance target.
            compile(raw, name, "exec")  # Syntax verification never evaluates imports or class registration.
            files.append({"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    return {"ok": True, "prefix": prefix, "automation_files": files, "in_game_verified": False}


def main():
    """Print a finite English JSON report for a preexisting local archive."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive")  # Archive creation is a separate explicit git command.
    parser.add_argument("--prefix", required=True)
    options = parser.parse_args()
    print(json.dumps(check_package(options.archive, options.prefix), indent=2, allow_nan=False))


# Direct execution neither bumps a version nor contacts GitHub.
# A missing runtime module must stop acceptance before any release upload.
if __name__ == "__main__":
    main()
