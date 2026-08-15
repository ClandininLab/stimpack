"""
Unit tests for what code produced a data file.

These matter more than they look: the version alone was actively misleading. An editable install
reports whatever setup.py said when it was installed, so a rig running from a git checkout stamps
its files with a number that is not what ran.
"""
import subprocess

import pytest

from stimpack.experiment.util import provenance

pytestmark = pytest.mark.unit


def _repo(path, dirty=False):
    subprocess.run(['git', 'init', '-q', str(path)], check=True)
    subprocess.run(['git', '-C', str(path), 'config', 'user.email', 't@t'], check=True)
    subprocess.run(['git', '-C', str(path), 'config', 'user.name', 't'], check=True)
    (path / 'f.txt').write_text('one')
    subprocess.run(['git', '-C', str(path), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(path), 'commit', '-qm', 'first'], check=True)
    if dirty:
        (path / 'f.txt').write_text('two')
    return path


def test_a_checkout_reports_its_commit(tmp_path):
    assert provenance.git_revision(str(_repo(tmp_path))).isalnum()


def test_uncommitted_changes_are_flagged(tmp_path):
    """A bare SHA claims the file can be reproduced from that commit, which an edited tree makes
    false."""
    assert provenance.git_revision(str(_repo(tmp_path, dirty=True))).endswith('.dirty')


def test_untracked_files_are_not_dirt(tmp_path):
    """Scratch work in the labpack directory is not a difference in what ran, and flagging it
    would make .dirty permanent for most people, which is the same as meaningless."""
    repo = _repo(tmp_path)
    (repo / 'scratch.txt').write_text('notes')

    assert not provenance.git_revision(str(repo)).endswith('.dirty')


@pytest.mark.parametrize('directory', ['', None, '/nonexistent/path'])
def test_a_non_checkout_reports_nothing_rather_than_raising(tmp_path, directory):
    """Provenance is a nicety. A missing git binary, or a directory that is not a repository, must
    never stop an experiment recording."""
    assert provenance.git_revision(directory) == ''


def test_a_directory_that_is_not_a_repository_reports_nothing(tmp_path):
    assert provenance.git_revision(str(tmp_path)) == ''


def test_git_failing_entirely_is_not_fatal(tmp_path, monkeypatch):
    def explode(*args, **kwargs):
        raise OSError('no git here')
    monkeypatch.setattr(subprocess, 'run', explode)

    assert provenance.git_revision(str(tmp_path.parent)) == ''


def test_unknown_values_are_omitted_rather_than_written_empty():
    """So a file never claims to know something it does not."""
    attributes = provenance.provenance_attributes({})

    assert '' not in attributes.values()
    assert 'config_name' not in attributes          # none given


def test_the_summary_names_both_halves():
    """A stimulus is defined by stimpack and by the labpack, and a file naming only one cannot
    answer what the experiment did."""
    summary = provenance.provenance_summary({'current_cfg_name': 'mc_config.yaml'})

    assert summary.startswith('stimpack ')
    assert 'config mc_config.yaml' in summary
