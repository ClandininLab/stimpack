=====================
Subframe multiplexing
=====================

A projector that can read the colour channels of one video frame as successive patterns turns a
120 Hz video link into a 360 Hz monochrome display. ``stimpack`` renders that half: it draws *n*
timepoints per frame and masks each into one channel. It cannot put the projector into the matching
mode, and it cannot see whether the projector is in it — that hardware belongs to a labpack.

So this is a feature a lab **completes**. The renderer is in stimpack; the projector driver and the
one function that keeps the two in step are yours to write. This page is what that takes.

The cost is colour. Under multiplexing each channel is a slice of time rather than a colour, so
stimuli have to be greyscale — a colour stimulus is not an error, it is three timepoints that happen
to differ, displayed in sequence.


What stimpack provides
======================

Configuration, on :class:`~stimpack.visual_stim.screen.Screen`:

``subframes``
    1 for ordinary rendering, or 2–3 to divide each video frame that many ways. Three is the ceiling:
    a frame has three 8-bit colour channels.

``subframe_channel_order``
    Which colour channel carries each successive timepoint, as a permutation of ``(0, 1, 2)`` —
    red, green, blue. Always the full permutation, even at ``subframes=2``, where the trailing entry
    names the channel that goes unwritten. That is what lets the order survive a change of
    ``subframes``.

``refresh_rate``
    The video link rate, in Hz, which sets how far apart in time the subframes are.
    ``None`` — the default — means *ask the display*, and ``StimDisplay`` resolves it from the Qt
    screen at start-up. Pass one only to override; it warns if it disagrees with what the display
    reports.

Rendering, computed from those:

``screen.subframe_color_masks()``
    One ``(r, g, b, a)`` write mask per subframe, in display order. ``paintGL`` runs one pass per
    mask, so a masked clear and a masked draw touch only their own channel and the passes share one
    framebuffer with no intermediate textures.

``screen.subframe_interval``
    Seconds between successive subframes, ``1 / (refresh_rate × subframes)``. Each pass is rendered
    at that offset into the future, which is what makes the three timepoints genuinely different.

``screen.subframe_channel_names()``
    The same permutation as ``subframe_color_masks()``, named rather than positional — ``('red',
    'green', 'blue')``. This is what a projector's pattern LUT is configured with. See
    `Two vocabularies, one permutation`_.

Timing signal:

The corner square toggles once per **subframe**, not once per frame. A photodiode on it therefore
reports the display rate directly: transitions at ``refresh_rate × subframes``. That is the
measurement to trust, since nothing in software can see the projector.

Changing it at run time:

``set_subframes(n, refresh_rate=None, channel_order=None)`` is in
``framework.SCREEN_FUNCTION_NAMES``, so every screen subprocess registers it. It takes effect on the
next frame — ``paintGL`` asks for the masks and the interval every frame and caches neither — and is
**refused mid-stimulus**, because half a trial at one temporal structure and half at another is not
recoverable from the data.


What a labpack must provide
===========================

**1. A projector that can be told to read** *n* **patterns per video frame.** For a DLPC350 that is
video-pattern mode with an *n*-entry pattern LUT: the first entry triggers on VSYNC and the rest
continue from it, so all *n* land inside one video frame. A driver that triggers every pattern on
VSYNC instead gives one pattern per frame, *n* times over — which validates, plays, and looks like
it is working.

**2. A driver for it.** ``labpack-template`` ships a DLPC350 driver at
``template_labpack/device/dlpc350.py`` with a tested ``pattern_mode()``; a lab with that projector
can use it as-is. For other hardware, what the rest of this page needs from a driver is only that it
can be handed an ordered list of channel names.

**3. One function, registered on** ``root``\ **, that sets both halves.** Not two — see below.

.. code-block:: python

    from stimpack.visual_stim.screen import channel_names

    def set_subframes(n, leds='magenta', channel_order=(0, 1, 2)):
        # channel_order is ONE permutation with two readings; derive the projector's from it.
        channels = ('blue',) if n == 1 else channel_names(channel_order[:n])
        projector.pattern_mode(fps=120, channels=channels, leds=leds)
        for screen_manager in server.modules['visual'].screen_managers:
            screen_manager.set_subframes(n, channel_order=channel_order)

    server.register_function_on_root(set_subframes, 'set_subframes')

This lives in a **rig server script** (``server/<rig>.py`` in a labpack), because which projector is
attached is a property of one rig, not of the lab. See :doc:`labpack_server`.


Two vocabularies, one permutation
=================================

The renderer takes channel **indices**, because a colour write mask is positional. A projector's
pattern LUT takes channel **names**. Both describe the same decision, so a rig that writes it out
twice can transpose them:

.. code-block:: python

    # DON'T: two statements of one permutation, with nothing connecting them
    projector.pattern_mode(fps=120, channels=('red', 'green', 'blue'))
    screen_manager.set_subframes(3, channel_order=(2, 1, 0))

Nothing raises. Three timepoints are simply displayed out of order, and scrambled motion is still
motion — the eye cannot see it, and no test in either repository can catch it, because each half is
correct in isolation.

Hold one permutation and derive the other reading with
:func:`~stimpack.visual_stim.screen.channel_names` (or its inverse
:func:`~stimpack.visual_stim.screen.channel_indices`), as in the example above. If you keep the two
separate for some reason, the check worth writing is that the pattern numbers your driver would send
name the same channels, in the same order, as the masks ``subframe_color_masks()`` would use.


One name, two targets
=====================

After the registration above there are two callables named ``set_subframes``, and they do different
amounts:

``manager.target('visual').set_subframes(3)``
    stimpack's own, on every screen subprocess. Sets **the renderer only**. The projector keeps
    doing whatever it was doing — which is the half-configured state this whole page is about.

``manager.target('root').set_subframes(3)``
    your registered function. Sets **both**. This is the one a protocol should call.

``has_server_function()`` defaults to the ``root`` target, so the guard asks about the right one:

.. code-block:: python

    if self.has_server_function('set_subframes'):
        self.manager.target('root').set_subframes(3)

Guard it, because a protocol written for the 360 Hz rig should degrade on rigs that have no
projector rather than refuse to run. See :doc:`modules_and_targets`.


Limits
======

- **1, 2 or 3 subframes.** The ceiling is the three colour channels of a frame. Two suits a rig with
  only two usable LEDs, or one trading rate for exposure per subframe.
- **Greyscale stimuli only**, as above.
- **Between trials only.** ``set_subframes`` is refused while a stimulus is running. A driver's
  pattern-mode call also runs a validation sequence, which is not a per-trial-latency operation.
- **8 bits per subframe.** Each pattern is one whole channel. Deeper multiplexing — 1-bit patterns
  for ~2880 Hz — would need bitplane packing in the renderer as well as a different LUT, and is not
  implemented.
- **The stimulus has to actually vary within a frame.** A stimulus that moves a degree per second
  gains nothing from being drawn three times 1/360 s apart. This buys temporal resolution, and only
  for stimuli that have some.


Commissioning a rig
===================

Nothing in software can check that the projector is unpacking the patterns. ``SubframeTimingCheck``
in ``stimpack/experiment/example_protocol.py`` is the stimulus that makes the answer visible: it
puts a spot at a different azimuth in each subframe, cycling once per video frame.

- **all subframes displayed** — ``n_subframes`` spots, evenly spaced, and with a high-speed camera
  they appear in order
- **only one channel reaching the screen** — a single spot
- **channel order wrong** — the right number of spots in the wrong sequence, which a camera sees and
  the eye does not

Alongside it, the corner square gives the rate on a photodiode. ``subframe_rate`` and
``n_subframes`` are parameters rather than read from the screen, deliberately: this is the stimulus
you run when you do not yet believe the screen is doing what it was told.

``StimDisplay`` also prints its subframe state at start-up and on every change — the channel order,
the video rate, and the resulting display rate — followed by the reminder that it is a claim about
hardware that stimpack cannot verify.
