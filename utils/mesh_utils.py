import numpy


class MeshUtils:
    @staticmethod
    def set_import_normals(mesh, normals):
        normals = numpy.asarray(normals, dtype=numpy.float32)
        mesh.normals_split_custom_set_from_vertices(normals)

    @staticmethod
    def set_import_normals_v2(mesh, normals):
        normals = numpy.asarray(normals, dtype=numpy.float32)
        n_verts = len(mesh.vertices)
        if normals.shape[0] != n_verts:
            raise ValueError(f"Expected {n_verts} vertex normals, got {normals.shape[0]}")
        mesh.normals_split_custom_set_from_vertices(normals)
