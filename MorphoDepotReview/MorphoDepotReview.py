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

import MorphoDepot


#
# MorphoDepotReview
#


class MorphoDepotReview(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("MorphoDepotReview")
        self.parent.categories = [translate("qSlicerAbstractCoreModule", "SlicerMorph")]
        self.parent.dependencies = ["MorphoDepot"]
        self.parent.contributors = ["Steve Pieper (Isomics, Inc.)"]
        self.parent.helpText = _("""
This module is the client side review tool of the MorphoDepotReview collaborative segmentation tool.
""")
        self.parent.acknowledgementText = _("""
This was developed as part of the SlicerMorhpCloud project funded by the NSF.
This file was originally developed by Jean-Christophe Fillion-Robin, Kitware Inc., Andras Lasso, PerkLab,
and Steve Pieper, Isomics, Inc. and was partially funded by NIH grant 3P41RR013218-12S1.
""")



#
# MorphoDepotReviewWidget
#


class MorphoDepotReviewWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    """Uses ScriptedLoadableModuleWidget base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent=None) -> None:
        """Called when the user opens the module the first time and the widget is initialized."""
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)  # needed for parameter node observation
        self.logic = None
        self.prsByItem = {}

    def setup(self) -> None:
        """Called when the user opens the module the first time and the widget is initialized."""
        ScriptedLoadableModuleWidget.setup(self)

        # Load widget from .ui file (created by Qt Designer).
        # Additional widgets can be instantiated manually and added to self.layout.
        uiWidget = slicer.util.loadUI(self.resourcePath("UI/MorphoDepotReview.ui"))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)

        # Set scene in MRML widgets. Make sure that in Qt designer the top-level qMRMLWidget's
        # "mrmlSceneChanged(vtkMRMLScene*)" signal in is connected to each MRML widget's.
        # "setMRMLScene(vtkMRMLScene*)" slot.
        uiWidget.setMRMLScene(slicer.mrmlScene)

        # Uses MorphoDepot logic and widget so all related methods are together
        ghProgressMethod = lambda message : MorphoDepot.MorphoDepotWidget.ghProgressMethod(None, message)
        self.logic = MorphoDepot.MorphoDepotLogic(ghProgressMethod)

        self.ui.prCollapsibleButton.enabled = False

        # Connections
        self.ui.refreshButton.connect("clicked(bool)", self.updatePRList)
        self.ui.prList.itemDoubleClicked.connect(self.onPRDoubleClicked)
        self.ui.requestChangesButton.clicked.connect(self.onRequestChanges)
        self.ui.approveButton.clicked.connect(self.onApprove)

    def updatePRList(self):
        slicer.util.showStatusMessage(f"Updating PRs")
        self.ui.prList.clear()
        self.prsByItem = {}
        prList = self.logic.prList(role="reviewer")
        for pr in prList:
            prStatus = 'draft' if pr['isDraft'] else 'ready for review'
            prTitle = f"{pr['repository']['nameWithOwner']}: {pr['title']} ({prStatus})"
            item = qt.QListWidgetItem(prTitle)
            self.prsByItem[item] = pr
            self.ui.prList.addItem(item)
        slicer.util.showStatusMessage(f"{len(prList)} prs")

    def onPRDoubleClicked(self, item):
        slicer.util.showStatusMessage(f"Loading {item.text()}")
        defaultRepoDir = slicer.util.settingsValue("DefaultScenePath", "")
        repoDirectory = slicer.util.settingsValue("MorphoDepot/repoDirectory", defaultRepoDir)
        pr = self.prsByItem[item]
        if slicer.util.confirmOkCancelDisplay("Close scene and load PR?"):
            self.ui.currentPRLabel.text = f"PR: {item.text()}"
            slicer.mrmlScene.Clear()
            self.logic.loadPR(pr, repoDirectory)
            self.ui.prCollapsibleButton.enabled = True
            slicer.util.showStatusMessage(f"Start reviewing {item.text()}")

    def onRequestChanges(self):
        slicer.util.showStatusMessage(f"Requesting changes")
        message = self.ui.reviewMessage.plainText
        self.logic.requestChanges(message)
        self.ui.reviewMessage.plainText = ""
        slicer.util.showStatusMessage(f"Changes requested")
        self.updatePRList()

    def onApprove(self):
        slicer.util.showStatusMessage(f"Approving")
        prURL = self.logic.approvePR()
        self.ui.reviewMessage.plainText = ""
        self.updatePRList()


#
# MorphoDepotReviewLogic
#


class MorphoDepotReviewLogic(ScriptedLoadableModuleLogic):
    """
    No logic here - rely on MorphoDepot logic
    """

    def __init__(self) -> None:
        """Called when the logic class is instantiated. Can be used for initializing member variables."""
        ScriptedLoadableModuleLogic.__init__(self)


#
# MorphoDepotReviewTest
#


class MorphoDepotReviewTest(ScriptedLoadableModuleTest):
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
        self.test_MorphoDepotReview1()

    def test_MorphoDepotReview1(self):
        """
        No testing here because it's very hard to test the server side
        """
        self.delayDisplay("Starting the test")
        self.delayDisplay("Test passed")
