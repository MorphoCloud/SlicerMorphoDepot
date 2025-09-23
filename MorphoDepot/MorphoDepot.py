from contextlib import contextmanager
from typing import Annotated, Optional
import fnmatch
import git
import glob
import json
import locale
import logging
import math
import os
import platform
import random
import re
import requests
import shutil
import subprocess
import sys
import traceback
import qt

import ctk
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
This was developed as part of the MorhpoCloud project funded by the NSF
Advances in Biological Informatics (1759883) and NSF/DBI Cyberinfrastructure (2301405) grants.
This file was originally developed by Jean-Christophe Fillion-Robin, Kitware Inc., Andras Lasso, PerkLab,
and Steve Pieper, Isomics, Inc. and was partially funded by NIH grant 3P41RR013218-12S1.
""")

#
# Utility
#
def downloadFileWorkaround(url, filePath):
    """Workaround for https://github.com/Slicer/Slicer/issues/8541"""
    import time
    networkManager = qt.QNetworkAccessManager()
    request = qt.QNetworkRequest()
    request.setAttribute(qt.QNetworkRequest.FollowRedirectsAttribute, True)

    request.setUrl(qt.QUrl(url))
    reply = networkManager.get(request)

    while not reply.isFinished():
        # bad form, but needed to emulate synchronous
        slicer.app.processEvents()

    data = reply.readAll()
    file = qt.QFile(filePath)
    file.open(qt.QIODevice.WriteOnly)
    file.write(data)
    file.close()


#
# MorphoDepotWidget
#

class EnableModuleMixin:
    """A superclass to check that everything is correct before enabling the module.  """

    def __init__(self):
        pass

    def offerPythonInstallation(self):
        msg = "Extra python packages (idigbio and pygbif) are required."
        msg += "\nClick OK to install them for MorphoDepot."
        install = slicer.util.confirmOkCancelDisplay(msg)
        if install:
            logic = MorphoDepotLogic(progressMethod=MorphoDepotWidget.progressMethod)
            logic.installPythonDependencies()
            msg = "Python package installation complete"
            slicer.util.messageBox(msg)
        return logic.checkPythonDependencies()

    def checkModuleEnabled(self):
        """Module is only enabled if all of the dependencies are available,
        possibly after the user has accepted installation and it worked as expected
        """
        if not self.logic.slicerVersionCheck():
            msg = "This version of Slicer is not supported. Use a newer Preview or a Release after 5.8."
            slicer.util.messageBox(msg)
            return False
        if not self.logic.checkPythonDependencies():
            if not self.offerPythonInstallation():
                return False
        moduleEnabled = True
        if not self.logic.checkGitDependencies():
            msg = "The git and gh must be installed and configured."
            msg += "\nBe sure that you have logged into Github with 'gh auth login' and then restart Slicer."
            msg += "\nSee documentation for platform-specific instructions"
            slicer.util.messageBox(msg)
            return False
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
        self.segmentNamesByID = {}
        self.searchResultsByItem = {}

    def progressMethod(self, message=None):
        message = message if message else self
        logging.info(message)
        slicer.util.showStatusMessage(message)
        slicer.app.processEvents(qt.QEventLoop.ExcludeUserInputEvents)

    def setupLogic(self):
        self.logic = MorphoDepotLogic(progressMethod=self.progressMethod)

    def setup(self) -> None:
        """Called when the user opens the module the first time and the widget is initialized."""
        ScriptedLoadableModuleWidget.setup(self)

        # Load widget from .ui file (created by Qt Designer).
        # Additional widgets can be instantiated manually and added to self.layout.
        self.tabWidget = qt.QTabWidget()
        self.layout.addWidget(self.tabWidget)

        uiWidget = slicer.util.loadUI(os.path.normpath(self.resourcePath("UI/MorphoDepotConfigure.ui")))
        uiWidget.setMRMLScene(slicer.mrmlScene)
        self.tabWidget.addTab(uiWidget, "Configure")
        self.configureUI = slicer.util.childWidgetVariables(uiWidget)

        uiWidget = slicer.util.loadUI(os.path.normpath(self.resourcePath("UI/MorphoDepotSearch.ui")))
        uiWidget.setMRMLScene(slicer.mrmlScene)
        self.tabWidget.addTab(uiWidget, "Search")
        self.searchUI = slicer.util.childWidgetVariables(uiWidget)

        uiWidget = slicer.util.loadUI(os.path.normpath(self.resourcePath("UI/MorphoDepotAnnotate.ui")))
        uiWidget.setMRMLScene(slicer.mrmlScene)
        self.tabWidget.addTab(uiWidget, "Annotate")
        self.annotateUI = slicer.util.childWidgetVariables(uiWidget)

        uiWidget = slicer.util.loadUI(os.path.normpath(self.resourcePath("UI/MorphoDepotReview.ui")))
        uiWidget.setMRMLScene(slicer.mrmlScene)
        self.tabWidget.addTab(uiWidget, "Review")
        self.reviewUI = slicer.util.childWidgetVariables(uiWidget)

        uiWidget = slicer.util.loadUI(os.path.normpath(self.resourcePath("UI/MorphoDepotCreate.ui")))
        uiWidget.setMRMLScene(slicer.mrmlScene)
        self.tabWidget.addTab(uiWidget, "Create")
        self.createUI = slicer.util.childWidgetVariables(uiWidget)

        uiWidget = slicer.util.loadUI(os.path.normpath(self.resourcePath("UI/MorphoDepotRelease.ui")))
        uiWidget.setMRMLScene(slicer.mrmlScene)
        self.tabWidget.addTab(uiWidget, "Release")
        self.releaseUI = slicer.util.childWidgetVariables(uiWidget)

        self.adminTab = qt.QScrollArea()
        self.tabWidget.addTab(self.adminTab, "Admin")
        self.adminTabIndex = self.tabWidget.indexOf(self.adminTab)
        self.adminUI = {} # for future use

        # restore last tab index
        tabIndex = slicer.util.settingsValue("MorphoDepot/tabIndex", 0, converter=int)
        self.tabWidget.currentIndex = tabIndex

        # Set scene in MRML widgets. Make sure that in Qt designer the top-level qMRMLWidget's
        # "mrmlSceneChanged(vtkMRMLScene*)" signal in is connected to each MRML widget's.
        # "setMRMLScene(vtkMRMLScene*)" slot.
        uiWidget.setMRMLScene(slicer.mrmlScene)

        self.setupLogic()

        # Configure
        # only allow picking directories (bitwise AND NOT file filter bit)
        self.configureUI.repoDirectory.filters = self.configureUI.repoDirectory.filters & ~self.configureUI.repoDirectory.Files
        repoDir = os.path.normpath(self.logic.localRepositoryDirectory())
        self.configureUI.repoDirectory.currentPath = repoDir
        self.configureUI.repoDirectory.toolTip = "Be sure to use a real local directory, not an iCloud or OneDrive online location"
        self.configureUI.gitPath.currentPath = os.path.normpath(self.logic.gitExecutablePath) if self.logic.gitExecutablePath else ""
        self.configureUI.gitPath.toolTip = "Restart Slicer after setting new path"
        self.configureUI.ghPath.currentPath = os.path.normpath(self.logic.ghExecutablePath) if self.logic.ghExecutablePath else ""
        self.configureUI.ghPath.toolTip = "Restart Slicer after setting new path"
        self.annotateUI.forkManagementCollapsibleButton.enabled = False
        self.configureUI.adminModeCheckBox = qt.QCheckBox("Administrator mode")
        self.configureUI.configureCollapsibleButton.layout().addWidget(self.configureUI.adminModeCheckBox)
        adminMode = slicer.util.settingsValue("MorphoDepot/adminMode", False, converter=slicer.util.toBool)
        self.configureUI.adminModeCheckBox.checked = adminMode

        # Testing
        self.configureUI.testingCollapsibleButton = ctk.ctkCollapsibleButton()
        self.configureUI.testingCollapsibleButton.text = "Testing"
        self.configureUI.testingCollapsibleButton.collapsed = True
        self.configureUI.configureCollapsibleButton.layout().addWidget(self.configureUI.testingCollapsibleButton)
        self.configureUI.testingCollapsibleButton.visible = slicer.util.settingsValue("Developer/DeveloperMode", False, converter=slicer.util.toBool)

        testingLayout = qt.QFormLayout(self.configureUI.testingCollapsibleButton)

        self.configureUI.creatorUser = qt.QLineEdit()
        self.configureUI.creatorUser.text = slicer.util.settingsValue("MorphoDepot/testingCreatorUser", "")
        self.configureUI.creatorUser.toolTip = "GitHub user account for creating repositories in tests. Must be logged in via 'gh auth login' with 'delete_repo' scope."
        testingLayout.addRow("Creator:", self.configureUI.creatorUser)

        self.configureUI.annotatorUser = qt.QLineEdit()
        self.configureUI.annotatorUser.text = slicer.util.settingsValue("MorphoDepot/testingAnnotatorUser", "")
        self.configureUI.annotatorUser.toolTip = "GitHub user account for annotating in tests. Must be logged in via 'gh auth login'."
        testingLayout.addRow("Annotator:", self.configureUI.annotatorUser)

        # Connections for testing widgets
        self.configureUI.creatorUser.editingFinished.connect(
            lambda: qt.QSettings().setValue("MorphoDepot/testingCreatorUser", self.configureUI.creatorUser.text)
        )
        self.configureUI.annotatorUser.editingFinished.connect(
            lambda: qt.QSettings().setValue("MorphoDepot/testingAnnotatorUser", self.configureUI.annotatorUser.text)
        )

        # Create
        self.createUI.inputSelector = slicer.qMRMLNodeComboBox()
        self.createUI.inputSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
        self.createUI.inputSelector.setMRMLScene(slicer.mrmlScene)
        self.createUI.inputSelector.showChildNodeTypes = False
        self.createUI.inputSelector.addEnabled = False
        self.createUI.inputSelector.removeEnabled = False
        self.createUI.inputSelector.noneDisplay = "Select a source volume (required)"
        self.createUI.inputSelector.toolTip = "Pick the source volume for the repository."

        self.createUI.colorSelector = slicer.qMRMLColorTableComboBox()
        self.createUI.colorSelector.setMRMLScene(slicer.mrmlScene)
        self.createUI.colorSelector.noneDisplay = "Select a color table (required)"

        self.createUI.segmentationSelector = slicer.qMRMLNodeComboBox()
        self.createUI.segmentationSelector.nodeTypes = ["vtkMRMLSegmentationNode"]
        self.createUI.segmentationSelector.setMRMLScene(slicer.mrmlScene)
        self.createUI.segmentationSelector.noneEnabled = True
        self.createUI.segmentationSelector.noneDisplay = "Select a baseline segmentation (optional)"
        self.createUI.segmentationSelector.toolTip = "Pick an baseline segmentation (optional)."

        formLayout = self.createUI.inputsCollapsibleButton.layout()
        formLayout.addRow("Source volume:", self.createUI.inputSelector)
        formLayout.addRow("Color table:", self.createUI.colorSelector)
        formLayout.addRow("Baseline segmentation:", self.createUI.segmentationSelector)

        self.createUI.accessionLayout = qt.QVBoxLayout()
        self.createUI.accessionCollapsibleButton.setLayout(self.createUI.accessionLayout)
        self.createUI.createRepository.enabled = False
        validationCallback = lambda valid, w=self.createUI.createRepository: w.setEnabled(valid)
        self.createUI.accessionForm = MorphoDepotAccessionForm(validationCallback=validationCallback)
        self.createUI.accessionLayout.addWidget(self.createUI.accessionForm.topWidget)

        # Annotate
        self.annotateUI.commitButton.enabled = False
        self.annotateUI.reviewButton.enabled = False

        # Review
        self.reviewUI.prCollapsibleButton.enabled = False

        # Release
        self.releaseUI.releasesCollapsibleButton.enabled = False

        # Search
        self.searchUI.searchForm = MorphoDepotSearchForm(updateCallback=self.doSearch)
        self.searchUI.searchCollapsibleButton.layout().addWidget(self.searchUI.searchForm.topWidget)
        self.searchUI.searchForm.topWidget.enabled = False
        self.searchUI.resultsTable = qt.QTableView()
        self.searchUI.resultsTable.setContextMenuPolicy(qt.Qt.CustomContextMenu)
        self.searchUI.resultsTable.customContextMenuRequested.connect(self.onSearchResultsContextMenu)
        self.searchUI.resultsModel = qt.QStandardItemModel()
        self.searchUI.resultsTable.setModel(self.searchUI.resultsModel)
        self.searchUI.resultsTable.setSelectionBehavior(qt.QAbstractItemView.SelectRows)
        self.searchUI.resultsTable.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
        self.searchUI.resultsCollapsibleButton.layout().addWidget(self.searchUI.resultsTable)

        # Connections
        self.tabWidget.currentChanged.connect(self.onCurrentTabChanged)
        self.configureUI.repoDirectory.comboBox().connect("currentTextChanged(QString)", self.onRepoDirectoryChanged)
        self.configureUI.gitPath.comboBox().connect("currentTextChanged(QString)", self.onGitPathChanged)
        self.configureUI.adminModeCheckBox.stateChanged.connect(self.onAdminModeChanged)
        self.configureUI.ghPath.comboBox().connect("currentTextChanged(QString)", self.onGhPathChanged)
        self.createUI.createRepository.clicked.connect(self.onCreateRepository)
        self.createUI.openRepository.clicked.connect(self.onOpenRepository)
        self.createUI.clearForm.clicked.connect(self.onClearForm)
        self.annotateUI.issueList.itemDoubleClicked.connect(self.onIssueDoubleClicked)
        self.annotateUI.prList.itemSelectionChanged.connect(self.onPRSelectionChanged)
        self.annotateUI.messageTitle.textChanged.connect(self.onCommitMessageChanged)
        self.annotateUI.commitButton.clicked.connect(self.onCommit)
        self.annotateUI.reviewButton.clicked.connect(self.onRequestReview)
        self.annotateUI.refreshButton.connect("clicked(bool)", self.onRefresh)
        self.annotateUI.openPRPageButton.clicked.connect(self.onOpenPRPageButtonClicked)
        self.reviewUI.refreshButton.connect("clicked(bool)", self.updateReviewPRList)
        self.reviewUI.prList.itemDoubleClicked.connect(self.onPRDoubleClicked)
        self.reviewUI.requestChangesButton.clicked.connect(self.onRequestChanges)
        self.reviewUI.approveButton.clicked.connect(self.onApprove)
        self.releaseUI.refreshButton.clicked.connect(self.onRefreshReleaseTab)
        self.releaseUI.repoList.itemDoubleClicked.connect(self.onReleaseRepoDoubleClicked)
        self.releaseUI.makeReleaseButton.clicked.connect(self.onMakeRelease)
        self.releaseUI.openReleasePageButton.clicked.connect(self.onOpenReleasePage)
        self.searchUI.resultsTable.doubleClicked.connect(self.onSearchResultsDoubleClicked)
        self.searchUI.refreshButton.clicked.connect(self.onRefreshSearch)

        # set initial visibility of admin tab
        self.onAdminModeChanged(self.configureUI.adminModeCheckBox.checkState())

    def cleanup(self) -> None:
        """Called when the application closes and the module widget is destroyed."""
        self.removeObservers()

    def enter(self):
        moduleEnabled = self.checkModuleEnabled()
        self.createUI.inputsCollapsibleButton.enabled = moduleEnabled
        self.createUI.accessionCollapsibleButton.enabled = moduleEnabled
        self.annotateUI.issuesCollapsibleButton.enabled = moduleEnabled
        self.annotateUI.prCollapsibleButton.enabled = moduleEnabled
        self.annotateUI.refreshButton.enabled = moduleEnabled
        self.reviewUI.prsCollapsibleButton.enabled = moduleEnabled
        self.reviewUI.refreshButton.enabled = moduleEnabled
        self.reviewUI.prCollapsibleButton.enabled = self.logic.issuePR(role="reviewer")
        self.releaseUI.reposCollapsibleButton.enabled = moduleEnabled
        self.releaseUI.refreshButton.enabled = moduleEnabled

    def onCurrentTabChanged(self,index):
        qt.QSettings().setValue("MorphoDepot/tabIndex", index)

    def onAdminModeChanged(self, state):
        isAdmin = (state == qt.Qt.Checked)
        qt.QSettings().setValue("MorphoDepot/adminMode", isAdmin)
        self.tabWidget.setTabVisible(self.adminTabIndex, isAdmin)

    # Create
    def onCreateRepository(self):
        if self.createUI.inputSelector.currentNode() == None or self.createUI.colorSelector.currentNode() == None:
            slicer.util.errorDisplay("Need to select volume and color table")
            return
        sourceVolume = self.createUI.inputSelector.currentNode()
        sourceSegmentation = self.createUI.segmentationSelector.currentNode()
        colorTable = self.createUI.colorSelector.currentNode()

        validGithubAsset = r'^[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?$'
        if re.fullmatch(validGithubAsset, sourceVolume.GetName()) is None:
            slicer.util.errorDisplay("Please rename volume.\n"
                "Only alphanumerics, periods, hyphens and underscores accepted.")
            return
        if re.fullmatch(validGithubAsset, colorTable.GetName()) is None:
            slicer.util.errorDisplay("Please rename color table.\n"
                "Only alphanumerics, periods, hyphens and underscores accepted.\n"
                "Use the 'All nodes' tab of the Data module to access the color table and right-click to rename.")
            return

        slicer.util.showStatusMessage(f"Creating...")
        accessionData = self.createUI.accessionForm.accessionData()
        with slicer.util.tryWithErrorDisplay(_("Trouble creating repository"), waitCursor=True):
            accessionData['scanDimensions'] = str(sourceVolume.GetImageData().GetDimensions())
            accessionData['scanSpacing'] = str(sourceVolume.GetSpacing())
            self.logic.createAccessionRepo(sourceVolume, colorTable, accessionData, sourceSegmentation)
        self.createUI.createRepository.enabled = False
        self.createUI.openRepository.enabled = True

    def onOpenRepository(self):
        nameWithOwner = self.logic.nameWithOwner("origin")
        repoURL = qt.QUrl(f"https://github.com/{nameWithOwner}")
        qt.QDesktopServices.openUrl(repoURL)

    def onClearForm(self):
        slicer.util.reloadScriptedModule(self.moduleName)


    # Annotate
    def onRefresh(self):
        with slicer.util.tryWithErrorDisplay("Failed to refresh from GitHub", waitCursor=True):
            self.annotateUI.issueList.clear()
            self.annotateUI.prList.clear()
            self.updateIssueList()
            self.updateAnnotatePRList()

    def onCommitMessageChanged(self, text):
        commitEnabled = (text != "")
        self.annotateUI.commitButton.enabled = commitEnabled

    def updateIssueList(self):
        slicer.util.showStatusMessage(f"Updating issues")
        self.annotateUI.issueList.clear()
        self.issuesByItem = {}
        issueList = self.logic.issueList()
        for issue in issueList:
            issueTitle = f"{issue['title']} {issue['repository']['nameWithOwner']}, #{issue['number']}"
            item = qt.QListWidgetItem(issueTitle)
            self.issuesByItem[item] = issue
            self.annotateUI.issueList.addItem(item)
        slicer.util.showStatusMessage(f"{len(issueList)} issues")

    def updateAnnotatePRList(self):
        slicer.util.showStatusMessage(f"Updating PRs")
        self.annotateUI.prList.clear()
        self.prsByItem = {}
        prList = self.logic.prList(role="segmenter")
        for pr in prList:
            prStatus = 'draft' if pr['isDraft'] else 'ready for review'
            prTitle = f"{pr['issueTitle']} {pr['repository']['nameWithOwner']}: {pr['title']} ({prStatus})"
            item = qt.QListWidgetItem(prTitle)
            self.prsByItem[item] = pr
            self.annotateUI.prList.addItem(item)
        slicer.util.showStatusMessage(f"{len(prList)} prs")

    def onPRSelectionChanged(self):
        self.annotateUI.openPRPageButton.enabled = False
        self.selectedPR = None
        selectedItems = self.annotateUI.prList.selectedItems()
        if selectedItems:
            item = selectedItems[0]
            self.selectedPR = self.prsByItem[item]
            self.annotateUI.openPRPageButton.enabled = True

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
        repoDirectory = os.path.normpath(self.configureUI.repoDirectory.currentPath)
        issue = self.issuesByItem[item]
        if slicer.util.confirmOkCancelDisplay("Close scene and load issue?"):
            with slicer.util.tryWithErrorDisplay("Failed to load issue", waitCursor=True):
                slicer.util.showStatusMessage(f"Loading {item.text()}")
                self.removeObservers()
                self.segmentNamesByID = {}
                self.annotateUI.currentIssueLabel.text = f"Issue: {item.text()}"
                slicer.mrmlScene.Clear()
                try:
                    self.logic.loadIssue(issue, repoDirectory)
                    self.annotateUI.forkManagementCollapsibleButton.enabled = True
                    segmentation = self.logic.segmentationNode.GetSegmentation()
                    segmentationLogic = slicer.modules.segmentations.logic()
                    for segmentID in segmentation.GetSegmentIDs():
                        segment = segmentation.GetSegment(segmentID)
                        segmentationLogic.SetSegmentStatus(segment, segmentationLogic.NotStarted)
                        self.segmentNamesByID[segmentID] = segment.GetName()
                    segmentEvents = [segmentation.SourceRepresentationModified,
                                     segmentation.SegmentModified,
                                     segmentation.SegmentAdded,
                                     segmentation.SegmentRemoved]
                    for event in segmentEvents:
                        self.addObserver(segmentation, event, self.onSegmentationModified)
                    pr = self.logic.issuePR(role="segmenter")
                    if pr:
                        self.annotateUI.reviewButton.enabled = True
                    slicer.util.showStatusMessage(f"Start segmenting {item.text()}")
                except git.exc.NoSuchPathError:
                    slicer.util.errorDisplay("Could not load issue. If it was just created on github please wait a few seconds and try again")

    def onSegmentationModified(self, segmentation, callData):
        """Called when a segment is modified, triggers an update of the commit message."""
        self.updateAutogeneratedCommitMessage()

    def updateAutogeneratedCommitMessage(self):
        """Updates the autogenerated commit title and body based on segmentation changes and added screenshots."""
        segmentationLogic = slicer.modules.segmentations.logic()
        segmentation = self.logic.segmentationNode.GetSegmentation()
        currentSegmentIDs = segmentation.GetSegmentIDs()

        removedSegmentNames = set()
        for segmentID,segmentName in self.segmentNamesByID.items():
            if segmentID not in currentSegmentIDs:
                removedSegmentNames.add(segmentName)

        addedSegmentNames = set()
        modifiedSegmentNames = set()
        for segmentID in currentSegmentIDs:
            segment = segmentation.GetSegment(segmentID)
            if segmentID not in self.segmentNamesByID:
                addedSegmentNames.add(segment.GetName())
            elif segmentationLogic.GetSegmentStatus(segment) != segmentationLogic.NotStarted:
                modifiedSegmentNames.add(segment.GetName())
            segmentName = segment.GetName()
            if segmentName in self.segmentNamesByID.values() and segmentName != self.segmentNamesByID[segmentID]:
                self.segmentNamesByID[segmentID] = segmentName
                modifiedSegmentNames.add(segment.GetName())


        # Update UI
        autogeneratedTitle = f"Edited {self.logic.segmentationNode.GetName()}"
        autogeneratedBody = "Edits:\n"
        if len(modifiedSegmentNames) > 0:
            autogeneratedTitle += f" - {len(modifiedSegmentNames)} modified"
            autogeneratedBody += "Modified segments:\n" + "\n".join(f"- {name}" for name in sorted(list(modifiedSegmentNames)))
        if len(addedSegmentNames) > 0:
            autogeneratedTitle += f" - {len(addedSegmentNames)} added"
            autogeneratedBody += "\nAdded segments:\n" + "\n".join(f"- {name}" for name in sorted(list(addedSegmentNames)))
        if len(removedSegmentNames) > 0:
            autogeneratedTitle += f" - {len(removedSegmentNames)} removed"
            autogeneratedBody += "\nRemoved segments:\n" + "\n".join(f"- {name}" for name in sorted(list(removedSegmentNames)))

        self.annotateUI.messageTitle.text = autogeneratedTitle
        self.annotateUI.autogeneratedCommitText.plainText = f"{autogeneratedBody.strip()}"
        slicer.util.showStatusMessage(f"MorphoDepot commit message updated.")

    def onCommit(self):
        with slicer.util.tryWithErrorDisplay("Failed to commit and push", waitCursor=True):
            slicer.util.showStatusMessage(f"Committing and pushing")
            message = self.annotateUI.messageTitle.text
            if message == "":
                slicer.util.messageBox("You must provide a commit message (title required, body optional)")
                return
            body = self.annotateUI.messageBody.plainText
            if body != "":
                message = f"{message}\n\n{body}"
            autogeneratedText = self.annotateUI.autogeneratedCommitText.plainText
            if autogeneratedText:
                message += f"\n\n{autogeneratedText}"
            if self.logic.commitAndPush(message):
                self.annotateUI.messageTitle.text = ""
                self.annotateUI.messageBody.plainText = ""
                slicer.util.showStatusMessage(f"Commit and push complete")
                self.updateAnnotatePRList()
                self.annotateUI.reviewButton.enabled = True
            else:
                path = os.path.normpath(self.configureUI.repoDirectory.currentPath)
                slicer.util.messageBox(f"Commit failed.\nYour repository conflicts with what's on github. Copy your work from {path} and then delete the local repository folder and restart the issues.")
                slicer.util.showStatusMessage(f"Commit and push failed")

    def onRequestReview(self):
        """Create a checkpoint if need, then mark issue as ready for review"""
        with slicer.util.tryWithErrorDisplay("Failed to request review", waitCursor=True):
            slicer.util.showStatusMessage(f"Marking pull request for review")
            pr = self.logic.issuePR(role="segmenter")
            if not pr:
                self.onCommit()
            prURL = self.logic.requestReview()
            self.updateAnnotatePRList()
            self.annotateUI.messageTitle.text = ""
            self.annotateUI.messageBody.plainText = ""

    def onRepoDirectoryChanged(self):
        logging.info(f"Setting repoDirectory to be {os.path.normpath(self.configureUI.repoDirectory.currentPath)}")
        self.logic.setLocalRepositoryDirectory(os.path.normpath(self.configureUI.repoDirectory.currentPath))

    def onGitPathChanged(self):
        logging.info(f"Setting gitPath to be {os.path.normpath(self.configureUI.gitPath.currentPath)}")
        qt.QSettings().setValue("MorphoDepot/gitPath", os.path.normpath(self.configureUI.gitPath.currentPath))
        self.setupLogic()
        self.enter()

    def onGhPathChanged(self):
        logging.info(f"Setting ghPath to be {os.path.normpath(self.configureUI.ghPath.currentPath)}")
        qt.QSettings().setValue("MorphoDepot/ghPath", os.path.normpath(self.configureUI.ghPath.currentPath))
        self.setupLogic()
        self.enter()

    # Review
    def updateReviewPRList(self):
        with slicer.util.tryWithErrorDisplay("Failed to update PR list", waitCursor=True):
            slicer.util.showStatusMessage(f"Updating PRs")
            self.reviewUI.prList.clear()
            self.prsByItem = {}
            prList = self.logic.prList(role="reviewer")
            for pr in prList:
                prStatus = 'draft' if pr['isDraft'] else 'ready for review'
                prTitle = f"{pr['issueTitle']} {pr['repository']['nameWithOwner']}: {pr['title']} ({prStatus})"
                item = qt.QListWidgetItem(prTitle)
                self.prsByItem[item] = pr
                self.reviewUI.prList.addItem(item)
            slicer.util.showStatusMessage(f"{len(prList)} prs")

    def onPRDoubleClicked(self, item):
        repoDirectory = self.logic.localRepositoryDirectory()
        pr = self.prsByItem[item]
        if slicer.util.confirmOkCancelDisplay("Close scene and load PR?"):
            with slicer.util.tryWithErrorDisplay("Failed to load PR", waitCursor=True):
                slicer.util.showStatusMessage(f"Loading {item.text()}")
                self.reviewUI.currentPRLabel.text = f"PR: {item.text()}"
                slicer.mrmlScene.Clear()
                if self.logic.loadPR(pr, repoDirectory):
                    self.reviewUI.prCollapsibleButton.enabled = True
                    slicer.util.showStatusMessage(f"Start reviewing {item.text()}")
                else:
                    slicer.util.showStatusMessage(f"PR load failed")

    def onRequestChanges(self):
        with slicer.util.tryWithErrorDisplay("Failed to request changes", waitCursor=True):
            slicer.util.showStatusMessage(f"Requesting changes")
            message = self.reviewUI.reviewMessage.plainText
            self.logic.requestChanges(message)
            self.reviewUI.reviewMessage.plainText = ""
            slicer.util.showStatusMessage(f"Changes requested")
            self.updateReviewPRList()

    def onApprove(self):
        with slicer.util.tryWithErrorDisplay("Failed to approve PR", waitCursor=True):
            slicer.util.showStatusMessage(f"Approving")
            prURL = self.logic.approvePR()
            self.reviewUI.reviewMessage.plainText = ""
            self.updateReviewPRList()

    # Release
    def onRefreshReleaseTab(self):
        with slicer.util.tryWithErrorDisplay("Failed to refresh repositories", waitCursor=True):
            slicer.util.showStatusMessage("Fetching owned repositories...")
            self.releaseUI.repoList.clear()
            self.releaseUI.makeReleaseButton.enabled = False
            self.releaseUI.releasesCollapsibleButton.enabled = False
            self.releaseUI.currentRepoLabel.text = "No repository loaded"
            self.releaseUI.currentVersionLabel.text = "Current version: None"
            self.releaseUI.openReleasePageButton.enabled = False
            self.reposByItem = {}
            ownedRepos = self.logic.ownedRepoList()
            for repo in ownedRepos:
                item = qt.QListWidgetItem(repo['nameWithOwner'])
                self.reposByItem[item] = repo
                self.releaseUI.repoList.addItem(item)
            slicer.util.showStatusMessage(f"Found {len(ownedRepos)} owned repositories.")

    def onReleaseRepoDoubleClicked(self, item):
        repoData = self.reposByItem[item]
        slicer.util.showStatusMessage(f"Loading repository {repoData['nameWithOwner']}...")
        if slicer.util.confirmOkCancelDisplay("Close scene and load repository?"):
            slicer.mrmlScene.Clear()
            with slicer.util.tryWithErrorDisplay("Failed to load repository", waitCursor=True):
                if self.logic.loadRepoForRelease(repoData):
                    self.releaseUI.currentRepoLabel.text = f"Loaded: {repoData['nameWithOwner']}"
                    self.releaseUI.releasesCollapsibleButton.enabled = True
                    self.releaseUI.makeReleaseButton.enabled = True
                    self.updateCurrentVersionLabel()
                    slicer.util.showStatusMessage(f"Repository {repoData['nameWithOwner']} loaded.")

    def updateCurrentVersionLabel(self):
        """Gets releases and updates the version label and open page button."""
        self.releaseUI.openReleasePageButton.enabled = False
        releases = self.logic.getReleases()
        if releases:
            latestRelease = releases[0] # gh cli returns latest first
            self.releaseUI.currentVersionLabel.text = f"Current version: {latestRelease['tagName']}"
            self.releaseUI.openReleasePageButton.enabled = True
        else:
            self.releaseUI.currentVersionLabel.text = "Current version: None"

    def onOpenReleasePage(self):
        """Opens the GitHub releases page for the current repository."""
        if self.logic.localRepo:
            nameWithOwner = self.logic.nameWithOwner("origin")
            releasesURL = qt.QUrl(f"https://github.com/{nameWithOwner}/releases")
            qt.QDesktopServices.openUrl(releasesURL)

    # Search
    def onRefreshSearch(self):
        with slicer.util.tryWithErrorDisplay("Failed to refresh search cache", waitCursor=True):
            slicer.util.showStatusMessage("Refreshing search cache...")
            self.logic.refreshSearchCache()
            self.searchUI.searchForm.searchBox.setPlaceholderText("Search...")
            self.searchUI.searchForm.topWidget.enabled = True
            self.doSearch()

    def doSearch(self):
        criteria = self.searchUI.searchForm.criteria()
        results = self.logic.search(criteria)
        self.updateSearchResults(results)

    def repoDataKetToRepoNameAndOwner(self, repoDataKey):
        nameWithOwnerSplit = repoDataKey.split('-')
        repoName = "-".join(nameWithOwnerSplit[:-1])
        owner = nameWithOwnerSplit[-1]
        return repoName,owner

    def updateSearchResults(self, results):
        slicer.util.showStatusMessage(f"Updating search results")
        self.searchUI.resultsModel.clear()
        self.searchResultsByItem = {}
        headers = ["Repository", "Owner", "Species", "Modality", "Spacing", "Dimensions"]
        self.searchUI.resultsModel.setHorizontalHeaderLabels(headers)
        for repoDataKey, repoData in results.items():
            repoName,owner = self.repoDataKetToRepoNameAndOwner(repoDataKey)
            species = repoData.get('species', [None, "N/A"])[1]
            modality = repoData.get('modality', [None, "N/A"])[1]

            spacingText = "N/A"
            spacingStr = repoData.get('scanSpacing')
            if spacingStr:
                try:
                    # The string is a tuple representation like "(0.5, 0.5, 0.9)"
                    spacingValues = [float(v) for v in spacingStr.strip("()").split(',')]
                    formattedValues = [f"{v:.3g}" for v in spacingValues]
                    spacingText = ", ".join(formattedValues)
                except (ValueError, IndexError, TypeError):
                    spacingText = "Invalid"

            dimensionsText = "N/A"
            dimensionsStr = repoData.get('scanDimensions')
            if dimensionsStr:
                try:
                    # The string is a tuple representation like "(512, 512, 300)"
                    dims = dimensionsStr.strip("()").split(',')
                    dimensionsText = " x ".join([d.strip() for d in dims])
                except:
                    dimensionsText = "Invalid"

            repoItem = qt.QStandardItem(repoName)
            ownerItem = qt.QStandardItem(owner)
            speciesItem = qt.QStandardItem(species)
            modalityItem = qt.QStandardItem(modality)
            spacingItem = qt.QStandardItem(spacingText)
            dimensionsItem = qt.QStandardItem(dimensionsText)

            # Store the full data in the first item of the row
            repoItem.setData(repoData, qt.Qt.UserRole)
            repoItem.setData(repoDataKey, qt.Qt.UserRole + 1)

            rowItems = [repoItem, ownerItem, speciesItem, modalityItem, spacingItem, dimensionsItem]
            tooltipText = json.dumps(repoData, indent=2)

            # Create a formatted HTML tooltip
            tooltipParts = [f"<b>{repoName}</b> by <b>{owner}</b><br><hr>"]
            for key in MorphoDepotAccessionForm.formQuestions.keys():
                if key in repoData:
                    questionText, answer = repoData[key]
                    answerStr = ", ".join(answer) if isinstance(answer, list) else str(answer)
                    displayAnswer = answerStr if answerStr else "<i>Not provided</i>"
                    tooltipParts.append(f"<i>{questionText}</i><br>{displayAnswer}<br>")
            tooltipText = "".join(tooltipParts)

            for item in rowItems:
                item.setToolTip(tooltipText)

            self.searchUI.resultsModel.appendRow(rowItems)

        self.searchUI.resultsTable.resizeColumnsToContents()
        slicer.util.showStatusMessage(f"{len(results.keys())} matching repositories")

    def onSearchResultsContextMenu(self, point):
        index = self.searchUI.resultsTable.indexAt(point)
        if not index.isValid():
            return

        item = self.searchUI.resultsModel.item(index.row(), 0)
        repoData = item.data(qt.Qt.UserRole)
        repoDataKey = item.data(qt.Qt.UserRole + 1)
        repoName, owner = self.repoDataKetToRepoNameAndOwner(repoDataKey)
        fullRepoName = f"{owner}/{repoName}"

        menu = qt.QMenu()
        openRepoAction = menu.addAction("Open Repository Page")
        previewAction = menu.addAction("Preview in Slicer")

        action = menu.exec_(self.searchUI.resultsTable.mapToGlobal(point))

        if action == openRepoAction:
            qt.QDesktopServices.openUrl(qt.QUrl(f"https://github.com/{fullRepoName}"))
        elif action == previewAction:
            self.previewRepository(fullRepoName)

    def onSearchResultsDoubleClicked(self, index):
        """Handle double-click on search results table to preview repository."""
        if not index.isValid():
            return

        item = self.searchUI.resultsModel.item(index.row(), 0)
        repoDataKey = item.data(qt.Qt.UserRole + 1)
        repoName, owner = self.repoDataKetToRepoNameAndOwner(repoDataKey)
        fullRepoName = f"{owner}/{repoName}"
        self.previewRepository(fullRepoName)

    def onMakeRelease(self):
        slicer.util.showStatusMessage("Creating new release...")
        releaseNotes = self.releaseUI.releaseCommentsEdit.plainText
        with slicer.util.tryWithErrorDisplay("Failed to create release", waitCursor=True):
            self.logic.createRelease(releaseNotes)
        self.releaseUI.releaseCommentsEdit.plainText = ""
        self.updateCurrentVersionLabel()
        slicer.util.showStatusMessage("New release created. You can add more comments on the GitHub release page.")

    def previewRepository(self, repoNameWithOwner):
        """Clones a repository and loads its data for previewing."""
        slicer.util.showStatusMessage(f"Previewing repository {repoNameWithOwner}...")
        if slicer.util.confirmOkCancelDisplay("Close scene and load repository for preview?"):
            slicer.mrmlScene.Clear()
            with slicer.util.tryWithErrorDisplay("Failed to load repository", waitCursor=True):
                self.logic.loadRepoForPreview(repoNameWithOwner)
            slicer.util.showStatusMessage(f"Repository {repoNameWithOwner} loaded for preview.")

class MorphoDepotAccessionForm():
    """Customized interface to collect data about MorphoDepot accessions"""

    sectionTitles = {
        1: "Acquisition type",
        2: "Accessioned specimen",
        3: "Commercially acquired or unaccessioned specimen",
        4: "Image data description",
        5: "Partial specimen",
        6: "Licensing",
        7: "Github"
    }

    formQuestions = {
        # each question is a tuple of question, answer options, and tooltip
        # This info is pure data, but is closely coupled to the GUI and validation code below for usability

        # section 1
        "specimenSource" : (
            "Is your data from a commercially acquired organism or from an accessioned specimen (i.e., from a natural history collection)?",
           ["Commercially acquired", "Accessioned specimen"],
           ""
        ),

        # section 2
        "iDigBioAccessioned" : (
            "Is your specimen's species in the iDigBio database?",
            ["Yes", "No"],
            ""
        ),
        "iDigBioURL" : (
            "Enter URL from iDigBio:",
            "",
            "Go to iDigBio portal, search for the specimen, click the link and paste the URL below (it should look something like this: https://www.idigbio.org/portal/records/b328320d-268e-4bfc-ae70-1c00f0891f89)"
        ),

        # section 3
        "species" : (
            "What is your specimen's species?",
            "",
            "Enter a valid genus and species for your specimen and use the 'Check species' button to confirm.  If unsure, use the GBIF web page to search"
        ),
        "biologicalSex" : (
            "What is your specimen's sex?",
            ["Male", "Female", "Unknown"],
            ""
        ),
        "developmentalStage" : (
            "What is your specimen's developmental stage?",
            ["Prenatal (fetus, embryo)", "Juvenile (neonatal to subadult)", "Adult"],
            ""
        ),

        # section 4
        "modality" : (
            "What is the modality of the acquisition?",
            ["Micro CT (or synchrotron)", "Medical CT", "MRI", "Lightsheet microscopy", "3D confocal microscopy", "Surface model (photogrammetry, structured light, or laser scanning)"],
            ""
        ),
        "contrastEnhancement" : (
            "Is there contrast enhancement treatment applied to the specimen (iodine, phosphotungstenic acid, gadolinium, casting agents, etc)?",
            ["Yes", "No"],
            ""
        ),
        "imageContents" : (
            "What is in the image?",
            ["Whole specimen", "Partial specimen"],
            ""
        ),

        # section 5
        "anatomicalAreas" : (
            "What anatomical area(s) is/are present in the scan?",
            ["Head and neck (e.g., cranium, mandible, proximal vertebral colum)", "Pectoral girdle", "Forelimb", "Trunk (e.g. body cavity, torso, spine, ribs)", "Pelvic girdle", "Hind limg", "Tail", "Other"],
            ""
        ),

        # section 6
        "redistributionAcknowledgement" : (
            "Acknowledgement:",
            ["I have the right to allow redistribution of this data."],
            ""
        ),
        "license" : (
            "Choose a license:",
            ["CC BY 4.0 (requires attribution, allows commercial usage)", "CC BY-NC 4.0 (requires attribution, non-commercial usage only)"],
            ""
        ),

        # section 7
        "githubRepoName" : (
            "What should the repository in your github account called? This needs to be unique value for your account.",
            "",
            "Name should be fairly short and contain only letters, numbers, and the dash, underscore, or dot characters."
        )
    }

    def __init__(self, workflowMode=False, validationCallback=None):
        """based on this form: https://docs.google.com/forms/d/1HbSL2lmslmeAggim4qlxjcyLy6KhQWcNPisrURA2Udo/edit"""
        self.workflowMode = workflowMode
        self.validationCallback = validationCallback
        sectionCount = 7
        self.form = qt.QWidget()
        layout = qt.QVBoxLayout()
        self.form.setLayout(layout)
        if not self.workflowMode:
            self.scrollArea = qt.QScrollArea()
            self.scrollArea.setWidget(self.form)
            self.scrollArea.setWidgetResizable(True)
            self.topWidget = self.scrollArea
        else:
            self.topWidget = self.form
        self.sectionWidgets = {}
        self.sectionSections = {}
        for section in range(1,1+sectionCount):
            sectionWidget = qt.QWidget()
            sectionLayout = qt.QVBoxLayout()
            sectionWidget.setLayout(sectionLayout)
            sectionLabel = qt.QLabel(f"Section {section}: {MorphoDepotAccessionForm.sectionTitles[section]}")
            sectionLayout.addWidget(sectionLabel)
            sectionSection = qt.QWidget()
            sectionSectionLayout = qt.QVBoxLayout()
            sectionSection.setLayout(sectionSectionLayout)
            self.sectionSections[section] = sectionSection

            if self.workflowMode:
                bottomRow = qt.QWidget()
                bottomRowLayout = qt.QHBoxLayout()
                bottomRow.setLayout(bottomRowLayout)
                prev = qt.QPushButton("Previous")
                next = qt.QPushButton("Next")
                bottomRowLayout.addWidget(prev)
                bottomRowLayout.addWidget(next)
                sectionLayout.addWidget(bottomRow)
                if section > 1:
                    prev.connect("clicked()", lambda section=section: self.showSection(section-1))
                else:
                    prev.enabled = False
                if section < sectionCount:
                    next.connect("clicked()", lambda section=section: self.showSection(section+1))
                else:
                    next.enabled = False

            self.sectionWidgets[section] = sectionWidget
            self.form.layout().addWidget(sectionWidget)

        form = MorphoDepotAccessionForm.formQuestions
        self.questions = {}

        # section 1
        layout = self.sectionWidgets[1].layout()
        q,a,t = form["specimenSource"]
        self.questions["specimenSource"] = FormRadioQuestion(q, a, self.validateForm)
        layout.addWidget(self.questions["specimenSource"].questionBox)

        # section 2
        layout = self.sectionWidgets[2].layout()
        q,a,t = form["iDigBioAccessioned"]
        self.questions["iDigBioAccessioned"] = FormRadioQuestion(q, a, self.validateForm)
        layout.addWidget(self.questions["iDigBioAccessioned"].questionBox)
        self.gotoiDigBioButton = qt.QPushButton("Open iDigBio")
        self.gotoiDigBioButton.connect("clicked()", lambda : qt.QDesktopServices.openUrl(qt.QUrl("https://iDigBio.org")))
        layout.addWidget(self.gotoiDigBioButton)
        q,a,t = form["iDigBioURL"]
        self.questions["iDigBioURL"] = FormTextQuestion(q, self.validateForm)
        self.questions["iDigBioURL"].questionBox.toolTip = t
        layout.addWidget(self.questions["iDigBioURL"].questionBox)

        # section 3
        layout = self.sectionWidgets[3].layout()
        q,a,t = form["species"]
        self.questions["species"] = FormSpeciesQuestion(q, self.validateForm)
        self.questions["species"].questionBox.toolTip = t
        layout.addWidget(self.questions["species"].questionBox)
        self.gotoGBIFButton = qt.QPushButton("Open GBIF")
        self.gotoGBIFButton.connect("clicked()", lambda : qt.QDesktopServices.openUrl(qt.QUrl("https://gbif.org")))
        layout.addWidget(self.gotoGBIFButton)
        q,a,t = form["biologicalSex"]
        self.questions["biologicalSex"] = FormRadioQuestion(q, a,  self.validateForm)
        layout.addWidget(self.questions["biologicalSex"].questionBox)
        q,a,t = form["developmentalStage"]
        self.questions["developmentalStage"] = FormRadioQuestion(q, a, self.validateForm)
        layout.addWidget(self.questions["developmentalStage"].questionBox)

        # section 4
        layout = self.sectionWidgets[4].layout()
        q,a,t = form["modality"]
        self.questions["modality"] = FormRadioQuestion(q, a, self.validateForm)
        layout.addWidget(self.questions["modality"].questionBox)
        q,a,t = form["contrastEnhancement"]
        self.questions["contrastEnhancement"] = FormRadioQuestion("Is there contrast enhancement treatment applied to the specimen (iodine, phosphotungstenic acid, gadolinium, casting agents, etc)?", ["Yes", "No"], self.validateForm)
        layout.addWidget(self.questions["contrastEnhancement"].questionBox)
        q,a,t = form["imageContents"]
        self.questions["imageContents"] = FormRadioQuestion(q, a, self.validateForm)
        layout.addWidget(self.questions["imageContents"].questionBox)

        # section 5
        layout = self.sectionWidgets[5].layout()
        q,a,t = form["anatomicalAreas"]
        self.questions["anatomicalAreas"] = FormCheckBoxesQuestion(q, a, self.validateForm)
        layout.addWidget(self.questions["anatomicalAreas"].questionBox)

        # section 6
        layout = self.sectionWidgets[6].layout()
        q,a,t = form["redistributionAcknowledgement"]
        self.questions["redistributionAcknowledgement"] = FormCheckBoxesQuestion(q, a, self.validateForm)
        layout.addWidget(self.questions["redistributionAcknowledgement"].questionBox)
        q,a,t = form["license"]
        self.questions["license"] = FormRadioQuestion(q, a, self.validateForm)
        self.questions["license"].optionButtons[a[0]].checked=True
        layout.addWidget(self.questions["license"].questionBox)

        # section 7
        layout = self.sectionWidgets[7].layout()
        q,a,t = form["githubRepoName"]
        self.questions["githubRepoName"] = FormTextQuestion(q, self.validateForm)
        self.questions["githubRepoName"].questionBox.toolTip = t
        layout.addWidget(self.questions["githubRepoName"].questionBox)

        if self.workflowMode:
            self.showSection(1)

    def showSection(self, section):
        if self.workflowMode:
            for sectionWidget in self.sectionWidgets.values():
                sectionWidget.hide()
            self.sectionWidgets[section].show()

    def validateForm(self, arguments=None):

        # first, update the visibility of dependent sections
        if self.questions["specimenSource"].answer() == "Commercially acquired":
            self.sectionWidgets[2].hide()
            self.sectionWidgets[3].show()
        else:
            self.sectionWidgets[2].show()
            if self.questions["iDigBioAccessioned"].answer() == "Yes":
                self.questions["iDigBioURL"].questionBox.show()
                self.gotoiDigBioButton.show()
                self.sectionWidgets[3].hide()
            else:
                self.questions["iDigBioURL"].questionBox.hide()
                self.gotoiDigBioButton.hide()
                self.sectionWidgets[3].show()
        if self.questions["imageContents"].answer() == "Partial specimen":
            self.sectionWidgets[5].show()
        else:
            self.sectionWidgets[5].hide()

        # then check if required elements have been filled out
        valid = True

        section3Required = False
        if self.questions["specimenSource"].answer() == "":
            valid = False
        if self.questions["specimenSource"].answer() == "Commercially acquired":
            section3Required = True
        elif self.questions["specimenSource"].answer() == "Accessioned specimen":
            if self.questions["iDigBioAccessioned"].answer() == "No":
                section3Required = True
            elif self.questions["iDigBioAccessioned"].answer() == "Yes":
                section3Required = False
                if not self.questions["iDigBioURL"].answer().startswith("https://portal.idigbio.org/portal/records"):
                    valid = False
        else:
            valid = False
        if section3Required:
            valid = valid and self.questions["species"].answer() != ""
            valid = valid and (len(self.questions["species"].answer().split()) == 2)
            valid = valid and self.questions["biologicalSex"].answer() != ""
            valid = valid and self.questions["developmentalStage"].answer() != ""
        valid = valid and self.questions["modality"].answer() != ""
        valid = valid and self.questions["contrastEnhancement"].answer() != ""
        valid = valid and self.questions["imageContents"].answer() != ""
        if self.questions["imageContents"].answer() == "Partial specimen":
            valid = valid and self.questions["anatomicalAreas"].answer() != []
        valid = valid and self.questions["redistributionAcknowledgement"].answer() != ""
        valid = valid and self.questions["license"].answer() != ""
        valid = valid and self.questions["githubRepoName"].answer() != ""
        repoNameRegex = r"^(?:([a-zA-Z\d]+(?:-[a-zA-Z\d]+)*)/)?([\w.-]+)$"
        valid = valid and (re.match(repoNameRegex, self.questions["githubRepoName"].answer()) != None)
        self.validationCallback(valid)

    def accessionData(self):
        data = {}
        for key in MorphoDepotAccessionForm.formQuestions.keys():
            data[key] = (self.questions[key].questionText.document.toPlainText(), self.questions[key].answer())
        return data


class FormBaseQuestion():
    def __init__(self, question):
        self.questionBox = qt.QWidget()
        self.questionLayout = qt.QVBoxLayout()
        self.questionBox.setLayout(self.questionLayout)
        self.questionText = qt.QTextEdit(question)
        self.questionText.readOnly = True
        self.questionText.maximumHeight = self.heightForString(question)
        self.questionLayout.addWidget(self.questionText)

    def heightForString(self, s):
        return max(len(s) // 2.5, 30)

class FormRadioQuestion(FormBaseQuestion):
    def __init__(self, question, options, validator):
        super().__init__(question)
        self.optionButtons = {}
        for option in options:
            self.optionButtons[option] = qt.QRadioButton(option)
            self.optionButtons[option].connect("clicked()", validator)
            self.questionLayout.addWidget(self.optionButtons[option])

    def answer(self):
        for option,button in self.optionButtons.items():
            if button.checked:
                return option
        return ""


class FormCheckBoxesQuestion(FormBaseQuestion):
    def __init__(self, question, options, validator):
        super().__init__(question)
        self.optionButtons = {}
        for option in options:
            self.optionButtons[option] = qt.QCheckBox(option)
            self.optionButtons[option].connect("clicked()", validator)
            self.questionLayout.addWidget(self.optionButtons[option])

    def answer(self):
        answers = []
        for option,button in self.optionButtons.items():
            if button.checked:
                answers.append(option)
        return answers

class FormTextQuestion(FormBaseQuestion):
    def __init__(self, question, validator):
        super().__init__(question)
        self.answerText = qt.QLineEdit()
        self.answerText.connect("textChanged(QString)", validator)
        self.questionLayout.addWidget(self.answerText)

    def answer(self):
        return self.answerText.text

class FormSpeciesQuestion(FormTextQuestion):
    def __init__(self, question, validator):
        super().__init__(question, validator)
        self.checkSpeciesButton = qt.QPushButton("Check species")
        self.checkSpeciesButton.connect("clicked()", self.onCheckSpecies)
        self.questionLayout.addWidget(self.checkSpeciesButton)
        self.searchButton = qt.QPushButton()
        self.searchButton.setIcon(qt.QIcon(qt.QPixmap(":/Icons/Search.png")))
        self.searchButton.connect("clicked()", self.onSearchSpecies)
        self.questionLayout.addWidget(self.searchButton)
        self.speciesInfo = qt.QLabel()
        self.questionLayout.addWidget(self.speciesInfo)
        self.searchDialog = None

    def _setSpeciesInfoLabel(self, result):
        requiredKeys = ['matchType', 'rank', 'canonicalName', 'kingdom', 'phylum', 'class', 'order', 'family', 'genus', 'species']
        for key in requiredKeys:
            if key not in result:
                result[key] = "missing"
        if result['matchType'] == "NONE":
            labelText = "No match"
        elif result['rank'] != "SPECIES":
            labelText = f"Not a species ({result['canonicalName']} is rank {result['rank']})"
        else:
            labelText = f"Kingdom: {result['kingdom']}, Phylum: {result['phylum']}, Class: {result['class']},\nOrder: {result['order']}, Family: {result['family']}, Genus: {result['genus']}, Species: {result['species']}"
        self.speciesInfo.text = labelText


    def onSearchSpecies(self):
        if self.searchDialog is None:
            self.searchDialog = qt.QDialog()
            self.searchDialog.setWindowTitle("Search for species")
            self.searchDialogLayout = qt.QVBoxLayout()
            self.searchDialog.setLayout(self.searchDialogLayout)
            self.searchEntry = qt.QLineEdit()
            self.searchEntry.connect("textChanged(QString)", self.onSearchTextChanged)
            self.searchDialogLayout.addWidget(self.searchEntry)
            self.searchResults = qt.QListWidget()
            self.searchResults.connect("itemClicked(QListWidgetItem*)", self.onSearchResultClicked)
            self.searchDialogLayout.addWidget(self.searchResults)
            self.searchDialog.setModal(True)
            mainWindow = slicer.util.mainWindow()
            self.searchDialog.move(mainWindow.geometry.center() - self.searchDialog.rect.center())
        self.searchEntry.text = self.answerText.text
        self.searchDialog.show()

    def onSearchTextChanged(self, text):
        import pygbif
        self.searchResults.clear()
        if len(text) < 3:
            return
        try:
            results = pygbif.species.name_suggest(q=text, rank="species")
        except Exception as e:
            slicer.util.errorDisplay(f"Error searching for species: {e}")
            return
        for result in results:
            if result['rank'] == "SPECIES":
                item = qt.QListWidgetItem(f"{result['canonicalName']} ({result['kingdom']})")
                item.setData(qt.Qt.UserRole, result)
                self.searchResults.addItem(item)

    def onSearchResultClicked(self, item):
        result = item.data(qt.Qt.UserRole)
        self.answerText.text = result['canonicalName']
        self.searchDialog.hide()
        self._setSpeciesInfoLabel(result)

    def onCheckSpecies(self):
        import pygbif
        result = pygbif.species.name_backbone(self.answerText.text)
        self._setSpeciesInfoLabel(result)

    def answer(self):
        return self.answerText.text


class MorphoDepotSearchForm():
    """Customized interface to specify MorphoDepot searches"""

    questionsToIgnore = ['iDigBioURL', 'species', 'redistributionAcknowledgement', "githubRepoName"]

    def __init__(self, updateCallback=lambda : None):
        self.updateCallback = updateCallback
        self.form = qt.QWidget()
        layout = qt.QVBoxLayout()
        self.form.setLayout(layout)
        self.scrollArea = qt.QScrollArea()
        self.scrollArea.setWidget(self.form)
        self.scrollArea.setWidgetResizable(True)
        self.topWidget = self.scrollArea
        self.searchFormLayout = qt.QFormLayout()
        self.topWidget.setLayout(self.searchFormLayout)
        self.searchBox = ctk.ctkSearchBox()
        self.searchFormLayout.addRow(self.searchBox)
        self.searchBox.textChanged.connect(self.updateCallback)
        self.searchBox.setPlaceholderText("Fetch repository data to search...")

        self.comboBoxesByQuestion = {}
        questions = MorphoDepotAccessionForm.formQuestions
        for question, questionData in questions.items():
            if question not in MorphoDepotSearchForm.questionsToIgnore:
                comboBox = ctk.ctkCheckableComboBox()
                self.searchFormLayout.addRow(question, comboBox)
                for option in questionData[1]:
                    comboBox.addItem(option)
                model = comboBox.checkableModel()
                for row in range(model.rowCount()):
                    index = model.index(row,0)
                    comboBox.setCheckState(index, qt.Qt.Checked)
                comboBox.checkedIndexesChanged.connect(self.updateCallback)
                self.comboBoxesByQuestion[question] = comboBox

    def criteria(self):
        criteria = {"freeText": self.searchBox.text}
        questions = MorphoDepotAccessionForm.formQuestions
        for question, questionData in questions.items():
            if question not in MorphoDepotSearchForm.questionsToIgnore:
                comboBox = self.comboBoxesByQuestion[question]
                model = comboBox.checkableModel()
                criteria[question] = []
                for row in range(model.rowCount()):
                    index = model.index(row,0)
                    if comboBox.checkState(index) == qt.Qt.Checked:
                        criteria[question].append(questionData[1][row])
        return criteria




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

    def __init__(self, progressMethod = None) -> None:
        """Called when the logic class is instantiated. Can be used for initializing member variables."""
        ScriptedLoadableModuleLogic.__init__(self)
        self.segmentationNode = None
        self.segmentationPath = None
        self.localRepo = None
        self.currentIssue = None
        self.progressMethod = progressMethod if progressMethod else lambda *args : None

        # for Search
        self.repoDataByNameWithOwner = {}

        self.executableExtension = '.exe' if os.name == 'nt' else ''
        modulePath = os.path.split(slicer.modules.morphodepot.path)[0]
        self.resourcesPath = os.path.normpath(modulePath + "/Resources")
        self.pixiInstallDir = os.path.normpath(self.resourcesPath + "/pixi")

        # use configured git and gh paths if selected,
        # else use system installed git and gh if available
        # Optionally install with pixi, but only if requireSystemGit is False
        # note: normpath returns "." when given ""
        gitPath = os.path.normpath(slicer.util.settingsValue("MorphoDepot/gitPath", "") or "")
        ghPath = os.path.normpath(slicer.util.settingsValue("MorphoDepot/ghPath", "") or "")
        if not gitPath or gitPath == "" or gitPath == ".":
            gitPath = shutil.which("git")
        if not ghPath or ghPath == "" or ghPath == ".":
            ghPath = shutil.which("gh")
        if gitPath and ghPath:
            self.gitExecutablePath = gitPath
            self.ghExecutablePath = ghPath

        qt.QSettings().setValue("MorphoDepot/gitPath", self.gitExecutablePath)
        qt.QSettings().setValue("MorphoDepot/ghPath", self.ghExecutablePath)

    def slicerVersionCheck(self):
        return hasattr(slicer.vtkSegment, "SetTerminology")

    def localRepositoryDirectory(self):
        repoDirectory = os.path.normpath(slicer.util.settingsValue("MorphoDepot/repoDirectory", "") or "")
        if repoDirectory == "" or repoDirectory == ".":
            defaultScenePath = os.path.normpath(slicer.app.defaultScenePath)
            defaultRepoDir = os.path.join(defaultScenePath, "MorphoDepot")
            self.setLocalRepositoryDirectory(defaultRepoDir)
            repoDirectory = defaultRepoDir
        return repoDirectory

    def setLocalRepositoryDirectory(self, repoDir):
        qt.QSettings().setValue("MorphoDepot/repoDirectory", repoDir)

    def checkPythonDependencies(self):
        """See if pygbif and idigbio are available.
        The GitPython package is installed by default in slicer.
        """
        try:
            import pygbif
        except ModuleNotFoundError:
            return False

        try:
            import idigbio
        except ModuleNotFoundError:
            return False

        return True

    def installPythonDependencies(self):
        """Install pygbif and idigbio if needed
        """
        try:
            import pygbif
        except ModuleNotFoundError:
            self.progressMethod(f"Installing pygbif")
            slicer.util.pip_install("pygbif")
            import pygbif

        try:
            import idigbio
        except ModuleNotFoundError:
            self.progressMethod(f"Installing idigbio")
            slicer.util.pip_install("idigbio")
            import idigbio

    def checkCommand(self, command):
        try:
            completedProcess = subprocess.run(command, capture_output=True)
            returnCode = completedProcess.returncode
            stdout = completedProcess.stdout
            stderr = completedProcess.stderr
        except Exception as e:
            stdout =  ""
            stderr = str(e)
            returnCode = -1
        if returnCode != 0:
            self.progressMethod(f"{command} failed to run, returned {returnCode}")
            self.progressMethod(stdout)
            self.progressMethod(stderr)
            return False
        return True

    def checkGitDependencies(self):
        """Check that git, and gh are available
        """
        if not (self.gitExecutablePath and self.ghExecutablePath):
            self.progressMethod("git/gh paths are not set")
            return False
        if not (os.path.exists(self.gitExecutablePath) and os.path.exists(self.ghExecutablePath)):
            self.progressMethod("bad git/gh paths")
            self.progressMethod(f"git path is {self.gitExecutablePath}")
            self.progressMethod(f"gh path is {self.ghExecutablePath}")
            return False
        if not self.checkCommand([self.gitExecutablePath, '--version']):
            return False
        if not self.checkCommand([self.ghExecutablePath, 'auth', 'status']):
            return False
        return True

    def gh(self, command):
        """Execute `gh` command.  Multiline input string accepted for readablity.
        Do not include `gh` in the command string"""
        if not self.ghExecutablePath or self.ghExecutablePath == "":
            logging.error("Error, gh not found")
            return "Error, gh not found"
        if command.__class__() == "":
            commandList = command.replace("\n", " ").split()
        elif command.__class__() == []:
            commandList = command
        else:
            logging.error("command must be string or list")
        self.progressMethod(" ".join(commandList))
        fullCommandList = [self.ghExecutablePath] + commandList

        originalLocale = locale.setlocale(locale.LC_ALL)
        locale.setlocale(locale.LC_ALL, "en_US.UTF-8")
        process = slicer.util.launchConsoleProcess(fullCommandList)
        result = process.communicate()
        locale.setlocale(locale.LC_ALL, originalLocale)
        if process.returncode != 0:
            error_message = f"gh command failed: {' '.join(commandList)}\nOutput: {result}"
            logging.error(error_message)
            self.progressMethod(f"gh command error: {result}")
            raise RuntimeError(error_message)
        self.progressMethod(f"gh command finished: {result}")
        return result[0]

    def ghJSON(self, command):
        """Wrapper around gh that returns json loaded data or an empty list on error"""
        jsonString = self.gh(command)
        if jsonString:
            return json.loads(jsonString)
        return []

    def morphoRepos(self):
        # TODO: generalize for other topics
        query = """
            query($searchQuery: String!, $after: String) {
              search(query: $searchQuery, type: REPOSITORY, first: 100, after: $after) {
                repositoryCount
                edges {
                  node {
                    ... on Repository {
                      name
                      owner {
                        login
                      }
                    }
                  }
                }
                pageInfo {
                  endCursor
                  hasNextPage
                }
              }
            }
        """
        all_repos = []
        hasNextPage = True
        after_cursor = None
        while hasNextPage:
            result = self.ghJSON(['api', 'graphql', '--cache', '5m', '-f', f'query={query}', '-f', 'searchQuery=topic:morphodepot fork:true', '-F', f'after={after_cursor if after_cursor else "null"}'])
            if result and 'data' in result and 'search' in result['data']:
                all_repos.extend([edge['node'] for edge in result['data']['search']['edges']])
                hasNextPage = result['data']['search']['pageInfo']['hasNextPage']
                after_cursor = result['data']['search']['pageInfo']['endCursor']
            else:
                hasNextPage = False
        return all_repos

    def issueList(self):
        repoList = self.morphoRepos()
        candiateIssueList = self.ghJSON(f"search issues --limit 1000 --assignee=@me --state open --json repository,title,number")
        repoNamesWithOwner = [f"{repo['owner']['login']}/{repo['name']}" for repo in repoList]
        issueList = [issue for issue in candiateIssueList if issue['repository']['nameWithOwner'] in repoNamesWithOwner]
        return issueList

    def ownedRepoList(self):
        repos = self.ghJSON(f"search repos --limit 1000 --owner=@me --json name,owner -- topic:morphodepot")
        for repo in repos:
            repo['nameWithOwner'] = f"{repo['owner']['login']}/{repo['name']}"
        return repos

    def prList(self, role="segmenter"):
        repoList = self.morphoRepos()
        repoNamesWithOwner = [f"{repo['owner']['login']}/{repo['name']}" for repo in repoList]
        if role == "segmenter":
            searchString = "--author=@me"
        elif role == "reviewer":
            searchString = "--owner=@me"
        jsonFields = "title,number,author,isDraft,updatedAt,repository"
        candidatePRList = self.ghJSON(f"search prs --limit 1000 --state open --json {jsonFields} {searchString}")
        prList = [pr for pr in candidatePRList if pr['repository']['nameWithOwner'] in repoNamesWithOwner]
        for pr in prList:
            issues = self.ghJSON(f"issue list --repo {pr['repository']['nameWithOwner']} --json title,number --state open")
            pr['issueTitle'] = "issue not found"
            for issue in issues:
                if pr['title'] == f"issue-{issue['number']}":
                    pr['issueTitle'] = issue['title']
        return prList

    def repositoryList(self):
        repositories = json.loads(self.gh("repo list --json name"))
        repositoryList = [r['name'] for r in repositories]
        return repositoryList

    def ensureUpstreamExists(self):
        if not "upstream" in self.localRepo.remotes:
            # no upstream, so this is an issue assigned to the owner of the repo
            self.localRepo.create_remote("upstream", list(self.localRepo.remotes[0].urls)[0])

    def loadIssue(self, issue, repoDirectory):
        self.currentIssue = issue
        self.progressMethod(f"Loading issue {issue} into {repoDirectory}")
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
            self.ensureUpstreamExists()
            pullResult = self.localRepo.git.pull("--rebase", "upstream", "main")
            self.progressMethod(pullResult)
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
        repositoryName = f"{pr['author']['login']}/{pr['repository']['name']}"
        localDirectory = f"{repoDirectory}/{pr['repository']['name']}-{branchName}"
        self.progressMethod(f"Loading issue {repositoryName} into {localDirectory}")

        if not os.path.exists(localDirectory):
            self.gh(f"repo clone {repositoryName} {localDirectory}")
        self.localRepo = git.Repo(localDirectory)
        self.ensureUpstreamExists()
        self.localRepo.remotes.origin.fetch()
        self.localRepo.git.checkout(branchName)
        if not self.localRepo.head.ref.tracking_branch():
            originMain = self.localRepo.remotes.origin.refs.main
            self.localRepo.head.ref.set_tracking_branch(originMain)
        try:
            self.localRepo.remotes.origin.pull(rebase=True)
        except git.exc.GitCommandError:
            self.progressMethod(f"Error pulling origin")
            return False

        self.loadFromLocalRepository()
        return True

    def loadRepoForRelease(self, repoData):
        repoName = repoData['name']
        repoNameWithOwner = repoData['nameWithOwner']
        localDirectory = os.path.join(self.localRepositoryDirectory(), repoName)

        if not os.path.exists(localDirectory):
            self.gh(f"repo clone {repoNameWithOwner} {localDirectory}")

        self.localRepo = git.Repo(localDirectory)
        self.localRepo.git.checkout("main")
        self.loadFromLocalRepository(remoteName="origin", configuration="release")
        return True

    def loadRepoForPreview(self, repoNameWithOwner):
        repoName = repoNameWithOwner.split('/')[1]
        localDirectory = os.path.join(self.localRepositoryDirectory(), repoName)

        if not os.path.exists(localDirectory):
            print(f"repo clone {repoNameWithOwner} {localDirectory}")
            self.gh(f"repo clone {repoNameWithOwner} {localDirectory}")

        self.localRepo = git.Repo(localDirectory)
        self.localRepo.git.checkout("main")
        self.loadFromLocalRepository(remoteName="origin", configuration="preview")
        return True

    def loadFromLocalRepository(self, remoteName="upstream", configuration="segment"):
        localDirectory = self.localRepo.working_dir
        branchName = self.localRepo.active_branch.name
        remoteNameWithOwner = self.nameWithOwner(remoteName)

        self.progressMethod(f"Loading {branchName} into {localDirectory}")

        try:
            colorPath = glob.glob(f"{localDirectory}/*.csv")[0]
            colorNode = slicer.util.loadColorTable(colorPath)
        except IndexError:
            try:
                colorPath = glob.glob(f"{localDirectory}/*.ctbl")[0]
                colorNode = slicer.util.loadColorTable(colorPath)
            except IndexError:
                self.ghProgressMethod(f"No color table found")

        # TODO: move from single volume file to segmentation specification json
        # TODO: save checksum in source_volume file to verify when downloading later
        volumePath = os.path.join(localDirectory, "source_volume")
        if not os.path.exists(volumePath):
            volumePath = os.path.join(localDirectory, "master_volume") # for backwards compatibility
        volumeURL = open(volumePath).read().strip()
        nrrdPath = os.path.join(localDirectory, f"{remoteNameWithOwner.replace('/', '-')}-volume.nrrd")
        if not os.path.exists(nrrdPath):
            #slicer.util.downloadFile(volumeURL, nrrdPath)
            downloadFileWorkaround(volumeURL, nrrdPath)
        volumeNode = slicer.util.loadVolume(nrrdPath)

        # Load all segmentations
        segmentationNodesByName = {}
        for segmentationPath in glob.glob(f"{localDirectory}/*.seg.nrrd"):
            name = os.path.split(segmentationPath)[1].split(".")[0]
            segmentationNodesByName[name] = slicer.util.loadSegmentation(segmentationPath)

        if configuration == "segment":
            for segmentationNode in segmentationNodesByName.values():
                segmentationNode.GetDisplayNode().SetVisibility(False)

            # Switch to Segment Editor module
            pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
            pluginHandlerSingleton.pluginByName("Default").switchToModule("SegmentEditor")
            editorWidget = slicer.modules.segmenteditor.widgetRepresentation().self()

            self.segmentationPath = os.path.join(localDirectory, branchName) + ".seg.nrrd"
            if configuration == "segment":
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
        if not self.localRepo:
            return None
        branchName = self.localRepo.active_branch.name
        try:
            upstreamNameWithOwner = self.nameWithOwner("upstream")
        except ValueError:
            return None
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

        # rebase branch if it exists in case other changes have been made (e.g. on another machine)
        branchNames = [branch.name.split("/")[1] for branch in self.localRepo.remotes['origin'].refs]
        if branchName in branchNames:
            pullResult = self.localRepo.git.pull(f"--rebase", "origin", branchName)
            self.progressMethod(pullResult)

        # Workaround for missing origin.push().raise_if_error() in 3.1.14
        # (see https://github.com/gitpython-developers/GitPython/issues/621):
        # https://github.com/gitpython-developers/GitPython/issues/621
        pushInfoList = remote.push(branchName)
        for pi in pushInfoList:
            for flag in [pi.REJECTED, pi.REMOTE_REJECTED, pi.REMOTE_FAILURE, pi.ERROR]:
                if pi.flags & flag:
                    self.progressMethod(f"Push failed with {flag}")
                    return False

        # create a PR if needed
        if not self.issuePR():
            issueNumber = branchName.split("-")[1]
            upstreamNameWithOwner = self.nameWithOwner("upstream")
            originNameWithOwner = self.nameWithOwner("origin")
            originOwner = originNameWithOwner.split("/")[0]
            prBody = f"Fixes #{issueNumber}"
            if self.currentIssue and 'author' in self.currentIssue and 'login' in self.currentIssue['author']:
                authorLogin = self.currentIssue['author']['login']
                prBody = f"Started work on this issue for @{authorLogin}. {prBody}"
            commandList = f"""
                pr create
                --draft
                --repo {upstreamNameWithOwner}
                --base main
                --title {branchName}
                --head {originOwner}:{branchName}
            """.replace("\n"," ").split()
            commandList += ["--body", prBody]
            self.gh(commandList)
        return True

    def requestReview(self):
        pr = self.issuePR(role="segmenter")
        if not pr:
            logging.error("No pull request found for the current issue branch.")
            return

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
        # TODO: this if the reviewer is also the creator of the PR
        # this generates an error from github that you aren't allowed
        # to approve your own PRs, but it's just a warning in this case.
        # Checking the name to avoid the approval or just skipping
        # approval since we are closing the PR anyway would be fine.
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

    def getReleases(self):
        """Get list of releases for the current repository."""
        if not self.localRepo:
            return None
        originNameWithOwner = self.nameWithOwner("origin")
        return self.ghJSON(f"release list --repo {originNameWithOwner} --json name,tagName")

    def createRelease(self, releaseNotes=""):
        """Create a new release for the current repository with an incremented version."""
        if not self.localRepo:
            return
        releases = self.getReleases()
        nextVersion = 1
        if releases:
            tagNames = [r['tagName'] for r in releases if r['tagName'].startswith('v')]
            versions = [int(t[1:]) for t in tagNames if t[1:].isdigit()]
            if versions:
                nextVersion = max(versions) + 1
        upstreamNameWithOwner = self.nameWithOwner("origin")
        if releaseNotes == "":
            releaseNotes = f"Version {nextVersion} release."
        # use list for command to handle spaces in releaseNotes
        commandList = ["release", "create", f"v{nextVersion}", "--repo", upstreamNameWithOwner]
        commandList += ["--notes", releaseNotes]
        self.gh(commandList)

    def createAccessionRepo(self, sourceVolume, colorTable, accessionData, sourceSegmentation=None):

        repoName = accessionData['githubRepoName'][1]
        repoDir = os.path.join(self.localRepositoryDirectory(), repoName)
        os.makedirs(repoDir)

        # save data
        repoFileNames = []
        sourceFileName = sourceVolume.GetName()
        sourceFilePath = os.path.join(repoDir, sourceFileName) + ".nrrd"
        slicer.util.saveNode(sourceVolume, sourceFilePath)
        colorTableName = colorTable.GetName()
        slicer.util.saveNode(colorTable, os.path.join(repoDir, colorTableName) + ".csv")
        repoFileNames.append(f"{colorTableName}.csv")

        # write accessionData file
        fp = open(os.path.join(repoDir, "MorphoDepotAccession.json"), "w")
        fp.write(json.dumps(accessionData, indent=4))
        fp.close()

        # write license file
        if accessionData["license"][1].startswith("CC BY-NC"):
            licenseURL = "https://creativecommons.org/licenses/by-nc/4.0/legalcode.txt"
        else:
            licenseURL = "https://creativecommons.org/licenses/by/4.0/legalcode.txt"
        response = requests.get(licenseURL)
        fp = open(os.path.join(repoDir, "LICENSE.txt"), "w")
        fp.write(response.content.decode('ascii', errors="ignore"))
        fp.close()

        if accessionData['iDigBioAccessioned'][1] == "Yes":
            idigbioURL = accessionData['iDigBioURL'][1]
            specimenID = idigbioURL.split("/")[-1]
            import idigbio
            api = idigbio.json()
            idigbioData = api.view("records", specimenID)
            if 'ala:species' in idigbioData['data']:
                speciesString = idigbioData['data']['ala:species']
            elif 'dwc:scientificName' in idigbioData['data']:
                speciesString = idigbioData['data']['dwc:scientificName']
            else:
                logging.warning(f"Could not find species for {idigbioURL}")
                logging.warning(f"Response from api: {idigbioData}")
                speciesString = "Unknown species"
        else:
            speciesString = accessionData['species'][1]
        speciesTopicString = speciesString.lower().replace(" ", "-")

        # write readme file
        fp = open(os.path.join(repoDir, "README.md"), "w")
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
        repo = git.Repo.init(repoDir, initial_branch='main')

        repoFileNames += [
            "README.md",
            "LICENSE.txt",
            "MorphoDepotAccession.json",
        ]
        if sourceSegmentation:
            segmentationName = "baseline" # initial segmentation
            slicer.util.saveNode(sourceSegmentation, os.path.join(repoDir, segmentationName) + ".seg.nrrd")
            repoFileNames.append(f"{segmentationName}.seg.nrrd")
        repoFilePaths = [os.path.join(repoDir, fileName) for fileName in repoFileNames]
        repo.index.add(repoFilePaths)
        repo.index.commit("Initial commit")

        self.gh(f"repo create {repoName} --add-readme --disable-wiki --public --source {repoDir} --push")

        self.localRepo = repo
        repoNameWithOwner = self.nameWithOwner("origin")

        self.gh(f"repo edit {repoNameWithOwner} --enable-projects=false --enable-discussions=false")

        self.gh(f"repo edit {repoNameWithOwner} --add-topic morphodepot --add-topic md-{speciesTopicString}")

        # create initial release and add asset
        # use list for command to handle spaces in notes
        commandList = ["release", "create", "--repo", repoNameWithOwner, "v1"]
        commandList += ["--notes", "Initial release"]
        self.gh(commandList)
        self.gh(f"release upload --repo {repoNameWithOwner} v1 {sourceFilePath}#{sourceFileName}.nrrd")

        # write source volume pointer file
        fp = open(os.path.join(repoDir, "source_volume"), "w")
        fp.write(f"https://github.com/{repoNameWithOwner}/releases/download/v1/{sourceFileName}.nrrd")
        fp.close()

        repo.index.add([f"{repoDir}/source_volume"])
        repo.index.commit("Add source file url file")
        repo.remote(name="origin").push()

        self.gh("config clear-cache"); # so the next morphoRepos call will include this repo

    #
    # Search
    #

    def refreshSearchCache(self):
        """Gets accession data from all repositories"""
        repos = self.morphoRepos()

        repoDirectory = os.path.normpath(slicer.util.settingsValue("MorphoDepot/repoDirectory", "") or "")

        searchDirectory = f"{repoDirectory}/MorphoDepotSearchCache"
        os.makedirs(searchDirectory, exist_ok=True)

        self.repoDataByNameWithOwner = {}

        for repo in repos:
            repoName = repo['name']
            ownerLogin = repo['owner']['login']
            nameWithOwner = f"{repoName}-{ownerLogin}"
            filePath = f"{searchDirectory}/{nameWithOwner}-MorphoDepotAccession.json"
            if os.path.exists(filePath):
                fp = open(filePath)
                self.repoDataByNameWithOwner[nameWithOwner] = json.loads(fp.read())
            else:
                urlPrefix = "https://raw.githubusercontent.com"
                urlSuffix = "refs/heads/main/MorphoDepotAccession.json"
                accessionURL = f"{urlPrefix}/{ownerLogin}/{repoName}/{urlSuffix}"
                request = requests.get(accessionURL)
                if request.status_code == 200:
                    fp = open(filePath, "w")
                    fp.write(request.text)
                    fp.close()
                    self.repoDataByNameWithOwner[nameWithOwner] = json.loads(request.text)


    def search(self, criteria):
        if self.repoDataByNameWithOwner == {}:
            return {}

        excludedRepos = set()
        for nameWithOwner, repoData in self.repoDataByNameWithOwner.items():
            for question in criteria:
                if question in repoData:
                    repoValue = repoData[question][1]
                    if repoValue.__class__() == []:
                        valueInCriterion = False
                        for value in repoValue:
                            if value in criteria[question]:
                                valueInCriterion = True
                            if not valueInCriterion:
                                excludedRepos.add(nameWithOwner)
                    else:
                        if repoValue != "" and repoValue not in criteria[question]:
                            excludedRepos.add(nameWithOwner)

        matchString = f"*{criteria['freeText'].lower()}*"
        matchingRepos = set()
        textFields = ["githubRepoName", "species"]
        for nameWithOwner, repoData in self.repoDataByNameWithOwner.items():
            if fnmatch.fnmatch(nameWithOwner, matchString):
                matchingRepos.add(nameWithOwner)
            for textField in textFields:
                if textField in repoData:
                    if fnmatch.fnmatch(repoData[textField][1].lower(), matchString):
                        matchingRepos.add(nameWithOwner)

        results = {}
        for nameWithOwner in matchingRepos:
            if nameWithOwner not in excludedRepos:
                results[nameWithOwner] = self.repoDataByNameWithOwner[nameWithOwner]

        return results


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

    def _generate_random_species_name(self):
        """Generates a random species-like name for testing."""
        genus_prefixes = ["Testudo", "Pseudo", "Archeo", "Pico", "Nano", "Slicero"]
        genus_suffixes = ["saurus", "therium", "pithecus", "don", "raptor", "morpho"]
        species_epithets = ["minimus", "maximus", "communis", "vulgaris", "testus", "exempli"]

        genus = random.choice(genus_prefixes) + random.choice(genus_suffixes).lower()
        species = random.choice(species_epithets)

        # Create a unique repository name from the species name
        repo_name = f"test-{genus.lower()}-{species.lower()}-{math.floor(1000*random.random())}"
        species_name = f"{genus.capitalize()} {species.lower()}"
        return repo_name, species_name

    def test_MorphoDepot1(self):
        """
        This test emulates the repository creation and issue assignment workflow.
        """

        self.delayDisplay("Starting MorphoDepot flow test")

        # 1. Get creator and annotator accounts from settings
        creator = slicer.util.settingsValue("MorphoDepot/testingCreatorUser", "")
        annotator = slicer.util.settingsValue("MorphoDepot/testingAnnotatorUser", "")
        if not creator and annotator:
            print("Creator and Annotator users must be set in Configure tab's Testing section")
            return

        widget = slicer.modules.MorphoDepotWidget
        logic = widget.logic

        # Helper function for switching user
        def switchUser(username):
            self.delayDisplay(f"Switching gh auth to {username}")
            logic.gh(["auth", "switch", "--user", username])

        # 2. Switch to Creator auth
        switchUser(creator)
        self.delayDisplay("Creating a test repository")
        widget.tabWidget.setCurrentWidget(widget.createUI.createRepository.parent().parent())

        # Use sample data for volume and color table
        import SampleData
        volumeNode = SampleData.SampleDataLogic().downloadMRHead()
        self.assertIsNotNone(volumeNode, "Failed to download MRHead sample data.")
        colorTable = slicer.util.getNode("Labels")
        widget.createUI.inputSelector.setCurrentNode(volumeNode)
        widget.createUI.colorSelector.setCurrentNode(colorTable)

        # Fill out the accession form
        form = widget.createUI.accessionForm
        repoName, speciesName = self._generate_random_species_name()
        form.questions["specimenSource"].optionButtons["Commercially acquired"].click()
        form.questions["species"].answerText.text = speciesName
        form.questions["biologicalSex"].optionButtons["Unknown"].click()
        form.questions["developmentalStage"].optionButtons["Adult"].click()
        form.questions["modality"].optionButtons["Micro CT (or synchrotron)"].click()
        form.questions["contrastEnhancement"].optionButtons["No"].click()
        form.questions["imageContents"].optionButtons["Whole specimen"].click()
        form.questions["redistributionAcknowledgement"].optionButtons["I have the right to allow redistribution of this data."].click()
        form.questions["license"].optionButtons["CC BY 4.0 (requires attribution, allows commercial usage)"].click()
        form.questions["githubRepoName"].answerText.text = f"MorphoDepotTesting/{repoName}"
        repoNameWithOwner = form.questions["githubRepoName"].answerText.text

        # Create the repository
        widget.onCreateRepository()
        slicer.app.processEvents()
        self.delayDisplay(f"Repository {repoName} created.")

        # Open the repository page
        self.delayDisplay(f"Opening repository page for {repoNameWithOwner}")
        repoURL = qt.QUrl(f"https://github.com/{repoNameWithOwner}")
        qt.QDesktopServices.openUrl(repoURL)

        # 3. Create two sample issues as Creator
        self.delayDisplay("Creating sample issues")
        issue1_title = "Segment the cranium"
        issue2_title = "Segment the mandible"
        logic.gh(["issue", "create", "--repo", repoNameWithOwner, "--title", issue1_title, "--body", "Please segment the entire cranium."])
        logic.gh(["issue", "create", "--repo", repoNameWithOwner, "--title", issue2_title, "--body", "Please segment the left and right dentary."])

        # 5. Switch to Annotator auth
        switchUser(annotator)

        # 6. List issues and comment as Annotator
        self.delayDisplay("Listing and commenting on issues as Annotator")
        issues = logic.ghJSON(f"issue list --repo {repoNameWithOwner} --json number,title")
        self.assertEqual(len(issues), 2)

        for issue in issues:
            issueNumber = issue['number']
            self.delayDisplay(f"Commenting on issue #{issueNumber}")
            logic.gh(["issue", "comment", str(issueNumber), "--repo", repoNameWithOwner, "--body", "I would like to work on this issue."])

        # 7. Switch back to Creator auth
        switchUser(creator)

        # 8. Assign issues to the Annotator
        self.delayDisplay("Assigning issues to Annotator")
        issues = logic.ghJSON(f"issue list --repo {repoNameWithOwner} --json number,title")
        for issue in issues:
            issueNumber = issue['number']
            self.delayDisplay(f"Assigning issue #{issueNumber} to {annotator}")
            logic.gh(["issue", "edit", str(issueNumber), "--repo", repoNameWithOwner, "--add-assignee", annotator])

        # Verify assignment
        assignedIssues = logic.ghJSON(f"issue list --repo {repoNameWithOwner} --assignee {annotator} --json number")
        self.assertEqual(len(assignedIssues), 2, f"Expected 2 issues to be assigned to {annotator}")

        # 9. Switch to Annotator to work on issues
        switchUser(annotator)
        self.delayDisplay("Annotator listing assigned issues")
        annotatorIssues = logic.issueList()
        # filter for the repo we just created
        annotatorIssues = [issue for issue in annotatorIssues if issue['repository']['nameWithOwner'] == repoNameWithOwner]
        self.assertEqual(len(annotatorIssues), 2, f"Annotator should have 2 issues for repo {repoNameWithOwner}.")

        # 10. Annotator loads each issue, makes a change, and creates a PR.
        repoDirectory = logic.localRepositoryDirectory()
        for issue in annotatorIssues:
            self.delayDisplay(f"Annotator working on issue #{issue['number']}: {issue['title']}")

            # Load issue
            slicer.mrmlScene.Clear()
            logic.loadIssue(issue, repoDirectory)

            # Check that things are loaded
            self.assertIsNotNone(logic.segmentationNode, "Segmentation node should be loaded.")
            self.assertTrue(len(slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")) > 0, "Volume node should be loaded.")

            # Make an arbitrary change to the segmentation
            self.delayDisplay("Making an arbitrary change to the segmentation")
            segmentation = logic.segmentationNode.GetSegmentation()
            segmentation.AddEmptySegment(f"test-segment-by-annotator-{issue['title']}")

            # Commit and push, which creates a draft PR
            commitMessage = f"Work on issue #{issue['number']}"
            self.delayDisplay(f"Committing and creating PR for issue #{issue['number']}")
            self.assertTrue(logic.commitAndPush(commitMessage), f"Failed to commit and push for issue #{issue['number']}")
            widget.annotateUI.messageTitle.text = commitMessage
            widget.onCommit()
            slicer.app.processEvents()

            # 11. Annotator requests review for the PR
            self.delayDisplay(f"Requesting review for work on issue #{issue['number']}")
            widget.onRequestReview()
            slicer.app.processEvents()

        # 12. Switch to Creator to review the PRs
        switchUser(creator)
        self.delayDisplay("Creator reviewing PRs")
        widget.updateReviewPRList()
        self.assertEqual(widget.reviewUI.prList.count, 2, "Expected 2 PRs for review.")

        # Approve the first PR and request changes on the second
        itemToApprove = widget.reviewUI.prList.item(0)
        prToApprove = widget.prsByItem[itemToApprove]
        itemToRequestChanges = widget.reviewUI.prList.item(1)
        prToRequestChanges = widget.prsByItem[itemToRequestChanges]

        # Approve the first PR
        self.delayDisplay(f"Approving and merging PR #{prToApprove['number']}")
        slicer.mrmlScene.Clear()
        logic.loadPR(prToApprove, repoDirectory)
        widget.reviewUI.reviewMessage.plainText = "Looks good!"
        widget.onApprove()
        slicer.app.processEvents()

        # Request changes on the second PR
        self.delayDisplay(f"Requesting changes on PR #{prToRequestChanges['number']}")
        slicer.mrmlScene.Clear()
        logic.loadPR(prToRequestChanges, repoDirectory)
        widget.reviewUI.reviewMessage.plainText = "Please add another segment."
        widget.onRequestChanges()
        slicer.app.processEvents()

        # 13. Switch to Annotator to address feedback
        switchUser(annotator)
        self.delayDisplay("Annotator addressing feedback")

        # Find the issue that needs changes
        issueForChanges = next(issue for issue in annotatorIssues if f"issue-{issue['number']}" == prToRequestChanges['title'])

        # Load the issue, make a change, and request review again
        slicer.mrmlScene.Clear()
        logic.loadIssue(issueForChanges, repoDirectory)
        self.delayDisplay("Making an additional change to the segmentation")
        segmentation = logic.segmentationNode.GetSegmentation()
        segmentation.AddEmptySegment("additional-annotator-segment")

        commitMessage = f"Addressing feedback on issue #{issueForChanges['number']}"
        widget.annotateUI.messageTitle.text = commitMessage
        widget.onCommit()
        slicer.app.processEvents()
        widget.onRequestReview()
        slicer.app.processEvents()
        logic.gh(f"pr comment {prToRequestChanges['number']} --repo {repoNameWithOwner} --body 'I have addressed the feedback. Ready for another look.'")

        # 14. Switch back to Creator to approve the updated PR
        switchUser(creator)
        self.delayDisplay(f"Creator approving updated PR #{prToRequestChanges['number']}")
        slicer.mrmlScene.Clear()
        logic.loadPR(prToRequestChanges, repoDirectory)
        widget.reviewUI.reviewMessage.plainText = "Thanks for the update!"
        widget.onApprove()
        slicer.app.processEvents()

        # 15. Create a release and open the repository page
        self.delayDisplay("Creating a new release")
        widget.tabWidget.setCurrentWidget(widget.releaseUI.repoList.parent().parent())
        widget.onRefreshReleaseTab()
        slicer.app.processEvents()

        # Find and select the repository in the list
        repoItem = None
        for i in range(widget.releaseUI.repoList.count):
            item = widget.releaseUI.repoList.item(i)
            if item.text() == repoNameWithOwner:
                repoItem = item
                break
        self.assertIsNotNone(repoItem, f"Repository {repoNameWithOwner} not found in release list.")
        widget.onReleaseRepoDoubleClicked(repoItem)
        widget.releaseUI.releaseCommentsEdit.plainText = "First segmentation complete."
        widget.onMakeRelease()

        #logic.gh(f"repo delete {repoNameWithOwner} --yes")

        self.delayDisplay("Test passed")
