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
    affiliation: "1, 5"
  - name: Maxwell H. Turner
    orcid: 0000-0002-4164-9995
    corresponding: true
    equal-contrib: true
    affiliation: "1, 6"
affiliations:
  - name: Department of Neurobiology, Stanford University, USA
    index: 1
  - name: Department of Electrical Engineering, Stanford University, USA
    index: 2
  - name: Department of Neurobiology, Harvard Medical School, USA
    index: 3
  - name: CatalystNeuro, USA
    index: 4
  - name: Biohub, San Francisco, USA
    index: 5
  - name: Department of Biological Sciences, University at Albany, SUNY, USA
    index: 6
date: 28 August 2026
bibliography: paper.bib
---

# Summary

A central goal of neuroscience is to understand how animals engage with the natural world. Studying this experimentally requires the ability to present stimuli that capture the complexity of dynamic sensory inputs during animal behavior. But performing such experiments across labs, and interpreting the resulting data, can be challenging because doing so requires highly flexible and precisely defined stimuli that can be synchronized with other measurement tools, and can be reconstructed to facilitate data analysis.

To address these challenges, we introduce `stimpack`, a Python framework for open- and closed-loop stimulus delivery. `stimpack` is a hardware-agnostic stimulus rendering environment where a single protocol simultaneously drives perspective-corrected displays, sound playback, analog outputs, and closed-loop position updates. Data are written through pluggable backends, including the neuroscience community standard Neurodata Without Borders (NWB) [@teeters2015; @rubel2022]. Everything specific to a laboratory or experimental setup (e.g. screen geometry, devices, and stimuli) is coded in a lab- or user-specific `labpack`. One protocol library runs across rigs with different screen geometries and hardware, allowing experiments to be replicated precisely across laboratories.

# Statement of need

`stimpack` was designed for laboratories that position visual displays around a stationary animal and couple the outputs of these displays to animal behavior in closed loop. In this context, `stimpack` satisfies three important requirements. First, with `stimpack` the same visual stimulus can be shown across different presentation geometries, including setups with multiple displays or curved screens. A stimulus can be specified in terms of visual angles relative to the subject, as in parametric psychophysics, or specified by Euclidean positions and sizes, as in a virtual environment. In either case, each display renders the stimulus at perspective-corrected angles (\autoref{fig:pipeline}). Second, the same package can coordinate multisensory stimulus delivery, closed-loop control, and analog device control, allowing these devices to be synchronized. Finally, `stimpack`'s files are valid NWB, so acquired data can be added with `pynwb` or NeuroConv [@mayorquin2025], browsed with Neurosift [@magland2024], and archived on DANDI.

# State of the field

We created `stimpack` to fill a gap by enabling flexible display geometries, native closed-loop control, modular device handling, and simple yet powerful stimulus design. Existing software packages for experiment control and visual stimulus delivery typically satisfy some, but not all, of these requirements.

Some visual display packages were built for **precise parametric control of a stimulus shown to a participant**. These packages make it easy to design visual stimuli, but can be difficult to extend to new screen geometries or incorporate closed-loop control based on behavioral feedback. For example, Psychtoolbox [@brainard1997; @pelli1997] and PsychoPy [@peirce2019] are designed around a display viewed roughly head-on, not around several surfaces at arbitrary orientations, and cannot readily be coupled to movement. A similar static-observer display model underlies tools for head-fixed physiology such as MonkeyLogic, PLDAPS, MWorks, and Rigbox [@hwang2019; @eastman2012; @mworks; @bhagat2020], as well as in the Python packages Vision Egg [@straw2008] and QDSpy [@franke2019].

Other software packages have been purpose-built for use cases that involve **closed-loop control in a virtual environment**. These packages, while often delivering good performance, are often designed with specific hardware setups or requirements. For example, Stytra [@stih2019] and vxPy [@vxpy] have been used for a single preparation (larval zebrafish) while FreemoVR [@stowers2017] extended similar functionality to freely moving animals. Modular, custom LED arenas designed for work in fruit flies [@reiser2008; @isaacson2022] reach kilohertz binary frame rates with specific hardware requirements and a fixed geometry and resolution. Each of these packages allows for closed-loop control of parameterized stimuli, but does not directly support transferring experimental specifications to other rig geometries. 

The existing packages that are most similar to `stimpack` can be extended to **diverse display types and geometries**. For example, ViRMEn [@aronov2014] and BonVision [@lopes2021] allow for curved displays, including conical and spherical screens. Bonsai [@lopes2015] handles closed-loop control and mixed devices, but trial structure and logging are left to the workflow's author. Finally, game engines like Unity or Unreal that have been used in neuroscience supply worlds rather than calibrated parametric stimuli, whether used directly [@jangraw2014] or wrapped for dome projection [@shapcott2025].

`stimpack` satisfies all these requirements, with a focus on a flexible architecture. Everything rig-specific is configured in a laboratory-specific `labpack` rather than inside experiment code, so **one protocol can be used across rigs and preparations**. To our knowledge, no existing package combines observer-centered perspective correction across an arbitrary number of flat screens and curved surfaces in one rig, closed-loop coupling to any locomotor tracker, non-visual outputs (sound, analog control) addressed from the same protocol, and trial-parameterized metadata saved in a community data standard by default.

# Software design

![
**stimpack's architecture.** A protocol names the module for each call. Inputs update a subject state that outputs follow, such that the closed loop does not pass through the client.
\label{fig:architecture}](figures/architecture.pdf){ width=100% }

## One module per capability

In `stimpack`, an experiment runs as a **client**, which executes the protocol and writes metadata to the data file, and a **server**, which controls hardware devices, including display screens, as a set of modules (\autoref{fig:architecture}). This modular design choice allows a shared protocol library to run on rigs whose hardware may differ. Four modules, defined by the capability rather than a particular device, are included in `stimpack` and described below.

The `visual` module controls visual stimulus rendering and display. Stimulus shapes can be painted with monochrome or RGB textures for stimuli like gratings, spatiotemporal white noise, or movie frames. The `visual` module supports most display devices and perspective-corrected rendering to any number of flat or curved screens. Temporal multiplexing packs up to three stimulus timepoints into the color channels of each output frame, so a 120 Hz video signal can drive a 360 Hz monochrome display, approaching the temporal regime of specialized LED hardware [@reiser2008]. During stimulus presentation, a small square in the corner of the display inverts on every rendered frame to enable accurate synchronization with other recorded data and to enable detection of dropped frames (\autoref{fig:pipeline}d). 

![
**One stimulus specification, three display geometries, one visual experience.**
(a) Three rigs, to scale: one monitor; two monitors meeting ahead of the subject; a hemispherical screen lit by a projector. Red: the photodiode at each display's synchronization square.
(b) The frames `stimpack` sends to the displays for one specified scene -- a 10° checkerboard to the left and a 360° photograph to the right: `stimpack` warps the images according to the specification of each display.
(c) The subject's visual field. Grey marks directions with no display surface. Faint outlines trace the coverages of the other two rigs for comparison across rows.
(d) Frame delivery at the photodiode: nominal inversions every 8.3 ms (120 Hz), and two dropped frames, one held bright and one held dark.
\label{fig:pipeline}](figures/pipeline.pdf){ width=100% }

The `audio` module plays sound stimuli through a sound card. The `locomotion` module handles locomotion-related behavior data for closed-loop feedback based on a lab-defined control function. The `voltage_out` module can send voltage waveforms to control devices (e.g. optogenetics, odor delivery, or reward). 

## Protocols, data, and the interface

A protocol is a Python class in the `labpack` that declares the parameters of a run and of the stimulus. Named presets can be saved and loaded to standardize protocol parameter sets. Users can also run an ensemble, which is a saved queue of protocols. Data are written through pluggable backends including NWB [@teeters2015;@rubel2022]. `stimpack` includes a GUI that is a shell over these objects and identical on every rig (\autoref{fig:gui}).

![
**From protocol code to a running experiment.** Left: the `AudiovisualPairing` protocol, abridged, and the module calls that `stimpack` makes from its descriptors on each trial. Right: the GUI's Main tab mid-run, its parameter fields built from the class's own declarations. The list-valued `freq` (solid red box) sweeps across trials in randomized order.
\label{fig:gui}](figures/gui_code.pdf){ width=100% }

# Research impact statement

`stimpack` consolidates four earlier Clandinin lab packages: `flystim` (perspective-corrected rendering), `flyrpc` (client--server messaging), `visprotocol` (protocols, metadata, GUI), and `multistim` (auditory stimulation). None has been described in an archival publication, and every author of those packages is an author here. The subscreen geometry is based on that of `flystim`. The curved-screen path was checked against `flymax`, an earlier MATLAB-based hemisphere-projector display in the lab, and its measured photometry. Predecessor versions underlie published work on fly visual processing and behavior [@turner2022; @mano2023; @currier2025], the most recent of which names `flystim`, `visprotocol`, and `stimpack` itself. In addition, `stimpack` has been used to reconstruct spatiotemporal receptive fields in mouse retina and visual cortex [@au2026; @weddington2026], including the example in \autoref{fig:v1_sta_rf}. `stimpack` is in use in ongoing *Drosophila* experiments in the Clandinin (Stanford), Turner (Albany), and Murthy (Princeton) laboratories, and in mouse work in the Baccus and Mitra laboratories (Stanford).

![
**Spatiotemporal receptive field (STRF) of a mouse primary visual cortex neuron.** The STRF of a cortical neuron recorded with a Neuropixels array was mapped with a white noise stimulus generated and rendered on two flat screens (similar to \autoref{fig:pipeline}, second row) with `stimpack`. The white noise stimulus had a 13° spatial correlation and a 33-ms temporal correlation. The eye was tracked to reconstruct the retinal image at a spatial scale of < 1°  [@au2026]. 
\label{fig:v1_sta_rf}](figures/v1_sta_rf.svg){ width=80% }

# AI usage disclosure

All primary architectural design decisions and implementations were made by authors. Generative AI (Claude Opus 4.8, Opus 5, and Fable 5 from Anthropic) was used for parts of code generation and editing (multisample anti-aliasing, curved screen, audio module, experiment GUI elements), code merging (curved screen, NWB data), documentation, testing scaffolding, and manuscript revision. Authors thoroughly reviewed, modified, and validated all AI-generated content.

# Acknowledgements

We thank the Clandinin, Turner, Baccus, Mitra, and Murthy Labs for testing across rigs and preparations. This work was supported by Stanford Graduate Fellowships (MC, SGH), a DoD NDSEG Fellowship (MC), a Hertz Fellowship (SGH), and NIH grants R00-EY032549, R01-EY022638, R01-EY022933, R01-EY025087, R01-EY034566 and P30-EY026877. TRC is a Biohub, San Francisco, Investigator.

# References



