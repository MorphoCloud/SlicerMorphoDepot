from contextlib import contextmanager
import glob
import json
import locale
import logging
import os
import shutil
import platform
import requests
import subprocess
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

    requireSystemGit = True  # don't try to install using pixi
                             # see https://github.com/MorphoCloud/SlicerMorphoDepot/issues/24

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

    def promptForGitConfig(self):
        # TODO - a prompting dialog would be required if requireSystemGit were False
        return ("Sample Name", "name@example.com")

    def offerGitInstallation(self):
        """Not currently used: reserve for future if git/gh install needs to be done by this module"""
        msg = "Extra tools are needed to use this module (pixi, git, and gh),"
        msg += "\nplus some python packages (idigbio and pygbif)."
        msg += "\nClick OK to install them for MorphoDepot."
        install = slicer.util.confirmOkCancelDisplay(msg)
        if install:
            logic = MorphoDepotLogic(progressMethod=MorphoDepotWidget.progressMethod)
            if not logic.usingSystemGit:
                name,email = self.promptForGitConfig()
                try:
                    logic.installGitDependencies(name, email)
                    self.enter()
                except Exception as e:
                    msg = "Installation failed. Check error log for debugging information."
                    slicer.util.messageBox(msg)
                    print(f"Exception: {e}")
                    traceback.print_exc(file=sys.stderr)
        return logic.ghExecutablePath

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
        if MorphoDepot.requireSystemGit:
            if not self.logic.checkGitDependencies():
                msg = "The git and gh must be installed and configured."
                msg += "\nBe sure that you have logged into Github with 'gh auth login' and then restart Slicer."
                msg += "\nSee documentation for platform-specific instructions"
                slicer.util.messageBox(msg)
                return False
        else:
            if not (moduleEnabled and self.logic.git and self.logic.gitExecutablePath and self.logic.ghExecutablePath):
                moduleEnabled = moduleEnabled and self.offerGitInstallation()
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

        uiWidget = slicer.util.loadUI(os.path.normpath(self.resourcePath("UI/MorphoDepotCreate.ui")))
        uiWidget.setMRMLScene(slicer.mrmlScene)
        self.tabWidget.addTab(uiWidget, "Create")
        self.createUI = slicer.util.childWidgetVariables(uiWidget)

        uiWidget = slicer.util.loadUI(os.path.normpath(self.resourcePath("UI/MorphoDepotAnnotate.ui")))
        uiWidget.setMRMLScene(slicer.mrmlScene)
        self.tabWidget.addTab(uiWidget, "Annotate")
        self.annotateUI = slicer.util.childWidgetVariables(uiWidget)

        uiWidget = slicer.util.loadUI(os.path.normpath(self.resourcePath("UI/MorphoDepotReview.ui")))
        uiWidget.setMRMLScene(slicer.mrmlScene)
        self.tabWidget.addTab(uiWidget, "Review")
        self.reviewUI = slicer.util.childWidgetVariables(uiWidget)

        uiWidget = slicer.util.loadUI(os.path.normpath(self.resourcePath("UI/MorphoDepotSearch.ui")))
        uiWidget.setMRMLScene(slicer.mrmlScene)
        self.tabWidget.addTab(uiWidget, "Search")
        self.searchUI = slicer.util.childWidgetVariables(uiWidget)


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
        self.configureUI.gitPath.currentPath = os.path.normpath(self.logic.gitExecutablePath) if self.logic.gitExecutablePath else ""
        self.configureUI.gitPath.toolTip = "Restart Slicer after setting new path"
        self.configureUI.ghPath.currentPath = os.path.normpath(self.logic.ghExecutablePath) if self.logic.ghExecutablePath else ""
        self.configureUI.ghPath.toolTip = "Restart Slicer after setting new path"
        self.annotateUI.forkManagementCollapsibleButton.enabled = False

        # Create
        self.createUI.colorSelector = slicer.qMRMLColorTableComboBox()
        self.createUI.colorSelector.setMRMLScene(slicer.mrmlScene)
        self.createUI.inputsCollapsibleButton.layout().addRow("Color table:", self.createUI.colorSelector)
        self.createUI.accessionLayout = qt.QVBoxLayout()
        self.createUI.accessionCollapsibleButton.setLayout(self.createUI.accessionLayout)
        self.createUI.createRepository.enabled = False
        validationCallback = lambda valid, w=self.createUI.createRepository: w.setEnabled(valid)
        self.createUI.accessionForm = MorphoDepotAccessionForm(validationCallback=validationCallback)
        self.createUI.accessionLayout.addWidget(self.createUI.accessionForm.topWidget)

        # Review
        self.reviewUI.prCollapsibleButton.enabled = False

        # Connections
        self.configureUI.repoDirectory.comboBox().connect("currentTextChanged(QString)", self.onRepoDirectoryChanged)
        self.configureUI.gitPath.comboBox().connect("currentTextChanged(QString)", self.onGitPathChanged)
        self.configureUI.ghPath.comboBox().connect("currentTextChanged(QString)", self.onGhPathChanged)
        self.createUI.createRepository.clicked.connect(self.onCreateRepository)
        self.createUI.openRepository.clicked.connect(self.onOpenRepository)
        self.createUI.clearForm.clicked.connect(self.onClearForm)
        self.annotateUI.issueList.itemDoubleClicked.connect(self.onIssueDoubleClicked)
        self.annotateUI.prList.itemSelectionChanged.connect(self.onPRSelectionChanged)
        self.annotateUI.commitButton.clicked.connect(self.onCommit)
        self.annotateUI.reviewButton.clicked.connect(self.onRequestReview)
        self.annotateUI.refreshButton.connect("clicked(bool)", self.onRefresh)
        self.annotateUI.openPRPageButton.clicked.connect(self.onOpenPRPageButtonClicked)
        self.reviewUI.refreshButton.connect("clicked(bool)", self.updateReviewPRList)
        self.reviewUI.prList.itemDoubleClicked.connect(self.onPRDoubleClicked)
        self.reviewUI.requestChangesButton.clicked.connect(self.onRequestChanges)
        self.reviewUI.approveButton.clicked.connect(self.onApprove)

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

    # Create
    def onCreateRepository(self):
        if self.createUI.inputSelector.currentNode() == None or self.createUI.colorSelector.currentNode() == None:
            slicer.util.errorDisplay("Need to select volume and color table")
            return
        sourceVolume = self.createUI.inputSelector.currentNode()
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
            self.logic.createAccessionRepo(sourceVolume, colorTable, accessionData)
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
        self.updateIssueList()
        self.updateAnnotatePRList()

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
            self.annotateUI.currentIssueLabel.text = f"Issue: {item.text()}"
            slicer.mrmlScene.Clear()
            try:
                self.logic.loadIssue(issue, repoDirectory)
                self.annotateUI.forkManagementCollapsibleButton.enabled = True
                slicer.util.showStatusMessage(f"Start segmenting {item.text()}")
            except self.logic.git.exc.NoSuchPathError:
                slicer.util.errorDisplay("Could not load issue. If it was just created on github please wait a few seconds and try again")

    def onCommit(self):
        slicer.util.showStatusMessage(f"Committing and pushing")
        message = self.annotateUI.messageTitle.text
        if message == "":
            slicer.util.messageBox("You must provide a commit message (title required, body optional)")
        body = self.annotateUI.messageBody.plainText
        if body != "":
            message = f"{message}\n\n{body}"
        if self.logic.commitAndPush(message):
            self.annotateUI.messageTitle.text = ""
            self.annotateUI.messageBody.plainText = ""
            slicer.util.showStatusMessage(f"Commit and push complete")
            self.updateAnnotatePRList()
        else:
            path = os.path.normpath(self.configureUI.repoDirectory.currentPath)
            slicer.util.messageBox(f"Commit failed.\nYour repository conflicts with what's on github. Copy your work from {path} and then delete the local repository folder and restart the issues.")
            slicer.util.showStatusMessage(f"Commit and push failed")

    def onRequestReview(self):
        """Create a checkpoint if need, then mark issue as ready for review"""
        slicer.util.showStatusMessage(f"Marking pull request for review")
        prURL = self.logic.requestReview()
        self.updateAnnotatePRList()

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
        slicer.util.showStatusMessage(f"Loading {item.text()}")
        repoDirectory = self.logic.localRepositoryDirectory()
        pr = self.prsByItem[item]
        if slicer.util.confirmOkCancelDisplay("Close scene and load PR?"):
            self.reviewUI.currentPRLabel.text = f"PR: {item.text()}"
            slicer.mrmlScene.Clear()
            if self.logic.loadPR(pr, repoDirectory):
                self.reviewUI.prCollapsibleButton.enabled = True
                slicer.util.showStatusMessage(f"Start reviewing {item.text()}")
            else:
                slicer.util.showStatusMessage(f"PR load failed")

    def onRequestChanges(self):
        slicer.util.showStatusMessage(f"Requesting changes")
        message = self.reviewUI.reviewMessage.plainText
        self.logic.requestChanges(message)
        self.reviewUI.reviewMessage.plainText = ""
        slicer.util.showStatusMessage(f"Changes requested")
        self.updateReviewPRList()

    def onApprove(self):
        slicer.util.showStatusMessage(f"Approving")
        prURL = self.logic.approvePR()
        self.reviewUI.reviewMessage.plainText = ""
        self.updateReviewPRList()

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
        repoNameRegex = r"^[a-zA-Z][a-zA-Z0-9-_.]*$"
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

    def __init__(self, progressMethod = None) -> None:
        """Called when the logic class is instantiated. Can be used for initializing member variables."""
        ScriptedLoadableModuleLogic.__init__(self)
        self.segmentationNode = None
        self.segmentationPath = None
        self.localRepo = None
        self.progressMethod = progressMethod if progressMethod else lambda *args : None
        self.gitExecutablesDir = None
        self.gitExecutablePath = None
        self.ghExecutablePath = None
        self.usingSystemGit = True

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
        else:
            # otherwise define where we expect to find git and gh after installation
            if not MorphoDepot.requireSystemGit:
                if os.name == 'nt':
                    self.gitExecutablesDir = os.path.join(self.pixiInstallDir, "/.pixi/envs/default/Library/bin")
                    self.gitExecutablePath = os.path.join(self.gitExecutablesDir, "/git.exe")
                    self.ghExecutablePath = os.path.join(self.pixiInstallDir, "/.pixi/envs/default/Scripts/gh.exe")
                else:
                    self.gitExecutablesDir = os.path.join(self.pixiInstallDir, "/.pixi/envs/default/bin")
                    self.gitExecutablePath = os.path.join(self.gitExecutablesDir, "/git")
                    self.ghExecutablePath = os.path.join(self.pixiInstallDir, "/.pixi/envs/default/bin/gh")
                self.usingSystemGit = False

        qt.QSettings().setValue("MorphoDepot/gitPath", self.gitExecutablePath)
        qt.QSettings().setValue("MorphoDepot/ghPath", self.ghExecutablePath)

        self.git = None
        if self.gitExecutablePath and os.path.exists(self.gitExecutablePath):
            self.importGitPython()

    def importGitPython(self):
        # gitpython cannot be imported if it can't find git.
        # we specify the executable but also set it explicitly so that
        # we know we are using our download in case it has already been
        # imported elsewhere and found a different git
        os.environ['GIT_PYTHON_GIT_EXECUTABLE'] = self.gitExecutablePath
        import git
        git.refresh(path=self.gitExecutablePath)
        self.git = git
        del os.environ['GIT_PYTHON_GIT_EXECUTABLE']

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

        self.progressMethod("Downloading pixi")
        url = f'https://pixi.sh/{fileName}'
        scriptPath = self.pixiInstallDir + "/" + fileName
        #slicer.util.downloadFile(url, scriptPath)
        downloadFileWorkaround(url, scriptPath)

        self.progressMethod("Running pixi installer")
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

        pixiPath = os.path.join(self.pixiInstallDir, "/bin/pixi") + self.executableExtension
        p = slicer.util.launchConsoleProcess([pixiPath, "init", self.pixiInstallDir], updateEnvironment=updateEnvironment)
        logging.info(str(p.communicate()))
        self.progressMethod("Adding git")
        p = slicer.util.launchConsoleProcess([pixiPath, "add", "--manifest-path", self.pixiInstallDir, "git"], updateEnvironment=updateEnvironment)
        logging.info(str(p.communicate()))
        self.progressMethod("Adding gh")
        p = slicer.util.launchConsoleProcess([pixiPath, "add", "--manifest-path", self.pixiInstallDir, "gh"], updateEnvironment=updateEnvironment)
        logging.info(str(p.communicate()))

        self.progressMethod("Importing GitPython")
        self.importGitPython()

        tempRepoDir = os.path.join(slicer.app.temporaryPath, "/_MorphoDepot_temp_git")
        shutil.rmtree(tempRepoDir, ignore_errors=True)
        os.makedirs(tempRepoDir)
        tempRepo = self.git.Repo.init(tempRepoDir)
        tempRepo.config_writer(config_level="global").set_value("user", "name", name).release()
        tempRepo.config_writer(config_level="global").set_value("user", "email", email).release()
        shutil.rmtree(tempRepoDir)

        self.progressMethod("Installation complete")

    @gitEnvironmentDecorator
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

        environment = {}
        if self.usingSystemGit:
            if not self.gitExecutablesDir:
                completedProcess = subprocess.run([self.gitExecutablePath, "--exec-path"], capture_output=True)
                self.gitExecutablesDir = completedProcess.stdout.strip()
                try:
                    self.gitExecutablesDir = self.gitExecutablesDir.decode() # needed on windows
                except (UnicodeDecodeError, AttributeError):
                    pass
                environment = {
                    "PATH" : os.path.dirname(self.gitExecutablePath),
                    "GIT_EXEC_PATH": self.gitExecutablesDir
                }
        else:
            environment = {
                "PATH" : self.gitExecutablesDir,
                "GIT_EXEC_PATH" : self.gitExecutablesDir,
                "GH_CONFIG_DIR" : self.pixiInstallDir
            }
        originalLocale = locale.setlocale(locale.LC_ALL)
        locale.setlocale(locale.LC_ALL, "en_US.UTF-8")
        process = slicer.util.launchConsoleProcess(fullCommandList, updateEnvironment=environment)
        result = process.communicate()
        locale.setlocale(locale.LC_ALL, originalLocale)
        if process.returncode != 0:
            logging.error("gh command failed:")
            logging.error(commandList)
            logging.error(result)
            self.progressMethod(f"gh command error: {result}")
            return None
        self.progressMethod(f"gh command finished: {result}")
        return result[0]

    def morphoRepos(self):
        # TODO: generalize for other topics
        return json.loads(self.gh("search repos --limit 1000 --json owner,name --include-forks true -- topic:morphodepot"))

    def issueList(self):
        repoList = self.morphoRepos()
        candiateIssueList = json.loads(self.gh(f"search issues --limit 1000 --assignee=@me --state open --json repository,title,number"))
        repoNamesWithOwner = [f"{repo['owner']['login']}/{repo['name']}" for repo in repoList]
        issueList = [issue for issue in candiateIssueList if issue['repository']['nameWithOwner'] in repoNamesWithOwner]
        return issueList

    def prList(self, role="segmenter"):
        repoList = self.morphoRepos()
        repoNamesWithOwner = [f"{repo['owner']['login']}/{repo['name']}" for repo in repoList]
        if role == "segmenter":
            searchString = "--author=@me"
        elif role == "reviewer":
            searchString = "--owner=@me"
        jsonFields = "title,number,author,isDraft,updatedAt,repository"
        candidatePRList = json.loads(self.gh(f"search prs --limit 1000 --state open --json {jsonFields} {searchString}"))
        prList = [pr for pr in candidatePRList if pr['repository']['nameWithOwner'] in repoNamesWithOwner]
        for pr in prList:
            issues = json.loads(self.gh(f"issue list --repo {pr['repository']['nameWithOwner']} --json title,number --state open"))
            pr['issueTitle'] = "issue not found"
            for issue in issues:
                if pr['title'] == f"issue-{issue['number']}":
                    pr['issueTitle'] = issue['title']
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
        repositoryName = f"{pr['author']['login']}/{pr['repository']['name']}"
        localDirectory = f"{repoDirectory}/{pr['repository']['name']}-{branchName}"
        self.progressMethod(f"Loading issue {repositoryName} into {localDirectory}")

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
            self.progressMethod(f"Error pulling origin")
            return False

        self.loadFromLocalRepository()
        return True

    def loadFromLocalRepository(self):
        localDirectory = self.localRepo.working_dir
        branchName = self.localRepo.active_branch.name
        upstreamNameWithOwner = self.nameWithOwner("upstream")

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
        nrrdPath = os.path.join(localDirectory, f"{upstreamNameWithOwner.replace('/', '-')}-volume.nrrd")
        if not os.path.exists(nrrdPath):
            #slicer.util.downloadFile(volumeURL, nrrdPath)
            downloadFileWorkaround(volumeURL, nrrdPath)
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

        self.segmentationPath = os.path.join(localDirectory, branchName) + ".seg.nrrd"
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
        repoDir = os.path.join(self.localRepositoryDirectory(), repoName)
        os.makedirs(repoDir)

        # save data
        sourceFileName = sourceVolume.GetName()
        sourceFilePath = os.path.join(repoDir, sourceFileName) + ".nrrd"
        slicer.util.saveNode(sourceVolume, sourceFilePath)
        colorTableName = colorTable.GetName()
        slicer.util.saveNode(colorTable, os.path.join(repoDir, colorTableName) + ".csv")

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
        repo = self.git.Repo.init(repoDir, initial_branch='main')

        repoFileNames = [
            "README.md",
            "LICENSE.txt",
            "MorphoDepotAccession.json",
            f"{colorTableName}.csv",
        ]
        repoFilePaths = [os.path.join(repoDir, fileName) for fileName in repoFileNames]
        repo.index.add(repoFilePaths)
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
        fp = open(os.path.join(repoDir, "source_volume"), "w")
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

