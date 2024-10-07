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
        self.parent.title = _("MorphoDepot")  # TODO: make this more human readable by adding spaces
        # TODO: set categories (folders where the module shows up in the module selector)
        self.parent.categories = [translate("qSlicerAbstractCoreModule", "SlicerMorph")]
        self.parent.dependencies = []  # TODO: add here list of module names that this module requires
        self.parent.contributors = ["Steve Pieper (Isomics, Inc.)"]  # TODO: replace with "Firstname Lastname (Organization)"
        # TODO: update with short description of the module and a link to online module documentation
        # _() function marks text as translatable to other languages
        self.parent.helpText = _("""
This module is the client side of the MorphoDepot collaborative segmentation tool.
""")
        # TODO: replace with organization, grant and thanks
        self.parent.acknowledgementText = _("""
This file was originally developed by Jean-Christophe Fillion-Robin, Kitware Inc., Andras Lasso, PerkLab,
and Steve Pieper, Isomics, Inc. and was partially funded by NIH grant 3P41RR013218-12S1.
""")

        # Additional initialization step after application startup is complete
        slicer.app.connect("startupCompleted()", registerSampleData)


#
# Register sample data sets in Sample Data module
#


def registerSampleData():
    """Add data sets to Sample Data module."""
    # It is always recommended to provide sample data for users to make it easy to try the module,
    # but if no sample data is available then this method (and associated startupCompeted signal connection) can be removed.

    import SampleData

    iconsPath = os.path.join(os.path.dirname(__file__), "Resources/Icons")

    # To ensure that the source code repository remains small (can be downloaded and installed quickly)
    # it is recommended to store data sets that are larger than a few MB in a Github release.

    # MorphoDepot1
    SampleData.SampleDataLogic.registerCustomSampleDataSource(
        # Category and sample name displayed in Sample Data module
        category="MorphoDepot",
        sampleName="MorphoDepot1",
        # Thumbnail should have size of approximately 260x280 pixels and stored in Resources/Icons folder.
        # It can be created by Screen Capture module, "Capture all views" option enabled, "Number of images" set to "Single".
        thumbnailFileName=os.path.join(iconsPath, "MorphoDepot1.png"),
        # Download URL and target file name
        uris="https://github.com/Slicer/SlicerTestingData/releases/download/SHA256/998cb522173839c78657f4bc0ea907cea09fd04e44601f17c82ea27927937b95",
        fileNames="MorphoDepot1.nrrd",
        # Checksum to ensure file integrity. Can be computed by this command:
        #  import hashlib; print(hashlib.sha256(open(filename, "rb").read()).hexdigest())
        checksums="SHA256:998cb522173839c78657f4bc0ea907cea09fd04e44601f17c82ea27927937b95",
        # This node name will be used when the data set is loaded
        nodeNames="MorphoDepot1",
    )

    # MorphoDepot2
    SampleData.SampleDataLogic.registerCustomSampleDataSource(
        # Category and sample name displayed in Sample Data module
        category="MorphoDepot",
        sampleName="MorphoDepot2",
        thumbnailFileName=os.path.join(iconsPath, "MorphoDepot2.png"),
        # Download URL and target file name
        uris="https://github.com/Slicer/SlicerTestingData/releases/download/SHA256/1a64f3f422eb3d1c9b093d1a18da354b13bcf307907c66317e2463ee530b7a97",
        fileNames="MorphoDepot2.nrrd",
        checksums="SHA256:1a64f3f422eb3d1c9b093d1a18da354b13bcf307907c66317e2463ee530b7a97",
        # This node name will be used when the data set is loaded
        nodeNames="MorphoDepot2",
    )


#
# MorphoDepotParameterNode
#


@parameterNodeWrapper
class MorphoDepotParameterNode:
    """
    The parameters needed by module.

    inputVolume - The volume to threshold.
    imageThreshold - The value at which to threshold the input volume.
    invertThreshold - If true, will invert the threshold.
    thresholdedVolume - The output volume that will contain the thresholded volume.
    invertedVolume - The output volume that will contain the inverted thresholded volume.
    """

    inputVolume: vtkMRMLScalarVolumeNode
    imageThreshold: Annotated[float, WithinRange(-100, 500)] = 100
    invertThreshold: bool = False
    thresholdedVolume: vtkMRMLScalarVolumeNode
    invertedVolume: vtkMRMLScalarVolumeNode


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
        self._parameterNode = None
        self._parameterNodeGuiTag = None
        self.issuesByItem = {}

    def updateIssueList(self):
        self.ui.issueList.clear()
        self.issuesByItem = {}
        issueList = self.logic.issueList()
        for issue in issueList:
            issueTitle = f"{issue['repository']['nameWithOwner']}, #{issue['number']}: {issue['title']}"
            item = qt.QListWidgetItem(issueTitle)
            self.issuesByItem[item] = issue
            self.ui.issueList.addItem(item)

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
        self.logic = MorphoDepotLogic()

        repoDir = slicer.util.settingsValue("MorphoDepot/repoDirectory", "")
        if repoDir == "":
            repoDir = qt.QStandardPaths.writableLocation(qt.QStandardPaths.DocumentsLocation)
        self.ui.repoDirectory.currentPath = repoDir

        # Connections
        self.ui.issueList.itemDoubleClicked.connect(self.onItemDoubleClicked)
        self.ui.checkpointButton.clicked.connect(self.logic.issueCheckpoint)
        self.ui.reviewButton.clicked.connect(self.issueRequestReview)

        # Buttons
        self.ui.refreshIssuesButton.connect("clicked(bool)", self.updateIssueList)

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

    def onItemDoubleClicked(self, item):
        repoDirectory = self.ui.repoDirectory.currentPath
        issue = self.issuesByItem[item]
        if slicer.util.confirmOkCancelDisplay("Close scene and load issue?"):
            slicer.mrmlScene.Clear()
            self.logic.loadIssue(issue, repoDirectory)
            self.ui.checkpointButton.enabled = True
            self.ui.reviewButton.enabled = True
            slicer.util.showStatusMessage(f"Start segmenting {item.text()}")

    def onRepoDirectoryChanged(self):
        qt.QSettings().setValue("MorphoDepot/repoDirectory", self.ui.repoDirectory.currentPath)

    def issueRequestReview(self):
        """Create a checkpoint if need, then mark issue as ready for review"""
        print("issueRequestReview")
        prURL = self.logic.issueRequestReviewURL()
        qt.QDesktopServices().openUrl(qt.QUrl(prURL))

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

    def __init__(self) -> None:
        """Called when the logic class is instantiated. Can be used for initializing member variables."""
        ScriptedLoadableModuleLogic.__init__(self)
        self.segmentationNode = None
        self.segmentationPath = ""
        self.localRepo = None

    def gh(self, command):
        process = slicer.util.launchConsoleProcess(["gh"] + command.split())
        result = process.communicate()
        print(result)
        if result[1] != None:
            logging.error("gh command failed")
            logging.error(result[1])
        return result[0]

    def issueList(self):
        issueList = json.loads(self.gh("search issues --assignee=@me --state open --json repository,title,number"))
        return issueList

    def repositoryList(self):
        repositories = json.loads(self.gh("repo list --json name"))
        repositoryList = [r['name'] for r in repositories]
        return repositoryList

    def loadIssue(self, issue, repoDirectory):

        sourceRepository = issue['repository']['nameWithOwner']
        repositoryName = issue['repository']['name']
        localDirectory = f"{repoDirectory}/{repositoryName}"

        if not os.path.exists(localDirectory):
            if repositoryName not in self.repositoryList():
                self.gh(f"repo fork {sourceRepository} --remote=true --clone=false")
            self.gh(f"repo clone {repositoryName} {localDirectory}")
        self.localRepo = git.Repo(localDirectory)

        issueNumber = issue['number']
        branchName=f"issue-{issueNumber}"

        issueBranch = None
        for branch in self.localRepo.branches:
            if branch.name == branchName:
                issueBranch = branch
                break

        if not issueBranch:
            self.localRepo.git.checkout("HEAD", b=branchName)
        else:
            self.localRepo.git.checkout(branchName)
        origin = self.localRepo.remotes.origin
        origin.pull('main')

        # TODO: move from single volume and color table file to segmentation specification json

        colorPath = glob.glob(f"{self.localRepo.working_dir}/*.ctbl")[0]
        colorNode = slicer.util.loadColorTable(colorPath)

        # TODO: move from single volume file to segmentation specification json
        volumePath = f"{self.localRepo.working_dir}/master_volume"
        volumeURL = open(volumePath).read().strip()
        print(volumeURL)
        nrrdPath = slicer.app.temporaryPath+"/volume.nrrd"
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

        # TODO: specify in the issue which segments in the color table should be included in issue segmentation
        if branchName in segmentationNodesByName.keys():
            self.segmentationNode = segmentationNodesByName[branchName]
        else:
            self.segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
            self.segmentationNode.CreateDefaultDisplayNodes()
            self.segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(volumeNode)
            self.segmentationNode.SetName(branchName)
            for colorIndex in range(colorNode.GetNumberOfColors()):
                color = [0]*4
                colorNode.GetColor(colorIndex, color)
                name = colorNode.GetColorName(colorIndex)
                segment = slicer.vtkSegment()
                segment.SetColor(color[:3])
                segment.SetName(name)
                self.segmentationNode.GetSegmentation().AddSegment(segment)

        self.segmentationPath = f"{localDirectory}/{branchName}.seg.nrrd"
        slicer.util.saveNode(self.segmentationNode, self.segmentationPath)

        editorWidget.parameterSetNode.SetAndObserveSegmentationNode(self.segmentationNode)
        editorWidget.parameterSetNode.SetAndObserveSourceVolumeNode(volumeNode)

    def issueCheckpoint(self):
        """Create a PR if needed and push current segmentation
        Mark the PR as WIP
        """
        print("issueCheckpoint")
        if not self.segmentationNode:
            return
        slicer.util.saveNode(self.segmentationNode, self.segmentationPath)
        self.localRepo.index.add([self.segmentationPath])
        self.localRepo.index.commit("New segmentation") # TODO: make this a text entry field

        branchName = self.localRepo.active_branch.name
        remote = self.localRepo.remote(name="origin")
        remote.push(branchName)

    def issueRequestReviewURL(self):
        if not self.segmentationNode:
            return ""
        self.issueCheckpoint()

        ghRepo = slicer.util.settingsValue("MorphoDepot/githubRepo", "")
        ghUser = slicer.util.settingsValue("MorphoDepot/githubUser", "")
        localRepo = self.localRepo

        issueName = localRepo.active_branch.name
        repoName = os.path.split(localRepo.working_dir)[1]

        # https://github.com/SlicerMorph/MD_E15/compare/main...pieper923:MD_E15:issue-1?expand=1
        prURL = f"https://github.com/{ghRepo}/compare/main...{ghUser}:{repoName}:{issueName}?expand=1"
        return prURL

    def getParameterNode(self):
        return MorphoDepotParameterNode(super().getParameterNode())

    def process(self,
                inputVolume: vtkMRMLScalarVolumeNode,
                outputVolume: vtkMRMLScalarVolumeNode,
                imageThreshold: float,
                invert: bool = False,
                showResult: bool = True) -> None:
        """
        Run the processing algorithm.
        Can be used without GUI widget.
        :param inputVolume: volume to be thresholded
        :param outputVolume: thresholding result
        :param imageThreshold: values above/below this threshold will be set to 0
        :param invert: if True then values above the threshold will be set to 0, otherwise values below are set to 0
        :param showResult: show output volume in slice viewers
        """

        if not inputVolume or not outputVolume:
            raise ValueError("Input or output volume is invalid")

        import time

        startTime = time.time()
        logging.info("Processing started")

        # Compute the thresholded output volume using the "Threshold Scalar Volume" CLI module
        cliParams = {
            "InputVolume": inputVolume.GetID(),
            "OutputVolume": outputVolume.GetID(),
            "ThresholdValue": imageThreshold,
            "ThresholdType": "Above" if invert else "Below",
        }
        cliNode = slicer.cli.run(slicer.modules.thresholdscalarvolume, None, cliParams, wait_for_completion=True, update_display=showResult)
        # We don't need the CLI module node anymore, remove it to not clutter the scene with it
        slicer.mrmlScene.RemoveNode(cliNode)

        stopTime = time.time()
        logging.info(f"Processing completed in {stopTime-startTime:.2f} seconds")


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

        # Get/create input data

        import SampleData

        registerSampleData()
        inputVolume = SampleData.downloadSample("MorphoDepot1")
        self.delayDisplay("Loaded test data set")

        inputScalarRange = inputVolume.GetImageData().GetScalarRange()
        self.assertEqual(inputScalarRange[0], 0)
        self.assertEqual(inputScalarRange[1], 695)

        outputVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        threshold = 100

        # Test the module logic

        logic = MorphoDepotLogic()

        # Test algorithm with non-inverted threshold
        logic.process(inputVolume, outputVolume, threshold, True)
        outputScalarRange = outputVolume.GetImageData().GetScalarRange()
        self.assertEqual(outputScalarRange[0], inputScalarRange[0])
        self.assertEqual(outputScalarRange[1], threshold)

        # Test algorithm with inverted threshold
        logic.process(inputVolume, outputVolume, threshold, False)
        outputScalarRange = outputVolume.GetImageData().GetScalarRange()
        self.assertEqual(outputScalarRange[0], inputScalarRange[0])
        self.assertEqual(outputScalarRange[1], inputScalarRange[1])

        self.delayDisplay("Test passed")
