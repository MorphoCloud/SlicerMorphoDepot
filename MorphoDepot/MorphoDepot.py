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

        ghUser = self.ui.githubUser.text
        ghRepo = self.ui.githubRepo.text
        print(f"checking for user {ghUser} in {ghRepo}")
        issues = self.logic.getGithubIssues(ghRepo, ghUser)
        for issue in issues:
            item = qt.QListWidgetItem(issue.title)
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

        # TODO: the rest of the UI should be disabled until they are filled in with valid info
        self.ui.githubUser.text = slicer.util.settingsValue("MorphoDepot/githubUser", "")
        self.ui.githubTokenPath.currentPath = slicer.util.settingsValue("MorphoDepot/githubTokenPath", "")
        repoDir = slicer.util.settingsValue("MorphoDepot/repoDirectory", "")
        if repoDir == "":
            repoDir = qt.QStandardPaths.writableLocation(qt.QStandardPaths.DocumentsLocation)
        self.ui.repoDirectory.currentPath = repoDir
        self.ui.githubRepo.text = slicer.util.settingsValue("MorphoDepot/githubRepo", "")

        # Connections
        self.ui.issueList.itemDoubleClicked.connect(self.onItemDoubleClicked)
        self.ui.githubUser.editingFinished.connect(self.onGithubUserChanged)
        self.ui.githubTokenPath.currentPathChanged.connect(self.onGithubTokenPathChanged)
        self.ui.repoDirectory.currentPathChanged.connect(self.onRepoDirectoryChanged)
        self.ui.githubRepo.editingFinished.connect(self.onGithubRepoChanged)


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
        ghRepo = self.ui.githubRepo.text
        repoDirectory = self.ui.repoDirectory.currentPath
        issue = self.issuesByItem[item]
        if slicer.util.confirmOkCancelDisplay("Close scene and load issue?"):
            slicer.mrmlScene.Clear()
            self.logic.loadIssue(ghRepo, issue, repoDirectory)
            self.ui.checkpointButton.enabled = True
            self.ui.reviewButton.enabled = True

    def onGithubUserChanged(self):
        qt.QSettings().setValue("MorphoDepot/githubUser", self.ui.githubUser.text)

    def onGithubTokenPathChanged(self):
        qt.QSettings().setValue("MorphoDepot/githubTokenPath", self.ui.githubTokenPath.currentPath)

    def onRepoDirectoryChanged(self):
        qt.QSettings().setValue("MorphoDepot/repoDirectory", self.ui.repoDirectory.currentPath)

    def onGithubRepoChanged(self):
        qt.QSettings().setValue("MorphoDepot/githubRepo", self.ui.githubRepo.text)


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

    def getGithubIssues(self, ghRepo, ghUser):
        import github
        gh = github.Github()
        repo = gh.get_repo(ghRepo)
        issues = repo.get_issues(assignee=ghUser)
        return ([issue for issue in issues])

    def loadIssue(self, ghRepo, issue, repoDirectory):
        import git

        tokenPath = slicer.util.settingsValue("MorphoDepot/githubTokenPath", "")
        repoToken = open(tokenPath).read().strip()

        repositoryURL = f"https://{repoToken}@github.com/{ghRepo}"
        localDirectory = f"{repoDirectory}/{ghRepo.split('/')[1]}"

        if os.path.exists(localDirectory):
            localRepo = git.Repo(localDirectory)
        else:
            logging.info(f"cloning from {repositoryURL} to {localDirectory}")
            localRepo = git.Repo.clone_from(repositoryURL, localDirectory)

        issueNumber = issue.number
        branchName=f"{issueNumber}-depot-branch"

        issueBranch = None
        for branch in localRepo.branches:
            if branch.name == branchName:
                issueBranch = branch
                break

        if not issueBranch:
            localRepo.git.checkout("HEAD", b=branchName)
        else:
            localRepo.git.checkout(branchName)

        # TODO: move from single volume file to segmentation specification json
        volumePath = f"{localRepo.working_dir}/master_volume"
        volumeURL = open(volumePath).read().strip()
        print(volumeURL)
        nrrdPath = slicer.app.temporaryPath+"/volume.nrrd"
        slicer.util.downloadFile(volumeURL, nrrdPath)
        volume = slicer.util.loadVolume(nrrdPath)

        # TODO: need way to identify segmentation - should be named for issue
        segmentationPath = f"{localRepo.working_dir}/IMPC_sample_data.seg.nrrd"
        segmentation = slicer.util.loadSegmentation(segmentationPath)

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
