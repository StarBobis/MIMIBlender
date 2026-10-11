import math
import bpy

from mathutils import *


class AlgorithmUtils:
    '''
    SmoothNormal Algorithm.
    SupportedGame: GI,HI3,HSR,ZZZ,WWMI
    Designed For: ZZZ,WWMI

    Nico: For unknown reasons this method can only approximately restore the content in TEXCOORD1; perhaps the weighted average is missing?
    Too much related knowledge is missing, so this is parked for now

    # Code credit and source:
    # function 
    # https://www.bilibili.com/video/BV13G411u75s/?spm_id_from=333.999.0.0 
    # by "Give you lemon coconut Yakult, will you play with me?" (bilibili)

    # Store the XY components of the normal in the UV map coordinates (X: normal.x, Y: normal.y)
    # Inspired by smoothtool from github
    # by dashu04

    # Assembled by "Exiled Knight"
    # Decomposed the info chain and refactored it into a utility class by NicoMico
    '''
    @staticmethod
    def vector_cross_product(v1,v2):
        '''
        Cross Product: The cross product of two non-parallel 3D vectors produces a new vector perpendicular to both of the original vectors.
        Therefore, for a given triangle, taking the cross product of two of its edges yields a vector perpendicular to the triangle's plane; this is the so-called normal vector.
        '''
        return Vector((v1.y*v2.z-v2.y*v1.z,v1.z*v2.x-v2.z*v1.x,v1.x*v2.y-v2.x*v1.y))
    
    @staticmethod
    def vector_dot_product (a,b):
        return a.x*b.x+a.y*b.y+a.z*b.z
    
    @staticmethod
    def vector_calc_length(v):
        return math.sqrt(v.x*v.x+v.y*v.y+v.z*v.z)
    
    @classmethod
    def vector_normalize(cls,v):
        '''
        Normalization:
        Then normalize the cross product result, i.e. adjust the normal vector's length to 1, which ensures the normal vector only represents direction without length information.
        This step is important because lighting calculations usually rely on unit-length normal vectors for correctness.
        '''
        L = cls.vector_calc_length(v)
        if L != 0 :
            return v/L
        return 0
    
    @staticmethod
    def vector_to_string(v):
        '''
        Convert a Vector into a string, convenient for storing in a dict
        '''
        return "x=" + str(v.x) + ",y=" + str(v.y) + ",z=" + str(v.z)
    
    @staticmethod
    def need_outline(vertex):
        '''
        Only for testing; in actual use it should always return True
        '''
        need = False
        for g in vertex.groups:
            if g.group == 446:
                need = True
                break
        return True
    
    @classmethod
    def calculate_angle_between_vectors (cls,v1,v2):
        ASIZE = cls.vector_calc_length(v1)
        BSIZE = cls.vector_calc_length(v2)
        D = ASIZE*BSIZE
        if D != 0:
            degree = math.acos(cls.vector_dot_product(v1,v2)/(ASIZE*BSIZE))
            #S = ASIZE*BSIZE*math.sin(degree)
            return degree
        return 0
    
    @classmethod
    def smooth_normal_save_to_uv(cls):
        mesh = bpy.context.active_object.data
        uvdata = mesh.uv_layers.active.data
        
        mesh.calc_tangents(uvmap="TEXCOORD.xy")
        # mesh.calc_tangents()

        co_str_data_dict = {}

        # Start
        for vertex in mesh.vertices:
            co = vertex.co
            co_str = cls.vector_to_string(co)
            co_str_data_dict[co_str] = []
        print("========")

        for poly in mesh.polygons:
            # Get the three vertices of the triangle
            loop_0 = mesh.loops[poly.loop_start]
            loop_1 = mesh.loops[poly.loop_start+1]
            loop_2 = mesh.loops[poly.loop_start + 2]

            # Get the vertex data
            vertex_loop0 = mesh.vertices[loop_0.vertex_index]
            vertex_loop1 = mesh.vertices[loop_1.vertex_index]
            vertex_loop2 = mesh.vertices[loop_2.vertex_index]

            # Convert the vertex data into string format
            co0_str = cls.vector_to_string(vertex_loop0.co)
            co1_str = cls.vector_to_string(vertex_loop1.co)
            co2_str = cls.vector_to_string(vertex_loop2.co)

            # Compute the normal using CorssProduct
            normal_vector = cls.vector_cross_product(vertex_loop1.co-vertex_loop0.co,vertex_loop2.co-vertex_loop0.co)
            # Normalize the normal so its length stays 1
            normal_vector = cls.vector_normalize(normal_vector)

            if co0_str in co_str_data_dict and cls.need_outline(vertex_loop0):
                w = cls.calculate_angle_between_vectors(vertex_loop2.co-vertex_loop0.co,vertex_loop1.co-vertex_loop0.co)
                co_str_data_dict[co0_str].append({"n":normal_vector,"w":w,"l":loop_0})
            if co1_str in co_str_data_dict and cls.need_outline(vertex_loop1):
                w = cls.calculate_angle_between_vectors(vertex_loop2.co-vertex_loop1.co,vertex_loop0.co-vertex_loop1.co)
                co_str_data_dict[co1_str].append({"n":normal_vector,"w":w,"l":loop_1})
            if co2_str in co_str_data_dict and cls.need_outline(vertex_loop0):
                w = cls.calculate_angle_between_vectors(vertex_loop1.co-vertex_loop2.co,vertex_loop0.co-vertex_loop2.co)
                co_str_data_dict[co2_str].append({"n":normal_vector,"w":w,"l":loop_2})

        # Write into UV
        uv_layer = mesh.uv_layers.new(name="SmoothNormalMap")
        for poly in mesh.polygons:
            for loop_index in range(poly.loop_start,poly.loop_start+poly.loop_total):
                vertex_index=mesh.loops[loop_index].vertex_index
                vertex = mesh.vertices[vertex_index]

                # Initialize the smooth normal and the smooth weight
                smoothnormal=Vector((0,0,0))
                weight = 0

                # Compute the smooth normal as the weighted average of the normals of the adjacent faces
                if cls.need_outline(vertex):
                    costr=cls.vector_to_string(vertex.co)

                    if costr in co_str_data_dict:
                        a = co_str_data_dict[costr]
                        # Iterate over the data of all faces that share this vertex
                        for d in a:
                            # Get the normal and the weight of each face
                            normal_vector=d['n']
                            w = d['w']
                            # Accumulate the weighted normals and the weights
                            smoothnormal  += normal_vector*w
                            weight  += w
                if smoothnormal != Vector((0,0,0)):
                    smoothnormal /= weight
                    smoothnormal = cls.vector_normalize(smoothnormal)

                loop_normal = mesh.loops[loop_index].normal
                loop_tangent = mesh.loops[loop_index].tangent
                loop_bitangent = mesh.loops[loop_index].bitangent

                tx = cls.vector_dot_product(loop_tangent,smoothnormal)
                ty = cls.vector_dot_product(loop_bitangent,smoothnormal)
                tz = cls.vector_dot_product(loop_normal,smoothnormal)

                normalT=Vector((tx,ty,tz))
                # print("nor:",smoothnormal)

                # Store the XY components of the normal into the UV map coordinates (X: normal.x, Y: normal.y)
                # May need adjusting per engine, e.g. UE uses (x, 1+y)

                # uv = (normalT.x, 1 + normalT.y) 
                uv = (normalT.x, 1 + normalT.y) 
                uv_layer.data[loop_index].uv = uv

        # Recalculate the object's UV map to apply the changes
        # bpy.ops.object.mode_set(mode="EDIT")
        # bpy.ops.uv.unwrap(method='ANGLE_BASED')
        # bpy.ops.object.mode_set(mode="OBJECT")