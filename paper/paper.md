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
    orcid: 0000-0001-9673-0224
    affiliation: 1
  - name: Steven G. Herbst
    orcid: 0000-0001-7128-9014
    affiliation: 2
  - name: Carl F.R. Wienecke
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
  - name: Jacob C. Simon
    orcid: 0000-0001-7683-9839
    affiliation: 1
  - name: David D. Au
    orcid: 0000-0002-0248-5385
    affiliation: 1
  - name: Bella E. Brezovec
    orcid: 0000-0001-9341-3565
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
  - name: Department of Neurobiology, Harvard Medical School, United States
    index: 3
  - name: CatalystNeuro, United States
    index: 4
  - name: Department of Biological Sciences, University at Albany, SUNY, United States
    index: 5
date: 14 August 2026
bibliography: paper.bib
---

# Summary

A central goal of neuroscience is to understand how animals engage with the natural world. Studying this experimentally requires the ability to present stimuli that capture the complexity of dynamic sensory inputs during animal behavior. But performing such experiments across labs, and interpreting the resulting data, can be challenging because doing so requires highly flexible and precisely defined stimuli that can be synchronized with other measurement tools, and can be reconstructed to facilitate data analysis.

To address these challenges, we introduce `stimpack`, a Python framework for open- and closed-loop stimulus delivery. `stimpack` is a hardware-agnostic stimulus rendering environment where a single protocol drives perspective-corrected displays across any number and arrangement of screens, sound playback, analog outputs (e.g. optogenetic stimulation, odor delivery, or reward), and closed-loop position updates. Stimuli and devices are **modules** addressed by name over a remote-procedure-call layer, and one protocol call can invoke several modules at once. Data are written through pluggable backends, including the neuroscience community standard Neurodata Without Borders (NWB) [@teeters2015; @rubel2022].

Everything specific to a laboratory or experimental setup (e.g. screen geometry, hardware drivers, stimulus definitions) is coded in a lab- or user-specific `labpack` outside the installed package, discovered at runtime from a configuration file. One protocol library runs across rigs with different screen geometries and hardware, allowing experiments to be replicated precisely across laboratories.

# Statement of need

Existing software packages for parametric psychophysics make naturalistic, behavior-coupled stimuli difficult to implement, while packages designed for three-dimensional virtual environments make precise parameterization challenging. `stimpack` was designed for laboratories that position visual displays around a head-fixed or tethered animal and couple the outputs of these displays to animal behavior in closed loop. In this context, `stimpack` satisfies three important requirements. First, with `stimpack` the same visual stimulus can be shown across different presentation geometries, including setups with multiple displays or curved screens. A stimulus can be specified in terms of visual angles relative to the subject, as in parametric psychophysics, or specified by Euclidean positions and sizes, as in a virtual environment. In either case, each display renders the stimulus at perspective-corrected angles (\autoref{fig:pipeline}) such that quantities measured against the stimulus, from receptive fields to speed tuning, emerge in the correct angular coordinates on any rig. Second, the same package can coordinate multisensory stimulus delivery, closed-loop control, and analog device control, allowing these devices to be synchronized precisely. Finally, `stimpack`'s files are valid NWB, so acquired data (e.g. physiological recordings, functional imaging, behavior tracking) can be added with `pynwb` or NeuroConv [@mayorquin2025], browsed with Neurosift [@magland2024], and archived on DANDI.

# State of the field

We created `stimpack` to fill a gap by enabling flexible display geometries, native closed-loop control, modular device handling, and simple yet powerful stimulus design. Existing software packages for experiment control and visual stimulus delivery typically satisfy some, but not all, of these requirements.

Some visual display packages were built for **precise parametric control of a stimulus shown to a participant**. These packages make it easy to design visual stimuli, but can be difficult to extend to new screen geometries or incorporate closed-loop control based on behavioral feedback. For example, Psychtoolbox [@brainard1997; @pelli1997] and PsychoPy [@peirce2019] are designed around a display viewed roughly head-on, not around several surfaces at arbitrary orientations, and cannot readily be coupled to movement. A similar static-observer display model underlies tools for head-fixed physiology such as MonkeyLogic, PLDAPS, MWorks, and Rigbox [@hwang2019; @eastman2012; @mworks; @bhagat2020], as well as in the Python packages Vision Egg [@straw2008] and QDSpy [@franke2019].

Other software packages have been purpose-built for use cases that involve **closed-loop control in a virtual environment**. These packages, while often delivering good performance, are often designed with specific hardware setups or requirements. For example, Stytra [@stih2019] and vxPy [@vxpy] have been used for a single preparation (larval zebrafish) while FreemoVR [@stowers2017] extended similar functionality to freely moving animals. Modular, custom LED arenas designed for work in fruit flies [@reiser2008; @isaacson2022] reach kilohertz binary frame rates with specific hardware requirements and a fixed geometry and resolution. Each of these packages allows for closed-loop control of parameterized stimuli, but does not directly support transferring experimental specifications to other rig geometries. 

The existing packages that are most similar to `stimpack` can be extended to **diverse display types and geometries**. For example, ViRMEn [@aronov2014] and BonVision [@lopes2021] allow for curved displays, including conical and spherical screens. Bonsai [@lopes2015] handles closed-loop control and mixed devices, but trial structure and logging are left to the workflow's author, and rig calibration is embedded in the workflow itself. However, a `stimpack` protocol is a `diff`-able Python class whose parameters sweep across trials and can be stored in NWB. Finally, game engines like Unity or Unreal that have been used in neuroscience supply worlds rather than calibrated parametric stimuli, whether used directly [@jangraw2014] or wrapped for dome projection [@shapcott2025].

`stimpack` satisfies all these requirements, with a focus on a flexible architecture. Everything rig-specific is configured in a laboratory-specific `labpack` rather than inside experiment code, so **one protocol can be used across rigs and preparations**. To our knowledge, no existing package combines observer-centered perspective correction across an arbitrary number of flat screens and curved surfaces in one rig, closed-loop coupling to any locomotor tracker, non-visual outputs (sound, analog control) addressed from the same protocol, and trial-parameterized metadata saved in a community data standard by default.

# Software design

## One module per capability

In `stimpack`, an experiment runs as a **client**, which executes the protocol and writes metadata to the data file, and a **server**, which controls hardware devices, including display screens, as a set of modules. One command from the client can control several modules at once (\autoref{fig:architecture}). Four modules, defined by the capability rather than a particular device, are included in `stimpack`: `visual`, which controls visual stimulus rendering and display; `audio`, which plays sound stimuli through a sound card; `locomotion`, which handles locomotion-related behavior data for closed-loop feedback; and `voltage_out`, which can send voltage waveforms to control devices (e.g. optogenetics, odor delivery, reward). This modular design choice allows a shared protocol library to run on rigs whose hardware may differ.

![
**stimpack's architecture.** A protocol names the module for each call, and the server routes it. Inputs update a subject state that outputs follow, such that the closed loop does not pass through the client. Stacked cards are extension points: a new capability is a new module, not a change to the core. 
\label{fig:architecture}](figures/architecture.pdf){ width=100% }

## Visual module

Displays are defined in the server code, which includes a description of the screen geometry relative to the observer. Built-in stimuli range from parametric primitives to natural movies. Stimulus shapes can be painted with monochrome or RGB textures for stimuli like gratings, spatiotemporal white noise, or movie frames. Layering, masking, and aperturing of stimuli can be achieved by a combination of alpha blending and rendering surfaces with depth.

The `visual` module supports two display geometries that have separate rendering paths. **Flat screens** are described by their corner locations (in meters), and each stimulus is rendered per subscreen (one perspective view per flat surface) through a generalized off-axis perspective projection [@kooima2009], so an object subtends the angle it should from where the subject sits. **Curved screens** (e.g. a hemisphere or a cylinder) cannot be described by a flat projection frustum, so rendering happens in two steps. The scene is first rendered into a cube centered on the subject, capturing what the subject should see in every direction. The screen's mesh is drawn in display device (e.g. projector) coordinates, and each output pixel samples the cube along the direction of the screen point it shows (\autoref{fig:pipeline}).

The `visual` module supports most computer display devices. Temporal multiplexing packs up to three stimulus timepoints into the color channels of each output frame, so a 120 Hz video signal can drive a 360 Hz monochrome display, approaching the temporal regime of specialized LED hardware [@reiser2008]. During stimulus presentation, a small square in the corner of the display inverts on every rendered frame to enable accurate synchronization with other recorded data and to enable detection of dropped frames (\autoref{fig:pipeline}d). 

![
**One stimulus specification, three display geometries, one visual experience.**
(a) Three rigs, to scale: one monitor; two monitors meeting ahead of the subject; a hemispherical screen lit by a projector. Red: the photodiode at each display's synchronization square.
(b) The frames `stimpack` sends to the displays for one specified scene -- a 10° checkerboard left of azimuth zero, and a 360° photograph right of it: `stimpack` warps the images according to the specification of each display.
(c) The subject's visual field: the color seen in each direction is read off the delivered frame, at the display point visible in that direction. Grey marks directions with no display surface; faint outlines trace the coverages of the other two rigs for comparison across rows.
(d) Frame delivery at the photodiode: nominal inversions every 8.3 ms (120 Hz), and two dropped frames, one held bright and one held dark.
\label{fig:pipeline}](figures/pipeline.pdf){ width=100% }

## Audio, locomotion, and voltage output modules

The `audio` module drives a sound card. A protocol addresses the sound card in the same way that the screens are addressed, naming a sound class whose waveform is rendered when the trial loads and played when the trial starts. For locomotion-based closed-loop control, lab-defined protocol code supplies a control function, which the server calls on every tracker update with the full subject state (position, orientation, and any laboratory-defined fields measured through `labpack`-defined trackers). The same interface lets a trial end on what the animal did, with the reason recorded. The voltage-output module supplies the dispatch; the calls themselves (steps, waveform streams, acquisition triggers) are defined and implemented by the `labpack` DAQ driver.

## Protocols, data, and the interface

A protocol is a Python class in the `labpack` that declares the parameters of a run and of the stimulus. Named presets can be saved and loaded to standardize protocol parameter sets. Users can also run an ensemble, which is a saved queue of protocols. Data are written through pluggable backends: HDF5 by subject, series, and trial, with parameters at each level, or NWB [@teeters2015;@rubel2022], the community standard. `stimpack` includes a GUI that is a shell over these objects and identical on every rig (\autoref{fig:gui}).

![
**From protocol code to a running experiment.** Left: the `AudiovisualPairing` protocol, abridged, and the module calls that `stimpack` makes from its descriptors on each trial -- one `load_stim` per descriptor, routed by target; one start for both modalities; the timing declarations pacing the trial. Right: the GUI's Main tab mid-run, its parameter fields built from the class's own declarations. The list-valued `freq` (solid red box) sweeps across trials in randomized order, and "This trial" shows the current draw (dashed red boxes), here reaching the audio module.
\label{fig:gui}](figures/gui_code.pdf){ width=100% }

## Extensibility

`stimpack` is extensible at every layer. Stimulus classes load from the `labpack` at runtime and are addressed exactly as built-ins; data backends, trackers, and DAQ drivers are likewise `labpack` code. A new capability (e.g. a novel sensor or effector) is a three-line subclass of the same module base class the built-ins inherit, registered with the server.

# Research impact statement

`stimpack` consolidates four earlier Clandinin lab packages: `flystim` (perspective-corrected rendering), `flyrpc` (client--server messaging), `visprotocol` (protocols, metadata, GUI), and `multistim` (auditory stimulation). None has been described in an archival publication, and every author of those packages is an author here. The subscreen geometry is based on that of `flystim`. The curved-screen path was checked against `flymax`, an earlier MATLAB-based hemisphere-projector display in the lab, and its measured photometry. Predecessor versions underlie published work on fly visual processing and behavior [@turner2022; @mano2023; @currier2025], the most recent of which names `flystim`, `visprotocol`, and `stimpack` itself. In addition, `stimpack` has been used to reconstruct spatiotemporal receptive fields in mouse retina and visual cortex [@au2026; @weddington2026], including the example in \autoref{fig:v1_sta_rf}.
The consolidation brought the modular architecture described above, improvements throughout each module, and three specific shifts. First, the viewer became a **subject with state**, which can be sent to every module, so one protocol can be used for a fly on a ball or a mouse on a treadmill. Second, **closed-loop control moved into the render loop**. Third, **laboratory-specific code left the core package**. Whereas `visprotocol` included lab-specific protocols and hardware drivers in its core, `stimpack` contains a generic core, and lab-specific code is housed in a `labpack`. `stimpack` is in use in ongoing *Drosophila* experiments in the Clandinin (Stanford), Turner (Albany), and Murthy (Princeton) laboratories, and in mouse work in the Baccus and Mitra laboratories (Stanford).

![
**Spatiotemporal receptive field (STRF) of a mouse primary visual cortex neuron.** The STRF of a cortical neuron recorded with a Neuropixels array was mapped with a white noise stimulus generated and rendered on two flat screens (similar to \autoref{fig:pipeline}, second row) with `stimpack`. The white noise stimulus had a 13° spatial correlation and a 33-ms temporal correlation. The eye was tracked to reconstruct the retinal image at a spatial scale of < 1°  [@au2026]. 
\label{fig:v1_sta_rf}](figures/v1_sta_rf.svg){ width=80% }

# AI usage disclosure

All primary architectural design decisions and implementations were made by authors. Generative AI (Claude Opus 4.8, Opus 5, and Fable 5 from Anthropic) was used for parts of code generation and editing (multisample anti-aliasing, curved screen, audio module, experiment GUI elements), code merging (curved screen, NWB data), documentation, testing scaffolding, and manuscript revision. Authors thoroughly reviewed, modified, and validated all AI-generated content.

# Acknowledgements

We thank the Clandinin, Turner, Baccus, Mitra, and Murthy Labs for testing across rigs and preparations. This work was supported by Stanford Graduate Fellowships (MC, SGH), a DoD NDSEG Fellowship (MC), a Hertz Fellowship (SGH), and NIH grants R00-EY032549, R01-EY022638, R01-EY022933, R01-EY025087, R01-EY034566 and P30-EY026877. TRC is a Chan-Zuckerberg BioHub Investigator.

# References


