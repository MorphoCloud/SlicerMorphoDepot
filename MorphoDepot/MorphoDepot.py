from contextlib import contextmanager
import glob
import json
import logging
import os
import shutil
import platform
import requests
import sys
import traceback
from typing import Annotated, Optional

import qt

import slicer
from slicer.i18n import tr as _
from slicer.i18n import translate
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
from slicer.parameterNodeWrapper import (
    parameterNodeWrapper,
    WithinRange,
)


#
# MorphoDepot
#


class MorphoDepot(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("MorphoDepot")
        self.parent.categories = [translate("qSlicerAbstractCoreModule", "SlicerMorph")]
        self.parent.dependencies = []
        self.parent.contributors = ["Steve Pieper (Isomics, Inc.)"]
        self.parent.helpText = _("""
This module is the client side of the MorphoDepot collaborative segmentation tool.
""")
        self.parent.acknowledgementText = _("""
This was developed as part of the SlicerMorhpCloud project funded by the NSF.
This file was originally developed by Jean-Christophe Fillion-Robin, Kitware Inc., Andras Lasso, PerkLab,
and Steve Pieper, Isomics, Inc. and was partially funded by NIH grant 3P41RR013218-12S1.
""")



#
# MorphoDepotWidget
#

class EnableModuleMixin:
    """A superclass to check that everything is correct before enabling the module.  """

    def __init__(self):
        pass

    def promptForGitConfig(self):
        # TODO
        return ("Sample Name", "name@example.com")

    def offerInstallation(self):
        msg = "Extra tools are needed to use this module (pixi, git, and gh),"
        msg += "\nplus some python packages (idigbio and pygbif)."
        msg += "\nClick OK to install them for MorphoDepot."
        install = slicer.util.confirmOkCancelDisplay(msg)
        if install:
            logic = MorphoDepotLogic(ghProgressMethod=MorphoDepotWidget.ghProgressMethod)
            logic.installPythonDependencies()
            if not logic.usingSystemGit:
                name,email = self.promptForGitConfig()
                try:
                    logic.installGitDependencies(name, email)
                    self.enter()
                except Exception as e:
                    msg = "Installation failed.  Check error log for debugging information."
                    slicer.util.messageBox(msg)
                    print(f"Exception: {e}")
                    traceback.print_exc(file=sys.stderr)
        return logic.ghPath

    def checkModuleEnabled(self):
        moduleEnabled = True
        if not self.logic.slicerVersionCheck():
            msg = "This version of Slicer is not supported. Use a newer Preview or a Release after 5.8."
            slicer.util.messageBox(msg)
            moduleEnabled = False
        if not (moduleEnabled and self.logic.git and self.logic.gitPath and self.logic.ghPath):
            moduleEnabled = moduleEnabled and self.offerInstallation()
        moduleEnabled = moduleEnabled and (self.logic.git is not None)
        return moduleEnabled


class MorphoDepotWidget(ScriptedLoadableModuleWidget, VTKObservationMixin, EnableModuleMixin):
    """Uses ScriptedLoadableModuleWidget base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent=None) -> None:
        """Called when the user opens the module the first time and the widget is initialized."""
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)  # needed for parameter node observation
        self.logic = None
        self.issuesByItem = {}
        self.prsByItem = {}


    def ghProgressMethod(self, message=None):
        message = message if message else self
        logging.info(message)
        slicer.util.showStatusMessage(message)
        slicer.app.processEvents(qt.QEventLoop.ExcludeUserInputEvents)

    def setup(self) -> None:
        """Called when the user opens the module the first time and the widget is initialized."""
        ScriptedLoadableModuleWidget.setup(self)

        # Load widget from .ui file (created by Qt Designer).
        # Additional widgets can be instantiated manually and added to self.layout.
        uiWidget = slicer.util.loadUI(self.resourcePath("UI/MorphoDepot.ui"))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)

        # Set scene in MRML widgets. Make sure that in Qt designer the top-level qMRMLWidget's
        # "mrmlSceneChanged(vtkMRMLScene*)" signal in is connected to each MRML widget's.
        # "setMRMLScene(vtkMRMLScene*)" slot.
        uiWidget.setMRMLScene(slicer.mrmlScene)

        # Create logic class. Logic implements all computations that should be possible to run
        # in batch mode, without a graphical user interface.
        self.logic = MorphoDepotLogic(ghProgressMethod=self.ghProgressMethod)

        # only allow picking directories (bitwise AND NOT file filter bit)
        self.ui.repoDirectory.filters = self.ui.repoDirectory.filters & ~self.ui.repoDirectory.Files

        repoDir = self.logic.localRepositoryDirectory()
        self.ui.repoDirectory.currentPath = repoDir

        self.ui.forkManagementCollapsibleButton.enabled = False

        # Connections
        self.ui.issueList.itemDoubleClicked.connect(self.onIssueDoubleClicked)
        self.ui.prList.itemSelectionChanged.connect(self.onPRSelectionChanged)
        self.ui.commitButton.clicked.connect(self.onCommit)
        self.ui.reviewButton.clicked.connect(self.onRequestReview)
        self.ui.refreshButton.connect("clicked(bool)", self.onRefresh)
        self.ui.repoDirectory.connect("currentPathChanged(QString)", self.onRepoDirectoryChanged)
        self.ui.openPRPageButton.clicked.connect(self.onOpenPRPageButtonClicked)

    def cleanup(self) -> None:
        """Called when the application closes and the module widget is destroyed."""
        self.removeObservers()

    def enter(self):
        moduleEnabled = self.checkModuleEnabled()
        self.ui.issuesCollapsibleButton.enabled = moduleEnabled
        self.ui.prCollapsibleButton.enabled = moduleEnabled
        self.ui.refreshButton.enabled = moduleEnabled

    def onRefresh(self):
        self.updateIssueList()
        self.updatePRList()

    def updateIssueList(self):
        slicer.util.showStatusMessage(f"Updating issues")
        self.ui.issueList.clear()
        self.issuesByItem = {}
        issueList = self.logic.issueList()
        for issue in issueList:
            issueTitle = f"{issue['title']} {issue['repository']['nameWithOwner']}, #{issue['number']}"
            item = qt.QListWidgetItem(issueTitle)
            self.issuesByItem[item] = issue
            self.ui.issueList.addItem(item)
        slicer.util.showStatusMessage(f"{len(issueList)} issues")

    def updatePRList(self):
        slicer.util.showStatusMessage(f"Updating PRs")
        self.ui.prList.clear()
        self.prsByItem = {}
        prList = self.logic.prList(role="segmenter")
        for pr in prList:
            prStatus = 'draft' if pr['isDraft'] else 'ready for review'
            prTitle = f"{pr['issueTitle']} {pr['repository']['nameWithOwner']}: {pr['title']} ({prStatus})"
            item = qt.QListWidgetItem(prTitle)
            self.prsByItem[item] = pr
            self.ui.prList.addItem(item)
        slicer.util.showStatusMessage(f"{len(prList)} prs")

    def onPRSelectionChanged(self):
        self.ui.openPRPageButton.enabled = False
        self.selectedPR = None
        selectedItems = self.ui.prList.selectedItems()
        if selectedItems:
            item = selectedItems[0]
            self.selectedPR = self.prsByItem[item]
            self.ui.openPRPageButton.enabled = True

    def onOpenPRPageButtonClicked(self):
        """Open the currently selected PR in the browser."""
        if self.selectedPR:
            repoNameWithOwner = self.selectedPR["repository"]["nameWithOwner"]
            prNumber = self.selectedPR["number"]
            prURL = qt.QUrl(f"https://github.com/{repoNameWithOwner}/pull/{prNumber}")
            qt.QDesktopServices.openUrl(prURL)
        else:
            slicer.util.errorDisplay("No PR selected.")

    def onIssueDoubleClicked(self, item):
        slicer.util.showStatusMessage(f"Loading {item.text()}")
        repoDirectory = self.ui.repoDirectory.currentPath
        issue = self.issuesByItem[item]
        if slicer.util.confirmOkCancelDisplay("Close scene and load issue?"):
            self.ui.currentIssueLabel.text = f"Issue: {item.text()}"
            slicer.mrmlScene.Clear()
            try:
                self.logic.loadIssue(issue, repoDirectory)
                self.ui.forkManagementCollapsibleButton.enabled = True
                slicer.util.showStatusMessage(f"Start segmenting {item.text()}")
            except self.logic.git.exc.NoSuchPathError:
                slicer.util.errorDisplay("Could not load issue.  If it was just created on github please wait a few seconds and try again")

    def onCommit(self):
        slicer.util.showStatusMessage(f"Commiting and pushing")
        message = self.ui.messageTitle.text
        if message == "":
            slicer.util.messageBox("You must provide a commit message (title required, body optional)")
        body = self.ui.messageBody.plainText
        if body != "":
            message = f"{message}\n\n{body}"
        if self.logic.commitAndPush(message):
            self.ui.messageTitle.text = ""
            self.ui.messageBody.plainText = ""
            slicer.util.showStatusMessage(f"Commit and push complete")
            self.updatePRList()
        else:
            path = self.ui.repoDirectory.currentPath
            slicer.util.messageBox(f"Commit failed.\nYour repository conflicts with what's on github.  Copy your work from {path} and then delete the local repository folder and restart the issues.")
            slicer.util.showStatusMessage(f"Commit and push failed")

    def onRequestReview(self):
        """Create a checkpoint if need, then mark issue as ready for review"""
        slicer.util.showStatusMessage(f"Marking pull request for review")
        prURL = self.logic.requestReview()
        self.updatePRList()

    def onRepoDirectoryChanged(self):
        self.logic.setLocalRepositoryDirectory(self.ui.repoDirectory.currentPath)


#
# MorphoDepotLogic
#

def gitEnvironmentDecorator(func):
    """
    Decorator that temporarily configures the enviornment for methods that use GitPython
    For use inside MorphoDepotLogic.
    """
    @contextmanager
    def tempHome(self):
        oldHOME = os.environ.get('HOME')
        try:
            if not self.usingSystemGit:
                os.environ['HOME'] = self.pixiInstallDir
            yield
        finally:
            if oldHOME is not None:
                os.environ['HOME'] = oldHOME
            else:
                try:
                    del os.environ['HOME']
                except KeyError:
                    pass

    def wrapper(*args, **kwargs):
        with tempHome(args[0]):
            return func(*args, **kwargs)

    return wrapper


class MorphoDepotLogic(ScriptedLoadableModuleLogic):
    """This class should implement all the actual
    computation done by your module.  The interface
    should be such that other python code can import
    this class and make use of the functionality without
    requiring an instance of the Widget.
    Uses ScriptedLoadableModuleLogic base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, ghProgressMethod = None) -> None:
        """Called when the logic class is instantiated. Can be used for initializing member variables."""
        ScriptedLoadableModuleLogic.__init__(self)
        self.segmentationNode = None
        self.segmentationPath = ""
        self.localRepo = None
        self.ghProgressMethod = ghProgressMethod if ghProgressMethod else lambda *args : None

        self.executableExtension = '.exe' if os.name == 'nt' else ''
        modulePath = os.path.split(slicer.modules.morphodepot.path)[0]
        self.resourcesPath = modulePath + "/Resources"
        self.pixiInstallDir = self.resourcesPath + "/pixi"

        # use system installed git and gh if available
        import shutil
        systemGitPath = shutil.which("git")
        systemGhPath = shutil.which("gh")
        if systemGitPath and systemGhPath:
            self.gitExecutablesDir = os.path.dirname(systemGitPath)
            self.gitPath = systemGitPath
            self.ghPath = systemGhPath
            self.usingSystemGit = True
        else:
            # otherwiss define where we expect to find git and gh after installation
            if os.name == 'nt':
                self.gitExecutablesDir = self.pixiInstallDir + "/.pixi/envs/default/Library/bin"
                self.gitPath = self.gitExecutablesDir + "/git.exe"
                self.ghPath = self.pixiInstallDir + "/.pixi/envs/default/Scripts/gh.exe"
            else:
                self.gitExecutablesDir = self.pixiInstallDir + "/.pixi/envs/default/bin"
                self.gitPath = self.gitExecutablesDir + "/git"
                self.ghPath = self.pixiInstallDir + "/.pixi/envs/default/bin/gh"
            self.usingSystemGit = False

        self.git = None
        if os.path.exists(self.gitPath):
            self.importGitPython()

    def importGitPython(self):
        # gitpython cannot be imported if it can't find git.
        # we specify the executable but also set it explicitly so that
        # we know we are using our download in case it has already been
        # imported elsewhere and found a different git
        os.environ['GIT_PYTHON_GIT_EXECUTABLE'] = self.gitPath
        import git
        git.refresh(path=self.gitPath)
        self.git = git
        del os.environ['GIT_PYTHON_GIT_EXECUTABLE']

    def slicerVersionCheck(self):
        return hasattr(slicer.vtkSegment, "SetTerminology")

    def localRepositoryDirectory(self):
        repoDirectory = slicer.util.settingsValue("MorphoDepot/repoDirectory", "")
        if repoDirectory == "":
            defaultRepoDir = os.path.join(slicer.app.defaultScenePath, "MorphoDepot")
            self.setLocalRepositoryDirectory(defaultRepoDir)
            repoDirectory = defaultRepoDir
        return repoDirectory

    def setLocalRepositoryDirectory(self, repoDir):
        qt.QSettings().setValue("MorphoDepot/repoDirectory", repoDir)

    def installPythonDependencies(self):
        """Install pygbif and idigbio if needed
        """
        try:
            import pygbif
        except ModuleNotFoundError:
            self.ghProgressMethod(f"Installing pygbif")
            slicer.util.pip_install("pygbif")
            import pygbif

        try:
            import idigbio
        except ModuleNotFoundError:
            self.ghProgressMethod(f"Installing idigbio")
            slicer.util.pip_install("idigbio")
            import idigbio


    @gitEnvironmentDecorator
    def installGitDependencies(self, name, email):
        """Install pixi, git, and gh in our resources to be used here.
        Requires name and email to configure git
        Returns path to gh
        """

        if self.usingSystemGit:
            return

        os.makedirs(self.pixiInstallDir, exist_ok=True)

        if os.name == 'nt':
            fileName = 'install.ps1'
        else:
            fileName = 'install.sh'

        self.ghProgressMethod("Downloading pixi")
        url = f'https://pixi.sh/{fileName}'
        scriptPath = self.pixiInstallDir + "/" + fileName
        slicer.util.downloadFile(url, scriptPath)

        self.ghProgressMethod("Running pixi installer")
        updateEnvironment = {}
        if os.name == 'nt':
            command = ["powershell.exe",
                        "-ExecutionPolicy", "Bypass",
                        "-File", scriptPath ,
                        "-PixiHome", self.pixiInstallDir, "-NoPathUpdate"]
        else:
            updateEnvironment['PIXI_HOME'] = self.pixiInstallDir
            updateEnvironment['PIXI_NO_PATH_UPDATE'] = "1"
            updateEnvironment['DBUS_SESSION_BUS_ADDRESS'] = "" ;# bug on jetstream2 linux
            command = ["/bin/bash", scriptPath]

        p = slicer.util.launchConsoleProcess(command, updateEnvironment=updateEnvironment)
        logging.info(str(p.communicate()))

        pixiPath = self.pixiInstallDir + "/bin/pixi" + self.executableExtension
        p = slicer.util.launchConsoleProcess([pixiPath, "init", self.pixiInstallDir], updateEnvironment=updateEnvironment)
        logging.info(str(p.communicate()))
        self.ghProgressMethod("Adding git")
        p = slicer.util.launchConsoleProcess([pixiPath, "add", "--manifest-path", self.pixiInstallDir, "git"], updateEnvironment=updateEnvironment)
        logging.info(str(p.communicate()))
        self.ghProgressMethod("Adding gh")
        p = slicer.util.launchConsoleProcess([pixiPath, "add", "--manifest-path", self.pixiInstallDir, "gh"], updateEnvironment=updateEnvironment)
        logging.info(str(p.communicate()))

        self.ghProgressMethod("Importing GitPython")
        self.importGitPython()

        tempRepoDir = slicer.app.temporaryPath + "/_MorphoDepot_temp_git"
        import shutil
        shutil.rmtree(tempRepoDir, ignore_errors=True)
        os.makedirs(tempRepoDir)
        tempRepo = self.git.Repo.init(tempRepoDir)
        tempRepo.config_writer(config_level="global").set_value("user", "name", name).release()
        tempRepo.config_writer(config_level="global").set_value("user", "email", email).release()
        shutil.rmtree(tempRepoDir)

        self.ghProgressMethod("Installation complete")

    @gitEnvironmentDecorator
    def gh(self, command):
        """Execute `gh` command.  Multiline input string accepted for readablity.
        Do not include `gh` in the command string"""
        if self.ghPath == "":
            logging.error("Error, gh not found")
            return "Error, gh not found"
        if command.__class__() == "":
            commandList = command.replace("\n", " ").split()
        elif command.__class__() == []:
            commandList = command
        else:
            logging.error("command must be string or list")
        self.ghProgressMethod(" ".join(commandList))
        fullCommandList = [self.ghPath] + commandList
        if self.usingSystemGit:
            environment = {}
        else:
            environment = {
                "PATH" : self.gitExecutablesDir,
                "GIT_EXEC_PATH" : self.gitExecutablesDir,
                "GH_CONFIG_DIR" : self.pixiInstallDir
            }
        process = slicer.util.launchConsoleProcess(fullCommandList, updateEnvironment=environment)
        result = process.communicate()
        if process.returncode != 0:
            logging.error("gh command failed:")
            logging.error(commandList)
            logging.error(result)
        self.ghProgressMethod(f"gh command finished: {result}")
        return result[0]

    def morphoRepos(self):
        # TODO: generalize for other topics
        return json.loads(self.gh("search repos --json owner,name --include-forks true -- topic:morphodepot"))

    def issueList(self):
        repoList = self.morphoRepos()
        issueList = []
        for repo in repoList:
            repoID = f"{repo['owner']['login']}/{repo['name']}"
            issueList += json.loads(self.gh(f"search issues --assignee=@me --state open --repo {repoID} --json repository,title,number"))
        return issueList

    def prList(self, role="segmenter"):
        repoList = self.morphoRepos()
        if role == "segmenter":
            searchString = "--author=@me"
        elif role == "reviewer":
            # if you are are reviewer, you must have one repo but check anyway
            myRepoList = json.loads(self.gh(f"repo list --json owner --limit 1"))
            if len(myRepoList) == 0:
                return []
            me = myRepoList[0]['owner']['login']
            searchString = "--search draft:false"
        jsonFields = "title,number,isDraft,updatedAt,headRepositoryOwner,headRepository"
        prList = []
        for repo in repoList:
            if role == "reviewer":
                if repo['owner']['login'] != me:
                    continue
            repoID = f"{repo['owner']['login']}/{repo['name']}"
            repoPRList = json.loads(self.gh(f"pr list --repo {repoID} --json {jsonFields} {searchString}"))
            for repoPR in repoPRList:
                repoPR['repository'] = {'nameWithOwner': repoID}
                issueNumber = repoPR['title'].split("-")[1]
                issueList = json.loads(self.gh(f"issue list --repo {repoID} --json number,title"))
                repoPR['issueTitle'] = "Issue not found"
                for issue in issueList:
                    if str(issue['number']) == issueNumber:
                        repoPR['issueTitle'] = issue['title']
            prList += repoPRList
        return prList

    def repositoryList(self):
        repositories = json.loads(self.gh("repo list --json name"))
        repositoryList = [r['name'] for r in repositories]
        return repositoryList

    @gitEnvironmentDecorator
    def ensureUpstreamExists(self):
        if not "upstream" in self.localRepo.remotes:
            # no upstream, so this is an issue assigned to the owner of the repo
            self.localRepo.create_remote("upstream", list(self.localRepo.remotes[0].urls)[0])

    @gitEnvironmentDecorator
    def loadIssue(self, issue, repoDirectory):
        self.ghProgressMethod(f"Loading issue {issue} into {repoDirectory}")
        issueNumber = issue['number']
        branchName=f"issue-{issueNumber}"
        sourceRepository = issue['repository']['nameWithOwner']
        repositoryName = issue['repository']['name']
        localDirectory = f"{repoDirectory}/{repositoryName}-{branchName}"

        if not os.path.exists(localDirectory):
            if repositoryName not in self.repositoryList():
                self.gh(f"repo fork {sourceRepository} --remote=true --clone=false")
            self.gh(f"repo clone {repositoryName} {localDirectory}")
        self.localRepo = self.git.Repo(localDirectory)
        self.ensureUpstreamExists()

        originBranches = self.localRepo.remotes.origin.fetch()
        originBranchIDs = [ob.name for ob in originBranches]
        originBranchID = f"origin/{branchName}"

        localIssueBranch = None
        for branch in self.localRepo.branches:
            if branch.name == branchName:
                localIssueBranch = branch
                break

        if localIssueBranch:
            logging.debug("Using existing local repository %s", localIssueBranch)
            self.localRepo.git.checkout(localIssueBranch)
        else:
            logging.debug("Making new branch")
            if originBranchID in originBranchIDs:
                logging.debug("Checking out existing from origin")
                self.localRepo.git.execute(f"git checkout --track {originBranchID}".split())
            else:
                logging.debug("Nothing local or remote, nothing in origin so make new branch %s", branchName)
                self.localRepo.git.checkout("origin/main")
                self.localRepo.git.branch(branchName)
                self.localRepo.git.checkout(branchName)

        self.loadFromLocalRepository()

    @gitEnvironmentDecorator
    def loadPR(self, pr, repoDirectory):
        branchName = pr['title']
        repositoryName = f"{pr['headRepositoryOwner']['login']}/{pr['headRepository']['name']}"
        localDirectory = f"{repoDirectory}/{pr['headRepository']['name']}-{branchName}"
        self.ghProgressMethod(f"Loading issue {repositoryName} into {localDirectory}")

        if not os.path.exists(localDirectory):
            self.gh(f"repo clone {repositoryName} {localDirectory}")
        self.localRepo = self.git.Repo(localDirectory)
        self.ensureUpstreamExists()
        self.localRepo.remotes.origin.fetch()
        self.localRepo.git.checkout(branchName)
        self.localRepo.remotes.origin.pull()
        try:
            self.localRepo.remotes.origin.pull()
        except self.git.exc.GitCommandError:
            self.ghProgressMethod(f"Error pulling origin")
            return False

        self.loadFromLocalRepository()
        return True

    def loadFromLocalRepository(self):
        localDirectory = self.localRepo.working_dir
        branchName = self.localRepo.active_branch.name
        upstreamNameWithOwner = self.nameWithOwner("upstream")

        self.ghProgressMethod(f"Loading {branchName} into {localDirectory}")

        colorPath = glob.glob(f"{localDirectory}/*.csv")[0]
        colorNode = slicer.util.loadColorTable(colorPath)

        # TODO: move from single volume file to segmentation specification json
        # TODO: save checksum in source_volume file to verify when downloading later
        volumePath = f"{localDirectory}/source_volume"
        if not os.path.exists(volumePath):
            volumePath = f"{localDirectory}/master_volume" # for backwards compatibility
        volumeURL = open(volumePath).read().strip()
        nrrdPath = f"{localDirectory}/{upstreamNameWithOwner.replace('/', '-')}-volume.nrrd"
        if not os.path.exists(nrrdPath):
            slicer.util.downloadFile(volumeURL, nrrdPath)
        volumeNode = slicer.util.loadVolume(nrrdPath)

        # Load all segmentations
        segmentationNodesByName = {}
        for segmentationPath in glob.glob(f"{localDirectory}/*.seg.nrrd"):
            name = os.path.split(segmentationPath)[1].split(".")[0]
            segmentationNodesByName[name] = slicer.util.loadSegmentation(segmentationPath)
            segmentationNodesByName[name].GetDisplayNode().SetVisibility(False)

        # Switch to Segment Editor module
        pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
        pluginHandlerSingleton.pluginByName("Default").switchToModule("SegmentEditor")
        editorWidget = slicer.modules.segmenteditor.widgetRepresentation().self()

        self.segmentationPath = f"{localDirectory}/{branchName}.seg.nrrd"
        if branchName in segmentationNodesByName.keys():
            self.segmentationNode = segmentationNodesByName[branchName]
            self.segmentationNode.GetDisplayNode().SetVisibility(True)
        else:
            self.segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
            self.segmentationNode.CreateDefaultDisplayNodes()
            self.segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(volumeNode)
            self.segmentationNode.SetName(branchName)

        editorWidget.parameterSetNode.SetAndObserveSegmentationNode(self.segmentationNode)
        editorWidget.parameterSetNode.SetAndObserveSourceVolumeNode(volumeNode)

    def nameWithOwner(self, remote):
        branchName = self.localRepo.active_branch.name
        repo = self.localRepo.remote(name=remote)
        repoURL = list(repo.urls)[0]
        if repoURL.find("@") != -1:
            # git ssh prototocol
            repoURL = "/".join(repoURL.split(":"))
            repoNameWithOwner = "/".join(repoURL.split("/")[-2:]).split(".")[0]
        else:
            # https protocol
            repoNameWithOwner = "/".join(repoURL.split("/")[-2:]).split(".")[0]
        return repoNameWithOwner

    def issuePR(self, role="segmenter"):
        """Find the issue for the issue currently being worked on or None if there isn't one"""
        branchName = self.localRepo.active_branch.name
        upstreamNameWithOwner = self.nameWithOwner("upstream")
        upstreamOwner = upstreamNameWithOwner.split("/")[0]
        issuePR = None
        prs = self.prList(role=role)
        for pr in prs:
            prRepoNameWithOwner = pr['repository']['nameWithOwner']
            if prRepoNameWithOwner == upstreamNameWithOwner and pr['title'] == branchName:
                issuePR = pr
        return issuePR

    def commitAndPush(self, message):
        """Create a PR if needed and push current segmentation
        Mark the PR as a draft
        """
        if not self.segmentationNode:
            return False
        if not slicer.util.saveNode(self.segmentationNode, self.segmentationPath):
            logging.error(f"Segmentation save failed: path is {self.segmentationPath}")
            return False
        self.localRepo.index.add([self.segmentationPath])
        self.localRepo.index.commit(message)

        branchName = self.localRepo.active_branch.name
        remote = self.localRepo.remote(name="origin")

        # Workaround for missing origin.push().raise_if_error() in 3.1.14
        # (see https://github.com/gitpython-developers/GitPython/issues/621):
        # https://github.com/gitpython-developers/GitPython/issues/621
        pushInfoList = remote.push(branchName)
        for pi in pushInfoList:
            for flag in [pi.REJECTED, pi.REMOTE_REJECTED, pi.REMOTE_FAILURE, pi.ERROR]:
                if pi.flags & flag:
                    logging.error(f"Push failed with {flag}")
                    return False

        # create a PR if needed
        if not self.issuePR():
            issueNumber = branchName.split("-")[1]
            upstreamNameWithOwner = self.nameWithOwner("upstream")
            originNameWithOwner = self.nameWithOwner("origin")
            originOwner = originNameWithOwner.split("/")[0]
            commandList = f"""
                pr create
                --draft
                --repo {upstreamNameWithOwner}
                --base main
                --title {branchName}
                --head {originOwner}:{branchName}
            """.replace("\n"," ").split()
            commandList += ["--body", f" Fixes #{issueNumber}"]
            self.gh(commandList)
        return True

    def requestReview(self):
        pr = self.issuePR(role="segmenter")
        upstreamNameWithOwner = self.nameWithOwner("upstream")
        self.gh(f"""
            pr ready {pr['number']}
                --repo {upstreamNameWithOwner}
            """)

    def requestChanges(self, message=""):
        pr = self.issuePR(role="reviewer")
        upstreamNameWithOwner = self.nameWithOwner("upstream")
        commandList = f"""
            pr review {pr['number']}
                --request-changes
                --repo {upstreamNameWithOwner}
        """.replace("\n"," ").split()
        if message != "":
            commandList += ["--body", message]
        self.gh(commandList)
        self.gh(f"""
            pr ready {pr['number']}
                --undo
                --repo {upstreamNameWithOwner}
            """)

    def approvePR(self, message=""):
        pr = self.issuePR(role="reviewer")
        upstreamNameWithOwner = self.nameWithOwner("upstream")
        commandList = f"""
            pr review {pr['number']}
                --approve
                --repo {upstreamNameWithOwner}
        """.replace("\n"," ").split()
        if message != "":
            commandList += ["--body", message]
        self.gh(commandList)
        commandList = f"""
            pr merge {pr['number']}
                --repo {upstreamNameWithOwner}
                --squash
        """.replace("\n"," ").split()
        commandList += ["--body", "Merging and closing"]
        self.gh(commandList)

    @gitEnvironmentDecorator
    def createAccessionRepo(self, sourceVolume, colorTable, accessionData):

        repoName = accessionData['githubRepoName'][1]
        repoDir = f"{self.localRepositoryDirectory()}/{repoName}"
        os.makedirs(repoDir)

        # save data
        sourceFileName = sourceVolume.GetName()
        sourceFilePath = f"{repoDir}/{sourceFileName}.nrrd"
        slicer.util.saveNode(sourceVolume, sourceFilePath)
        colorTableName = colorTable.GetName()
        slicer.util.saveNode(colorTable, f"{repoDir}/{colorTableName}.csv")

        # write accessionData file
        fp = open(f"{repoDir}/MorphoDepotAccession.json", "w")
        fp.write(json.dumps(accessionData, indent=4))
        fp.close()

        # write license file
        if accessionData["license"][1].startswith("CC BY-NC"):
            licenseURL = "https://creativecommons.org/licenses/by-nc/4.0/legalcode.txt"
        else:
            licenseURL = "https://creativecommons.org/licenses/by/4.0/legalcode.txt"
        response = requests.get(licenseURL)
        fp = open(f"{repoDir}/LICENSE.txt", "w")
        fp.write(response.content.decode('ascii', errors="ignore"))
        fp.close()

        if accessionData['iDigBioAccessioned'][1] == "Yes":
            idigbioURL = accessionData['iDigBioURL']
            specimenID = idigbioURL.split("/")[-1]
            import idigbio
            api = idigbio.json()
            idigbioData = api.view("records", specimenID)
            speciesString = idigbioData['data']['ala:species']
        else:
            speciesString = accessionData['species'][1]
        speciesTopicString = speciesString.lower().replace(" ", "-")

        # write readme file
        fp = open(f"{repoDir}/README.md", "w")
        fp.write(f"""
## MorphoDepot Repository
Repository for segmentation of a specimen scan.  See [this JSON file](MorphoDepotAccession.json) for specimen details.
* Species: {speciesString}
* Modality: {accessionData['modality'][1]}
* Contrast: {accessionData['contrastEnhancement'][1]}
* Dimensions: {accessionData['scanDimensions']}
* Spacing (mm): {accessionData['scanSpacing']}
        """)
        fp.close()

        # create initial repo
        repo = self.git.Repo.init(repoDir, initial_branch='main')

        repo.index.add([f"{repoDir}/README.md",
                        f"{repoDir}/LICENSE.txt",
                        f"{repoDir}/MorphoDepotAccession.json",
                        f"{repoDir}/{colorTableName}.csv",
        ])
        repo.index.commit("Initial commit")

        self.gh(f"repo create {repoName} --add-readme --disable-wiki --public --source {repoDir} --push")

        self.localRepo = repo
        repoNameWithOwner = self.nameWithOwner("origin")

        self.gh(f"repo edit {repoNameWithOwner} --enable-projects=false --enable-discussions=false")

        self.gh(f"repo edit {repoNameWithOwner} --add-topic morphodepot --add-topic md-{speciesTopicString}")

        # create initial release and add asset
        self.gh(f"release create --repo {repoNameWithOwner} v1 --notes Initial-release")
        self.gh(f"release upload --repo {repoNameWithOwner} v1 {sourceFilePath}#{sourceFileName}.nrrd")

        # write source volume pointer file
        fp = open(f"{repoDir}/source_volume", "w")
        fp.write(f"https://github.com/{repoNameWithOwner}/releases/download/v1/{sourceFileName}.nrrd")
        fp.close()

        repo.index.add([f"{repoDir}/source_volume"])
        repo.index.commit("Add source file url file")
        repo.remote(name="origin").push()


#
# MorphoDepotTest
#


class MorphoDepotTest(ScriptedLoadableModuleTest):
    """
    This is the test case for your scripted module.
    Uses ScriptedLoadableModuleTest base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def setUp(self):
        """Do whatever is needed to reset the state - typically a scene clear will be enough."""
        slicer.mrmlScene.Clear()

    def runTest(self):
        """Run as few or as many tests as needed here."""
        self.setUp()
        self.test_MorphoDepot1()

    def test_MorphoDepot1(self):
        """Ideally you should have several levels of tests.  At the lowest level
        tests should exercise the functionality of the logic with different inputs
        (both valid and invalid).  At higher levels your tests should emulate the
        way the user would interact with your code and confirm that it still works
        the way you intended.
        One of the most important features of the tests is that it should alert other
        developers when their changes will have an impact on the behavior of your
        module.  For example, if a developer removes a feature that you depend on,
        your test should break so they know that the feature is needed.
        """

        self.delayDisplay("Starting the test")

        self.delayDisplay("Test passed")

