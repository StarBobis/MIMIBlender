from dataclasses import dataclass, field
from typing import Dict, List
from copy import deepcopy


@dataclass
class WWMIInfoComponent:
    vertex_offset: int
    vertex_count: int
    index_offset: int
    index_count: int
    vg_offset: int
    vg_count: int
    vg_map: Dict[int, int]


@dataclass
class WWMIInfoShapeKeys:
    offsets_hash: str = ''
    scale_hash: str = ''
    vertex_count: int = 0
    dispatch_y: int = 0
    # Missing and zero are different: empty leading shape slots can hash to 0.
    # None preserves absence until the runtime metadata validator reports it.
    checksum: int | None = None
    batches: list = field(default_factory=list)


@dataclass
class WWMIInfoObject:
    vb0_hash: str
    cb4_hash: str
    vertex_count: int
    index_count: int
    components: List[WWMIInfoComponent]
    shapekeys: WWMIInfoShapeKeys


def _merge_shape_batches(sources, required_key_count):
    """Merge one horizontal batch before deciding whether its successor is used.

    A component can omit its key count while another records it. Per-component
    early truncation would default that count and lose needed complementary
    fields, or even conceal a real conflict in the next consumed batch.
    """
    result = []
    key_end = 0
    for index in range(max((len(rows) for rows in sources), default=0)):
        merged = {}
        for rows in sources:
            if index >= len(rows):
                continue
            batch = deepcopy(rows[index])
            if not isinstance(batch, dict):
                raise ValueError("WWMI malformed required shape batch " + str(index))
            # Invalidated numeric defaults cannot compete with actual evidence.
            if batch.get("runtime_metadata_complete") is False:
                for field_name in ("checksum", "dispatch_y", "vertex_offset"):
                    batch.pop(field_name, None)
            for field_name, value in batch.items():
                if field_name == "runtime_metadata_complete":
                    merged.setdefault(field_name, value)
                    continue
                if value is None:
                    continue
                previous = merged.get(field_name)
                if previous is not None and previous != value:
                    raise ValueError("WWMI conflicting shape key metadata for batches."
                                     + str(index) + "." + field_name)
                merged[field_name] = value
        result.append(merged)
        # Only the merged count can select the global consumed prefix.
        count = merged.get("shapekey_count")
        if count is not None:
            try:
                parsed = int(count)
            except (ValueError, TypeError, OverflowError):
                raise ValueError("WWMI invalid required shape batch size")
            if isinstance(count, bool) or (not isinstance(count, str) and count != parsed) or not 0 <= parsed <= 127:
                raise ValueError("WWMI invalid required shape batch size")
            count = parsed
        key_end += 127 if count is None else count
        if required_key_count is not None and required_key_count <= key_end:
            break
    return result


class WWMIInfoHelper:
    @staticmethod
    def build_from_json_list(ordered_submesh_json_list: list, include_shapekeys=True,
                             required_key_count=None) -> WWMIInfoObject:
        if not ordered_submesh_json_list:
            raise ValueError("No SubmeshJson provided to build WWMIInfoObject.")

        first_json = ordered_submesh_json_list[0]
        vb0_hash = first_json.VertexLimitVB
        cb4_hash = first_json.CB4Hash

        components = []
        total_index_count = 0
        max_vertex_end = 0

        for j in ordered_submesh_json_list:
            vertex_offset = j.VertexOffset
            vertex_count = max(j.VertexCount, 0)
            index_offset = int(j.JsonDict.get("IndexOffset", 0))
            index_count = int(j.JsonDict.get("IndexCount", 0))
            vg_offset = j.VGOffset
            vg_count = j.VGCount
            vg_map = {str(k): int(v) for k, v in j.VGMap.items()}

            component = WWMIInfoComponent(
                vertex_offset=vertex_offset,
                vertex_count=vertex_count,
                index_offset=index_offset,
                index_count=index_count,
                vg_offset=vg_offset,
                vg_count=vg_count,
                vg_map=vg_map,
            )
            components.append(component)
            total_index_count += index_count
            max_vertex_end = max(max_vertex_end, vertex_offset + vertex_count)

        # Shapes belong to the DrawIB/LOD, not necessarily its first component.
        # Older workspaces sometimes attach them only to the face component.
        # Merge complementary records, but do not silently select conflicting
        # runtime hashes or checksums from another extraction of the character.
        sk_info = {}
        # Upstream uses explicit batches when present and treats scalar checksum
        # / dispatch fields as deprecated. Mixing an old component header with
        # a newer batch record must not compare two different representations.
        has_batches = include_shapekeys and any(row.ShapeKeysInfo.get("batches") for row in ordered_submesh_json_list)
        legacy_fields = {"checksum", "dispatch_y", "vertex_count", "vertex_offset",
                         "shapekey_count", "runtime_metadata_complete"}
        for submesh in ordered_submesh_json_list if include_shapekeys else []:
            for key, value in submesh.ShapeKeysInfo.items():
                if value is None or value == "" or value == []:
                    continue
                if has_batches and key in legacy_fields:
                    continue
                if key.endswith("_hash") and isinstance(value, str):
                    value = value.lower()
                if key == "batches":
                    continue
                if key in sk_info and sk_info[key] != value:
                    raise ValueError("WWMI conflicting shape key metadata for " + key)
                sk_info[key] = deepcopy(value)
        if has_batches:
            sources = [row.ShapeKeysInfo.get("batches") or [] for row in ordered_submesh_json_list]
            sk_info["batches"] = _merge_shape_batches(sources, required_key_count)
            for batch in sk_info["batches"]:
                # Completeness follows the merged evidence, never the order in
                # which older and newer component copies were encountered.
                if "runtime_metadata_complete" in batch:
                    batch["runtime_metadata_complete"] = all(
                        batch.get(field_name) is not None
                        for field_name in ("checksum", "dispatch_y", "vertex_offset"))
            first_batch = sk_info["batches"][0]
            # Compatibility scalars describe the same first runtime dispatch.
            # No deprecated header can replace an explicit batch identity.
            for key in legacy_fields:
                if key in first_batch:
                    sk_info[key] = deepcopy(first_batch[key])
        shapekeys = WWMIInfoShapeKeys(
            offsets_hash=sk_info.get("offsets_hash", ""),
            scale_hash=sk_info.get("scale_hash", ""),
            vertex_count=sk_info.get("vertex_count", 0),
            dispatch_y=sk_info.get("dispatch_y", 0),
            checksum=sk_info.get("checksum"),
            batches=list(sk_info.get("batches", [])),
        )
        if not shapekeys.batches and shapekeys.checksum is not None:
            # Legacy extraction has one batch, even with a valid zero checksum.
            # Preserve explicit original bases and key counts when available.
            # Never infer another runtime dispatch from edited Mod buffers.
            shapekeys.batches = [{
                "vertex_offset": sk_info.get("vertex_offset", 0),
                "vertex_count": shapekeys.vertex_count,
                "dispatch_y": shapekeys.dispatch_y,
                "checksum": shapekeys.checksum,
                "shapekey_count": sk_info.get("shapekey_count", 127),
                "runtime_metadata_complete": sk_info.get("runtime_metadata_complete", True),
            }]

        return WWMIInfoObject(
            vb0_hash=vb0_hash,
            cb4_hash=cb4_hash,
            vertex_count=max_vertex_end,
            index_count=total_index_count,
            components=components,
            shapekeys=shapekeys,
        )
