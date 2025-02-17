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
# MorphoDepotAccession
#

class MorphoDepotAccession(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("MorphoDepotAccession")
        self.parent.categories = [translate("qSlicerAbstractCoreModule", "SlicerMorph")]
        self.parent.dependencies = ["MorphoDepot"]
        self.parent.contributors = ["Steve Pieper (Isomics, Inc.)"]
        self.parent.helpText = _("""
This module is the client side review tool of the MorphoDepotAccession collaborative segmentation tool.
""")
        self.parent.acknowledgementText = _("""
This was developed as part of the SlicerMorhpCloud project funded by the NSF.
This file was originally developed by Jean-Christophe Fillion-Robin, Kitware Inc., Andras Lasso, PerkLab,
and Steve Pieper, Isomics, Inc. and was partially funded by NIH grant 3P41RR013218-12S1.
""")


#
# MorphoDepotAccessionWidget
#

class MorphoDepotAccessionWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
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

        try:
            import pygbif
        except ModuleNotFoundError:
            slicer.util.showStatusMessage("Installing pygbif package...")
            slicer.util.pip_install("pygbif")
            import pygbif

        # Load widget from .ui file (created by Qt Designer).
        # Additional widgets can be instantiated manually and added to self.layout.
        uiWidget = slicer.util.loadUI(self.resourcePath("UI/MorphoDepotAccession.ui"))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)

        # Set scene in MRML widgets. Make sure that in Qt designer the top-level qMRMLWidget's
        # "mrmlSceneChanged(vtkMRMLScene*)" signal in is connected to each MRML widget's.
        # "setMRMLScene(vtkMRMLScene*)" slot.
        uiWidget.setMRMLScene(slicer.mrmlScene)

        # Uses MorphoDepot logic and widget so all related methods are together
        ghProgressMethod = lambda message : MorphoDepot.MorphoDepotWidget.ghProgressMethod(None, message)
        self.logic = MorphoDepot.MorphoDepotLogic(ghProgressMethod)

        self.ui.createRepository.enabled = False

        # set up WebWidget with schemaform
        self.accessionLayout = qt.QVBoxLayout()
        self.ui.accessionCollapsibleButton.setLayout(self.accessionLayout)

        self.form = MorphoDepotAccessionForm(validationCallback = lambda valid, w=self.ui.createRepository: w.setEnabled(valid))
        slicer.modules.form = self.form
        self.accessionLayout.addWidget(self.form.topWidget)
        self.form.showSection(1)

        # Connections
        self.ui.createRepository.clicked.connect(self.onCreateRepository)

    def onCreateRepository(self):
        slicer.util.showStatusMessage(f"Creating...")
        accessionData = self.form.jsonData()
        print(accessionData)


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

        # section 1
        layout = self.sectionWidgets[1].layout()
        self.question1_1 = FormRadioQuestion("Is your data from a commercially acquired organism or from an accessioned specimen (i.e., from a natural history collection)?", ["Commercially acquired", "Accessioned specimen"], self.validateForm)
        layout.addWidget(self.question1_1.questionBox)

        # section 2
        layout = self.sectionWidgets[2].layout()
        self.question2_1 = FormRadioQuestion("Is your specimen's species in the iDigBio database?", ["Yes", "No"], self.validateForm)
        layout.addWidget(self.question2_1.questionBox)
        self.gotoiDigBioButton = qt.QPushButton("Open iDigBio")
        self.gotoiDigBioButton.connect("clicked()", lambda : qt.QDesktopServices.openUrl(qt.QUrl("https://iDigBio.org")))
        layout.addWidget(self.gotoiDigBioButton)
        self.question2_2 = FormTextQuestion("Enter URL from iDigBio:", self.validateForm)
        self.question2_2.questionBox.toolTip = "Go to iDigBio portal, search for the specimen, click the link and paste the URL below (it should look something like this: https://www.idigbio.org/portal/records/b328320d-268e-4bfc-ae70-1c00f0891f89)"
        layout.addWidget(self.question2_2.questionBox)

        # section 3
        layout = self.sectionWidgets[3].layout()
        self.question3_1 = FormTextQuestion("What is your specimen's species?", self.validateForm)
        layout.addWidget(self.question3_1.questionBox)
        self.gotoGBIFButton = qt.QPushButton("Open GBIF")
        self.gotoGBIFButton.connect("clicked()", lambda : qt.QDesktopServices.openUrl(qt.QUrl("https://gbif.org")))
        layout.addWidget(self.gotoGBIFButton)
        self.question3_2 = FormRadioQuestion("What is your specimen's sex?", ["Male", "Female", "Unknown"], self.validateForm)
        layout.addWidget(self.question3_2.questionBox)
        self.question3_3 = FormRadioQuestion("What is your specimen's developmental stage?", ["Prenatal (fetus, embryo)", "Juvenile (neonatal to subadult)", "Adult"], self.validateForm)
        layout.addWidget(self.question3_3.qButtonuestionBox)

        # section 4
        layout = self.sectionWidgets[4].layout()
        self.question4_1 = FormRadioQuestion("What is the modality of the acquisition?", ["Micro CT (or synchrotron)", "Medical CT", "MRI", "Lightsheet microscopy", "3D confocal microscopy", "Surface model (photogrammetry, structured light, or laser scanning"], self.validateForm)
        layout.addWidget(self.question4_1.questionBox)
        self.question4_2 = FormRadioQuestion("Is there contrast enhancement treatment applied to the specimen (iodine, phosphotungstenic acid, gadolinium, casting agents, etc)?", ["Yes", "No"], self.validateForm)
        layout.addWidget(self.question4_2.questionBox)
        self.question4_3 = FormRadioQuestion("What is in the image?", ["Whole specimen", "Partial specimen"], self.validateForm)
        layout.addWidget(self.question4_3.questionBox)

        # section 5
        layout = self.sectionWidgets[5].layout()
        self.question5_1 = FormCheckBoxesQuestion("What anatomical area(s) is/are present in the scan?", ["Head and neck (e.g., cranium, mandible, proximal vertebral colum)", "Pectoral girdle", "Forelimb", "Trunk (e.g. body cavity, torso, spine, ribs)", "Pelvic girdle", "Hind limg", "Tail", "Other"], self.validateForm)
        layout.addWidget(self.question5_1.questionBox)

        # section 6
        layout = self.sectionWidgets[6].layout()
        self.question6_1 = FormCheckBoxesQuestion("Acknowledgement:", ["I have the right to allow redistribution of this data."], self.validateForm)
        layout.addWidget(self.question6_1.questionBox)
        self.question6_2 = FormRadioQuestion("Choose a license:", ["CC BY 4.0 (requires attribution, allows commercial usage)", "CC BY-NC 4.0 (requires attribution, non-commercial usage only)"], self.validateForm)
        layout.addWidget(self.question6_2.questionBox)

        # section 7
        layout = self.sectionWidgets[7].layout()
        self.question7_1 = FormTextQuestion("What should the repository in your github account called? This needs to be unique value for your account.", self.validateForm)
        layout.addWidget(self.question7_1.questionBox)

    def showSection(self, section):
        if self.workflowMode:
            for sectionWidget in self.sectionWidgets.values():
                sectionWidget.hide()
            self.sectionWidgets[section].show()

    def validateForm(self, arguments=None):
        # first, update the visibility of dependent sections
        if self.question1_1.answer() == "Commercially acquired":
            self.sectionWidgets[2].hide()
            self.sectionWidgets[3].show()
        else:
            self.sectionWidgets[2].show()
            if self.question2_1.answer() == "Yes":
                self.question2_2.questionBox.show()
                self.sectionWidgets[3].hide()
            else:
                self.question2_2.questionBox.hide()
                self.sectionWidgets[3].show()
        if self.question4_3.answer() == "Partial specimen":
            self.sectionWidgets[5].show()
        else:
            self.sectionWidgets[5].hide()

        # then check if required elements have been filled out
        valid = True
        section3Required = False
        if self.question1_1.answer() == "":
            valid = False
        if self.question1_1.answer() == "Commercially acquired":
            section3Required = True
        elif self.question1_1.answer() == "Accessioned specimen":
            if self.question2_1.answer() == "No":
                section3Required = True
            elif self.question2_1.answer() == "Yes":
                section3Required = False
                if self.question2_2.answer() == "":
                    valid = False
        else:
            valid = False
        if section3Required:
            valid = valid and self.question3_1.answer() != ""
            valid = valid and self.question3_2.answer() != ""
            valid = valid and self.question3_3.answer() != ""
        valid = valid and self.question4_1.answer() != ""
        valid = valid and self.question4_2.answer() != ""
        valid = valid and self.question4_3.answer() != ""
        if self.question4_3.answer() == "Partial specimen":
            valid = valid and self.question5_1.answer() != []
        valid = valid and self.question6_1.answer() != ""
        valid = valid and self.question6_2.answer() != ""
        valid = valid and self.question7_1.answer() != ""

        self.validationCallback(valid)

    def data(self):
        data = {}
        data[self.question1_1.questionText.document.toPlainText()] = self.question1_1.answer()
        data[self.question2_1.questionText.document.toPlainText()] = self.question2_1.answer()
        data[self.question2_2.questionText.document.toPlainText()] = self.question2_2.answer()
        data[self.question3_1.questionText.document.toPlainText()] = self.question3_1.answer()
        data[self.question3_2.questionText.document.toPlainText()] = self.question3_2.answer()
        data[self.question3_3.questionText.document.toPlainText()] = self.question3_3.answer()
        data[self.question4_1.questionText.document.toPlainText()] = self.question4_1.answer()
        data[self.question4_2.questionText.document.toPlainText()] = self.question4_2.answer()
        data[self.question4_3.questionText.document.toPlainText()] = self.question4_3.answer()
        data[self.question5_1.questionText.document.toPlainText()] = self.question5_1.answer()
        data[self.question6_1.questionText.document.toPlainText()] = self.question6_1.answer()
        data[self.question6_2.questionText.document.toPlainText()] = self.question6_2.answer()
        data[self.question7_1.questionText.document.toPlainText()] = self.question7_1.answer()
        return data


class BaseQuestion():
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

class FormRadioQuestion(BaseQuestion):
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


class FormCheckBoxesQuestion(BaseQuestion):
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

class FormTextQuestion(BaseQuestion):
    def __init__(self, question, validator):
        super().__init__(question)
        self.answerText = qt.QLineEdit()
        self.answerText.connect("textChanged(QString)", validator)
        self.questionLayout.addWidget(self.answerText)

    def answer(self):
        return self.answerText.text


#
# MorphoDepotAccessionLogic
#


class MorphoDepotAccessionLogic(ScriptedLoadableModuleLogic):
    """
    No logic here - rely on MorphoDepot logic
    """

    def __init__(self) -> None:
        """Called when the logic class is instantiated. Can be used for initializing member variables."""
        ScriptedLoadableModuleLogic.__init__(self)


#
# MorphoDepotAccessionTest
#


class MorphoDepotAccessionTest(ScriptedLoadableModuleTest):
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
        self.test_MorphoDepotAccession1()

    def test_MorphoDepotAccession1(self):
        """
        No testing here because it's very hard to test the server side
        """
        self.delayDisplay("Starting the test")
        self.delayDisplay("Test passed")
