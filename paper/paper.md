---
title: 'stimpack: a modular framework for precise multisensory stimulus generation in systems neuroscience'
tags:
  - Python
  - systems neuroscience
  - visual stimulation
  - auditory stimulation
  - virtual reality
  - closed-loop behavior
  - psychophysics
authors:
  - name: Minseung Choi
    orcid: 0000-0001-5398-219X
    corresponding: true
    affiliation: 1
  - name: Joshua B. Melander
    affiliation: 1
  - name: Steven G. Herbst
    orcid: 0000-0001-7128-9014
    affiliation: 2
  - name: Carl Wienecke
    affiliation: "1, 3"
  - name: Heberto Mayorquin
    orcid: 0000-0002-5937-7537
    affiliation: 4
  - name: Alex Y. Hao
    orcid: 0000-0002-3454-5733
    affiliation: 1
  - name: Manze Zhang
    orcid: 0009-0004-8899-4667
    affiliation: 1
  - name: Jacob Simon
    orcid: 0000-0001-7683-9839
    affiliation: 1
  - name: Bella E. Brezovec
    orcid: 0000-0001-9341-3565
    affiliation: 1
  - name: Shaul Druckmann
    orcid: 0000-0003-0068-3377
    affiliation: 1
  - name: Stephen A. Baccus
    orcid: 0000-0001-8692-5685
    affiliation: 1
  - name: Thomas R. Clandinin
    orcid: 0000-0001-6277-6849
    equal-contrib: true
    affiliation: 1
  - name: Maxwell H. Turner
    orcid: 0000-0002-4164-9995
    corresponding: true
    equal-contrib: true
    affiliation: "1, 5"
affiliations:
  - name: Department of Neurobiology, Stanford University, United States
    index: 1
  - name: Department of Electrical Engineering, Stanford University, United States
    index: 2
  - name: Harvard Medical School, United States
    index: 3
  - name: CatalystNeuro, United States
    index: 4
  - name: Department of Biological Sciences, University at Albany, SUNY, United States
    index: 5
date: 12 August 2026
bibliography: paper.bib
---

# Summary

A central goal of neuroscience is to understand how animals engage with the natural world. Studying this experimentally requires the ability to present stimuli that capture the complexity of dynamic sensory inputs during animal behavior. But performing such experiments across labs, and interpreting the resulting data, can be challenging because doing so requires highly flexible and precisely defined stimuli that can be synchronized with other measurement tools, and can be reconstructed to facilitate data analysis.

To address these challenges, we introduce `stimpack`, a Python framework for open- and closed-loop stimulus delivery in neuroscience experiments. `stimpack` is a hardware-agnostic stimulus rendering environment where a single protocol drives perspective-corrected displays across any number and arrangement of screens, sound playback, analog outputs (e.g. optogenetic stimulation, odor delivery, or reward), and closed-loop position updates. Stimuli and devices are **modules** addressed by name over a remote-procedure-call layer, and one protocol call can invoke several modules at once. Data are written through pluggable backends, including the neuroscience community standard Neurodata Without Borders (NWB) [@rubel2022].

Everything specific to a laboratory or experimental setup (e.g. screen geometry, hardware drivers, stimulus definitions) lives in a lab- or user-specific `labpack` outside the installed package, discovered at runtime from a configuration file. One protocol library runs across rigs with different screen geometries and hardware, allowing experiments to be replicated precisely across rigs and laboratories.

# Statement of need

Existing software packages for parametric psychophysics make naturalistic, behavior-coupled stimuli difficult to implement, while packages designed for three-dimensional virtual environments make precise parameterization and replication across rigs challenging. `stimpack` was designed for laboratories that position visual displays around a head-fixed or tethered animal and couple the outputs of these displays to animal behavior in closed loop. In this context, `stimpack` satisfies three important requirements. First, with `stimpack` the same visual stimulus can be shown across different presentation geometries, including setups with multiple displays or curved screens. Second, the same package can coordinate multisensory stimulus delivery, closed-loop control, and analog device control, allowing these devices to be synchronized precisely. Finally, acquired data (e.g. physiological recordings, functional imaging, behavior tracking) can be attached to the data files produced by `stimpack` using a wide array of existing tools in the NWB ecosystem.

# State of the field

We created `stimpack` to fill a gap by enabling flexible display geometries, native closed-loop control, modular device handling, and simple yet powerful stimulus design. Existing software packages for experiment control and visual stimulus delivery typically satisfy some, but not all, of these requirements.

Some visual display packages were built for **precise parametric control of a stimulus shown to a participant**. These packages tend to make it easy to design visual stimuli, but can be difficult to extend to new screen geometries or incorporate closed-loop control based on behavioral feedback. For example, Psychtoolbox [@brainard1997; @pelli1997] and PsychoPy [@peirce2019] are designed around a display viewed roughly head-on, not around several surfaces at arbitrary orientations, and cannot readily be coupled to movement. A similar static-observer display model persists in tools for head-fixed physiology such as MonkeyLogic, PLDAPS, MWorks, and Rigbox [@hwang2019; @eastman2012; @mworks; @bhagat2020], as well as in the Python packages Vision Egg [@straw2008] and QDSpy [@franke2019].

Other software packages have been purpose-built for specific use cases that involve **closed-loop control in a virtual environment**. These packages, while often delivering good performance, are often designed with specific hardware setups or requirements.
For example, Stytra [@stih2019] and vxPy [@vxpy] were designed around a single preparation (larval zebrafish) while FreemoVR [@stowers2017] extended similar functionality to freely moving animals. Modular, custom LED arenas designed for work in fruit flies [@reiser2008; @isaacson2022] reach kilohertz binary frame rates with specific hardware requirements and a fixed geometry and resolution. Each of these packages allows for closed-loop control of parameterized stimuli, but not for rig-agnostic display geometry.

The existing packages that are most similar to `stimpack` can be extended to **diverse display types and geometries**. For example, ViRMEn [@aronov2014] and BonVision [@lopes2021] allow for curved display geometry, including conical and spherical screens. Bonsai [@lopes2015] handles closed-loop control and mixed devices, but trial structure and logging are left to the workflow's author, and rig calibration is embedded in the workflow itself. However, a `stimpack` protocol is a `diff`-able Python class whose parameters sweep across trials and land in NWB. Outside these purposes sit the game engines, which supply worlds rather than calibrated parametric stimuli [@brookes2020; @shapcott2025], and ratcave [@delgrosso2019], which supplies the projection mathematics alone.

`stimpack` satisfies all these requirements, with a focus on a flexible architecture. Everything rig-specific is configured in a per-laboratory `labpack` rather than inside experiment code, so one protocol can be used across rigs and preparations. Similarly, metadata are trial-parameterized with provenance in HDF5 or NWB, an export structure that is not implemented as standard within any other stimulus generating system. No existing package combines observer-centered perspective correction across an arbitrary number of flat screens and curved surfaces in one rig, closed-loop coupling to a tracker of the laboratory's choosing, and non-visual outputs (sound, analog control) addressed from the same protocol.

# Software design

## One module per capability

In `stimpack`, an experiment runs as a **client**, which executes the protocol and writes metadata to the data file, and a **server**, which controls hardware devices, including display screens, as a set of modules. One command from the client can control several modules at once (\autoref{fig:architecture}). Four modules, defined by the capability rather than a particular device, are included in `stimpack`: `visual`, which controls visual stimulus rendering and display; `audio`, which plays sound stimuli through a sound card; `locomotion`, which handles locomotion-related behavior data for closed-loop feedback; and `voltage_out`, which can be used to send voltage waveforms to control devices (e.g. optogenetics, odor delivery, reward). This modular design choice allows a shared protocol library to run on rigs whose hardware may differ.

![
**stimpack's architecture.** A protocol names the module each call is for, and the server routes it there. Inputs update a subject state that outputs follow, so the closed loop does not pass through the client. Stacked cards are extension points: a new capability is a new module rather than a change to the core.
\label{fig:architecture}](figures/architecture.pdf){ width=100% }

## Visual module

Displays and screen devices are defined in the server code, which includes a description of the screen geometry relative to the observer. Built-in stimuli range from parametric primitives to natural movies. Stimulus shapes can be painted with monochrome or RGB textures for stimuli like gratings, spatiotemporal white noise, or movie frames. Layering, masking, and aperturing of stimuli can be achieved by a combination of alpha blending and rendering surfaces in front of or behind one another.

The `visual` module supports two display geometries that have separate rendering paths. **Flat screens** are described by their corner locations (in meters), and each stimulus is rendered per subscreen (one perspective view per flat surface) through a generalized off-axis perspective projection [@kooima2009], so an object subtends the angle it should from where the subject sits. **Curved screens** (e.g. a hemisphere or a cylinder) cannot be described by a flat projection frustum, so rendering happens in two steps. The scene is first rendered into a cube map centered on the subject, capturing what the subject should see in every direction. The screen's mesh is drawn in display device (e.g. projector) coordinates, and each output pixel samples the cube along the direction of the screen point it shows (\autoref{fig:pipeline}).

The `visual` module can support most computer display devices. Temporal multiplexing packs up to three stimulus timepoints into the color channels of each output frame, so a 120 Hz video signal can drive a 360 Hz monochrome display, approaching the temporal regime of specialized LED hardware [@reiser2008]. During stimulus presentation, a small square in the corner of the display inverts on every rendered frame to enable accurate synchronization with other recorded data and detection of dropped frames (\autoref{fig:pipeline}d).

![
**Visual stimulus path on an example setup.**
(a) The rig: a projector lights a hemispherical screen around the subject, and a photodiode watches the corner of the thrown frame.
(b) The frame sent to the projector, warped by the screen's geometry, with the synchronization square in the corner.
(c) The subject's visual field: the checkerboard's patches are regular in the subject's angular coordinates.
(d) Frame delivery at the photodiode: nominal inversions every 8.3 ms (120 Hz), and two dropped frames, one leaving the square held bright and one held dark, each a level held for 16.6--16.7 ms.
\label{fig:pipeline}](figures/pipeline.pdf){ width=100% }

## Audio, locomotion, and voltage output modules

The `audio` module drives a sound card. A protocol addresses it exactly as it addresses the screens, naming a sound class whose waveform is rendered when the trial loads and played when the trial starts. For locomotion-based closed-loop control, lab-defined protocol code supplies a control function, which the server calls on every tracker update with the full subject state (position, orientation, and any laboratory-defined fields measured through `labpack`-defined trackers). The same hook lets a trial end on what the animal did, with the reason recorded. The voltage-output module supplies the dispatch; the calls themselves (steps, waveform streams, acquisition triggers) are defined and implemented by the `labpack`'s DAQ driver.

## Protocols, data, and the interface

A protocol is a Python class in the `labpack` that declares the parameters of a run and of the stimulus. Named presets can be saved and loaded to standardize protocol parameter sets. Users can also run an ensemble, which is a saved queue of protocols. Data are written through pluggable backends: HDF5 by subject, series, and trial, with parameters at each level, or NWB [@rubel2022], the community standard. `stimpack` includes a GUI that is a shell over these objects and identical on every rig (\autoref{fig:gui}).

## Extensibility

`stimpack` is extensible at every layer. Stimulus classes load from the `labpack` at runtime and are addressed exactly as built-ins; data backends, trackers, and DAQ drivers are likewise `labpack` code. A new capability (e.g. a novel sensor or effector) is a three-line subclass of the same module base class the built-ins inherit, registered with the server.

![
**The experiment GUI, identical on every rig.** Left: the Main tab mid-run. Parameter fields are built from the protocol class's own declarations; the list-valued angle sweeps across trials in randomized order, and the bottom panel shows the current trial's draw from that list. Right: the Subject tab, whose metadata fields beyond the built-ins are declared in the labpack's config.
\label{fig:gui}](figures/gui.png){ width=100% }

# Research impact statement

`stimpack` consolidates four earlier Clandinin lab packages: `flystim` (perspective-corrected rendering), `flyrpc` (client--server messaging), `visprotocol` (protocols, metadata, GUI), and `multistim` (auditory stimulation). None has been described in an archival publication, and every author of those packages is an author here. The subscreen geometry is based on `flystim`'s. The curved-screen path was checked against `flymax`, an earlier MATLAB-based hemisphere-projector display in the lab, and its measured photometry. Predecessor versions underlie published work on fly visual processing and behavior [@turner2022; @mano2023; @currier2025], the most recent of which names `flystim`, `visprotocol`, and `stimpack` itself.
The consolidation brought the modular architecture described above, improvements throughout each module, and three shifts in particular. First, the viewer became a **subject with state**, which can be sent to every module, so one protocol can be used for a fly on a ball or a mouse on a treadmill. Second, **closed-loop control moved into the render loop**. Third, **laboratory-specific code left the core package**. Whereas `visprotocol` included lab-specific protocols and hardware drivers in its core, `stimpack` contains a generic core, and lab-specific code is housed in a `labpack`. `stimpack` is in use in ongoing *Drosophila* experiments in the Clandinin (Stanford), Turner (Albany), and Murthy (Princeton) laboratories, and in mouse work in the Baccus and Mitra laboratories (Stanford), including retina-to-cortex recordings [@weddington2026].

# AI usage disclosure

All primary architectural design decisions and implementations were made by authors. Generative AI (Claude Opus 4.8, Opus 5, and Fable 5 from Anthropic) was used for parts of code generation and editing (multisample anti-aliasing, curved screen, audio module, experiment GUI elements), code merging (curved screen, NWB data), documentation, testing scaffolding, and manuscript revision. Authors thoroughly reviewed, modified, and validated all AI-generated content.

# Acknowledgements

We thank the Clandinin, Turner, Baccus, Mitra, and Murthy Labs for testing across rigs and preparations. This work was supported by Stanford Graduate Fellowships (MC, SGH), a DoD NDSEG Fellowship (MC), a Hertz Fellowship (SGH), and NIH grants R00-EY032549, R01-EY022638, R01-EY022933, R01-EY025087, and P30-EY026877.

# References
