# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

bl_info = {
    "name": "Import DirectX X Format (.x)",
    "author": "T.Yonemori, B.Okada",
    "version": (0, 5, 1),
    "blender": (2, 66, 0),
    "location": "File > Import > DirectX (.x)",
    "description": "Import files in the DirectX X format (.x)",
    "warning": "",
    "wiki_url": "",
    "tracker_url": "",
    "category": "Import-Export"
    }

# Copyright (c) T.Yonemori 2012
# boiled_frog04@yahoo.co.jp
#
# Version 0.3 - Mar 16, 2012
#
import os
import bpy
from mathutils import *

#
#    Global flags
#

T_Debug      = 0x10
T_Verbose    = 0x20

#
#    Token kind
#
TK_LITERAL_NUM    = 1
TK_LITERAL_STRING = 2
TK_ID        = 3
TK_COMMA     = 4
TK_SEMICOLON = 5
TK_LBRACE    = 6
TK_RBRACE    = 7
TK_OP_MINUS  = 8

TK_UUID      = 10

TK_EOF = -1

from bpy.props import *

class ImportSettings:
    def __init__(self, CoordinateSystem=1,UpwardAxis=1):
        self.CoordinateSystem = int(CoordinateSystem)
        self.UpwardAxis = int(UpwardAxis)

class CharacterStream:
    def __init__(self, fileName):
        self.fp = open(fileName, "r")
        self.curLine = ""
        self.curIndex = 0
        self.curLineLen = 0
        self.unget = ""

    def getChar(self):
        if self.unget != "":
            ch = self.unget
            self.unget = ""
            return ch
        elif self.curIndex >= self.curLineLen:
            self.curLine = self.fp.readline()
            self.curLineLen = len(self.curLine)
            self.curIndex = 0
            if self.curLine == "":
                return None
        ch = self.curLine[self.curIndex]
        self.curIndex = self.curIndex + 1
        return ch
 
    def ungetChar(self,ch):
        self.unget = ch

    def close(self):
        self.fp.close()

class Token:
    def __init__(self, kind, value=""):
        self.kind  = kind
        self.value = value

class Tokenizer:
    def __init__(self, filePath):
        self.lineno = 1
        self.filePath = filePath
        self.cstr = CharacterStream(filePath)

    def shutdown(self):
        self.cstr.close()

    def skipToEOL(self):
        while 1:
            c = self.cstr.getChar()
            if c is None:
               break 
            if c == "\n":
                self.lineno += 1
                break

    def getToken(self):
        while 1:
            c = self.cstr.getChar()
            if c is None:
               return Token(TK_EOF)
            elif c == ' ' or c == '\t':
                pass
            elif c == '#':
                self.skipToEOL()
            elif c == '/':
                c = self.cstr.getChar()
                if c == '/':
                    self.skipToEOL()
                else:
                    self.cstr.ungetChar()
                    raise RuntimeError("")
            elif c == '\n':
                self.lineno += 1
            elif c == "<":
               c = self.cstr.getChar()
               while not c is None and c != ">":
                   c = self.cstr.getChar()
               if c is None:
                   self.cstr.ungetChar(c)
               else:
                   return Token(TK_UUID)
            elif c == '"':
               valStr = ""
               c = self.cstr.getChar()
               while not c is None and c != '"':
                   valStr += c
                   c = self.cstr.getChar()
               if c is None:
                   self.cstr.ungetChar(c)
               else:
                   return Token(TK_LITERAL_STRING, valStr)
            elif c.isdecimal() or c == ".":
                numStr = ""
                if c.isdecimal():
                    numStr += c
                    c = self.cstr.getChar()
                    while c.isdecimal():
                        numStr += c
                        c = self.cstr.getChar()
                if c == ".":
                    numStr += c
                    c = self.cstr.getChar()
                    while c.isdecimal():
                        numStr += c
                        c = self.cstr.getChar()
                self.cstr.ungetChar(c)
                return Token(TK_LITERAL_NUM, numStr)
            elif c.isalpha() or c == "_":
                identStr = c
                c = self.cstr.getChar()
                while c.isalnum() or c in ["_", "-"]:
                    identStr = identStr + c
                    c = self.cstr.getChar()
                self.cstr.ungetChar(c)
                return Token(TK_ID, identStr)
            elif c == "{":
                return Token(TK_LBRACE)
            elif c == "}":
                return Token(TK_RBRACE)
            elif c == "-":
                return Token(TK_OP_MINUS)
            elif c == ";":
                return Token(TK_SEMICOLON)
            elif c == ",":
                return Token(TK_COMMA)
            else:
                pass

class CMaterial:
    def __init__(self):
        self.faceColor = [1.0,1.0,1.0,1.0]
        self.power = 0.0
        self.specularColor = [1.0,1.0,1.0]
        self.emissiveColor = [1.0,1.0,1.0]
        self.textureFilename = ""

class MeshData:
    def __init__(self, mesh):
        self.mesh   = mesh
        self.coords = None
        self.faces  = None
        self.texCoords = None
        self.vertexColors = None
        self.faceMaterialIndex = None
        self.normals = None
        self.faceNormals = None

class Parser:

    def __init__(self, fileName, config):
        self.config    = config
        self.tokenizer = Tokenizer(fileName)
        self.lookahead = self.tokenizer.getToken()
        self.materialDict = {}

    def matchToken(self, kind, value=""):
        if self.lookahead.kind == kind and (value == "" or self.lookahead.value == value):
            res = self.lookahead.value
            self.lookahead = self.tokenizer.getToken()
            return res
        else:
            raise RuntimeError("("+str(self.tokenizer.lineno)+")" + self.lookahead.value)
    
    def parseFileHeader(self):
        self.matchToken(TK_ID, "xof")
        self.matchToken(TK_LITERAL_NUM)
        self.matchToken(TK_ID, "txt")
        self.matchToken(TK_LITERAL_NUM)
                          
    def parseTemplateDef(self):
        self.matchToken(TK_ID, "template")
        self.matchToken(TK_ID)
        self.matchToken(TK_LBRACE)
        while self.lookahead.kind != TK_RBRACE:
            self.lookahead = self.tokenizer.getToken()
        self.matchToken(TK_RBRACE)
    
    def skipInstanceBlock(self):
        level = 1
        while self.lookahead.kind != TK_RBRACE or level > 1:
            if self.lookahead.kind == TK_LBRACE:
                level += 1
            elif self.lookahead.kind == TK_RBRACE:
                level -= 1
                if level < 1:
                    raise RuntimeError("")
            self.lookahead = self.tokenizer.getToken()
#        print("leave at " + str(self.tokenizer.lineno) + " kind " + str(self.lookahead.kind))
    
    def parseFloat(self):
        if self.lookahead.kind == TK_OP_MINUS:
            scale = -1.0
            self.matchToken(TK_OP_MINUS)
        else:
            scale = 1.0
        val = self.matchToken(TK_LITERAL_NUM)
        res = scale * float(val)
        return res
    
    def checkSeparator(self):
        if self.lookahead.kind in [TK_COMMA,TK_SEMICOLON]:
            self.matchToken(self.lookahead.kind)
        else:
            RuntimeError("lack of separator")

    def parseMeshCoords(self):
        val = self.matchToken(TK_LITERAL_NUM)
        nVertices = int(val)
        self.matchToken(TK_SEMICOLON)
        coords = []
        for v in range(nVertices):
            x = self.parseFloat()
            self.matchToken(TK_SEMICOLON)
            y = self.parseFloat()
            self.matchToken(TK_SEMICOLON)
            z = self.parseFloat()
            self.matchToken(TK_SEMICOLON)
            if v < nVertices - 1:
                self.checkSeparator()
            if self.config.CoordinateSystem == 1:
                z *= -1.0
            if self.config.UpwardAxis == 1:
                coords.append((x,-z,y))
            else:
                coords.append((x,y,z))
        
        self.checkSeparator()
        
        return coords
    
    def parseMeshFaces(self, offset=0):
        val = self.matchToken(TK_LITERAL_NUM)
        nFaces = int(val)
        self.matchToken(TK_SEMICOLON)
        faces = []
        for f in range(nFaces):
            val = self.matchToken(TK_LITERAL_NUM)
            nFaceVertexIndices = int(val)
            self.matchToken(TK_SEMICOLON)
            indices = []
            for i in range(nFaceVertexIndices):
                val = self.matchToken(TK_LITERAL_NUM)
                index = int(val)
                indices.append(index+offset)
                if i < nFaceVertexIndices - 1:
                    self.checkSeparator()
            self.matchToken(TK_SEMICOLON)
            if len(indices) == 3:
                indices.append(indices[0])
            if self.config.CoordinateSystem == 1:
                indices.reverse()
            if len(indices) <= 4:
                faces.append(tuple(indices))
            if f < nFaces - 1:
                self.matchToken(TK_COMMA)
        self.matchToken(TK_SEMICOLON)
        
        return faces
    
    def parseMeshVertexColors(self):
        val = self.matchToken(TK_LITERAL_NUM)
        nVertices = int(val)
        self.matchToken(TK_SEMICOLON)
        colors = [(1.0,1.0,1.0,1.0)]
        for v in range(nVertices):
            self.matchToken(TK_LITERAL_NUM)
            self.matchToken(TK_SEMICOLON)
            r = self.parseFloat()
            self.matchToken(TK_SEMICOLON)
            g = self.parseFloat()
            self.matchToken(TK_SEMICOLON)
            b = self.parseFloat()
            self.matchToken(TK_SEMICOLON)
            a = self.parseFloat()
            self.matchToken(TK_SEMICOLON)
            if v < nVertices - 1:
                if self.lookahead.kind == TK_COMMA:
                    self.matchToken(TK_COMMA)
                else:
                    self.matchToken(TK_SEMICOLON)
            colors.append((r,g,b,a))
        self.matchToken(TK_SEMICOLON)
        if self.lookahead.kind == TK_SEMICOLON:
            self.matchToken(TK_SEMICOLON)
        return colors
    
    def parseMaterialCore(self):
        m = CMaterial()
    
        m.faceColor[0] = self.parseFloat()
        self.matchToken(TK_SEMICOLON)
        m.faceColor[1] = self.parseFloat()
        self.matchToken(TK_SEMICOLON)
        m.faceColor[2] = self.parseFloat()
        self.matchToken(TK_SEMICOLON)
        m.faceColor[3] = self.parseFloat()
        self.matchToken(TK_SEMICOLON)
        self.matchToken(TK_SEMICOLON)
        
        m.power = self.parseFloat()
        self.matchToken(TK_SEMICOLON)
    
        m.specularColor[0] = self.parseFloat()
        self.matchToken(TK_SEMICOLON)
        m.specularColor[1] = self.parseFloat()
        self.matchToken(TK_SEMICOLON)
        m.specularColor[2] = self.parseFloat()
        self.matchToken(TK_SEMICOLON)
        self.matchToken(TK_SEMICOLON)
    
        m.emissiveColor[0] = self.parseFloat()
        self.matchToken(TK_SEMICOLON)
        m.emissiveColor[1] = self.parseFloat()
        self.matchToken(TK_SEMICOLON)
        m.emissiveColor[2] = self.parseFloat()
        self.matchToken(TK_SEMICOLON)
        self.matchToken(TK_SEMICOLON)
    
        material = bpy.data.materials.new("Material")
    
        material.diffuse_color = [m.faceColor[0]+m.emissiveColor[0], m.faceColor[1]+m.emissiveColor[1], m.faceColor[2]+m.emissiveColor[2]]
        material.diffuse_intensity = 1.0
        material.diffuse_shader = "LAMBERT"
        material.specular_color = m.specularColor
        material.specular_shader = 'COOKTORR'
        material.specular_intensity = 1.0
        material.specular_hardness = m.power
    
        material.alpha = m.faceColor[3]
        material.use_transparency = material.alpha < 1.0
    
        material.ambient = 1
    
        if self.lookahead.kind == TK_ID:
            self.matchToken(TK_ID, "TextureFilename")
            self.matchToken(TK_LBRACE)
            m.textureFilename = self.matchToken(TK_LITERAL_STRING)
            absPath = os.path.join(os.path.dirname(self.tokenizer.filePath), m.textureFilename)
            if os.path.isfile(absPath):
                try:
                    cTex = bpy.data.textures.new('Texture', type = 'IMAGE')
                    cTex.image = bpy.data.images.load(absPath)
                    
                    mtex = material.texture_slots.add()
                    mtex.texture = cTex
                    mtex.texture_coords = 'UV'
                    mtex.use_map_color_diffuse = True 
    #                mtex.use_map_color_emission = True 
    #                mtex.emission_color_factor = 0.5
    #                mtex.use_map_density = True 
    #                mtex.mapping = 'FLAT' 
                except:
                    print( "Cannot read image" )
            self.matchToken(TK_SEMICOLON)
            self.matchToken(TK_RBRACE)
    
        return material;

    def parseMaterial(self, mesh):
        self.matchToken(TK_ID, "Material")
        if self.lookahead.kind == TK_ID:
            self.matchToken(TK_ID)
        self.matchToken(TK_LBRACE)
        material = self.parseMaterialCore()
        self.matchToken(TK_RBRACE)
        mesh.materials.append(material)

    def parseMaterialOnTopLevel(self, name):
        material = self.parseMaterialCore()
        self.materialDict[name] = material

    def parseMeshMaterialList(self, mesh):
        val = self.matchToken(TK_LITERAL_NUM)
        nMaterials = int(val)
        self.matchToken(TK_SEMICOLON)
        val = self.matchToken(TK_LITERAL_NUM)
        nFaceIndexes = int(val)
        self.matchToken(TK_SEMICOLON)
    
        faceIndexes = []
        for i in range(nFaceIndexes):
            val = self.matchToken(TK_LITERAL_NUM)
            fi = int(val)
            if i < nFaceIndexes - 1:
                self.matchToken(TK_COMMA)
            faceIndexes.append(fi)
        self.matchToken(TK_SEMICOLON)
        if self.lookahead.kind == TK_SEMICOLON:
            self.matchToken(TK_SEMICOLON)
        
        while self.lookahead.kind == TK_ID or self.lookahead.kind == TK_LBRACE:
            if self.lookahead.kind == TK_LBRACE:
                self.matchToken(TK_LBRACE)
                matName = self.matchToken(TK_ID)
                mesh.materials.append(self.materialDict[matName])
                self.matchToken(TK_RBRACE)
            elif self.lookahead.value == "Material":
                self.parseMaterial(mesh)
            else:
                self.skipInstanceBlock()

        return faceIndexes

    def parseMeshNormals(self, meshData):
        meshData.normals = self.parseMeshCoords()
        meshData.faceNormals = self.parseMeshFaces()

    def parseMeshTextureCoords(self):
        val = self.matchToken(TK_LITERAL_NUM)
        nTextureCoords = int(val)
        self.matchToken(TK_SEMICOLON)
        texCoords = [(0.0, 0.0)]
        for i in range(nTextureCoords):
            u = self.parseFloat()
            self.matchToken(TK_SEMICOLON)
            v = self.parseFloat()
            self.matchToken(TK_SEMICOLON)
            if i < nTextureCoords - 1:
                self.checkSeparator()
            texCoords.append((u,1.0-v))
        self.checkSeparator()

        return texCoords
    
    def parseMeshSubInstance(self, meshData):
#        print(">" + self.lookahead.value)
        templateName = self.matchToken(TK_ID)
        if self.lookahead.kind == TK_ID:
            self.matchToken(TK_ID)
        
        self.matchToken(TK_LBRACE)
    
        if templateName == "MeshMaterialList":
            meshData.faceMaterialIndex = self.parseMeshMaterialList(meshData.mesh)
        elif templateName == "MeshNormals":
            self.parseMeshNormals(meshData)
        elif templateName == "MeshTextureCoords":
            meshData.texCoords = self.parseMeshTextureCoords()
        elif templateName == "MeshVertexColors":
            self.vertexColors = self.parseMeshVertexColors()
        else:
            self.skipInstanceBlock()
    
        self.matchToken(TK_RBRACE)
    
        return templateName
    
    def parseMeshInstance(self):
        meshName = "Mesh"
        
        me = bpy.data.meshes.new(meshName)
        meshData = MeshData(me)
        meshData.coords = [(0,0,0)] + self.parseMeshCoords()
        meshData.faces  = self.parseMeshFaces(1)
        
        hasVertexColors = False
        while self.lookahead.kind == TK_ID:
            template = self.parseMeshSubInstance(meshData)
            if template == "MeshVertexColors":
                hasVertexColors = True
        vnormals = None
        if meshData.normals != None and meshData.faceNormals != None:
            comb = set([])
            for vf, nf in zip(meshData.faces, meshData.faceNormals):
                for v, n in zip(vf, nf):
                    comb.add((v,n))
            comblist = list(comb)
            comblist.sort(key=lambda x: (x[0],x[1]))
            coords =[(0,0,0)]
            vnormals = [(1,0,0)]
            for c in comblist:
                coords.append(meshData.coords[c[0]])
                vnormals.append(meshData.normals[c[1]])
            faces = []
            for vf, nf in zip(meshData.faces, meshData.faceNormals):
                indices = []
                for v, n in zip(vf, nf):
                    index = comblist.index((v,n))
                    indices.append(index+1)
                faces.append(tuple(indices))
        else:
            coords = meshData.coords
            faces  = meshData.faces
        
        # create a mesh
        me.from_pydata(coords, [], faces)
        
        # set vertex normals if exist
        if vnormals != None and len(vnormals) == len(me.vertices):
            for i, v in enumerate(me.vertices):
                v.normal = vnormals[i]

        # set material index for each faces
        if meshData.faceMaterialIndex != None:
            for i in range(len(meshData.faces)):
                if i < len(meshData.faceMaterialIndex):
                    me.polygons[i].material_index = meshData.faceMaterialIndex[i]
                else:
                    me.polygons[i].material_index = meshData.faceMaterialIndex[-1]

        if meshData.texCoords != None:
            me.uv_textures.new("TextureCoords")
            uvs = me.uv_layers.active
            index = 0
            for face in meshData.faces:
                for vertexIndex in face:
                    vc = uvs.data[index]
                    vc.uv = meshData.texCoords[vertexIndex]
                    index += 1

        if meshData.vertexColors != None:
            vcol = me.vertex_colors.new("VertexColor")
            for i in range(len(meshData.faces)):
                vc = vcol.data[i]
#                fv = me.faces[i].vertices
                fv = meshData.faces[i]
                vc.color1 = meshData.vertexColors[fv[0]][0:3]
                vc.color2 = meshData.vertexColors[fv[1]][0:3]
                vc.color3 = meshData.vertexColors[fv[2]][0:3]
                vc.color4 = meshData.vertexColors[fv[3]][0:3]

        me.update()
        
        if hasVertexColors:
            for m in me.materials:
                m.use_shadeless = True
    
        # Not to depend on the order in which MeshMaterialList or MeshTextureCoords tags appears,
        # this work must be here.
        if "TextureCoords" in me.uv_textures.keys():
            uvs = me.uv_textures["TextureCoords"]
            for i in range(len(me.polygons)):
                if me.materials[me.polygons[i].material_index].texture_slots[0]:
                    uvs.data[i].image = me.materials[me.polygons[i].material_index].texture_slots[0].texture.image
    
        for material in me.materials:
            material.game_settings.alpha_blend = "ALPHA"

        me.update()
    
        return me;
    
    def parseFrameInstance(self, objectName):
        frameMatrix = Matrix()
        frameMatrix.identity()
        me = None
        children = []
        while self.lookahead.kind == TK_ID:
            subInstName = self.matchToken(TK_ID)
            name = None
            if self.lookahead.kind == TK_ID:
                name = self.matchToken(TK_ID)
            self.matchToken(TK_LBRACE)
    
#            print(subInstName + " at " + str(self.tokenizer.lineno))
    
            if subInstName == "FrameTransformMatrix":
                matrix = []
                for i in range(16):
                    e = self.parseFloat()
                    matrix.append(e)
                    if i < 15:
                        self.matchToken(TK_COMMA)
                self.matchToken(TK_SEMICOLON)
                self.matchToken(TK_SEMICOLON)
                row1 = matrix[0:4]
                row2 = matrix[4:8]
                row3 = matrix[8:12]
                row4 = matrix[12:16]
                frameMatrix = Matrix((tuple(row1), tuple(row2), tuple(row3), tuple(row4)))
                frameMatrix.transpose()
                if self.config.CoordinateSystem == 1:
                    sc = Matrix.Scale(-1, 4, Vector((0.0, 0.0, 1.0)))
                    frameMatrix = sc  * frameMatrix * sc
                if self.config.UpwardAxis == 1:
                    frameMatrix = Matrix(((1,0,0,0),(0,0,-1,0),(0,1,0,0),(0,0,0,1))) * frameMatrix * Matrix(((1,0,0,0),(0,0,1,0),(0,-1,0,0),(0,0,0,1)))
            elif subInstName == "Mesh":
                me = self.parseMeshInstance()
            elif subInstName == "Frame":
                c = self.parseFrameInstance(name)
                children.append(c)
            else:
                self.skipInstanceBlock()
            self.matchToken(TK_RBRACE)
        if not me is None:
            ob = bpy.data.objects.new("Frame", me)
            bpy.context.scene.objects.link(ob)
            ob.select = True
            bpy.context.scene.objects.active = ob
            bpy.context.tool_settings.mesh_select_mode = (True, False, False)
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action = 'DESELECT')
            bpy.ops.object.mode_set(mode='OBJECT')
            me.vertices[0].select = True
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.delete(type='VERT')
            bpy.ops.object.mode_set(mode='OBJECT')
        else:
            ob = bpy.data.objects.new("Frame", None)
            bpy.context.scene.objects.link(ob)
        if objectName != None:
            ob.name = objectName
        ob.matrix_local = frameMatrix
        for c in children:
            c.parent = ob
    
        return ob
    
    def parseInstanse(self):
        instName = None
#        print(self.lookahead.value)
        templateName = self.matchToken(TK_ID)
        if self.lookahead.kind == TK_ID:
            instName = self.matchToken(TK_ID)
        
        self.matchToken(TK_LBRACE)
    
        if templateName == "Mesh":
            me = self.parseMeshInstance()
            ob = bpy.data.objects.new("Frame", me)
            bpy.context.scene.objects.link(ob)
            
            ob.select = True
            bpy.context.scene.objects.active = ob
            bpy.context.tool_settings.mesh_select_mode = (True, False, False)
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action = 'DESELECT')
            bpy.ops.object.mode_set(mode='OBJECT')
            me.vertices[0].select = True
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.delete(type='VERT')
            bpy.ops.object.mode_set(mode='OBJECT')
        elif templateName == "Frame":
            self.parseFrameInstance(instName)
        elif templateName == "Material":
            self.parseMaterialOnTopLevel(instName)
        elif templateName == "Header":
            self.skipInstanceBlock()
        else:
            self.skipInstanceBlock()
    
        self.matchToken(TK_RBRACE)
    
    def readXFile(self):
        self.parseFileHeader()
    
        while self.lookahead.kind == TK_ID and self.lookahead.value == "template":
            self.parseTemplateDef()
    
        while self.lookahead.kind == TK_ID:
            self.parseInstanse()
    
        self.tokenizer.shutdown()
    
        if bpy.ops.object.shade_smooth.poll():
            bpy.ops.object.shade_smooth()

########

CoordinateSystems = (
    ("1", "Left-Handed", ""),
    ("2", "Right-Handed", ""),
    )

UpAxisSelect = (
    ("1", "Y-axis up", ""),
    ("2", "Z-axis up", ""),
    )

def importXFile(filepath, config):
    fileName = os.path.expanduser(filepath)
    if fileName:
        (shortName, ext) = os.path.splitext(fileName)
        if ext.lower() != ".x":
            print("Error: Not a x file: " + fileName)
            return
        parser = Parser(fileName, config)
        parser.readXFile()
        bpy.context.scene.update()
        print("Done")
        return
    print("Error: Not a x file: " + filepath)
    return

class IMPORT_OT_directx_x(bpy.types.Operator):
    '''Import from X file format (.x)'''
    bl_idname = "import_scene.directx_x"
    bl_description = 'Import from X file format (.x)'
    bl_label = "Import DirectX"
#    bl_space_type = "PROPERTIES"
#    bl_region_type = "WINDOW"
    bl_options = {'UNDO'}
    
    files = CollectionProperty(type=bpy.types.OperatorFileListElement, options={'HIDDEN', 'SKIP_SAVE'})
    directory = StringProperty(maxlen=1024, subtype='FILE_PATH', options={'HIDDEN', 'SKIP_SAVE'})
    filter_glob = StringProperty(default="*.x", options={'HIDDEN'})

    #Coordinate System
    CoordinateSystem = EnumProperty(
        name="Src System",
        description="Select a coordinate system to import from",
        items=CoordinateSystems,
        default="1")

    UpwardAxis = EnumProperty(
        name="Src Up-Axis",
        description="Select a upward vector to import from",
        items=UpAxisSelect,
        default="1")

    def execute(self, context):
        config = ImportSettings(
                    CoordinateSystem=self.CoordinateSystem,
                    UpwardAxis=self.UpwardAxis
                 )
        for file in self.files:
            try:
                importXFile(self.directory + "/" + file.name, config)
            except:
                print("import '" + self.directory + "/" + file.name + "' failed")
        return {'FINISHED'}

    def invoke(self, context, event):
        wm = context.window_manager
        wm.fileselect_add(self)
        return {'RUNNING_MODAL'}

def menu_func(self, context):
    self.layout.operator(IMPORT_OT_directx_x.bl_idname, text="DirectX (.x)")

def register():
    bpy.utils.register_module(__name__)

    bpy.types.INFO_MT_file_import.append(menu_func)

def unregister():
    bpy.utils.unregister_module(__name__)

    bpy.types.INFO_MT_file_import.remove(menu_func)

if __name__ == "__main__":
    register()
