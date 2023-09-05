# StimPack
Open-source, neuroscience-forward suite for precise stimulus presentation

### I. What is it?

### II. Requirements

### III. Installation

### IV. Example Working System
#####  IVa. Setup computer
- Install Ubuntu 22.04 on a fresh computer
- Check whether you are running Wayland or Xorg
  - Go to Settings>About and look at the Window Manager
  - If Wayland, log out, and log backin using Gnome Xorg
-  `sudo apt-get update && sudo apt-get install python3.10-virtualenv`
- Make a virtualenv `python3 -m venv (your virtualenvironment path here)`
- `source (your virtualenvironment path here)/bin/activate`

#####  IVb. Install stimulus packages
- Download `github.com/clandininlab/stimpack` locally
- In the terminal, `cd /(your install path here)/stimpack` and install stimpack
- `pip3 install .` 
- `stimpack`
>[~NOTE]
> If you receive an error referencing "xcb", try the following:
> `sudo apt-get upgrade && sudo apt-get update && sudo apt-get install -y libxcb-cursor-dev`
> `stimpack`

#####  IVc. Setup `labpack` directory
**Next, download `github.com/clandininlab/labpack` and use it as a starting-point for your own custom stimpack suite**

### V. Labpack
