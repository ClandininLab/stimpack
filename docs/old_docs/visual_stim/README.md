# stimpack.visual_stim

**stimpack.visual_stim** is a software package for generating visual stimuli for neuroscience experiments. It was originally designed for fly labs, but can be used for any subject/viewer.  The stimuli are perspective-corrected and can be displayed across multiple screens.  Sample code, illustrating various use cases, is included in the **examples** directory.

# Prerequisites

# Running the Example Code

In a terminal tab, navigate to the examples directory and run one of the sample programs, such as **show_all.py**.

```shell
> cd stimpack.visual_stim/examples
> python show_all.py
```

Each example can be exited at any time by pressing Ctrl+C.

# Coordinate system
The coordinate system convention in stimpack.visual_stim is defined as follows:
* Yaw = rotation around the Z axis (theta)
* Pitch = rotation around the X axis (phi)
* Roll = rotation around the Y axis

A fly heading of (yaw=0, pitch=0, roll=0) corresponds to the fly looking down the +Y axis, the +X axis lies to the fly's right side, and +Z lies above the fly's head

## Screen objects and defining subscreen geometry

A **Screen** object specifies a display device and a list of **SubScreens**, each **SubScreen** is defined by:
1. Physical coordinates ( (x, y, z), in meters) that specify the screen geometry in 3D space

2. Normalized Device Coordinates ( (x, y), [-1, +1]) ) that specify a viewport for that SubScreen. This controls where on the display device the image for this SubScreen will appear. 
