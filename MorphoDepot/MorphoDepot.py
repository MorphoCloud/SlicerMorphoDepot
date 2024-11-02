import git
import glob
import json
import logging
import os
from typing import Annotated, Optional

import qt
import vtk

import slicer
from slicer.i18n import tr as _
from slicer.i18n import translate
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
from slicer.parameterNodeWrapper import (
    parameterNodeWrapper,
    WithinRange,
)

from slicer import vtkMRMLScalarVolumeNode


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


class MorphoDepotWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
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

    def ghProgressMethod(self, message):
        logging.debug(message)
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

        repoDir = slicer.util.settingsValue("MorphoDepot/repoDirectory", "")
        if repoDir == "":
            repoDir = qt.QStandardPaths.writableLocation(qt.QStandardPaths.DocumentsLocation)
        self.ui.repoDirectory.currentPath = repoDir
        self.onRepoDirectoryChanged()

        self.ui.forkManagementCollapsibleButton.enabled = False

        # Connections
        self.ui.issueList.itemDoubleClicked.connect(self.onIssueDoubleClicked)
        self.ui.commitButton.clicked.connect(self.onCommit)
        self.ui.reviewButton.clicked.connect(self.onRequestReview)
        self.ui.refreshButton.connect("clicked(bool)", self.onRefresh)
        self.ui.repoDirectory.connect("currentPathChanged(QString)", self.onRepoDirectoryChanged)

    def cleanup(self) -> None:
        """Called when the application closes and the module widget is destroyed."""
        self.removeObservers()

    def enter(self) -> None:
        """Called each time the user opens this module."""
        # Make sure parameter node exists and observed
        pass

    def exit(self) -> None:
        """Called each time the user opens a different module."""
        pass

    def onRefresh(self):
        self.updateIssueList()
        self.updatePRList()

    def updateIssueList(self):
        slicer.util.showStatusMessage(f"Updating issues")
        self.ui.issueList.clear()
        self.issuesByItem = {}
        issueList = self.logic.issueList()
        for issue in issueList:
            issueTitle = f"{issue['repository']['nameWithOwner']}, #{issue['number']}: {issue['title']}"
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
            prTitle = f"{pr['repository']['nameWithOwner']}: {pr['title']} ({prStatus})"
            item = qt.QListWidgetItem(prTitle)
            self.prsByItem[item] = pr
            self.ui.prList.addItem(item)
        slicer.util.showStatusMessage(f"{len(prList)} prs")

    def onIssueDoubleClicked(self, item):
        slicer.util.showStatusMessage(f"Loading {item.text()}")
        repoDirectory = self.ui.repoDirectory.currentPath
        issue = self.issuesByItem[item]
        if slicer.util.confirmOkCancelDisplay("Close scene and load issue?"):
            self.ui.currentIssueLabel.text = f"Issue: {item.text()}"
            slicer.mrmlScene.Clear()
            self.logic.loadIssue(issue, repoDirectory)
            self.ui.forkManagementCollapsibleButton.enabled = True
            slicer.util.showStatusMessage(f"Start segmenting {item.text()}")

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
        qt.QSettings().setValue("MorphoDepot/repoDirectory", self.ui.repoDirectory.currentPath)


#
# MorphoDepotLogic
#


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

    def gh(self, command):
        """Execute `gh` command.  Multiline input string accepted for readablity.
        Do not include `gh` in the command string"""
        if command.__class__() == "":
            commandList = command.replace("\n", " ").split()
        elif command.__class__() == []:
            commandList = command
        else:
            logging.error("command must be string or list")
        self.ghProgressMethod(" ".join(commandList))
        process = slicer.util.launchConsoleProcess(["gh"] + commandList)
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
            me = self.gh("auth status").split("\n")[1].split()[-2] # TODO better way?
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
            prList += repoPRList
        return prList

    def repositoryList(self):
        repositories = json.loads(self.gh("repo list --json name"))
        repositoryList = [r['name'] for r in repositories]
        return repositoryList

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
        self.localRepo = git.Repo(localDirectory)
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

    def loadPR(self, pr, repoDirectory):
        branchName = pr['title']
        repositoryName = f"{pr['headRepositoryOwner']['login']}/{pr['headRepository']['name']}"
        localDirectory = f"{repoDirectory}/{pr['headRepository']['name']}-{branchName}"
        self.ghProgressMethod(f"Loading issue {repositoryName} into {localDirectory}")

        if not os.path.exists(localDirectory):
            self.gh(f"repo clone {repositoryName} {localDirectory}")
        self.localRepo = git.Repo(localDirectory)
        self.localRepo.remotes.origin.fetch()
        self.localRepo.git.checkout(branchName)
        self.localRepo.remotes.origin.pull()

        self.loadFromLocalRepository()


    def loadFromLocalRepository(self):

        localDirectory = self.localRepo.working_dir
        branchName = self.localRepo.active_branch.name
        upstreamNameWithOwner = self.nameWithOwner("upstream")

        self.ghProgressMethod(f"Loading {branchName} into {localDirectory}")

        # TODO: move from single volume and color table file to segmentation specification json
        colorPath = glob.glob(f"{localDirectory}/*.ctbl")[0]
        colorNode = slicer.util.loadColorTable(colorPath)

        # TODO: move from single volume file to segmentation specification json
        volumePath = f"{self.localRepo.working_dir}/master_volume"
        volumeURL = open(volumePath).read().strip()
        nrrdPath = f"{slicer.app.temporaryPath}/{upstreamNameWithOwner.replace('/', '-')}-volume.nrrd"
        slicer.util.downloadFile(volumeURL, nrrdPath)
        volumeNode = slicer.util.loadVolume(nrrdPath)

        # Load all segmentations
        segmentationNodesByName = {}
        for segmentationPath in glob.glob(f"{localDirectory}/*.seg.nrrd"):
            name = os.path.split(segmentationPath)[1].split(".")[0]
            segmentationNodesByName[name] = slicer.util.loadSegmentation(segmentationPath)

        # Switch to Segment Editor module
        pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
        pluginHandlerSingleton.pluginByName("Default").switchToModule("SegmentEditor")
        editorWidget = slicer.modules.segmenteditor.widgetRepresentation().self()

        self.segmentationPath = f"{localDirectory}/{branchName}.seg.nrrd"
        if branchName in segmentationNodesByName.keys():
            self.segmentationNode = segmentationNodesByName[branchName]
        else:
            self.segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
            self.segmentationNode.CreateDefaultDisplayNodes()
            self.segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(volumeNode)
            self.segmentationNode.SetName(branchName)
            # TODO: specify in the issue which segments in the color table should be included in issue segmentation
            for colorIndex in range(1,colorNode.GetNumberOfColors()):
                color = [0]*4
                colorNode.GetColor(colorIndex, color)
                name = colorNode.GetColorName(colorIndex)
                segment = slicer.vtkSegment()
                segment.SetColor(color[:3])
                segment.SetName(name)
                self.segmentationNode.GetSegmentation().AddSegment(segment)
            slicer.util.saveNode(self.segmentationNode, self.segmentationPath)

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
