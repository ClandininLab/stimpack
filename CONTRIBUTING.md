# Contributing to stimpack

The following pull request flow description is slightly modified from a similar document in the [DragonPHY project](https://github.com/StanfordVLSI/DragonPHY).  More details on using pull requests can be found in [this tutorial](https://yangsu.github.io/pull-request-tutorial/).

We use pull requests (PRs) to manage updates to the code base.  The test suite lives in the top-level **tests/** directory and runs on every PR via GitHub Actions (see `.github/workflows/test.yml`); please make sure it passes before asking for a review.  Here are the steps to go through to use this system.
1. Make sure that you're up-to-date with the latest changes from the **main** branch:
```shell
> git pull origin main
```
2. Create a new branch to store your work, and change to that branch.  The name of the branch should give some brief indictation of the feature that you're working on.  For example, you might call the branch **new_vert_bars** if it represents a new kind of vertical bar stimulus.
```shell
> git checkout -b NAME_OF_YOUR_BRANCH
```
3. Make changes to the code and commit them.
```shell
<make changes to code>
> git commit -am "description of changes"
```
4. Push code back to GitHub:
```shell
> git push origin NAME_OF_YOUR_BRANCH
```
5. Go to the [stimpack GitHub page](https://github.com/ClandininLab/stimpack).
6. Click Pull Requests -> New Pull Request.
7. Make sure "base" is at **main** and set **compare** to the name of your branch.
8. Add a title and description of your pull request and click "Create Pull Request".
  * If the tests pass, then you should be able to click a button at the bottom of the page to merge the pull request.  At that point it is safe to click the button that deletes the branch you created, since the changes have been merged into the **main** branch.
  * If the tests don't pass, then modify the code and push it to your branch.  The checks will automatically be re-run and the pull request will be updated with the build status.  In other words,
```shell
<make changes to code>
> git commit -am "description of changes"
> git push origin NAME_OF_YOUR_BRANCH
```
10. Now that the changes are merged, switch back to the **main** branch and pull the changes on you machine.
```shell
> git checkout main
> git pull origin main
```

## Running the tests

The suite is split into tiers by what each needs (see `tests/conftest.py`). A bare `pytest`
runs everything in one process:

```shell
> pip install -e .[test]
> pytest
```

Individual tiers, which is what CI runs so a failure says which layer broke:

```shell
> pytest -m unit                    # pure logic; no GL, GUI or hardware
> pytest -m "integration or gui"    # real objects over a fake RPC link; the PyQt6 GUI, offscreen
> pytest -m gl                      # needs an OpenGL context (software Mesa is fine)
> pytest -m e2e                     # a live server with real screen subprocesses
```

`-m e2e` launches real stimulus windows; run it under a virtual display (`xvfb-run -a pytest -m e2e`)
if you would rather they did not appear. `-m hardware` needs an actual rig and is not run in CI.

Golden-image tests under `tests/gl/` compare renders against `tests/gl/reference/`. If you change
a stimulus deliberately, regenerate them with `pytest -m gl --update-goldens` and review the diff.

## Checking a labpack

Changes to how stimpack loads user modules can break a labpack silently. Against a real one:

```shell
> stimpack --check-labpack           # config keys and module_paths; imports nothing
> stimpack --check-labpack --deep    # also imports each protocol and checks where its calls go
```
