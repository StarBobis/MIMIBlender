

import bpy

from ..common.mesh_create_helper import MeshCreateHelper
from .migoto_binary_file import MigotoBinaryFile


class MeshImportHelper:
    @staticmethod
    def create_mesh_obj_from_mbf(mbf:MigotoBinaryFile, import_collection:bpy.types.Collection):
        if not mbf.file_size_check():
            return

        return MeshCreateHelper.create_mesh_object(
            mesh_name=mbf.mesh_name,
            source_path=mbf.fmt_path,
            logic_name=mbf.fmt_file.logic_name,
            gametypename=mbf.fmt_file.gametypename,
            elements=mbf.fmt_file.elements,
            vb_data=mbf.vb_data,
            ib_data=mbf.ib_data,
            vb_vertex_count=mbf.vb_vertex_count,
            ib_count=mbf.ib_count,
            ib_polygon_count=mbf.ib_polygon_count,
            import_collection=import_collection,
        )

    @staticmethod
    def set_import_attributes(obj, mbf:MigotoBinaryFile):
        return MeshCreateHelper.set_import_attributes(obj=obj, gametypename=mbf.fmt_file.gametypename)

    @staticmethod
    def set_import_coordinate(obj):
        return MeshCreateHelper.set_import_coordinate(obj=obj)

    @staticmethod
    def initialize_mesh(mesh, mbf:MigotoBinaryFile):
        return MeshCreateHelper.initialize_mesh(
            mesh=mesh,
            ib_data=mbf.ib_data,
            ib_count=mbf.ib_count,
            ib_polygon_count=mbf.ib_polygon_count,
            logic_name=mbf.fmt_file.logic_name,
            vb_vertex_count=mbf.vb_vertex_count,
        )

    @staticmethod
    def import_uv_layers(mesh, obj, texcoords):
        return MeshCreateHelper.import_uv_layers(mesh=mesh, obj=obj, texcoords=texcoords)

    @staticmethod
    def import_vertex_groups(mesh, obj, blend_indices, blend_weights, component):
        return MeshCreateHelper.import_vertex_groups(
            mesh=mesh,
            obj=obj,
            blend_indices=blend_indices,
            blend_weights=blend_weights,
            component=component,
        )

    @staticmethod
    def import_shapekeys(mesh, obj, shapekeys):
        return MeshCreateHelper.import_shapekeys(mesh=mesh, obj=obj, shapekeys=shapekeys)

    @staticmethod
    def create_bsdf_with_diffuse_linked(obj, mesh_name:str, directory:str, logic_name:str | None = None):
        return MeshCreateHelper.create_bsdf_with_diffuse_linked(
            obj=obj,
            mesh_name=mesh_name,
            directory=directory,
            logic_name=logic_name,
        )
