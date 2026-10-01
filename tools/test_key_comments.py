"""Verify shape hotkey remarks without requiring a live Blender installation.

Use the actual exporter, refresh operator and shared INI writer implementations.
Only Blender registration and graph IO are replaced by small in-memory stubs.
No generated test files are written outside the repository tmp directory.
"""

import ast
import os
import sys
import types

import test_time_switch_ini as support

# Prevent bytecode artifacts next to production modules during this smoke test.
sys.dont_write_bytecode = True
support.ensure_parent_packages()
support.install_stubs()
modules = support.load_real_modules()
key_class = modules[support.TEST_PKG + ".common.m_key"].M_Key
builder_class = modules[support.TEST_PKG + ".common.m_ini_builder"].M_IniBuilder
ini_helper = modules[support.TEST_PKG + ".common.m_ini_helper"].M_IniHelper


def load_method(relative_path, class_name, method_name, namespace):
    """Compile an unchanged method body while skipping bpy class registration."""
    # The source is parsed, not copied, so regressions exercise production code.
    with open(os.path.join(support.ROOT, relative_path), encoding="utf-8") as source:
        tree = ast.parse(source.read())
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == method_name)
    method.decorator_list = []
    exec(compile(ast.Module(body=[method], type_ignores=[]), relative_path, "exec"), namespace)
    return namespace[method_name]


# Include an old list item without comment to prove saved files remain compatible.
items = [
    types.SimpleNamespace(enabled=True, shapekey_name="Smile", key="F6", comment="Expression\nSecond line"),
    types.SimpleNamespace(enabled=True, shapekey_name="Old", key="F7"),
]
output = types.SimpleNamespace(enable_shapekey=True, shapekey_items=items, bl_idname="MIMINode_Result_Output")
tree = types.SimpleNamespace(nodes=[output])
output.id_data = tree
helper = types.SimpleNamespace(runtime_output_node=output, get_current_blueprint_tree=lambda context=None: tree)
namespace = {"M_Key": key_class, "BlueprintExportHelper": helper}
get_keys = load_method("blueprint/blueprint_export_helper.py", "BlueprintExportHelper", "get_current_shapekeyname_mkey_dict", namespace)
keys = get_keys()
assert keys["Smile"].comment == "Expression\nSecond line"
assert keys["Old"].comment == ""

# Verify both kinds of keys use comments immediately after their section header.
# Inspect the real builder sections in memory rather than creating an INI file.
builder = builder_class()
# No draw buffers means no shader files are copied; only tmp is created.
shape_module = support.load_module_by_path(
    support.TEST_PKG + ".common.m_shape_layout", os.path.join(support.ROOT, "common/m_shape_layout.py")
)
writer_module = modules[support.TEST_PKG + ".common.m_ini_helper"]
writer_module.BlueprintExportHelper.get_current_shapekeyname_mkey_dict = lambda: keys
writer_module.GlobalConfig.path_generate_mod_folder = lambda: os.path.join(support.ROOT, "tmp", "key_comments")
ini_helper.add_shapekey_ini_sections(builder, {})
shape_lines = [line for section in builder.ini_section_list for line in section.SectionLineList]
index = shape_lines.index("[Key_ShapeKey_Smile]")
assert shape_lines[index + 1:index + 3] == ["; Expression", "; Second line"]
assert "$shapekey0 = 0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1" in shape_lines
hotkey = key_class(key_name="$swapkey0", value_list=[0, 1], initialize_vk_str="3", comment="Hat")
builder = builder_class()
ini_helper.add_branch_key_sections(builder, {hotkey.key_name: hotkey})
branch_lines = [line for section in builder.ini_section_list for line in section.SectionLineList]
index = branch_lines.index("[KeySwap_0]")
assert branch_lines[index + 1] == "; Hat"


class ItemList(list):
    # Mimic just the Blender CollectionProperty methods used by refresh.
    # Production logic still owns the settings transfer and deduplication.
    def add(self):
        item = types.SimpleNamespace(enabled=False, shapekey_name="", key="", comment="")
        self.append(item)
        return item


# Refresh the list using a fake object source from this exact output graph.
# Relative imports resolve inside the same synthetic package as the INI tests.
source_object = types.SimpleNamespace(type="MESH", data=types.SimpleNamespace(
    shape_keys=types.SimpleNamespace(key_blocks=[types.SimpleNamespace(name=name) for name in ("Basis", "Smile", "Old")])
))
source_node = types.SimpleNamespace(bl_idname="MIMINode_Object_Info")
graph_stub = types.ModuleType(support.TEST_PKG + ".blueprint.blueprint_graph")
graph_stub.iter_object_sources = lambda node: [source_node]
sys.modules[graph_stub.__name__] = graph_stub
object_stub = types.ModuleType(support.TEST_PKG + ".blueprint.blueprint_node_obj")
object_stub.ObjectPersistentIdManager = types.SimpleNamespace(resolve_node_target=lambda node: source_object)
sys.modules[object_stub.__name__] = object_stub
output.shapekey_items = ItemList(items)
tree.bl_idname = "MIMIBlueprintTreeType"
refresh_namespace = {"__package__": support.TEST_PKG + ".blueprint", "tr": lambda text: text}
execute = load_method("blueprint/blueprint_node_shapekey.py", "MMT_OT_RefreshShapeKeyList", "execute", refresh_namespace)
get_names = load_method("blueprint/blueprint_node_shapekey.py", "MMT_OT_RefreshShapeKeyList", "_get_shapekeys_from_object", refresh_namespace)
operator = types.SimpleNamespace(node_name="", tree_name="", report=lambda *args: None, _get_shapekeys_from_object=get_names)
tree.nodes = types.SimpleNamespace(active=output)
context = types.SimpleNamespace(space_data=types.SimpleNamespace(edit_tree=tree))
assert execute(operator, context) == {"FINISHED"}
assert output.shapekey_items[0].comment == "Expression\nSecond line"
assert output.shapekey_items[0].key == "F6"
assert output.shapekey_items[1].comment == ""
# Exercise the actual shared-key merge statements without loading Blender RNA.
# Repeated graph visits must retain distinct remarks once and in traversal order.
with open(os.path.join(support.ROOT, "model/blueprint_model.py"), encoding="utf-8") as source:
    model_tree = ast.parse(source.read())
merge_block = next(
    node for node in ast.walk(model_tree)
    if isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
    and ast.unparse(node.test) == "existing_key is None"
    and any(isinstance(statement, ast.Assign) and ast.unparse(statement.targets[0]) == "comments" for statement in node.orelse)
)
merge_code = compile(ast.Module(body=merge_block.orelse[1:], type_ignores=[]), "shared_key_merge", "exec")
existing = key_class(comment="Hat")
for remark in ("Clothes", "Hat", "Clothes", ""):
    merge_namespace = {"existing_key": existing, "m_key": key_class(comment=remark)}
    exec(merge_code, merge_namespace)
assert existing.comment == "Hat\nClothes"
print("Key remarks: export, multiline INI, legacy lists, refresh and shared-key merge passed.")
