"""Render the experiment GUI headlessly to a PNG, for visual inspection or bug reports.

Builds the real ExperimentGUI with the startup modal and the client stubbed out (same approach as
the GUI tests), optionally selects a protocol, and saves a screenshot. No display or rig needed.

Usage:
    python tests/gui/screenshot_gui.py                                  # -> gui.png
    python tests/gui/screenshot_gui.py --protocol MovingPatch --out /tmp/shot.png
    python tests/gui/screenshot_gui.py --tab Subject
"""
import argparse
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/ for fakes

from PyQt6.QtWidgets import QApplication, QDialog  # noqa: E402

import stimpack.experiment.gui as gui_mod  # noqa: E402
from fakes import FakeClient  # noqa: E402

CFG = {
    'experimenter': 'screenshot',
    'subject_metadata': {'genotype': ['wildtype', 'mutant']},
    'current_rig_name': 'test_rig',
    'current_cfg_name': 'test_cfg',
    'rig_config': {'test_rig': {'screen_center': [0, 0], 'loco_available': False,
                                'data_directory': '/tmp'}},
}


def build_gui(app):
    def fake_setupUI(self, gui, parent=None, window_size=None):
        gui.cfg = CFG
        gui.cfg_initialized = True

    gui_mod.InitializeRigGUI.setupUI = fake_setupUI
    QDialog.exec = lambda self: 0             # don't block on the startup modal
    gui_mod.client.BaseClient = FakeClient    # don't launch a stimulus server
    return gui_mod.ExperimentGUI()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--protocol', default='DriftingSquareGrating', help='protocol to select ("" for none)')
    ap.add_argument('--tab', default=None, help='tab to show: Main | Ensemble | Subject | File')
    ap.add_argument('--out', default='gui.png')
    ap.add_argument('--size', default='900x700', help='WxH')
    args = ap.parse_args()

    app = QApplication.instance() or QApplication([])
    gui = build_gui(app)

    if args.protocol:
        names = [c.__name__ for c in gui.available_protocols]
        if args.protocol not in names:
            raise SystemExit(f'Unknown protocol {args.protocol!r}. Available: {", ".join(sorted(names))}')
        idx = names.index(args.protocol) + 1
        gui.protocol_selection_combo_box.setCurrentIndex(idx)
        gui.on_selected_protocol_ID(idx)

    if args.tab:
        from PyQt6.QtWidgets import QTabWidget
        for tab_widget in gui.findChildren(QTabWidget):
            for i in range(tab_widget.count()):
                if tab_widget.tabText(i) == args.tab:
                    tab_widget.setCurrentIndex(i)

    w, h = (int(x) for x in args.size.lower().split('x'))
    gui.resize(w, h)
    app.processEvents()
    gui.grab().save(args.out)
    print(f'wrote {args.out}  (protocol={args.protocol or "none"}, status="{gui.status_label.text()}")')


if __name__ == '__main__':
    main()
