"""
Stimulus classes.

Each class is is derived from stimpack.visual_stim.base.BaseProgram, which handles the GL context and shader programs

"""

from PIL import Image
import numpy as np
from stimpack.visual_stim.base import BaseProgram
from stimpack.visual_stim.trajectory import make_as_trajectory, return_for_time_t
from stimpack.visual_stim import shapes
from stimpack.visual_stim import util
import copy

class ShowImage(BaseProgram):
    def __init__(self, screen):
        super().__init__(screen=screen, num_tri=14000)
        
        self.use_texture=True
        self.rgb_texture=True

    def configure(self, image_path, horizontal_extent=360, vertical_extent=180, rotate=0):
        # image = np.zeros((200,400,3))
        image = Image.open(image_path)
        image = np.array(image)
        
        image = image.astype(np.uint8)
        image = image[:,:,:3]
        
        self.rgb_texture=True



        n_steps=32

        self.add_texture_gl(image, texture_interpolation='NEAREST')

        self.stim_object = shapes.GlSphericalTexturedRect(height=vertical_extent, width=horizontal_extent, sphere_radius=1,
                                                                n_steps_x = n_steps, n_steps_y = n_steps, 
                                                                color=[1,1,1,1], texture=True).rotate(np.radians(rotate),0,0)


        self.update_texture_gl(image)
    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        pass
        # rotation = 0.2
        # self.stim_object = self.stim_object.rotate(np.radians(rotation),0,0)

        
