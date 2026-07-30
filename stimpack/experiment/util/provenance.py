#!/usr/bin/env python3
"""
What code produced a data file, recorded into the file itself.

A stimulus is defined by two moving parts, and until now a file named neither. stimpack's version
is half the story -- the protocol that ran, the parameters it exposed and the stimuli it drew all
live in the labpack -- and a version number alone cannot answer "what did this experiment actually
do" a year later.

Two of these deserve explanation.

``stimpack_revision`` exists because ``stimpack_version`` can lie. It comes from installed
distribution metadata, which for an editable install is whatever setup.py said at install time:
this checkout reports 0.1.1 to pip and 0.2.0 to importlib.metadata while running 0.3.0.dev0 code.
Every rig running from a git checkout -- which is most of them -- would otherwise stamp its files
with a number that is not what ran.

``.dirty`` is appended when the working tree has uncommitted changes, because a bare SHA claims
the file can be reproduced from that commit, and an edited tree makes that false.

Every lookup here fails soft. Provenance is a nicety; a git binary that is missing, slow or
pointed at a directory that is not a repository must never stop an experiment recording.
"""
import os
import subprocess

GIT_TIMEOUT_SECONDS = 5


def stimpack_version() -> str:
    """The installed distribution's version, or ``'unknown'`` outside an installed distribution.

    Stale for an editable install -- see this module's docstring, and prefer :func:`git_revision`
    when it returns something.
    """
    try:
        from importlib.metadata import PackageNotFoundError, version
        return version('stimpack')
    except PackageNotFoundError:
        return 'unknown'


def git_revision(directory) -> str:
    """``'28a303e'``, or ``'28a303e.dirty'`` with uncommitted changes; ``''`` if not a checkout.

    Fails soft on everything: no git binary, not a repository, a repository so large the call times
    out. None of that is worth interrupting an experiment for.
    """
    if not directory or not os.path.isdir(directory):
        return ''

    def git(*args):
        return subprocess.run(('git', '-C', directory) + args, capture_output=True, text=True,
                              timeout=GIT_TIMEOUT_SECONDS)

    try:
        head = git('rev-parse', '--short', 'HEAD')
        if head.returncode != 0:
            return ''
        revision = head.stdout.strip()
        # --porcelain covers staged and unstaged changes but not untracked files, which are
        # usually scratch work rather than a difference in what ran.
        status = git('status', '--porcelain', '--untracked-files=no')
        if status.returncode == 0 and status.stdout.strip():
            revision += '.dirty'
        return revision
    except (OSError, subprocess.SubprocessError):
        return ''


def stimpack_directory() -> str:
    """The stimpack package's own directory, so its checkout can be identified."""
    import stimpack
    return os.path.dirname(os.path.abspath(stimpack.__file__))


def provenance_attributes(cfg=None) -> dict[str, str]:
    """Everything worth recording about the code that produced a file, ready to write as attrs.

    Keys whose value could not be determined are left out rather than written empty, so a file
    never claims to know something it does not.
    """
    from stimpack.experiment.util import config_tools

    labpack_directory = ''
    try:
        labpack_directory = config_tools.get_labpack_directory() or ''
    except Exception:
        pass  # no labpack configured is a normal state, not a reason to fail

    attributes = {
        'stimpack_version': stimpack_version(),
        'stimpack_revision': git_revision(stimpack_directory()),
        'labpack_directory': labpack_directory,
        'labpack_name': os.path.basename(labpack_directory.rstrip(os.sep)),
        'labpack_revision': git_revision(labpack_directory),
        'config_name': str((cfg or {}).get('current_cfg_name', '')),
    }
    return {key: value for key, value in attributes.items() if value}


def provenance_summary(cfg=None) -> str:
    """The same, as one line, for formats with no free-form attributes of their own (NWB)."""
    attributes = provenance_attributes(cfg)

    stimpack_part = 'stimpack ' + attributes.get('stimpack_version', 'unknown')
    if 'stimpack_revision' in attributes:
        stimpack_part += f" ({attributes['stimpack_revision']})"

    parts = [stimpack_part]
    if 'labpack_name' in attributes:
        labpack_part = 'labpack ' + attributes['labpack_name']
        if 'labpack_revision' in attributes:
            labpack_part += f" ({attributes['labpack_revision']})"
        parts.append(labpack_part)
    if 'config_name' in attributes:
        parts.append('config ' + attributes['config_name'])
    return '; '.join(parts)
