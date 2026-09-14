# Helpers for wiring image textures into materials in a way that works in
# every interface language.
#
# Blender localises *node* names: in a Chinese interface "Principled BSDF"
# is called "原理化 BSDF". Looking a node up by name with
# nodes.get("Principled BSDF") silently fails there, and the code then
# creates a second, unconnected node. That is exactly the bug this module
# avoids. Node properties such as bl_idname and type are internal
# identifiers and are never translated, so nodes must be found by
# bl_idname instead of by name.
#
# Node *socket* names (inputs / outputs) are NOT localised: their name and
# identifier stay English in every language, so looking sockets up by name
# is safe.
import bpy


def find_node(nodes, bl_idname):
    """Return the first node whose internal type id matches, or None.

    bl_idname is stable and language independent (for example
    "ShaderNodeBsdfPrincipled"). Node .name is localised and must never be
    used to find a node, otherwise the lookup breaks in a non-English
    interface.
    """
    for node in nodes:
        if node.bl_idname == bl_idname:
            return node
    return None


def apply_image_texture_to_material(material, image_data):
    """Add an image texture to a material and wire it into the shader.

    This is the shared core of the "Apply Texture to Selected Objects"
    operators (quick preview texture panel and sword panel). It reuses the
    existing Principled BSDF and Material Output nodes (found by bl_idname)
    instead of creating new ones, so the image connects to the original
    node chain that is already tied to the material output.

    The image alpha mode is forced to CHANNEL_PACKED: game base-color maps
    pack data (emission / material masks) into the alpha channel, so alpha
    must stay available as packed data and must NOT drive transparency.
    For the same reason the Alpha output is deliberately left unlinked.
    """
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links

    # Find the Principled BSDF by type, never by localised name.
    bsdf_node = find_node(nodes, "ShaderNodeBsdfPrincipled")
    if bsdf_node is None:
        # No shader yet: create one and connect it to the output node.
        bsdf_node = nodes.new(type="ShaderNodeBsdfPrincipled")
        bsdf_node.location = (0, 0)

        # Get the material output node, also found by type only.
        output_node = find_node(nodes, "ShaderNodeOutputMaterial")
        if output_node is None:
            output_node = nodes.new(type="ShaderNodeOutputMaterial")
            output_node.location = (400, 0)

        # Wire the new shader into the material output.
        links.new(bsdf_node.outputs["BSDF"], output_node.inputs["Surface"])

    # Create the image texture node that shows the picked image.
    tex_image = nodes.new(type="ShaderNodeTexImage")
    tex_image.image = image_data
    tex_image.location = (-300, 0)

    # Mark the alpha channel as packed data. Guarded: generated/UDIM images
    # still expose alpha_mode, but a failed assignment must never abort the
    # texture wiring itself.
    if image_data is not None:
        try:
            image_data.alpha_mode = "CHANNEL_PACKED"
        except (AttributeError, TypeError, ValueError):
            pass

    # Connect the image to the shader. Socket names stay English in every
    # language, so these lookups are stable identifiers. Alpha stays
    # unlinked: with CHANNEL_PACKED it carries mask data, not coverage.
    links.new(tex_image.outputs["Color"], bsdf_node.inputs["Base Color"])
