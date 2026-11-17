"""Resolve host capture settings and blueprint-owned mesh identities.

Automatic export refreshes evidence instead of trusting cached shader hashes.
Explicit manual directory and shader choices remain authoritative.
"""
from pathlib import Path
import json
import re


def read_json(path):
    """Treat absent host settings as unavailable, never another game's data."""
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError,ValueError):
        return {}


def latest_host_capture(config_root, workspace, lod=''):
    """Use the configured install directory, with workspace path fallback.

    MMT can keep captures in a LOD subdirectory or an external parent.
    Pick the latest dated capture within that selected scope, not a random
    folder from a different game or LOD. Missing paths produce useful errors.
    """
    config_root,workspace=Path(config_root),Path(workspace)
    settings=read_json(config_root/'settings.json')
    game=settings.get('CurrentGameName','')
    if game!='Naraka':
        raise ValueError('Select Naraka in MMT before reading its capture folder')
    install=read_json(config_root/'Games'/game/'Config.json').get('installDir','')
    if not install:
        raise ValueError('MMT has no configured game install directory')
    root=Path(install)
    config=read_json(workspace/'Config/FrameAnalysisPath.json') or read_json(workspace/'FrameAnalysisPathConfig.json')
    recorded=str(config.get('frameAnalysisFolderPath','') or '')
    # A manually configured external capture location takes priority over
    # the install root. The button still finds the latest capture there.
    if recorded:
        path=Path(recorded)
        if path.is_dir() and not path.is_relative_to(root):
            root=path.parent if path.name.startswith('FrameAnalysis-') else path
    if lod and (root/lod).is_dir():
        root=root/lod
    captures=sorted(p for p in root.glob('FrameAnalysis-*') if p.is_dir() and (p/'log.txt').is_file())
    if not captures:
        raise ValueError('No complete FrameAnalysis capture was found in the configured game folder')
    return str(captures[-1])


def region_submesh(tree,entry):
    """Prefer the blueprint's Submesh assignment over a renamed object."""
    matches=set()
    for node in getattr(tree,'nodes',[]):
        for item in getattr(node,'object_items',[]):
            if getattr(item,'object_name','')==entry.object_name:
                name=getattr(item,'submesh_name','')
                if name:
                    matches.add(name)
    if len(matches)>1:
        raise ValueError('The selected object belongs to several Submeshes; choose an unambiguous region object')
    return next(iter(matches)) if matches else entry.object_name


def configure_node(node,drawib=None,force_host=False):
    """Resolve the current selection once per explicit action or export.

    No filesystem scans run from draw callbacks. Manual shader mode keeps
    the exact user-entered pair; automatic mode replaces stale hashes.
    """
    import bpy
    from ..global_config import GlobalConfig
    from .capture import find_picker_shaders
    entries=[e for e in node.regions if e.enabled and e.object_name]
    if not entries:
        raise ValueError('Choose an imported mesh object first')
    entry=node.regions[min(node.region_index,len(node.regions)-1)]
    if not entry.enabled or not entry.object_name:
        entry=entries[0]
    submesh=region_submesh(node.id_data,entry)
    if drawib:
        for candidate in entries:
            name=region_submesh(node.id_data,candidate)
            if re.search(r'(?:^|\.)'+re.escape(drawib)+r'-',name,re.I):
                submesh=name
                break
    match=re.search(r'(?:^|\.)([0-9a-fA-F]{8})-',submesh)
    if drawib is None:
        if not match:
            raise ValueError('Choose an imported mesh object first')
        drawib=match[1]
    lod=re.match(r'^(LOD\d+)\.',submesh,re.I)
    automatic=getattr(node,'auto_capture',True) or force_host
    folder=latest_host_capture(GlobalConfig.path_project_bunny_global_configs_folder(),
                               GlobalConfig.path_workspace_folder(),lod[1] if lod else '') if automatic else bpy.path.abspath(node.capture_directory)
    manual=getattr(node,'manual_picker',False)
    if manual:
        vs,ps=node.pick_vs,node.pick_ps
    else:
        from ...workspace.mmt_workspace import MMTWorkSpace
        metadata=read_json(MMTWorkSpace.check_and_get_submesh_json_path(submesh))
        source_ranges=set()
        for row in metadata.get('IndexBufferList',[]):
            source=re.search(r'[0-9a-fA-F]{8}-(\d+)-(\d+)\.ib$',row.get('FileName',''))
            if source:
                source_ranges.add((int(source[1]),int(source[2])))
        count,first=next(iter(source_ranges)) if len(source_ranges)==1 else (None,None)
        vs,ps=find_picker_shaders(folder,drawib,first_index=first,index_count=count)
    # Commit only after discovery succeeds so failed refreshes do not erase
    # the user's previous configuration or explicit manual shader values.
    node.capture_directory=folder
    if force_host:
        node.auto_capture=True
    if not manual:
        node.pick_vs,node.pick_ps=vs,ps
    return folder,vs,ps
